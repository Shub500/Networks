
import copy
import itertools
from . import core
from .quotient import RolloutGroups, small_pair_load


def _can_beat(upper_yield, splitter, best, slack_ties):
    if best is None:
        return True
    best_yield = len(best["restore"]) - 1
    if upper_yield != best_yield:
        return upper_yield > best_yield
    return slack_ties or splitter < best["delete"][0]


def find21(
    state,
    cap,
    history,
    rollout,
    lazy,
    clock,
    offer=None,
    *,
    store=None,
    cardinality_bounds=True,
    slack_ties=False,
    component_priority=False,
    incremental_quotient=False,
    incident_rollout=False,
    defer_unused_warmup=False,
    branch_offer=None,
    private_mass_history=False,
    root_local_bounds=False,
    defer_family_keys=False
):
    for name, value in (
        ("incremental_quotient", incremental_quotient),
        ("incident_rollout", incident_rollout),
        ("defer_unused_warmup", defer_unused_warmup),
        ("private_mass_history", private_mass_history),
        ("root_local_bounds", root_local_bounds),
        ("defer_family_keys", defer_family_keys),
    ):
        if type(value) is not bool:
            raise ValueError(name + " must be boolean")
    if branch_offer is not None and (not callable(branch_offer)):
        raise ValueError("branch_offer must be callable or None")
    if private_mass_history and (
        not callable(getattr(history, "record_private_mass21", None))
    ):
        raise ValueError("private_mass_history requires compatible certified history")
    check = core.check
    base, stats = (state.base, state.stats)
    state._cap = cap
    saturated = core._is_saturated(base, cap, clock)
    if not defer_unused_warmup:
        core._warm_indices(state, sorted(base.members), lazy, clock)
    candidates, keys, skipped, pending = ({}, {}, set(), {})
    found_in_root, bound_pruned = (set(), set())
    splitter_summaries = {}

    def admit_family(root, cand):
        check(clock)
        keys[root] = core.family_key(("21", cap), base, (root,), cand)
        stats["rollout_family_keys_built"] += 1
        stats["rollout_deferred_family_keys_bound"] += int(defer_family_keys)
        if len(cand) < 2 or history.can_skip(keys[root], cand, base, (root,), clock):
            skipped.add(root)

    roots_to_prepare = (
        sorted(state.incidence) if incident_rollout and saturated else sorted(base.members)
    )
    if incident_rollout:
        stats["incident_rollout_nonincident_roots_omitted"] += len(base.members) - len(
            roots_to_prepare
        )
        if not saturated:
            stats["incident_rollout_unsaturated_fallbacks"] += 1
    for root in roots_to_prepare:
        check(clock)
        if incident_rollout and saturated and (len(state.incidence[root]) < 2):
            stats["incident_rollout_short_incidence_roots_omitted"] += 1
            continue
        cand = core._eligible(state, (root,), cap, clock, saturated)
        if incident_rollout and len(cand) < 2:
            stats["incident_rollout_short_candidate_roots_omitted"] += 1
            continue
        candidates[root] = cand
        if not defer_family_keys:
            admit_family(root, cand)
        elif len(cand) < 2:
            skipped.add(root)
        pending[root] = len(base.members[root])
    best, best_score = (None, None)
    root_best = {}
    warmed_roots = set()

    def visit_sequence():
        if not rollout or not component_priority:
            for x in range(len(state.adj)):
                check(clock)
                if (
                    x not in base.cut
                    and base.owner[x] in candidates
                    and (base.owner[x] not in skipped)
                ):
                    yield x
            return
        roots = [r for r in candidates if r not in skipped]
        roots.sort(key=lambda r: (-(len(candidates[r]) - 1), -base.sizes[r], r))
        for index, root in enumerate(roots):
            check(clock)
            upper = len(candidates[root]) - 1
            if cardinality_bounds and (not root_local_bounds) and (best is not None):
                if upper < len(best["restore"]) - 1:
                    tail = roots[index:]
                    bound_pruned.update(tail)
                    stats["rollout_component_bound_roots_skipped"] += len(tail)
                    stats["rollout_component_bound_splitters_skipped"] += sum(
                        (len(base.members[r]) for r in tail)
                    )
                    stats["rollout_component_bound_tail_breaks"] += 1
                    break
                first_x = min(base.members[root])
                if not _can_beat(upper, first_x, best, slack_ties):
                    bound_pruned.add(root)
                    stats["rollout_component_bound_roots_skipped"] += 1
                    stats["rollout_component_bound_splitters_skipped"] += len(
                        base.members[root]
                    )
                    continue
            if root not in keys:
                admit_family(root, candidates[root])
            if root in skipped:
                continue
            for x in sorted(base.members[root]):
                check(clock)
                yield x

    def finish_splitter(root, x=None, summary=None):
        if private_mass_history and summary is not None:
            check(clock)
            splitter_summaries.setdefault(root, {})[x] = summary
            stats["private_margin_completed_splitter_rows"] += 1
        pending[root] -= 1
        if pending[root] == 0 and root not in found_in_root and (root not in bound_pruned):
            history.record(keys[root], candidates[root], base, (root,), clock)
            if private_mass_history:
                check(clock)
                history.record_private_mass21(
                    keys[root],
                    candidates[root],
                    base,
                    root,
                    splitter_summaries.get(root, {}),
                    clock,
                )
        if pending[root] == 0:
            splitter_summaries.pop(root, None)

    for x in visit_sequence():
        check(clock)
        root = base.owner[x]
        cand = candidates[root]
        if root not in keys:
            admit_family(root, cand)
        if root in skipped:
            continue
        comparison_best = root_best.get(root) if root_local_bounds else best
        if (
            rollout
            and cardinality_bounds
            and (not _can_beat(len(cand) - 1, x, comparison_best, slack_ties))
        ):
            bound_pruned.add(root)
            stats["rollout_component_bound_splitters_skipped"] += 1
            stats["root_local_candidate_bound_skips"] += int(root_local_bounds)
            finish_splitter(root)
            continue
        if defer_unused_warmup and root not in warmed_roots:
            core._warm_indices(state, (root,), lazy, clock)
            check(clock)
            warmed_roots.add(root)
        stats["splitters_21_tested"] += 1
        if store is None:
            sizes, signatures, masses, rescued = core._post_trial(
                state, (root,), (x,), cand, lazy, None, clock
            )
        else:
            sizes, signatures, masses, rescued = store.post_trial(
                state, (root,), (x,), cand, lazy, None, clock
            )
        summary = None
        if private_mass_history:
            smallest_single = None
            for u in cand:
                check(clock)
                if masses[u] > cap:
                    excess = masses[u] - cap
                    smallest_single = (
                        excess if smallest_single is None else min(smallest_single, excess)
                    )
            summary = dict(
                candidate_count=len(cand),
                rescued_count=len(rescued),
                evaluated_pairs=0,
                feasible_pairs=0,
                min_single_deficit=smallest_single,
                min_pair_deficit=None,
                complete=True,
            )
        if len(rescued) < 2:
            finish_splitter(root, x, summary)
            continue
        if (
            rollout
            and cardinality_bounds
            and (not _can_beat(len(rescued) - 1, x, comparison_best, slack_ties))
        ):
            bound_pruned.add(root)
            stats["rollout_splitter_cardinality_bound_skips"] += 1
            stats["root_local_rescued_bound_skips"] += int(root_local_bounds)
            finish_splitter(root)
            continue
        best_seed = None
        for u, v in itertools.combinations(rescued, 2):
            check(clock)
            stats["quotient_21_checks"] += 1
            if incremental_quotient:
                load = small_pair_load(state.adj, u, v, signatures, sizes, clock)
                stats["incremental_quotient_pair_checks"] += 1
            else:
                load = core.quotient_load(state.adj, (u, v), signatures, sizes, clock)
            if summary is not None:
                summary["evaluated_pairs"] += 1
                if load <= cap:
                    summary["feasible_pairs"] += 1
                else:
                    deficit = load - cap
                    prior = summary["min_pair_deficit"]
                    summary["min_pair_deficit"] = (
                        deficit if prior is None else min(prior, deficit)
                    )
            if load <= cap:
                found_in_root.add(root)
                if not rollout:
                    return dict(kind="21", restore=[u, v], delete=[x], affected_load=load)
                seed = (load, u, v)
                if best_seed is None or seed < best_seed:
                    best_seed = seed
        if best_seed is not None:
            load, u, v = best_seed
            restored = [u, v]
            groups = (
                RolloutGroups(
                    state.adj, signatures, sizes, (u, v), clock=clock, counters=stats
                )
                if incremental_quotient
                else None
            )
            for w in rescued:
                check(clock)
                if w in restored:
                    continue
                stats["rollout_extension_checks"] += 1
                if groups is None:
                    new_load = core.quotient_load(
                        state.adj, restored + [w], signatures, sizes, clock
                    )
                    accepted = new_load <= cap
                else:
                    accepted, new_load = groups.try_extend(w, cap, clock)
                if accepted:
                    restored.append(w)
                    load = new_load
            gain = len(restored) - 1
            score = (gain, cap - load, -x) if slack_ties else (gain, -x)
            if root not in root_best or score > tuple(root_best[root]["selection_score"]):
                root_best[root] = dict(
                    restore=list(restored), delete=[x], selection_score=list(score)
                )
            if branch_offer is not None:
                check(clock)
                observation = dict(
                    kind="rollout_k1",
                    restore=list(restored),
                    delete=[x],
                    affected_load=load,
                    selection_score=list(score),
                    selected_score=list(score),
                    selection_policy=(
                        "yield_slack_splitter_id" if slack_ties else "yield_splitter_id"
                    ),
                )
                stats["completed_rollout_branch_callbacks"] += 1
                branch_offer(copy.deepcopy(observation))
                check(clock)
            if best_score is None or score > best_score:
                prior_gain = -1 if best is None else len(best["restore"]) - 1
                best_score = score
                best = dict(
                    kind="rollout_k1",
                    restore=restored,
                    delete=[x],
                    affected_load=load,
                    selection_score=list(score),
                    selected_score=list(score),
                    selection_policy=(
                        "yield_slack_splitter_id" if slack_ties else "yield_splitter_id"
                    ),
                )
                if gain > prior_gain:
                    stats["rollout_strict_yield_records"] += 1
                    if offer is not None:
                        offer(best)
                else:
                    stats["rollout_equal_yield_score_records"] += 1
        finish_splitter(root, x, summary)
    check(clock)
    return best
