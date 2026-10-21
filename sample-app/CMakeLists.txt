cmake_minimum_required(VERSION 3.16)
project(SampleApp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

# Qt 6 when both are installed; -DSAMPLEAPP_QT_MAJOR=5 pins Qt 5 (used by tests/smoke.sh and CI).
# When built from the repository root, the root project has already chosen (QT_VERSION_MAJOR).
set(SAMPLEAPP_QT_MAJOR "" CACHE STRING "Qt major version to build against (5 or 6); empty = autodetect")
if(SAMPLEAPP_QT_MAJOR)
    set(QT_VERSION_MAJOR ${SAMPLEAPP_QT_MAJOR})
elseif(NOT QT_VERSION_MAJOR)
    find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Widgets)
endif()
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Widgets)

add_executable(SampleApp
    main.cpp
    mainwindow.h
    mainwindow.cpp
)
target_link_libraries(SampleApp PRIVATE Qt${QT_VERSION_MAJOR}::Widgets)

# UI performance testing: compile in the dormant automation seam (qt-ui-perf, harness/perfdriver).
# It only activates when the app is started with --perf-driver; see docs/integration.md.
# qtuiperf_instrument() links QtUiPerf::perfdriver and defines QTUIPERF_ENABLED for main.cpp.
option(SAMPLEAPP_PERF_DRIVER "Compile in the perf driver seam (dormant unless --perf-driver)" ON)
if(SAMPLEAPP_PERF_DRIVER)
    if(NOT TARGET QtUiPerf::perfdriver)   # already there when built from the repository root
        add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../harness/perfdriver perfdriver)
    endif()
    qtuiperf_instrument(SampleApp)
endif()

if(WIN32)
    set_target_properties(SampleApp PROPERTIES WIN32_EXECUTABLE ON)
endif()
