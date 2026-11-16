
import itertools
from . import core


def find21(state, cap, history, rollout=False, lazy=True, clock=None, offer=None):
    if rollout:
        raise ValueError("lazy first-improvement does not implement rollout")
    if type(cap) is not int or cap < 1 or type(lazy) is not bool:
        raise ValueError("positive integer cap and boolean lazy required")
    if not isinstance(history, core.SafeHistory):
        raise TypeError("requires frozen dependency-complete SafeHistory")
    core.check(clock)
    history.bind(cap, state.adj, clock)
    state._cap = cap
    base, stats = (state.base, state.stats)
    families = {}
    for x in range(len(state.adj)):
        core.check(clock)
        if x in base.cut:
            continue
        root = base.owner[x]
        if root not in families:
            candidates = state._candidates(root, cap, clock)
            key = core.family_key(("21", cap), base, (root,), candidates)
            skipped = len(candidates) < 2 or history.can_skip(
                key, candidates, base, (root,), clock
            )
            families[root] = dict(
                candidates=candidates,
                key=key,
                skipped=skipped,
                pending=len(base.members[root]),
            )
            stats["lazy21_families_visited"] += 1
            if not skipped and (not lazy):
                index = state._index(root, clock)
                for u in state.incidence.get(root, ()):
                    core.check(clock)
                    index.attachment_positions(u, clock)
                stats["eager_components_prepared"] += 1
        family = families[root]
        if family["skipped"]:
            stats["lazy21_splitters_certified_or_ineligible"] += 1
            continue
        stats["splitters_21_tested"] += 1
        sizes, signatures, masses = state.trial(x, cap, clock)
        rescued = []
        for u in family["candidates"]:
            core.check(clock)
            if masses[u] <= cap:
                rescued.append(u)
        for u, v in itertools.combinations(rescued, 2):
            core.check(clock)
            stats["quotient_21_checks"] += 1
            su, sv = (signatures[u], signatures[v])
            small, other = (su, sv) if len(su) <= len(sv) else (sv, su)
            shared = 0
            for token in small:
                core.check(clock)
                stats["lazy21_pair_signature_entries"] += 1
                if token in other:
                    shared += sizes[token]
            load = (
                masses[u] + masses[v] - shared
                if v in state.adj[u] or shared
                else max(masses[u], masses[v])
            )
            stats["lazy21_direct_pair_loads"] += 1
            if load <= cap:
                core.check(clock)
                return dict(kind="21", restore=[u, v], delete=[x], affected_load=load)
        family["pending"] -= 1
        if family["pending"] == 0:
            history.record(family["key"], family["candidates"], base, (root,), clock)
    core.check(clock)
    return None
