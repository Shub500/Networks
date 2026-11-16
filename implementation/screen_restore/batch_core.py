
import copy
import itertools
from . import core


def cached_lazy_find21(
    state, cap, history, rollout=False, lazy=True, clock=None, offer=None, *, store
):
    if rollout:
        raise ValueError("cached lazy first-improvement does not implement rollout")
    if type(cap) is not int or cap < 1 or type(lazy) is not bool:
        raise ValueError("positive integer cap and boolean lazy required")
    if not isinstance(history, core.SafeHistory):
        raise TypeError("requires dependency-complete SafeHistory")
    if store is None:
        raise ValueError("cached lazy first-improvement requires a response store")
    core.check(clock)
    history.bind(cap, state.adj, clock)
    store.bind(state, clock)
    state._cap = cap
    base, stats, families = (state.base, state.stats, {})
    for x in range(len(state.adj)):
        core.check(clock)
        if x in base.cut:
            continue
        root = base.owner[x]
        if root not in families:
            candidates = state._candidates(root, cap, clock)
            key = core.family_key(("21", cap), base, (root,), candidates)
            skip = len(candidates) < 2 or history.can_skip(
                key, candidates, base, (root,), clock
            )
            families[root] = dict(
                candidates=candidates, key=key, skipped=skip, pending=len(base.members[root])
            )
            stats["cached_lazy21_families_visited"] += 1
        family = families[root]
        if family["skipped"]:
            stats["cached_lazy21_splitters_certified_or_ineligible"] += 1
            continue
        stats["splitters_21_tested"] += 1
        sizes, signatures, masses, rescued = store.post_trial(
            state, (root,), (x,), family["candidates"], lazy, None, clock
        )
        for u, v in itertools.combinations(rescued, 2):
            core.check(clock)
            stats["quotient_21_checks"] += 1
            su, sv = (signatures[u], signatures[v])
            small, other = (su, sv) if len(su) <= len(sv) else (sv, su)
            overlap = 0
            for token in small:
                core.check(clock)
                stats["cached_lazy21_pair_signature_entries"] += 1
                if token in other:
                    overlap += sizes[token]
            load = (
                masses[u] + masses[v] - overlap
                if v in state.adj[u] or overlap
                else max(masses[u], masses[v])
            )
            stats["cached_lazy21_direct_pair_loads"] += 1
            if load <= cap:
                core.check(clock)
                return dict(kind="21", restore=[u, v], delete=[x], affected_load=load)
        family["pending"] -= 1
        if family["pending"] == 0:
            history.record(family["key"], family["candidates"], base, (root,), clock)
    core.check(clock)
    return None


def _neighbor_union(adj, vertices, clock, stats):
    neighbors = set()
    for u in vertices:
        core.check(clock)
        neighbors.update(adj[u])
        stats["batch_guard_adjacency_entries"] += len(adj[u])
    return neighbors


def _compile_local(state, root, move, cap, clock, saturated, family_cache):
    core.check(clock)
    base, stats = (state.base, state.stats)
    restored, deleted = (frozenset(move["restore"]), frozenset(move["delete"]))
    if (
        len(deleted) != 1
        or not restored <= base.cut
        or any((x in base.cut or base.owner[x] != root for x in deleted))
        or (len(restored) <= 1)
        or (move["affected_load"] > cap)
    ):
        raise ValueError("invalid frozen-origin rollout witness")
    if root not in family_cache:
        candidates = frozenset(core._eligible(state, (root,), cap, clock, saturated))
        environment = {root}
        for u in candidates:
            core.check(clock)
            environment.update(base.signatures[u])
            stats["batch_guard_signature_entries"] += len(base.signatures[u])
        family_cache[root] = (candidates, frozenset(environment))
    candidates, environment = family_cache[root]
    if not restored <= candidates:
        raise ValueError("restored endpoints are outside the declared family")
    footprint = {root}
    for u in restored:
        core.check(clock)
        footprint.update(base.signatures[u])
        stats["batch_guard_signature_entries"] += len(base.signatures[u])
    return dict(
        root=root,
        move=copy.deepcopy(move),
        restored=restored,
        deleted=deleted,
        footprint=frozenset(footprint),
        candidates=candidates,
        environment=environment,
    )


def _select_batch(state, proposals, cap, mode, clock):
    stats = state.stats
    ordered = sorted(
        proposals,
        key=lambda p: (
            -(len(p["restored"]) - len(p["deleted"])),
            p["move"]["affected_load"],
            tuple(sorted(p["deleted"])),
            tuple(sorted(p["restored"])),
        ),
    )
    accepted, deferred = ([], [])
    used_u, used_x, feet, envs, candidates = (set(), set(), set(), set(), set())
    restored_neighbors = set()
    current_cut = set(state.base.cut)
    physical_peak = None
    for p in ordered:
        core.check(clock)
        unbrs = set()
        if mode == "physical":
            trial_cut = set(state.base.cut) - (used_u | p["restored"]) | used_x | p["deleted"]
            groups = core.physical_components(state.adj, trial_cut, clock)
            trial_peak = max(map(len, groups), default=0)
            stats["batch_overlap_physical_union_checks"] += 1
            good = trial_peak <= cap and len(trial_cut) < len(current_cut)
        else:
            unbrs = _neighbor_union(state.adj, p["restored"], clock, stats)
            good = (
                p["restored"].isdisjoint(used_u)
                and p["footprint"].isdisjoint(feet)
                and unbrs.isdisjoint(used_u)
            )
        if good and mode == "local_preserving":
            good = (
                p["footprint"].isdisjoint(envs)
                and p["environment"].isdisjoint(feet)
                and p["restored"].isdisjoint(candidates)
                and p["candidates"].isdisjoint(used_u)
                and unbrs.isdisjoint(candidates)
                and restored_neighbors.isdisjoint(p["candidates"])
            )
        stats["batch_proposals_considered"] += 1
        if not good:
            deferred.append(p)
            stats["batch_proposals_deferred"] += 1
            continue
        accepted.append(p)
        used_u.update(p["restored"])
        used_x.update(p["deleted"])
        feet.update(p["footprint"])
        restored_neighbors.update(unbrs)
        if mode == "physical":
            current_cut, physical_peak = (trial_cut, trial_peak)
        if mode == "local_preserving":
            envs.update(p["environment"])
            candidates.update(p["candidates"])
        stats["batch_proposals_accepted"] += 1
    core.check(clock)
    if not accepted:
        return None
    if len(accepted) == 1:
        return copy.deepcopy(accepted[0]["move"])
    gain = len(used_u) - len(used_x)
    if mode != "physical" and gain != sum(
        (len(p["restored"]) - len(p["deleted"]) for p in accepted)
    ):
        raise AssertionError("disjoint batch lost additive gain")
    stats["batch_multi_root_commits_proposed"] += 1
    stats["batch_actual_gain_proposed"] += gain
    if mode != "physical":
        stats["batch_additive_gain_proposed"] += gain
    return dict(
        kind="rollout_batch_k1",
        restore=sorted(used_u),
        delete=sorted(used_x),
        affected_load=(
            physical_peak
            if mode == "physical"
            else max((p["move"]["affected_load"] for p in accepted))
        ),
        batch_mode=mode,
        batch_gain=gain,
        batch_additive=mode != "physical",
        batch_moves=[copy.deepcopy(p["move"]) for p in accepted],
        batch_roots=[p["root"] for p in accepted],
        batch_deferred_roots=[p["root"] for p in deferred],
        origin_cut=sorted(state.base.cut),
        selection_policy="greedy_yield_slack_ids_compatible_root_moves",
    )
