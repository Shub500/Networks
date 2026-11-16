# Python API

`screen_restore` repairs feasible removal sets on fixed, simple undirected graphs.
It uses Python 3.10 or later and the standard library.

```python
from screen_restore import repair, repair_local_pairs, repair_pair_first

adj = ({1, 2}, {0}, {0})
result = repair(adj, cap=1, deleted={1, 2}, seconds=10.0)
cut = result["deletions"]
```

| Function | Search |
|---|---|
| `repair(adj, cap, deleted, seconds=10.0)` | Algorithm 1: screened one-deletion repairs and compatible batches, followed by Class I, Class II, and swap-then-repair |
| `repair_local_pairs(adj, cap, deleted, seconds=30.0)` | Component-local delete-first pair repair with RG; the Layer-1 control in the matched comparisons |
| `repair_pair_first(adj, cap, deleted, seconds=30.0)` | Pair-first low-link repair with merged-size screening, state reuse, and RG |

The two pair-repair functions evaluate the same feasible `(2,1)` move relation.
Their traversal orders differ and can reach different final plans.
The full `repair` policy uses a Class-II component-size limit of 35 and publishes
a compatible batch after every eight new component proposals. Its fixed settings
are written in `_ALGORITHM_OPTIONS` in `screen_restore/__init__.py`.

## Inputs and outputs

`adj` is an adjacency sequence indexed `0..n-1`; `cap` is a positive integer;
`deleted` is a feasible deleted-vertex iterable. Use the `node_base` recorded in
`data/datasets.json` when converting source-file IDs. Keep `adj` unchanged during
a call. The optional keyword `clock` supplies a shared clock.

Results contain `deletions`, `removed`, `trace`, `stop`, `closure`, `counters`, and
wall, CPU, and charged seconds. The full method also returns per-phase times and
cache counters. Every returned plan is feasible and has no more deletions than
the input. `closure` records completed searches; a time-limited call returns its
last verified plan. Time includes graph and input verification, search, and final
plan verification; construction of the supplied starting plan is separate.

## Building blocks

| Operation | Module |
|---|---|
| `PairContext`, `candidate_menu` | `screen_restore.incidence` |
| `ComponentFragmentIndex`, `LocalDeleteState`, `feasible_moves` | `screen_restore.local` |
| `ResponseStore` | `screen_restore.responses` |
| `quotient_load`, `SafeHistory`, `ChargedClock`, `physical_components` | `screen_restore.core` |
| `pair_exchange`, `reverse_greedy` | `screen_restore.pair_bags` |

`pair_exchange` is the pair-first routine used inside the larger-graph pipeline;
its caller supplies the shared clock and acceptance callback.
`screen_restore.incidence.repair(..., fused=False, incremental=False)` is the
unscreened, rebuilt-state control. Internal engine options retain the component
ablations; the top-level `repair` call selects the fixed policy above.

## Recorded plans

`run_plans.py GRAPH_FOLDER core|pair_closed|larger [SECONDS]` loads the graphs,
replays the starting cuts in `data/plans.json`, and compares sizes and proposal
counts with `data/expected.json`. Source graphs are obtained using the URLs and
preprocessing in `data/datasets.json`.

The paper used CPython 3.14 on Linux. A completed deterministic search can be
compared by its endpoint and counters. A time-limited search depends on machine
load and interpreter speed, so the script separates completed and timed-out runs.
