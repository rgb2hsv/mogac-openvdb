// Copyright Contributors to the OpenVDB Project
// SPDX-License-Identifier: Apache-2.0

/// @file tests/TestLevelSetMultiObjectVideo.cc
///
/// @brief Scenes for the demo videos (docs/media), at a chosen resolution.
///
/// Disabled by default: they only make sense with frame dumping on. Run with
///
///     OPENVDB_MOGAC_FRAME_DIR=<dir> mogac_test --gtest_also_run_disabled_tests \
///         --gtest_filter='*DISABLED_TopologyCubeVideo:*DISABLED_VortexTwist'
///
/// Frames go to <dir>/TopologyCubeVideo-{1,2} and <dir>/VortexTwist-1.
/// Compose the cube runs with scripts/render_topology_cube.py and render the
/// vortex with scripts/render_mogac_tests.py --skip-build --skip-tests.

#include <openvdb/openvdb.h>
#include <mogac/LevelSetMultiObject.h>
#include <openvdb/tools/LevelSetPlatonic.h>
#include <openvdb/tools/LevelSetSphere.h>

#include "LevelSetMultiObjectFixtures.h"
#include "LevelSetMultiObjectTopology.h"

#include <gtest/gtest.h>

#include <chrono>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <map>
#include <set>
#include <string>

using namespace openvdb;

namespace {

using MLS = lsmo_test::MLS;
using Forces = tools::MultiObjectForces<MLS>;
using Conn = tools::MultiObjectConnectivity;

// The scene of TopologyCubeThroughSpheres (TestLevelSetMultiObject.cc), in
// world units: a cube of side 40 occupying [-0.5, 39.5]^3, advected along +x
// at unit speed through three balls of radius 4 that orbit rigidly about
// the axis parallel to x through their common centroid, one revolution per
// 84 time units. The test samples it with dx = 1 (40 voxels per cube side);
// here dx = 40 / resolution, so the geometry, motion and timing are the same
// and only the grid is finer.
constexpr double kSide = 40.0;
constexpr double kSphereRadius = 4.0;
const Vec3d kSpheres[3] = {Vec3d(48, 10, 12), Vec3d(48, 20, 28), Vec3d(48, 29, 15)};
const double kOmega = 2.0 * math::pi<double>() / 84.0;

Vec3d
orbitCenter()
{
    return (kSpheres[0] + kSpheres[1] + kSpheres[2]) / 3.0;
}

// Rigid rotation about the orbit axis, row-vector convention of
// Mat4d::transform: x' = (x - c) R + c.
math::Mat4d
orbitMotion(double t)
{
    const Vec3d c = orbitCenter();
    const double a = kOmega * t, ca = std::cos(a), sa = std::sin(a);
    math::Mat4d m = math::Mat4d::identity();
    m(1, 1) = ca; m(1, 2) = sa;
    m(2, 1) = -sa; m(2, 2) = ca;
    for (int j = 0; j < 3; ++j) {
        double v = c[j];
        for (int i = 0; i < 3; ++i) v -= c[i] * m(i, j);
        m(3, j) = v;
    }
    return m;
}

int
envInt(const char* name, int fallback)
{
    const char* v = std::getenv(name);
    return (v && *v) ? std::atoi(v) : fallback;
}

double
envDouble(const char* name, double fallback)
{
    const char* v = std::getenv(name);
    return (v && *v) ? std::atof(v) : fallback;
}

// One run to @a tEnd; @a protect makes the cube (label 1) topology-preserving
// under @a rule. Prints the cube's digital topology every @a chunk time units.
void
runCube(bool protect, Conn rule, int resolution, double tEnd)
{
    const double dx = kSide / double(resolution);
    // Initial state from signed distance fields, so the spheres (and the
    // cube's faces) are sub-voxel accurate at any resolution. (The unit test
    // starts from a voxel label mask, which is exact for its cube on the
    // dx = 1 grid but makes the balls blocky.) The cube is [-0.5, 39.5]^3,
    // the union of the test's voxels 0..39.
    std::map<int32_t, FloatGrid::ConstPtr> sdfs;
    sdfs[1] = tools::createLevelSetCube<FloatGrid>(float(kSide),
        Vec3f(float(0.5 * kSide - 0.5)), float(dx));
    for (int s = 0; s < 3; ++s) {
        sdfs[2 + s] = tools::createLevelSetSphere<FloatGrid>(float(kSphereRadius),
            Vec3f(kSpheres[s]), float(dx));
    }
    auto m = MLS::fromSignedGrids(sdfs);
    ASSERT_EQ(m->labelSet(), (std::vector<int32_t>{1, 2, 3, 4}));

    Forces forces;
    forces.setAdvection(Vec3SGrid::create(Vec3s(1.0f, 0.0f, 0.0f)), 1.0f);
    forces.setCurvatureWeight(0.0f);
    lsmo_frames::FrameEvolver<MLS, Forces> lsmo(*m, forces);
    for (int s = 0; s < 3; ++s) {
        lsmo.setKinematicLabel(2 + s, tools::createLevelSetSphere<FloatGrid>(
            float(kSphereRadius), Vec3f(kSpheres[s]), float(dx)), orbitMotion);
    }
    lsmo.setConnectivity(rule);
    if (protect) lsmo.setTopologyPreservingLabels({1});

    // domain for the topology report: the cube's whole path, with margin
    const double margin = 8.0;
    const CoordBBox domain(
        Coord::floor(Vec3d(-margin) / dx),
        Coord::ceil(Vec3d(kSide + tEnd + margin, kSide + margin, kSide + margin) / dx));
    const lsmo_test::DigitalTopology ball{1, 0, 1};
    const std::string log = std::string("TopologyCubeVideo(") + (protect ? "protected" : "control")
        + "/" + lsmo_test::connectivityName(rule) + ", " + std::to_string(resolution) + "^3)";
    std::cout << log << ": dx " << dx << ", " << m->phi()->activeVoxelCount()
              << " band voxels at t 0" << std::endl;

    const double chunk = 2.0;
    double t = 0.0, firstChange = -1.0;
    size_t steps = 0;
    const auto start = std::chrono::steady_clock::now();
    while (t < tEnd - 1e-9) {
        const double t1 = std::min(tEnd, t + chunk);
        steps += lsmo.advect(t, t1);
        t = t1;
        const auto topo = lsmo_test::digitalTopology(*m->labels(), 1, domain,
            lsmo_test::connectivityOf(lsmo));
        if (topo != ball && firstChange < 0.0) firstChange = t;
        const double secs =
            std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        std::cout << log << ": t " << t << " steps " << steps << " cube " << topo << " ("
                  << secs << " s)" << std::endl;
        if (protect) EXPECT_EQ(topo, ball) << "t " << t;
    }
    std::cout << log << ": " << steps << " steps; first topology change "
              << (firstChange < 0.0 ? std::string("none") : "at t " + std::to_string(firstChange))
              << std::endl;
}

} // anonymous namespace

class TestLevelSetMultiObjectVideo: public ::testing::Test
{
protected:
    void SetUp() override { openvdb::initialize(); }
    void TearDown() override { openvdb::uninitialize(); }
};

// Simulations TopologyCubeVideo-1 (protected) and -2 (control), both to
// MOGAC_VIDEO_T_END (default 54). MOGAC_VIDEO_RESOLUTION sets the voxels per
// cube side (default 128; the unit test uses 40).
TEST_F(TestLevelSetMultiObjectVideo, DISABLED_TopologyCubeVideo)
{
    const int resolution = envInt("MOGAC_VIDEO_RESOLUTION", 128);
    const double tEnd = envDouble("MOGAC_VIDEO_T_END", 54.0);
    ASSERT_GT(resolution, 0);
    runCube(true, Conn::FG26_BG6, resolution, tEnd);
    runCube(false, Conn::FG26_BG6, resolution, tEnd);
}

// The VortexEightObjects scene and schedule (lsmo_test::Vortex) with the
// twist on: objects stretched along z are also twisted about it, more the
// farther they reach from the plane z = 0. Simulation VortexTwist-1.
TEST_F(TestLevelSetMultiObjectVideo, DISABLED_VortexTwist)
{
    lsmo_test::Vortex vortex;
    vortex.twist = lsmo_test::Vortex::kTwist;
    MLS::Ptr m = MLS::fromSignedGrids(vortex.inputs(), 3);
    size_t steps = 0;
    double tContact = -1.0;
    const double t = vortex.run(*m, vortex.velocity(), steps, tContact,
        [](double tc, size_t n, const std::set<std::pair<int32_t, int32_t>>& pairs, int) {
            std::cout << "VortexTwist: t " << tc << " steps " << n << " contacts "
                      << pairs.size() << std::endl;
            return true;
        });
    std::cout << "VortexTwist: twist " << vortex.twist << ", t " << t << ", " << steps
              << " steps, >= 4 contact pairs first at t " << tContact << std::endl;
    std::string msg;
    EXPECT_TRUE(m->validate(&msg)) << msg;
}
