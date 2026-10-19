#!/usr/bin/env sh
# Build the sample app with the perf driver seam and play scenarios/sample_app.json in the
# headless lane. This is the end-to-end check that the C++ seam, the Python driver and the
# scenario format still agree. Any Qt 5.15+ or Qt 6 with Widgets will do.
#
#   tests/smoke.sh [build-dir] [extra cmake args...]
#
# Env: QT_MAJOR=5|6 to pin a Qt (default: whatever CMake finds first, Qt6 preferred),
#      REPEATS (default 2), OUT (result JSON, default results/smoke.json),
#      SMOKE_QUICK=0|1 (see below).
#
# When Qt Quick is installed as well, the Qt Quick sample (sample-app-quick/) is built into
# <build-dir>-quick and scenarios/sample_app_quick.json is played too, results next to OUT
# as <OUT>-quick.json. It is skipped, with a notice, when the Qt Quick CMake package or the
# QtQuick.Controls QML module is missing. SMOKE_QUICK=0 disables it, SMOKE_QUICK=1 makes a
# skip a failure.
set -eu

cd "$(dirname "$0")/.."
if [ $# -gt 0 ]; then
    BUILD="$1"
    shift
    QBUILD="${BUILD}-quick"
else
    BUILD="sample-app/build-smoke"
    QBUILD="sample-app-quick/build-smoke"
fi
REPEATS="${REPEATS:-2}"
OUT="${OUT:-results/smoke.json}"
QOUT="${OUT%.json}-quick.json"

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

# ---- optional: the Qt Quick sample ---------------------------------------------------------
QUICK="${SMOKE_QUICK:-auto}"
[ "$QUICK" = "0" ] && exit 0

skip_quick() {
    if [ "$QUICK" = "1" ]; then
        echo "smoke: Qt Quick smoke required (SMOKE_QUICK=1) but $1" >&2
        exit 1
    fi
    echo "smoke: skipping the Qt Quick sample: $1" >&2
    exit 0
}

# shellcheck disable=SC2086
if ! cmake -S sample-app-quick -B "$QBUILD" -DCMAKE_BUILD_TYPE=Release -DSAMPLEAPP_PERF_DRIVER=ON $PIN "$@"; then
    skip_quick "Qt Quick is not installed for this Qt (configure failed, see above)"
fi
if ! grep -q '^SAMPLEAPPQUICK_HAS_CONTROLS:BOOL=ON' "$QBUILD/CMakeCache.txt"; then
    skip_quick "the QtQuick.Controls QML module is not installed"
fi
cmake --build "$QBUILD" --config Release --parallel

QEXE="$QBUILD/SampleAppQuick"
[ -x "$QEXE" ] || QEXE="$QBUILD/Release/SampleAppQuick.exe"
[ -x "$QEXE" ] || QEXE="$QBUILD/SampleAppQuick.exe"

python3 tools/perfdrive.py --app "$QEXE" --scenario scenarios/sample_app_quick.json \
    --lane headless --repeats "$REPEATS" --out "$QOUT"
