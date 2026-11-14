# Copyright Contributors to the OpenVDB Project
# SPDX-License-Identifier: Apache-2.0

find_package(GTest 1.10 REQUIRED)

add_executable(mogac_test
  main.cc
  TestLevelSetMultiObject.cc
  TestLevelSetMultiObjectMesh.cc)

target_link_libraries(mogac_test PRIVATE MOGAC::mogac GTest::gtest)

include(GoogleTest)
gtest_discover_tests(mogac_test DISCOVERY_TIMEOUT 60)
