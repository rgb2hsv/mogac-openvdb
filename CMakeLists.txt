# Copyright Contributors to the OpenVDB Project
# SPDX-License-Identifier: Apache-2.0
#
# MOGAC (Multi-Object Geodesic Active Contours) for OpenVDB.
#
# A header-only library (include/mogac) built on top of OpenVDB. By default
# OpenVDB is built from the external/openvdb git submodule; set
# MOGAC_USE_SYSTEM_OPENVDB=ON to use an installed OpenVDB instead (found with
# find_package(OpenVDB), e.g. via CMAKE_PREFIX_PATH or CMAKE_MODULE_PATH).

cmake_minimum_required(VERSION 3.24)
project(MOGAC LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17 CACHE STRING "C++ standard")
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "Build type" FORCE)
endif()

option(MOGAC_USE_SYSTEM_OPENVDB "Use an installed OpenVDB instead of the external/openvdb submodule" OFF)
option(MOGAC_BUILD_TESTS "Build the MOGAC unit tests" ON)

#########################################################################
# OpenVDB
#
# OpenVDB's CMake files assume OpenVDB is the top-level project, so it cannot
# be pulled in with add_subdirectory(). Instead the submodule is configured,
# built and installed into the build tree at configure time (once, and again
# whenever the submodule commit or the options below change), and then found
# like any installed OpenVDB.

set(MOGAC_OPENVDB_CMAKE_ARGS "" CACHE STRING
  "Extra CMake arguments for building the OpenVDB submodule (a ;-list)")
option(MOGAC_OPENVDB_USE_BLOSC "Build the OpenVDB submodule with Blosc compression" OFF)

if(MOGAC_USE_SYSTEM_OPENVDB)
  find_package(OpenVDB REQUIRED COMPONENTS openvdb)
else()
  set(OPENVDB_SOURCE_DIR ${CMAKE_CURRENT_SOURCE_DIR}/external/openvdb)
  if(NOT EXISTS ${OPENVDB_SOURCE_DIR}/CMakeLists.txt)
    message(FATAL_ERROR "The OpenVDB submodule is missing. Run:\n"
      "  git submodule update --init --recursive")
  endif()

  set(_ovdb_build ${CMAKE_BINARY_DIR}/openvdb-build)
  set(_ovdb_install ${CMAKE_BINARY_DIR}/openvdb-install)
  set(_ovdb_args
    -DCMAKE_BUILD_TYPE=${CMAKE_BUILD_TYPE}
    -DCMAKE_INSTALL_PREFIX=${_ovdb_install}
    -DCMAKE_CXX_COMPILER=${CMAKE_CXX_COMPILER}
    -DCMAKE_CXX_STANDARD=${CMAKE_CXX_STANDARD}
    -DOPENVDB_BUILD_CORE=ON
    -DOPENVDB_CORE_SHARED=ON
    -DOPENVDB_CORE_STATIC=OFF
    -DOPENVDB_BUILD_BINARIES=OFF
    -DOPENVDB_BUILD_UNITTESTS=OFF
    -DOPENVDB_BUILD_DOCS=OFF
    -DOPENVDB_BUILD_PYTHON_MODULE=OFF
    -DOPENVDB_BUILD_AX=OFF
    -DOPENVDB_BUILD_NANOVDB=OFF
    -DOPENVDB_ENABLE_UNINSTALL=OFF
    -DUSE_BLOSC=${MOGAC_OPENVDB_USE_BLOSC}
    ${MOGAC_OPENVDB_CMAKE_ARGS})

  find_package(Git QUIET)
  set(_ovdb_commit "unknown")
  if(GIT_FOUND)
    execute_process(COMMAND ${GIT_EXECUTABLE} -C ${OPENVDB_SOURCE_DIR} rev-parse HEAD
      OUTPUT_VARIABLE _ovdb_commit OUTPUT_STRIP_TRAILING_WHITESPACE ERROR_QUIET)
  endif()
  string(SHA1 _ovdb_key "${_ovdb_commit};${_ovdb_args}")
  set(_ovdb_stamp ${_ovdb_install}/mogac-openvdb.stamp)
  set(_ovdb_old_key "")
  if(EXISTS ${_ovdb_stamp})
    file(READ ${_ovdb_stamp} _ovdb_old_key)
  endif()

  if(NOT _ovdb_old_key STREQUAL _ovdb_key)
    include(ProcessorCount)
    ProcessorCount(_ncpu)
    if(_ncpu EQUAL 0)
      set(_ncpu 1)
    endif()
    message(STATUS "Building the OpenVDB submodule (${_ovdb_commit}) into ${_ovdb_install}")
    execute_process(COMMAND ${CMAKE_COMMAND} -S ${OPENVDB_SOURCE_DIR} -B ${_ovdb_build}
      -G ${CMAKE_GENERATOR} ${_ovdb_args} RESULT_VARIABLE _rc)
    if(_rc EQUAL 0)
      execute_process(COMMAND ${CMAKE_COMMAND} --build ${_ovdb_build}
        --config ${CMAKE_BUILD_TYPE} --parallel ${_ncpu} RESULT_VARIABLE _rc)
    endif()
    if(_rc EQUAL 0)
      execute_process(COMMAND ${CMAKE_COMMAND} --install ${_ovdb_build}
        --config ${CMAKE_BUILD_TYPE} RESULT_VARIABLE _rc)
    endif()
    if(NOT _rc EQUAL 0)
      message(FATAL_ERROR "Building the OpenVDB submodule failed (see ${_ovdb_build})")
    endif()
    file(WRITE ${_ovdb_stamp} "${_ovdb_key}")
  endif()

  # The OpenVDBConfig.cmake at this OpenVDB commit only looks up ZLIB when
  # Blosc is enabled, but the exported target always links ZLIB::ZLIB.
  find_package(ZLIB 1.2.7 REQUIRED)
  find_package(OpenVDB REQUIRED CONFIG PATHS ${_ovdb_install} NO_DEFAULT_PATH)
endif()

#########################################################################
# MOGAC (header only)

add_library(mogac INTERFACE)
add_library(MOGAC::mogac ALIAS mogac)
target_include_directories(mogac INTERFACE
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>)
target_link_libraries(mogac INTERFACE OpenVDB::openvdb)
target_compile_features(mogac INTERFACE cxx_std_17)

include(GNUInstallDirs)
install(DIRECTORY include/mogac DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

#########################################################################
# Tests

if(MOGAC_BUILD_TESTS)
  enable_testing()
  add_subdirectory(tests)
endif()
