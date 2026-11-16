# Copyright Contributors to the OpenVDB Project
# SPDX-License-Identifier: Apache-2.0
"""Render one topology cube simulation with Blender (Cycles) to PNG frames.

Renders the frames of one run of TestLevelSetMultiObjectVideo.DISABLED_TopologyCubeVideo
(<sim>-1: topology-preserving cube, <sim>-2: unconstrained control) as its own
video: the cube semi-transparent (true alpha blending, so the spheres and the
sheets wrapped around them stay visible inside it), the other labels opaque.
The camera is fixed from the bounds of every directory given to --bounds-from,
so separate videos of the two runs frame the scene identically.

  blender -b --python scripts/render_topology_cube_blender.py -- \\
      <frames>/TopologyCubeVideo-1 <out>/protected \\
      --bounds-from <frames>/TopologyCubeVideo-1 <frames>/TopologyCubeVideo-2 \\
      --title "topology-preserving cube (FG26/BG6), 128^3" --frames 230

Writes <out>/frame_%04d.png; encode with e.g.
  cat <out>/frame_*.png | ffmpeg -f image2pipe -framerate 24 -i - \\
      -c:v libx264 -pix_fmt yuv420p -crf 18 -f mp4 - > video.mp4
"""

import argparse
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Vector

CUBE_LABEL = 1
CUBE_ALPHA = 0.06       # facing the camera
CUBE_EDGE_ALPHA = 0.55  # at grazing angles
SPHERE_EMISSION = 0.35
COINCIDENT_TOLERANCE = 1e-5  # world units: vertices this close are the same point
CUBE_COLOR = (0.55, 0.75, 1.00)
BACKGROUND = (0.035, 0.04, 0.055)
TEXT_COLOR = (0.9, 0.9, 0.9)
# saturated linear-RGB colors for the other labels (in label order), so they
# stand out through the translucent cube
LABEL_COLORS = [(0.80, 0.05, 0.04), (0.02, 0.45, 0.60), (0.95, 0.40, 0.02),
                (0.25, 0.60, 0.05), (0.45, 0.10, 0.60)]
VIEW_DIRECTION = (0.9, -1.4, 0.8)
CAMERA_DISTANCE = 3.3  # in bounding-sphere radii
VIEW_ANGLE_DEG = 30.0
SHARP_ANGLE_DEG = 40.0


def load_ply(path):
    """Frame PLY: binary little endian, float xyz, uchar rgb, int label,
    triangles. Returns (points, faces, rgb, label)."""
    with open(path, "rb") as f:
        data = f.read()
    end = data.index(b"end_header\n") + len(b"end_header\n")
    nv = nf = 0
    for line in data[:end].decode().split("\n"):
        if line.startswith("element vertex"):
            nv = int(line.split()[2])
        elif line.startswith("element face"):
            nf = int(line.split()[2])
    vdt = np.dtype([("p", "<f4", 3), ("c", "u1", 3), ("l", "<i4")])
    fdt = np.dtype([("n", "u1"), ("i", "<i4", 3)])
    verts = np.frombuffer(data, vdt, nv, end)
    faces = np.frombuffer(data, fdt, nf, end + nv * vdt.itemsize)
    return verts["p"].astype(np.float64), faces["i"], verts["c"], verts["l"]


def load_sim(sim_dir):
    files = sorted(f for f in os.listdir(sim_dir) if f.startswith("frame_") and f.endswith(".ply"))
    times = {}
    with open(os.path.join(sim_dir, "frames.txt")) as f:
        for line in f:
            parts = line.split()
            if len(parts) == 2:
                times[int(parts[0])] = float(parts[1])
    return files, [times[int(f[len("frame_"):-len(".ply")])] for f in files]


def scene_bounds(dirs):
    lo, hi = np.full(3, np.inf), np.full(3, -np.inf)
    for d in dirs:
        files, _ = load_sim(d)
        for f in files[:: max(1, len(files) // 40)] + [files[-1]]:
            p = load_ply(os.path.join(d, f))[0]
            if len(p):
                lo, hi = np.minimum(lo, p.min(0)), np.maximum(hi, p.max(0))
    return lo, hi


def material(name, rgb, alpha):
    """Opaque (alpha 1, with a little emission so the color survives the
    translucent layers in front of it) or translucent: alpha @a alpha where
    the surface faces the camera, rising towards CUBE_EDGE_ALPHA at grazing
    angles, so stacked sheets read as outlines rather than a white haze."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (*rgb, 1.0)
    bsdf.inputs["Roughness"].default_value = 0.35
    if alpha >= 1.0:
        bsdf.inputs["Emission Color"].default_value = (*rgb, 1.0)
        bsdf.inputs["Emission Strength"].default_value = SPHERE_EMISSION
        return mat
    weight = nodes.new("ShaderNodeLayerWeight")
    weight.inputs["Blend"].default_value = 0.5
    ramp = nodes.new("ShaderNodeMapRange")
    ramp.inputs["To Min"].default_value = alpha
    ramp.inputs["To Max"].default_value = CUBE_EDGE_ALPHA
    links.new(weight.outputs["Facing"], ramp.inputs["Value"])
    links.new(ramp.outputs["Result"], bsdf.inputs["Alpha"])  # Cycles: true alpha blending
    return mat


def setup_scene(args, lo, hi):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    prefs.compute_device_type = args.device
    prefs.get_devices()
    for d in prefs.devices:
        d.use = d.type == args.device
    scene.cycles.device = "GPU" if args.device != "NONE" else "CPU"
    scene.cycles.samples = args.samples
    scene.cycles.use_denoising = True
    scene.cycles.transparent_max_bounces = 32
    scene.cycles.max_bounces = 12
    scene.render.resolution_x, scene.render.resolution_y = args.width, args.height
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"

    world = bpy.data.worlds.new("world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (*BACKGROUND, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 1.0
    scene.world = world

    center = Vector(0.5 * (lo + hi))
    radius = 0.5 * float(np.linalg.norm(hi - lo))
    direction = Vector(VIEW_DIRECTION).normalized()

    cam_data = bpy.data.cameras.new("camera")
    cam_data.sensor_fit = "VERTICAL"
    cam_data.angle_y = math.radians(VIEW_ANGLE_DEG)
    cam = bpy.data.objects.new("camera", cam_data)
    cam.location = center + direction * radius * CAMERA_DISTANCE
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()
    scene.collection.objects.link(cam)
    scene.camera = cam

    # key light from above and behind the camera, soft fill from the side
    for name, energy, rot, size in (("key", 3.0, (math.radians(35), 0, math.radians(30)), 8.0),
                                    ("fill", 1.0, (math.radians(70), 0, math.radians(-110)), 20.0)):
        light = bpy.data.lights.new(name, "SUN")
        light.energy = energy
        light.angle = math.radians(size)
        obj = bpy.data.objects.new(name, light)
        obj.rotation_euler = rot
        scene.collection.objects.link(obj)

    # floor that only catches shadows
    bpy.ops.mesh.primitive_plane_add(size=radius * 12, location=(center.x, center.y, lo[2] - 0.5))
    floor = bpy.context.active_object
    floor.is_shadow_catcher = True
    scene.render.film_transparent = False

    # title and time, parented to the camera in its upper-left corner
    curve = bpy.data.curves.new("title", "FONT")
    curve.size = 0.022
    curve.align_x, curve.align_y = "LEFT", "TOP"
    text = bpy.data.objects.new("title", curve)
    text.parent = cam
    half_h = math.tan(cam_data.angle_y / 2.0)
    half_w = half_h * args.width / args.height
    text.location = (-half_w * 0.97, half_h * 0.95, -1.0)
    tmat = bpy.data.materials.new("text")
    tmat.use_nodes = True
    nodes = tmat.node_tree.nodes
    nodes.remove(nodes["Principled BSDF"])
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = (*TEXT_COLOR, 1.0)
    tmat.node_tree.links.new(emit.outputs["Emission"], nodes["Material Output"].inputs["Surface"])
    curve.materials.append(tmat)
    text.visible_shadow = False
    scene.collection.objects.link(text)
    return scene, curve


def build_meshes(scene, path, materials, old):
    for obj in old:
        mesh = obj.data
        bpy.data.objects.remove(obj)
        bpy.data.meshes.remove(mesh)
    p, f, rgb, lab = load_ply(path)
    # The mesher writes an interface between two labels once per label, as
    # coincident surfaces. Drop the cube's copy where it lies on another
    # label: a ray continuing through the translucent cube from that point
    # can miss the coincident opaque surface, so the spheres would show holes.
    key = np.round(p / COINCIDENT_TOLERANCE).astype(np.int64)
    key = (key[:, 0] * 73856093) ^ (key[:, 1] * 19349663) ^ (key[:, 2] * 83492791)
    onOther = np.isin(key, key[lab != CUBE_LABEL]) & (lab == CUBE_LABEL)
    f = f[~onOther[f].all(axis=1)]
    objs = []
    for label in np.unique(lab):
        sel = lab == label
        vid = np.nonzero(sel)[0]
        fsel = sel[f[:, 0]]
        if not fsel.any():
            continue
        remap = -np.ones(len(p), np.int64)
        remap[vid] = np.arange(len(vid))
        ff = remap[f[fsel]]
        mesh = bpy.data.meshes.new(f"label{label}")
        mesh.from_pydata(p[vid].tolist(), [], ff.tolist())
        mesh.shade_smooth()
        mesh.set_sharp_from_angle(angle=math.radians(SHARP_ANGLE_DEG))
        if label not in materials:
            if label == CUBE_LABEL:
                materials[label] = material("cube", CUBE_COLOR, CUBE_ALPHA)
            else:
                c = LABEL_COLORS[(int(label) - CUBE_LABEL - 1) % len(LABEL_COLORS)]
                materials[label] = material(f"label{label}", c, 1.0)
        mesh.materials.append(materials[label])
        obj = bpy.data.objects.new(f"label{label}", mesh)
        scene.collection.objects.link(obj)
        objs.append(obj)
    return objs


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sim", help="simulation frame directory (e.g. <frames>/TopologyCubeVideo-1)")
    ap.add_argument("out", help="directory for the PNG frames")
    ap.add_argument("--bounds-from", nargs="+", default=None,
                    help="directories whose frames fix the camera (default: sim)")
    ap.add_argument("--title", default="")
    ap.add_argument("--frames", type=int, default=230,
                    help="video frames, evenly spaced in simulated time")
    ap.add_argument("--start", type=int, default=0, help="first video frame to render")
    ap.add_argument("--end", type=int, default=-1, help="last video frame (inclusive)")
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--device", default="OPTIX", choices=["OPTIX", "CUDA", "HIP", "METAL", "NONE"])
    args = ap.parse_args(argv)

    os.makedirs(args.out, exist_ok=True)
    files, times = load_sim(args.sim)
    lo, hi = scene_bounds(args.bounds_from or [args.sim])
    scene, title = setup_scene(args, lo, hi)
    sample = np.linspace(times[0], times[-1], args.frames)
    end = args.frames - 1 if args.end < 0 else min(args.end, args.frames - 1)
    materials, objs, loaded = {}, [], None
    for k in range(args.start, end + 1):
        t = float(sample[k])
        idx = max(0, min(int(np.searchsorted(times, t + 1e-9) - 1), len(files) - 1))
        if idx != loaded:
            objs = build_meshes(scene, os.path.join(args.sim, files[idx]), materials, objs)
            loaded = idx
        title.body = f"{args.title}\nt = {t:.1f}" if args.title else f"t = {t:.1f}"
        scene.render.filepath = os.path.join(args.out, f"frame_{k:04d}.png")
        bpy.ops.render.render(write_still=True)
        print(f"[blender] frame {k}/{end} t {t:.2f} <- {files[idx]}", flush=True)


if __name__ == "__main__":
    main()
