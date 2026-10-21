#!/usr/bin/env python3
"""Compare a perfdrive.py result against a baseline and turn it into a pass/fail.

    compare.py results/linux-headless-sample_app.json \\
               --baseline baselines/linux-headless-sample_app.json \\
               --scenario scenarios/sample_app.json \\
               --junit results/linux-headless-sample_app-junit.xml \\
               --markdown results/linux-headless-sample_app.md --json results/verdict.json

    compare.py results/linux-headless-sample_app.json \\
               --update-baseline baselines/linux-headless-sample_app.json --keep 20 --ref "$GIT_COMMIT"

The baseline is either another perfdrive result file (one run of N repeats, no noise band)
or a *baseline store*: a small JSON file that this script maintains with --update-baseline.
The store keeps the per-metric medians of the last --keep (default 20) green runs, so the
spread of a metric across builds can be learned instead of guessed.

Per metric the current median is compared with the baseline median (for a store: the median
of the stored medians). Thresholds come from the scenario file's "thresholds" block
({"metric": {"unstable_pct": 10, "fail_pct": 25, "higher_is_better": false}}); metrics
without an entry use --default-unstable-pct / --default-fail-pct. Lower is better unless
the entry says "higher_is_better": true.

Noise band. Once the store holds at least --min-runs (default 5) runs of a metric, the band
median +/- --mad-factor (default 3) * MAD of the stored medians is computed and a metric is
only flagged when it is outside BOTH the percentage threshold AND the band. MAD (median
absolute deviation) was chosen over a bootstrap interval because it is deterministic (no
random seed to argue about in a CI log), is unaffected by the one or two outlier runs that
every perf history collects, and is meaningful at 5 samples where a bootstrap of the median
is just a handful of distinct values. 3 * MAD is roughly 2 sigma for normal noise, i.e. the
band is deliberately narrower than the usual 3 sigma: it is a second opinion that saves a
noisy metric from crying wolf, not a replacement for the percentage threshold. When all
stored medians are equal the MAD is 0, the band collapses to a point and the percentage
threshold alone decides.

Verdicts: ok, unstable (over unstable_pct), fail (over fail_pct), new (metric not in the
baseline; informational), missing (metric in the baseline but not in the current result;
counts as unstable). Exit code: 0 ok, 1 unstable, 2 fail, 3 usage or input error.
Standard library only, Python 3.8+.
"""
import argparse
import json
import os
import statistics
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

STORE_KIND = "qt-ui-perf-baseline-store"
EXIT_OK, EXIT_UNSTABLE, EXIT_FAIL, EXIT_USAGE = 0, 1, 2, 3
VERDICT_EXIT = {"ok": EXIT_OK, "new": EXIT_OK, "unstable": EXIT_UNSTABLE,
                "missing": EXIT_UNSTABLE, "fail": EXIT_FAIL}


class UsageError(Exception):
    pass


def load_json(path, what):
    try:
        with open(path) as f:
            return json.load(f)
    except OSError as e:
        raise UsageError("cannot read %s %s: %s" % (what, path, e.strerror))
    except ValueError as e:
        raise UsageError("%s %s is not valid JSON: %s" % (what, path, e))


def load_result(path):
    """A perfdrive.py result; returns the whole document after checking its shape."""
    doc = load_json(path, "result")
    metrics = doc.get("metrics") if isinstance(doc, dict) else None
    if not isinstance(metrics, dict):
        raise UsageError("%s has no 'metrics' object (is it a perfdrive.py result?)" % path)
    for name, entry in metrics.items():
        if not isinstance(entry, dict) or "median" not in entry:
            raise UsageError("%s: metric %r has no 'median'" % (path, name))
    return doc


def result_medians(doc):
    return {name: float(entry["median"]) for name, entry in doc["metrics"].items()}


def is_store(doc):
    return isinstance(doc, dict) and doc.get("kind") == STORE_KIND


def load_baseline(path):
    """Returns {metric: [median, ...]} (one entry per stored run) and the run count."""
    doc = load_json(path, "baseline")
    if is_store(doc):
        runs = doc.get("runs")
        if not isinstance(runs, list):
            raise UsageError("%s: baseline store has no 'runs' list" % path)
        history = {}
        for run in runs:
            for name, median in run.get("metrics", {}).items():
                history.setdefault(name, []).append(float(median))
        return history, len(runs)
    if not isinstance(doc, dict) or not isinstance(doc.get("metrics"), dict):
        raise UsageError("%s is neither a perfdrive.py result nor a baseline store" % path)
    return {name: [float(entry["median"])] for name, entry in doc["metrics"].items()}, 1


def load_thresholds(path):
    doc = load_json(path, "scenario")
    thresholds = doc.get("thresholds", {}) if isinstance(doc, dict) else None
    if not isinstance(thresholds, dict):
        raise UsageError("%s: 'thresholds' must be an object" % path)
    return thresholds


def threshold_for(name, thresholds, default_unstable, default_fail):
    entry = thresholds.get(name, {})
    return {
        "unstable_pct": float(entry.get("unstable_pct", default_unstable)),
        "fail_pct": float(entry.get("fail_pct", default_fail)),
        "higher_is_better": bool(entry.get("higher_is_better", False)),
    }


def noise_band(history, min_runs, mad_factor):
    """(low, high) around the median of the stored medians, or None with too few runs."""
    if len(history) < min_runs:
        return None
    centre = statistics.median(history)
    mad = statistics.median(abs(v - centre) for v in history)
    return (centre - mad_factor * mad, centre + mad_factor * mad)


def judge(baseline, current, band, th):
    """Verdict for one metric. Returns (verdict, delta_pct, note)."""
    hib = th["higher_is_better"]
    if baseline is None:
        return "new", None, "not in baseline"
    if current is None:
        return "missing", None, "not in current result"
    if baseline == 0:
        worse = current < 0 if hib else current > 0
        if not worse:
            return "ok", None, ""
        return "unstable", None, "baseline is 0, relative change undefined"
    delta = (current - baseline) / abs(baseline) * 100.0
    regression = -delta if hib else delta
    if regression > th["fail_pct"]:
        verdict = "fail"
    elif regression > th["unstable_pct"]:
        verdict = "unstable"
    else:
        return "ok", delta, ""
    if band is not None:
        low, high = band
        inside = current >= low if hib else current <= high
        if inside:
            return "ok", delta, "over %s but within noise band" % verdict
    return verdict, delta, "over %.0f %%" % (th["fail_pct"] if verdict == "fail" else th["unstable_pct"])


def compare(current, history, thresholds, default_unstable=10.0, default_fail=25.0,
            min_runs=5, mad_factor=3.0):
    """current: {metric: median}; history: {metric: [median, ...]}. Returns a list of rows."""
    names = list(current)
    names += [n for n in history if n not in current]
    rows = []
    for name in names:
        th = threshold_for(name, thresholds, default_unstable, default_fail)
        past = history.get(name)
        baseline = statistics.median(past) if past else None
        band = noise_band(past, min_runs, mad_factor) if past else None
        verdict, delta, note = judge(baseline, current.get(name), band, th)
        rows.append({
            "metric": name,
            "baseline": baseline,
            "baseline_runs": len(past) if past else 0,
            "current": current.get(name),
            "delta_pct": delta,
            "band": list(band) if band else None,
            "unstable_pct": th["unstable_pct"],
            "fail_pct": th["fail_pct"],
            "higher_is_better": th["higher_is_better"],
            "verdict": verdict,
            "note": note,
        })
    return rows


def overall(rows):
    code = max((VERDICT_EXIT[r["verdict"]] for r in rows), default=EXIT_OK)
    return {EXIT_OK: "ok", EXIT_UNSTABLE: "unstable", EXIT_FAIL: "fail"}[code], code


def fmt_num(value):
    return "-" if value is None else "%.2f" % value


def fmt_delta(value):
    return "-" if value is None else "%+.1f %%" % value


def print_table(rows, out=None):
    out = out or sys.stdout
    width = max([len(r["metric"]) for r in rows] + [6])
    print("%-*s %12s %12s %9s  %-8s %s" % (width, "metric", "baseline", "current", "delta", "verdict", "note"), file=out)
    for r in rows:
        print("%-*s %12s %12s %9s  %-8s %s" % (width, r["metric"], fmt_num(r["baseline"]), fmt_num(r["current"]),
                                               fmt_delta(r["delta_pct"]), r["verdict"], r["note"]), file=out)


def write_junit(path, rows, suite_name):
    suite = ET.Element("testsuite", name=suite_name, tests=str(len(rows)),
                       failures=str(sum(1 for r in rows if r["verdict"] in ("unstable", "missing", "fail"))),
                       errors="0", skipped="0")
    for r in rows:
        case = ET.SubElement(suite, "testcase", classname=suite_name, name=r["metric"])
        summary = "baseline %s, current %s, delta %s" % (fmt_num(r["baseline"]), fmt_num(r["current"]), fmt_delta(r["delta_pct"]))
        if r["verdict"] in ("unstable", "missing", "fail"):
            ET.SubElement(case, "failure", type=r["verdict"], message="%s: %s" % (r["verdict"], r["note"])).text = summary
        ET.SubElement(case, "system-out").text = "%s (%s)" % (summary, r["verdict"] + (": " + r["note"] if r["note"] else ""))
    ensure_dir(path)
    ET.ElementTree(suite).write(path, encoding="unicode", xml_declaration=True)


def write_markdown(path, rows, title):
    verdict, _ = overall(rows)
    lines = ["**%s: %s**" % (title, verdict.upper()), "",
             "| metric | baseline | current | delta | verdict | note |", "|---|---:|---:|---:|---|---|"]
    for r in rows:
        v = r["verdict"]
        if v in ("fail", "unstable", "missing"):
            v = "**%s**" % v
        lines.append("| `%s` | %s | %s | %s | %s | %s |" % (r["metric"], fmt_num(r["baseline"]), fmt_num(r["current"]),
                                                            fmt_delta(r["delta_pct"]), v, r["note"]))
    ensure_dir(path)
    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")


def write_json(path, payload):
    ensure_dir(path)
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)


def ensure_dir(path):
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)


def update_store(store_path, result, keep, ref=None):
    """Appends the result's medians to the store (created if absent), keeps the last `keep` runs."""
    if os.path.exists(store_path):
        store = load_json(store_path, "baseline store")
        if not is_store(store) or not isinstance(store.get("runs"), list):
            raise UsageError("%s exists but is not a baseline store; refusing to overwrite it" % store_path)
    else:
        store = {"kind": STORE_KIND, "scenario": result.get("scenario"), "lane": result.get("lane"), "runs": []}
    run = {
        "time": result.get("time") or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": result.get("host"),
        "platform": result.get("platform"),
        "repeats": result.get("repeats"),
        "metrics": result_medians(result),
    }
    if ref:
        run["ref"] = ref
    store["runs"].append(run)
    store["runs"] = store["runs"][-keep:]
    store["keep"] = keep
    ensure_dir(store_path)
    with open(store_path, "w") as f:
        json.dump(store, f, indent=2)
    return len(store["runs"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("current", help="result JSON written by perfdrive.py")
    ap.add_argument("--baseline", help="perfdrive.py result or baseline store to compare against")
    ap.add_argument("--update-baseline", metavar="STORE", help="append the current result to this baseline store instead of comparing")
    ap.add_argument("--keep", type=int, default=20, help="runs to keep in the store with --update-baseline (default 20)")
    ap.add_argument("--ref", help="label for the stored run, e.g. the git commit (--update-baseline)")
    ap.add_argument("--scenario", help="scenario JSON whose 'thresholds' block to use")
    ap.add_argument("--default-unstable-pct", type=float, default=10.0, help="for metrics without a threshold (default 10)")
    ap.add_argument("--default-fail-pct", type=float, default=25.0, help="for metrics without a threshold (default 25)")
    ap.add_argument("--min-runs", type=int, default=5, help="stored runs needed before the noise band is used (default 5)")
    ap.add_argument("--mad-factor", type=float, default=3.0, help="noise band half-width in MADs (default 3)")
    ap.add_argument("--junit", help="write JUnit XML here, one testcase per metric")
    ap.add_argument("--markdown", help="write a Markdown table here (PR comment)")
    ap.add_argument("--json", help="write the verdicts as JSON here")
    args = ap.parse_args()

    try:
        if bool(args.baseline) == bool(args.update_baseline):
            raise UsageError("give exactly one of --baseline or --update-baseline")
        if args.keep < 1:
            raise UsageError("--keep must be at least 1")
        result = load_result(args.current)

        if args.update_baseline:
            n = update_store(args.update_baseline, result, args.keep, args.ref)
            print("stored %s in %s (%d run%s kept)" % (args.current, args.update_baseline, n, "" if n == 1 else "s"))
            return EXIT_OK

        history, runs = load_baseline(args.baseline)
        thresholds = load_thresholds(args.scenario) if args.scenario else {}
        rows = compare(result_medians(result), history, thresholds, args.default_unstable_pct,
                       args.default_fail_pct, args.min_runs, args.mad_factor)
    except UsageError as e:
        print("compare: %s" % e, file=sys.stderr)
        return EXIT_USAGE

    verdict, code = overall(rows)
    suite = "%s.%s" % (result.get("scenario", "perf"), result.get("lane", "lane"))
    print_table(rows)
    band = any(r["band"] for r in rows)
    print("\n%s: %s (baseline: %d run%s%s)" % (suite, verdict.upper(), runs, "" if runs == 1 else "s",
                                               ", noise band active" if band else ""))
    try:
        if args.junit:
            write_junit(args.junit, rows, suite)
        if args.markdown:
            write_markdown(args.markdown, rows, "perf %s" % suite)
        if args.json:
            write_json(args.json, {
                "verdict": verdict, "exit_code": code, "suite": suite,
                "current": args.current, "baseline": args.baseline, "baseline_runs": runs,
                "noise_band_active": band, "metrics": rows,
            })
    except OSError as e:
        print("compare: cannot write %s: %s" % (e.filename, e.strerror), file=sys.stderr)
        return EXIT_USAGE
    return code


if __name__ == "__main__":
    sys.exit(main())
