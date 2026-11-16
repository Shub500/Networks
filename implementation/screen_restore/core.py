
from collections import Counter
from collections.abc import Mapping
import itertools
import math
import time
from .local import LocalDeleteState


class ChargedClock:

    def __init__(self, seconds):
        if isinstance(seconds, bool) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError("allowance must be finite and nonnegative")
        self.seconds = float(seconds)
        self.wall0, self.cpu0 = (time.perf_counter(), time.process_time())

    def elapsed(self):
        return (time.perf_counter() - self.wall0, time.process_time() - self.cpu0)

    def expired(self):
        return max(self.elapsed()) >= self.seconds


def check(clock):
    if clock is not None and clock.expired():
        raise TimeoutError("safe higher-order shared deadline")


def physical_components(adj, cut, clock=None):
    cut = set(cut)
    seen, groups = (set(), [])
    for root in range(len(adj)):
        check(clock)
        if root in cut or root in seen:
            continue
        stack, group = ([root], set())
        seen.add(root)
        while stack:
            check(clock)
            u = stack.pop()
            group.add(u)
            for v in adj[u]:
                check(clock)
                if v not in cut and v not in seen:
                    seen.add(v)
                    stack.append(v)
        groups.append(frozenset(group))
    return groups


def _validated_graph(adj, cap):
    if type(cap) is not int or cap < 1:
        raise ValueError("cap must be a positive integer")
    adj = tuple((frozenset(row) for row in adj))
    for u, row in enumerate(adj):
        if u in row or any((type(v) is not int or not 0 <= v < len(adj) for v in row)):
            raise ValueError("invalid undirected simple adjacency")
        if any((u not in adj[v] for v in row)):
            raise ValueError("asymmetric adjacency")
    return adj


def family_key(kind, base, roots, candidates):
    return (
        kind,
        tuple(
            sorted((frozenset(base.members[r]) for r in roots), key=lambda s: (min(s), len(s)))
        ),
        tuple(sorted(candidates)),
    )


class SafeHistory:

    def __init__(self, adj, enabled=True, counters=None, cap=None):
        self.adj = (
            adj
            if isinstance(adj, tuple) and all((isinstance(row, frozenset) for row in adj))
            else tuple((frozenset(row) for row in adj))
        )
        self.enabled = enabled
        self.stats = counters if counters is not None else Counter()
        self.cap = cap
        self.records = {}

    def bind_graph(self, adj, clock=None):
        if adj is self.adj:
            return
        if len(adj) != len(self.adj):
            raise ValueError("history cannot cross physical graphs")
        for old, row in zip(self.adj, adj):
            check(clock)
            if old != frozenset(row):
                raise ValueError("history cannot cross physical graphs")

    def bind(self, cap, adj=None, clock=None):
        if self.cap is None:
            self.cap = cap
        elif self.cap != cap:
            raise ValueError("history cannot cross component caps")
        if adj is not None:
            self.bind_graph(adj, clock)

    def record(self, key, candidates, base, excluded_roots, clock=None):
        if not self.enabled:
            return
        check(clock)
        self.bind_graph(base.adj, clock)
        candidates = tuple(sorted(candidates))
        external = set()
        excluded_roots = set(excluded_roots)
        for u in candidates:
            check(clock)
            for r in base.signatures[u]:
                check(clock)
                if r not in excluded_roots:
                    for v in base.members[r]:
                        check(clock)
                        external.add(v)
        local = tuple(
            sorted(
                (frozenset(base.members[r]) for r in excluded_roots),
                key=lambda s: (min(s), len(s)),
            )
        )
        certificate = (candidates, local, frozenset(external))
        check(clock)
        self.records[key] = certificate
        self.stats["history_certificates_recorded"] += 1
        self.stats["history_external_vertices_recorded"] += len(external)

    def can_skip(self, key, candidates, base, excluded_roots, clock=None):
        if not self.enabled or key not in self.records:
            return False
        check(clock)
        self.bind_graph(base.adj, clock)
        saved_candidates, local, external = self.records[key]
        now_local = tuple(
            sorted(
                (frozenset(base.members[r]) for r in excluded_roots),
                key=lambda s: (min(s), len(s)),
            )
        )
        if tuple(sorted(candidates)) != saved_candidates or now_local != local:
            self.stats["history_identity_invalidations"] += 1
            return False
        for u in saved_candidates:
            check(clock)
            if u not in base.cut:
                self.stats["history_candidate_invalidations"] += 1
                return False
        for v in external:
            check(clock)
            self.stats["history_external_vertices_checked"] += 1
            if v in base.cut:
                self.stats["history_external_loss_invalidations"] += 1
                return False
        self.stats["history_safe_hits"] += 1
        return True


class FragmentStore:

    def __init__(self, adj, counters):
        self.adj, self.stats = (adj, counters)
        self.records = {}

    def get(self, members, deletions, clock=None):
        key = (frozenset(members), tuple(sorted(deletions)))
        if key in self.records:
            self.stats["double_fragment_cache_hits"] += 1
            return self.records[key]
        retained = set(members) - set(deletions)
        seen, owner, sizes = (set(), {}, {})
        for start in sorted(retained):
            check(clock)
            if start in seen:
                continue
            fid = len(sizes)
            seen.add(start)
            stack, count = ([start], 0)
            while stack:
                check(clock)
                u = stack.pop()
                owner[u] = fid
                count += 1
                for v in self.adj[u]:
                    check(clock)
                    self.stats["double_fragment_adjacency_examined"] += 1
                    if v in retained and v not in seen:
                        seen.add(v)
                        stack.append(v)
            sizes[fid] = count
        check(clock)
        result = (owner, sizes)
        self.records[key] = result
        self.stats["double_fragment_cache_builds"] += 1
        return result


class _OverlaySizes(Mapping):

    def __init__(self, base, excluded):
        self.base, self.excluded, self.fragments = (base, frozenset(excluded), {})

    def __getitem__(self, key):
        if key in self.fragments:
            return self.fragments[key]
        if key in self.excluded:
            raise KeyError(key)
        return self.base[key]

    def __iter__(self):
        yield from self.fragments
        yield from (r for r in self.base if r not in self.excluded)

    def __len__(self):
        return len(self.base) - len(self.excluded) + len(self.fragments)

    def update(self, local):
        self.fragments.update(local)


def quotient_load(adj, endpoints, signatures, sizes, clock=None):
    endpoints = tuple(endpoints)
    left, largest = (set(endpoints), 0)
    while left:
        check(clock)
        u = min(left)
        left.remove(u)
        group, tokens, stack = ({u}, set(signatures[u]), [u])
        while stack:
            check(clock)
            z = stack.pop()
            for v in sorted(left):
                check(clock)
                if v in adj[z] or not signatures[z].isdisjoint(signatures[v]):
                    left.remove(v)
                    group.add(v)
                    stack.append(v)
                    tokens.update(signatures[v])
        load = len(group)
        for token in tokens:
            check(clock)
            load += sizes[token]
        largest = max(largest, load)
    return largest


def _is_saturated(base, cap, clock):
    for mass in base.masses.values():
        check(clock)
        if mass <= cap:
            return False
    return True


def _eligible(state, roots, cap, clock, saturated=None):
    base, roots = (state.base, set(roots))
    candidates = []
    incident = set()
    for r in roots:
        incident.update(state.incidence.get(r, ()))
    if saturated is None:
        saturated = _is_saturated(base, cap, clock)
    pool = sorted(incident if saturated else base.cut)
    for u in pool:
        check(clock)
        shed_bound = sum((base.sizes[r] for r in base.signatures[u] if r in roots))
        if base.masses[u] - shed_bound <= cap:
            candidates.append(u)
        else:
            state.stats["component_mass_rejections"] += 1
    return tuple(candidates)


def _single_context(state, root, x, candidates, lazy, clock):
    index = state._index(root, clock)
    if not lazy:
        for u in state.incidence.get(root, ()):
            check(clock)
            index.attachment_positions(u, clock)
    fragments = index.fragment_context(x)
    tagged_sizes = {(root, f): s for f, s in fragments.items()}
    attachments = {}
    for u in candidates:
        check(clock)
        attachments[u] = (
            {(root, f) for f in index.touched_fragments(x, u, clock)}
            if root in state.base.signatures[u]
            else set()
        )
    return (tagged_sizes, attachments)


def _post_trial(state, roots, deleted, candidates, lazy, fragment_store, clock):
    base, roots = (state.base, tuple(roots))
    sizes = _OverlaySizes(base.sizes, roots)
    signatures = {u: set(base.signatures[u]) - set(roots) for u in candidates}
    if len(roots) == 1 and len(deleted) == 2:
        root = roots[0]
        owner, fragments = fragment_store.get(base.members[root], deleted, clock)
        sizes.update({(root, f): size for f, size in fragments.items()})
        pool = (
            candidates
            if lazy
            else sorted(set(candidates).union(state.incidence.get(root, ())))
        )
        all_touched = {}
        for u in pool:
            check(clock)
            touched = set()
            for v in state.adj[u]:
                check(clock)
                state.stats["double_attachment_adjacency_examined"] += 1
                if v in owner:
                    touched.add((root, owner[v]))
            all_touched[u] = touched
        for u in candidates:
            signatures[u].update(all_touched[u])
    else:
        for root, x in zip(roots, deleted):
            check(clock)
            fs, attachments = _single_context(state, root, x, candidates, lazy, clock)
            sizes.update(fs)
            for u in candidates:
                signatures[u].update(attachments[u])
    masses, rescued = ({}, [])
    for u in candidates:
        check(clock)
        mass = 1
        for token in signatures[u]:
            check(clock)
            mass += sizes[token]
        masses[u] = mass
        if mass <= state._cap:
            rescued.append(u)
    return (sizes, signatures, masses, rescued)


def _warm_indices(state, roots, lazy, clock):
    if lazy:
        return
    for root in roots:
        check(clock)
        index = state._index(root, clock)
        for u in state.incidence.get(root, ()):
            check(clock)
            index.attachment_positions(u, clock)
        state.stats["eager_components_prepared"] += 1


def _find21(state, cap, history, rollout, lazy, clock, offer=None):
    base, stats = (state.base, state.stats)
    state._cap = cap
    candidates, keys, skipped = ({}, {}, set())
    pending, found_in_root = ({}, set())
    saturated = _is_saturated(base, cap, clock)
    _warm_indices(state, sorted(base.members), lazy, clock)
    for root in sorted(base.members):
        check(clock)
        cand = _eligible(state, (root,), cap, clock, saturated)
        candidates[root] = cand
        keys[root] = family_key(("21", cap), base, (root,), cand)
        if len(cand) < 2 or history.can_skip(keys[root], cand, base, (root,), clock):
            skipped.add(root)
        pending[root] = len(base.members[root])
    best, best_score = (None, None)
    for x in range(len(state.adj)):
        check(clock)
        if x in base.cut:
            continue
        root = base.owner[x]
        if root in skipped:
            continue
        cand = candidates[root]
        stats["splitters_21_tested"] += 1
        sizes, signatures, masses, rescued = _post_trial(
            state, (root,), (x,), cand, lazy, None, clock
        )
        best_seed = None
        for u, v in itertools.combinations(rescued, 2):
            check(clock)
            stats["quotient_21_checks"] += 1
            load = quotient_load(state.adj, (u, v), signatures, sizes, clock)
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
            for w in rescued:
                check(clock)
                if w in restored:
                    continue
                stats["rollout_extension_checks"] += 1
                new_load = quotient_load(state.adj, restored + [w], signatures, sizes, clock)
                if new_load <= cap:
                    restored.append(w)
                    load = new_load
            score = (len(restored) - 1,)
            if best_score is None or score > best_score:
                best_score = score
                best = dict(
                    kind="rollout_k1",
                    restore=restored,
                    delete=[x],
                    affected_load=load,
                    selection_score=list(score),
                )
                if offer is not None:
                    offer(best)
        pending[root] -= 1
        if pending[root] == 0 and root not in found_in_root:
            history.record(keys[root], cand, base, (root,), clock)
    return best


def _rg(state, cap, clock):
    restored = []
    while True:
        check(clock)
        eligible = []
        for u in sorted(state.base.cut):
            check(clock)
            if state.base.masses[u] <= cap:
                eligible.append((state.base.masses[u], u))
        if not eligible:
            return restored
        _, u = min(eligible)
        state.update(state.base.cut - {u}, clock)
        restored.append(u)
        state.stats["rg_restorations"] += 1


def _neutral_escape(state, cap, lazy, clock):
    original = set(state.base.cut)
    stats = state.stats
    for x in range(len(state.adj)):
        check(clock)
        if x in original:
            continue
        sizes, signatures, masses = state.trial(x, cap, clock)
        for u in sorted(signatures):
            check(clock)
            if masses[u] > cap:
                continue
            neutral = original - {u} | {x}
            stats["neutral_branches_started"] += 1
            trial = LocalDeleteState(state.adj, neutral, clock, stats)
            _rg(trial, cap, clock)
            if len(trial.base.cut) >= len(original):
                move = _find21(
                    trial, cap, SafeHistory(state.adj, False, stats, cap), False, lazy, clock
                )
                if move is None:
                    continue
                trial.update(
                    trial.base.cut - set(move["restore"]) | set(move["delete"]), clock
                )
                _rg(trial, cap, clock)
            if len(trial.base.cut) < len(original):
                return dict(
                    kind="neutral_then_repair",
                    restore=sorted(original - trial.base.cut),
                    delete=sorted(trial.base.cut - original),
                    neutral_restore=u,
                    neutral_delete=x,
                )
    return None
