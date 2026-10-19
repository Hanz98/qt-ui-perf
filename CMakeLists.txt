# Repository-level build: the perfdriver seam (harness/perfdriver, package "QtUiPerf"), the
# instrumented sample application and a CTest test that plays scenarios/sample_app.json
# against it in the headless lane.
#
#     cmake -S . -B build [-DPERFDRIVER_QT_MAJOR=5]
#     cmake --build build
#     ctest --test-dir build --output-on-failure
#     cmake --install build --prefix /opt/qtuiperf       # then find_package(QtUiPerf) elsewhere
#
# Other projects do not need this file: they consume harness/perfdriver directly
# (add_subdirectory / FetchContent with SOURCE_SUBDIR harness/perfdriver / find_package). If
# this root is pulled in with FetchContent anyway, samples and tests default to off.
cmake_minimum_required(VERSION 3.16)
project(qt-ui-perf VERSION 0.1.0 LANGUAGES CXX)

if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    set(_qtuiperf_top_level ON)
else()
    set(_qtuiperf_top_level OFF)
endif()
option(QTUIPERF_BUILD_SAMPLES "Build the instrumented sample application(s)" ${_qtuiperf_top_level})
option(QTUIPERF_INSTALL "Generate install rules and the QtUiPerfConfig.cmake package" ${_qtuiperf_top_level})

# One Qt for everything below: -DPERFDRIVER_QT_MAJOR=5|6 pins it, otherwise Qt 6 is preferred.
set(PERFDRIVER_QT_MAJOR "" CACHE STRING "Qt major version to build against (5 or 6); empty = autodetect")
if(PERFDRIVER_QT_MAJOR)
    set(QT_VERSION_MAJOR ${PERFDRIVER_QT_MAJOR})
else()
    find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Widgets)
endif()

add_subdirectory(harness/perfdriver)

if(QTUIPERF_BUILD_SAMPLES)
    add_subdirectory(sample-app)
endif()

if(_qtuiperf_top_level)
    include(CTest)
endif()
if(BUILD_TESTING AND QTUIPERF_BUILD_SAMPLES)
    find_package(Python3 REQUIRED COMPONENTS Interpreter)
    # The end-to-end check: C++ seam, Python driver and scenario format still agree.
    # Headless lane, one measured run; it checks the tooling, not performance.
    add_test(NAME sample_app_scenario
        COMMAND Python3::Interpreter ${CMAKE_CURRENT_SOURCE_DIR}/tools/perfdrive.py
            --app $<TARGET_FILE:SampleApp>
            --scenario ${CMAKE_CURRENT_SOURCE_DIR}/scenarios/sample_app.json
            --lane headless --repeats 1
            --out ${CMAKE_CURRENT_BINARY_DIR}/results/sample_app_scenario.json
        WORKING_DIRECTORY ${CMAKE_CURRENT_SOURCE_DIR}
    )
    set_tests_properties(sample_app_scenario PROPERTIES TIMEOUT 300)
endif()
