
from collections import Counter
from dataclasses import dataclass
from . import core
from .history_groups import GroupedSafeHistory, _local_members


def _limit(value, name):
    if value is not None and (type(value) is not int or value < 0):
        raise ValueError(name + " must be a nonnegative integer or None")


def _references(certificate):
    if isinstance(certificate, PrivateMassCertificate):
        return (
            len(certificate.candidates)
            + sum(map(len, certificate.local))
            + sum(map(len, certificate.shared_external))
            + sum((len(members) for _, members in certificate.private_external))
        )
    candidates, local, external = certificate
    return len(candidates) + sum(map(len, local)) + len(external)


class BoundedSafeHistory(GroupedSafeHistory):

    def __init__(
        self,
        adj,
        enabled=True,
        counters=None,
        cap=None,
        *,
        max_records=None,
        max_vertex_refs=None
    ):
        _limit(max_records, "max_records")
        _limit(max_vertex_refs, "max_vertex_refs")
        super().__init__(adj, enabled, counters, cap)
        self.max_records = max_records
        self.max_vertex_refs = max_vertex_refs
        self.vertex_refs = 0
        self._sizes = {}

    def _remove(self, key, *, eviction=False):
        del self.records[key]
        self.vertex_refs -= self._sizes.pop(key)
        if eviction:
            self.stats["history_capacity_evictions"] += 1
        self._gauges()

    def _gauges(self):
        self.stats["history_current_records"] = len(self.records)
        self.stats["history_current_certificate_vertex_refs"] = self.vertex_refs
        self.stats["history_peak_records"] = max(
            self.stats["history_peak_records"], len(self.records)
        )
        self.stats["history_peak_certificate_vertex_refs"] = max(
            self.stats["history_peak_certificate_vertex_refs"], self.vertex_refs
        )

    def record(self, key, candidates, base, excluded_roots, clock=None):
        if not self.enabled:
            return
        core.check(clock)
        if self.max_records == 0:
            self.stats["history_capacity_refusals"] += 1
            return
        self.bind_graph(base.adj, clock)
        staging = GroupedSafeHistory(self.adj, True, self.stats, self.cap)
        staging.record(key, candidates, base, excluded_roots, clock)
        certificate = staging.records[key]
        return self._put_certificate(key, certificate, clock)

    def _put_certificate(self, key, certificate, clock):
        refs = _references(certificate)
        core.check(clock)
        if self.max_records == 0 or (
            self.max_vertex_refs is not None and refs > self.max_vertex_refs
        ):
            self.stats["history_capacity_refusals"] += 1
            return False
        if key in self.records:
            self._remove(key)
            self.stats["history_capacity_replacements"] += 1
        while self.records and (
            self.max_records is not None
            and len(self.records) >= self.max_records
            or (
                self.max_vertex_refs is not None
                and self.vertex_refs + refs > self.max_vertex_refs
            )
        ):
            core.check(clock)
            self._remove(next(iter(self.records)), eviction=True)
        core.check(clock)
        self.records[key] = certificate
        self._sizes[key] = refs
        self.vertex_refs += refs
        self._gauges()
        self.stats["history_capacity_records_admitted"] += 1
        return True


@dataclass(frozen=True)
class PrivateMassCertificate:
    adj: tuple
    cap: int
    candidates: tuple
    local: tuple
    deleted_per_root: tuple
    restored_count: int
    margin: int
    trials: int
    shared_external: tuple
    private_external: tuple
    proof_kind: str = "exhaustive_physical_reference"
    actual_pair_checks: int = 0


def _external_dependencies(base, roots, candidates, clock):
    touches = {}
    for u in candidates:
        core.check(clock)
        for root in base.signatures[u]:
            core.check(clock)
            if root not in roots:
                touches.setdefault(root, []).append(u)
    shared, private = ([], [])
    for root, endpoints in touches.items():
        core.check(clock)
        members = frozenset(base.members[root])
        if len(endpoints) > 1:
            shared.append(members)
        else:
            private.append((endpoints[0], members))
    return (tuple(shared), tuple(private))


def _complete_pair_margin(base, root, candidates, rows, clock):
    core.check(clock)
    if root not in base.members or set(rows) != set(base.members[root]):
        return None
    n = len(candidates)
    if n < 2:
        return None
    margin, evaluated = (None, 0)
    for x in sorted(rows):
        core.check(clock)
        row = rows[x]
        if not isinstance(row, dict) or row.get("complete") is not True:
            return None
        rescued = row.get("rescued_count")
        checked = row.get("evaluated_pairs")
        if (
            type(row.get("candidate_count")) is not int
            or row["candidate_count"] != n
            or type(rescued) is not int
            or (not 0 <= rescued <= n)
            or (type(checked) is not int)
            or (checked != rescued * (rescued - 1) // 2)
            or (type(row.get("feasible_pairs")) is not int)
            or (row["feasible_pairs"] != 0)
        ):
            return None
        single, pair = (row.get("min_single_deficit"), row.get("min_pair_deficit"))
        minima = []
        if rescued < n:
            if type(single) is not int or single < 1:
                return None
            minima.append(single)
        elif single is not None:
            return None
        if rescued >= 2:
            if type(pair) is not int or pair < 1:
                return None
            minima.append(pair)
        elif pair is not None:
            return None
        if not minima:
            return None
        row_margin = min(minima)
        margin = row_margin if margin is None else min(margin, row_margin)
        evaluated += checked
    core.check(clock)
    return (margin, evaluated, len(rows) * n * (n - 1) // 2)


class PrivateMassHistory(BoundedSafeHistory):

    def record_private_mass21(
        self, key, candidates, base, root, splitter_summaries, clock=None
    ):
        if not self.enabled:
            return False
        core.check(clock)
        if self.max_records == 0:
            self.stats["history_capacity_refusals"] += 1
            return False
        if type(self.cap) is not int or self.cap < 1:
            raise ValueError("bind the positive cap before recording a margin")
        self.bind_graph(base.adj, clock)
        candidates = tuple(sorted(candidates))
        if len(set(candidates)) != len(candidates) or not set(candidates) <= base.cut:
            raise ValueError("distinct currently deleted candidates required")
        if key != core.family_key(("21", self.cap), base, (root,), candidates):
            raise ValueError("private margin key must bind the exact (2,1) family")
        proof = _complete_pair_margin(base, root, candidates, splitter_summaries, clock)
        if proof is None:
            self.stats["private_margin_coverage_refusals"] += 1
            return False
        margin, pair_checks, logical_trials = proof
        local = _local_members(base, (root,), clock)
        shared, private = _external_dependencies(base, (root,), candidates, clock)
        certificate = PrivateMassCertificate(
            self.adj,
            self.cap,
            candidates,
            local,
            (1,),
            2,
            margin,
            logical_trials,
            shared,
            private,
            "complete_single_pair_cover",
            pair_checks,
        )
        core.check(clock)
        self.stats["private_margin_completed_splitters"] += len(splitter_summaries)
        self.stats["private_margin_covered_pair_trials"] += logical_trials
        self.stats["private_margin_actual_pair_checks"] += pair_checks
        if self._put_certificate(key, certificate, clock):
            self.stats["private_margin_certificates_admitted"] += 1
            return True
        return False

    def can_skip(self, key, candidates, base, excluded_roots, clock=None):
        if not self.enabled or key not in self.records:
            return False
        certificate = self.records[key]
        if not isinstance(certificate, PrivateMassCertificate):
            return super().can_skip(key, candidates, base, excluded_roots, clock)
        core.check(clock)
        if private_mass_can_skip(
            certificate,
            base,
            excluded_roots,
            candidates,
            self.cap,
            restored_count=2,
            clock=clock,
            counters=self.stats,
        ):
            core.check(clock)
            self.stats["history_safe_hits"] += 1
            self.stats["history_private_mass_hits"] += 1
            return True
        return False


def private_mass_can_skip(
    certificate,
    base,
    roots,
    candidates,
    cap,
    *,
    deleted_per_root=None,
    restored_count=None,
    clock=None,
    counters=None
):
    stats = counters if counters is not None else Counter()
    if not isinstance(certificate, PrivateMassCertificate):
        raise TypeError("requires a complete declared-family certificate")
    core.check(clock)
    if type(cap) is not int or cap != certificate.cap:
        return False
    binder = core.SafeHistory(certificate.adj, cap=cap)
    binder.bind_graph(base.adj, clock)
    roots = tuple(roots)
    if len(set(roots)) != len(roots) or any((r not in base.members for r in roots)):
        return False
    if _local_members(base, roots, clock) != certificate.local:
        return False
    if tuple(sorted(candidates)) != certificate.candidates:
        return False
    if any((u not in base.cut for u in certificate.candidates)):
        return False
    counts = (1,) * len(roots) if deleted_per_root is None else tuple(deleted_per_root)
    if len(counts) != len(roots):
        return False
    if any((type(count) is not int or count < 1 for count in counts)):
        return False
    counts = tuple(
        (
            count
            for _, count in sorted(
                zip(roots, counts),
                key=lambda row: (min(base.members[row[0]]), len(base.members[row[0]])),
            )
        )
    )
    if counts != certificate.deleted_per_root:
        return False
    if restored_count is None:
        restored_count = certificate.restored_count
    if type(restored_count) is not int or restored_count != certificate.restored_count:
        return False
    for members in certificate.shared_external:
        core.check(clock)
        if not members.isdisjoint(base.cut):
            stats["private_margin_shared_invalidations"] += 1
            return False
        core.check(clock)
    losses = Counter()
    for u, members in certificate.private_external:
        core.check(clock)
        if not members.isdisjoint(base.cut):
            losses[u] += len(members)
        core.check(clock)
    bound = sum(sorted(losses.values(), reverse=True)[:restored_count])
    core.check(clock)
    if bound < certificate.margin:
        stats["private_margin_safe_hits"] += 1
        stats["private_margin_bound_mass"] += bound
        return True
    stats["private_margin_loss_invalidations"] += 1
    return False
