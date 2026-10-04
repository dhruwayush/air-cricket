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

# --------------------------------------------------------------------------
# detailed geometry helpers
#   Everything is built in the rest pose and skinned by name: each vertex gets
#   a small {bone: weight} dict, so joints (shoulders, elbows, knees) bend
#   smoothly instead of being separate rigid pieces.
# --------------------------------------------------------------------------

def mesh_obj(name, verts, faces, face_mats, weights, smooth=True, recalc=True):
    me = bpy.data.meshes.new(name)
    me.from_pydata([tuple(v) for v in verts], [], [tuple(f) for f in faces])
    me.update()
    ob = bpy.data.objects.new(name, me)
    bpy.context.collection.objects.link(ob)
    order = []
    for m in face_mats:
        if m.name not in [o.name for o in order]:
            order.append(m)
    for m in order:
        me.materials.append(m)
    idx = {m.name: i for i, m in enumerate(order)}
    for p, m in zip(me.polygons, face_mats):
        p.material_index = idx[m.name]
        p.use_smooth = smooth
    groups = {}
    for vi, wd in enumerate(weights):
        tot = sum(w for w in wd.values() if w > 0) or 1.0
        for b, w in wd.items():
            if w <= 1e-4:
                continue
            if b not in groups:
                groups[b] = ob.vertex_groups.new(name=b)
            groups[b].add([vi], w / tot, "REPLACE")
    if recalc:
        bm = bmesh.new()
        bm.from_mesh(me)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(me)
        bm.free()
    return ob


def wb(t, a, b):
    """Smooth hand-over from bone a (t <= 0) to bone b (t >= 1)."""
    t = min(1.0, max(0.0, t))
    t = t * t * (3 - 2 * t)
    return {a: 1 - t, b: t}


def tube(name, pts, prof, mat_fn, w_fn, n=16, caps=(True, True), up=(0, -1, 0)):
    """Rings through pts. prof[i] is a radius or (side, up) radii. Ring angle a: 0 = side axis
    (t x up), 90 deg = up axis. mat_fn(i, a) -> material for the band after ring i; w_fn(i) -> weights."""
    pts = [Vector(p) for p in pts]
    upv = Vector(up).normalized()
    verts, faces, fm, ws, rings = [], [], [], [], []
    for i, c in enumerate(pts):
        t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        side = t.cross(upv)
        if side.length < 1e-4:
            side = t.cross(Vector((1, 0, 0)))
        side.normalize()
        u = side.cross(t).normalized()
        r = prof[i]
        rs, ru = r if isinstance(r, tuple) else (r, r)
        ring = []
        for k in range(n):
            a = 2 * math.pi * k / n
            verts.append(c + side * (math.cos(a) * rs) + u * (math.sin(a) * ru))
            ws.append(w_fn(i))
            ring.append(len(verts) - 1)
        rings.append(ring)
    for i in range(len(rings) - 1):
        for k in range(n):
            k2 = (k + 1) % n
            faces.append((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
            fm.append(mat_fn(i, 2 * math.pi * (k + 0.5) / n))
    for end in (0, 1):
        if not caps[end]:
            continue
        ring, c, i = (rings[0], pts[0], 0) if end == 0 else (rings[-1], pts[-1], len(pts) - 1)
        verts.append(c.copy())
        ws.append(w_fn(i))
        ci = len(verts) - 1
        for k in range(n):
            k2 = (k + 1) % n
            faces.append((ring[k2], ring[k], ci) if end == 0 else (ring[k], ring[k2], ci))
            fm.append(mat_fn(min(i, len(pts) - 2), 0.0))
    return mesh_obj(name, verts, faces, fm, ws)


def surface(name, fn, nu, nv, mat_fn, w_fn, thickness=0.0):
    """Open grid surface p = fn(u, v), u, v in [0, 1]; optionally given thickness (solidify)."""
    verts, faces, fm, ws = [], [], [], []
    for j in range(nv + 1):
        for i in range(nu + 1):
            u, v = i / nu, j / nv
            verts.append(fn(u, v))
            ws.append(w_fn(u, v))
    for j in range(nv):
        for i in range(nu):
            a = j * (nu + 1) + i
            faces.append((a, a + 1, a + nu + 2, a + nu + 1))
            fm.append(mat_fn((i + 0.5) / nu, (j + 0.5) / nv))
    ob = mesh_obj(name, verts, faces, fm, ws, recalc=False)
    if thickness:
        mod = ob.modifiers.new("solid", "SOLIDIFY")
        mod.thickness = thickness
        mod.offset = 0.0
        mod.use_even_offset = True
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.modifier_apply(modifier=mod.name)
        bm = bmesh.new()
        bm.from_mesh(ob.data)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        bm.to_mesh(ob.data)
        bm.free()
    return ob


def weighted(ob, wd):
    """Give a whole primitive the same blended weights (replacing its single bone group)."""
    for g in list(ob.vertex_groups):
        ob.vertex_groups.remove(g)
    tot = sum(wd.values())
    for b, w in wd.items():
        g = ob.vertex_groups.new(name=b)
        g.add(list(range(len(ob.data.vertices))), w / tot, "REPLACE")
    return ob


def lerpv(a, b, t):
    return Vector(a).lerp(Vector(b), t)


JP = lambda k: Vector(J[k])


# --------------------------------------------------------------------------
# body
# --------------------------------------------------------------------------

def torso(kind, shirt, trousers, belt, panel):
    sections = [   # z, half-width, half-depth, depth offset (+ is the back)
        (0.84, 0.124, 0.09, 0.006), (0.88, 0.157, 0.103, 0.006), (0.94, 0.168, 0.108, 0.006),
        (0.995, 0.164, 0.104, 0.004), (1.035, 0.159, 0.101, 0.002), (1.09, 0.150, 0.099, 0.0),
        (1.15, 0.155, 0.103, -0.003), (1.22, 0.169, 0.110, -0.006), (1.29, 0.183, 0.116, -0.007),
        (1.35, 0.192, 0.116, -0.004), (1.395, 0.188, 0.111, 0.0), (1.42, 0.172, 0.104, 0.004),
        (1.44, 0.148, 0.095, 0.006), (1.46, 0.124, 0.084, 0.008), (1.48, 0.09, 0.07, 0.008), (1.5, 0.062, 0.058, 0.008),
    ]
    pts = [(0, yo, z) for z, _, _, yo in sections]
    prof = [(rx, ry) for _, rx, ry, _ in sections]

    def mat_fn(i, a):
        z = (sections[i][0] + sections[i + 1][0]) / 2
        if z < 0.995:
            return trousers
        if z < 1.035:
            return belt
        if panel and 1.06 < z < 1.42 and abs(math.cos(a)) > 0.9:   # contrasting side panels on the shirt
            return panel
        return shirt

    def w_fn(i):
        z = sections[i][0]
        if z < 1.02:
            return {"hips": 1.0}
        if z < 1.14:
            return wb((z - 1.02) / 0.12, "hips", "spine")
        if z < 1.24:
            return {"spine": 1.0}
        if z < 1.34:
            return wb((z - 1.24) / 0.1, "spine", "chest")
        if z < 1.48:
            return {"chest": 1.0}
        return wb((z - 1.48) / 0.04, "chest", "neck")

    return tube(kind + "_torso", pts, prof, mat_fn, w_fn, n=28, up=(0, -1, 0))


def arm(kind, s, sx, sleeve, cuff, skin, long_sleeve):
    """Shoulder to wrist as one tube; long sleeves for the batsman, short for fielders."""
    S, E, W = JP("shoulder." + s), JP("elbow." + s), JP("wrist." + s)
    rows = []   # (point, (side, front) radius, weights, material of the band below)

    def add(p, r, w, m):
        rows.append((Vector(p), r, w, m))

    top = S + Vector((-0.05 * sx, 0.0, -0.005))
    add(top, (0.042, 0.05), {"chest": 0.6, "upper_arm." + s: 0.4}, sleeve)
    loose = 0.005
    for u, rs, rf in ((0.0, 0.05, 0.055), (0.12, 0.051, 0.055), (0.3, 0.049, 0.053), (0.5, 0.046, 0.049)):
        w = {"chest": 0.3, "upper_arm." + s: 0.7} if u == 0 else {"upper_arm." + s: 1.0}
        add(lerpv(S, E, u), (rs + loose, rf + loose), w, sleeve)
    if not long_sleeve:   # short sleeve: hem, then bare arm
        add(lerpv(S, E, 0.56), (0.047 + loose + 0.003, 0.05 + loose + 0.003), {"upper_arm." + s: 1.0}, sleeve)
        add(lerpv(S, E, 0.565), (0.045, 0.047), {"upper_arm." + s: 1.0}, skin)
        loose, m_ = 0.0, skin
    else:
        m_ = sleeve
    for u, rs, rf in ((0.72, 0.045, 0.047), (0.88, 0.042, 0.044), (1.0, 0.04, 0.042)):
        add(lerpv(S, E, u), (rs + loose, rf + loose), wb((u - 0.82) / 0.36, "upper_arm." + s, "forearm." + s), m_)
    for u, rs, rf in ((0.12, 0.042, 0.046), (0.35, 0.041, 0.043), (0.62, 0.035, 0.035), (0.84, 0.03, 0.027)):
        w = wb((u + 0.18) / 0.36, "upper_arm." + s, "forearm." + s) if u < 0.2 else {"forearm." + s: 1.0}
        add(lerpv(E, W, u), (rs + loose, rf + loose), w, m_)
    if long_sleeve:   # ribbed cuff over the wrist
        add(lerpv(E, W, 0.86), (0.035, 0.033), {"forearm." + s: 1.0}, cuff)
        add(lerpv(E, W, 1.0) + Vector((0, 0, -0.005)), (0.034, 0.032), {"forearm." + s: 0.7, "hand." + s: 0.3}, cuff)
    else:
        add(lerpv(E, W, 1.0) + Vector((0, 0, -0.012)), (0.027, 0.021), {"forearm." + s: 0.5, "hand." + s: 0.5}, skin)
    pts = [r[0] for r in rows]
    prof = [r[1] for r in rows]
    return tube(f"{kind}_arm_{s}", pts, prof, lambda i, a: rows[i][3], lambda i: rows[i][2], n=16, up=(0, -1, 0))


def leg(kind, s, sx, trousers, stripe):
    H, K, A = JP("hip." + s), JP("knee." + s), JP("ankle." + s)
    rows = []

    def add(p, r, w):
        rows.append((Vector(p), r, w))

    lo = 0.012   # trousers sit a little off the leg
    add(H + Vector((-0.012 * sx, 0.0, 0.05)), (0.08, 0.085), {"hips": 0.65, "thigh." + s: 0.35})
    for u, rs, rf, w in ((0.06, 0.088, 0.09, {"hips": 0.35, "thigh." + s: 0.65}), (0.2, 0.084, 0.087, None),
                         (0.42, 0.077, 0.078, None), (0.65, 0.068, 0.068, None), (0.84, 0.06, 0.06, None)):
        add(lerpv(H, K, u), (rs + lo, rf + lo), w or {"thigh." + s: 1.0})
    add(K, (0.056 + lo, 0.058 + lo), {"thigh." + s: 0.5, "shin." + s: 0.5})
    for u, rs, rf, back in ((0.12, 0.054, 0.058, 0.004), (0.32, 0.055, 0.064, 0.012), (0.55, 0.05, 0.054, 0.008),
                            (0.78, 0.042, 0.044, 0.002), (0.92, 0.038, 0.04, 0.0)):
        w = wb((u + 0.16) / 0.32, "thigh." + s, "shin." + s) if u < 0.16 else {"shin." + s: 1.0}
        add(lerpv(K, A, u) + Vector((0, back, 0)), (rs + lo, rf + lo), w)
    add(A + Vector((0, 0, 0.015)), (0.046, 0.05), {"shin." + s: 0.7, "foot." + s: 0.3})
    pts = [r[0] for r in rows]
    prof = [r[1] for r in rows]

    def mat_fn(i, a):
        # a = 0 points to -X; the outer side of the left leg is +X
        if stripe and math.cos(a) * -sx > 0.96:
            return stripe
        return trousers

    return tube(f"{kind}_leg_{s}", pts, prof, mat_fn, lambda i: rows[i][2], n=18, up=(0, -1, 0))


def shoe(s, sx, upper, sole, accent):
    A = JP("ankle." + s)
    x = A.x
    secs = [   # y (toe is -y), half-width, centre height, half-height
        (0.065, 0.03, 0.055, 0.045), (0.035, 0.04, 0.06, 0.056), (-0.02, 0.045, 0.055, 0.05),
        (-0.08, 0.047, 0.045, 0.04), (-0.14, 0.044, 0.036, 0.031), (-0.185, 0.035, 0.03, 0.025),
        (-0.212, 0.02, 0.027, 0.018),
    ]
    pts = [(x, y, cz) for y, _, cz, _ in secs]
    prof = [(hw, hh) for _, hw, _, hh in secs]

    def mat_fn(i, a):
        y = (secs[i][0] + secs[i + 1][0]) / 2
        if -0.12 < y < 0.03 and abs(math.cos(a)) > 0.8 and math.sin(a) > -0.2:
            return accent
        return upper

    up_ = tube(f"shoe_{s}", pts, prof, mat_fn, lambda i: {"foot." + s: 1.0} if secs[i][0] < 0.02 else {"foot." + s: 0.85, "shin." + s: 0.15},
               n=14, up=(0, 0, 1))
    # sole: a flat slab under the whole foot, with a small heel
    sp = [(x, y, 0.011) for y, _, _, _ in secs]
    sprof = [(hw + 0.004, 0.011) for _, hw, _, _ in secs]
    so = tube(f"sole_{s}", sp, sprof, lambda i, a: sole, lambda i: {"foot." + s: 1.0}, n=10, up=(0, 0, 1))
    return [up_, so]


def head_parts(skin, eye, hair, with_hair):
    parts = []
    parts.append(ellipsoid((0, 0.006, 1.69), (0.085, 0.098, 0.11), skin, "head", seg=24, rings=16))   # skull
    parts.append(ellipsoid((0, -0.03, 1.628), (0.068, 0.072, 0.058), skin, "head", seg=18, rings=12))  # jaw
    parts.append(ellipsoid((0, -0.074, 1.597), (0.03, 0.024, 0.024), skin, "head", seg=10, rings=8))  # chin
    parts.append(ellipsoid((0, -0.1, 1.668), (0.016, 0.022, 0.028), skin, "head", seg=10, rings=8, rot=(0.25, 0, 0)))  # nose
    for x in (0.087, -0.087):
        parts.append(ellipsoid((x, 0.004, 1.68), (0.012, 0.026, 0.032), skin, "head", seg=10, rings=8))   # ears
        parts.append(ellipsoid((x * 0.38, -0.088, 1.7), (0.012, 0.006, 0.007), eye, "head", seg=8, rings=6))  # eyes
        parts.append(ellipsoid((x * 0.39, -0.093, 1.722), (0.02, 0.006, 0.005), hair, "head", seg=8, rings=4))  # brows
    if with_hair:
        h = ellipsoid((0, 0.008, 1.695), (0.09, 0.104, 0.116), hair, "head", seg=24, rings=16)
        mw = h.matrix_world
        bm = bmesh.new()
        bm.from_mesh(h.data)
        W = lambda v: mw @ v.co
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if W(v).z < 1.655 or (W(v).y < -0.05 and W(v).z < 1.745)
                                   or (abs(W(v).x) > 0.07 and W(v).y < 0.02 and W(v).z < 1.69)], context="VERTS")
        bm.to_mesh(h.data)
        bm.free()
        parts.append(h)
    return parts


def neck_and_collar(kind, skin, collar):
    n = tube(kind + "_neck", [(0, 0.012, 1.44), (0, 0.008, 1.52), (0, 0.004, 1.6)], [(0.054, 0.05), (0.05, 0.047), (0.048, 0.046)],
             lambda i, a: skin, lambda i: [{"chest": 0.6, "neck": 0.4}, {"neck": 1.0}, {"neck": 0.6, "head": 0.4}][i], n=14, up=(0, -1, 0))
    bpy.ops.mesh.primitive_torus_add(major_radius=0.064, minor_radius=0.012, major_segments=28, minor_segments=8,
                                     location=(0, 0.004, 1.478), rotation=(-0.18, 0, 0))
    c = bpy.context.active_object
    c.scale = (1.0, 0.86, 1.0)
    bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
    _finish(c, collar, "chest")
    weighted(c, {"chest": 0.75, "neck": 0.25})
    return [n, c]


def fielder_hand(s, sx, skin):
    """Palm, four slightly curled fingers and a thumb, on the hand bone (fingers point down)."""
    W = JP("wrist." + s)
    parts = [ellipsoid(W + Vector((0.004 * sx, -0.008, -0.045)), (0.016, 0.038, 0.045), skin, "hand." + s, seg=12, rings=8)]
    for k, dy in enumerate((-0.03, -0.012, 0.006, 0.022)):
        L = (0.05, 0.056, 0.052, 0.042)[k]
        base = W + Vector((0.002 * sx, dy - 0.008, -0.085))
        mid = base + Vector((-0.006 * sx, -0.004, -L * 0.55))
        tip = mid + Vector((-0.014 * sx, -0.004, -L * 0.42))
        parts.append(tube(f"finger_{s}{k}", [base, mid, tip], [0.0085, 0.008, 0.0068], lambda i, a: skin,
                          lambda i: {"hand." + s: 1.0}, n=7))
    th0 = W + Vector((-0.008 * sx, -0.035, -0.035))
    parts.append(tube(f"thumb_{s}", [th0, th0 + Vector((-0.012 * sx, -0.016, -0.03)), th0 + Vector((-0.02 * sx, -0.02, -0.055))],
                      [0.011, 0.0095, 0.008], lambda i, a: skin, lambda i: {"hand." + s: 1.0}, n=7))
    return parts


def batting_glove(s, sx, glove, rolls, cuff):
    """The hand bone runs along the bat handle, so the glove is a mitt around that line: a cuffed wrist,
    padded finger rolls wrapping round the handle, and a thumb roll."""
    W, F = JP("wrist." + s), JP("fingers." + s)
    d = (F - W).normalized()
    parts = [tube(f"glove_cuff_{s}", [W - d * 0.045, W + d * 0.005], [(0.047, 0.05), (0.046, 0.049)],
                  lambda i, a: cuff, lambda i: [{"forearm." + s: 0.4, "hand." + s: 0.6}, {"hand." + s: 1.0}][i], n=16)]
    parts.append(tube(f"glove_body_{s}", [W, W + d * 0.04, F, F + d * 0.012],
                      [(0.044, 0.047), (0.045, 0.049), (0.04, 0.045), (0.026, 0.03)],
                      lambda i, a: glove, lambda i: {"hand." + s: 1.0}, n=16))
    for k in range(4):   # finger rolls: padded bands round the handle on the back of the glove
        c = W + d * (0.03 + 0.017 * k)
        bpy.ops.mesh.primitive_torus_add(major_radius=0.043 - 0.002 * k, minor_radius=0.0105, major_segments=18,
                                         minor_segments=6, location=c)
        r = bpy.context.active_object
        r.scale = (1.0, 1.1, 0.85)
        bpy.ops.object.transform_apply(location=False, rotation=True, scale=True)
        parts.append(_finish(r, rolls, "hand." + s))
    t0 = W + d * 0.02 + Vector((0, -0.045, 0))
    parts.append(tube(f"glove_thumb_{s}", [t0, t0 + d * 0.035 + Vector((0, -0.006, 0)), t0 + d * 0.06 + Vector((0, 0.004, 0))],
                      [0.013, 0.012, 0.009], lambda i, a: rolls, lambda i: {"hand." + s: 1.0}, n=8))
    return parts


def leg_pad(s, sx, pad, strap, buckle, top=0.66, wings=1.85, n_straps=3, rib=0.006):
    """A batting pad: a curved shell over the front of the shin with vertical canes, a three-roll knee,
    side wings and a top flap over the thigh, held on by straps round the back of the calf."""
    K, A = JP("knee." + s), JP("ankle." + s)
    z0 = 0.12

    def axis(z):
        t = (z - A.z) / (K.z - A.z)
        return Vector((K.x, A.y + (K.y - A.y) * t - 0.01, z))

    def half_angle(z):
        if z < 0.5:
            return wings
        if z < 0.6:
            return wings - (wings - 1.3) * (z - 0.5) / 0.1
        return 1.3 - 0.35 * (z - 0.6) / max(0.01, top - 0.6)

    def fn(u, v):
        z = z0 + (top - z0) * v
        th = (u * 2 - 1) * half_angle(z)
        R = 0.078 + 0.012 * (th / wings) ** 2
        if abs(th) < 1.35 and (z < 0.47 or z > 0.6):                        # vertical canes
            R += rib * (0.5 + 0.5 * math.cos(2 * math.pi * th / 0.34)) * math.cos(th * 0.9)
        if 0.47 <= z <= 0.6:                                                   # knee rolls
            R += 0.016 * (0.5 + 0.5 * math.cos(2 * math.pi * (z - 0.47) / 0.043)) * max(0.0, math.cos(th * 0.8))
        if z < 0.17:                                                           # instep: curls in at the bottom
            R -= 0.25 * (0.17 - z)
        c = axis(z)
        return c + Vector((math.sin(th) * R * sx, -math.cos(th) * R, 0))

    def w_fn(u, v):
        z = z0 + (top - z0) * v
        if z < 0.56:
            return {"shin." + s: 1.0}
        t = (z - 0.56) / max(0.01, top - 0.56)
        return {"shin." + s: 1 - 0.7 * t, "thigh." + s: 0.7 * t}

    parts = [surface(f"pad_{s}", fn, 28, 30, lambda u, v: pad, w_fn, thickness=0.022)]
    zs = (0.2, 0.32, 0.43)[:n_straps] if n_straps > 2 else (0.22, 0.4)
    for z in zs:   # straps: from wing to wing round the back of the calf
        c = axis(z) + Vector((0, 0.012, 0))
        th0 = wings * 0.92
        pts = []
        for k in range(17):
            th = th0 + (2 * math.pi - 2 * th0) * k / 16
            pts.append(c + Vector((math.sin(th) * 0.083 * sx, -math.cos(th) * 0.088, 0)))
        parts.append(tube(f"strap_{s}{z}", pts, [(0.003, 0.012)] * len(pts), lambda i, a: strap,
                          lambda i: {"shin." + s: 1.0}, n=6, up=(0, 0, 1)))
        bx = pts[3]
        parts.append(rbox(tuple(bx), (0.012, 0.012, 0.022), buckle, "shin." + s, bevel=0.003))
    return parts


def helmet_parts(shell, grille, strap):
    C = Vector((0, 0.006, 1.698))
    parts = []
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=20, radius=1, location=C)
    h = bpy.context.active_object
    h.scale = (0.124, 0.136, 0.13)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bm = bmesh.new()
    bm.from_mesh(h.data)
    # the rim drops from the brow at the front to the nape at the back
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < 1.655 - 0.42 * v.co.y], context="VERTS")
    bm.to_mesh(h.data)
    bm.free()
    _finish(h, shell, "head")
    mod = h.modifiers.new("solid", "SOLIDIFY")
    mod.thickness = 0.009
    mod.offset = 1.0
    bpy.context.view_layer.objects.active = h
    bpy.ops.object.modifier_apply(modifier=mod.name)
    parts.append(h)
    parts.append(ellipsoid((0, 0.0, 1.828), (0.022, 0.12, 0.012), shell, "head", seg=10, rings=6))          # crest ridge
    for x in (-0.05, 0.05):                                                                              # vents
        parts.append(ellipsoid((x, 0.03, 1.818), (0.012, 0.04, 0.008), mat("vent", "#05080d", 0.6), "head", seg=8, rings=4, rot=(0.0, x * 4, 0)))
    # peak
    bpy.ops.mesh.primitive_uv_sphere_add(segments=28, ring_count=8, radius=1, location=(0, -0.085, 1.722))
    pk = bpy.context.active_object
    pk.scale = (0.122, 0.09, 0.013)
    pk.rotation_euler = (0.16, 0, 0)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bm = bmesh.new()
    bm.from_mesh(pk.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.y > -0.07], context="VERTS")
    bm.to_mesh(pk.data)
    bm.free()
    parts.append(_finish(pk, shell, "head"))
    # ear pieces with a bolt for the grille
    for sx in (1, -1):
        parts.append(ellipsoid((0.114 * sx, -0.014, 1.655), (0.012, 0.046, 0.05), shell, "head", seg=14, rings=10))
        parts.append(cyl((0.12 * sx, -0.03, 1.66), (0.127 * sx, -0.03, 1.66), 0.007, grille, "head", verts=10))
    # grille: three curved bars round the face and three uprights
    def arc(z, rx, ry, a0, a1, yo=0.0, sag=0.0):
        out = []
        for k in range(13):
            a = a0 + (a1 - a0) * k / 12
            out.append(Vector((math.sin(a) * rx, -math.cos(a) * ry + yo, z - sag * math.cos(a) ** 2)))
        return out
    bars = [arc(1.706, 0.123, 0.147, -1.25, 1.25), arc(1.655, 0.122, 0.15, -1.3, 1.3), arc(1.605, 0.11, 0.138, -1.2, 1.2, sag=0.012)]
    for k, pts in enumerate(bars):
        parts.append(tube(f"grille_{k}", pts, [0.0045] * len(pts), lambda i, a: grille, lambda i: {"head": 1.0}, n=6, up=(0, 0, 1)))
    for k, a in enumerate((-0.42, 0.0, 0.42)):
        top_ = Vector((math.sin(a) * 0.123, -math.cos(a) * 0.147, 1.706))
        bot = Vector((math.sin(a) * 0.11, -math.cos(a) * 0.138, 1.605 - 0.012 * math.cos(a) ** 2))
        mid = (top_ + bot) / 2 + Vector((0, -0.006, 0))
        parts.append(tube(f"grille_v{k}", [top_, mid, bot], [0.0042] * 3, lambda i, a: grille, lambda i: {"head": 1.0}, n=6))
    # neck guard at the back, and the chin strap
    # stem guard: two curved plates hanging from the back of the rim, following the neck
    for side in (-1, 1):
        def plate(u, v, side=side):
            a = side * (0.12 + 0.75 * u)                  # radians round from straight behind
            z = 1.6 - 0.075 * v
            r = 0.083 - 0.012 * v
            return Vector((math.sin(a) * r, 0.012 + math.cos(a) * r, z))
        parts.append(surface(f"stem_guard_{side}", plate, 6, 4, lambda u, v: shell, lambda u, v: {"head": 1.0}, thickness=0.01))
    parts.append(tube("chin_strap", [(-0.112, -0.02, 1.625), (-0.06, -0.06, 1.585), (0, -0.07, 1.57), (0.06, -0.06, 1.585), (0.112, -0.02, 1.625)],
                      [(0.006, 0.0025)] * 5, lambda i, a: strap, lambda i: {"head": 1.0}, n=6, up=(0, 0, 1)))
    return parts


def bat_parts(willow, grip, label, label2):
    top = BAT_TOP
    xf = top.x - 0.02                          # face of the blade (it faces -x)
    zs, zt = top.z - 0.31, top.z - 0.86        # shoulder and toe
    rings, n_side = [], 9
    parts = []

    def section(z):
        t = (z - zt) / (zs - zt)               # 0 at the toe, 1 at the shoulder
        w = 0.054 * (1 - 0.85 * max(0.0, (0.035 - t) / 0.035) ** 2)
        spine = 0.042 + 0.023 * math.sin(math.pi * min(1.0, max(0.0, (t - 0.04) / 0.8)))
        edge = 0.036 - 0.014 * t
        pts = []
        for k in range(n_side + 1):            # the flat face, edge to edge
            y = w - 2 * w * k / n_side
            pts.append(Vector((xf, top.y + y * 0.96, z)))
        for k in range(n_side + 1):            # the back: thick edges rising to the spine
            y = -w + 2 * w * k / n_side
            q = abs(y) / w
            pts.append(Vector((xf + edge + (spine - edge) * (1 - q ** 1.6) ** 0.9 - 0.006 * q ** 6, top.y + y, z)))
        return pts

    verts, faces, fm, ws = [], [], [], []
    nz = 40
    for j in range(nz + 1):
        z = zt + (zs - zt) * j / nz
        ring = section(z)
        rings.append(list(range(len(verts), len(verts) + len(ring))))
        verts += ring
        ws += [{"bat": 1.0}] * len(ring)
    m = len(rings[0])
    for j in range(nz):
        t = (j + 0.5) / nz
        for k in range(m):
            k2 = (k + 1) % m
            faces.append((rings[j][k], rings[j][k2], rings[j + 1][k2], rings[j + 1][k]))
            face_side = k < n_side
            if face_side and 0.66 < t < 0.8:
                fm.append(label if 0.68 < t < 0.78 else label2)
            elif not face_side and 0.4 < t < 0.62 and n_side + 2 < k < 2 * n_side - 1:
                fm.append(label)
            else:
                fm.append(willow)
    for ring, z in ((rings[0], zt), (rings[-1], zs)):
        c = sum((verts[i] for i in ring), Vector()) / len(ring)
        verts.append(c)
        ws.append({"bat": 1.0})
        ci = len(verts) - 1
        for k in range(m):
            faces.append((ring[k], ring[(k + 1) % m], ci))
            fm.append(willow)
    parts.append(mesh_obj("blade", verts, faces, fm, ws))
    # shoulders: blade narrowing into the splice and handle
    sh = []
    for k in range(6):
        u = k / 5
        z = zs + 0.05 * u
        sh.append((Vector((xf + 0.02, top.y, z)), (0.052 * (1 - u) + 0.019 * u, 0.026 * (1 - u) + 0.018 * u)))
    parts.append(tube("shoulders", [p for p, _ in sh], [r for _, r in sh], lambda i, a: willow,
                      lambda i: {"bat": 1.0}, n=14, up=(1, 0, 0)))
    # handle with a ribbed rubber grip and an end cap
    hp, hr = [], []
    for k in range(61):
        z = zs + 0.04 + (top.z + 0.012 - zs - 0.04) * k / 60
        hp.append(Vector((xf + 0.02, top.y, z)))
        hr.append(0.0172 + (0.0011 if k % 2 else 0.0))
    parts.append(tube("handle", hp, hr, lambda i, a: grip, lambda i: {"bat": 1.0}, n=12))
    return parts


def cap_parts(cap, button):
    c = ellipsoid((0, 0.006, 1.712), (0.094, 0.106, 0.112), cap, "head", seg=24, rings=14)
    cut_below(c, 1.698)
    parts = [c, ellipsoid((0, 0.0, 1.823), (0.011, 0.011, 0.007), button, "head", seg=8, rings=4)]
    bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=8, radius=1, location=(0, -0.07, 1.708))
    b = bpy.context.active_object
    b.scale = (0.088, 0.1, 0.011)
    b.rotation_euler = (0.12, 0, 0)
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bm = bmesh.new()
    bm.from_mesh(b.data)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.y > -0.05], context="VERTS")
    bm.to_mesh(b.data)
    bm.free()
    parts.append(_finish(b, cap, "head"))
    return parts


def shirt_number(text, torso_ob, colour):
    """A number printed on the back of the shirt, shrink-wrapped onto it."""
    cu = bpy.data.curves.new("num", "FONT")
    cu.body = text
    cu.size = 0.15
    cu.align_x = "CENTER"
    cu.align_y = "CENTER"
    ob = bpy.data.objects.new("num", cu)
    bpy.context.collection.objects.link(ob)
    # text faces +z: turn it to face backwards (+y), reading left to right for someone behind
    ob.matrix_world = Matrix(((-1, 0, 0, 0), (0, 0, 1, 0.2), (0, 1, 0, 1.285), (0, 0, 0, 1)))
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.convert(target="MESH")
    ob = bpy.context.active_object
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.triangulate(bm, faces=bm.faces)
    bmesh.ops.subdivide_edges(bm, edges=[e for e in bm.edges if e.calc_length() > 0.02], cuts=2, use_grid_fill=False)
    bm.to_mesh(ob.data)
    bm.free()
    sw = ob.modifiers.new("wrap", "SHRINKWRAP")
    sw.target = torso_ob
    sw.wrap_method = "PROJECT"
    sw.use_negative_direction = True
    sw.use_project_y = True
    sw.offset = 0.0025
    bpy.ops.object.modifier_apply(modifier=sw.name)
    ob.data.materials.append(colour)
    for p in ob.data.polygons:
        p.use_smooth = True
    gs, gc = ob.vertex_groups.new(name="spine"), ob.vertex_groups.new(name="chest")
    for v in ob.data.vertices:   # follow the shirt's own spine/chest blend
        w = wb((v.co.z - 1.24) / 0.1, "spine", "chest")
        gs.add([v.index], w["spine"], "REPLACE")
        gc.add([v.index], w["chest"], "REPLACE")
    return ob


# --------------------------------------------------------------------------
# the two characters
# --------------------------------------------------------------------------

def keeper_gear_parts():
    """Wicket-keeping pads and big gauntlets, skinned to the fielder rig and shown only on the keeper."""
    parts = []
    pad = mat("keeper_pad", "#f1efe6", 0.8)
    strap = mat("keeper_strap", "#16244d", 0.7)
    buckle = mat("buckle", "#c9ccd1", 0.35, 0.8)
    glove = mat("keeper_glove", "#e8dcc2", 0.75)
    web = mat("keeper_web", "#c9b48a", 0.8)
    for s, sx in (("L", 1), ("R", -1)):
        parts += leg_pad(s, sx, pad, strap, buckle, top=0.6, wings=1.55, n_straps=2, rib=0.005)
        w = JP("wrist." + s)
        parts.append(limb(w + Vector((0, 0, 0.05)), w + Vector((0, 0, -0.01)), 0.052, 0.058, glove, "hand." + s, overlap=0.0))  # cuff
        parts.append(ellipsoid(w + Vector((0, -0.012, -0.075)), (0.068, 0.058, 0.092), glove, "hand." + s, seg=18, rings=12))  # mitt
        parts.append(ellipsoid(w + Vector((0, -0.052, -0.085)), (0.05, 0.02, 0.07), web, "hand." + s, seg=14, rings=8))   # palm
        for k in range(4):   # finger seams on the back of the mitt
            parts.append(ellipsoid(w + Vector((-0.03 + 0.02 * k, 0.046, -0.09)), (0.008, 0.012, 0.06), glove, "hand." + s, seg=8, rings=6))
    return parts


def build_body(kind):
    """kind: 'batsman' or 'fielder'. Returns list of mesh objects (weighted by bone name)."""
    bat = kind == "batsman"
    k = kind + "_"
    skin = mat("skin", "#9a6644", 0.55)
    shirt = mat(k + "shirt", "#f0a431" if bat else "#3462d6", 0.82)
    panel = mat(k + "panel", "#1c2d59" if bat else "#1f3f9e", 0.8)
    trousers = mat(k + "trousers", "#1c2d59" if bat else "#16244d", 0.82)
    trim = mat(k + "trim", "#1c2d59" if bat else "#f0c040", 0.7)
    shoe_up = mat("shoe", "#eeeee9", 0.5)
    sole = mat("sole", "#2a2a2a", 0.85)
    accent = mat(k + "shoe_accent", "#1c2d59" if bat else "#f0c040", 0.5)
    eye = mat("eye", "#1d1410", 0.3)
    hair = mat("hair", "#17110d", 0.7)
    parts = []

    t = torso(kind, shirt, trousers, trim, panel)
    parts.append(t)
    parts += neck_and_collar(kind, skin, trim)
    parts += head_parts(skin, eye, hair, with_hair=not bat)
    for s, sx in (("L", 1), ("R", -1)):
        parts.append(weighted(ellipsoid(JP("shoulder." + s) + Vector((-0.016 * sx, 0.0, -0.02)), (0.052, 0.058, 0.062), shirt, "chest", seg=16, rings=10),
                              {"chest": 0.3, "upper_arm." + s: 0.7}))
        parts.append(arm(kind, s, sx, shirt, trim, skin, long_sleeve=bat))
        parts.append(leg(kind, s, sx, trousers, None if bat else trim))
        parts += shoe(s, sx, shoe_up, sole, accent)
        if bat:
            parts += batting_glove(s, sx, mat("glove", "#f4f2ec", 0.8), mat("glove_roll", "#e9e6dd", 0.85), trim)
            parts += leg_pad(s, sx, mat("pad", "#f3f1ea", 0.82), mat("pad_strap", "#e4e2db", 0.75), mat("buckle", "#c9ccd1", 0.35, 0.8))
        else:
            parts += fielder_hand(s, sx, skin)
    if bat:
        parts += helmet_parts(mat("helmet", "#16244a", 0.32), mat("grille", "#b7bec6", 0.28, 0.85), mat("strap", "#111111", 0.7))
        parts += bat_parts(mat("willow", "#e2c38b", 0.5), mat("grip", "#1d1d1d", 0.9), mat("bat_label", "#1c2d59", 0.45), mat("bat_label2", "#f0a431", 0.45))
        parts.append(shirt_number("7", t, trim))
    else:
        parts += cap_parts(mat("cap", "#16244d", 0.7), trim)
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
    if BAKE_AO:
        bake_ao(body, rig, hide=EXTRAS[kind])
        for e in EXTRAS[kind]:
            bake_ao(e, rig)
    for ob in [body] + EXTRAS[kind]:
        collapse_materials(ob)
    return rig, body


EXTRAS = {}
BAKE_AO = True
AO_FLOOR = 0.4      # the darkest crease keeps this much of its colour


FINISHES = {   # name: (roughness, metalness); every material folds into one of these
    "fin_matte": (0.82, 0.0),     # cloth, pads, grip, soles
    "fin_satin": (0.55, 0.0),     # skin, shoes, willow
    "fin_gloss": (0.32, 0.0),     # helmet shell, eyes, bat stickers
    "fin_metal": (0.3, 0.85),     # grille, buckles
}


def finish_of(m):
    b = m.node_tree.nodes.get("Principled BSDF")
    r, mt = b.inputs["Roughness"].default_value, b.inputs["Metallic"].default_value
    if mt > 0.5:
        return "fin_metal"
    return "fin_matte" if r >= 0.7 else "fin_satin" if r >= 0.47 else "fin_gloss"


def collapse_materials(ob):
    """Each player becomes a handful of draw calls instead of twenty: every face's colour (times the baked
    occlusion) goes into a per-corner vertex colour, and faces share one material per finish."""
    me = ob.data
    ao = me.color_attributes.get("AO")
    col = me.color_attributes.new("Col", "FLOAT_COLOR", "CORNER")
    fins = {}
    for m in me.materials:
        f = finish_of(m)
        if f not in fins:
            fm = bpy.data.materials.get(f)
            if fm is None:
                fm = bpy.data.materials.new(f)
                fm.use_nodes = True
                bsdf = fm.node_tree.nodes.get("Principled BSDF")
                bsdf.inputs["Base Color"].default_value = (1, 1, 1, 1)
                bsdf.inputs["Roughness"].default_value, bsdf.inputs["Metallic"].default_value = FINISHES[f]
                va = fm.node_tree.nodes.new("ShaderNodeVertexColor")      # so Blender previews show the colours too
                va.layer_name = "Col"
                fm.node_tree.links.new(va.outputs["Color"], bsdf.inputs["Base Color"])
            fins[f] = fm
    order = list(fins)
    remap = []
    for m in me.materials:
        bc = m.node_tree.nodes.get("Principled BSDF").inputs["Base Color"].default_value
        remap.append((order.index(finish_of(m)), (bc[0], bc[1], bc[2])))
    new_idx = []
    for p in me.polygons:
        idx, c = remap[p.material_index]
        for li in p.loop_indices:
            a = ao.data[me.loops[li].vertex_index].color[0] if ao else 1.0
            col.data[li].color = (c[0] * a, c[1] * a, c[2] * a, 1.0)
        new_idx.append(idx)
    me.materials.clear()                 # (this resets every face to slot 0, so set them again after)
    for f in order:
        me.materials.append(fins[f])
    for p, idx in zip(me.polygons, new_idx):
        p.material_index = idx
    if ao:
        me.color_attributes.remove(ao)
    me.color_attributes.active_color = me.color_attributes.get("Col")


def bake_ao(ob, rig, hide=()):
    """Bake local ambient occlusion into a vertex colour layer, so creases (under the helmet peak, inside the
    collar, between pad canes, round the gloves) are darker. The rig is spread first, arms away from the body
    and the bat out to the side, so only creases that stay creases in play get shaded."""
    addon_utils.enable("cycles", default_set=True)
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"
    sc.cycles.samples = 64
    if sc.world is None:
        sc.world = bpy.data.worlds.new("bake_world")
    sc.world.light_settings.distance = 0.1
    pbs = rig.pose.bones
    for s, sx in (("L", 1), ("R", -1)):
        set_rot(pbs["upper_arm." + s], limb_R(0.15, 0.55, sx=sx))
        set_rot(pbs["thigh." + s], limb_R(0.0, 0.1, sx=sx))
    if "bat" in pbs:
        pbs["bat"].matrix = Matrix.Translation((-0.5, 0.0, 0.0)) @ pbs["bat"].matrix
    bpy.context.view_layer.update()
    for h in hide:
        h.hide_render = True
    me = ob.data
    ca = me.color_attributes.new("AO", "FLOAT_COLOR", "POINT")
    me.color_attributes.active_color = ca
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    sc.render.bake.target = "VERTEX_COLORS"
    bpy.ops.object.bake(type="AO")
    for h in hide:
        h.hide_render = False
    for d in ca.data:
        v = AO_FLOOR + (1 - AO_FLOOR) * d.color[0]
        d.color = (v, v, v, 1.0)
    for pb in pbs:
        pb.matrix_basis = Matrix.Identity(4)
    bpy.context.view_layer.update()


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

# ---------------- more shots ----------------
# Blender frame for the batsman: bowler at +X, off side at -Y, up +Z.
# bat = (grip-top position, (tilt about X, swing about Y, yaw about Z)).
PUNCH_FEET = dict(footR=((-0.3, -0.3, 0.03), 0.25), footL=((0.18, -0.2, 0.03), 0.3))
BACK_UP = dict(BACKFOOT, hips=((-0.08, -0.08, -0.03), (0.02, 0.2, 0.0)),
               spine=(0.1, 0.1, 0.0), chest=(0.05, 0.15, 0.0), head=(0.12, 0.7, 0.05))
SWEEP_BODY = dict(
    footL=((0.6, -0.32, 0.03), 0.35), footR=((-0.3, -0.06, 0.07), -0.3),
    hips=((0.12, -0.02, -0.4), (0.35, 0.2, 0.1)),
    spine=(0.3, 0.1, 0.0), chest=(0.15, 0.1, 0.0), neck=(0.15, 0.4, 0.0), head=(0.3, 0.8, 0.1),
    kneeL=(0.9, -0.8, 0.6), kneeR=(-0.1, -0.9, 0.1), elbowL=(0.6, -0.5, 0.8), elbowR=(0.1, -0.7, 0.6),
)
SCOOP_BODY = dict(
    footL=((0.55, -0.25, 0.03), 0.3), footR=((-0.22, -0.12, 0.07), 0.1),
    hips=((0.18, -0.05, -0.36), (0.45, 0.35, 0.0)),
    spine=(0.3, 0.1, 0.0), chest=(0.1, 0.1, 0.0), neck=(0.05, 0.3, 0.0), head=(0.3, 0.6, 0.0),
    kneeL=(0.9, -0.8, 0.6), kneeR=(-0.1, -0.9, 0.1), elbowL=(0.6, -0.6, 0.8), elbowR=(0.2, -0.7, 0.7),
)
DUCK = P(bat=((-0.2, -0.05, 0.62), (0.0, 0.6, 0.0)), footL=((0.3, -0.2, 0.03), 0.35), footR=((-0.2, -0.18, 0.03), 0.1),
         hips=((-0.1, 0.05, -0.45), (0.9, -0.1, 0.0)), spine=(0.45, 0.0, 0.0), chest=(0.2, 0.0, 0.0),
         neck=(0.4, 0.3, 0.0), head=(0.5, 0.3, 0.0), kneeL=(0.6, -1.0, 0.4), kneeR=(-0.2, -1.0, 0.4),
         elbowL=(0.1, -0.5, 0.8), elbowR=(-0.4, -0.4, 0.7))

BATSMAN_CLIPS.update({
    "on_drive": shot(
        P(bat=((0.34, -0.26, 0.86), (0.0, -0.12, 0.35)), footL=((0.64, -0.1, 0.03), 0.75),
          **dict(FRONT, hips=((0.2, 0.0, -0.14), (0.05, 0.3, 0.12)))),
        P(bat=((0.3, 0.0, 1.4), (0.0, -2.5, 0.5)), footL=((0.64, -0.1, 0.03), 0.75),
          **dict(THRU, hips=((0.24, 0.0, -0.1), (0.0, 0.55, 0.1)), chest=(0.05, 0.5, 0.0))),
        None),
    "sq_drive": shot(
        P(bat=((0.24, -0.44, 0.84), (0.0, -0.08, -0.75)), footL=((0.55, -0.45, 0.03), -0.05), **FRONT),
        P(bat=((0.12, -0.42, 1.3), (0.0, -2.3, -1.2)), footL=((0.55, -0.45, 0.03), -0.05),
          **dict(THRU, hips=((0.2, 0.0, -0.1), (0.0, 0.1, 0.1)), chest=(0.05, 0.1, 0.0))),
        None),
    "glance": shot(
        P(bat=((0.3, -0.2, 0.86), (0.0, -0.05, 0.9)), footL=((0.6, -0.12, 0.03), 0.6), **FRONT),
        P(bat=((0.24, -0.08, 1.0), (0.0, -0.45, 1.4)), footL=((0.6, -0.12, 0.03), 0.6),
          **dict(FRONT, hips=((0.2, 0.0, -0.13), (0.05, 0.3, 0.1)))),
        None),
    "late_cut": shot(
        P(bat=((0.0, -0.45, 1.02), (-1.0, 0.0, -0.3)), footR=((-0.16, -0.42, 0.03), -0.35), footL=((0.22, -0.22, 0.03), 0.1),
          elbowL=(0.4, -0.6, 1.3), elbowR=(-0.3, -0.7, 1.0), **dict(BACKFOOT, chest=(0.05, -0.2, 0.0), head=(0.1, 1.0, 0.0))),
        P(bat=((-0.12, -0.45, 0.92), (-1.05, 0.0, -0.95)), footR=((-0.16, -0.42, 0.03), -0.35), footL=((0.22, -0.22, 0.03), 0.1),
          elbowL=(0.3, -0.8, 1.2), elbowR=(-0.4, -0.7, 1.0), **dict(BACKFOOT, chest=(0.05, -0.3, 0.0), head=(0.1, 1.2, 0.0))),
        None),
    "punch": shot(
        P(bat=((0.2, -0.36, 1.02), (0.0, -0.06, -0.15)), elbowL=(0.6, -0.4, 1.4), elbowR=(-0.1, -0.6, 1.1), **PUNCH_FEET, **BACK_UP),
        P(bat=((0.3, -0.32, 1.3), (0.0, -1.25, -0.2)), elbowL=(0.7, -0.3, 1.6), elbowR=(0.1, -0.6, 1.3), **PUNCH_FEET, **BACK_UP),
        None),
    "back_def": shot(
        P(bat=((0.2, -0.3, 1.05), (0.0, 0.1, 0.0)), elbowL=(0.5, -0.3, 1.5), elbowR=(-0.2, -0.5, 1.1),
          **PUNCH_FEET, **dict(BACK_UP, head=(0.3, 0.8, 0.1))),
        P(bat=((0.2, -0.3, 1.05), (0.0, 0.12, 0.0)), elbowL=(0.5, -0.3, 1.5), elbowR=(-0.2, -0.5, 1.1),
          **PUNCH_FEET, **dict(BACK_UP, head=(0.3, 0.8, 0.1))),
        None),
    "hook": shot(
        P(bat=((0.1, -0.25, 1.45), (-1.55, 0.0, 0.35)), footR=((-0.3, -0.28, 0.03), 1.3), footL=((0.12, 0.05, 0.03), 1.3),
          elbowL=(0.4, -0.5, 1.6), elbowR=(-0.2, -0.6, 1.4),
          **dict(BACKFOOT, hips=((-0.08, -0.05, -0.04), (-0.05, 0.4, 0.0)), chest=(-0.05, 0.3, 0.0), head=(-0.05, 0.5, 0.0))),
        P(bat=((-0.05, 0.2, 1.65), (-1.7, 0.0, 2.9)), footR=((-0.3, -0.28, 0.06), 1.6), footL=((0.12, 0.05, 0.03), 1.3),
          elbowL=(0.4, 0.4, 1.7), elbowR=(0.1, -0.4, 1.6),
          **dict(BACKFOOT, hips=((-0.08, 0.0, -0.04), (-0.05, 1.0, 0.0)), chest=(-0.05, 0.8, 0.0), head=(-0.05, 0.3, 0.0))),
        None),
    "upper_cut": shot(
        P(bat=((0.1, -0.42, 1.45), (-1.95, 0.0, 0.2)), footR=((-0.15, -0.4, 0.03), -0.3), footL=((0.22, -0.2, 0.03), 0.1),
          elbowL=(0.3, -0.7, 1.6), elbowR=(-0.3, -0.7, 1.4),
          **dict(BACKFOOT, hips=((-0.1, -0.05, -0.05), (-0.1, 0.15, 0.0)), spine=(-0.05, 0.1, 0.0), chest=(-0.05, 0.0, 0.0), head=(-0.1, 0.9, 0.0))),
        P(bat=((-0.05, -0.4, 1.65), (-2.3, 0.0, -0.7)), footR=((-0.15, -0.4, 0.03), -0.3), footL=((0.22, -0.2, 0.03), 0.1),
          elbowL=(0.3, -0.7, 1.8), elbowR=(-0.3, -0.7, 1.6),
          **dict(BACKFOOT, hips=((-0.1, -0.05, -0.05), (-0.12, 0.1, 0.0)), spine=(-0.1, 0.0, 0.0), chest=(-0.1, -0.1, 0.0), head=(-0.2, 1.0, 0.0))),
        None),
    "loft_off": shot(
        P(bat=((0.3, -0.38, 0.9), (0.0, -0.25, -0.4)), footL=((0.58, -0.4, 0.03), 0.1), **FRONT),
        P(bat=((0.15, -0.3, 1.6), (0.0, -2.9, -0.9)), footL=((0.58, -0.4, 0.03), 0.1),
          **dict(THRU, hips=((0.18, 0.0, -0.05), (-0.05, 0.2, 0.05)), chest=(-0.1, 0.2, 0.0), head=(-0.15, 0.6, 0.0))),
        None),
    "slog": shot(
        P(bat=((0.28, -0.2, 0.95), (-0.4, -0.25, 0.6)), footL=((0.5, 0.05, 0.03), 0.9), **FRONT),
        P(bat=((0.05, 0.25, 1.55), (-1.6, 0.0, 2.8)), footL=((0.5, 0.05, 0.03), 0.9),
          **dict(THRU, hips=((0.15, 0.05, -0.06), (-0.05, 0.8, 0.05)), chest=(-0.05, 0.7, 0.0), head=(-0.1, 0.3, 0.0),
                 elbowL=(0.3, 0.5, 1.8), elbowR=(0.1, -0.3, 1.6))),
        None),
    "sweep": shot(
        P(bat=((0.42, -0.4, 0.5), (-1.45, 0.0, 0.9)), **SWEEP_BODY),
        P(bat=((0.3, 0.05, 0.6), (-1.35, 0.0, 2.6)), **dict(SWEEP_BODY, hips=((0.12, -0.02, -0.4), (0.35, 0.45, 0.1)), chest=(0.15, 0.4, 0.0))),
        None),
    "slog_sweep": shot(
        P(bat=((0.42, -0.4, 0.55), (-1.5, 0.0, 1.0)), **SWEEP_BODY),
        P(bat=((0.2, 0.15, 1.15), (-2.0, 0.0, 2.7)),
          **dict(SWEEP_BODY, hips=((0.12, -0.02, -0.38), (0.2, 0.6, 0.1)), chest=(0.0, 0.6, 0.0), head=(0.1, 0.4, 0.0),
                 elbowL=(0.4, 0.4, 1.3), elbowR=(0.2, -0.3, 1.2))),
        None),
    "rev_sweep": shot(
        P(bat=((0.42, -0.3, 0.5), (-1.45, 0.0, 1.75)), **SWEEP_BODY),
        P(bat=((0.3, -0.55, 0.55), (-1.45, 0.0, -0.3)), **dict(SWEEP_BODY, hips=((0.12, -0.02, -0.4), (0.35, -0.1, 0.1)), chest=(0.15, -0.2, 0.0))),
        None),
    "scoop": shot(
        P(bat=((0.35, -0.3, 0.55), (0.0, -1.25, 0.0)), **SCOOP_BODY),
        P(bat=((0.2, -0.28, 0.95), (0.0, -2.6, 0.0)), **dict(SCOOP_BODY, head=(0.0, 0.6, 0.0))),
        None),
    "duck": [(0.0, BACKLIFT), (0.18, DUCK), (0.7, DUCK), (1.2, BAT_BASE)],
})

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
        export_def_bones=False, export_yup=True, export_apply=False, export_morph=False, export_vertex_color="ACTIVE",
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
        BAKE_AO = "--ao" in sys.argv
        reset()
        build_character("batsman")
        f, _ = build_character("fielder")
        f.location.x = 1.2
        cam = setup_preview_scene()
        render(os.path.join(PREVIEW, "rest_front.png"), cam, (0.6, -4.2, 1.2), (0.6, 0, 0.95))
        render(os.path.join(PREVIEW, "rest_three_q.png"), cam, (3.0, -3.0, 1.6), (0.6, 0, 0.95))
        render(os.path.join(PREVIEW, "rest_face.png"), cam, (0.5, -1.7, 1.55), (0.6, 0, 1.45))
        render(os.path.join(PREVIEW, "rest_back.png"), cam, (0.2, 2.6, 1.3), (0.2, 0, 0.9))
        render(os.path.join(PREVIEW, "rest_legs.png"), cam, (-0.6, -1.2, 0.6), (0.0, 0, 0.45))
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
