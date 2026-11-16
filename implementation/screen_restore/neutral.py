
import itertools
from . import core
from .local import LocalDeleteState
from .lazy_pairs import find21


def dependency_changed_roots(origin, trial, x, u, clock=None):
    core.check(clock)
    a, b, stats = (origin.base, trial.base, trial.stats)
    if trial.adj is not origin.adj:
        if len(trial.adj) != len(origin.adj):
            raise ValueError("neutral dependencies cannot cross physical graphs")
        for left, right in zip(origin.adj, trial.adj):
            core.check(clock)
            if left != right:
                raise ValueError("neutral dependencies cannot cross physical graphs")
    if x in a.cut or u not in a.cut or b.cut != a.cut - {u} | {x}:
        raise ValueError("dependencies require exactly one declared neutral swap")
    old_roots = set(a.signatures[u])
    old_roots.add(a.owner[x])
    changed_endpoints = {x}
    for root in old_roots:
        core.check(clock)
        boundary = origin.incidence.get(root, ())
        stats["neutral40_dependency_old_incidents"] += len(boundary)
        changed_endpoints.update(boundary)
    for w in origin.adj[u]:
        core.check(clock)
        stats["neutral40_dependency_restored_adjacency"] += 1
        if w in b.cut:
            changed_endpoints.add(w)
    changed_endpoints.discard(u)
    roots = {b.owner[u]}
    for v in origin.adj[x]:
        core.check(clock)
        stats["neutral40_dependency_deleted_adjacency"] += 1
        if v not in b.cut:
            roots.add(b.owner[v])
    for w in changed_endpoints:
        core.check(clock)
        if w in b.cut:
            roots.update(b.signatures[w])
            stats["neutral40_dependency_current_incidents"] += len(b.signatures[w])
    core.check(clock)
    stats["neutral40_dependency_endpoints"] += len(changed_endpoints)
    stats["neutral40_dependency_roots_scheduled"] += len(roots)
    stats["neutral40_dependency_roots_preserved"] += len(b.members) - len(roots)
    return frozenset(roots)


def find21_in_roots(state, cap, roots, lazy=True, clock=None, *, store=None):
    if type(cap) is not int or cap < 1 or type(lazy) is not bool:
        raise ValueError("positive integer cap and boolean lazy required")
    core.check(clock)
    roots = frozenset(roots)
    if not roots <= state.base.members.keys():
        raise ValueError("unknown current component root")
    stats, base = (state.stats, state.base)
    state._cap = cap
    candidates, splitters = ({}, [])
    for root in sorted(roots):
        core.check(clock)
        cand = state._candidates(root, cap, clock)
        if len(cand) < 2:
            stats["neutral40_descendant_ineligible_roots"] += 1
            continue
        candidates[root] = cand
        splitters.extend(base.members[root])
        if not lazy:
            index = state._index(root, clock)
            for endpoint in state.incidence.get(root, ()):
                core.check(clock)
                index.attachment_positions(endpoint, clock)
            stats["eager_components_prepared"] += 1
    core.check(clock)
    splitters.sort()
    core.check(clock)
    for x in splitters:
        core.check(clock)
        root = base.owner[x]
        cand = candidates[root]
        stats["splitters_21_tested"] += 1
        stats["neutral40_descendant_splitters"] += 1
        if store is None:
            sizes, signatures, masses = state.trial(x, cap, clock)
            rescued = [endpoint for endpoint in cand if masses[endpoint] <= cap]
        else:
            sizes, signatures, masses, rescued = store.post_trial(
                state, (root,), (x,), cand, lazy, None, clock
            )
        for a, b in itertools.combinations(rescued, 2):
            core.check(clock)
            stats["quotient_21_checks"] += 1
            sa, sb = (signatures[a], signatures[b])
            small, other = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
            shared = 0
            for token in small:
                core.check(clock)
                stats["neutral40_descendant_signature_entries"] += 1
                if token in other:
                    shared += sizes[token]
            load = (
                masses[a] + masses[b] - shared
                if b in state.adj[a] or shared
                else max(masses[a], masses[b])
            )
            if load <= cap:
                core.check(clock)
                return dict(kind="21", restore=[a, b], delete=[x], affected_load=load)
    core.check(clock)
    stats["neutral40_descendant_selected_scan_complete"] += 1
    return None


def find_neutral_escape(
    state,
    cap,
    lazy=True,
    clock=None,
    *,
    store=None,
    shed_priority=True,
    large_component_first=False,
    large_threshold=35,
    max_trials=None,
    descendant_lazy21=True,
    incremental_trial_state=False,
    localized_descendants=False,
    prior_pair_closed=False
):
    if type(cap) is not int or cap < 1:
        raise ValueError("positive integer cap required")
    switches = (
        lazy,
        shed_priority,
        large_component_first,
        descendant_lazy21,
        incremental_trial_state,
        localized_descendants,
        prior_pair_closed,
    )
    if any((type(value) is not bool for value in switches)):
        raise ValueError("boolean ordering/implementation switches required")
    if type(large_threshold) is not int or large_threshold < 1:
        raise ValueError("large threshold must be a positive integer")
    if max_trials is not None and (type(max_trials) is not int or max_trials < 0):
        raise ValueError("neutral limit must be nonnegative or None")
    core.check(clock)
    for size in state.base.sizes.values():
        core.check(clock)
        if size > cap:
            raise ValueError("neutral search requires a feasible origin")
    if not core._is_saturated(state.base, cap, clock):
        raise ValueError("ranked neutral search requires an RG-saturated origin")
    original = frozenset(state.base.cut)
    base, stats = (state.base, state.stats)

    def feasible_at(root, x):
        core.check(clock)
        candidates = state._candidates(root, cap, clock)
        size = base.sizes[root]
        if store is None:
            _, _, masses = state.trial(x, cap, clock)
        for u in candidates:
            core.check(clock)
            if store is None:
                shed = base.masses[u] - masses[u]
                feasible = masses[u] <= cap
            else:
                shed, _ = store.response(state, root, x, u, lazy, clock)
                feasible = base.masses[u] - shed <= cap
            stats["neutral_exact_response_checks"] += 1
            if feasible:
                stats["neutral_generated_candidates"] += 1
                if size == 1:
                    stats["neutral_singleton_candidates"] += 1
                yield (x, u, shed, size)

    def id_order():
        for x in range(len(state.adj)):
            core.check(clock)
            if x not in original:
                yield from feasible_at(base.owner[x], x)

    ranked = shed_priority or large_component_first
    if ranked:
        menu = []
        for root in sorted(state.incidence):
            core.check(clock)
            if state._candidates(root, cap, clock):
                for x in sorted(base.members[root]):
                    core.check(clock)
                    menu.extend(feasible_at(root, x))
        stats["neutral_candidate_menu_size"] += len(menu)
        core.check(clock)
        menu.sort(
            key=lambda item: (
                -int(item[3] > large_threshold) if large_component_first else 0,
                -item[2] if shed_priority else 0,
                -item[3] if large_component_first else 0,
                item[0],
                item[1],
            )
        )
        core.check(clock)
    else:
        menu = id_order()
    trial = None
    for position, (x, u, shed, size) in enumerate(menu):
        core.check(clock)
        if max_trials is not None and position >= max_trials:
            stats["neutral_limit_reached"] += 1
            stats["neutral_candidates_unattempted"] += len(menu) - position if ranked else 1
            if not ranked:
                stats["neutral_unattempted_count_is_lower_bound"] += 1
            return None
        stats["neutral_branches_started"] += 1
        neutral = set(original) - {u} | {x}
        if incremental_trial_state:
            if trial is None:
                trial = LocalDeleteState(state.adj, neutral, clock, stats)
                stats["neutral40_trial_state_initializations"] += 1
            else:
                stats["neutral40_trial_state_reuses"] += 1
                trial.update(neutral, clock)
                stats["neutral40_trial_state_updates"] += 1
        else:
            trial = LocalDeleteState(state.adj, neutral, clock, stats)
            stats["neutral40_trial_state_initializations"] += 1
        initial_rg = core._rg(trial, cap, clock)
        move, subsequent_rg = (None, [])
        if len(trial.base.cut) >= len(original):
            local = localized_descendants and prior_pair_closed
            if local and (
                trial.base.cut != neutral or not core._is_saturated(trial.base, cap, clock)
            ):
                local = False
                stats["neutral40_dependency_precondition_fallbacks"] += 1
            if local:
                roots = dependency_changed_roots(state, trial, x, u, clock)
                stats["neutral40_dependency_localized_trials"] += 1
                move = find21_in_roots(trial, cap, roots, lazy, clock)
            else:
                if localized_descendants and (not prior_pair_closed):
                    stats["neutral40_dependency_no_closure_fallbacks"] += 1
                history = core.SafeHistory(state.adj, False, stats, cap)
                if descendant_lazy21:
                    move = find21(trial, cap, history, False, lazy, clock)
                else:
                    move = core._find21(trial, cap, history, False, lazy, clock)
            if move is None:
                continue
            trial.update(trial.base.cut - set(move["restore"]) | set(move["delete"]), clock)
            subsequent_rg = core._rg(trial, cap, clock)
        if len(trial.base.cut) < len(original):
            core.check(clock)
            stats["neutral_strict_improvements_found"] += 1
            return dict(
                kind="neutral_then_repair",
                restore=sorted(original - trial.base.cut),
                delete=sorted(trial.base.cut - original),
                neutral_restore=u,
                neutral_delete=x,
                neutral_shed=shed,
                neutral_component_size=size,
                neutral_menu_position=position,
                neutral_initial_rg=list(initial_rg),
                neutral_descendant_move=move,
                neutral_descendant_rg=list(subsequent_rg),
            )
    core.check(clock)
    stats["neutral_declared_menu_exhausted"] += 1
    return None
