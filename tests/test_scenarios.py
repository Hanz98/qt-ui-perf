"""Every scenarios/*.json must be something tools/perfdrive.py can play."""
import glob
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCENARIOS = sorted(glob.glob(os.path.join(ROOT, "scenarios", "*.json")))

KNOWN_OPS = {"launch", "wait_first_frame", "wait_idle", "click", "key", "wheel", "get",
             "mark", "stats", "tree", "quit"}
NEEDS_OBJECT = {"click", "key", "wheel", "get"}


class ScenarioFilesTest(unittest.TestCase):
    def test_there_are_scenarios(self):
        self.assertTrue(SCENARIOS)

    def test_each_scenario_is_well_formed(self):
        for path in SCENARIOS:
            with self.subTest(scenario=os.path.basename(path)):
                with open(path) as f:
                    scenario = json.load(f)
                steps = scenario["steps"]
                self.assertEqual(steps[0]["op"], "launch", "first step must be launch")
                self.assertEqual(steps[-1]["op"], "quit", "last step must be quit")
                for step in steps:
                    self.assertIn(step["op"], KNOWN_OPS)
                    if step["op"] in NEEDS_OBJECT:
                        self.assertIn("object", step)
                    if step["op"] == "mark":
                        self.assertIn("name", step)

    def test_thresholds_name_recorded_metrics(self):
        for path in SCENARIOS:
            with self.subTest(scenario=os.path.basename(path)):
                with open(path) as f:
                    scenario = json.load(f)
                marks = set()
                for step in scenario["steps"]:
                    if step["op"] == "mark":
                        marks.add(step["name"])
                    elif step["op"] == "stats":
                        prefix = step.get("mark", "jank")
                        marks.update({prefix + ".p95", prefix + ".max", prefix + ".over_50ms"})
                    elif step.get("mark"):
                        marks.add(step["mark"])
                        if step["op"] in ("key", "wheel"):
                            marks.update({step["mark"] + ".p95", step["mark"] + ".max"})
                        if step["op"] == "wait_first_frame":
                            marks.add(step["mark"] + ".wall")
                for name in scenario.get("thresholds", {}):
                    self.assertIn(name, marks, "threshold for a metric the scenario never records")


if __name__ == "__main__":
    unittest.main()
