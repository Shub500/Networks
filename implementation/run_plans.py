
import hashlib
import json
import os
import sys
import zipfile
from screen_restore import repair, repair_local_pairs, repair_pair_first
from screen_restore.incidence import repair as pair_first

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data")


def read(name):
    with open(os.path.join(DATA, name), encoding="utf-8") as handle:
        return json.load(handle)


def load(entry, folder):
    path = os.path.join(folder, entry["url"].rsplit("/", 1)[1])
    member = entry.get("archive_member")
    if member:
        with zipfile.ZipFile(path) as archive:
            raw = archive.read(member)
    else:
        with open(path, "rb") as handle:
            raw = handle.read()
    rows = [
        line.split() for line in raw.decode().splitlines() if line.strip() and line[0] != "%"
    ]
    base = 1 if member else entry["node_base"]
    adj = [set() for _ in range(entry["n"])]
    for row in rows[1:] if member else rows:
        u, v = (int(row[0]) - base, int(row[1]) - base)
        if u != v:
            adj[u].add(v)
            adj[v].add(u)
    if member:
        raw = "".join(
            ("%d %d\n" % (u, v) for u in range(len(adj)) for v in sorted(adj[u]) if u < v)
        ).encode()
    if (
        hashlib.sha256(raw).hexdigest() != entry["sha256"]
        or sum(map(len, adj)) != 2 * entry["m"]
    ):
        raise SystemExit("graph differs from datasets.json: " + path)
    return tuple((frozenset(row) for row in adj))


def main():
    if len(sys.argv) < 3 or sys.argv[2] not in ("core", "pair_closed", "larger"):
        raise SystemExit("usage: run_plans.py GRAPH_FOLDER core|pair_closed|larger [SECONDS]")
    folder, panel = sys.argv[1:3]
    datasets, expected = (read("datasets.json"), read("expected.json"))
    limit = float(sys.argv[3]) if len(sys.argv) > 3 else None
    seconds, pair_seconds = (
        limit or expected["seconds"][panel],
        limit or expected["seconds"]["screening"],
    )
    calls = [
        ("layer1", lambda *plan: repair_local_pairs(*plan, seconds)),
        ("algorithm1", lambda *plan: repair(*plan, seconds)),
    ]
    if panel == "core":
        calls.append(
            (
                "proposals_unscreened",
                lambda *plan: pair_first(*plan, pair_seconds, fused=False, incremental=False),
            )
        )
        calls.append(
            ("proposals_screened", lambda *plan: repair_pair_first(*plan, pair_seconds))
        )
    rows = [
        (plan, want)
        for plan, want in zip(read("plans.json"), expected["plans"])
        if plan["panel"] == panel
    ]
    graphs = {
        graph: load(datasets[graph], folder)
        for graph in dict.fromkeys((plan["graph"] for plan, _ in rows))
    }
    print(
        "%s: %d plans, %d deletions"
        % (panel, len(rows), sum((want["start"] for _, want in rows))),
        flush=True,
    )
    for name, call in calls:
        runs = [call(graphs[plan["graph"]], plan["cap"], plan["deleted"]) for plan, _ in rows]
        done = [run["stop"] != "time_budget" for run in runs]
        if name.startswith("proposals"):
            counts = [run["counters"].get("enumeration_proposals", 0) for run in runs]
            same = sum(
                (
                    ok and count == want[name]
                    for ok, count, (_, want) in zip(done, counts, rows)
                )
            )
            print(
                "%s: %d (expected %d); %d of %d runs finished, %d with the expected count"
                % (
                    name,
                    sum(counts),
                    sum((want[name] for _, want in rows)),
                    sum(done),
                    len(rows),
                    same,
                ),
                flush=True,
            )
            continue
        restored = sum((want["start"] - run["removed"] for run, (_, want) in zip(runs, rows)))
        mean = sum((want["start"] - sum(want[name]) / len(want[name]) for _, want in rows))
        closed = [
            {size for size, ok in zip(want[name], want[name + "_finished"]) if ok}
            for _, want in rows
        ]
        both = [
            run["removed"] in sizes
            for run, ok, sizes in zip(runs, done, closed)
            if ok and sizes
        ]
        print(
            "%s: restored %d (expected %g); %d of %d runs finished; of the %d plans whose expected run finished, %d finished here, %d with the expected size"
            % (
                name,
                restored,
                mean,
                sum(done),
                len(rows),
                sum(map(bool, closed)),
                len(both),
                sum(both),
            ),
            flush=True,
        )


if __name__ == "__main__":
    main()
