# Integrating qt-ui-perf into your application

Two pieces: the C++ seam (`harness/perfdriver`, CMake package **QtUiPerf**) compiled into
the application, and the Python driver (`tools/perfdrive.py`, pip package **qtuiperf**) that
runs scenarios against it on the CI agent. Both are one line to pull in.

## 1. C++: the seam

### Get the package

Pick one. All three give you the target `QtUiPerf::perfdriver` and the function
`qtuiperf_instrument()`.

**add_subdirectory** (vendored checkout or git submodule):

```cmake
add_subdirectory(third_party/qt-ui-perf/harness/perfdriver)
```

**FetchContent** (CMake 3.18+; full example in [`examples/fetchcontent/`](../examples/fetchcontent/CMakeLists.txt)):

```cmake
include(FetchContent)
FetchContent_Declare(QtUiPerf
    GIT_REPOSITORY https://github.com/Hanz98/qt-ui-perf.git
    GIT_TAG        v0.1.0                  # a tag or commit, not a branch, for reproducible builds
    SOURCE_SUBDIR  harness/perfdriver)     # only the library, not the sample app and tests
FetchContent_MakeAvailable(QtUiPerf)
```

**find_package** (installed once per toolchain, e.g. into the Qt prefix or a shared SDK dir):

```sh
cmake -S qt-ui-perf/harness/perfdriver -B build-perfdriver [-DPERFDRIVER_QT_MAJOR=5]
cmake --build build-perfdriver
cmake --install build-perfdriver --prefix /opt/qtuiperf
```

```cmake
find_package(QtUiPerf 0.1 CONFIG REQUIRED)    # CMAKE_PREFIX_PATH=/opt/qtuiperf
```

Installed layout: `lib/libqtuiperf-perfdriver.a`, `include/qtuiperf/perfdriver.h`,
`lib/cmake/QtUiPerf/QtUiPerfConfig.cmake` (+ `ConfigVersion`, `Targets`, `Helpers`). The
config file does `find_dependency(Qt<N> COMPONENTS Widgets)` for the Qt major it was built
with and exports `QtUiPerf_QT_MAJOR`, so a consumer can write
`find_package(Qt${QtUiPerf_QT_MAJOR} COMPONENTS Widgets)` and be sure the majors match.

### Which Qt

The seam builds against Qt 5.15 or Qt 6 (Widgets only, no extra modules). With
`add_subdirectory`/FetchContent it uses the `QT_VERSION_MAJOR` your project already set
(the variable `find_package(QT NAMES Qt6 Qt5 ...)` produces); if that is unset it detects
Qt itself, preferring Qt 6. `-DPERFDRIVER_QT_MAJOR=5|6` pins it either way. One rule: the
app and the seam must link the same Qt, which the exported `Qt<N>::Widgets` dependency
enforces at configure time.

### Instrument the target

```cmake
option(MYAPP_PERF_DRIVER "Compile in the UI perf seam (dormant unless --perf-driver)" ON)
if(MYAPP_PERF_DRIVER)
    qtuiperf_instrument(MyApp)      # links QtUiPerf::perfdriver, defines QTUIPERF_ENABLED
endif()
```

`qtuiperf_instrument(<target>)` is `target_link_libraries(<target> PRIVATE
QtUiPerf::perfdriver)` plus `target_compile_definitions(<target> PRIVATE QTUIPERF_ENABLED)`.
Keeping it behind your own option lets release builds leave the seam out entirely; builds
that include it still behave normally unless started with `--perf-driver` or
`QT_PERF_DRIVER=1`.

### The two calls in main()

```cpp
#include <QApplication>

#ifdef QTUIPERF_ENABLED
#include <perfdriver.h>
#endif

int main(int argc, char *argv[])
{
#ifdef QTUIPERF_ENABLED
    PerfDriver::markProcessStart();        // first line of main(): starts the startup clock
#endif
    QApplication app(argc, argv);
#ifdef QTUIPERF_ENABLED
    PerfDriver::installIfRequested(app);   // no-op unless --perf-driver / QT_PERF_DRIVER
#endif
    ...
    return app.exec();
}
```

`markProcessStart()` must run before the `QApplication` constructor, because the
"startup to first paint" metric is measured from it. `installIfRequested()` needs the
application object; when active it takes over stdin/stdout for the driver protocol (see
[`harness/README.md`](../harness/README.md)), so an instrumented app must not use stdin itself
and should keep its own stdout output free of lines starting with `@perf `.

The complete app-side change for the sample app, as a patch:
[`sample-app/testing-changes.diff`](../sample-app/testing-changes.diff).

### objectName conventions

Scenarios address widgets by `QObject::objectName()`. Give a stable name to every widget a
scenario drives or reads, and to the top-level windows:

- Names are looked up among all top-level widgets and their descendants; `parent/child`
  paths disambiguate duplicates (`settingsDialog/okButton`).
- Name the *thing the user interacts with* (`countButton`, `levelSlider`, `searchField`), not
  layouts or containers, and name the labels/fields whose value proves the interaction took
  effect (`clicksLabel`, `statusLabel`) so `get … expect` steps can check them.
- lowerCamelCase, no spaces, stable across refactors: names are part of the scenario
  contract, treat renaming one like renaming a public API.
- Set them in code (`setObjectName(QStringLiteral("countButton"))`) or in the `.ui` file
  (Qt Designer's object name is exactly this).

## 2. Python: the driver

Standard library only, Python 3.8+. Either run the file from a checkout:

```sh
python3 tools/perfdrive.py --app ./build/MyApp --scenario scenarios/my_app.json \
        --lane headless --repeats 5 --out results/my_app.json
```

or install it (no dependencies, so a venv on the agent is all it needs):

```sh
pip install git+https://github.com/Hanz98/qt-ui-perf.git@v0.1.0
perfdrive --app ./build/MyApp --scenario scenarios/my_app.json --lane headless --out results/my_app.json
python3 -m qtuiperf.perfdrive --help     # same thing
```

The package is `qtuiperf`; `tools/perfdrive.py` is `qtuiperf.perfdrive` once installed
(`pyproject.toml` maps the directory, so every `tools/*.py` module ships the same way).

## 3. Scenarios

Scenario files are JSON; [`scenarios/schema.json`](../scenarios/schema.json) describes every
step and field (point your editor at it with `"$schema": "./schema.json"`), and
[`scenarios/sample_app.json`](../scenarios/sample_app.json) is a complete example. Keep your
scenarios next to your app and run `tests/test_scenarios.py`-style validation in your own
CI if you like; the schema is the contract.

## 4. Checking the integration

From a checkout of this repository:

```sh
cmake -S . -B build && cmake --build build          # seam + sample app
ctest --test-dir build --output-on-failure           # plays scenarios/sample_app.json headless
tests/smoke.sh                                       # same, building sample-app/ standalone
```

For your own app: build it with the seam, then
`perfdrive --app <exe> --scenario <file> --lane headless --repeats 1`. If the app does not
report ready it was not built with the seam (check `QTUIPERF_ENABLED` reached `main.cpp`) or
its stdout is not reaching the driver.
