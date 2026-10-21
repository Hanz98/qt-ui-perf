# Minimal application that pulls the qt-ui-perf seam in with FetchContent. Not built by CI;
# configure it against a checkout without network access with
#
#     cmake -S examples/fetchcontent -B /tmp/fc-build \
#           -DFETCHCONTENT_SOURCE_DIR_QTUIPERF=/path/to/qt-ui-perf
#
# or let CMake clone it (replace GIT_TAG with a release tag or commit in real use).
cmake_minimum_required(VERSION 3.18)   # 3.18: SOURCE_SUBDIR in FetchContent_Declare
project(FetchContentExample LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(QT NAMES Qt6 Qt5 REQUIRED COMPONENTS Widgets)
find_package(Qt${QT_VERSION_MAJOR} REQUIRED COMPONENTS Widgets)

include(FetchContent)
FetchContent_Declare(QtUiPerf
    GIT_REPOSITORY https://github.com/Hanz98/qt-ui-perf.git
    GIT_TAG        develop
    GIT_SHALLOW    TRUE
    SOURCE_SUBDIR  harness/perfdriver      # only the library, not the samples/tests
)
FetchContent_MakeAvailable(QtUiPerf)      # defines QtUiPerf::perfdriver + qtuiperf_instrument()

add_executable(FetchContentExample main.cpp)
target_link_libraries(FetchContentExample PRIVATE Qt${QT_VERSION_MAJOR}::Widgets)

option(EXAMPLE_PERF_DRIVER "Compile in the UI perf seam (dormant unless --perf-driver)" ON)
if(EXAMPLE_PERF_DRIVER)
    qtuiperf_instrument(FetchContentExample)
endif()
