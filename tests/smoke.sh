#!/usr/bin/env sh
# Build the sample app with the perf driver seam and play scenarios/sample_app.json in the
# headless lane. This is the end-to-end check that the C++ seam, the Python driver and the
# scenario format still agree. Any Qt 5.15+ or Qt 6 with Widgets will do.
#
#   tests/smoke.sh [build-dir] [extra cmake args...]
#
# Env: QT_MAJOR=5|6 to pin a Qt (default: whatever CMake finds first, Qt6 preferred),
#      REPEATS (default 2), OUT (result JSON, default results/smoke.json).
set -eu

cd "$(dirname "$0")/.."
BUILD="${1:-sample-app/build-smoke}"
[ $# -gt 0 ] && shift
REPEATS="${REPEATS:-2}"
OUT="${OUT:-results/smoke.json}"

PIN=""
if [ -n "${QT_MAJOR:-}" ]; then
    PIN="-DSAMPLEAPP_QT_MAJOR=$QT_MAJOR"
fi

# shellcheck disable=SC2086
cmake -S sample-app -B "$BUILD" -DCMAKE_BUILD_TYPE=Release -DSAMPLEAPP_PERF_DRIVER=ON $PIN "$@"
cmake --build "$BUILD" --config Release --parallel

EXE="$BUILD/SampleApp"
[ -x "$EXE" ] || EXE="$BUILD/Release/SampleApp.exe"
[ -x "$EXE" ] || EXE="$BUILD/SampleApp.exe"

python3 tools/perfdrive.py --app "$EXE" --scenario scenarios/sample_app.json \
    --lane headless --repeats "$REPEATS" --out "$OUT"

# The gate, end to end: a result compared with itself must pass (exit 0) and must produce
# the JUnit/Markdown files the pipeline publishes.
python3 tools/compare.py "$OUT" --baseline "$OUT" --scenario scenarios/sample_app.json \
    --junit "${OUT%.json}-junit.xml" --markdown "${OUT%.json}.md"
