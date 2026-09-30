"""
Air Cricket player builder.

Builds two rigged, low-poly characters in Blender and exports them as glTF:
  - batsman.glb : batting kit, pads, gloves, helmet, bat, with batting animations
  - fielder.glb : fielding kit and cap, with fielding and bowling animations

Run headless:  python3 tools/players.py            (needs `pip install bpy`)
Preview only:  python3 tools/players.py preview

Axes (Blender): character faces -Y, its left (.L) is +X, up is +Z.
For the batsman the bowler is at +X (left shoulder toward the bowler, like a
right-hander), the off side is -Y and the stumps are behind at -X.
"""
import math
import os
import sys

import bpy  # noqa: E402  (must come before addon_utils)
import addon_utils
import bmesh
from mathutils import Euler, Matrix, Vector

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "build")
PREVIEW = os.path.join(HERE, "preview")
FPS = 30

# --------------------------------------------------------------------------
# scene helpers
# --------------------------------------------------------------------------

def reset():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    _mats.clear()
    sc = bpy.context.scene
    sc.render.fps = FPS
    for a in list(bpy.data.actions):
        bpy.data.actions.remove(a)


def hexcol(h):
    h = h.lstrip("#")
    srgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in srgb]
    return (*lin, 1.0)


_mats = {}


def mat(name, color, rough=0.7, metal=0.0):
    key = name
    if key in _mats:
        return _mats[key]
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes.get("Principled BSDF")
    b.inputs["Base Color"].default_value = hexcol(color)
    b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metal
    _mats[key] = m
    return m


def _finish(ob, material, bone, smooth=True):
    ob.data.materials.append(material)
    vg = ob.vertex_groups.new(name=bone)
    vg.add(list(range(len(ob.data.vertices))), 1.0, "REPLACE")
    if smooth:
        for p in ob.data.polygons:
            p.use_smooth = True
    return ob


def ellipsoid(center, radii, material, bone, seg=16, rings=10, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=rings, radius=1, location=center, rotation=rot)
    ob = bpy.context.active_object
    ob.scale = radii
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    return _finish(ob, material, bone)


def limb(p0, p1, r0, r1, material, bone, overlap=0.12, seg=14):
    """Tapered capsule-like ellipsoid from p0 to p1."""
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    L = d.length
    bpy.ops.mesh.primitive_uv_sphere_add(segments=seg, ring_count=10, radius=1)
    ob = bpy.context.active_object
    me = ob.data
    # taper: scale ring radius by height
    for v in me.vertices:
        t = (v.co.z + 1) / 2  # 0 bottom .. 1 top
        r = r0 + (r1 - r0) * t
        v.co.x *= r
        v.co.y *= r
        v.co.z *= L / 2 * (1 + overlap)
    q = Vector((0, 0, 1)).rotation_difference(d.normalized())
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = q
    ob.location = (p0 + p1) / 2
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    # the sphere was built bottom(-z)=p0? rotation maps +z to d, so top(t=1) is p1: r1 at p1
    return _finish(ob, material, bone)


def rbox(center, size, material, bone, bevel=0.02, rot=(0, 0, 0)):
    bpy.ops.mesh.primitive_cube_add(size=1, location=center, rotation=rot)
    ob = bpy.context.active_object
    ob.scale = size
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    mod = ob.modifiers.new("bev", "BEVEL")
    mod.width = bevel
    mod.segments = 3
    bpy.ops.object.modifier_apply(modifier=mod.name)
    return _finish(ob, material, bone)


def cyl(p0, p1, r, material, bone, verts=10):
    p0, p1 = Vector(p0), Vector(p1)
    d = p1 - p0
    bpy.ops.mesh.primitive_cylinder_add(vertices=verts, radius=r, depth=d.length, location=(p0 + p1) / 2)
    ob = bpy.context.active_object
    ob.rotation_mode = "QUATERNION"
    ob.rotation_quaternion = Vector((0, 0, 1)).rotation_difference(d.normalized())
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    return _finish(ob, material, bone)


def cut_below(ob, z):
    """Delete vertices of a mesh object below world height z (for helmet / cap shells)."""
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    mw = ob.matrix_world
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if (mw @ v.co).z < z], context="VERTS")
    bm.to_mesh(ob.data)
    bm.free()
    return ob


def loft(sections, n, mat_for_z, weights_for_z, name="loft"):
    """Smooth tube through elliptical sections [(z, rx, ry, yoff)], capped at both ends.
    mat_for_z(z) -> material, weights_for_z(z) -> {bone: weight}."""
    bm = bmesh.new()
    rings = []
    for z, rx, ry, yo in sections:
        ring = []
        for i in range(n):
            a = 2 * math.pi * i / n
            ring.append(bm.verts.new((math.cos(a) * rx, math.sin(a) * ry + yo, z)))
        rings.append(ring)
    faces = []
    for r0, r1 in zip(rings, rings[1:]):
        for i in range(n):
            j = (i + 1) % n
            faces.append(bm.faces.new((r0[i], r0[j], r1[j], r1[i])))
    for ring, (z, rx, ry, yo), flip in ((rings[0], sections[0], True), (rings[-1], sections[-1], False)):
        c = bm.verts.new((0, yo, z))
        for i in range(n):
            j = (i + 1) % n
            f = (ring[j], ring[i], c) if flip else (ring[i], ring[j], c)
            faces.append(bm.faces.new(f))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    mats = []
    for p in me.polygons:
        m = mat_for_z(p.center.z)
        if m.name not in [x.name for x in mats]:
            mats.append(m)
            me.materials.append(m)
        p.material_index = [x.name for x in mats].index(m.name)
        p.use_smooth = True
    groups = {}
    for v in me.vertices:
        for bone, w in weights_for_z(v.co.z).items():
            if w <= 0:
                continue
            if bone not in groups:
                groups[bone] = ob.vertex_groups.new(name=bone)
            groups[bone].add([v.index], w, "REPLACE")
    return ob


def blend(z, z0, z1, a, b):
    t = min(1.0, max(0.0, (z - z0) / (z1 - z0)))
    t = t * t * (3 - 2 * t)
    return {a: 1 - t, b: t}


# --------------------------------------------------------------------------
# skeleton
# --------------------------------------------------------------------------

J = {  # joint positions (Blender coords)
    "root": (0, 0, 0),
    "pelvis": (0, 0, 0.93),
    "spine": (0, 0, 1.05),
    "chest": (0, 0, 1.25),
    "neck": (0, 0, 1.47),
    "head": (0, 0, 1.57),
    "head_top": (0, 0, 1.82),
}
for s, x in (("L", 1), ("R", -1)):
    J["shoulder." + s] = (0.2 * x, 0.0, 1.43)
    J["elbow." + s] = (0.21 * x, 0.025, 1.17)
    J["wrist." + s] = (0.21 * x, -0.01, 0.93)
    J["fingers." + s] = (0.21 * x, -0.02, 0.84)
    J["hip." + s] = (0.1 * x, 0.0, 0.93)
    J["knee." + s] = (0.1 * x, -0.025, 0.51)
    J["ankle." + s] = (0.1 * x, 0.0, 0.09)
    J["toe." + s] = (0.1 * x, -0.15, 0.03)

BAT_TOP = Vector((-0.21, -0.03, 0.9))


def build_armature(name, with_bat):
    arm = bpy.data.armatures.new(name + "_rig")
    ob = bpy.data.objects.new(name, arm)
    bpy.context.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.edit_bones

    def bone(n, h, t, parent=None, connect=False):
        b = eb.new(n)
        b.head = J[h] if isinstance(h, str) else h
        b.tail = J[t] if isinstance(t, str) else t
        b.roll = 0
        if parent:
            b.parent = eb[parent]
            b.use_connect = connect
        return b

    bone("root", "root", (0, 0.0, 0.15))
    bone("hips", "pelvis", "spine", "root")
    bone("spine", "spine", "chest", "hips", True)
    bone("chest", "chest", "neck", "spine", True)
    bone("neck", "neck", "head", "chest", True)
    bone("head", "head", "head_top", "neck", True)
    for s in ("L", "R"):
        bone("upper_arm." + s, "shoulder." + s, "elbow." + s, "chest")
        bone("forearm." + s, "elbow." + s, "wrist." + s, "upper_arm." + s, True)
        bone("hand." + s, "wrist." + s, "fingers." + s, "forearm." + s, True)
        bone("thigh." + s, "hip." + s, "knee." + s, "hips")
        bone("shin." + s, "knee." + s, "ankle." + s, "thigh." + s, True)
        bone("foot." + s, "ankle." + s, "toe." + s, "shin." + s, True)
    if with_bat:
        bone("bat", tuple(BAT_TOP), tuple(BAT_TOP - Vector((0, 0, 0.86))), "root")
    bpy.ops.object.mode_set(mode="OBJECT")
    for pb in ob.pose.bones:
        pb.rotation_mode = "XYZ"
    return ob


# --------------------------------------------------------------------------
# bodies
# --------------------------------------------------------------------------

def leg_pads(s, color="#f3f1ea", thigh_flap=True):
    pad = mat("pad" + color, color, 0.85)
    kx = Vector(J["knee." + s]).x
    out = [rbox((kx, -0.045, 0.3), (0.15, 0.085, 0.44), pad, "shin." + s, bevel=0.035)]
    for z in (0.16, 0.27, 0.38):  # vertical rolls
        out.append(cyl((kx - 0.045, -0.092, z - 0.1), (kx - 0.045, -0.092, z + 0.1), 0.012, pad, "shin." + s, verts=8))
        out.append(cyl((kx + 0.045, -0.092, z - 0.1), (kx + 0.045, -0.092, z + 0.1), 0.012, pad, "shin." + s, verts=8))
    out.append(ellipsoid((kx, -0.07, 0.56), (0.085, 0.055, 0.075), pad, "shin." + s))  # knee roll
    if thigh_flap:
        out.append(rbox((kx, -0.03, 0.66), (0.13, 0.06, 0.1), pad, "thigh." + s, bevel=0.025))
    return out


def keeper_gear_parts():
    """Wicket-keeping pads and big gauntlets, skinned to the fielder rig and shown only on the keeper."""
    parts = []
    glove = mat("keeper_glove", "#e8dcc2", 0.75)
    web = mat("keeper_web", "#c9b48a", 0.8)
    for s in ("L", "R"):
        parts += leg_pads(s, "#f1efe6", thigh_flap=False)
        w = Vector(J["wrist." + s])
        parts.append(limb(w + Vector((0, 0, 0.05)), w + Vector((0, 0, -0.01)), 0.052, 0.058, glove, "hand." + s, overlap=0.0))  # cuff
        parts.append(ellipsoid(w + Vector((0, -0.012, -0.075)), (0.068, 0.058, 0.092), glove, "hand." + s))              # mitt
        parts.append(ellipsoid(w + Vector((0, -0.052, -0.085)), (0.05, 0.02, 0.07), web, "hand." + s, seg=12, rings=8))  # palm
    return parts


def build_body(kind):
    """kind: 'batsman' or 'fielder'. Returns list of mesh objects (weighted by bone name)."""
    bat = kind == "batsman"
    k = kind + "_"
    skin = mat("skin", "#a06d4a", 0.6)
    shirt = mat(k + "shirt", "#f0a431" if bat else "#3462d6", 0.75)
    trousers = mat(k + "trousers", "#1c2d59" if bat else "#16244d", 0.8)
    shoe = mat("shoe", "#ecebe6", 0.6)
    trim = mat(k + "trim", "#1c2d59" if bat else "#f0c040", 0.7)
    parts = []
    P = lambda k: Vector(J[k])

    # torso: one lofted shape, trousers below the belt, shirt above
    torso_sections = [
        (0.84, 0.13, 0.09, 0.0), (0.9, 0.162, 0.104, 0.0), (0.97, 0.168, 0.106, 0.0),
        (1.0, 0.162, 0.103, 0.0), (1.035, 0.158, 0.102, 0.0), (1.09, 0.152, 0.1, 0.0),
        (1.18, 0.164, 0.106, -0.004), (1.28, 0.183, 0.114, -0.008), (1.37, 0.19, 0.114, -0.004),
        (1.43, 0.172, 0.1, 0.004), (1.47, 0.12, 0.08, 0.008), (1.5, 0.07, 0.062, 0.008),
    ]

    def torso_mat(z):
        return trousers if z < 1.0 else trim if z < 1.035 else shirt

    def torso_w(z):
        if z < 1.02:
            return {"hips": 1.0}
        if z < 1.14:
            return blend(z, 1.02, 1.14, "hips", "spine")
        if z < 1.24:
            return {"spine": 1.0}
        if z < 1.34:
            return blend(z, 1.24, 1.34, "spine", "chest")
        if z < 1.48:
            return {"chest": 1.0}
        return blend(z, 1.48, 1.52, "chest", "neck")

    parts.append(loft(torso_sections, 24, torso_mat, torso_w, kind + "_torso"))
    # neck + head
    parts.append(limb((0, 0.004, 1.46), (0, 0.0, 1.6), 0.056, 0.05, skin, "neck"))
    parts.append(ellipsoid((0, -0.004, 1.685), (0.09, 0.1, 0.117), skin, "head", seg=20, rings=14))
    parts.append(ellipsoid((0, -0.098, 1.66), (0.018, 0.02, 0.028), skin, "head", seg=8, rings=6))  # nose
    for x in (0.089, -0.089):
        parts.append(ellipsoid((x, 0.0, 1.68), (0.014, 0.024, 0.03), skin, "head", seg=8, rings=6))  # ears

    for s, sx in (("L", 1), ("R", -1)):
        parts.append(ellipsoid(P("shoulder." + s) + Vector((-0.01 * sx, 0, -0.02)), (0.066, 0.064, 0.062), shirt, "chest"))
        parts.append(limb(P("shoulder." + s), P("elbow." + s), 0.058, 0.047, shirt, "upper_arm." + s))
        parts.append(ellipsoid(P("elbow." + s), (0.046, 0.046, 0.046), shirt, "forearm." + s, seg=10, rings=8))
        parts.append(limb(P("elbow." + s), P("wrist." + s), 0.044, 0.036, shirt, "forearm." + s))
        if bat:
            parts.append(limb(P("wrist." + s) + Vector((0, 0, 0.03)), P("wrist." + s) + Vector((0, 0, -0.02)), 0.05, 0.05, trim, "hand." + s, overlap=0.0))
            parts.append(ellipsoid(P("wrist." + s) + Vector((0, -0.01, -0.06)), (0.052, 0.046, 0.066), mat("glove", "#f4f2ec", 0.8), "hand." + s))
        else:
            parts.append(limb(P("wrist." + s) + Vector((0, 0, 0.02)), P("wrist." + s), 0.038, 0.035, shirt, "forearm." + s, overlap=0.0))
            parts.append(ellipsoid(P("wrist." + s) + Vector((0, -0.008, -0.055)), (0.037, 0.026, 0.058), skin, "hand." + s))
        # legs
        parts.append(limb(P("hip." + s) + Vector((0, 0, 0.03)), P("knee." + s), 0.086, 0.062, trousers, "thigh." + s))
        parts.append(ellipsoid(P("knee." + s), (0.06, 0.06, 0.06), trousers, "shin." + s, seg=10, rings=8))
        parts.append(limb(P("knee." + s), P("ankle." + s) + Vector((0, 0, 0.02)), 0.058, 0.042, trousers, "shin." + s))
        parts.append(ellipsoid(P("ankle." + s) + Vector((0, -0.05, -0.045)), (0.052, 0.12, 0.045), shoe, "foot." + s))
        parts.append(ellipsoid(P("ankle." + s) + Vector((0, -0.03, -0.075)), (0.055, 0.125, 0.018), mat("sole", "#2a2a2a", 0.9), "foot." + s))
        if bat:
            parts += leg_pads(s)

    if bat:
        helmet = mat("helmet", "#16244a", 0.35)
        grille = mat("grille", "#b7bec6", 0.3, 0.8)
        h = ellipsoid((0, 0.005, 1.7), (0.122, 0.13, 0.125), helmet, "head", seg=24, rings=16)
        cut_below(h, 1.63)
        parts.append(h)
        parts.append(ellipsoid((0, -0.12, 1.745), (0.1, 0.06, 0.012), helmet, "head", seg=16, rings=6))  # peak
        for z in (1.6, 1.635, 1.67, 1.705):
            parts.append(cyl((-0.085, -0.13, z), (0.085, -0.13, z), 0.0055, grille, "head", verts=6))
        for x in (-0.03, 0.03):
            parts.append(cyl((x, -0.132, 1.59), (x, -0.13, 1.72), 0.0055, grille, "head", verts=6))
        for x in (-0.09, 0.09):
            parts.append(cyl((x, -0.12, 1.6), (x * 1.25, -0.02, 1.64), 0.0065, grille, "head", verts=6))
        # bat
        willow = mat("willow", "#e2c38b", 0.55)
        grip = mat("grip", "#1d1d1d", 0.9)
        top = BAT_TOP
        parts.append(cyl(top + Vector((0, 0, 0.02)), top - Vector((0, 0, 0.29)), 0.0175, grip, "bat", verts=10))
        blade = rbox(tuple(top - Vector((0, 0, 0.57))), (0.042, 0.108, 0.56), willow, "bat", bevel=0.012)
        # thicken the back (splice) a little: push vertices on +X face toward the middle top
        for v in blade.data.vertices:
            if v.co.x > top.x + 0.015:
                zt = (v.co.z - (top.z - 0.85)) / 0.56
                v.co.x += 0.018 * math.sin(max(0.0, min(1.0, zt)) * math.pi) * (1 - abs(v.co.y - top.y) / 0.06)
        parts.append(blade)
        parts.append(ellipsoid(tuple(top - Vector((0, 0, 0.3))), (0.022, 0.02, 0.03), willow, "bat", seg=10, rings=6))  # shoulders
    else:
        cap = mat("cap", "#16244d", 0.7)
        c = ellipsoid((0, 0.005, 1.715), (0.1, 0.108, 0.11), cap, "head", seg=20, rings=12)
        cut_below(c, 1.705)
        parts.append(c)
        parts.append(ellipsoid((0, -0.12, 1.71), (0.08, 0.075, 0.01), cap, "head", seg=16, rings=6))
        parts.append(ellipsoid((0, 0.0, 1.805), (0.012, 0.012, 0.008), trim, "head", seg=8, rings=4))
    return parts


def build_character(kind):
    rig = build_armature(kind, kind == "batsman")
    parts = build_body(kind)
    bpy.ops.object.select_all(action="DESELECT")
    for p in parts:
        p.select_set(True)
    bpy.context.view_layer.objects.active = parts[0]
    bpy.ops.object.join()
    body = bpy.context.active_object
    body.name = kind + "_mesh"
    body.parent = rig
    mod = body.modifiers.new("rig", "ARMATURE")
    mod.object = rig
    EXTRAS[kind] = []
    if kind == "fielder":
        gp = keeper_gear_parts()
        bpy.ops.object.select_all(action="DESELECT")
        for p in gp:
            p.select_set(True)
        bpy.context.view_layer.objects.active = gp[0]
        bpy.ops.object.join()
        gear = bpy.context.active_object
        gear.name = "keeper_gear"
        gear.parent = rig
        gm = gear.modifiers.new("rig", "ARMATURE")
        gm.object = rig
        EXTRAS[kind].append(gear)
    return rig, body


EXTRAS = {}


# --------------------------------------------------------------------------
# posing helpers
#   Rotations are given in world terms and converted into each bone's frame:
#   bend  > 0 : tip tilts toward -Y (the chest side)   [about world X]
#   yaw   > 0 : turns counter-clockwise seen from above [about world Z]
#   lean  > 0 : tip tilts toward +X                     [about world Y]
# --------------------------------------------------------------------------

def Rw(bend=0.0, yaw=0.0, lean=0.0):
    return Matrix.Rotation(yaw, 3, "Z") @ Matrix.Rotation(lean, 3, "Y") @ Matrix.Rotation(bend, 3, "X")


def limb_R(fwd=0.0, out=0.0, sx=1):
    """Swing a downward limb forward (toward -Y) by fwd and outward (away from body) by out."""
    return Matrix.Rotation(-out * sx, 3, "Y") @ Matrix.Rotation(-fwd, 3, "X")


_prev_euler = {}


def set_rot(pb, R):
    M = pb.bone.matrix_local.to_3x3()
    L = M.inverted() @ R @ M
    key = (pb.id_data.name, pb.name)
    prev = _prev_euler.get(key)
    e = L.to_euler("XYZ", prev) if prev is not None else L.to_euler("XYZ")
    pb.rotation_euler = e
    _prev_euler[key] = e.copy()


def set_loc(pb, world_off):
    M = pb.bone.matrix_local.to_3x3()
    pb.location = M.inverted() @ Vector(world_off)


def add_empty(name, parent=None):
    e = bpy.data.objects.new(name, None)
    bpy.context.collection.objects.link(e)
    e.empty_display_size = 0.05
    e.rotation_mode = "XYZ"
    if parent:
        e.parent = parent
    return e


def bone_world(rig, bone):
    return rig.matrix_world @ rig.data.bones[bone].matrix_local


def bone_tail_world(rig, bone):
    return rig.matrix_world @ rig.data.bones[bone].tail_local


def key_all(objs_and_paths, frame):
    for ob, path in objs_and_paths:
        ob.keyframe_insert(data_path=path, frame=frame)


# --------------------------------------------------------------------------
# batsman control rig (IK hands on the bat handle, IK feet)
# --------------------------------------------------------------------------

GRIP_TOP = -0.07   # fingertip target of the top hand, below the top of the handle
GRIP_BOT = -0.18


def setup_batsman_controls(rig):
    vl = bpy.context.view_layer
    C = {}
    bat = add_empty("ctl_bat")
    bat.location = BAT_TOP
    C["bat"] = bat
    vl.update()

    def matched(name, bone, pos, parent):
        e = add_empty(name, parent)
        R = bone_world(rig, bone).to_3x3().to_4x4()
        vl.update()
        e.matrix_world = Matrix.Translation(Vector(pos)) @ R
        return e

    C["tgt_bat"] = matched("tgt_bat", "bat", BAT_TOP, bat)
    C["gripL"] = matched("gripL", "hand.L", BAT_TOP + Vector((0, 0, GRIP_TOP)), bat)
    C["gripR"] = matched("gripR", "hand.R", BAT_TOP + Vector((0, 0, GRIP_BOT)), bat)
    for s in ("L", "R"):
        f = matched("foot" + s, "foot." + s, bone_tail_world(rig, "foot." + s), None)
        C["foot" + s] = f
        C["foot" + s + "_rest"] = f.rotation_euler.copy()
        C["knee" + s] = add_empty("knee" + s)
        C["elbow" + s] = add_empty("elbow" + s)
    vl.update()

    pbs = rig.pose.bones
    c = pbs["bat"].constraints.new("COPY_TRANSFORMS")
    c.target = C["tgt_bat"]
    for s in ("L", "R"):
        ik = pbs["hand." + s].constraints.new("IK")
        ik.target = C["grip" + s]
        ik.chain_count = 3
        ik.use_tail = True
        ik.use_rotation = True
        ik.pole_target = C["elbow" + s]
        ik.pole_angle = math.radians(-90)
        ik = pbs["foot." + s].constraints.new("IK")
        ik.target = C["foot" + s]
        ik.chain_count = 3
        ik.use_tail = True
        ik.use_rotation = True
        ik.pole_target = C["knee" + s]
        ik.pole_angle = math.radians(-90)
    return C


BAT_BASE = {
    "bat": ((0.02, -0.25, 0.94), (0.0, 0.3, 0.0)),        # grip-top position, (twist, swing, yaw)
    "footL": ((0.27, -0.17, 0.03), 0.35),                  # toe position, yaw
    "footR": ((-0.2, -0.16, 0.03), 0.05),
    "kneeL": (0.4, -0.9, 0.5), "kneeR": (-0.25, -0.9, 0.5),
    "elbowL": (0.45, -0.25, 1.05), "elbowR": (-0.35, -0.35, 0.95),
    "hips": ((0.0, 0.0, -0.07), (0.0, 0.0, 0.0)),
    "spine": (0.14, 0.0, 0.0), "chest": (0.12, 0.05, 0.0),
    "neck": (0.02, 0.35, 0.0), "head": (0.06, 1.0, 0.08),
}


def P(base=None, **kw):
    d = dict(base or BAT_BASE)
    d.update(kw)
    return d


def apply_batsman_pose(rig, C, pose, frame):
    b = C["bat"]
    b.location = pose["bat"][0]
    b.rotation_euler = pose["bat"][1]
    b.keyframe_insert("location", frame=frame)
    b.keyframe_insert("rotation_euler", frame=frame)
    for s in ("L", "R"):
        f = C["foot" + s]
        loc, yaw = pose["foot" + s]
        f.location = loc
        r = C["foot" + s + "_rest"].copy()
        r.z += yaw
        f.rotation_euler = r
        f.keyframe_insert("location", frame=frame)
        f.keyframe_insert("rotation_euler", frame=frame)
        for k in ("knee", "elbow"):
            C[k + s].location = pose[k + s]
            C[k + s].keyframe_insert("location", frame=frame)
    pbs = rig.pose.bones
    off, rot = pose["hips"]
    set_loc(pbs["hips"], off)
    set_rot(pbs["hips"], Rw(*rot))
    pbs["hips"].keyframe_insert("location", frame=frame)
    pbs["hips"].keyframe_insert("rotation_euler", frame=frame)
    for n in ("spine", "chest", "neck", "head"):
        set_rot(pbs[n], Rw(*pose[n]))
        pbs[n].keyframe_insert("rotation_euler", frame=frame)


# --------------------------------------------------------------------------
# fielder poses (plain FK)
# --------------------------------------------------------------------------

F_BASE = {
    "hips": ((0, 0, 0), (0, 0, 0)), "spine": (0.02, 0, 0), "chest": (0.02, 0, 0), "neck": (0, 0, 0), "head": (0, 0, 0),
    "uaL": (0.05, 0.12), "uaR": (0.05, 0.12), "faL": 0.25, "faR": 0.25, "hL": 0.0, "hR": 0.0,
    "thL": (0.0, 0.03), "thR": (0.0, 0.03), "shL": 0.05, "shR": 0.05, "ftL": 0.0, "ftR": 0.0,
}


def F(base=None, **kw):
    d = dict(base or F_BASE)
    d.update(kw)
    return d


def apply_fielder_pose(rig, pose, frame):
    pbs = rig.pose.bones
    off, rot = pose["hips"]
    set_loc(pbs["hips"], off)
    set_rot(pbs["hips"], Rw(*rot))
    pbs["hips"].keyframe_insert("location", frame=frame)
    pbs["hips"].keyframe_insert("rotation_euler", frame=frame)
    for n in ("spine", "chest", "neck", "head"):
        set_rot(pbs[n], Rw(*pose[n]))
    for s, sx in (("L", 1), ("R", -1)):
        set_rot(pbs["upper_arm." + s], limb_R(*pose["ua" + s], sx=sx))
        set_rot(pbs["forearm." + s], Matrix.Rotation(-pose["fa" + s], 3, "X"))
        set_rot(pbs["hand." + s], Matrix.Rotation(-pose["h" + s], 3, "X"))
        set_rot(pbs["thigh." + s], limb_R(*pose["th" + s], sx=sx))
        set_rot(pbs["shin." + s], Matrix.Rotation(pose["sh" + s], 3, "X"))
        set_rot(pbs["foot." + s], Matrix.Rotation(pose["ft" + s], 3, "X"))
    for pb in pbs:
        if pb.name not in ("root", "hips", "bat"):
            pb.keyframe_insert("rotation_euler", frame=frame)


def mirror_run(p):
    """Swap left/right limbs of a fielder pose (for the second half of a run cycle)."""
    q = dict(p)
    for a, b in (("uaL", "uaR"), ("faL", "faR"), ("thL", "thR"), ("shL", "shR"), ("ftL", "ftR"), ("hL", "hR")):
        q[a], q[b] = p[b], p[a]
    return q


# --------------------------------------------------------------------------
# preview
# --------------------------------------------------------------------------

def setup_preview_scene():
    addon_utils.enable("cycles", default_set=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 12
    sc.render.resolution_x = 480
    sc.render.resolution_y = 480
    world = bpy.data.worlds.new("w")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.02, 0.05, 0.06, 1)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.8
    sc.world = world
    bpy.ops.mesh.primitive_plane_add(size=6)
    g = bpy.context.active_object
    g.data.materials.append(mat("preview_grass", "#3a7e43", 0.9))
    sun = bpy.data.lights.new("sun", "SUN")
    sun.energy = 3.5
    so = bpy.data.objects.new("sun", sun)
    so.rotation_euler = Euler((math.radians(50), math.radians(10), math.radians(-30)))
    sc.collection.objects.link(so)
    cam = bpy.data.cameras.new("cam")
    cam.lens = 50
    co = bpy.data.objects.new("cam", cam)
    sc.collection.objects.link(co)
    sc.camera = co
    return co


def aim(cam, loc, target):
    cam.location = loc
    d = Vector(target) - Vector(loc)
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()


def render(path, cam, loc, target=(0, 0, 0.9)):
    aim(cam, loc, target)
    bpy.context.scene.render.filepath = path
    bpy.ops.render.render(write_still=True)


# --------------------------------------------------------------------------
# clips
# --------------------------------------------------------------------------

CONTACT = 5 / FPS          # every batting shot meets the ball at this time
RELEASE = 0.55             # bowler lets go of the ball at this time in "bowl"

BACKLIFT = P(
    bat=((-0.1, -0.2, 1.24), (0.0, 1.85, 0.0)),
    footL=((0.33, -0.17, 0.05), 0.35),
    spine=(0.12, -0.04, 0.0), chest=(0.1, -0.12, 0.0), neck=(0.02, 0.4, 0.0), head=(0.06, 1.1, 0.08),
    elbowL=(0.5, -0.4, 1.25), elbowR=(-0.4, -0.4, 1.15),
)


def shot(contact, follow, hold=None, extra=None):
    """Standard shot timeline: backlift -> contact at CONTACT -> follow-through -> hold -> stance."""
    keys = [(0.0, BACKLIFT), (CONTACT, contact), (0.45, follow), (0.9, hold or follow), (1.4, BAT_BASE)]
    if extra:
        keys += extra
        keys.sort(key=lambda k: k[0])
    return keys


FRONT = dict(
    footR=((-0.22, -0.15, 0.03), 0.25),
    hips=((0.2, 0.0, -0.14), (0.05, 0.15, 0.12)),
    spine=(0.25, 0.05, 0.05), chest=(0.18, 0.1, 0.0), neck=(0.1, 0.3, 0.0), head=(0.25, 0.8, 0.1),
    kneeL=(0.9, -0.9, 0.5), elbowL=(0.8, -0.2, 1.1), elbowR=(0.0, -0.6, 0.9),
)
THRU = dict(
    footR=((-0.14, -0.2, 0.09), 0.5),
    hips=((0.24, 0.0, -0.1), (0.0, 0.35, 0.1)),
    spine=(0.1, 0.15, 0.0), chest=(0.05, 0.35, 0.0), neck=(0.05, 0.2, 0.0), head=(0.12, 0.55, 0.0),
    elbowL=(0.7, 0.3, 1.7), elbowR=(0.4, -0.5, 1.4),
)
BACKFOOT = dict(
    hips=((-0.08, -0.08, -0.08), (0.02, 0.25, -0.05)),
    spine=(0.08, 0.1, 0.0), chest=(0.02, 0.2, 0.0), neck=(0.0, 0.3, 0.0), head=(0.05, 0.7, 0.0),
    kneeL=(0.5, -0.9, 0.5), kneeR=(-0.3, -1.0, 0.5),
)

BATSMAN_CLIPS = {
    "stance": [(0.0, BAT_BASE), (0.5, P(bat=((0.02, -0.25, 0.97), (0.0, 0.45, 0.0)))), (1.0, BAT_BASE)],
    "backlift": [(0.0, BAT_BASE), (0.35, BACKLIFT), (0.5, BACKLIFT)],
    "straight": shot(
        P(bat=((0.34, -0.3, 0.86), (0.0, -0.12, 0.05)), footL=((0.68, -0.2, 0.03), 0.55), **FRONT),
        P(bat=((0.3, -0.12, 1.4), (0.0, -2.5, 0.1)), footL=((0.68, -0.2, 0.03), 0.55), **THRU),
        P(bat=((0.22, -0.08, 1.45), (0.0, -2.8, 0.1)), footL=((0.68, -0.2, 0.03), 0.55), **THRU)),
    "off": shot(
        P(bat=((0.34, -0.36, 0.86), (0.0, -0.1, -0.35)), footL=((0.62, -0.34, 0.03), 0.15), **FRONT),
        P(bat=((0.22, -0.34, 1.35), (0.0, -2.4, -0.9)), footL=((0.62, -0.34, 0.03), 0.15), **THRU),
        P(bat=((0.16, -0.3, 1.4), (0.0, -2.7, -1.0)), footL=((0.62, -0.34, 0.03), 0.15), **THRU)),
    "leg": shot(
        P(bat=((0.32, -0.22, 0.85), (0.0, -0.15, 0.4)), footL=((0.62, -0.08, 0.03), 0.7), **FRONT),
        P(bat=((0.28, 0.05, 1.15), (0.0, -1.9, 1.3)), footL=((0.62, -0.08, 0.03), 0.7),
          **dict(THRU, hips=((0.2, 0.0, -0.1), (0.0, 0.5, 0.05)), chest=(0.05, 0.6, 0.0), head=(0.12, 0.3, 0.0))),
        None),
    "pull": shot(
        P(bat=((0.12, -0.3, 1.12), (-1.45, 0.0, 0.15)), footL=((0.2, -0.02, 0.03), 1.1), footR=((-0.3, -0.3, 0.03), 0.9),
          elbowL=(0.4, -0.5, 1.3), elbowR=(-0.2, -0.7, 1.1), **BACKFOOT),
        P(bat=((0.1, 0.12, 1.3), (-1.45, 0.0, 2.6)), footL=((0.2, -0.02, 0.03), 1.1), footR=((-0.3, -0.3, 0.06), 1.3),
          elbowL=(0.4, 0.4, 1.4), elbowR=(0.2, -0.5, 1.3),
          **dict(BACKFOOT, hips=((-0.05, -0.05, -0.08), (0.0, 0.7, 0.0)), chest=(0.0, 0.7, 0.0), head=(0.05, 0.2, 0.0))),
        None),
    "cut": shot(
        P(bat=((0.1, -0.4, 1.1), (-1.0, 0.0, 0.3)), footR=((-0.12, -0.42, 0.03), -0.2), footL=((0.26, -0.2, 0.03), 0.2),
          elbowL=(0.4, -0.6, 1.3), elbowR=(-0.3, -0.7, 1.0), **BACKFOOT),
        P(bat=((-0.05, -0.45, 0.95), (-1.0, 0.0, -0.9)), footR=((-0.12, -0.42, 0.03), -0.2), footL=((0.26, -0.2, 0.03), 0.2),
          elbowL=(0.3, -0.8, 1.2), elbowR=(-0.4, -0.7, 1.0),
          **dict(BACKFOOT, chest=(0.05, -0.1, 0.0), head=(0.05, 0.9, 0.0))),
        None),
    "block": shot(
        P(bat=((0.36, -0.25, 0.86), (0.0, 0.12, 0.0)), footL=((0.62, -0.2, 0.03), 0.5),
          **dict(FRONT, head=(0.35, 0.85, 0.12), elbowL=(0.7, -0.2, 1.35))),
        P(bat=((0.36, -0.25, 0.86), (0.0, 0.15, 0.0)), footL=((0.62, -0.2, 0.03), 0.5),
          **dict(FRONT, head=(0.35, 0.85, 0.12), elbowL=(0.7, -0.2, 1.35))),
        None),
    "loft": shot(
        P(bat=((0.3, -0.3, 0.9), (0.0, -0.25, 0.05)), footL=((0.66, -0.2, 0.03), 0.55), **FRONT),
        P(bat=((0.18, -0.05, 1.6), (0.0, -3.0, 0.1)), footL=((0.66, -0.2, 0.03), 0.55),
          **dict(THRU, hips=((0.2, 0.0, -0.04), (-0.05, 0.3, 0.05)), chest=(-0.1, 0.35, 0.0), head=(-0.15, 0.55, 0.0))),
        None),
    "leave": [(0.0, BACKLIFT),
              (0.25, P(bat=((0.0, -0.05, 1.52), (0.0, 1.0, 0.0)), elbowL=(0.4, -0.3, 1.6), elbowR=(-0.3, -0.3, 1.6), head=(0.08, 1.1, 0.1))),
              (0.8, P(bat=((0.0, -0.05, 1.52), (0.0, 1.0, 0.0)), elbowL=(0.4, -0.3, 1.6), elbowR=(-0.3, -0.3, 1.6), head=(0.08, 1.1, 0.1))),
              (1.2, BAT_BASE)],
}

RUN_BAT = dict(
    bat=((-0.12, -0.3, 0.98), (-0.9, 0.0, 0.0)),
    spine=(0.25, 0.0, 0.0), chest=(0.05, 0.0, 0.0), neck=(-0.1, 0.0, 0.0), head=(-0.05, 0.0, 0.0),
    kneeL=(0.1, -1.0, 0.5), kneeR=(-0.1, -1.0, 0.5), elbowL=(0.4, 0.2, 1.0), elbowR=(-0.4, 0.2, 1.0),
)
BATSMAN_CLIPS["run"] = [
    (0.0, P(footL=((0.1, -0.45, 0.03), 0.0), footR=((-0.1, 0.3, 0.22), 0.0), hips=((0, 0, -0.04), (0, 0, 0)), **RUN_BAT)),
    (0.15, P(footL=((0.1, -0.05, 0.03), 0.0), footR=((-0.1, -0.1, 0.33), 0.0), hips=((0, 0, 0.0), (0, 0, 0)), **RUN_BAT)),
    (0.3, P(footL=((0.1, 0.3, 0.22), 0.0), footR=((-0.1, -0.45, 0.03), 0.0), hips=((0, 0, -0.04), (0, 0, 0)), **RUN_BAT)),
    (0.45, P(footL=((0.1, -0.1, 0.33), 0.0), footR=((-0.1, -0.05, 0.03), 0.0), hips=((0, 0, 0.0), (0, 0, 0)), **RUN_BAT)),
    (0.6, P(footL=((0.1, -0.45, 0.03), 0.0), footR=((-0.1, 0.3, 0.22), 0.0), hips=((0, 0, -0.04), (0, 0, 0)), **RUN_BAT)),
]
BACKUP = P(bat=((-0.26, -0.14, 0.92), (0.15, 0.05, 0.0)), footL=((0.11, -0.16, 0.03), 0.1), footR=((-0.11, -0.16, 0.03), -0.1),
           hips=((0, 0, -0.01), (0, 0, 0)), spine=(0.03, 0, 0), chest=(0.02, 0, 0), neck=(0, 0, 0), head=(0.05, 0, 0),
           kneeL=(0.1, -1.0, 0.5), kneeR=(-0.1, -1.0, 0.5), elbowL=(0.3, 0.1, 1.1), elbowR=(-0.4, 0.1, 1.1))
BATSMAN_CLIPS["backup"] = [(0.0, BACKUP), (1.0, P(BACKUP, spine=(0.05, 0.02, 0))), (2.0, BACKUP)]

# ---- fielders / bowler ----
RUN_A = F(hips=((0, 0, -0.03), (0.0, 0.05, 0)), spine=(0.2, 0, 0), chest=(0.05, -0.05, 0), neck=(-0.12, 0, 0), head=(-0.05, 0, 0),
          uaL=(-0.6, 0.12), faL=0.9, uaR=(0.75, 0.12), faR=1.3,
          thL=(0.85, 0.02), shL=0.35, ftL=-0.15, thR=(-0.45, 0.02), shR=1.3, ftR=0.4)
RUN_B = F(RUN_A, hips=((0, 0, 0.02), (0.0, 0.0, 0)),
          uaL=(-0.1, 0.12), faL=1.1, uaR=(0.2, 0.12), faR=1.2,
          thL=(0.2, 0.02), shL=0.5, ftL=0.0, thR=(0.4, 0.02), shR=1.6, ftR=0.2)
READY = F(hips=((0, -0.04, -0.16), (0.3, 0, 0)), spine=(0.25, 0, 0), chest=(0.05, 0, 0), neck=(-0.35, 0, 0), head=(-0.2, 0, 0),
          uaL=(0.55, 0.25), faL=0.7, uaR=(0.55, 0.25), faR=0.7, hL=0.3, hR=0.3,
          thL=(0.75, 0.18), shL=1.1, ftL=-0.3, thR=(0.75, 0.18), shR=1.1, ftR=-0.3)
CATCH_UP = F(hips=((0, 0, -0.05), (-0.05, 0, 0)), spine=(-0.1, 0, 0), chest=(-0.05, 0, 0), neck=(-0.2, 0, 0), head=(-0.3, 0, 0),
             uaL=(2.0, 0.1), faL=0.4, uaR=(2.0, 0.1), faR=0.4, hL=-0.4, hR=-0.4,
             thL=(0.35, 0.08), shL=0.5, thR=(-0.1, 0.08), shR=0.4)
CATCH_IN = F(CATCH_UP, uaL=(0.9, 0.1), faL=1.9, uaR=(0.9, 0.1), faR=1.9, head=(0.1, 0, 0), neck=(0.1, 0, 0), spine=(0.15, 0, 0))
DIVE_1 = F(hips=((0, -0.4, -0.45), (1.1, 0, 0)), spine=(0.2, 0, 0), chest=(0.0, 0, 0), neck=(-0.6, 0, 0), head=(-0.3, 0, 0),
           uaL=(2.8, 0.15), faL=0.1, uaR=(2.8, 0.15), faR=0.1, thL=(-0.1, 0.1), shL=0.3, thR=(-0.3, 0.1), shR=0.2, ftL=0.6, ftR=0.6)
DIVE_2 = F(DIVE_1, hips=((0, -0.9, -0.78), (1.5, 0, 0)), thL=(-0.2, 0.1), thR=(-0.2, 0.1))
PICK_1 = F(hips=((0, -0.1, -0.28), (0.35, 0, 0)), spine=(0.55, 0, 0), chest=(0.2, 0, 0), neck=(-0.4, 0, 0), head=(-0.2, 0, 0),
           uaL=(0.4, 0.3), faL=0.6, uaR=(1.25, 0.05), faR=0.2, hR=0.2,
           thL=(1.0, 0.15), shL=1.4, ftL=-0.3, thR=(0.2, 0.15), shR=1.5, ftR=0.3)
PICK_2 = F(hips=((0, 0, -0.08), (0.05, -0.2, 0)), spine=(0.15, -0.2, 0), chest=(0.05, -0.2, 0), neck=(0, 0.2, 0), head=(0, 0.2, 0),
           uaL=(1.2, 0.2), faL=0.4, uaR=(-0.5, 0.9), faR=1.6,
           thL=(0.35, 0.1), shL=0.4, thR=(-0.2, 0.1), shR=0.3)
THROW_1 = F(PICK_2, uaR=(-0.9, 1.2), faR=1.7, chest=(-0.05, -0.5, 0), spine=(0.0, -0.3, 0), uaL=(1.5, 0.1), faL=0.2,
            neck=(0, 0.4, 0), head=(0, 0.35, 0))
THROW_2 = F(THROW_1, uaR=(2.7, 0.3), faR=0.3, chest=(0.1, 0.4, 0), spine=(0.2, 0.3, 0), uaL=(0.3, 0.3), faL=1.2,
            neck=(0, -0.2, 0), head=(0, -0.3, 0), thL=(0.6, 0.1), shL=0.2, thR=(-0.5, 0.1), shR=0.6)
THROW_3 = F(THROW_2, uaR=(0.7, -0.3), faR=0.4, spine=(0.45, 0.35, 0), chest=(0.15, 0.3, 0))

BOWL_GATHER = F(hips=((0, 0, 0.1), (-0.05, -0.2, 0)), spine=(-0.1, -0.2, 0), chest=(-0.1, -0.3, 0), neck=(0.1, 0.3, 0), head=(0, 0.2, 0),
                uaL=(2.4, 0.1), faL=0.3, uaR=(-0.4, 0.2), faR=0.4,
                thL=(0.95, 0.05), shL=1.3, ftL=-0.2, thR=(-0.3, 0.05), shR=0.6, ftR=0.4)
BOWL_COIL = F(BOWL_GATHER, hips=((0, 0.05, 0.0), (-0.1, -0.5, 0)), spine=(-0.25, -0.3, 0), chest=(-0.1, -0.4, 0), neck=(0.1, 0.5, 0), head=(0, 0.3, 0),
              uaL=(2.9, 0.05), faL=0.1, uaR=(-1.2, 0.1), faR=0.2, thL=(0.75, 0.05), shL=0.25, ftL=-0.1, thR=(-0.2, 0.05), shR=0.3)
BOWL_RELEASE = F(hips=((0, -0.1, -0.03), (0.1, 0.2, 0)), spine=(0.2, 0.2, 0), chest=(0.05, 0.3, 0), neck=(0, -0.2, 0), head=(0.05, -0.3, 0),
                 uaL=(0.2, 0.3), faL=1.0, uaR=(3.25, 0.05), faR=0.0,
                 thL=(0.5, 0.05), shL=0.0, ftL=0.1, thR=(-0.6, 0.05), shR=0.5, ftR=0.5)
BOWL_FOLLOW = F(hips=((0, -0.3, -0.12), (0.4, 0.4, 0)), spine=(0.5, 0.3, 0), chest=(0.2, 0.3, 0), neck=(-0.3, -0.3, 0), head=(-0.2, -0.3, 0),
                uaL=(-0.4, 0.3), faL=0.8, uaR=(4.6, -0.5), faR=0.2,
                thL=(0.3, 0.05), shL=0.3, thR=(0.7, 0.05), shR=0.9, ftR=0.2)

# wicket-keeper: deep squat behind the stumps, then rise to take the ball in front of the chest
KEEP = F(hips=((0, 0.2, -0.4), (0.4, 0, 0)), spine=(0.25, 0, 0), chest=(0.1, 0, 0), neck=(-0.45, 0, 0), head=(-0.3, 0, 0),
         uaL=(1.2, 0.12), faL=0.45, uaR=(1.2, 0.12), faR=0.45, hL=0.15, hR=0.15,
         thL=(1.75, 0.32), shL=1.9, ftL=-0.5, thR=(1.75, 0.32), shR=1.9, ftR=-0.5)
KEEP_UP = F(KEEP, hips=((0, 0.14, -0.3), (0.3, 0, 0)), thL=(1.45, 0.3), shL=1.6, ftL=-0.4, thR=(1.45, 0.3), shR=1.6, ftR=-0.4)
GATHER = F(hips=((0, 0.1, -0.22), (0.22, 0, 0)), spine=(0.12, 0, 0), chest=(0.0, 0, 0), neck=(-0.2, 0, 0), head=(-0.15, 0, 0),
           uaL=(1.3, 0.05), faL=1.1, uaR=(1.3, 0.05), faR=1.1, hL=-0.2, hR=-0.2,
           thL=(1.05, 0.25), shL=1.3, ftL=-0.3, thR=(1.05, 0.25), shR=1.3, ftR=-0.3)
GATHER_IN = F(GATHER, uaL=(0.9, 0.08), faL=1.7, uaR=(0.9, 0.08), faR=1.7, spine=(0.2, 0, 0))

FIELDER_CLIPS = {
    "idle": [(0.0, F_BASE), (1.0, F(chest=(0.0, 0, 0), spine=(0.03, 0.03, 0), head=(0.03, 0.05, 0))), (2.0, F_BASE)],
    "ready": [(0.0, READY), (0.5, F(READY, hips=((0, -0.04, -0.13), (0.28, 0, 0)))), (1.0, READY)],
    "run": [(0.0, RUN_A), (0.15, RUN_B), (0.3, mirror_run(RUN_A)), (0.45, mirror_run(RUN_B)), (0.6, RUN_A)],
    "catch": [(0.0, RUN_B), (0.18, CATCH_UP), (0.4, CATCH_IN), (1.0, CATCH_IN)],
    "dive": [(0.0, READY), (0.2, DIVE_1), (0.45, DIVE_2), (1.0, DIVE_2)],
    "pickup": [(0.0, RUN_B), (0.25, PICK_1), (0.55, PICK_2)],
    "throw": [(0.0, PICK_2), (0.2, THROW_1), (0.38, THROW_2), (0.65, THROW_3), (1.0, F_BASE)],
    "bowl": [(0.0, RUN_A), (0.18, BOWL_GATHER), (0.4, BOWL_COIL), (RELEASE, BOWL_RELEASE), (0.8, BOWL_FOLLOW),
             (1.3, F(RUN_B, spine=(0.3, 0.1, 0)))],
    "keep": [(0.0, KEEP), (0.5, KEEP_UP), (1.0, KEEP)],
    "gather": [(0.0, KEEP), (0.3, GATHER), (0.55, GATHER_IN), (1.2, GATHER_IN)],   # ball is taken at 0.3 s
}


def author(rig, clips, apply_fn, gap=12):
    """Lay every clip out on one timeline; returns [(name, start_frame, end_frame)]."""
    ranges = []
    frame = 1
    for name, keys in clips.items():
        _prev_euler.clear()
        end = frame
        for t, pose in keys:
            f = frame + round(t * FPS)
            apply_fn(pose, f)
            end = max(end, f)
        ranges.append((name, frame, end))
        frame = end + gap
    return ranges


def bake_and_split(rig, ranges):
    vl = bpy.context.view_layer
    bpy.ops.object.select_all(action="DESELECT")
    vl.objects.active = rig
    rig.select_set(True)
    bpy.ops.object.mode_set(mode="POSE")
    bpy.ops.pose.select_all(action="SELECT")
    start = min(r[1] for r in ranges)
    end = max(r[2] for r in ranges)
    authored = rig.animation_data.action if rig.animation_data else None
    bpy.ops.nla.bake(frame_start=start, frame_end=end, step=1, only_selected=False, visual_keying=True,
                     clear_constraints=True, clear_parents=False, use_current_action=False, bake_types={"POSE"})
    bpy.ops.object.mode_set(mode="OBJECT")
    baked = rig.animation_data.action
    out = []
    for name, s, e in ranges:
        a = bpy.data.actions.new(name)
        a.use_fake_user = True
        for fc in baked.fcurves:
            if fc.data_path.startswith('pose.bones["root"]') or fc.data_path.endswith("scale"):
                continue
            if fc.data_path.endswith("location") and not (
                    fc.data_path.startswith('pose.bones["hips"]') or fc.data_path.startswith('pose.bones["bat"]')):
                continue
            nf = a.fcurves.new(fc.data_path, index=fc.array_index, action_group=fc.group.name if fc.group else "")
            pts = [tuple(k.co) for k in fc.keyframe_points if s <= k.co.x <= e]
            nf.keyframe_points.add(len(pts))
            for kp, (x, y) in zip(nf.keyframe_points, pts):
                kp.co = (x - s, y)
                kp.interpolation = "LINEAR"
        out.append(a)
    rig.animation_data.action = None
    for a in (baked, authored):
        if a:
            bpy.data.actions.remove(a)
    # one NLA track per clip -> one named glTF animation per clip
    for a in out:
        a.id_root = "OBJECT"
        tr = rig.animation_data.nla_tracks.new()
        tr.name = a.name
        st = tr.strips.new(a.name, 0, a)
        st.name = a.name
        tr.mute = False
    return out


def build_animated(kind):
    rig, body = build_character(kind)
    if kind == "batsman":
        C = setup_batsman_controls(rig)
        ranges = author(rig, BATSMAN_CLIPS, lambda pose, f: apply_batsman_pose(rig, C, pose, f))
    else:
        C = None
        ranges = author(rig, FIELDER_CLIPS, lambda pose, f: apply_fielder_pose(rig, pose, f))
    return rig, body, C, ranges


def cleanup_controls(C):
    if not C:
        return
    for k, v in C.items():
        if isinstance(v, bpy.types.Object):
            if v.animation_data and v.animation_data.action:
                bpy.data.actions.remove(v.animation_data.action)
            bpy.data.objects.remove(v, do_unlink=True)


def export(kind, rig, body):
    os.makedirs(OUT, exist_ok=True)
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    body.select_set(True)
    for e in EXTRAS.get(kind, []):
        e.select_set(True)
    bpy.context.view_layer.objects.active = rig
    path = os.path.join(OUT, kind + ".glb")
    bpy.ops.export_scene.gltf(
        filepath=path, export_format="GLB", use_selection=True,
        export_animations=True, export_animation_mode="NLA_TRACKS", export_force_sampling=True,
        export_def_bones=False, export_yup=True, export_apply=False, export_morph=False,
        export_optimize_animation_size=True, export_reset_pose_bones=True,
    )
    return path


def contact_sheet(frames, path, cols):
    """Combine several rendered PNGs into one image with Blender's image API."""
    imgs = [bpy.data.images.load(f) for f in frames]
    w, h = imgs[0].size
    rows = (len(imgs) + cols - 1) // cols
    sheet = bpy.data.images.new("sheet", w * cols, h * rows)
    import numpy as np
    buf = np.zeros((h * rows, w * cols, 4), dtype=np.float32)
    for i, im in enumerate(imgs):
        px = np.array(im.pixels[:], dtype=np.float32).reshape(h, w, 4)
        r, c = rows - 1 - i // cols, i % cols
        buf[r * h:(r + 1) * h, c * w:(c + 1) * w] = px
    sheet.pixels = buf.ravel()
    sheet.filepath_raw = path
    sheet.file_format = "PNG"
    sheet.save()


def preview_clips(kind, rig, ranges, names, times, views, size=260):
    cam = setup_preview_scene()
    sc = bpy.context.scene
    sc.render.resolution_x = size
    sc.render.resolution_y = size
    sc.cycles.samples = 8
    rng = {n: (s, e) for n, s, e in ranges}
    for n in names:
        frames = []
        for t in times:
            s, e = rng[n]
            sc.frame_set(min(e, s + round(t * FPS)))
            for vi, (loc, tgt) in enumerate(views):
                p = os.path.join(PREVIEW, f"_{kind}_{n}_{t:.2f}_{vi}.png")
                render(p, cam, loc, tgt)
                frames.append(p)
        contact_sheet(frames, os.path.join(PREVIEW, f"{kind}_{n}.png"), cols=len(times) * 0 + len(times) if len(views) == 1 else len(views))
        for f in frames:
            os.remove(f)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "export"
    os.makedirs(PREVIEW, exist_ok=True)
    if mode == "rest":
        reset()
        build_character("batsman")
        f, _ = build_character("fielder")
        f.location.x = 1.2
        cam = setup_preview_scene()
        render(os.path.join(PREVIEW, "rest_front.png"), cam, (0.6, -4.2, 1.2), (0.6, 0, 0.95))
        render(os.path.join(PREVIEW, "rest_three_q.png"), cam, (3.0, -3.0, 1.6), (0.6, 0, 0.95))
    elif mode in ("bat", "field"):
        kind = "batsman" if mode == "bat" else "fielder"
        names = sys.argv[2].split(",")
        times = [float(x) for x in sys.argv[3].split(",")]
        reset()
        rig, body, C, ranges = build_animated(kind)
        if "--gear" in sys.argv:
            pass
        else:
            for e in EXTRAS.get(kind, []):
                e.hide_render = True
        if kind == "batsman":   # game camera (behind the stumps) + side-on from the off side
            views = [((-4.6, -0.5, 2.1), (1.0, -0.1, 0.8)), ((0.2, -4.2, 1.1), (0.2, 0.0, 0.9))]
        else:
            views = [((2.6, -3.4, 1.3), (0.0, 0.0, 0.8))]
        preview_clips(kind, rig, ranges, names, times, views)
    else:
        for kind in ("batsman", "fielder"):
            reset()
            rig, body, C, ranges = build_animated(kind)
            bake_and_split(rig, ranges)
            cleanup_controls(C)
            print("exported", export(kind, rig, body), [r[0] for r in ranges])
    print("done")
