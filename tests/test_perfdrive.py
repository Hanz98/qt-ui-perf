"""Tests for tools/perfdrive.py that need no Qt: the driver is run against tests/fake_app.py,
which speaks the perfdriver protocol.

    python3 -m unittest discover -s tests -v
"""
import json
import os
import stat
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import perfdrive  # noqa: E402

FAKE_APP = os.path.join(ROOT, "tests", "fake_app.py")
SAMPLE_SCENARIO = os.path.join(ROOT, "scenarios", "sample_app.json")

needs_exec = unittest.skipIf(sys.platform == "win32",
                             "fake_app.py is launched through its shebang; no Windows launcher")


def setUpModule():
    # git does not always preserve the executable bit (Windows checkouts, zip downloads).
    mode = os.stat(FAKE_APP).st_mode
    os.chmod(FAKE_APP, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def load_scenario():
    with open(SAMPLE_SCENARIO) as f:
        return json.load(f)


def env_for(**extra):
    env = dict(os.environ)
    env.update(perfdrive.LANE_ENV["headless"])
    env.update(extra)
    return env


class PercentileTest(unittest.TestCase):
    def test_single_value(self):
        self.assertEqual(perfdrive.percentile([4.0], 0.95), 4.0)

    def test_nearest_rank(self):
        values = list(range(1, 11))
        self.assertEqual(perfdrive.percentile(values, 0.0), 1)
        self.assertEqual(perfdrive.percentile(values, 0.9), 9)
        self.assertEqual(perfdrive.percentile(values, 0.95), 10)

    def test_unsorted_input(self):
        self.assertEqual(perfdrive.percentile([9, 1, 5], 1.0), 9)


class AggregateTest(unittest.TestCase):
    def test_keeps_metric_order_and_stats(self):
        runs = [{"a": 1.0, "b": 10.0}, {"a": 3.0}, {"a": 2.0, "b": 30.0}]
        out = perfdrive.aggregate(runs)
        self.assertEqual(list(out), ["a", "b"])
        self.assertEqual(out["a"]["median"], 2.0)
        self.assertEqual(out["a"]["min"], 1.0)
        self.assertEqual(out["a"]["max"], 3.0)
        self.assertEqual(out["b"]["values"], [10.0, 30.0])
        self.assertEqual(out["b"]["median"], 20.0)

    def test_empty(self):
        self.assertEqual(perfdrive.aggregate([]), {})


@needs_exec
class RunOnceTest(unittest.TestCase):
    def test_sample_scenario_records_every_mark(self):
        metrics = perfdrive.run_once(FAKE_APP, load_scenario(), env_for())
        expected = {
            "startup_to_first_paint_ms", "startup_to_first_paint_ms.wall",
            "rss_after_start_mib", "count_click_to_paint_ms",
            "slider_key_to_paint_ms", "slider_key_to_paint_ms.p95", "slider_key_to_paint_ms.max",
            "slider_wheel_to_paint_ms", "slider_wheel_to_paint_ms.p95", "slider_wheel_to_paint_ms.max",
            "reset_click_to_paint_ms", "jank.p95", "jank.max", "jank.over_50ms",
            "rss_after_scenario_mib",
        }
        if not sys.platform.startswith("linux"):
            expected -= {"rss_after_start_mib", "rss_after_scenario_mib"}
        self.assertEqual(set(metrics), expected)
        self.assertEqual(metrics["count_click_to_paint_ms"], 0.5)
        self.assertEqual(metrics["jank.over_50ms"], 0)

    def test_quick_frames_are_recorded_per_window(self):
        scenario = {"steps": [{"op": "launch"}, {"op": "click", "object": "countButton"},
                              {"op": "stats", "mark": "jank"}]}
        metrics = perfdrive.run_once(FAKE_APP, scenario, env_for(FAKE_APP_FRAMES="1"))
        self.assertEqual(metrics["frames.mainWindow.count"], 1)
        self.assertEqual(metrics["frames.mainWindow.fps"], 60.0)
        self.assertEqual(metrics["frames.mainWindow.interval_p95"], 17.0)
        # a Widgets-only build reports no windows and no frame metrics appear
        metrics = perfdrive.run_once(FAKE_APP, scenario, env_for())
        self.assertFalse([m for m in metrics if m.startswith("frames.")])

    def test_tree_step_is_playable(self):
        scenario = {"steps": [{"op": "launch"}, {"op": "tree", "depth": 2}, {"op": "quit"}]}
        import contextlib
        import io
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            perfdrive.run_once(FAKE_APP, scenario, env_for())
        self.assertIn('QSlider "levelSlider"', err.getvalue())

    def test_expect_mismatch_fails_the_run(self):
        scenario = {"steps": [
            {"op": "launch"},
            {"op": "click", "object": "countButton"},
            {"op": "get", "object": "clicksLabel", "expect": "Clicks: 2"},
        ]}
        with self.assertRaises(perfdrive.ProtocolError) as cm:
            perfdrive.run_once(FAKE_APP, scenario, env_for())
        self.assertIn("Clicks: 1", str(cm.exception))

    def test_unknown_object_fails(self):
        scenario = {"steps": [{"op": "launch"}, {"op": "click", "object": "noSuchButton"}]}
        with self.assertRaises(perfdrive.ProtocolError) as cm:
            perfdrive.run_once(FAKE_APP, scenario, env_for())
        self.assertIn("noSuchButton", str(cm.exception))

    def test_unknown_op_fails(self):
        scenario = {"steps": [{"op": "launch"}, {"op": "teleport"}]}
        with self.assertRaises(perfdrive.ProtocolError):
            perfdrive.run_once(FAKE_APP, scenario, env_for())

    def test_launch_must_come_first(self):
        with self.assertRaises(perfdrive.ProtocolError):
            perfdrive.run_once(FAKE_APP, {"steps": [{"op": "mark", "name": "x"}]}, env_for())

    def test_missing_ready_is_reported(self):
        app = perfdrive.App(FAKE_APP, [], env_for(FAKE_APP_NO_READY="1"))
        try:
            with self.assertRaises(perfdrive.ProtocolError):
                app.wait_ready(timeout=2.0)
        finally:
            app.close()

    def test_nonzero_exit_fails(self):
        scenario = {"steps": [{"op": "launch"}, {"op": "quit"}]}
        with self.assertRaises(perfdrive.ProtocolError) as cm:
            perfdrive.run_once(FAKE_APP, scenario, env_for(FAKE_APP_EXIT_CODE="7"))
        self.assertIn("code 7", str(cm.exception))


@needs_exec
class MainTest(unittest.TestCase):
    def test_writes_result_file(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "nested", "result.json")
            argv = ["perfdrive", "--app", FAKE_APP, "--scenario", SAMPLE_SCENARIO,
                    "--repeats", "2", "--out", out]
            import contextlib
            import io
            old = sys.argv
            sys.argv = argv
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(perfdrive.main(), 0)
            finally:
                sys.argv = old
            with open(out) as f:
                result = json.load(f)
        self.assertEqual(result["scenario"], "sample_app")
        self.assertEqual(result["lane"], "headless")
        self.assertEqual(result["repeats"], 2)
        self.assertEqual(len(result["metrics"]["count_click_to_paint_ms"]["values"]), 2)

    def test_tree_flag_prints_the_object_tree(self):
        import contextlib
        import io
        out = io.StringIO()
        old = sys.argv
        sys.argv = ["perfdrive", "--app", FAKE_APP, "--tree"]
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(perfdrive.main(), 0)
        finally:
            sys.argv = old
        self.assertIn('MainWindow "mainWindow"', out.getvalue())
        self.assertIn("text='Clicks: 0'", out.getvalue())


class FormatTreeTest(unittest.TestCase):
    def test_indents_by_depth_and_marks_hidden(self):
        text = perfdrive.format_tree([
            {"depth": 0, "class": "QQuickWindow", "name": "mainWindow", "visible": True, "geometry": [0, 0, 4, 3]},
            {"depth": 1, "class": "QQuickButton", "name": "", "text": "Count", "visible": False},
        ])
        self.assertEqual(text.splitlines(), ['QQuickWindow "mainWindow" [0,0,4,3]',
                                             "  QQuickButton text='Count' (hidden)"])


if __name__ == "__main__":
    unittest.main()
