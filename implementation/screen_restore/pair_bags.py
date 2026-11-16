
from __future__ import annotations
import heapq
import itertools
import math
import sys
import time
from collections import OrderedDict


class Clock:

    def __init__(self, seconds):
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError("budget_seconds must be finite and nonnegative")
        self.limit = float(seconds)
        self.wall0, self.cpu0 = (time.perf_counter(), time.process_time())

    def elapsed(self):
        return (time.perf_counter() - self.wall0, time.process_time() - self.cpu0)

    def expired(self):
        return max(self.elapsed()) >= self.limit

    def spent(self):
        return max(self.elapsed())


def components(adj, removed=()):
    seen = set(removed)
    answer = []
    for root in range(len(adj)):
        if root in seen:
            continue
        seen.add(root)
        stack, group = ([root], [])
        while stack:
            u = stack.pop()
            group.append(u)
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        answer.append(group)
    return answer


def lcc(adj, removed=()):
    return max(map(len, components(adj, removed)), default=0)


def _validate(adj, cap):
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise ValueError("cap must be a positive integer")
    n = len(adj)
    graph = tuple((frozenset(neighbors) for neighbors in adj))
    for u, neighbors in enumerate(graph):
        for v in neighbors:
            if not isinstance(v, int) or not 0 <= v < n or u == v:
                raise ValueError("invalid neighbor or self loop")
            if u not in graph[v]:
                raise ValueError("graph must be undirected")
    return graph


def reverse_greedy(adj, cap, removed, clock=None, held_deleted=()):
    cut = set(removed)
    held = set(held_deleted)
    if not held <= cut:
        raise ValueError("held_deleted must be contained in the trial deletion set")
    parent = list(range(len(adj)))
    size = [0 if u in cut else 1 for u in range(len(adj))]

    def find(u):
        while parent[u] != u:
            parent[u] = parent[parent[u]]
            u = parent[u]
        return u

    def union(u, v):
        u, v = (find(u), find(v))
        if u != v:
            if size[u] < size[v]:
                u, v = (v, u)
            parent[v] = u
            size[u] += size[v]

    for u in range(len(adj)):
        if u not in cut:
            for v in adj[u]:
                if v not in cut:
                    union(u, v)

    def mass(u):
        return 1 + sum((size[r] for r in {find(v) for v in adj[u] if v not in cut}))

    queue = [(mass(u), u) for u in cut - held]
    heapq.heapify(queue)
    while queue and (not (clock and clock.expired())):
        old, u = heapq.heappop(queue)
        if u not in cut:
            continue
        new = mass(u)
        if new > cap:
            continue
        if new != old:
            heapq.heappush(queue, (new, u))
            continue
        cut.remove(u)
        parent[u], size[u] = (u, 1)
        for v in adj[u]:
            if v not in cut:
                union(u, v)
    return cut


def articulation_loads(adj, bag):
    bag = set(bag)
    local = {u: list(adj[u] & bag) for u in bag}
    tin, low, subtree, separated, largest, roots, totals = ({}, {}, {}, {}, {}, {}, {})
    timer = 0
    for root in bag:
        if root in tin:
            continue
        timer += 1
        tin[root] = low[root] = timer
        subtree[root], separated[root], largest[root], roots[root] = (1, 0, 0, root)
        stack = [[root, None, 0]]
        while stack:
            u, parent, i = stack[-1]
            if i < len(local[u]):
                v = local[u][i]
                stack[-1][2] += 1
                if v == parent:
                    continue
                if v not in tin:
                    timer += 1
                    tin[v] = low[v] = timer
                    subtree[v], separated[v], largest[v], roots[v] = (1, 0, 0, root)
                    stack.append([v, u, 0])
                else:
                    low[u] = min(low[u], tin[v])
            else:
                stack.pop()
                if parent is not None:
                    subtree[parent] += subtree[u]
                    low[parent] = min(low[parent], low[u])
                    if low[u] >= tin[parent]:
                        separated[parent] += subtree[u]
                        largest[parent] = max(largest[parent], subtree[u])
        totals[root] = subtree[root]
    biggest = second = 0
    biggest_root = None
    for root, size in totals.items():
        if size > biggest:
            second, biggest, biggest_root = (biggest, size, root)
        elif size > second:
            second = size
    return {
        u: max(
            largest[u],
            totals[roots[u]] - 1 - separated[u],
            second if roots[u] == biggest_root else biggest,
        )
        for u in bag
    }


def pair_candidate_menu(
    adj, cut, groups, candidate_index="scan", clock=None, telemetry=None, boundary_context=None
):
    if candidate_index not in {"scan", "incidence", "operation_estimate"}:
        raise ValueError("unknown candidate_index")
    owner = {u: i for i, group in enumerate(groups) for u in group}
    sig = {u: {owner[v] for v in adj[u] if v not in cut} for u in cut}
    if boundary_context is not None:
        started = time.perf_counter()
        sizes = list(map(len, groups))
        boundary_context.update(
            sizes=sizes,
            signatures=sig,
            restoration_masses={u: 1 + sum((sizes[i] for i in ids)) for u, ids in sig.items()},
        )
        boundary_context["preparation_seconds"] = time.perf_counter() - started
    degrees = {}
    for ids in sig.values():
        for i in ids:
            degrees[i] = degrees.get(i, 0) + 1
    direct_edges = sum((len(adj[u] & cut) for u in cut)) // 2
    scan_estimate = len(cut) * (len(cut) - 1) // 2
    incidence_estimate = direct_edges + sum((n * (n - 1) // 2 for n in degrees.values()))
    selected = candidate_index
    if selected == "operation_estimate":
        selected = "incidence" if incidence_estimate < scan_estimate else "scan"
    record = dict(
        requested_index=candidate_index,
        selected_index=selected,
        scan_pair_estimate=scan_estimate,
        incidence_proposal_estimate=incidence_estimate,
        signature_incidents=sum(degrees.values()),
        direct_deleted_edges=direct_edges,
        enumeration_proposals=0,
        key_checks=0,
        connected_pairs=0,
        enumeration_complete=False,
    )
    if telemetry is not None:
        telemetry.update(record)
        record = telemetry
    complete = True
    if selected == "scan":
        keys = itertools.combinations(sorted(cut), 2)
    else:
        incidence = {}
        unique = set()
        for u in sorted(cut):
            for i in sig[u]:
                incidence.setdefault(i, []).append(u)
            for v in adj[u] & cut:
                if u < v:
                    unique.add((u, v))
                    record["enumeration_proposals"] += 1
        for ids in incidence.values():
            for pair in itertools.combinations(ids, 2):
                if clock and clock.expired():
                    complete = False
                    break
                unique.add(pair)
                record["enumeration_proposals"] += 1
            if clock and clock.expired():
                complete = False
                break
        keys = sorted(unique)
    pairs = []
    for u, v in keys:
        if clock and clock.expired():
            complete = False
            break
        record["key_checks"] += 1
        if selected == "scan":
            record["enumeration_proposals"] += 1
        if v not in adj[u] and (not sig[u] & sig[v]):
            continue
        ids = sig[u] | sig[v]
        pairs.append((2 + sum((len(groups[i]) for i in ids)), u, v, ids))
    record["connected_pairs"] = len(pairs)
    record["enumeration_complete"] = complete and (not (clock and clock.expired()))
    return pairs


def _validate_pair_options(max_bags, max_moves, candidate_order, candidate_index):
    for name, value in (("max_bags", max_bags), ("max_moves", max_moves)):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{name} must be a nonnegative integer or None")
    if candidate_order not in {"bag_size", "label"}:
        raise ValueError("unknown candidate_order")
    if candidate_index not in {"scan", "incidence", "operation_estimate"}:
        raise ValueError("unknown candidate_index")


def _validate_dead_cache_options(enabled, max_entries, max_bytes):
    if type(enabled) is not bool:
        raise ValueError("dead_bag_cache must be a bool")
    for name, value in (
        ("dead_bag_cache_max_entries", max_entries),
        ("dead_bag_cache_max_bytes", max_bytes),
    ):
        if type(value) is not int or value < 0:
            raise ValueError(f"{name} must be a nonnegative integer")


def _pair_boundary_reason(cap, sizes, sig_u, sig_v, mass_u, mass_v, bag_size, direct_edge):
    if mass_u <= cap or mass_v <= cap:
        return ("unsaturated_fallback", 0)
    common = sig_u & sig_v
    if not common:
        return ("no_shared_component", 0)
    if direct_edge or len(common) > 1:
        impossible = bag_size - max((sizes[i] for i in common)) > cap
    else:
        size = sizes[next(iter(common))]
        impossible = max(mass_u - size, mass_v - size) > cap
    return ("boundary_mass" if impossible else "survives", len(common))


class _DeadBagCache:

    def __init__(self, stats, max_entries, max_bytes):
        self.entries = OrderedDict()
        self.empty_bytes = sys.getsizeof(self.entries)
        self.payload_bytes = 0
        self.max_entries, self.max_bytes, self.stats = (max_entries, max_bytes, stats)
        self.key_vertices = 0

    def lookup(self, u, v, bag, cap):
        started = time.perf_counter()
        key = (min(u, v), max(u, v), frozenset(bag), cap)
        key_bytes = sys.getsizeof(key) + sys.getsizeof(key[2])
        self.stats["dead_cache_key_build_seconds"] += time.perf_counter() - started
        self.stats["dead_cache_key_vertices_built"] += len(bag)
        self.stats["dead_cache_max_key_vertices"] = max(
            self.stats["dead_cache_max_key_vertices"], len(bag)
        )
        self.stats["dead_cache_key_bytes_built"] += key_bytes
        started = time.perf_counter()
        entry = self.entries.get(key)
        self.stats["dead_cache_lookup_seconds"] += time.perf_counter() - started
        self.stats["dead_cache_hits" if entry is not None else "dead_cache_misses"] += 1
        if entry is not None:
            self.stats["dead_cache_dfs_avoided"] += 1
        return (key, entry)

    def _retained_bytes(self):
        return self.payload_bytes + sys.getsizeof(self.entries) - self.empty_bytes

    def remember_dead(self, key, summary):
        started = time.perf_counter()
        payload = sys.getsizeof(key) + sys.getsizeof(key[2]) + sys.getsizeof(summary)
        if not self.max_entries or payload > self.max_bytes:
            self.stats["dead_cache_capacity_skips"] += 1
            self.stats["dead_cache_update_seconds"] += time.perf_counter() - started
            return
        self.entries[key] = summary
        self.payload_bytes += payload
        self.key_vertices += len(key[2])
        self.stats["dead_cache_insertions"] += 1
        while self.entries and (
            len(self.entries) > self.max_entries or self._retained_bytes() > self.max_bytes
        ):
            old_key, old_summary = self.entries.popitem(last=False)
            self.payload_bytes -= (
                sys.getsizeof(old_key) + sys.getsizeof(old_key[2]) + sys.getsizeof(old_summary)
            )
            self.key_vertices -= len(old_key[2])
            self.stats["dead_cache_evictions"] += 1
        if not self.entries:
            self.entries.clear()
        current = self._retained_bytes()
        self.stats["dead_cache_entries"] = len(self.entries)
        self.stats["dead_cache_entries_peak"] = max(
            self.stats["dead_cache_entries_peak"], len(self.entries)
        )
        self.stats["dead_cache_retained_key_vertices"] = self.key_vertices
        self.stats["dead_cache_retained_key_vertices_peak"] = max(
            self.stats["dead_cache_retained_key_vertices_peak"], self.key_vertices
        )
        self.stats["dead_cache_retained_bytes_proxy"] = current
        self.stats["dead_cache_retained_bytes_proxy_peak"] = max(
            self.stats["dead_cache_retained_bytes_proxy_peak"], current
        )
        self.stats["dead_cache_update_seconds"] += time.perf_counter() - started


def pair_exchange(
    adj,
    cap,
    removed,
    clock,
    max_bags=4096,
    max_moves=32,
    acceptance=None,
    candidate_order="bag_size",
    candidate_index="scan",
    dead_bag_cache=False,
    dead_bag_cache_max_entries=4096,
    dead_bag_cache_max_bytes=67108864,
    pair_boundary_screen=False,
):
    _validate_pair_options(max_bags, max_moves, candidate_order, candidate_index)
    _validate_dead_cache_options(
        dead_bag_cache, dead_bag_cache_max_entries, dead_bag_cache_max_bytes
    )
    if type(pair_boundary_screen) is not bool:
        raise ValueError("pair_boundary_screen must be a bool")
    cut = reverse_greedy(adj, cap, removed, clock)
    stats = dict(
        tested_bags=0,
        accepted_moves=0,
        candidate_pairs=0,
        bag_vertices=0,
        bag_edges=0,
        stop="local_menu_exhausted",
        replacement_candidates=0,
        articulation_candidates=0,
        cap_feasible_replacements=0,
        no_cap_separator_bags=0,
        complete_neighborhood_certificates=0,
        enumeration_rounds=[],
        enumeration_proposals=0,
        enumeration_key_checks=0,
        enumeration_scan_rounds=0,
        enumeration_incidence_rounds=0,
        dfs_evaluations=0,
        dfs_bag_vertices=0,
        dfs_bag_edges=0,
        dead_cache_mode="exact_negative" if dead_bag_cache else "off",
        dead_cache_hits=0,
        dead_cache_misses=0,
        dead_cache_dfs_avoided=0,
        dead_cache_insertions=0,
        dead_cache_evictions=0,
        dead_cache_capacity_skips=0,
        dead_cache_late_results_not_stored=0,
        dead_cache_entries=0,
        dead_cache_entries_peak=0,
        dead_cache_key_vertices_built=0,
        dead_cache_max_key_vertices=0,
        dead_cache_key_bytes_built=0,
        dead_cache_retained_key_vertices=0,
        dead_cache_retained_key_vertices_peak=0,
        dead_cache_retained_bytes_proxy=0,
        dead_cache_retained_bytes_proxy_peak=0,
        dead_cache_key_build_seconds=0.0,
        dead_cache_lookup_seconds=0.0,
        dead_cache_update_seconds=0.0,
        pair_boundary_mode="exact_shared_component" if pair_boundary_screen else "off",
        boundary_screen_checks=0,
        boundary_screen_saturation_fallbacks=0,
        boundary_screen_shared_components=0,
        boundary_screen_rejected_bags=0,
        boundary_screen_no_shared_bags=0,
        boundary_screen_mass_bags=0,
        boundary_screen_rejected_bag_vertices=0,
        boundary_screen_rejected_replacement_candidates=0,
        boundary_screen_context_seconds=0.0,
        boundary_screen_query_seconds=0.0,
        boundary_screen_edge_counts_unevaluated_bags=0,
        boundary_screen_articulation_counts_unevaluated_bags=0,
        bag_edges_scope="all_conceptual_bags",
        articulation_candidates_scope="all_conceptual_bags",
    )
    dead_cache = (
        _DeadBagCache(stats, dead_bag_cache_max_entries, dead_bag_cache_max_bytes)
        if dead_bag_cache
        else None
    )
    if acceptance:
        acceptance(cut, "reverse_greedy")
    while not clock.expired():
        if max_moves is not None and stats["accepted_moves"] >= max_moves:
            stats["stop"] = "move_budget"
            break
        groups = components(adj, cut)
        telemetry = {}
        boundary_context = {} if pair_boundary_screen else None
        pairs = pair_candidate_menu(
            adj, cut, groups, candidate_index, clock, telemetry, boundary_context
        )
        if boundary_context is not None:
            stats["boundary_screen_context_seconds"] += boundary_context["preparation_seconds"]
        stats["enumeration_rounds"].append(telemetry)
        stats["enumeration_proposals"] += telemetry["enumeration_proposals"]
        stats["enumeration_key_checks"] += telemetry["key_checks"]
        stats["enumeration_" + telemetry["selected_index"] + "_rounds"] += 1
        if candidate_order == "bag_size":
            pairs.sort(key=lambda row: row[:3])
        elif candidate_order != "label":
            raise ValueError("unknown candidate_order")
        stats["candidate_pairs"] += len(pairs)
        moved = False
        for bag_size, u, v, ids in pairs:
            if clock.expired():
                break
            if max_bags is not None and stats["tested_bags"] >= max_bags:
                stats["stop"] = "pair_budget"
                return (cut, stats)
            if boundary_context is not None:
                started = time.perf_counter()
                sig, masses = (
                    boundary_context["signatures"],
                    boundary_context["restoration_masses"],
                )
                reason, shared = _pair_boundary_reason(
                    cap,
                    boundary_context["sizes"],
                    sig[u],
                    sig[v],
                    masses[u],
                    masses[v],
                    bag_size,
                    v in adj[u],
                )
                stats["boundary_screen_query_seconds"] += time.perf_counter() - started
                stats["boundary_screen_checks"] += 1
                stats["boundary_screen_shared_components"] += shared
                if reason == "unsaturated_fallback":
                    stats["boundary_screen_saturation_fallbacks"] += 1
                elif reason != "survives":
                    stats["boundary_screen_rejected_bags"] += 1
                    stats[
                        (
                            "boundary_screen_no_shared_bags"
                            if reason == "no_shared_component"
                            else "boundary_screen_mass_bags"
                        )
                    ] += 1
                    stats["boundary_screen_rejected_bag_vertices"] += bag_size
                    stats["boundary_screen_rejected_replacement_candidates"] += bag_size - 2
                    stats["boundary_screen_edge_counts_unevaluated_bags"] += 1
                    stats["boundary_screen_articulation_counts_unevaluated_bags"] += 1
                    stats["bag_edges_scope"] = "evaluated_or_cached_bags_only"
                    stats["articulation_candidates_scope"] = "evaluated_or_cached_bags_only"
                    stats["tested_bags"] += 1
                    stats["bag_vertices"] += bag_size
                    stats["replacement_candidates"] += bag_size - 2
                    stats["no_cap_separator_bags"] += 1
                    continue
            bag = {u, v}.union(*(groups[i] for i in ids))
            key, cached = (
                dead_cache.lookup(u, v, bag, cap) if dead_cache is not None else (None, None)
            )
            if cached is None:
                loads = articulation_loads(adj, bag)
                bag_edges = sum((len(adj[x] & bag) for x in bag)) // 2
                articulation_count = sum(
                    (load < len(bag) - 1 for x, load in loads.items() if x not in (u, v))
                )
                valid = [
                    (load, x) for x, load in loads.items() if x not in (u, v) and load <= cap
                ]
                stats["dfs_evaluations"] += 1
                stats["dfs_bag_vertices"] += len(bag)
                stats["dfs_bag_edges"] += bag_edges
            else:
                bag_edges, articulation_count = cached
                valid = []
            stats["tested_bags"] += 1
            stats["bag_vertices"] += len(bag)
            stats["bag_edges"] += bag_edges
            stats["replacement_candidates"] += len(bag) - 2
            stats["articulation_candidates"] += articulation_count
            stats["cap_feasible_replacements"] += len(valid)
            if not valid:
                stats["no_cap_separator_bags"] += 1
                if dead_cache is not None and cached is None:
                    if clock.expired():
                        stats["dead_cache_late_results_not_stored"] += 1
                    else:
                        dead_cache.remember_dead(key, (bag_edges, articulation_count))
                continue
            _, x = min(valid)
            proposed = cut - {u, v} | {x}
            if lcc(adj, proposed) > cap:
                raise AssertionError("affected-bag result failed full-graph verification")
            if clock.expired():
                break
            cut = proposed
            stats["accepted_moves"] += 1
            if acceptance:
                acceptance(cut, "pair_exchange", restore=[u, v], delete=x)
            cut = reverse_greedy(adj, cap, cut, clock)
            if acceptance:
                acceptance(cut, "reverse_greedy")
            moved = True
            break
        if not moved:
            break
    if clock.expired():
        stats["stop"] = "time_budget"
    if (
        stats["stop"] == "local_menu_exhausted"
        and stats["enumeration_rounds"]
        and all((row["enumeration_complete"] for row in stats["enumeration_rounds"]))
    ):
        stats["complete_neighborhood_certificates"] = 1
    return (cut, stats)
