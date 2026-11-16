
from collections import Counter
import math
import time
from . import core
from .local import LocalDeleteState
from .responses import ResponseStore
from .scalar_responses import find32
from .batches import find21 as compiled_find21, cached_lazy_find21
from .lazy_pairs import find21 as lazy_find21
from .history import BoundedSafeHistory, PrivateMassHistory
from .neutral import find_neutral_escape


def resolve_options(options=None):
    defaults = dict(
        class_i=False,
        class_ii=False,
        max_same_component=35,
        rollout=False,
        lazy=True,
        history=True,
        neutral=False,
        response_cache=True,
        bridge_bounds=True,
        pair_priority=False,
        splitter_priority=False,
        profile_dedup=True,
        cardinality_bounds=True,
        slack_ties=False,
        component_priority=False,
        lazy_first_improvement=True,
        cache_21_responses=False,
        skip_certified_rollout_rg=False,
        incremental_rollout_quotient=False,
        grouped_history=False,
        incident_rollout=False,
        defer_unused_warmup=False,
        direct_triple=False,
        response_capacity=None,
        history_limit_records=None,
        history_limit_vertices=None,
        neutral_strategy="legacy",
        neutral_large_first=False,
        neutral_max_trials=None,
        neutral_descendant_lazy=True,
        escape_order="higher_first",
        branch_unpruned_collection=False,
        private_mass_history=False,
        scalar_first=False,
        batch_mode="off",
        rescued_signatures=False,
        batch_root_bounds=False,
        batch_root_quota=None,
        batch_stream_interval=None,
        batch_pack_limit=None,
        defer_family_keys=False,
        incremental_neutral_state=False,
        localized_neutral_descendants=False,
    )
    supplied = dict(options or {})
    if set(supplied) - defaults.keys():
        raise ValueError("unknown engine options: " + repr(set(supplied) - defaults.keys()))
    opts = defaults | supplied
    limit = opts["max_same_component"]
    if limit is not None and (type(limit) is not int or limit < 2):
        raise ValueError("same-component cap must be an integer >=2 or None")
    numeric = (
        "response_capacity",
        "history_limit_records",
        "history_limit_vertices",
        "neutral_max_trials",
        "batch_root_quota",
        "batch_stream_interval",
        "batch_pack_limit",
    )
    for name in numeric:
        value = opts[name]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("nonnegative integer or None required: " + name)
    if opts["neutral_strategy"] not in ("legacy", "quotient_id", "shed"):
        raise ValueError("unknown neutral strategy")
    if opts["escape_order"] not in ("higher_first", "neutral_first"):
        raise ValueError("unknown escape order")
    if opts["batch_mode"] not in (
        "off",
        "collect_only",
        "independent",
        "local_preserving",
        "physical",
    ):
        raise ValueError("unknown batch mode")
    for name in ("batch_root_quota", "batch_stream_interval", "batch_pack_limit"):
        if opts[name] is not None and opts[name] < 1:
            raise ValueError(name + " requires a positive integer")
    if opts["batch_pack_limit"] is not None and opts["batch_pack_limit"] > 16:
        raise ValueError("bounded exact packing limit cannot exceed 16")
    if any(
        (
            opts[name]
            for name in (
                "batch_root_bounds",
                "batch_root_quota",
                "batch_stream_interval",
                "batch_pack_limit",
            )
        )
    ) and opts["batch_mode"] not in ("independent", "local_preserving"):
        raise ValueError(
            "collector refinements require independent or local-preserving batches"
        )
    if opts["rescued_signatures"] and (not (opts["scalar_first"] and opts["response_cache"])):
        raise ValueError("rescued signatures require scalar-first response caching")
    if opts["batch_mode"] != "off" and (not opts["rollout"]):
        raise ValueError("batch collection requires rollout")
    if (opts["incremental_neutral_state"] or opts["localized_neutral_descendants"]) and opts[
        "neutral_strategy"
    ] == "legacy":
        raise ValueError("neutral refinements require quotient neutral strategy")
    if any(
        (opts[k] is not None for k in ("history_limit_records", "history_limit_vertices"))
    ) and (not opts["grouped_history"]):
        raise ValueError("history limits require grouped_history")
    if opts["private_mass_history"] and (not opts["grouped_history"]):
        raise ValueError("private mass transport requires grouped_history")
    if opts["neutral_strategy"] == "legacy" and (
        opts["neutral_large_first"] or opts["neutral_max_trials"] is not None
    ):
        raise ValueError("neutral ranking/limit requires quotient neutral strategy")
    for name, value in opts.items():
        if (
            name
            not in ("max_same_component", "neutral_strategy", "escape_order", "batch_mode")
            + numeric
            and type(value) is not bool
        ):
            raise ValueError("boolean option required: " + name)
    return opts


def run_repair(
    adj,
    cap,
    start,
    options=None,
    budget_seconds=30.0,
    clock=None,
    *,
    candidate_sink=None,
    shared_response_store=None
):
    if (
        isinstance(budget_seconds, bool)
        or not math.isfinite(budget_seconds)
        or budget_seconds < 0
    ):
        raise ValueError("allowance must be finite and nonnegative")
    opts = resolve_options(options)
    limit = opts["max_same_component"]
    if candidate_sink is not None and (not callable(candidate_sink)):
        raise ValueError("candidate_sink must be callable")
    clock = clock or core.ChargedClock(budget_seconds)
    adj = core._validated_graph(adj, cap)
    initial_vertices = tuple(start)
    if any((type(v) is not int or not 0 <= v < len(adj) for v in initial_vertices)):
        raise ValueError("invalid saved cut")
    best = set(initial_vertices)
    stats, phases, phase_cpu, trace, rounds = (Counter(), Counter(), Counter(), [], [])
    initial = core.physical_components(adj, best)
    if max(map(len, initial), default=0) > cap:
        raise ValueError("saved cut is infeasible")
    initial_wall, initial_cpu = clock.elapsed()
    trace.append(
        dict(
            stage="initial_plan",
            before=sorted(best),
            cut=sorted(best),
            deletions=sorted(best),
            removed=len(best),
            restore=[],
            delete=[],
            wall_seconds=0.0,
            cpu_seconds=0.0,
            charged_seconds=0.0,
            admission="verified_input",
        )
    )
    if opts["grouped_history"]:
        history_type = (
            PrivateMassHistory if opts["private_mass_history"] else BoundedSafeHistory
        )
        history = history_type(
            adj,
            opts["history"],
            stats,
            cap,
            max_records=opts["history_limit_records"],
            max_vertex_refs=opts["history_limit_vertices"],
        )
    else:
        history = core.SafeHistory(adj, opts["history"], stats, cap)
    fragments = core.FragmentStore(adj, stats)
    if shared_response_store is not None:
        if not opts["response_cache"]:
            raise ValueError("shared response store requires response_cache")
        store = shared_response_store
        if store.adj != adj:
            raise ValueError("shared response store cannot cross graphs")
        if (
            store.max_components != opts["response_capacity"]
            or store.scalar_first != opts["scalar_first"]
            or store.rescued_signatures != opts["rescued_signatures"]
            or (not store.enabled)
        ):
            raise ValueError("shared response configuration mismatch")
    else:
        store = (
            ResponseStore(
                adj,
                Counter(),
                max_components=opts["response_capacity"],
                scalar_first=opts["scalar_first"],
                rescued_signatures=opts["rescued_signatures"],
                cap=cap,
            )
            if opts["response_cache"]
            else None
        )
    store_before = dict(store.stats) if shared_response_store is not None else {}
    closure = dict(
        rg=False,
        pair=False,
        class_i=False,
        class_ii=False,
        class_ii_max_component=limit,
        unrestricted_32=False,
        neutral=False,
    )
    stop = "time_budget"
    skip_next_rg = False

    def measured(name, function):
        w0, c0 = (time.perf_counter(), time.process_time())
        try:
            return function()
        finally:
            phases[name] += time.perf_counter() - w0
            phase_cpu[name] += time.process_time() - c0

    def publish(proposal, stage, *, allow_equal=False, **details):
        nonlocal best
        core.check(clock)
        candidate = set(proposal)
        if candidate == best or len(candidate) > len(best):
            return False
        if len(candidate) == len(best) and (not allow_equal):
            return False
        before = set(best)
        groups = measured(
            "physical_verification", lambda: core.physical_components(adj, candidate, clock)
        )
        if max(map(len, groups), default=0) > cap:
            raise AssertionError("response evaluator proposed an infeasible cut")
        core.check(clock)
        saved = sorted(candidate)
        event = dict(
            stage=stage,
            before=sorted(before),
            cut=saved,
            deletions=saved,
            removed=len(saved),
            restore=sorted(before - candidate),
            delete=sorted(candidate - before),
            cardinality_change=len(before) - len(candidate),
            **details
        )
        wall, cpu = clock.elapsed()
        event.update(wall_seconds=wall, cpu_seconds=cpu, charged_seconds=max(wall, cpu))
        core.check(clock)
        best = candidate
        trace.append(event)
        stats["accepted_publications"] += 1
        stats[
            "strict_publications" if len(candidate) < len(before) else "tie_publications"
        ] += 1
        for key in ("rg", "pair", "class_i", "class_ii", "unrestricted_32", "neutral"):
            closure[key] = False
        return True

    def scan(name, state, function):
        before_stats = dict(stats)
        before_store = dict(store.stats) if store is not None else {}
        start_cut = sorted(state.base.cut)
        w0, c0 = clock.elapsed()
        outcome, result = ("error", None)
        try:
            result = measured("scan_" + name, function)
            outcome = "complete_move" if result is not None else "complete_no_move"
            return result
        except TimeoutError:
            outcome = "deadline_censored"
            raise
        finally:
            w1, c1 = clock.elapsed()
            rounds.append(
                dict(
                    round=stats["rounds"],
                    start_removed=len(start_cut),
                    start_cut=start_cut,
                    end_incumbent_removed=len(best),
                    scan=name,
                    outcome=outcome,
                    found=result is not None,
                    start_wall_seconds=w0,
                    start_cpu_seconds=c0,
                    end_wall_seconds=w1,
                    end_cpu_seconds=c1,
                    counter_delta={
                        k: v - before_stats.get(k, 0)
                        for k, v in stats.items()
                        if v != before_stats.get(k, 0)
                    },
                    response_counter_delta=(
                        {
                            k: v - before_store.get(k, 0)
                            for k, v in store.stats.items()
                            if v != before_store.get(k, 0)
                        }
                        if store is not None
                        else {}
                    ),
                )
            )

    try:
        core.check(clock)
        if store is not None:
            store.bind_graph(adj, cap, clock)
        state = measured(
            "state_initialization", lambda: LocalDeleteState(adj, best, clock, stats)
        )
        while True:
            core.check(clock)
            stats["rounds"] += 1
            if skip_next_rg:
                stats["rg_saturation_certificates_used"] += 1
                skip_next_rg = False
            else:
                restored = measured("rg", lambda: core._rg(state, cap, clock))
                if restored:
                    publish(state.base.cut, "reverse_greedy")
            closure["rg"] = True
            origin_rg_saturated = True
            search_start = sorted(state.base.cut)

            def offer(candidate):
                proposal = state.base.cut - set(candidate["restore"]) | set(
                    candidate["delete"]
                )
                publish(
                    proposal,
                    candidate["kind"],
                    witness=candidate,
                    search_start=search_start,
                    publication_scope="strict_completed_branch_during_frozen_scan",
                )

            def remember(candidate):
                core.check(clock)
                copied = dict(candidate)
                copied["restore"] = tuple(candidate["restore"])
                copied["delete"] = tuple(candidate["delete"])
                candidate_sink(copied, frozenset(state.base.cut))
                core.check(clock)

            def scan21():
                if opts["lazy_first_improvement"] and (not opts["rollout"]):
                    if opts["cache_21_responses"] and store is not None:
                        return cached_lazy_find21(
                            state, cap, history, False, opts["lazy"], clock, store=store
                        )
                    return lazy_find21(state, cap, history, False, opts["lazy"], clock)
                return compiled_find21(
                    state,
                    cap,
                    history,
                    opts["rollout"],
                    opts["lazy"],
                    clock,
                    offer=offer if opts["rollout"] else None,
                    store=store if opts["cache_21_responses"] else None,
                    cardinality_bounds=opts["cardinality_bounds"]
                    and (
                        not (candidate_sink is not None and opts["branch_unpruned_collection"])
                    ),
                    slack_ties=opts["slack_ties"],
                    component_priority=opts["component_priority"],
                    incremental_quotient=opts["incremental_rollout_quotient"],
                    incident_rollout=opts["incident_rollout"],
                    defer_unused_warmup=opts["defer_unused_warmup"],
                    branch_offer=remember if candidate_sink is not None else None,
                    private_mass_history=opts["private_mass_history"] and opts["history"],
                    batch_mode=opts["batch_mode"],
                    root_local_bounds=opts["batch_root_bounds"],
                    root_quota=opts["batch_root_quota"],
                    stream_interval=opts["batch_stream_interval"],
                    pack_limit=opts["batch_pack_limit"],
                    defer_family_keys=opts["defer_family_keys"],
                )

            move = scan("21", state, scan21)
            if move is None:
                closure["pair"] = True
                order = (
                    ("32", "neutral")
                    if opts["escape_order"] == "higher_first"
                    else ("neutral", "32")
                )
                neutral_limited = False
                for phase in order:
                    if phase == "32" and (opts["class_i"] or opts["class_ii"]):
                        move = scan(
                            "32",
                            state,
                            lambda: find32(
                                state,
                                cap,
                                history,
                                fragments,
                                opts["class_i"],
                                opts["class_ii"],
                                limit,
                                True,
                                opts["lazy"],
                                clock,
                                store=store,
                                bridge_bounds=opts["bridge_bounds"],
                                pair_priority=opts["pair_priority"],
                                splitter_priority=opts["splitter_priority"],
                                profile_dedup=opts["profile_dedup"],
                                direct_triple=opts["direct_triple"],
                            ),
                        )
                        if move is None:
                            closure["class_i"], closure["class_ii"] = (
                                opts["class_i"],
                                opts["class_ii"],
                            )
                            closure["unrestricted_32"] = bool(
                                opts["class_i"]
                                and opts["class_ii"]
                                and (
                                    limit is None
                                    or max(state.base.sizes.values(), default=0) <= limit
                                )
                            )
                    elif phase == "neutral" and opts["neutral"]:
                        before_limits = stats["neutral_limit_reached"]
                        if opts["neutral_strategy"] == "legacy":
                            move = scan(
                                "neutral",
                                state,
                                lambda: core._neutral_escape(state, cap, opts["lazy"], clock),
                            )
                        else:
                            move = scan(
                                "neutral",
                                state,
                                lambda: find_neutral_escape(
                                    state,
                                    cap,
                                    opts["lazy"],
                                    clock,
                                    store=store,
                                    shed_priority=opts["neutral_strategy"] == "shed",
                                    large_component_first=opts["neutral_large_first"],
                                    large_threshold=limit if limit is not None else 35,
                                    max_trials=opts["neutral_max_trials"],
                                    descendant_lazy21=opts["neutral_descendant_lazy"],
                                    incremental_trial_state=opts["incremental_neutral_state"],
                                    localized_descendants=opts[
                                        "localized_neutral_descendants"
                                    ],
                                    prior_pair_closed=closure["pair"],
                                ),
                            )
                        neutral_limited = stats["neutral_limit_reached"] > before_limits
                        closure["neutral"] = move is None and (not neutral_limited)
                    if move is not None:
                        break
                if move is None:
                    core.check(clock)
                    stop = (
                        "declared_menu_limited"
                        if neutral_limited
                        else "declared_menu_exhausted"
                    )
                    break
            proposal = state.base.cut - set(move["restore"]) | set(move["delete"])
            if len(proposal) >= len(state.base.cut) or len(proposal) > len(best):
                raise AssertionError("selected repair did not improve its frozen origin")
            tie = len(proposal) == len(best) and proposal != best
            publish(
                proposal,
                "completed_branch_tie" if tie else move["kind"],
                allow_equal=tie,
                witness=move,
                search_start=sorted(state.base.cut),
                publication_scope="completed_scan_selection",
            )
            if proposal != best:
                raise AssertionError("private search state diverged from published incumbent")
            measured("state_update", lambda: state.update(proposal, clock))
            skip_next_rg = bool(
                opts["skip_certified_rollout_rg"]
                and origin_rg_saturated
                and (move["kind"] == "rollout_k1")
            )
    except TimeoutError:
        stats["deadline_cancellations"] += 1
    store_delta = (
        {
            key: value - store_before.get(key, 0)
            for key, value in store.stats.items()
            if value != store_before.get(key, 0)
        }
        if store is not None
        else {}
    )
    stats.update(store_delta)
    wall, cpu = clock.elapsed()
    return dict(
        cut=sorted(best),
        deletions=sorted(best),
        removed=len(best),
        trace=trace,
        counters=dict(stats),
        status=stop,
        stop=stop,
        closure=closure,
        options=opts,
        round_trace=rounds,
        phase_seconds=dict(phases),
        phase_cpu_seconds=dict(phase_cpu),
        elapsed_wall=wall,
        elapsed_cpu=cpu,
        algorithm_wall_seconds=wall,
        algorithm_cpu_seconds=cpu,
        mandatory_input_validation_wall_seconds=initial_wall,
        mandatory_input_validation_cpu_seconds=initial_cpu,
        charged_seconds=max(wall, cpu),
        budget_seconds=budget_seconds,
        response_store_counters=store_delta,
        response_store_shared=shared_response_store is not None,
    )
