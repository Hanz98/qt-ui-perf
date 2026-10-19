#!/usr/bin/env python3
"""A stand-in for an application built with harness/perfdriver.

Speaks the same protocol (newline-delimited JSON on stdin, "@perf "-prefixed replies on
stdout) so tools/perfdrive.py can be tested without Qt. It models the sample app's widgets
just enough for scenarios/sample_app.json: a slider, two buttons and the labels.

Environment knobs for the tests:
  FAKE_APP_NO_READY=1   never send the ready event
  FAKE_APP_EXIT_CODE=n  exit with this code after quit
"""
import json
import os
import sys
import time

START = time.perf_counter()
LEVEL_DEFAULT = 50


def now_ms():
    return (time.perf_counter() - START) * 1000.0


def mood(level):
    if level == 0:
        return "Silent"
    if level < 30:
        return "Quiet"
    if level < 70:
        return "Moderate"
    if level < 100:
        return "Loud"
    return "Maximum"


class State:
    def __init__(self):
        self.level = LEVEL_DEFAULT
        self.clicks = 0
        self.status = "Ready."
        self.paints = 0

    def labels(self):
        return {
            "valueLabel": "Level: %d %%" % self.level,
            "moodLabel": mood(self.level),
            "clicksLabel": "Clicks: %d" % self.clicks,
            "statusLabel": self.status,
        }

    def objects(self):
        objs = dict.fromkeys(self.labels(), "QLabel")
        objs.update({"mainWindow": "MainWindow", "levelSlider": "QSlider",
                     "countButton": "QPushButton", "resetButton": "QPushButton"})
        return objs


def reply(msg):
    sys.stdout.write("@perf " + json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(state, cmd):
    op = cmd.get("op")
    obj = cmd.get("object")
    out = {"id": cmd.get("id"), "ok": True, "t": now_ms()}
    if obj is not None and obj not in state.objects():
        return {"id": cmd.get("id"), "ok": False, "t": now_ms(), "error": "no object '%s'" % obj}

    if op in ("ping", "mark", "wait_idle"):
        pass
    elif op == "find":
        out.update(**{"class": state.objects()[obj], "visible": True, "enabled": True,
                      "geometry": [0, 0, 100, 20]})
    elif op == "get":
        prop = cmd.get("property", "text")
        value = state.labels().get(obj) if prop == "text" else None
        out["value"] = value
    elif op == "wait_first_frame":
        state.paints += 1
        out["first_paint_ms"] = now_ms()
    elif op == "click":
        if obj == "countButton":
            state.clicks += 1
            state.status = "Counted click number %d." % state.clicks
        elif obj == "resetButton":
            state.clicks = 0
            state.level = LEVEL_DEFAULT
            state.status = "Everything reset."
        state.paints += 1
        out.update(dispatch_ms=0.1, painted=True, paint_ms=0.5, enabled=True)
    elif op == "key":
        keys = cmd.get("keys", [])
        if obj == "levelSlider":
            for k in keys:
                if k == "Right":
                    state.level = min(100, state.level + 1)
                elif k == "Left":
                    state.level = max(0, state.level - 1)
            state.status = "Level set to %d." % state.level
        state.paints += 1
        out.update(dispatch_ms=0.1, keys=len(keys), painted=True, paint_ms=0.4)
    elif op == "wheel":
        if obj == "levelSlider":
            # Qt moves a slider by singleStep * 3 per wheel notch.
            delta = int(cmd.get("delta", -120))
            state.level = max(0, min(100, state.level + (3 if delta > 0 else -3)))
            state.status = "Level set to %d." % state.level
        state.paints += 1
        out.update(dispatch_ms=0.1, accepted=True, painted=True, paint_ms=0.3)
    elif op == "stats":
        out.update(jank={"count": 10, "p50": 0.2, "p95": 1.0, "max": 2.0, "over_50ms": 0},
                   paint_count=state.paints, first_paint_ms=1.0)
    elif op == "quit":
        reply(out)
        return None
    else:
        return {"id": cmd.get("id"), "ok": False, "t": now_ms(), "error": "unknown op '%s'" % op}
    return out


def main():
    if "--perf-driver" not in sys.argv:
        return 0
    if not os.environ.get("FAKE_APP_NO_READY"):
        reply({"event": "ready", "t": now_ms()})
    state = State()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            cmd = json.loads(line)
        except json.JSONDecodeError:
            reply({"ok": False, "error": "bad json"})
            continue
        out = handle(state, cmd)
        if out is None:
            break
        reply(out)
    return int(os.environ.get("FAKE_APP_EXIT_CODE", "0"))


if __name__ == "__main__":
    sys.exit(main())
