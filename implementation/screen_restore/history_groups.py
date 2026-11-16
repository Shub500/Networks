
from . import core


def _local_members(base, roots, clock):
    members = []
    for root in roots:
        core.check(clock)
        members.append(frozenset(base.members[root]))
        core.check(clock)
    result = tuple(sorted(members, key=lambda group: (min(group), len(group))))
    core.check(clock)
    return result


class GroupedSafeHistory(core.SafeHistory):

    def record(self, key, candidates, base, excluded_roots, clock=None):
        if not self.enabled:
            return
        core.check(clock)
        self.bind_graph(base.adj, clock)
        candidates = tuple(sorted(candidates))
        core.check(clock)
        excluded = set(excluded_roots)
        core.check(clock)
        roots = set()
        for u in candidates:
            core.check(clock)
            for root in base.signatures[u]:
                core.check(clock)
                if root not in excluded:
                    roots.add(root)
                    self.stats["history_grouped_external_root_incidents"] += 1
        external = set()
        for root in roots:
            core.check(clock)
            members = base.members[root]
            self.stats["history_grouped_union_calls"] += 1
            self.stats["history_grouped_union_operand_vertices"] += len(members)
            external.update(members)
            core.check(clock)
        local = _local_members(base, excluded, clock)
        core.check(clock)
        immutable_external = frozenset(external)
        core.check(clock)
        certificate = (candidates, local, immutable_external)
        core.check(clock)
        self.records[key] = certificate
        self.stats["history_certificates_recorded"] += 1
        self.stats["history_external_vertices_recorded"] += len(external)
        self.stats["history_grouped_unique_roots_recorded"] += len(roots)

    def can_skip(self, key, candidates, base, excluded_roots, clock=None):
        if not self.enabled or key not in self.records:
            return False
        core.check(clock)
        self.bind_graph(base.adj, clock)
        saved_candidates, local, external = self.records[key]
        now_local = _local_members(base, excluded_roots, clock)
        core.check(clock)
        now_candidates = tuple(sorted(candidates))
        core.check(clock)
        if now_candidates != saved_candidates or now_local != local:
            self.stats["history_identity_invalidations"] += 1
            return False
        for u in saved_candidates:
            core.check(clock)
            if u not in base.cut:
                self.stats["history_candidate_invalidations"] += 1
                return False
        core.check(clock)
        self.stats["history_grouped_disjoint_calls"] += 1
        self.stats["history_grouped_disjoint_external_operand_vertices"] += len(external)
        self.stats["history_grouped_disjoint_cut_operand_vertices"] += len(base.cut)
        unchanged = external.isdisjoint(base.cut)
        core.check(clock)
        if not unchanged:
            self.stats["history_external_loss_invalidations"] += 1
            return False
        core.check(clock)
        self.stats["history_safe_hits"] += 1
        return True
