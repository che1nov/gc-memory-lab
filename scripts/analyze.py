#!/usr/bin/env python3
"""Summarize the original logs; render a plot from measured values, not a GUI screenshot."""
import csv
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
summary = {}
measurements = {}
for mode in ("leak", "bounded"):
    folder = ROOT / "results" / mode
    rows = []
    with (folder / "heap.csv").open() as source:
        for row in csv.DictReader(source):
            # HotSpot writes its final OOME diagnostic to stdout, after the CSV rows.
            if re.fullmatch(r"\d+\.\d+", row["elapsed_seconds"]):
                rows.append({key: float(value) for key, value in row.items()})
    measurements[mode] = rows
    pauses = []
    for line in (folder / "gc.log").read_text().splitlines():
        match = re.search(r"\[([\d.]+)s\].*GC\((\d+)\) (Pause .*) ([\d.]+)ms$", line)
        if match:
            used = re.search(r"(\d+)M->(\d+)M\((\d+)M\)", line)
            pauses.append(dict(uptime_seconds=float(match[1]), gc_id=int(match[2]),
                               event=match[3], pause_ms=float(match[4]),
                               before_mib=int(used[1]) if used else None,
                               after_mib=int(used[2]) if used else None))
    jstat_lines = (folder / "jstat.txt").read_text().splitlines()
    columns = jstat_lines[0].split()
    jstat = [dict(zip(columns, map(float, line.replace(",", ".").split())))
             for line in jstat_lines[1:] if len(line.split()) == len(columns)]
    stats = dict(samples=len(rows), first_sample=rows[0], last_sample=rows[-1],
                 max_heap_used_mib=max(row["heap_used_bytes"] for row in rows) / 2**20,
                 max_retained_objects=int(max(row["retained_objects"] for row in rows)),
                 gc_pause_count=len(pauses), full_gc_count=sum("Pause Full" in p["event"] for p in pauses),
                 pause_sum_ms=sum(p["pause_ms"] for p in pauses),
                 pause_max_ms=max(p["pause_ms"] for p in pauses), pauses=pauses,
                 jstat_first=jstat[0], jstat_last=jstat[-1])
    viewer = {}
    for line in (folder / "gcviewer.csv").read_text().splitlines():
        key, value, unit = (part.strip() for part in line.split(";"))
        viewer[key] = {"value": value, "unit": unit}
    assert int(viewer["pauseCount"]["value"]) == len(pauses), "GCViewer pause count differs from raw log"
    assert abs(float(viewer["pauseSum"]["value"]) * 1000 - stats["pause_sum_ms"]) < .001
    summary[mode] = stats
assert summary["bounded"]["max_retained_objects"] == 64
assert summary["leak"]["max_retained_objects"] > 1000
assert 60 < summary["leak"]["pauses"][-1]["uptime_seconds"] < 120
(ROOT / "results/analysis.json").write_text(json.dumps(summary, indent=2) + "\n")

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
fig, axes = plt.subplots(2, 1, figsize=(10, 7), sharex=True, layout="constrained")
for mode, label, color in (("leak", "Утечка", "#c43c39"), ("bounded", "Лимит 64 объекта", "#237a57")):
    rows = measurements[mode]
    times = [row["elapsed_seconds"] for row in rows]
    axes[0].plot(times, [row["heap_used_bytes"] / 2**20 for row in rows], label=label, color=color)
    axes[1].plot(times, [row["payload_bytes"] / 2**20 for row in rows], label=label, color=color)
axes[0].axhline(128, linestyle="--", color="#666666", label="Heap max: 128 МиБ")
axes[0].set_title("Фактические замеры heap и удерживаемых массивов")
axes[0].set_ylabel("Занято heap, МиБ")
axes[1].set_ylabel("Данные в коллекции, МиБ")
axes[1].set_xlabel("Время от старта JVM, с")
for axis in axes:
    axis.axvline(70, linestyle=":", color="#888888")
    axis.grid(alpha=.2)
    axis.legend(loc="upper left")
axes[1].text(71, 30, "jcmd: дамп и гистограмма\n(вызывают Full GC)", fontsize=9, color="#555555")
fig.savefig(ROOT / "report/images/heap-comparison.png", dpi=170)
print(json.dumps({mode: {key: value for key, value in stats.items() if key not in
                        ("pauses", "first_sample", "last_sample", "jstat_first", "jstat_last")}
                  for mode, stats in summary.items()}, indent=2))
