# The automation seam. Link it into the application and call PerfDriver::markProcessStart()
# first thing in main() and PerfDriver::installIfRequested(app) after the application object
# exists. It stays dormant unless the app is started with --perf-driver (or QT_PERF_DRIVER=1).
# Expects QT_VERSION_MAJOR to be set by the including project.
add_library(perfdriver STATIC
    perfdriver.cpp
    perfdriver.h
)
target_include_directories(perfdriver PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
if(NOT TARGET Qt${QT_VERSION_MAJOR}::Widgets)   # a Qt Quick application has not looked for it
    find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Widgets)
endif()
target_link_libraries(perfdriver PUBLIC Qt${QT_VERSION_MAJOR}::Widgets)
target_compile_features(perfdriver PUBLIC cxx_std_17)

# Qt Quick support (QQuickWindow item trees, frameSwapped-based paint detection, frame
# stats). Optional, so Widgets-only applications never pick up a QtQuick dependency:
# default ON when the Qt Quick CMake package is found, OFF otherwise; -DPERFDRIVER_QUICK=OFF
# forces a Widgets-only seam even when Qt Quick is installed.
set(_perfdriver_quick_default OFF)
if(NOT DEFINED PERFDRIVER_QUICK)
    find_package(Qt${QT_VERSION_MAJOR} QUIET OPTIONAL_COMPONENTS Quick)
    if(Qt${QT_VERSION_MAJOR}Quick_FOUND)
        set(_perfdriver_quick_default ON)
    endif()
endif()
option(PERFDRIVER_QUICK "Qt Quick support in the perf driver seam (needs Qt${QT_VERSION_MAJOR}::Quick)" ${_perfdriver_quick_default})
if(PERFDRIVER_QUICK)
    find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Quick)
    target_link_libraries(perfdriver PUBLIC Qt${QT_VERSION_MAJOR}::Quick)
    target_compile_definitions(perfdriver PRIVATE PERFDRIVER_HAVE_QUICK)
endif()
message(STATUS "perfdriver: Qt Quick support ${PERFDRIVER_QUICK}")
