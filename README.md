# Screen then Restore: An Efficient Method for Repairing Cap-Constrained Network Dismantling Plans

Screen then Restore reduces a feasible vertex-removal set while keeping every
remaining connected component within a prescribed size cap. Merged-size
screening, exact fragment summaries, and compatible batches make coordinated
restoration practical after single-vertex restoration has stopped.

## Contents

```text
data/datasets.json       graph sources, preprocessing, and checksums
data/protocol.json       caps, cohorts, budgets, and fixed method settings
data/plans.json          starting removal sets
data/expected.json       recorded sizes and candidate counts
implementation/          Python library and plan replay script
theory/proofs.md         definitions and complete proofs
```

## Use

Requires Python 3.10 or later; no external Python packages are needed.
Put `implementation` on the Python import path, then call:

```python
from screen_restore import repair

adj = ({1, 2}, {0}, {0})
result = repair(adj, cap=1, deleted={1, 2}, seconds=10.0)
print(result["deletions"])
```

The graph is a fixed simple undirected adjacency indexed from zero.
The input removal set must satisfy the cap. Returned plans are verified by
connected-component traversal. See `implementation/API.md` for the three
repair entry points and result fields.

## Data and replay

Download the files listed in `data/datasets.json` into one folder.
The loader checks the graph hashes and edge counts before replay.

```text
python -B implementation/run_plans.py GRAPH_FOLDER core
python -B implementation/run_plans.py GRAPH_FOLDER pair_closed
python -B implementation/run_plans.py GRAPH_FOLDER larger
```

The core cohort has 50 starts: 14 Core/Mass+RG, 9 IG+ with RG, and 27
MACC-CNP+RG. The continuation cohort contains all 73 distinct closed endpoints
from the comparison of pair-repair implementations. The larger cohort has
18 starts on three graphs after the construction and pair-repair pipeline.

## Paper map

| Paper | Files |
|---|---|
| Section 2 and Propositions 1-3 | `theory/proofs.md` |
| Algorithm 1 | `screen_restore.repair`; `data/protocol.json` |
| Table 1 | The 14 Core/Mass+RG records in `data/plans.json` and `data/expected.json` |
| Supplied-plan comparison | All 50 `core` records, including IG+ and MACC-CNP starts |
| Pair-closed continuation | All 73 `pair_closed` records |
| Matched 25-second continuation | All 18 `larger` records; Layer 1 and both layers start from the same saved plan |
| Pair-screening study | `screen_restore.incidence`; core replay |
| Component-local evaluation | `screen_restore.repair_local_pairs` |
| Table 2 pair-repair operator | `screen_restore.pair_exchange`; its 120-second pipeline produces the `larger` starting plans |

Replay uses the recorded time limits. Completed searches permit endpoint and
count comparisons; runs stopped by their time limit can differ with hardware
and interpreter speed. The replay script reports these cases separately.
