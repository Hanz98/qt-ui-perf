cmake_minimum_required(VERSION 3.16)
project(SampleAppQuick LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)
set(CMAKE_AUTORCC ON)

# Qt 6 when both are installed; -DSAMPLEAPP_QT_MAJOR=5 pins Qt 5 (used by tests/smoke.sh and CI).
set(SAMPLEAPP_QT_MAJOR "" CACHE STRING "Qt major version to build against (5 or 6); empty = autodetect")
if(SAMPLEAPP_QT_MAJOR)
    set(QT_VERSION_MAJOR ${SAMPLEAPP_QT_MAJOR})
else()
    find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Quick)
endif()
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Gui Qml Quick)

add_executable(SampleAppQuick
    main.cpp
    qml.qrc
)
target_link_libraries(SampleAppQuick PRIVATE Qt${QT_VERSION_MAJOR}::Gui Qt${QT_VERSION_MAJOR}::Qml Qt${QT_VERSION_MAJOR}::Quick)

# UI performance testing: compile in the dormant automation seam (harness/perfdriver).
# It only activates when the app is started with --perf-driver; see harness/README.md.
option(SAMPLEAPP_PERF_DRIVER "Compile in the perf driver seam (dormant unless --perf-driver)" ON)
if(SAMPLEAPP_PERF_DRIVER)
    add_subdirectory(${CMAKE_CURRENT_SOURCE_DIR}/../harness/perfdriver perfdriver)
    target_link_libraries(SampleAppQuick PRIVATE perfdriver)
    target_compile_definitions(SampleAppQuick PRIVATE SAMPLEAPP_PERF_DRIVER)
endif()

# main.qml imports QtQuick.Controls, a runtime-only dependency CMake cannot check. Warn now
# rather than fail at startup; tests/smoke.sh reads SAMPLEAPPQUICK_HAS_CONTROLS to skip.
set(_controls_qmldir "")
if(TARGET Qt${QT_VERSION_MAJOR}::qmake)
    get_target_property(_qmake Qt${QT_VERSION_MAJOR}::qmake IMPORTED_LOCATION)
    execute_process(COMMAND "${_qmake}" -query QT_INSTALL_QML
                    OUTPUT_VARIABLE _qml_dir OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
    if(QT_VERSION_MAJOR EQUAL 5)
        set(_controls_qmldir "${_qml_dir}/QtQuick/Controls.2/qmldir")
    else()
        set(_controls_qmldir "${_qml_dir}/QtQuick/Controls/qmldir")
    endif()
endif()
if(_controls_qmldir AND NOT EXISTS "${_controls_qmldir}")
    message(WARNING "QtQuick.Controls QML module not found (${_controls_qmldir}); SampleAppQuick will not start")
    set(SAMPLEAPPQUICK_HAS_CONTROLS OFF CACHE BOOL "QtQuick.Controls QML module was found at configure time" FORCE)
else()
    set(SAMPLEAPPQUICK_HAS_CONTROLS ON CACHE BOOL "QtQuick.Controls QML module was found at configure time" FORCE)
endif()

if(WIN32)
    set_target_properties(SampleAppQuick PROPERTIES WIN32_EXECUTABLE ON)
endif()
