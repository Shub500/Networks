
import copy
from . import core
from . import batch_core as previous
from . import scan as scan

cached_lazy_find21 = previous.cached_lazy_find21


def _gain(move):
    return len(move["restore"]) - len(move["delete"]) if move else 0


def select_batch(state, proposals, cap, mode, clock, *, pack_limit=None, offer=None):
    best = previous._select_batch(state, proposals, cap, mode, clock)
    if pack_limit is None or not best:
        return best
    if mode not in ("independent", "local_preserving"):
        raise ValueError("exact packing requires a pairwise sufficient guard")
    if type(pack_limit) is not int or not 1 <= pack_limit <= 16:
        raise ValueError("packing limit must be an integer in [1,16]")
    if len(proposals) > pack_limit:
        state.stats["packing_large_menu_greedy_fallbacks"] += 1
        return best
    if offer is not None:
        offer(copy.deepcopy(best))
    n = len(proposals)
    weights = [_gain(p["move"]) for p in proposals]
    neighbors = [
        previous._neighbor_union(state.adj, p["restored"], clock, state.stats)
        for p in proposals
    ]
    conflicts = [0] * n
    for i, a in enumerate(proposals):
        for j in range(i + 1, n):
            core.check(clock)
            b = proposals[j]
            good = (
                a["restored"].isdisjoint(b["restored"])
                and a["footprint"].isdisjoint(b["footprint"])
                and neighbors[i].isdisjoint(b["restored"])
            )
            if good and mode == "local_preserving":
                good = (
                    a["footprint"].isdisjoint(b["environment"])
                    and b["footprint"].isdisjoint(a["environment"])
                    and a["restored"].isdisjoint(b["candidates"])
                    and b["restored"].isdisjoint(a["candidates"])
                    and neighbors[i].isdisjoint(b["candidates"])
                    and neighbors[j].isdisjoint(a["candidates"])
                )
            state.stats["packing_pair_checks"] += 1
            if not good:
                conflicts[i] |= 1 << j
                conflicts[j] |= 1 << i
    best_gain = _gain(best)

    def visit(available, chosen, gain):
        nonlocal best, best_gain
        core.check(clock)
        state.stats["packing_search_nodes"] += 1
        upper = gain + sum((weights[i] for i in range(n) if available & 1 << i))
        if upper <= best_gain:
            state.stats["packing_gain_bound_prunes"] += 1
            return
        if gain > best_gain:
            candidate = previous._select_batch(
                state, [proposals[i] for i in chosen], cap, mode, clock
            )
            if _gain(candidate) != gain:
                raise AssertionError("pairwise compatible subset lost additive gain")
            candidate["packing_scope"] = "bounded_current_menu_search"
            candidate["packing_search_completed"] = False
            candidate["packing_menu_size"] = n
            candidate["packing_limit"] = pack_limit
            candidate["selection_policy"] = "bounded_exact_gain_compatible_root_moves"
            best, best_gain = (candidate, gain)
            state.stats["packing_strict_improvements"] += 1
            if offer is not None:
                offer(copy.deepcopy(candidate))
        if not available:
            return
        bit = available & -available
        i = bit.bit_length() - 1
        rest = available ^ bit
        visit(rest & ~conflicts[i], chosen + (i,), gain + weights[i])
        visit(rest, chosen, gain)

    visit((1 << n) - 1, (), 0)
    core.check(clock)
    best = copy.deepcopy(best)
    best.update(
        packing_scope="bounded_current_menu_search",
        packing_search_completed=True,
        packing_menu_size=n,
        packing_limit=pack_limit,
    )
    state.stats["packing_exact_menus_completed"] += 1
    return best


class _CollectedEnough(Exception):
    pass


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
    batch_mode="off",
    root_local_bounds=False,
    root_quota=None,
    stream_interval=None,
    pack_limit=None,
    defer_family_keys=False
):
    if batch_mode not in (
        "off",
        "collect_only",
        "independent",
        "local_preserving",
        "physical",
    ):
        raise ValueError("unknown batch_mode")
    if batch_mode != "off" and (not rollout):
        raise ValueError("batch collection requires rollout")
    if type(root_local_bounds) is not bool:
        raise ValueError("root_local_bounds must be boolean")
    for name, value in (
        ("root_quota", root_quota),
        ("stream_interval", stream_interval),
        ("pack_limit", pack_limit),
    ):
        if value is not None and (type(value) is not int or value < 1):
            raise ValueError(name + " must be a positive integer or None")
    if pack_limit is not None and pack_limit > 16:
        raise ValueError("packing limit cannot exceed 16")
    if (
        root_local_bounds or root_quota or stream_interval or pack_limit
    ) and batch_mode not in ("independent", "local_preserving"):
        raise ValueError("collector refinements need an independent compatibility guard")
    if root_local_bounds and branch_offer is not None:
        raise ValueError("root-only bounds cannot preserve a complete branch-offer ledger")
    if branch_offer is not None and (not callable(branch_offer)):
        raise ValueError("branch_offer must be callable")
    collected, scores, compiled, family_cache = ({}, {}, {}, {})
    best_seen_batch, last_stream_count = (None, 0)
    saturated = None

    def collect_batch():
        nonlocal saturated, best_seen_batch
        if saturated is None:
            saturated = core._is_saturated(state.base, cap, clock)
        for root, move in collected.items():
            core.check(clock)
            if root not in compiled or compiled[root]["move"] != move:
                compiled[root] = previous._compile_local(
                    state, root, move, cap, clock, saturated, family_cache
                )
        candidate = select_batch(
            state,
            list(compiled.values()),
            cap,
            batch_mode,
            clock,
            pack_limit=pack_limit,
            offer=offer,
        )
        if candidate is not None and _gain(candidate) > _gain(best_seen_batch):
            best_seen_batch = copy.deepcopy(candidate)
        return best_seen_batch

    def observe(move):
        nonlocal last_stream_count
        core.check(clock)
        root = state.base.owner[move["delete"][0]]
        score = tuple(move["selection_score"])
        if root not in scores or score > scores[root]:
            collected[root], scores[root] = (copy.deepcopy(move), score)
            state.stats["batch_completed_root_records"] += 1
        if branch_offer is not None:
            branch_offer(copy.deepcopy(move))
        if stream_interval and len(collected) >= last_stream_count + stream_interval:
            batch = collect_batch()
            last_stream_count = len(collected)
            state.stats["batch_prefix_publication_attempts"] += 1
            if batch is not None and offer is not None:
                offer(copy.deepcopy(batch))
        if root_quota and len(collected) >= root_quota:
            state.stats["batch_proposal_quota_stops"] += 1
            raise _CollectedEnough()
        core.check(clock)

    partial = False
    try:
        best = scan.find21(
            state,
            cap,
            history,
            rollout,
            lazy,
            clock,
            offer,
            store=store,
            cardinality_bounds=(
                cardinality_bounds if batch_mode == "off" else root_local_bounds
            ),
            root_local_bounds=root_local_bounds,
            defer_family_keys=defer_family_keys,
            slack_ties=slack_ties,
            component_priority=component_priority,
            incremental_quotient=incremental_quotient,
            incident_rollout=incident_rollout,
            defer_unused_warmup=defer_unused_warmup,
            branch_offer=branch_offer if batch_mode == "off" else observe,
            private_mass_history=private_mass_history,
        )
    except _CollectedEnough:
        partial = True
        best = max(collected.values(), key=lambda m: tuple(m["selection_score"]))
    core.check(clock)
    if batch_mode == "off":
        return best
    state.stats["batch_distinct_completed_roots"] += len(collected)
    state.stats["batch_prefix_scans" if partial else "batch_completed_scans"] += 1
    if batch_mode == "collect_only" or best is None:
        return best
    batch = collect_batch()
    core.check(clock)
    if batch is None or _gain(batch) < _gain(best):
        return best
    if partial:
        batch["collection_scope"] = "completed_proposal_prefix_not_family_closure"
        batch["collection_root_quota"] = root_quota
    return batch
