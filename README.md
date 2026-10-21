# qt-ui-perf — UI performance testing of a Qt application on Jenkins

Measure the UI performance of a Qt application from *inside the process*, so the tests run
on CI agents that sit at a locked screen or have no desktop at all. MIT licensed.

## Status

| Piece | State |
|---|---|
| `harness/perfdriver/` — the in-process automation seam (C++, Qt Widgets, Qt 5.15 / Qt 6) | working |
| `tools/perfdrive.py` — launches the app, plays a scenario, writes results JSON; `--tree` dumps the object tree | working, headless + display lanes |
| `sample-app/` — small Qt Widgets app instrumented with the seam (`testing-changes.diff` shows exactly what was added) | working |
| `scenarios/sample_app.json` — startup, click-to-paint, key/wheel latency, jank, RSS | working |
| `tests/` + GitHub Actions — driver tests without Qt, build-and-play smoke on Linux Qt 5/6 and Windows Qt 6 | working |
| `tools/compare.py` (baseline + thresholds → junit), `tools/preflight.py` | not written |
| Qt Quick support in the seam — item-tree addressing, synthetic input to `QQuickWindow`, `frameSwapped` paint detection, per-window frame stats; optional (`PERFDRIVER_QUICK`), `sample-app-quick/` + `scenarios/sample_app_quick.json` | working, headless lane verified on Qt 6; display-lane fps untested |
| `ci/Jenkinsfile` | sketch, see §4 step 7 |
| Display-lane agent setup scripts | not written; facts in `docs/agents.md` |

## Quick start

```sh
# needs cmake, a C++17 compiler, Qt 5.15+ or Qt 6 (Widgets; Quick + Controls optional), Python 3.8+
tests/smoke.sh                       # builds sample-app/ (and sample-app-quick/ if Qt Quick
                                     # is installed) and plays the scenarios headless
python3 -m unittest discover -s tests   # driver and scenario tests, no Qt required

# the same by hand
cmake -S sample-app -B sample-app/build -DSAMPLEAPP_PERF_DRIVER=ON
cmake --build sample-app/build
python3 tools/perfdrive.py --app sample-app/build/SampleApp \
    --scenario scenarios/sample_app.json --lane headless --repeats 5 --out results/local.json

# the Qt Quick twin, and how to discover addresses in an app with few objectNames
cmake -S sample-app-quick -B sample-app-quick/build && cmake --build sample-app-quick/build
python3 tools/perfdrive.py --app sample-app-quick/build/SampleAppQuick --tree
python3 tools/perfdrive.py --app sample-app-quick/build/SampleAppQuick \
    --scenario scenarios/sample_app_quick.json --lane headless --repeats 5
```

Instrumenting your own application takes two calls in `main()` and `objectName`s on the
widgets or QML items you want to drive — see [`harness/README.md`](harness/README.md),
[`sample-app/testing-changes.diff`](sample-app/testing-changes.diff) (Widgets) and
[`sample-app-quick/testing-changes.diff`](sample-app-quick/testing-changes.diff) (Qt Quick).
How to contribute, branch model and what CI checks: [`CONTRIBUTING.md`](CONTRIBUTING.md).

The rest of this file is the plan the work follows, the decisions it rests on, and the
questions that still need answers from the stakeholders.

## 1. Goal

Measure the UI performance of a Qt application (startup, responsiveness, frame rate,
memory) reliably and repeatably in a Jenkins pipeline, on Linux and Windows agents, where the
agent machines are usually sitting at a **locked user session** or have **no interactive
session at all** (Jenkins agent running as a service).

"Reliably" means two things that pull in different directions:

1. The test must *run* every time — no "the desktop was locked so input injection failed".
2. The numbers must be *stable enough* to catch a regression without crying wolf.

## 2. The core idea in one paragraph

Do not drive the application through the operating system's desktop at all. Drive it
**from inside the process** (synthetic Qt events, a small automation seam in the app) and
render it to a **virtual display** that we own (Qt's `offscreen` platform plugin, Xvfb, or
a dedicated X/Wayland/KMS session on a perf box). Then a locked screen, a missing monitor
or Windows "Session 0" stops being a problem, because we never touch the user's desktop.
Split the metrics into a **headless lane** (CPU-side work, runs anywhere, fully
deterministic) and a **display lane** (real GPU, real compositor, only on dedicated agents
prepared for it). Compare every result to a stored baseline with a noise band, not an
absolute number.

## 3. Open questions (answer these first)

| # | Question | Why it matters |
|---|---|---|
| 1 | Qt 5 or Qt 6? Widgets, Qt Quick, or both? | Decides profiler tooling (`qmlprofiler`, scenegraph logging) and which platform plugins exist (`offscreen` supports OpenGL on Qt 6, not reliably on Qt 5). |
| 2 | Do we have the app's source and may we add a test-only flag? | The in-process approach needs an *automation seam* compiled into the app (behind `--perf-driver` / env var). Without source we fall back to accessibility-based drivers, which do need an unlocked desktop. |
| 3 | What does "performance" mean to the stakeholders? | Startup to first frame? Click-to-paint latency? Scroll fps? Memory after a workflow? Each is a different scenario and metric. Pick 3–5 scenarios for the first version. |
| 4 | How do the Jenkins agents run today? (Windows service / Linux systemd service / launched from a logged-in session?) | Service = Session 0 on Windows = no desktop. That's fine for the headless lane, fatal for the display lane. |
| 5 | Does the app need a real GPU to be representative? Is one available on any agent? | Software rendering (llvmpipe / WARP) is deterministic but can be 10× slower than a GPU; it is useless for absolute fps, fine for relative CPU regressions. |
| 6 | How many machines / can one be dedicated to perf? | Numbers from a shared build agent running three jobs at once are noise. |

## 4. Approach, step by step

### Step 1 — Automation seam in the application

A compile-time-optional component (`perfdriver/`) linked into the real binary, enabled only
by `--perf-driver <socket-or-stdin>`. It:

- reads newline-delimited JSON commands on stdin and answers on stdout (`@perf `-prefixed
  lines): `find(objectName)`, `get`, `click`, `key`, `wheel`, `wait_idle`,
  `wait_first_frame`, `stats`, `quit` — see `harness/README.md`; no extra Qt module needed;
- delivers input with `QTest::mouseClick` / `QCoreApplication::postEvent` style synthetic
  events, so it works whatever the OS desktop is doing;
- records timings in-process: `QElapsedTimer` around actions, `QQuickWindow::frameSwapped`
  / `QWidget::paintEvent` for "time to paint", a 16 ms heartbeat timer whose lateness is the
  main-thread **jank meter**, `QQuickWindow::beforeSynchronizing` / `afterRendering` for
  frame budget;
- writes one JSON result file per run.

The Python side (`tools/perfdrive.py`) launches the app with the right environment, speaks
the protocol, runs a scenario, and collects the JSON. Same script on both OSes.

Alternative if the app cannot be modified: a QTest harness that links the app's libraries
and creates its main window in-process (same benefits, more coupling), or an external
driver through accessibility (Squish; `pywinauto`/UIA on Windows, AT-SPI/dogtail on
Linux). The accessibility route needs an unlocked interactive desktop on Windows, which is
exactly the thing we cannot rely on, so treat it as last resort.

### Step 2 — Scenarios

Plain data files (`scenarios/*.json`), each a short script: start app, wait idle, mark
`startup`, open view X, mark, scroll list 50 steps, mark, close. Start with:

1. **Cold start to first frame** (process launch → first `frameSwapped` / first paint).
2. **Open the heaviest dialog/view** (click → view painted).
3. **Scroll/zoom the heaviest list or canvas** (frame times, p95, dropped frames).
4. **Typing latency** in the busiest editor field (key → paint).
5. **Memory** (RSS / private bytes) after scenario 2–3, and after closing (leak check).

### Step 3 — Two lanes

| Lane | Platform plugin | Runs where | Measures | Does not measure |
|---|---|---|---|---|
| **headless** | `QT_QPA_PLATFORM=offscreen` (+ software GL / `QSG_RHI_PREFER_SOFTWARE_RENDERER=1`) | any agent, locked session, Windows Session 0, containers | startup, layout, event handling, QML compile/instantiation, main-thread jank, memory | real GPU frame times, compositor, vsync |
| **display** | `xcb` on Xvfb or a dedicated X/Wayland/`eglfs` session; `windows` on an unlocked auto-logon desktop | labelled `perf-display` agents only | fps, frame pacing, click-to-photon-ish latency | — |

The headless lane is the one that gates merges. The display lane runs nightly on the
dedicated box(es) and produces trend charts; it only fails on gross regressions.

### Step 4 — Agents and the locked-session problem

Details and commands in [`docs/agents.md`](docs/agents.md). Summary:

**Linux**
- Run the Jenkins agent as a **systemd system service**, not inside anyone's desktop
  session. Then "the user locked the screen" is irrelevant.
- Headless lane: nothing needed (`offscreen`). Display lane: the job starts its own
  `Xvfb :99` (or `xvfb-run -a`) with Mesa llvmpipe, or, on a GPU perf box, the agent owns a
  bare `Xorg` on a free VT with no display manager, or Qt runs directly on KMS with
  `QT_QPA_PLATFORM=eglfs` (no compositor at all — the quietest setup you can get).
- Never use `xdotool`/`ydotool` against a session you don't own.

**Windows**
- An agent installed as a Windows service lives in **Session 0**: no interactive desktop,
  no DWM, GUI windows are invisible. Qt still runs there with `offscreen` (and even with
  the `windows` plugin, un-composited), so the **headless lane works unchanged**.
- A locked interactive session is *worse* than Session 0 for the display lane: DWM stops
  presenting (`DXGI_STATUS_OCCLUDED`), `SendInput` goes to the secure desktop, screenshots
  are black. So the display lane needs a **dedicated machine with auto-logon**, the agent
  started by a *scheduled task at log-on* (not as a service), screensaver and lock disabled
  by policy, a real or dummy monitor (HDMI dummy plug for physical boxes, a virtual display
  driver for VMs), and a rule that nobody RDPs into it (or they leave with
  `tscon <id> /dest:console` so the session returns to the physical console unlocked).

### Step 5 — Metrics and tooling per Qt flavour

- **Qt Quick**: `QT_LOGGING_RULES="qt.scenegraph.time.*=true"` for per-frame sync/render
  timings; the `qmlprofiler` CLI (ships with Qt Creator) can attach with
  `-qmljsdebugger=port:…,block` and dump a trace headless; `QSG_RENDER_TIMING=1`.
- **Widgets**: override `QApplication::notify` in the seam to time event dispatch; hook
  `paintEvent` via an event filter.
- **Both**: the jank-meter timer; `QBENCHMARK` micro-benchmarks in a QtTest executable for
  hot functions (models, delegates, parsers) — with `-perfcounter instructions` on Linux the
  numbers are nearly deterministic, far better than wall time.
- **System**: RSS/private bytes via `psutil` from the driver; CPU time of the process;
  optional `perf record` (Linux) / WPR (Windows) captures archived for the slow runs only.

### Step 6 — Making the numbers trustworthy

- Dedicated, labelled agents; `disableConcurrentBuilds()`; no other jobs on perf labels.
- Fixed environment: CPU governor `performance`, turbo off (optional, trades peak for
  stability), same Qt build, same screen size (set the virtual display to 1920×1080).
- Warm-up run discarded; then N = 5–10 repetitions; report **median and p95**, never mean.
- Compare to a **baseline** (last green result of the main branch for the same OS × lane ×
  scenario), with a relative threshold: > +10 % → UNSTABLE, > +25 % → FAIL, after
  confirming with one re-run. Thresholds per metric, tuned once we see the real noise.
- Keep every raw JSON as a build artifact; push summaries to a time series (Jenkins Plot /
  Benchmark plugin to start, InfluxDB + Grafana if trends matter).

### Step 7 — Jenkins pipeline shape

Sketch in [`ci/Jenkinsfile`](ci/Jenkinsfile): a declarative pipeline with a `matrix` over
`OS ∈ {linux, windows}` × `LANE ∈ {headless, display}`, display cells restricted by
`excludes`/labels to the prepared agents, each cell: build (or fetch) the app, run
`perfdrive.py --lane … --scenarios …`, archive JSON, publish JUnit-style pass/fail from
`compare.py`, update the baseline on main.

## 5. Proposed repository layout

```
qt-ui-perf/
├── README.md            this file
├── CONTRIBUTING.md      branch model (master / develop / feature PRs), what CI runs
├── docs/
│   └── agents.md        Linux / Windows agent setup, the locked-session details
├── harness/             perfdriver/ (C++ seam compiled into the app, CMake)
│                        qbench/     (QtTest micro-benchmarks, optional, not started)
├── sample-app/          instrumented Qt Widgets demo + testing-changes.diff
├── scenarios/           *.json scenario scripts
├── tools/
│   ├── perfdrive.py     launches the app, runs a scenario, writes results JSON
│   ├── compare.py       baseline comparison, thresholds, junit output   (not written)
│   └── report.py        markdown/HTML summary for the build page        (not written)
├── tests/
│   ├── fake_app.py      speaks the perfdriver protocol without Qt
│   ├── test_*.py        unit tests for the driver and the scenario files
│   └── smoke.sh         build sample-app + play the scenario (what CI runs)
├── .github/workflows/   GitHub Actions PR checks
└── ci/
    ├── Jenkinsfile      perf pipeline sketch for the dedicated agents
    ├── linux-agent-setup.sh      (not written)
    └── windows-agent-setup.ps1   (not written)
```

## 6. First iteration (what I would actually do in the first week)

1. Get answers to the open questions in §3, pick Qt flavour and 3 scenarios.
2. Prove the headless lane on a laptop: app + `--perf-driver` + `offscreen`, one scenario,
   JSON out, on Linux and on Windows. No Jenkins yet.
3. Run it 20× in a row on one machine and look at the spread. This tells us the thresholds
   and whether `offscreen` is representative enough for the CPU-side metrics.
4. Wire the Jenkins matrix with the headless lane only; store baselines; make it gate.
5. Prepare one display agent per OS per `docs/agents.md`; add the display lane nightly.
6. Only then: micro-benchmarks, profiler traces on regression, dashboards.

## 7. Things explicitly not planned

- Pixel-comparison / visual regression testing (different tool, different noise).
- Driving the app through screen coordinates or OS input injection.
- Running perf on shared build agents and hoping thresholds absorb the noise.
