#!/usr/bin/env python3
# Copyright Contributors to the OpenVDB Project
# SPDX-License-Identifier: Apache-2.0
"""Render the side-by-side topology cube video (docs/media/mogac_topology_cube_*).

Composes the two simulations of TestLevelSetMultiObjectVideo.DISABLED_TopologyCubeVideo
(<sim>-1: topology-preserving cube, <sim>-2: unconstrained control) into one
MP4, with the cube translucent so the spheres stay visible inside it, and
optionally a GIF. Produce the frames first, e.g. at 128 voxels per cube side:

  OPENVDB_MOGAC_FRAME_DIR=<frames> MOGAC_VIDEO_RESOLUTION=128 \\
      build/tests/mogac_test --gtest_also_run_disabled_tests \\
      --gtest_filter='*DISABLED_TopologyCubeVideo*'
  scripts/render_topology_cube.py <frames> docs/media/mogac_topology_cube_t54.mp4 \\
      --gif docs/media/mogac_topology_cube_t54.gif --subtitle "128^3" --frames 230

Requires numpy, pyvista and ffmpeg (see render_mogac_tests.py).
"""

import argparse
import importlib.util
import os
import shutil
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("render_mogac_tests",
                                              os.path.join(HERE, "render_mogac_tests.py"))
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

WINDOW_SIZE = (1600, 700)
BACKGROUND = (0.93, 0.93, 0.95)
BOX_COLOR = (0.7, 0.7, 0.75)
VIEW_DIRECTION = (0.9, -1.4, 0.8)
CAMERA_DISTANCE = 3.3  # in bounding-sphere radii
CUBE_LABEL, CUBE_OPACITY = 1, 0.35
FPS = 24
GIF_FPS, GIF_WIDTH, GIF_COLORS = 12, 900, 96


def load_sim(sim_dir):
    files = sorted(f for f in os.listdir(sim_dir) if f.startswith("frame_") and f.endswith(".ply"))
    times = r.read_times(sim_dir)
    return files, [times[r.frame_number(f)] for f in files]


def render(frame_root, sim, out, subtitle, nframes=0):
    import pyvista as pv
    titles = ["topology-preserving cube (FG26/BG6)", "unconstrained cube"]
    if subtitle:
        titles = [f"{t}, {subtitle}" for t in titles]
    data = []
    for k in (1, 2):
        d = os.path.join(frame_root, f"{sim}-{k}")
        data.append((d,) + load_sim(d))

    # fixed camera from the bounds of a sample of frames of both runs
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for d, files, _ in data:
        for f in files[:: max(1, len(files) // 40)] + [files[-1]]:
            p = r.load_ply(os.path.join(d, f))[0]
            if len(p):
                lo, hi = np.minimum(lo, p.min(0)), np.maximum(hi, p.max(0))
    center, radius = 0.5 * (lo + hi), 0.5 * np.linalg.norm(hi - lo)
    direction = np.asarray(VIEW_DIRECTION) / np.linalg.norm(VIEW_DIRECTION)

    pl = pv.Plotter(off_screen=True, shape=(1, 2), window_size=WINDOW_SIZE, border=False)
    for k in range(2):
        pl.subplot(0, k)
        pl.set_background(BACKGROUND)
        pl.add_mesh(pv.Box(bounds=(lo[0], hi[0], lo[1], hi[1], lo[2], hi[2])), style="wireframe",
                    color=BOX_COLOR, line_width=1)
    actors, texts = [[], []], [None, None]
    video = None
    # one video frame per step of the protected run, or nframes evenly in time
    sample = data[0][2]
    if nframes > 0:
        sample = list(np.linspace(sample[0], sample[-1], nframes))
    for t in sample:
        for k, (d, files, times) in enumerate(data):
            # the frame of this run at time t (the runs take different steps)
            idx = max(0, min(int(np.searchsorted(times, t + 1e-9) - 1), len(files) - 1))
            p, f, rgb, lab = r.load_ply(os.path.join(d, files[idx]))
            pl.subplot(0, k)
            for a in actors[k]:
                pl.remove_actor(a, render=False)
            actors[k] = []
            for label in np.unique(lab):
                sel = lab == label
                vid = np.nonzero(sel)[0]
                fsel = sel[f[:, 0]]
                if not fsel.any():
                    continue
                remap = -np.ones(len(p), np.int64)
                remap[vid] = np.arange(len(vid))
                ff = remap[f[fsel]]
                cells = np.hstack([np.full((len(ff), 1), 3), ff]).ravel()
                mesh = pv.PolyData(p[vid], cells)
                actors[k].append(pl.add_mesh(
                    mesh, color=tuple(rgb[vid[0]] / 255.0), smooth_shading=True, specular=0.3,
                    opacity=CUBE_OPACITY if label == CUBE_LABEL else 1.0))
            if texts[k] is not None:
                pl.remove_actor(texts[k], render=False)
            ended = " (stopped: topology changed)" if k == 1 and t > times[-1] + 1e-6 else ""
            texts[k] = pl.add_text(f"{titles[k]}\nt = {min(t, times[-1]) if ended else t:.1f}{ended}",
                                   position="upper_left", font_size=11, color="black")
            pl.camera.focal_point = center
            pl.camera.position = center + direction * radius * CAMERA_DISTANCE
            pl.camera.up = (0, 0, 1)
            pl.camera.view_angle = 30
        img = pl.screenshot(return_img=True)
        h, w = img.shape[0] // 2 * 2, img.shape[1] // 2 * 2
        if video is None:
            video = r.VideoWriter(out, (w, h), FPS)
        video.write(np.ascontiguousarray(img[:h, :w, :3]))
    pl.close()
    video.close()
    print(f"[cube] {len(sample)} frames -> {out}", flush=True)


def make_gif(mp4, gif):
    ffmpeg = shutil.which("ffmpeg") or "/snap/bin/ffmpeg"
    # through pipes: a snap-packaged ffmpeg cannot open files outside $HOME
    with open(mp4, "rb") as src, open(gif, "wb") as dst:
        subprocess.run([ffmpeg, "-loglevel", "error", "-f", "mp4", "-i", "-", "-vf",
                        f"fps={GIF_FPS},scale={GIF_WIDTH}:-2:flags=lanczos,split[a][b];"
                        f"[a]palettegen=max_colors={GIF_COLORS}[p];"
                        "[b][p]paletteuse=dither=bayer:bayer_scale=4", "-f", "gif", "-"],
                       stdin=src, stdout=dst, check=True)
    print(f"[cube] {gif}", flush=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter,
                                 epilog=__doc__.split("\n", 2)[2])
    ap.add_argument("frames", help="frame root (OPENVDB_MOGAC_FRAME_DIR of the run)")
    ap.add_argument("mp4", help="output video")
    ap.add_argument("--gif", help="also write this GIF")
    ap.add_argument("--sim", default="TopologyCubeVideo",
                    help="simulation name without the -1/-2 suffix")
    ap.add_argument("--subtitle", default="", help="appended to both panel titles")
    ap.add_argument("--frames", dest="nframes", type=int, default=0,
                    help="video frames, evenly spaced in time (default: one per step); "
                         "finer grids take more steps, so this keeps the pacing fixed")
    args = ap.parse_args()
    r.ensure_pyvista(os.path.abspath(args.frames))
    render(args.frames, args.sim, os.path.abspath(args.mp4), args.subtitle, args.nframes)
    if args.gif:
        make_gif(os.path.abspath(args.mp4), os.path.abspath(args.gif))


if __name__ == "__main__":
    sys.exit(main())
