#!/usr/bin/env python3
"""Run a UI performance scenario against an application built with harness/perfdriver.

    perfdrive.py --app sample-app/build/SampleApp --scenario scenarios/sample_app.json \
                 --lane headless --repeats 5 --out results/linux-headless.json

The application is started with --perf-driver and spoken to over its stdin/stdout
(newline-delimited JSON, replies prefixed "@perf "). One warm-up run is discarded, then the
scenario is repeated and every metric is reported as median / p95 / min / max.
Standard library only, so it runs on any Jenkins agent with Python 3.8+.
"""
import argparse
import json
import os
import platform
import queue
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone

LANE_ENV = {
    # Owns its display: works in Windows Session 0, locked sessions, containers.
    "headless": {
        "QT_QPA_PLATFORM": "offscreen",
        "QT_SCALE_FACTOR": "1",
        "QSG_RHI_PREFER_SOFTWARE_RENDERER": "1",
        "LIBGL_ALWAYS_SOFTWARE": "1",
    },
    # Real platform plugin; needs a prepared agent (docs/agents.md).
    "display": {
        "QT_SCALE_FACTOR": "1",
    },
}


class ProtocolError(RuntimeError):
    pass


def percentile(values, p):
    values = sorted(values)
    index = int(round(p * (len(values) - 1)))
    return values[min(index, len(values) - 1)]


class App:
    """One application process under the perf driver."""

    def __init__(self, exe, args, env):
        self.started = time.perf_counter()
        self.proc = subprocess.Popen(
            [exe, "--perf-driver", *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None,
            text=True, bufsize=1, env=env)
        self._lines = queue.Queue()
        self._next_id = 0
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self):
        for line in self.proc.stdout:
            if line.startswith("@perf "):
                try:
                    self._lines.put(json.loads(line[6:]))
                except json.JSONDecodeError:
                    pass
        self._lines.put(None)

    def _next(self, timeout):
        try:
            return self._lines.get(timeout=timeout)
        except queue.Empty:
            raise ProtocolError("no reply from the application within %.0f s" % timeout)

    def wait_ready(self, timeout=30.0):
        msg = self._next(timeout)
        if not msg or msg.get("event") != "ready":
            raise ProtocolError("application did not report ready (was it built with the perf driver?)")
        return msg

    def call(self, op, timeout=15.0, **fields):
        self._next_id += 1
        cmd = {"id": self._next_id, "op": op}
        cmd.update(fields)
        self.proc.stdin.write(json.dumps(cmd) + "\n")
        self.proc.stdin.flush()
        while True:
            msg = self._next(timeout)
            if msg is None:
                raise ProtocolError("application exited during '%s'" % op)
            if msg.get("id") == self._next_id:
                break
        if not msg.get("ok", False):
            raise ProtocolError("%s failed: %s" % (op, msg.get("error")))
        return msg

    def rss_mib(self):
        pid = self.proc.pid
        if sys.platform.startswith("linux"):
            with open("/proc/%d/status" % pid) as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1]) / 1024.0
        elif sys.platform == "win32":
            import ctypes
            import ctypes.wintypes as wt

            class PMC(ctypes.Structure):
                _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                            ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                            ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return None
            try:
                pmc = PMC()
                pmc.cb = ctypes.sizeof(PMC)
                if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb):
                    return pmc.WorkingSetSize / 1048576.0
            finally:
                ctypes.windll.kernel32.CloseHandle(handle)
        return None

    def close(self, timeout=10.0):
        try:
            self.call("quit", timeout=5.0)
        except ProtocolError:
            pass
        try:
            self.proc.wait(timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait()
        return self.proc.returncode


def run_once(exe, scenario, env):
    """Plays the scenario once; returns {metric_name: value}."""
    metrics = {}
    app = None
    launched_at = None

    def record(name, value):
        if name and value is not None:
            metrics[name] = value

    def record_series(name, values):
        values = [v for v in values if v is not None]
        if name and values:
            metrics[name] = statistics.median(values)
            metrics[name + ".p95"] = percentile(values, 0.95)
            metrics[name + ".max"] = max(values)

    try:
        for step in scenario["steps"]:
            op = step["op"]
            mark = step.get("mark")
            if op == "launch":
                launched_at = time.perf_counter()
                app = App(exe, scenario.get("app_args", []), env)
                app.wait_ready()
                continue
            if app is None:
                raise ProtocolError("the first step must be 'launch'")
            if op == "wait_first_frame":
                r = app.call("wait_first_frame", timeout=step.get("timeout_s", 30))
                record(mark, r["first_paint_ms"])
                record((mark or "startup") + ".wall", (time.perf_counter() - launched_at) * 1000.0)
            elif op == "wait_idle":
                app.call("wait_idle", ms=step.get("ms", 300))
            elif op == "click":
                r = app.call("click", object=step["object"], timeout_ms=step.get("timeout_ms", 1000))
                record(mark, r.get("paint_ms"))
            elif op in ("key", "wheel"):
                samples = []
                for _ in range(int(step.get("times", 1))):
                    if op == "key":
                        r = app.call("key", object=step["object"], keys=step.get("keys", []),
                                     text=step.get("text", ""), timeout_ms=step.get("timeout_ms", 1000))
                    else:
                        r = app.call("wheel", object=step["object"], delta=step.get("delta", -120),
                                     axis=step.get("axis", "y"), timeout_ms=step.get("timeout_ms", 1000))
                    samples.append(r.get("paint_ms"))
                record_series(mark, samples)
            elif op == "get":
                prop = step.get("property", "text")
                r = app.call("get", object=step["object"], property=prop)
                if "expect" in step and r["value"] != step["expect"]:
                    raise ProtocolError("%s.%s is %r, expected %r" % (step["object"], prop, r["value"], step["expect"]))
            elif op == "mark":
                metric = step.get("metric", "time")
                if metric == "rss":
                    record(step["name"], app.rss_mib())
                else:
                    record(step["name"], app.call("mark")["t"])
            elif op == "stats":
                r = app.call("stats", reset=bool(step.get("reset", False)))
                prefix = mark or "jank"
                record(prefix + ".p95", r["jank"]["p95"])
                record(prefix + ".max", r["jank"]["max"])
                record(prefix + ".over_50ms", r["jank"]["over_50ms"])
                # Qt Quick windows: frame count, pacing and fps since the last reset
                # (frameSwapped timestamps). Empty for Widgets-only applications.
                for window in r.get("frames", []):
                    name = "frames." + (window.get("window") or "window")
                    for field in ("count", "fps", "interval_p50", "interval_p95", "interval_max"):
                        record(name + "." + field, window.get(field))
            elif op == "tree":
                r = app.call("tree", depth=int(step.get("depth", 8)), **({"window": step["window"]} if "window" in step else {}))
                print(format_tree(r["nodes"]), file=sys.stderr)
            elif op == "quit":
                code = app.close()
                app = None
                if code != 0:
                    raise ProtocolError("application exited with code %s" % code)
            else:
                raise ProtocolError("unknown op '%s'" % op)
    finally:
        if app is not None:
            app.close()
    return metrics


def format_tree(nodes):
    """Renders a 'tree' reply (flat, depth-annotated nodes) as an indented listing."""
    lines = []
    for node in nodes:
        line = "  " * node.get("depth", 0) + node.get("class", "?")
        if node.get("name"):
            line += ' "%s"' % node["name"]
        if node.get("text"):
            line += " text=%r" % node["text"]
        if node.get("geometry"):
            line += " [%s]" % ",".join(str(v) for v in node["geometry"])
        if node.get("visible") is False:
            line += " (hidden)"
        lines.append(line)
    return "\n".join(lines)


def dump_tree(exe, scenario, env, depth):
    """Starts the app, waits for its first frame and prints the object tree: how to find
    the addresses for a scenario in an application that sets few objectNames."""
    app = App(exe, scenario.get("app_args", []), env)
    try:
        app.wait_ready()
        app.call("wait_first_frame", timeout=30)
        app.call("wait_idle", ms=300)
        r = app.call("tree", depth=depth)
        print(format_tree(r["nodes"]))
        if r.get("truncated"):
            print("... (truncated; use --tree-depth or the 'window' field to narrow down)")
    finally:
        app.close()


def aggregate(runs):
    names = []
    for run in runs:
        for name in run:
            if name not in names:
                names.append(name)
    out = {}
    for name in names:
        values = [run[name] for run in runs if name in run]
        out[name] = {
            "values": values,
            "median": statistics.median(values),
            "p95": percentile(values, 0.95),
            "min": min(values),
            "max": max(values),
        }
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--app", required=True, help="application executable built with the perf driver")
    ap.add_argument("--scenario", help="scenario JSON file (required unless --tree)")
    ap.add_argument("--lane", choices=sorted(LANE_ENV), default="headless")
    ap.add_argument("--repeats", type=int, default=5, help="measured runs after the warm-up run")
    ap.add_argument("--no-warmup", action="store_true")
    ap.add_argument("--out", help="write results JSON here")
    ap.add_argument("--tree", action="store_true",
                    help="start the app, print its object tree (widgets and Qt Quick items) and exit")
    ap.add_argument("--tree-depth", type=int, default=8, metavar="N")
    args = ap.parse_args()

    if not args.scenario and not args.tree:
        ap.error("--scenario is required (or --tree)")
    scenario = {}
    if args.scenario:
        with open(args.scenario) as f:
            scenario = json.load(f)
    env = dict(os.environ)
    env.update(LANE_ENV[args.lane])
    env.update(scenario.get("env", {}))

    if args.tree:
        try:
            dump_tree(args.app, scenario, env, args.tree_depth)
        except ProtocolError as e:
            print("perfdrive: %s" % e, file=sys.stderr)
            return 3
        return 0

    runs = []
    total = args.repeats + (0 if args.no_warmup else 1)
    try:
        for i in range(total):
            metrics = run_once(args.app, scenario, env)
            if i == 0 and not args.no_warmup:
                print("warm-up run done", file=sys.stderr)
                continue
            runs.append(metrics)
            print("run %d/%d done" % (len(runs), args.repeats), file=sys.stderr)
    except ProtocolError as e:
        print("perfdrive: %s" % e, file=sys.stderr)
        return 3

    summary = aggregate(runs)
    width = max(len(n) for n in summary) if summary else 10
    print("%-*s %10s %10s %10s %10s" % (width, "metric", "median", "p95", "min", "max"))
    for name, s in summary.items():
        print("%-*s %10.2f %10.2f %10.2f %10.2f" % (width, name, s["median"], s["p95"], s["min"], s["max"]))

    if args.out:
        result = {
            "scenario": scenario.get("name", os.path.basename(args.scenario)),
            "app": args.app,
            "lane": args.lane,
            "repeats": args.repeats,
            "host": platform.node(),
            "platform": platform.platform(),
            "env": LANE_ENV[args.lane],
            "time": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "metrics": summary,
        }
        os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
        with open(args.out, "w") as f:
            json.dump(result, f, indent=2)
        print("wrote %s" % args.out, file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
