
from .core import check


def _weight(tokens, sizes, clock):
    total = 0
    for token in tokens:
        check(clock)
        weight = sizes[token]
        if type(weight) is not int or weight <= 0:
            raise ValueError("fragment sizes must be positive integers")
        total += weight
    return total


def triple_load(adj, u, v, w, signatures, sizes, clock=None):
    check(clock)
    if len({u, v, w}) != 3:
        raise ValueError("triple endpoints must be distinct")
    a, b, c = (signatures[u], signatures[v], signatures[w])
    uv = v in adj[u] or not a.isdisjoint(b)
    check(clock)
    uw = w in adj[u] or not a.isdisjoint(c)
    check(clock)
    vw = w in adj[v] or not b.isdisjoint(c)
    check(clock)
    connected_edges = int(uv) + int(uw) + int(vw)
    if connected_edges >= 2:
        load = 3 + _weight(a | b | c, sizes, clock)
    elif uv:
        load = max(2 + _weight(a | b, sizes, clock), 1 + _weight(c, sizes, clock))
    elif uw:
        load = max(2 + _weight(a | c, sizes, clock), 1 + _weight(b, sizes, clock))
    elif vw:
        load = max(2 + _weight(b | c, sizes, clock), 1 + _weight(a, sizes, clock))
    else:
        load = max(
            1 + _weight(a, sizes, clock),
            1 + _weight(b, sizes, clock),
            1 + _weight(c, sizes, clock),
        )
    check(clock)
    return load
