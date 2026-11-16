
from collections import Counter
from .core import check


def _tokens(signature, clock):
    result = set()
    for token in signature:
        check(clock)
        result.add(token)
    return frozenset(result)


def _mass(tokens, sizes, clock):
    result = 0
    for token in tokens:
        check(clock)
        weight = sizes[token]
        if type(weight) is not int or weight <= 0:
            raise ValueError("quotient fragment weights must be positive integers")
        result += weight
    return result


def _shared(a, b, sizes, clock):
    small, other = (a, b) if len(a) <= len(b) else (b, a)
    result = 0
    for token in small:
        check(clock)
        if token in other:
            weight = sizes[token]
            if type(weight) is not int or weight <= 0:
                raise ValueError("quotient fragment weights must be positive integers")
            result += weight
    return result


def small_pair_load(adj, u, v, signatures, sizes, clock=None):
    check(clock)
    if u == v:
        raise ValueError("pair endpoints must be distinct")
    su, sv = (_tokens(signatures[u], clock), _tokens(signatures[v], clock))
    mu, mv = (1 + _mass(su, sizes, clock), 1 + _mass(sv, sizes, clock))
    shared = _shared(su, sv, sizes, clock)
    load = mu + mv - shared if shared or v in adj[u] else max(mu, mv)
    check(clock)
    return load


class RolloutGroups:

    def __init__(self, adj, signatures, sizes, seed=(), clock=None, counters=None):
        self.adj, self.signatures, self.sizes = (adj, signatures, sizes)
        self.clock = clock
        self.stats = counters if counters is not None else Counter()
        self._state = ((), (), 0)
        check(clock)
        for u in seed:
            check(clock)
            proposal = self._evaluate(u, clock)
            self._commit(u, proposal, clock)
        check(clock)

    @property
    def endpoints(self):
        return self._state[0]

    @property
    def load(self):
        return self._state[2]

    def snapshot(self):
        return self._state

    def _evaluate(self, w, clock):
        check(clock)
        if w in self.endpoints:
            raise ValueError("endpoint is already restored")
        tokens = _tokens(self.signatures[w], clock)
        merged_load = 1 + _mass(tokens, self.sizes, clock)
        touched, outside_max = ([], 0)
        for index, (endpoints, old_tokens, load) in enumerate(self._state[1]):
            check(clock)
            self.stats["incremental_quotient_groups_examined"] += 1
            shared = _shared(tokens, old_tokens, self.sizes, clock)
            connected = bool(shared)
            if not connected:
                for v in endpoints:
                    check(clock)
                    self.stats["incremental_quotient_endpoint_edges_checked"] += 1
                    if v in self.adj[w]:
                        connected = True
                        break
            if connected:
                touched.append(index)
                merged_load += load - shared
            else:
                outside_max = max(outside_max, load)
        check(clock)
        return (tokens, frozenset(touched), merged_load, max(merged_load, outside_max))

    def _commit(self, w, proposal, clock):
        tokens, touched, merged_load, maximum = proposal
        new_endpoints, new_tokens, kept = ({w}, set(tokens), [])
        for index, group in enumerate(self._state[1]):
            check(clock)
            if index in touched:
                for v in group[0]:
                    check(clock)
                    new_endpoints.add(v)
                for token in group[1]:
                    check(clock)
                    new_tokens.add(token)
            else:
                kept.append(group)
        kept.append((frozenset(new_endpoints), frozenset(new_tokens), merged_load))
        replacement = (self.endpoints + (w,), tuple(kept), maximum)
        check(clock)
        self._state = replacement
        self.stats["incremental_quotient_commits"] += 1

    def try_extend(self, w, cap, clock=None):
        if type(cap) is not int or cap < 1:
            raise ValueError("cap must be a positive integer")
        clock = self.clock if clock is None else clock
        check(clock)
        self.stats["incremental_quotient_trials"] += 1
        proposal = self._evaluate(w, clock)
        maximum = proposal[3]
        if maximum > cap:
            check(clock)
            self.stats["incremental_quotient_rejections"] += 1
            return (False, maximum)
        self._commit(w, proposal, clock)
        return (True, maximum)
