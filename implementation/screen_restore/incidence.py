
from collections import Counter
import itertools
import time


def deadline(clock):
    if clock is not None and clock.expired():
        raise TimeoutError("context/menu deadline")


class PairContext:

    def __init__(self, adj, cut, clock=None):
        self.adj = adj
        self.cut = set(cut)
        self.members = self._components(set(range(len(adj))) - self.cut, clock)
        self.owner = {x: root for root, group in self.members.items() for x in group}
        self.sizes = {root: len(group) for root, group in self.members.items()}
        self.signatures, self.masses = ({}, {})
        self._refresh_signatures(self.cut, clock)

    def _components(self, retained, clock):
        seen, groups = (set(), {})
        for root in sorted(retained):
            deadline(clock)
            if root in seen:
                continue
            seen.add(root)
            stack, group = ([root], set())
            while stack:
                deadline(clock)
                u = stack.pop()
                group.add(u)
                for v in self.adj[u]:
                    if v in retained and v not in seen:
                        seen.add(v)
                        stack.append(v)
            groups[root] = frozenset(group)
        return groups

    def _refresh_signatures(self, vertices, clock):
        for u in vertices:
            deadline(clock)
            sig = {self.owner[v] for v in self.adj[u] if v not in self.cut}
            self.signatures[u] = sig
            self.masses[u] = 1 + sum((self.sizes[root] for root in sig))

    def update(self, new_cut, clock=None):
        deadline(clock)
        new_cut = set(new_cut)
        restored, deleted = (self.cut - new_cut, new_cut - self.cut)
        roots = {self.owner[u] for u in deleted}
        for u in restored:
            deadline(clock)
            roots.update((self.owner[v] for v in self.adj[u] if v not in self.cut))
        region = set(restored)
        for root in roots:
            region.update(self.members[root])
        new_groups = self._components(region - new_cut, clock)
        boundary = set(deleted)
        for u in region:
            deadline(clock)
            boundary.update((v for v in self.adj[u] if v in new_cut))
        for root in roots:
            del self.members[root]
            del self.sizes[root]
        for u in region:
            self.owner.pop(u, None)
        for root, group in new_groups.items():
            assert root not in self.members
            self.members[root] = group
            self.sizes[root] = len(group)
            for u in group:
                self.owner[u] = root
        for u in restored:
            del self.signatures[u]
            del self.masses[u]
        self.cut = new_cut
        self._refresh_signatures(boundary, clock)
        return dict(
            restored=len(restored),
            deleted=len(deleted),
            affected_vertices=len(region),
            affected_old_components=len(roots),
            affected_new_components=len(new_groups),
            signatures_refreshed=len(boundary),
            affected_ambient_adjacency=sum((len(self.adj[u]) for u in region)),
            refreshed_signature_adjacency=sum((len(self.adj[u]) for u in boundary)),
        )

    def identity(self):
        return (self.cut, self.members, self.owner, self.sizes, self.signatures, self.masses)


def candidate_menu(state, cap, fused, clock=None):
    from .pair_bags import _pair_boundary_reason

    adj, cut, sig, sizes, mass = (
        state.adj,
        state.cut,
        state.signatures,
        state.sizes,
        state.masses,
    )
    saturated = all((m > cap for m in mass.values()))
    use_fusion = fused and saturated
    buckets, unique = ({}, set())
    stats = Counter(
        proposals=0,
        full_incidents=0,
        eligible_incidents=0,
        unique_keys=0,
        fused_boundary_rejections=0,
        returned_pairs=0,
    )
    stats["saturation_fallback"] = int(fused and (not saturated))
    for u in sorted(cut):
        deadline(clock)
        for root in sig[u]:
            stats["full_incidents"] += 1
            if not use_fusion or mass[u] - sizes[root] <= cap:
                buckets.setdefault(root, []).append(u)
                stats["eligible_incidents"] += 1
        if not use_fusion:
            for v in adj[u] & cut:
                if u < v:
                    unique.add((u, v))
                    stats["proposals"] += 1
    for bucket in buckets.values():
        for pair in itertools.combinations(bucket, 2):
            deadline(clock)
            unique.add(pair)
            stats["proposals"] += 1
    rows = []
    for u, v in sorted(unique):
        deadline(clock)
        ids = sig[u] | sig[v]
        b = 2 + sum((sizes[root] for root in ids))
        stats["unique_keys"] += 1
        if use_fusion:
            reason, _ = _pair_boundary_reason(
                cap, sizes, sig[u], sig[v], mass[u], mass[v], b, v in adj[u]
            )
            if reason not in ("survives", "unsaturated_fallback"):
                stats["fused_boundary_rejections"] += 1
                continue
        rows.append((b, u, v, ids))
    rows.sort(key=lambda r: r[:3])
    deadline(clock)
    stats["returned_pairs"] = len(rows)
    return (rows, dict(stats))


def repair(adj, cap, initial_cut, seconds, *, fused=False, incremental=False, clock=None):
    from .pair_bags import (
        Clock,
        _pair_boundary_reason,
        articulation_loads,
        lcc,
        reverse_greedy,
    )

    clock = clock or Clock(seconds)
    best = set(initial_cut)
    trace = [
        dict(
            stage="initial_plan",
            deletions=sorted(best),
            removed=len(best),
            wall_seconds=0.0,
            cpu_seconds=0.0,
        )
    ]
    stats = Counter(
        rounds=0,
        tested_surviving_menu_bags=0,
        accepted_moves=0,
        dfs_evaluations=0,
        boundary_rejected_visited=0,
        context_rebuilds=0,
        context_updates=0,
    )
    phase_seconds = Counter()

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
        assert lcc(adj, best) <= cap
        deadline(clock)
        started = time.perf_counter()
        cut = reverse_greedy(adj, cap, best, clock)
        phase_seconds["rg"] += time.perf_counter() - started
        accept(cut, "reverse_greedy")
        state = None
        while not clock.expired():
            if state is None:
                started = time.perf_counter()
                state = PairContext(adj, cut, clock)
                phase_seconds["context"] += time.perf_counter() - started
                stats["context_rebuilds"] += 1
            started = time.perf_counter()
            rows, telemetry = candidate_menu(state, cap, fused, clock)
            phase_seconds["enumeration"] += time.perf_counter() - started
            stats.update({"enumeration_" + k: v for k, v in telemetry.items()})
            stats["rounds"] += 1
            moved = False
            for b, u, v, ids in rows:
                deadline(clock)
                stats["tested_surviving_menu_bags"] += 1
                started = time.perf_counter()
                reason, _ = _pair_boundary_reason(
                    cap,
                    state.sizes,
                    state.signatures[u],
                    state.signatures[v],
                    state.masses[u],
                    state.masses[v],
                    b,
                    v in adj[u],
                )
                phase_seconds["visited_boundary"] += time.perf_counter() - started
                if reason not in ("survives", "unsaturated_fallback"):
                    stats["boundary_rejected_visited"] += 1
                    continue
                started = time.perf_counter()
                bag = {u, v}.union(*(state.members[root] for root in ids))
                loads = articulation_loads(adj, bag)
                valid = [
                    (load, x) for x, load in loads.items() if x not in (u, v) and load <= cap
                ]
                stats["dfs_evaluations"] += 1
                phase_seconds["oracle"] += time.perf_counter() - started
                if not valid:
                    continue
                _, x = min(valid)
                proposal = cut - {u, v} | {x}
                started = time.perf_counter()
                assert lcc(adj, proposal) <= cap
                phase_seconds["verification"] += time.perf_counter() - started
                deadline(clock)
                cut = proposal
                stats["accepted_moves"] += 1
                accept(cut, "pair_exchange", restore=[u, v], delete=x)
                started = time.perf_counter()
                cut = reverse_greedy(adj, cap, cut, clock)
                phase_seconds["rg"] += time.perf_counter() - started
                accept(cut, "reverse_greedy")
                deadline(clock)
                if incremental:
                    started = time.perf_counter()
                    updates = state.update(cut, clock)
                    phase_seconds["context"] += time.perf_counter() - started
                    stats.update({"update_" + k: v for k, v in updates.items()})
                    stats["context_updates"] += 1
                else:
                    state = None
                moved = True
                break
            if not moved:
                deadline(clock)
                stop = "local_menu_exhausted"
                break
    except TimeoutError:
        stop = "time_budget"
    wall, cpu = clock.elapsed()
    return dict(
        deletions=sorted(best),
        removed=len(best),
        trace=trace,
        stop=stop,
        counters=dict(stats),
        phase_seconds=dict(phase_seconds),
        algorithm_wall_seconds=wall,
        algorithm_cpu_seconds=cpu,
        charged_seconds=max(wall, cpu),
        budget_seconds=seconds,
        closure=stop == "local_menu_exhausted",
    )
