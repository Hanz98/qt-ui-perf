# The automation seam, packaged as the CMake package "QtUiPerf" with one target:
#
#     QtUiPerf::perfdriver      static library, header <perfdriver.h>, links Qt Widgets
#
# and one helper function (cmake/QtUiPerfHelpers.cmake):
#
#     qtuiperf_instrument(<target>)   links the seam into <target> and defines QTUIPERF_ENABLED
#
# Consumable three ways, see docs/integration.md:
#   add_subdirectory(path/to/qt-ui-perf/harness/perfdriver)
#   FetchContent_Declare(QtUiPerf GIT_REPOSITORY https://github.com/Hanz98/qt-ui-perf.git ...)
#   find_package(QtUiPerf CONFIG)        after `cmake --install` of this directory
#
# The seam stays dormant unless the app is started with --perf-driver (or QT_PERF_DRIVER=1).
cmake_minimum_required(VERSION 3.16)
project(QtUiPerf VERSION 0.1.0 LANGUAGES CXX)

if(CMAKE_CURRENT_SOURCE_DIR STREQUAL CMAKE_SOURCE_DIR)
    set(_qtuiperf_top_level ON)
else()
    set(_qtuiperf_top_level OFF)
endif()
option(QTUIPERF_INSTALL "Generate install rules and the QtUiPerfConfig.cmake package" ${_qtuiperf_top_level})

# ---- Qt ------------------------------------------------------------------------------------
# An including project that already chose a Qt passes it down through QT_VERSION_MAJOR (the
# variable find_package(QT NAMES Qt6 Qt5) sets). -DPERFDRIVER_QT_MAJOR=5|6 pins it explicitly;
# otherwise Qt 6 is preferred when both are installed.
set(PERFDRIVER_QT_MAJOR "" CACHE STRING "Qt major version to build the seam against (5 or 6); empty = autodetect")
if(PERFDRIVER_QT_MAJOR)
    set(QT_VERSION_MAJOR ${PERFDRIVER_QT_MAJOR})
elseif(NOT QT_VERSION_MAJOR)
    find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Widgets)
endif()

# Every Qt component the seam links. The list is also what the installed config file asks
# find_dependency() for, so an optional extra module only needs to be appended here.
set(PERFDRIVER_QT_COMPONENTS Widgets)

# ---- optional components ---------------------------------------------------------------------
# Extra Qt modules go here, each behind an option that appends its component to
# PERFDRIVER_QT_COMPONENTS, adds the matching PERFDRIVER_HAVE_<MODULE> compile definition to
# PERFDRIVER_DEFINITIONS and, if the installed package must know about it, a line in
# cmake/QtUiPerfConfig.cmake.in. Example of the pattern (Qt Quick, option PERFDRIVER_QUICK):
#
#     option(PERFDRIVER_QUICK "Also drive Qt Quick windows (links Qt::Quick)" OFF)
#     if(PERFDRIVER_QUICK)
#         list(APPEND PERFDRIVER_QT_COMPONENTS Quick)
#         list(APPEND PERFDRIVER_DEFINITIONS PERFDRIVER_HAVE_QUICK)
#     endif()
set(PERFDRIVER_DEFINITIONS "")
# ---- end optional components ----------------------------------------------------------------

find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS ${PERFDRIVER_QT_COMPONENTS})

# ---- library -------------------------------------------------------------------------------
add_library(perfdriver STATIC
    perfdriver.cpp
    perfdriver.h
)
add_library(QtUiPerf::perfdriver ALIAS perfdriver)

include(GNUInstallDirs)
target_include_directories(perfdriver PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}/qtuiperf>
)
foreach(_component IN LISTS PERFDRIVER_QT_COMPONENTS)
    target_link_libraries(perfdriver PUBLIC Qt${QT_VERSION_MAJOR}::${_component})
endforeach()
if(PERFDRIVER_DEFINITIONS)
    target_compile_definitions(perfdriver PUBLIC ${PERFDRIVER_DEFINITIONS})
endif()
target_compile_features(perfdriver PUBLIC cxx_std_17)
set_target_properties(perfdriver PROPERTIES
    AUTOMOC ON
    OUTPUT_NAME qtuiperf-perfdriver
    EXPORT_NAME perfdriver
    POSITION_INDEPENDENT_CODE ON    # the static lib may end up inside a shared app library
)

# qtuiperf_instrument() for add_subdirectory / FetchContent users. The installed package
# includes the same file from its config.
include(${CMAKE_CURRENT_SOURCE_DIR}/cmake/QtUiPerfHelpers.cmake)

# ---- install + find_package() support -------------------------------------------------------
if(QTUIPERF_INSTALL)
    include(CMakePackageConfigHelpers)
    set(_qtuiperf_cmake_dir ${CMAKE_INSTALL_LIBDIR}/cmake/QtUiPerf)

    install(TARGETS perfdriver EXPORT QtUiPerfTargets
        ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
        LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    )
    install(FILES perfdriver.h DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}/qtuiperf)
    install(EXPORT QtUiPerfTargets
        NAMESPACE QtUiPerf::
        DESTINATION ${_qtuiperf_cmake_dir}
    )

    configure_package_config_file(
        ${CMAKE_CURRENT_SOURCE_DIR}/cmake/QtUiPerfConfig.cmake.in
        ${CMAKE_CURRENT_BINARY_DIR}/QtUiPerfConfig.cmake
        INSTALL_DESTINATION ${_qtuiperf_cmake_dir}
    )
    write_basic_package_version_file(
        ${CMAKE_CURRENT_BINARY_DIR}/QtUiPerfConfigVersion.cmake
        VERSION ${PROJECT_VERSION}
        COMPATIBILITY SameMajorVersion
    )
    install(FILES
        ${CMAKE_CURRENT_BINARY_DIR}/QtUiPerfConfig.cmake
        ${CMAKE_CURRENT_BINARY_DIR}/QtUiPerfConfigVersion.cmake
        ${CMAKE_CURRENT_SOURCE_DIR}/cmake/QtUiPerfHelpers.cmake
        DESTINATION ${_qtuiperf_cmake_dir}
    )
endif()
