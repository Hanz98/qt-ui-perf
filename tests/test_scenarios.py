"""Every scenarios/*.json must be something tools/perfdrive.py can play, and must validate
against scenarios/schema.json.

The schema check uses a deliberately small validator below (standard library only, like the
rest of the tooling) that understands exactly the keywords schema.json uses: type, enum,
const, required, properties, additionalProperties, items, minItems, minLength, minimum,
exclusiveMinimum, oneOf and local $ref. Extend it if the schema starts using more.
"""
import glob
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMA = os.path.join(ROOT, "scenarios", "schema.json")
SCENARIOS = sorted(p for p in glob.glob(os.path.join(ROOT, "scenarios", "*.json")) if p != SCHEMA)

KNOWN_OPS = {"launch", "wait_first_frame", "wait_idle", "click", "key", "wheel", "get",
             "mark", "stats", "quit"}
NEEDS_OBJECT = {"click", "key", "wheel", "get"}

TYPES = {
    "object": dict, "array": list, "string": str, "boolean": bool,
    "number": (int, float), "integer": int,
}


class SchemaError(ValueError):
    pass


def validate(instance, schema, root=None, path="$"):
    """Raises SchemaError with the JSON path of the first violation."""
    root = schema if root is None else root
    if "$ref" in schema:
        node = root
        for part in schema["$ref"].lstrip("#/").split("/"):
            node = node[part]
        return validate(instance, node, root, path)

    def fail(msg):
        raise SchemaError("%s: %s" % (path, msg))

    if "type" in schema:
        expected = TYPES[schema["type"]]
        ok = isinstance(instance, expected) and not (schema["type"] in ("number", "integer")
                                                     and isinstance(instance, bool))
        if not ok:
            fail("expected %s, got %s" % (schema["type"], type(instance).__name__))
    if "enum" in schema and instance not in schema["enum"]:
        fail("%r not one of %r" % (instance, schema["enum"]))
    if "const" in schema and instance != schema["const"]:
        fail("%r is not %r" % (instance, schema["const"]))
    if "minimum" in schema and instance < schema["minimum"]:
        fail("%r < minimum %r" % (instance, schema["minimum"]))
    if "exclusiveMinimum" in schema and instance <= schema["exclusiveMinimum"]:
        fail("%r <= exclusiveMinimum %r" % (instance, schema["exclusiveMinimum"]))
    if "minLength" in schema and len(instance) < schema["minLength"]:
        fail("shorter than %d" % schema["minLength"])
    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                fail("missing required property %r" % key)
        props = schema.get("properties", {})
        for key, value in instance.items():
            if key in props:
                validate(value, props[key], root, "%s.%s" % (path, key))
            elif schema.get("additionalProperties") is False:
                fail("unexpected property %r" % key)
            elif isinstance(schema.get("additionalProperties"), dict):
                validate(value, schema["additionalProperties"], root, "%s.%s" % (path, key))
    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            fail("fewer than %d items" % schema["minItems"])
        if "items" in schema:
            for i, item in enumerate(instance):
                validate(item, schema["items"], root, "%s[%d]" % (path, i))
    if "oneOf" in schema:
        matches, errors = 0, []
        for option in schema["oneOf"]:
            try:
                validate(instance, option, root, path)
                matches += 1
            except SchemaError as e:
                errors.append(str(e))
        if matches != 1:
            fail("matches %d of the oneOf alternatives; %s" % (matches, "; ".join(errors)))


def load_schema():
    with open(SCHEMA) as f:
        return json.load(f)


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

    def test_each_scenario_matches_the_schema(self):
        schema = load_schema()
        for path in SCENARIOS:
            with self.subTest(scenario=os.path.basename(path)):
                with open(path) as f:
                    validate(json.load(f), schema)

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


class SchemaTest(unittest.TestCase):
    """The schema covers every op perfdrive.py handles and rejects what it would reject."""

    def setUp(self):
        self.schema = load_schema()

    def test_schema_lists_exactly_the_known_ops(self):
        ops = {self.schema["definitions"][ref["$ref"].rsplit("/", 1)[1]]["properties"]["op"]["const"]
               for ref in self.schema["definitions"]["step"]["oneOf"]}
        self.assertEqual(ops, KNOWN_OPS)

    def test_minimal_scenario_is_valid(self):
        validate({"name": "x", "steps": [{"op": "launch"}, {"op": "quit"}]}, self.schema)

    def test_rejects(self):
        bad = {
            "unknown op": {"name": "x", "steps": [{"op": "launch"}, {"op": "teleport"}, {"op": "quit"}]},
            "click without object": {"name": "x", "steps": [{"op": "launch"}, {"op": "click"}, {"op": "quit"}]},
            "mark without name": {"name": "x", "steps": [{"op": "launch"}, {"op": "mark"}, {"op": "quit"}]},
            "bad metric": {"name": "x", "steps": [{"op": "launch"}, {"op": "mark", "name": "m", "metric": "cpu"}, {"op": "quit"}]},
            "bad axis": {"name": "x", "steps": [{"op": "launch"}, {"op": "wheel", "object": "o", "axis": "z"}, {"op": "quit"}]},
            "typo in field": {"name": "x", "steps": [{"op": "launch"}, {"op": "key", "object": "o", "key": ["Right"]}, {"op": "quit"}]},
            "times zero": {"name": "x", "steps": [{"op": "launch"}, {"op": "key", "object": "o", "times": 0}, {"op": "quit"}]},
            "no name": {"steps": [{"op": "launch"}, {"op": "quit"}]},
            "env not strings": {"name": "x", "env": {"A": 1}, "steps": [{"op": "launch"}, {"op": "quit"}]},
            "threshold not a number": {"name": "x", "steps": [{"op": "launch"}, {"op": "quit"}],
                                       "thresholds": {"m": {"fail_pct": "25"}}},
        }
        for label, scenario in bad.items():
            with self.subTest(case=label):
                with self.assertRaises(SchemaError):
                    validate(scenario, self.schema)


if __name__ == "__main__":
    unittest.main()
