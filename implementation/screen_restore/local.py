
from bisect import bisect_left, bisect_right
from collections import Counter
from collections.abc import Mapping
import itertools
import time
from types import MappingProxyType
from .incidence import PairContext


def deadline(clock):
    if clock is not None and clock.expired():
        raise TimeoutError("component-local delete-first deadline")


def _cut_nodes(cut, n):
    cut = set(cut)
    if any((type(u) is not int or not 0 <= u < n for u in cut)):
        raise ValueError("cut contains invalid vertex")
    return cut


class _TrialSizes(Mapping):

    def __init__(self, base, removed_root, fragments):
        self.base, self.removed_root, self.fragments = (base, removed_root, fragments)

    def __getitem__(self, key):
        if key in self.fragments:
            return self.fragments[key]
        if key == self.removed_root:
            raise KeyError(key)
        return self.base[key]

    def __iter__(self):
        yield from self.fragments
        yield from (key for key in self.base if key != self.removed_root)

    def __len__(self):
        return len(self.base) - 1 + len(self.fragments)


class ComponentFragmentIndex:

    def __init__(self, adj, members, clock=None, counters=None):
        self.adj, self.members = (adj, frozenset(members))
        if not self.members:
            raise ValueError("empty component index")
        self.stats = counters if counters is not None else Counter()
        self.n = len(adj)
        local = {}
        for u in self.members:
            deadline(clock)
            self.stats["index_ambient_adjacency_examined"] += len(adj[u])
            local[u] = tuple((v for v in adj[u] if v in self.members))
        self.stats["index_local_adjacency_entries"] += sum(map(len, local.values()))
        self.tin, self.tout, self.low, self.subtree = ({}, {}, {}, {})
        self.children, self.parent, self.separated = ({}, {}, {})
        root = min(self.members)
        self.tin[root] = self.low[root] = 0
        self.parent[root] = None
        self.subtree[root], self.children[root] = (1, [])
        timer = 1
        stack = [[root, 0]]
        while stack:
            deadline(clock)
            u, position = stack[-1]
            if position < len(local[u]):
                v = local[u][position]
                stack[-1][1] += 1
                if v == self.parent[u]:
                    continue
                if v not in self.tin:
                    self.parent[v] = u
                    self.children[u].append(v)
                    self.tin[v] = self.low[v] = timer
                    timer += 1
                    self.subtree[v], self.children[v] = (1, [])
                    stack.append([v, 0])
                else:
                    self.low[u] = min(self.low[u], self.tin[v])
            else:
                stack.pop()
                self.tout[u] = timer
                parent = self.parent[u]
                if parent is not None:
                    self.low[parent] = min(self.low[parent], self.low[u])
                    self.subtree[parent] += self.subtree[u]
        if len(self.tin) != len(self.members):
            raise ValueError("index members must form one connected component")
        self.specs = {}
        for x in self.members:
            deadline(clock)
            separated = tuple((c for c in self.children[x] if self.low[c] >= self.tin[x]))
            self.separated[x] = separated
            starts = tuple((self.tin[c] for c in separated))
            ends = tuple((self.tout[c] for c in separated))
            ids = tuple((self.n + c + 1 for c in separated))
            remainder_id = self.n + x + 1
            remainder_size = len(self.members) - 1 - sum((self.subtree[c] for c in separated))
            sizes = {key: self.subtree[c] for key, c in zip(ids, separated)}
            if remainder_size:
                sizes[remainder_id] = remainder_size
            self.specs[x] = (starts, ends, ids, remainder_id, MappingProxyType(sizes))
        self.attachments = {}
        self.stats["component_indices_built"] += 1
        self.stats["index_vertices_processed"] += len(self.members)

    def fragment_context(self, x):
        return self.specs[x][4]

    def fragment_owner(self, x, v):
        if v == x:
            return None
        starts, ends, ids, remainder_id, _ = self.specs[x]
        position = self.tin[v]
        index = bisect_right(starts, position) - 1
        return ids[index] if index >= 0 and position < ends[index] else remainder_id

    def attachment_positions(self, u, clock=None):
        if u in self.attachments:
            self.stats["attachment_cache_hits"] += 1
            return self.attachments[u]
        deadline(clock)
        self.stats["attachment_ambient_adjacency_examined"] += len(self.adj[u])
        positions = tuple(sorted((self.tin[v] for v in self.adj[u] if v in self.members)))
        self.attachments[u] = positions
        self.stats["attachment_cache_builds"] += 1
        self.stats["attachment_positions_stored"] += len(positions)
        return positions

    def touched_fragments(self, x, u, clock=None):
        positions = self.attachment_positions(u, clock)
        starts, ends, ids, remainder_id, sizes = self.specs[x]
        removed_position = self.tin[x]
        if not starts:
            count = len(positions)
            index = bisect_left(positions, removed_position)
            count -= int(index < len(positions) and positions[index] == removed_position)
            self.stats["fragment_single_remainder_queries"] += 1
            return {remainder_id} if count else set()
        touched = set()
        if len(positions) <= 2 * len(starts) + 1:
            for position in positions:
                deadline(clock)
                self.stats["fragment_neighbor_queries"] += 1
                if position == removed_position:
                    continue
                index = bisect_right(starts, position) - 1
                touched.add(
                    ids[index] if index >= 0 and position < ends[index] else remainder_id
                )
        else:
            covered = 0
            for start, end, key in zip(starts, ends, ids):
                deadline(clock)
                self.stats["fragment_interval_queries"] += 1
                count = bisect_left(positions, end) - bisect_left(positions, start)
                if count:
                    touched.add(key)
                    covered += count
            index = bisect_left(positions, removed_position)
            removed = int(index < len(positions) and positions[index] == removed_position)
            if len(positions) - covered - removed:
                touched.add(remainder_id)
        if not touched <= sizes.keys():
            raise AssertionError("fragment lookup returned an empty fragment")
        return touched


class LocalDeleteState:

    def __init__(self, adj, cut, clock=None, counters=None):
        self.adj = adj
        self.stats = counters if counters is not None else Counter()
        self.base = PairContext(adj, _cut_nodes(cut, len(adj)), clock)
        self.indices = {}
        self.stats["context_rebuilds"] += 1
        self._prepare_round(clock)

    def _prepare_round(self, clock):
        self.ordered_cut = sorted(self.base.cut)
        self.incidence = {}
        for u in self.ordered_cut:
            deadline(clock)
            for root in self.base.signatures[u]:
                self.incidence.setdefault(root, []).append(u)
                self.stats["round_signature_incidents"] += 1
        self._eligible_buckets = {}
        self._global_eligible = {}

    def update(self, new_cut, clock=None):
        info = self.base.update(_cut_nodes(new_cut, len(self.adj)), clock)
        current = set(self.base.members.values())
        stale = [members for members in self.indices if members not in current]
        for members in stale:
            del self.indices[members]
        self.stats["component_indices_invalidated"] += len(stale)
        self.stats["unchanged_component_indices_retained"] += len(self.indices)
        self.stats["context_updates"] += 1
        self.stats.update({"update_" + key: value for key, value in info.items()})
        self._prepare_round(clock)
        return info

    def _index(self, root, clock):
        members = self.base.members[root]
        if members not in self.indices:
            self.indices[members] = ComponentFragmentIndex(
                self.adj, members, clock, self.stats
            )
        else:
            self.stats["component_index_uses_reused"] += 1
        return self.indices[members]

    def _candidates(self, root, cap, clock):
        key = (root, cap)
        if key not in self._eligible_buckets:
            size = self.base.sizes[root]
            incident = self.incidence.get(root, ())
            eligible = []
            for u in incident:
                deadline(clock)
                self.stats["incidence_eligibility_checks"] += 1
                if self.base.masses[u] - size <= cap:
                    eligible.append(u)
                else:
                    self.stats["incidence_mass_rejections"] += 1
            if cap not in self._global_eligible:
                global_eligible = []
                for u in self.ordered_cut:
                    deadline(clock)
                    self.stats["round_global_eligibility_checks"] += 1
                    if self.base.masses[u] <= cap:
                        global_eligible.append(u)
                self._global_eligible[cap] = tuple(global_eligible)
            global_eligible = self._global_eligible[cap]
            if global_eligible:
                self.stats["unsaturated_bucket_fallbacks"] += 1
                eligible = sorted(set(eligible).union(global_eligible))
            self._eligible_buckets[key] = tuple(eligible)
        return self._eligible_buckets[key]

    def trial(self, x, cap, clock=None, *, filter_candidates=True):
        deadline(clock)
        root = self.base.owner[x]
        candidates = (
            self._candidates(root, cap, clock) if filter_candidates else self.ordered_cut
        )
        index = self._index(root, clock)
        fragments = index.fragment_context(x)
        sizes = _TrialSizes(self.base.sizes, root, fragments)
        signatures, masses = ({}, {})
        for u in candidates:
            deadline(clock)
            original = self.base.signatures[u]
            if root not in original:
                signatures[u] = original
                masses[u] = self.base.masses[u]
                self.stats["unaffected_endpoint_signatures_reused"] += 1
                continue
            touched = index.touched_fragments(x, u, clock)
            signatures[u] = original - {root} | touched
            masses[u] = (
                self.base.masses[u]
                - self.base.sizes[root]
                + sum((fragments[f] for f in touched))
            )
            self.stats["signature_deltas"] += 1
            self.stats["delta_outside_signature_entries_copied"] += len(original) - 1
        self.stats["local_trial_contexts"] += 1
        return (sizes, signatures, masses)


def _moves(state, cap, clock, stats):
    for x in range(len(state.adj)):
        deadline(clock)
        if x in state.base.cut:
            continue
        stats["replacement_vertices_tested"] += 1
        root = state.base.owner[x]
        if len(state._candidates(root, cap, clock)) < 2:
            stats["replacement_vertices_screened"] += 1
            continue
        sizes, signatures, masses = state.trial(x, cap, clock)
        eligible = [u for u in signatures if masses[u] <= cap]
        stats["endpoint_mass_rejections"] += len(signatures) - len(eligible)
        stats["eligible_restore_endpoints"] += len(eligible)
        for u, v in itertools.combinations(eligible, 2):
            deadline(clock)
            stats["pair_load_evaluations"] += 1
            su, sv = (signatures[u], signatures[v])
            small, other = (su, sv) if len(su) <= len(sv) else (sv, su)
            shared = sum((sizes[c] for c in small if c in other))
            stats["pair_signature_entries_examined"] += len(small)
            load = (
                masses[u] + masses[v] - shared
                if v in state.adj[u] or shared
                else max(masses[u], masses[v])
            )
            if load <= cap:
                yield (u, v, x)


def feasible_moves(adj, cap, cut, clock=None, counters=None):
    from .pair_bags import _validate, lcc

    adj = _validate(adj, cap)
    cut = _cut_nodes(cut, len(adj))
    if lcc(adj, cut) > cap:
        raise ValueError("component-local delete-first input is not feasible")
    stats = counters if counters is not None else Counter()
    state = LocalDeleteState(adj, cut, clock, stats)
    yield from _moves(state, cap, clock, stats)


def repair(adj, cap, initial_cut, seconds, *, clock=None):
    from .pair_bags import Clock, _validate, lcc, reverse_greedy

    clock = clock or Clock(seconds)
    adj = _validate(adj, cap)
    best = _cut_nodes(initial_cut, len(adj))
    stats = Counter(
        rounds=0,
        accepted_moves=0,
        context_rebuilds=0,
        context_updates=0,
        replacement_vertices_tested=0,
        replacement_vertices_screened=0,
        component_indices_built=0,
        component_indices_invalidated=0,
        unchanged_component_indices_retained=0,
        component_index_uses_reused=0,
        signature_deltas=0,
        pair_load_evaluations=0,
    )
    phases, round_trace = (Counter(), [])
    trace = [
        dict(
            stage="initial_plan",
            deletions=sorted(best),
            removed=len(best),
            wall_seconds=0.0,
            cpu_seconds=0.0,
        )
    ]

    def accept(cut, stage, **extras):
        nonlocal best
        if len(cut) < len(best):
            saved = sorted(cut)
            wall, cpu = clock.elapsed()
            if not clock.expired():
                best = set(cut)
                trace.append(
                    dict(
                        stage=stage,
                        deletions=saved,
                        removed=len(saved),
                        wall_seconds=wall,
                        cpu_seconds=cpu,
                        **extras
                    )
                )

    stop = "time_budget"
    try:
        if lcc(adj, best) > cap:
            raise ValueError("component-local delete-first requires a feasible saved cut")
        deadline(clock)
        started = time.perf_counter()
        cut = reverse_greedy(adj, cap, best, clock)
        phases["rg"] += time.perf_counter() - started
        accept(cut, "reverse_greedy")
        deadline(clock)
        started = time.perf_counter()
        state = LocalDeleteState(adj, cut, clock, stats)
        phases["context"] += time.perf_counter() - started
        while not clock.expired():
            stats["rounds"] += 1
            before = dict(stats)
            started = time.perf_counter()
            try:
                move = next(_moves(state, cap, clock, stats), None)
            finally:
                elapsed = time.perf_counter() - started
                phases["delete_first_scan"] += elapsed
                round_trace.append(
                    dict(
                        round=stats["rounds"],
                        start_removed=len(cut),
                        scan_seconds=elapsed,
                        counter_delta={
                            key: value - before.get(key, 0)
                            for key, value in stats.items()
                            if value != before.get(key, 0)
                        },
                    )
                )
            deadline(clock)
            if move is None:
                stop = "local_menu_exhausted"
                round_trace[-1]["outcome"] = "complete_no_move"
                break
            u, v, x = move
            proposal = cut - {u, v} | {x}
            started = time.perf_counter()
            if lcc(adj, proposal) > cap:
                raise AssertionError("component-local oracle admitted an infeasible move")
            phases["verification"] += time.perf_counter() - started
            deadline(clock)
            cut = proposal
            stats["accepted_moves"] += 1
            accept(cut, "pair_exchange", restore=[u, v], delete=x)
            round_trace[-1].update(outcome="accepted", restore=[u, v], delete=x)
            started = time.perf_counter()
            cut = reverse_greedy(adj, cap, cut, clock)
            phases["rg"] += time.perf_counter() - started
            accept(cut, "reverse_greedy")
            deadline(clock)
            started = time.perf_counter()
            info = state.update(cut, clock)
            phases["context"] += time.perf_counter() - started
            round_trace[-1]["context_update"] = info
    except TimeoutError:
        stop = "time_budget"
    wall, cpu = clock.elapsed()
    return dict(
        deletions=sorted(best),
        removed=len(best),
        trace=trace,
        stop=stop,
        counters=dict(stats),
        phase_seconds=dict(phases),
        round_trace=round_trace,
        algorithm_wall_seconds=wall,
        algorithm_cpu_seconds=cpu,
        charged_seconds=max(wall, cpu),
        budget_seconds=seconds,
        closure=stop == "local_menu_exhausted",
    )
