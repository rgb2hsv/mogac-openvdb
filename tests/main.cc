// Copyright Contributors to the OpenVDB Project
// SPDX-License-Identifier: Apache-2.0

#include <gtest/gtest.h>

#include <openvdb/util/logging.h>

int
main(int argc, char *argv[])
{
    ::testing::InitGoogleTest(&argc, argv);

    // Tests that exercise warnings would otherwise flood the test output.
    openvdb::logging::initialize();
    openvdb::logging::removeSink(openvdb::logging::ConsoleSink::defaultName());

    return RUN_ALL_TESTS();
}
