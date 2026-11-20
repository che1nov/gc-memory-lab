#!/usr/bin/env python3
"""Run two isolated JVMs with identical allocation rates, collecting original evidence."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--java-home", default=os.environ.get("JAVA_HOME"))
parser.add_argument("--output", default="results")
args = parser.parse_args()
if not args.java_home:
    parser.error("Pass --java-home pointing to JDK 17+")
jdk = Path(args.java_home).resolve() / "bin"
output = (ROOT / args.output).resolve()
output.mkdir(parents=True, exist_ok=True)
if any((output / mode).exists() for mode in ("leak", "bounded")):
    parser.error("Output contains a previous experiment; choose a new --output directory")
(ROOT / "build").mkdir(exist_ok=True)
subprocess.run([str(jdk / "javac"), "--release", "17", "-d", str(ROOT / "build"),
                str(ROOT / "src/MemoryLab.java")], check=True)
java_version = subprocess.run([str(jdk / "java"), "-version"], capture_output=True, text=True, check=True).stderr
runs = []
try:
    for mode in ("leak", "bounded"):
        folder = output / mode
        folder.mkdir()
        streams = [(folder / name).open("w") for name in ("heap.csv", "application.txt", "jstat.txt", "jstat-errors.txt")]
        flags = ["-Xms128m", "-Xmx128m", "-XX:+UseG1GC", "-XX:+ExitOnOutOfMemoryError",
                 "-Xlog:gc*=info:file=gc.log:uptime,level,tags:filecount=0"]
        process = subprocess.Popen([str(jdk / "java"), *flags, "-cp", str(ROOT / "build"),
                                    "MemoryLab", mode, "120"], cwd=folder, stdout=streams[0], stderr=streams[1])
        run = dict(mode=mode, process=process, folder=folder, streams=streams,
                   start=time.monotonic(), flags=flags, dumped=False)
        runs.append(run)
        time.sleep(1)
        run["jstat"] = subprocess.Popen([str(jdk / "jstat"), "-gc", "-t", str(process.pid), "1000"],
                                        stdout=streams[2], stderr=streams[3])
        print(f"Started {mode}: pid={process.pid}", flush=True)
    while any(run["process"].poll() is None for run in runs):
        for run in runs:
            process = run["process"]
            if not run["dumped"] and time.monotonic() - run["start"] >= 70 and process.poll() is None:
                # Relative dump path avoids attach-command quoting issues with spaces in project paths.
                for filename, command in (("heap-dump.txt", ["GC.heap_dump", "heap.hprof"]),
                                          ("histogram.txt", ["GC.class_histogram"]),
                                          ("heap-info.txt", ["GC.heap_info"])):
                    result = subprocess.run([str(jdk / "jcmd"), str(process.pid), *command],
                                            capture_output=True, text=True, timeout=30)
                    (run["folder"] / filename).write_text(result.stdout + result.stderr)
                    if result.returncode:
                        raise RuntimeError(f"jcmd {run['mode']} {command} failed: {result.stderr}")
                run["dumped"] = True
                print(f"Captured dump and histogram: {run['mode']}", flush=True)
        time.sleep(0.5)
finally:
    for run in runs:
        if run["process"].poll() is None:
            run["process"].terminate()
            run["process"].wait(timeout=10)
        monitor = run.get("jstat")
        if monitor and monitor.poll() is None:
            monitor.terminate()
            monitor.wait(timeout=10)
        for stream in run["streams"]:
            stream.close()
summary = {"java_version": java_version, "heap_mib": 128, "chunk_bytes": 65536,
           "allocation_mib_per_second_target": 1.25, "dump_at_seconds_target": 70,
           "duration_seconds_target": 120, "bounded_items": 64,
           "runs": [{"mode": r["mode"], "exit_code": r["process"].returncode,
                     "dump_created": (r["folder"] / "heap.hprof").exists(), "jvm_flags": r["flags"]} for r in runs]}
(output / "experiment.json").write_text(json.dumps(summary, indent=2) + "\n")
assert runs[0]["process"].returncode == 3, "HotSpot must exit on OOME"
assert runs[1]["process"].returncode == 0, "Bounded run must finish normally"
assert all((r["folder"] / "heap.hprof").exists() for r in runs), "Both dumps are required"
print("Experiment completed: leak failed as expected, bounded mode finished normally", flush=True)
