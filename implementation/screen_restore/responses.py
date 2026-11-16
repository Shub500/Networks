
from collections import Counter
from . import core
from .scalar_responses import ResponseStore as PreviousResponseStore


class ResponseStore(PreviousResponseStore):

    def __init__(
        self,
        adj,
        stats=None,
        enabled=True,
        max_components=None,
        *,
        scalar_first=False,
        rescued_signatures=False,
        cap=None,
        clock=None,
        max_verified_graphs=16
    ):
        if type(enabled) is not bool:
            raise ValueError("enabled must be boolean")
        if type(max_verified_graphs) is not int or max_verified_graphs < 1:
            raise ValueError("max_verified_graphs must be a positive integer")
        if type(rescued_signatures) is not bool:
            raise ValueError("rescued_signatures must be boolean")
        if rescued_signatures and scalar_first is not True:
            raise ValueError("rescued signatures require scalar_first")
        self.stats = stats if stats is not None else Counter()
        self.cap = None
        self._validate_cap(cap)
        self.max_verified_graphs = max_verified_graphs
        self._verified_graphs = {}
        graph = self._snapshot_and_validate(adj, clock)
        super().__init__(graph, self.stats, enabled, max_components, scalar_first=scalar_first)
        self.rescued_signatures = rescued_signatures
        self.cap = cap

    def _validate_cap(self, cap):
        if cap is None:
            return
        if type(cap) is not int or cap < 1:
            raise ValueError("response cache cap must be a positive integer")
        if self.cap is not None and self.cap != cap:
            raise ValueError("response cache cannot cross caps")

    def _snapshot_and_validate(self, adj, clock):
        immutable = type(adj) is tuple
        rows = []
        for row in adj:
            core.check(clock)
            immutable = immutable and type(row) is frozenset
            if type(row) is frozenset:
                rows.append(row)
            else:
                values = []
                for value in row:
                    core.check(clock)
                    values.append(value)
                rows.append(frozenset(values))
        graph = adj if immutable else tuple(rows)
        for vertex, row in enumerate(graph):
            core.check(clock)
            self.stats["response_binding_initial_rows"] += 1
            if vertex in row:
                raise ValueError("invalid undirected simple adjacency")
            for neighbor in row:
                core.check(clock)
                self.stats["response_binding_initial_entries"] += 1
                if type(neighbor) is not int or not 0 <= neighbor < len(graph):
                    raise ValueError("invalid undirected simple adjacency")
                if vertex not in graph[neighbor]:
                    raise ValueError("asymmetric adjacency")
        core.check(clock)
        return graph

    def bind_graph(self, adj, cap=None, clock=None):
        self.stats["response_binding_calls"] += 1
        self._validate_cap(cap)
        core.check(clock)
        verified_alias = None
        checked_mutable = False
        if adj is self.adj:
            self.stats["response_binding_canonical_hits"] += 1
        elif self._verified_graphs.get(id(adj)) is adj:
            self.stats["response_binding_alias_hits"] += 1
        else:
            immutable = type(adj) is tuple and all((type(row) is frozenset for row in adj))
            if immutable:
                rows = adj
            else:
                snapshots = []
                for row in adj:
                    core.check(clock)
                    values = []
                    for value in row:
                        core.check(clock)
                        if type(value) is not int:
                            self.stats["response_binding_mismatches"] += 1
                            raise ValueError("response cache requires integer vertices")
                        values.append(value)
                    snapshots.append(frozenset(values))
                rows = tuple(snapshots)
            if len(rows) != len(self.adj):
                self.stats["response_binding_mismatches"] += 1
                raise ValueError("response cache cannot cross graphs")
            for old_row, row in zip(self.adj, rows):
                core.check(clock)
                self.stats["response_binding_rows_compared"] += 1
                if old_row is row:
                    continue
                values = []
                for value in row:
                    core.check(clock)
                    self.stats["response_binding_entries_compared"] += 1
                    if type(value) is not int:
                        self.stats["response_binding_mismatches"] += 1
                        raise ValueError("response cache requires integer vertices")
                    values.append(value)
                if old_row != frozenset(values):
                    self.stats["response_binding_mismatches"] += 1
                    raise ValueError("response cache cannot cross graphs")
            core.check(clock)
            if immutable:
                verified_alias = adj
            else:
                checked_mutable = True
        core.check(clock)
        if verified_alias is not None:
            while len(self._verified_graphs) >= self.max_verified_graphs:
                self._verified_graphs.pop(next(iter(self._verified_graphs)))
                self.stats["response_binding_aliases_evicted"] += 1
            self._verified_graphs[id(adj)] = adj
            self.stats["response_binding_immutable_graphs_verified"] += 1
        if checked_mutable:
            self.stats["response_binding_mutable_graph_checks"] += 1
        if cap is not None:
            self.cap = cap
        return self.adj

    def bind(self, state, clock=None):
        self.bind_graph(state.adj, getattr(state, "_cap", None), clock)

    def post_trial(self, state, roots, deleted, candidates, lazy, fragment_store, clock):
        roots, deleted, candidates = (tuple(roots), tuple(deleted), tuple(candidates))
        if (
            not self.rescued_signatures
            or not self.enabled
            or (len(roots), len(deleted)) not in ((1, 1), (2, 2))
            or (len(set(roots)) != len(roots))
        ):
            if self.rescued_signatures:
                self.stats["rescued_signature_full_fallbacks"] += 1
            return super().post_trial(
                state, roots, deleted, candidates, lazy, fragment_store, clock
            )
        self.bind(state, clock)
        core.check(clock)
        masses = {u: state.base.masses[u] for u in candidates}
        for root, x in zip(roots, deleted):
            core.check(clock)
            entry = self._entry(state, root, clock)
            if not lazy:
                for endpoint in state.incidence.get(root, ()):
                    core.check(clock)
                    entry["index"].attachment_positions(endpoint, clock)
            for u in candidates:
                core.check(clock)
                if root in state.base.signatures[u]:
                    shed, _ = self._response(state, root, x, u, entry, clock)
                    masses[u] -= shed
                self.stats["scalar_first_mass_entries"] += 1
        rescued = [u for u in candidates if masses[u] <= state._cap]
        sizes = core._OverlaySizes(state.base.sizes, roots)
        if len(rescued) < len(deleted) + 1:
            self.stats["scalar_first_contexts_rejected"] += 1
            self.stats["scalar_first_signature_allocations_avoided"] += len(candidates)
            core.check(clock)
            return (sizes, {}, masses, rescued)
        self.stats["scalar_first_contexts_materialized"] += 1
        self.stats["rescued_signature_contexts"] += 1
        root_set = set(roots)
        signatures = {}
        for u in rescued:
            core.check(clock)
            signatures[u] = set(state.base.signatures[u]) - root_set
        for root, x in zip(roots, deleted):
            core.check(clock)
            fragments, attachments = self.single_context(state, root, x, rescued, lazy, clock)
            sizes.update(fragments)
            for u in rescued:
                core.check(clock)
                signatures[u].update(attachments[u])
        self.stats["rescued_signature_rows_materialized"] += len(rescued)
        self.stats["rescued_signature_rows_avoided"] += len(candidates) - len(rescued)
        self.stats["rescued_mass_recomputations_avoided"] += len(candidates)
        core.check(clock)
        return (sizes, signatures, masses, rescued)
