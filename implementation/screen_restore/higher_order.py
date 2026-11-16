
from collections import Counter
import itertools
from types import MappingProxyType
from . import core
from .triples import triple_load

check = core.check


class ResponseStore:

    def __init__(self, adj, stats=None, enabled=True, max_components=None):
        if max_components is not None and (
            type(max_components) is not int or max_components < 0
        ):
            raise ValueError("max_components must be a nonnegative integer or None")
        self.adj = (
            adj
            if isinstance(adj, tuple) and all((isinstance(r, frozenset) for r in adj))
            else tuple((frozenset(r) for r in adj))
        )
        self.stats = stats if stats is not None else Counter()
        self.enabled = enabled and max_components != 0
        self.max_components = max_components
        self.records = {}

    def bind(self, state, clock=None):
        if state.adj is self.adj:
            return
        if len(state.adj) != len(self.adj):
            raise ValueError("response cache cannot cross graphs")
        for old, row in zip(self.adj, state.adj):
            check(clock)
            if old != frozenset(row):
                raise ValueError("response cache cannot cross graphs")

    def _entry(self, state, root, clock):
        members = frozenset(state.base.members[root])
        if self.enabled and members in self.records:
            self.stats["response_component_hits"] += 1
            return self.records[members]
        index = state._index(root, clock)
        entry = dict(
            index=index, members=members, responses={}, tagged_sizes={}, tagged_touched={}
        )
        check(clock)
        if self.enabled:
            if self.max_components is not None:
                while len(self.records) >= self.max_components:
                    check(clock)
                    oldest = next(iter(self.records))
                    del self.records[oldest]
                    self.stats["response_components_evicted"] += 1
            self.records[members] = entry
            self.stats["response_components_resident"] = len(self.records)
            self.stats["response_components_peak_resident"] = max(
                self.stats["response_components_peak_resident"], len(self.records)
            )
        self.stats["response_components_built"] += 1
        return entry

    def _response(self, state, root, x, u, entry, clock):
        if x not in entry["members"] or u in entry["members"]:
            raise ValueError("invalid local response identities")
        key = (x, u)
        if self.enabled and key in entry["responses"]:
            self.stats["response_record_hits"] += 1
            return entry["responses"][key]
        index = entry["index"]
        touched = tuple(sorted(index.touched_fragments(x, u, clock)))
        sizes = index.fragment_context(x)
        attached = 0
        for token in touched:
            check(clock)
            attached += sizes[token]
        shed = len(entry["members"]) - attached if root in state.base.signatures[u] else 0
        result = (shed, touched)
        check(clock)
        if self.enabled:
            entry["responses"][key] = result
        self.stats["response_records_built"] += 1
        self.stats["response_fragment_ids_stored"] += len(touched)
        return result

    def response(self, state, root, x, u, lazy=True, clock=None):
        self.bind(state, clock)
        entry = self._entry(state, root, clock)
        if not lazy:
            for endpoint in state.incidence.get(root, ()):
                check(clock)
                entry["index"].attachment_positions(endpoint, clock)
        return self._response(state, root, x, u, entry, clock)

    def single_context(self, state, root, x, candidates, lazy, clock):
        self.bind(state, clock)
        if not self.enabled:
            return core._single_context(state, root, x, candidates, lazy, clock)
        entry = self._entry(state, root, clock)
        index = entry["index"]
        if not lazy:
            for u in state.incidence.get(root, ()):
                check(clock)
                index.attachment_positions(u, clock)
        context_key = (root, x)
        if context_key not in entry["tagged_sizes"]:
            tagged = {}
            for token, mass in index.fragment_context(x).items():
                check(clock)
                tagged[root, token] = mass
            check(clock)
            entry["tagged_sizes"][context_key] = MappingProxyType(tagged)
        attachments = {}
        for u in candidates:
            check(clock)
            if root not in state.base.signatures[u]:
                attachments[u] = frozenset()
                continue
            response_key = (root, x, u)
            if response_key not in entry["tagged_touched"]:
                _, touched = self._response(state, root, x, u, entry, clock)
                tagged = frozenset(((root, token) for token in touched))
                check(clock)
                entry["tagged_touched"][response_key] = tagged
            else:
                self.stats["response_tagged_hits"] += 1
            attachments[u] = entry["tagged_touched"][response_key]
        return (entry["tagged_sizes"][context_key], attachments)

    def post_trial(self, state, roots, deleted, candidates, lazy, fragment_store, clock):
        self.bind(state, clock)
        if not self.enabled or (len(roots) == 1 and len(deleted) == 2):
            return core._post_trial(
                state, roots, deleted, candidates, lazy, fragment_store, clock
            )
        base, roots = (state.base, tuple(roots))
        sizes = core._OverlaySizes(base.sizes, roots)
        signatures = {}
        for u in candidates:
            check(clock)
            signatures[u] = set(base.signatures[u]) - set(roots)
        for root, x in zip(roots, deleted):
            check(clock)
            fragments, attachments = self.single_context(
                state, root, x, candidates, lazy, clock
            )
            sizes.update(fragments)
            for u in candidates:
                check(clock)
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


def _scalar_row(state, root, x, endpoints, store, lazy, clock):
    row = {}
    if store is not None:
        entry = store._entry(state, root, clock)
        for u in endpoints:
            check(clock)
            row[u] = store._response(state, root, x, u, entry, clock)[0]
    else:
        index = state._index(root, clock)
        for u in endpoints:
            check(clock)
            touched = index.touched_fragments(x, u, clock)
            attached = 0
            for token in touched:
                check(clock)
                attached += index.fragment_context(x)[token]
            row[u] = state.base.sizes[root] - attached
    state.stats["bridge_bound_scalar_entries"] += len(row)
    return row


def _bridge_tables(state, roots, bridges, store, lazy, clock):
    tables, maxima, row_maxima = ([], [], [])
    for root in roots:
        table, maximum, row_maximum = ({}, {u: 0 for u in bridges}, {})
        for x in sorted(state.base.members[root]):
            check(clock)
            row = _scalar_row(state, root, x, bridges, store, lazy, clock)
            table[x] = row
            largest = 0
            for u, shed in row.items():
                check(clock)
                maximum[u] = max(maximum[u], shed)
                largest = max(largest, shed)
            row_maximum[x] = largest
        tables.append(table)
        maxima.append(maximum)
        row_maxima.append(row_maximum)
    return (tables, maxima, row_maxima)


def _profile_prefix(state, roots, candidates, clock, signatures=None):
    candidates, roots = (tuple(candidates), set(roots))
    edges = []
    for u, v in itertools.combinations(candidates, 2):
        check(clock)
        if v in state.adj[u]:
            edges.append((u, v))
    external_incidence = {}
    for u in candidates:
        check(clock)
        source = state.base.signatures[u] if signatures is None else signatures[u]
        for token in source:
            check(clock)
            if not isinstance(token, tuple) and token not in roots:
                external_incidence.setdefault(token, []).append(u)
    external = []
    for token, attached in external_incidence.items():
        check(clock)
        members = []
        for v in state.base.members[token]:
            check(clock)
            members.append(v)
        external.append((tuple(sorted(members)), state.base.sizes[token], tuple(attached)))
    check(clock)
    state.stats["response_profile_prefixes_built"] += 1
    return (candidates, tuple(edges), tuple(sorted(external)))


def failed_profile(state, roots, candidates, sizes, signatures, clock, *, prefix=None):
    if prefix is None:
        prefix = _profile_prefix(state, roots, candidates, clock, signatures)
    local_incidence = {}
    for u in candidates:
        check(clock)
        for token in signatures[u]:
            check(clock)
            if isinstance(token, tuple):
                local_incidence.setdefault(token, []).append(u)
    local = []
    for token, attached in local_incidence.items():
        check(clock)
        local.append((sizes[token], tuple(attached)))
    key = (prefix, tuple(sorted(local)))
    check(clock)
    state.stats["response_profiles_built"] += 1
    return key


def pair_load(adj, u, v, signatures, sizes, masses, clock=None):
    check(clock)
    shared = signatures[u] & signatures[v]
    if v not in adj[u] and (not shared):
        return max(masses[u], masses[v])
    overlap = 0
    for token in shared:
        check(clock)
        overlap += sizes[token]
    return masses[u] + masses[v] - overlap


def _triple_from_context(
    state, cap, roots, deleted, candidates, context, bridge, clock, *, direct_triple=False
):
    if type(direct_triple) is not bool:
        raise ValueError("direct_triple must be boolean")
    sizes, signatures, masses, rescued = context
    if len(rescued) < 3:
        return None
    neighbors = {u: set() for u in rescued}
    for u, v in itertools.combinations(rescued, 2):
        check(clock)
        state.stats["triangle_pair_checks"] += 1
        state.stats["pair_direct_formula_checks"] += 1
        if pair_load(state.adj, u, v, signatures, sizes, masses, clock) <= cap:
            neighbors[u].add(v)
    for u in rescued:
        check(clock)
        for v in sorted(neighbors[u]):
            check(clock)
            for w in sorted(neighbors[u] & neighbors[v]):
                check(clock)
                if bridge is not None and (not {u, v, w} & bridge):
                    state.stats["conditional_bridge_triples_skipped"] += 1
                    continue
                state.stats["quotient_32_checks"] += 1
                if direct_triple:
                    state.stats["direct_triple_formula_checks"] += 1
                    load = triple_load(state.adj, u, v, w, signatures, sizes, clock)
                else:
                    load = core.quotient_load(state.adj, (u, v, w), signatures, sizes, clock)
                if load <= cap:
                    return dict(
                        kind="32_class_i" if len(roots) == 2 else "32_class_ii",
                        restore=[u, v, w],
                        delete=list(deleted),
                        affected_load=load,
                    )
    return None


def find32(
    state,
    cap,
    history,
    fragments,
    class_i,
    class_ii,
    max_same_component,
    pair_closed,
    lazy,
    clock,
    *,
    store=None,
    bridge_bounds=True,
    pair_priority=False,
    splitter_priority=False,
    profile_dedup=True,
    direct_triple=False
):
    if type(direct_triple) is not bool:
        raise ValueError("direct_triple must be boolean")
    base, stats = (state.base, state.stats)
    state._cap = cap
    history.bind(cap, state.adj, clock)
    if store is not None:
        store.bind(state, clock)
    saturated = core._is_saturated(base, cap, clock)
    if pair_closed and (not saturated):
        raise ValueError("bridge restriction requires RG and (2,1) closure")
    post = core._post_trial if store is None else store.post_trial
    if class_i:
        if pair_closed:
            pair_bridges = {}
            for u in sorted(base.cut):
                check(clock)
                for r1, r2 in itertools.combinations(sorted(base.signatures[u]), 2):
                    check(clock)
                    if base.masses[u] - base.sizes[r1] - base.sizes[r2] <= cap:
                        pair_bridges.setdefault((r1, r2), []).append(u)
            if pair_priority:
                ordered = sorted(
                    pair_bridges,
                    key=lambda pair: (
                        -len(pair_bridges[pair]),
                        -sum((base.sizes[r] for r in pair)),
                        pair,
                    ),
                )
            else:
                ordered = sorted(pair_bridges)
        else:
            ordered = itertools.combinations(sorted(base.members), 2)
            if pair_priority:
                ordered = sorted(
                    ordered,
                    key=lambda pair: (
                        -len(
                            set(state.incidence.get(pair[0], ()))
                            & set(state.incidence.get(pair[1], ()))
                        ),
                        -sum((base.sizes[r] for r in pair)),
                        pair,
                    ),
                )
        for roots in ordered:
            check(clock)
            r1, r2 = roots
            candidates = core._eligible(state, roots, cap, clock, saturated)
            bridge = (
                set(state.incidence.get(r1, ())) & set(state.incidence.get(r2, ()))
                if pair_closed
                else None
            )
            if len(candidates) < 3 or (bridge is not None and (not set(candidates) & bridge)):
                continue
            key = core.family_key(("32I", cap, bool(pair_closed)), base, roots, candidates)
            if history.can_skip(key, candidates, base, roots, clock):
                continue
            core._warm_indices(state, roots, lazy, clock)
            bridges = tuple((u for u in candidates if bridge is not None and u in bridge))
            tables = maxima = row_maxima = deficits = None
            minimum_deficit = None
            if bridges and (bridge_bounds or splitter_priority):
                tables, maxima, row_maxima = _bridge_tables(
                    state, roots, bridges, store, lazy, clock
                )
                deficits = {u: base.masses[u] - cap for u in bridges}
                minimum_deficit = min(deficits.values())
            xs, ys = (sorted(base.members[r1]), sorted(base.members[r2]))
            if splitter_priority and tables is not None:
                xs.sort(key=lambda x: (-row_maxima[0][x], x))
                ys.sort(key=lambda y: (-row_maxima[1][y], y))
            if bridge_bounds and tables is not None:
                possible = False
                for u in bridges:
                    check(clock)
                    if maxima[0][u] + maxima[1][u] >= deficits[u]:
                        possible = True
                        break
                if not possible:
                    stats["bridge_component_pairs_rejected"] += 1
                    history.record(key, candidates, base, roots, clock)
                    continue
            for x in xs:
                check(clock)
                if bridge_bounds and tables is not None:
                    possible = False
                    for u in bridges:
                        check(clock)
                        if tables[0][x][u] + maxima[1][u] >= deficits[u]:
                            possible = True
                            break
                    if not possible:
                        stats["bridge_splitter_rows_rejected"] += 1
                        continue
                for y in ys:
                    check(clock)
                    if bridge_bounds and tables is not None:
                        if row_maxima[0][x] + row_maxima[1][y] < minimum_deficit:
                            stats["bridge_coarse_pairs_rejected"] += 1
                            if splitter_priority:
                                stats["bridge_sorted_suffix_breaks"] += 1
                                break
                            continue
                        possible = False
                        for u in bridges:
                            check(clock)
                            if tables[0][x][u] + tables[1][y][u] >= deficits[u]:
                                possible = True
                                break
                        if not possible:
                            stats["bridge_endpoint_pairs_rejected"] += 1
                            continue
                    stats["splitter_pairs_class_i"] += 1
                    context = post(state, roots, (x, y), candidates, lazy, fragments, clock)
                    move = _triple_from_context(
                        state,
                        cap,
                        roots,
                        (x, y),
                        candidates,
                        context,
                        bridge,
                        clock,
                        direct_triple=direct_triple,
                    )
                    if move is not None:
                        return move
            history.record(key, candidates, base, roots, clock)
    if class_ii:
        for root in sorted(base.members, key=lambda r: (base.sizes[r], r)):
            check(clock)
            size = base.sizes[root]
            if size < 2:
                continue
            if max_same_component is not None and size > max_same_component:
                stats["class_ii_size_gated_components"] += 1
                continue
            candidates = core._eligible(state, (root,), cap, clock, saturated)
            if len(candidates) < 3:
                continue
            key = core.family_key(("32II", cap), base, (root,), candidates)
            if history.can_skip(key, candidates, base, (root,), clock):
                continue
            failed = set()
            prefix = (
                _profile_prefix(state, (root,), candidates, clock) if profile_dedup else None
            )
            for deleted in itertools.combinations(sorted(base.members[root]), 2):
                check(clock)
                stats["splitter_pairs_class_ii"] += 1
                context = post(state, (root,), deleted, candidates, lazy, fragments, clock)
                profile = None
                if profile_dedup:
                    profile = failed_profile(
                        state,
                        (root,),
                        candidates,
                        context[0],
                        context[1],
                        clock,
                        prefix=prefix,
                    )
                    if profile in failed:
                        stats["response_failed_profile_hits"] += 1
                        continue
                move = _triple_from_context(
                    state,
                    cap,
                    (root,),
                    deleted,
                    candidates,
                    context,
                    None,
                    clock,
                    direct_triple=direct_triple,
                )
                if move is not None:
                    return move
                if profile is not None:
                    check(clock)
                    failed.add(profile)
                    stats["response_failed_profiles_recorded"] += 1
            history.record(key, candidates, base, (root,), clock)
    return None
