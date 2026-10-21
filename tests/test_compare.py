"""Tests for tools/compare.py: thresholds, noise band, verdicts, outputs and exit codes.

    python3 -m unittest discover -s tests -v
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import compare  # noqa: E402

SAMPLE_SCENARIO = os.path.join(ROOT, "scenarios", "sample_app.json")


def result_doc(medians, scenario="sample_app", lane="headless"):
    """A perfdrive.py-shaped result with the given {metric: median}."""
    return {
        "scenario": scenario, "lane": lane, "repeats": 3, "host": "h", "platform": "p", "time": "2026-01-01T00:00:00+00:00",
        "metrics": {name: {"values": [m, m, m], "median": m, "p95": m, "min": m, "max": m} for name, m in medians.items()},
    }


def store_doc(runs):
    """A baseline store whose runs have the given [{metric: median}, ...]."""
    return {"kind": compare.STORE_KIND, "scenario": "sample_app", "lane": "headless", "keep": 20,
            "runs": [{"time": "t%d" % i, "metrics": m} for i, m in enumerate(runs)]}


def history(**metrics):
    """{metric: [median, ...]} from keyword lists, the shape compare.compare() consumes."""
    return {name: list(values) for name, values in metrics.items()}


def run_main(argv):
    old = sys.argv
    sys.argv = ["compare"] + argv
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = compare.main()
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


def by_name(rows):
    return {r["metric"]: r for r in rows}


class JudgeTest(unittest.TestCase):
    """compare.compare() on in-memory data: one metric, no files."""

    def one(self, baseline, current, thresholds=None, **kw):
        rows = compare.compare({"m": current} if current is not None else {},
                               history(m=baseline) if baseline is not None else {}, thresholds or {}, **kw)
        return rows[0]

    def test_no_regression(self):
        r = self.one([100.0], 105.0)
        self.assertEqual(r["verdict"], "ok")
        self.assertAlmostEqual(r["delta_pct"], 5.0)

    def test_improvement_is_ok(self):
        self.assertEqual(self.one([100.0], 50.0)["verdict"], "ok")

    def test_unstable(self):
        r = self.one([100.0], 112.0)
        self.assertEqual(r["verdict"], "unstable")
        self.assertIn("10", r["note"])

    def test_fail(self):
        r = self.one([100.0], 130.0)
        self.assertEqual(r["verdict"], "fail")

    def test_scenario_thresholds_override_defaults(self):
        th = {"m": {"unstable_pct": 5, "fail_pct": 15}}
        self.assertEqual(self.one([100.0], 107.0, th)["verdict"], "unstable")
        self.assertEqual(self.one([100.0], 116.0, th)["verdict"], "fail")
        self.assertEqual(self.one([100.0], 107.0)["verdict"], "ok")

    def test_command_line_defaults(self):
        self.assertEqual(self.one([100.0], 107.0, default_unstable=5.0, default_fail=50.0)["verdict"], "unstable")
        self.assertEqual(self.one([100.0], 140.0, default_unstable=5.0, default_fail=50.0)["verdict"], "unstable")

    def test_metric_missing_in_baseline_is_new(self):
        r = self.one(None, 42.0)
        self.assertEqual(r["verdict"], "new")
        self.assertIsNone(r["baseline"])
        self.assertIsNone(r["delta_pct"])
        self.assertEqual(compare.overall([r]), ("ok", compare.EXIT_OK))

    def test_metric_missing_in_current_is_unstable(self):
        r = self.one([42.0], None)
        self.assertEqual(r["verdict"], "missing")
        self.assertIsNone(r["current"])
        self.assertEqual(compare.overall([r]), ("unstable", compare.EXIT_UNSTABLE))

    def test_zero_baseline(self):
        self.assertEqual(self.one([0.0], 0.0)["verdict"], "ok")
        r = self.one([0.0], 1.0)
        self.assertEqual(r["verdict"], "unstable")
        self.assertIsNone(r["delta_pct"])

    def test_higher_is_better(self):
        th = {"m": {"unstable_pct": 10, "fail_pct": 25, "higher_is_better": True}}
        self.assertEqual(self.one([60.0], 70.0, th)["verdict"], "ok")
        r = self.one([60.0], 50.0, th)
        self.assertEqual(r["verdict"], "unstable")
        self.assertAlmostEqual(r["delta_pct"], -100.0 / 6)
        self.assertEqual(self.one([60.0], 40.0, th)["verdict"], "fail")

    def test_overall_is_the_worst_verdict(self):
        rows = compare.compare({"a": 100.0, "b": 130.0, "c": 112.0}, history(a=[100.0], b=[100.0], c=[100.0]), {})
        self.assertEqual(compare.overall(rows), ("fail", compare.EXIT_FAIL))
        self.assertEqual(compare.overall([]), ("ok", compare.EXIT_OK))

    def test_rows_keep_current_order_then_baseline_only(self):
        rows = compare.compare({"b": 1.0, "a": 1.0}, history(c=[1.0], a=[1.0]), {})
        self.assertEqual([r["metric"] for r in rows], ["b", "a", "c"])


class NoiseBandTest(unittest.TestCase):
    # median 115, MAD 15 -> band [70, 160]
    PAST = [100.0, 130.0, 90.0, 120.0, 110.0, 140.0]

    def test_band_from_median_and_mad(self):
        self.assertEqual(compare.noise_band(self.PAST, 5, 3.0), (70.0, 160.0))
        self.assertIsNone(compare.noise_band(self.PAST[:4], 5, 3.0))

    def test_band_suppresses_a_flagged_metric(self):
        r = compare.compare({"m": 150.0}, history(m=self.PAST), {})[0]
        self.assertEqual(r["verdict"], "ok", "+30 % but inside [70, 160]")
        self.assertIn("noise band", r["note"])
        self.assertEqual(r["band"], [70.0, 160.0])
        self.assertAlmostEqual(r["baseline"], 115.0)

    def test_outside_band_and_threshold_still_fails(self):
        r = compare.compare({"m": 170.0}, history(m=self.PAST), {})[0]
        self.assertEqual(r["verdict"], "fail")

    def test_band_needs_min_runs(self):
        r = compare.compare({"m": 150.0}, history(m=self.PAST[:4]), {})[0]
        self.assertEqual(r["verdict"], "fail")
        self.assertIsNone(r["band"])
        r = compare.compare({"m": 150.0}, history(m=self.PAST[:4]), {}, min_runs=4)[0]
        self.assertEqual(r["verdict"], "ok")

    def test_band_does_not_rescue_the_low_side_for_lower_is_better(self):
        # a big improvement is never flagged; the band only matters on the worse side
        r = compare.compare({"m": 20.0}, history(m=self.PAST), {})[0]
        self.assertEqual(r["verdict"], "ok")

    def test_band_for_higher_is_better_uses_low_edge(self):
        th = {"m": {"higher_is_better": True}}
        self.assertEqual(compare.compare({"m": 80.0}, history(m=self.PAST), th)[0]["verdict"], "ok")
        self.assertEqual(compare.compare({"m": 60.0}, history(m=self.PAST), th)[0]["verdict"], "fail")

    def test_identical_history_collapses_the_band(self):
        r = compare.compare({"m": 112.0}, history(m=[100.0] * 6), {})[0]
        self.assertEqual(r["band"], [100.0, 100.0])
        self.assertEqual(r["verdict"], "unstable")


class StoreTest(unittest.TestCase):
    def test_update_creates_appends_and_trims(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = os.path.join(tmp, "r.json")
            store = os.path.join(tmp, "nested", "store.json")
            for i in range(4):
                with open(res, "w") as f:
                    json.dump(result_doc({"m": 100.0 + i}), f)
                code, out, _ = run_main([res, "--update-baseline", store, "--keep", "3", "--ref", "c%d" % i])
                self.assertEqual(code, 0, out)
            with open(store) as f:
                doc = json.load(f)
            self.assertEqual(doc["kind"], compare.STORE_KIND)
            self.assertEqual(doc["keep"], 3)
            self.assertEqual([r["metrics"]["m"] for r in doc["runs"]], [101.0, 102.0, 103.0])
            self.assertEqual([r["ref"] for r in doc["runs"]], ["c1", "c2", "c3"])
            hist, runs = compare.load_baseline(store)
            self.assertEqual(runs, 3)
            self.assertEqual(hist, {"m": [101.0, 102.0, 103.0]})

    def test_refuses_to_overwrite_a_non_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = os.path.join(tmp, "r.json")
            with open(res, "w") as f:
                json.dump(result_doc({"m": 1.0}), f)
            code, _, err = run_main([res, "--update-baseline", res])
            self.assertEqual(code, compare.EXIT_USAGE)
            self.assertIn("not a baseline store", err)

    def test_plain_result_as_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            res = os.path.join(tmp, "r.json")
            with open(res, "w") as f:
                json.dump(result_doc({"m": 7.0, "n": 0.0}), f)
            self.assertEqual(compare.load_baseline(res), ({"m": [7.0], "n": [0.0]}, 1))


class MainTest(unittest.TestCase):
    """Exit codes and output files through the real CLI."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, doc):
        path = os.path.join(self.dir, name)
        with open(path, "w") as f:
            json.dump(doc, f)
        return path

    def test_exit_ok_unstable_fail(self):
        base = self.write("base.json", result_doc({"startup_to_first_paint_ms": 100.0, "count_click_to_paint_ms": 10.0}))
        for cur, expected in [({"startup_to_first_paint_ms": 105.0, "count_click_to_paint_ms": 10.0}, 0),
                              ({"startup_to_first_paint_ms": 112.0, "count_click_to_paint_ms": 10.0}, 1),
                              ({"startup_to_first_paint_ms": 100.0, "count_click_to_paint_ms": 13.0}, 2)]:
            with self.subTest(expected=expected):
                path = self.write("cur.json", result_doc(cur))
                code, out, _ = run_main([path, "--baseline", base, "--scenario", SAMPLE_SCENARIO])
                self.assertEqual(code, expected, out)
                self.assertIn("sample_app.headless:", out)

    def test_same_file_as_its_own_baseline_is_ok(self):
        path = self.write("r.json", result_doc({"a": 1.0, "b": 0.0}))
        self.assertEqual(run_main([path, "--baseline", path])[0], 0)

    def test_usage_errors_exit_3(self):
        good = self.write("r.json", result_doc({"a": 1.0}))
        bad = self.write("bad.json", {"not": "a result"})
        with open(os.path.join(self.dir, "garbage.json"), "w") as f:
            f.write("{")
        cases = [
            [good],                                               # neither --baseline nor --update-baseline
            [good, "--baseline", good, "--update-baseline", good],
            [os.path.join(self.dir, "missing.json"), "--baseline", good],
            [good, "--baseline", os.path.join(self.dir, "missing.json")],
            [bad, "--baseline", good],
            [good, "--baseline", bad],
            [good, "--baseline", os.path.join(self.dir, "garbage.json")],
            [good, "--baseline", good, "--scenario", os.path.join(self.dir, "missing.json")],
            [good, "--update-baseline", os.path.join(self.dir, "s.json"), "--keep", "0"],
        ]
        for argv in cases:
            with self.subTest(argv=argv):
                code, _, err = run_main(argv)
                self.assertEqual(code, 3)
                self.assertTrue(err.startswith("compare: "), err)

    def test_store_baseline_with_noise_band_through_cli(self):
        store = self.write("store.json", store_doc([{"m": v} for v in NoiseBandTest.PAST]))
        ok = self.write("ok.json", result_doc({"m": 150.0}))
        bad = self.write("bad.json", result_doc({"m": 170.0}))
        code, out, _ = run_main([ok, "--baseline", store])
        self.assertEqual(code, 0, out)
        self.assertIn("noise band active", out)
        self.assertEqual(run_main([bad, "--baseline", store])[0], 2)
        code, out, _ = run_main([ok, "--baseline", store, "--min-runs", "10"])
        self.assertEqual(code, 2, out)
        self.assertNotIn("noise band active", out)

    def test_output_files(self):
        base = self.write("base.json", result_doc({"ok_ms": 100.0, "slow_ms": 100.0, "worse_ms": 100.0, "gone_ms": 5.0}))
        cur = self.write("cur.json", result_doc({"ok_ms": 101.0, "slow_ms": 115.0, "worse_ms": 140.0, "fresh_ms": 1.0}))
        junit = os.path.join(self.dir, "out", "junit.xml")
        md = os.path.join(self.dir, "out", "table.md")
        js = os.path.join(self.dir, "out", "verdict.json")
        code, _, _ = run_main([cur, "--baseline", base, "--junit", junit, "--markdown", md, "--json", js])
        self.assertEqual(code, 2)

        suite = ET.parse(junit).getroot()
        self.assertEqual(suite.tag, "testsuite")
        self.assertEqual(suite.get("name"), "sample_app.headless")
        self.assertEqual(suite.get("tests"), "5")
        self.assertEqual(suite.get("failures"), "3")
        cases = {c.get("name"): c for c in suite.findall("testcase")}
        self.assertEqual(set(cases), {"ok_ms", "slow_ms", "worse_ms", "gone_ms", "fresh_ms"})
        self.assertIsNone(cases["ok_ms"].find("failure"))
        self.assertIsNone(cases["fresh_ms"].find("failure"))
        self.assertEqual(cases["slow_ms"].find("failure").get("type"), "unstable")
        self.assertEqual(cases["worse_ms"].find("failure").get("type"), "fail")
        self.assertEqual(cases["gone_ms"].find("failure").get("type"), "missing")

        with open(md) as f:
            text = f.read()
        self.assertIn("**perf sample_app.headless: FAIL**", text)
        self.assertIn("| `worse_ms` | 100.00 | 140.00 | +40.0 % | **fail** |", text)
        self.assertIn("| `fresh_ms` | - | 1.00 | - | new | not in baseline |", text)

        with open(js) as f:
            doc = json.load(f)
        self.assertEqual(doc["verdict"], "fail")
        self.assertEqual(doc["exit_code"], 2)
        self.assertEqual(doc["baseline_runs"], 1)
        self.assertFalse(doc["noise_band_active"])
        rows = by_name(doc["metrics"])
        self.assertEqual(rows["slow_ms"]["verdict"], "unstable")
        self.assertEqual(rows["gone_ms"]["verdict"], "missing")
        self.assertEqual(rows["fresh_ms"]["verdict"], "new")
        self.assertAlmostEqual(rows["worse_ms"]["delta_pct"], 40.0)

    def test_higher_is_better_from_scenario_file(self):
        scenario = self.write("scn.json", {"steps": [], "thresholds": {"fps": {"unstable_pct": 10, "fail_pct": 25, "higher_is_better": True}}})
        base = self.write("base.json", result_doc({"fps": 60.0}))
        self.assertEqual(run_main([self.write("c1.json", result_doc({"fps": 70.0})), "--baseline", base, "--scenario", scenario])[0], 0)
        self.assertEqual(run_main([self.write("c2.json", result_doc({"fps": 50.0})), "--baseline", base, "--scenario", scenario])[0], 1)
        self.assertEqual(run_main([self.write("c3.json", result_doc({"fps": 40.0})), "--baseline", base, "--scenario", scenario])[0], 2)
        # without the scenario the same drop is an improvement for a lower-is-better metric
        self.assertEqual(run_main([self.write("c4.json", result_doc({"fps": 40.0})), "--baseline", base])[0], 0)


if __name__ == "__main__":
    unittest.main()
