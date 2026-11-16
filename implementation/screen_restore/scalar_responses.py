
from . import higher_order as prior
from . import core


class ResponseStore(prior.ResponseStore):

    def __init__(
        self, adj, stats=None, enabled=True, max_components=None, *, scalar_first=False
    ):
        if type(scalar_first) is not bool:
            raise ValueError("scalar_first must be boolean")
        super().__init__(adj, stats, enabled, max_components)
        self.scalar_first = scalar_first

    def _entry(self, state, root, clock):
        entry = super()._entry(state, root, clock)
        entry["index"].stats = state.stats
        return entry

    def post_trial(self, state, roots, deleted, candidates, lazy, fragment_store, clock):
        roots, deleted, candidates = (tuple(roots), tuple(deleted), tuple(candidates))
        if (
            not self.scalar_first
            or len(roots) != len(deleted)
            or len(set(roots)) != len(roots)
        ):
            if self.scalar_first:
                self.stats["scalar_first_same_component_fallbacks"] += 1
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
        if len(rescued) < len(deleted) + 1:
            self.stats["scalar_first_contexts_rejected"] += 1
            self.stats["scalar_first_signature_allocations_avoided"] += len(candidates)
            core.check(clock)
            return (core._OverlaySizes(state.base.sizes, roots), {}, masses, rescued)
        self.stats["scalar_first_contexts_materialized"] += 1
        full = super().post_trial(
            state, roots, deleted, candidates, lazy, fragment_store, clock
        )
        if full[2] != masses or full[3] != rescued:
            raise AssertionError("scalar-first masses disagree with exact response")
        return full


find32 = prior.find32
