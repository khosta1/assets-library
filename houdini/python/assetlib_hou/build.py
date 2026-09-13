"""Karma / MaterialX / Solaris node building.

PORTED, almost verbatim, from
`H:/3D/Maya/Scripts/Manager_tool/assets_manager/Assets_manager_var01.py`
(lines 400-1457), 2026-09-12. That file is a working Houdini shelf tool and
this is the half of it worth keeping: the component chain, the MaterialX
subnet, the opacity stencil, the VDB foliage proxy, the USD variant sets, the
node layout. Knowledge about Houdini, which the library has no opinion about.

What did NOT come across is the other half - `find_textures`, `find_3d_file`,
`_parse_categories`, `find_assets`, `_udimify`, `_TEX_SLOTS` - roughly a
thousand lines that re-derived, on every run, what a filename meant. That is
what `asset.json` already records, decided once at import with a human
watching. This module is handed the answers.

The internals still speak the shape the original spoke: a dict with "name",
"dir" and "file", and a textures map of
`{slot: (path, mtlx_input, dtype, colorspace, post_node)}`. Keeping that shape
is deliberate - it is what let a thousand lines cross unchanged, and a port
that rewrites everything is a port whose bugs are all new.

NO Qt in this file, at any level. It runs inside Houdini, and the options
dialog lives in `ui/import_houdini.py` on the library side.
"""

from __future__ import annotations

import re
from pathlib import Path

import hou

from assetlib import derived
from assetlib.model import Asset, expand, res_width

# Which loader a geometry file needs. USD goes in as a reference on a LOP;
# everything else is read by a SOP inside componentgeometry.
SOP_EXTS = {".fbx", ".obj", ".abc", ".glb", ".gltf"}
LOP_EXTS = {".usdz", ".usd", ".usdc", ".usda"}


def _hou_safe_name(raw):
    name = re.sub(r"[^a-zA-Z0-9_]", "_", str(raw))
    if name and name[0].isdigit(): name = "asset_" + name
    return name or "asset"

def _uname(parent, base):
    ex = {c.name() for c in parent.children()}
    n, i = base, 1
    while n in ex: n = f"{base}_{i}"; i += 1
    return n

def _to_hip(p):
    if p is None: return None
    abs_p = str(p).replace("\\", "/")
    try:
        hip_dir = hou.hscript("echo $HIP")[0].strip().replace("\\", "/")
        if hip_dir and abs_p.lower().startswith(hip_dir.lower()):
            return "$HIP/" + abs_p[len(hip_dir):].lstrip("/")
    except Exception: pass
    return abs_p

def _udimify(path_str):
    """If `path_str` is a UDIM tile (…name.1001.ext or …name_1001.ext), replace the
    4-digit UDIM number just before the extension with the <UDIM> token, so the
    mtlximage node loads the whole tile set. Non-UDIM paths are returned unchanged.
    Only a delimited 1xxx number immediately before the extension is treated as a
    UDIM id, to avoid matching resolutions like '_1024' mid-name."""
    if not path_str:
        return path_str
    return re.sub(r'([._])(1[0-9]{3})(\.[A-Za-z0-9]+)$', r'\1<UDIM>\3', path_str)

def build_in_houdini(asset):
    if asset.get("file"):
        file_path = Path(asset["file"]); ext = file_path.suffix.lower()
    else:
        raise RuntimeError("no geometry bound - asset.json names none")
    textures  = asset["textures"]
    node_name = _hou_safe_name(asset["name"])
    mat_name  = "MAT_" + node_name
    file_str  = _to_hip(file_path)
    prim_root    = "/" + node_name
    mat_prefix   = "/ASSET/mtl/"
    mat_usd_path = mat_prefix + mat_name
    stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")
    lop_geo = None
    if file_str and ext in SOP_EXTS:
        obj  = hou.node("/obj") or hou.node("/").createNode("objnet", "obj")
        geo  = obj.createNode("geo", _uname(obj, node_name))
        for ch in list(geo.children()): ch.destroy()
        fsop  = geo.createNode("file", "file1")
        fsop.parm("file").set(file_str)
        xform = geo.createNode("xform", "transform1")
        xform.setInput(0, fsop)
        xform.parmTuple("s").set((0.01, 0.01, 0.01))
        outn  = geo.createNode("null", "OUT")
        outn.setInput(0, xform)
        outn.setDisplayFlag(True); outn.setRenderFlag(True)
        imp = stage.createNode("sopimport", _uname(stage, node_name+"_import"))
        imp.parm("soppath").set(geo.path() + "/OUT")
        try: imp.parm("primpath").set(prim_root)
        except: pass
        lop_geo = imp
    elif file_str and ext in LOP_EXTS:
        sub = stage.createNode("sublayer", _uname(stage, node_name+"_sub"))
        sub.parm("filepath1").set(file_str)
        lop_geo = sub

    # -- Material library --
    mlib = stage.createNode("materiallibrary", _uname(stage, node_name+"_matlib"))
    mlib.parm("matpathprefix").set(mat_prefix)
    if lop_geo: mlib.setInput(0, lop_geo)

    # -- Karma MaterialX builder --
    mat = None
    try:
        import voptoolutils
        mat = voptoolutils._setupMtlXBuilderSubnet(
            subnet_node=None,
            destination_node=mlib,
            name=mat_name,
            mask=voptoolutils.KARMAMTLX_TAB_MASK,
            folder_label='Karma Material Builder',
            render_context='kma',
        )
    except Exception:
        pass
    if mat is None:
        for ntype in ('materialxbuilder', 'subnet'):
            try: mat = mlib.createNode(ntype, mat_name); break
            except: pass
    if mat is None:
        raise RuntimeError("Could not create MaterialX builder node")

    # -- mtlxstandard_surface --
    surface = mat.node('mtlxstandard_surface') or mat.node('mtlxstandard_surface1')
    if surface is None:
        for c in mat.children():
            if c.type().name() == 'mtlxstandard_surface':
                surface = c; break
    if surface is None:
        surface = mat.createNode('mtlxstandard_surface', 'mtlxstandard_surface1')
        surf_out = mat.node('surface_output') or mat.createNode('suboutput', 'surface_output')
        surf_out.setInput(0, surface, 0)

    # -- mtlxdisplacement (only when a displacement texture was found) --
    disp = None
    if 'disp' in textures:
        disp = mat.node('mtlxdisplacement') or mat.node('mtlxdisplacement1')
        if disp is None:
            for c in mat.children():
                if c.type().name() == 'mtlxdisplacement':
                    disp = c; break
        if disp is None:
            disp = mat.createNode('mtlxdisplacement', 'mtlxdisplacement1')
            disp_out = mat.node('displacement_output') or mat.createNode('suboutput', 'displacement_output')
            disp_out.setInput(0, disp, 0)
        try: disp.parm('scale').set(0.01)
        except: pass

    # -- Texture nodes --
    y = 6.0
    for slot, (tp, surf_in, dtype, cspace, post) in textures.items():
        try:
            img = mat.createNode('mtlximage', f'img_{slot}')
            img.parm('file').set(_udimify(_to_hip(tp)))
            try: img.parm('signature').set(dtype)
            except: pass
            try: img.parm('colorspace').set(cspace)
            except: pass
            img.setPosition([-8, y])
            last_node = img
        except Exception:
            y -= 2.5; continue

        if post == 'normalmap':
            try:
                nm = mat.createNode('mtlxnormalmap', f'nm_{slot}')
                nm.setInput(0, last_node, 0)
                nm.setPosition([-4, y])
                last_node = nm
            except Exception:
                pass

        if surf_in and surface is not None:
            try: surface.setNamedInput(surf_in, last_node, 0)
            except: pass
        elif slot == 'disp' and disp is not None:
            try: disp.setNamedInput('displacement', last_node, 0)
            except: pass

        y -= 2.5

    mat.layoutChildren()

    # -- Material assignment --
    asgn = stage.createNode("assignmaterial", _uname(stage, node_name+"_assign"))
    asgn.parm("primpattern1").set(prim_root + "//*")
    asgn.parm("matspecpath1").set(mat_usd_path)
    asgn.setInput(0, mlib)
    asgn.setDisplayFlag(True)
    print(f"[VC] DONE: {node_name}")


# ---------------------------------------------------------------------------
# KARMA COMPONENT BUILDER  (component-based MaterialX workflow)
# ---------------------------------------------------------------------------
def _setup_sop_geometry(geo_nd, file_str, make_vdb_proxy=False, isolate_name=None):
    """Build file -> xform -> unpack -> OUT chain inside componentgeometry/sopnet/geo
    and wire it to the existing 'default' output node.

    make_vdb_proxy=True -> build a vdbfrompolygons -> convertvdb chain off the
    render geo and wire that to the 'proxy' output (used for foliage, where the
    opacity-cut leaf cards make a poor proxy).

    isolate_name=<str> -> insert a blast that keeps only prims whose 'name' prim
    attribute equals this value, so this componentgeometry represents exactly one
    geometry variant (used by the variant-set build for multi-version assets)."""
    geo_network = geo_nd.node("sopnet/geo")
    if geo_network is None:
        return None

    fsop = geo_network.createNode("file", "import_file")
    try: fsop.parm("file").set(file_str)
    except: pass

    xform = geo_network.createNode("xform", "transform1")
    xform.setInput(0, fsop, 0)
    try: xform.parmTuple("s").set((0.01, 0.01, 0.01))
    except: pass

    unpack = geo_network.createNode("unpack", "unpack_geo")
    unpack.setInput(0, xform, 0)

    # Strip FBX-baked attributes (Cd / shop_materialpath / material_override /
    # path / etc.) that would otherwise override the MaterialX shading.
    # We KEEP the 'name' prim attribute so multiple variants (e.g. plant_A/B/C)
    # survive the USD import as separate, addressable prims in Solaris.
    # negate=1  ('Delete Non Selected') inverts the patterns to keep-patterns,
    # so empty fields = "keep nothing" = delete everything in that class,
    # "name" in primitive = "keep only name on prims",
    # and "uv" in vertex = "keep only uv on vertices".
    clean = geo_network.createNode("attribdelete", "clean_fbx_attribs")
    clean.setInput(0, unpack, 0)
    try: clean.parm("negate").set(1)
    except: pass
    try: clean.parm("ptdel").set("")
    except: pass
    try: clean.parm("vtxdel").set("uv")
    except: pass
    try: clean.parm("primdel").set("name")   # keep 'name' -> variants stay separate USD prims
    except: pass
    try: clean.parm("dtldel").set("")
    except: pass

    # For a variant build, isolate a single 'name' piece so this componentgeometry
    # holds exactly one geo variant (blast keeps the selected group, deletes rest).
    render_src = clean
    if isolate_name is not None:
        blast = geo_network.createNode("blast", "isolate_variant")
        blast.setInput(0, clean, 0)
        try: blast.parm("group").set("@name=%s" % isolate_name)
        except: pass
        try: blast.parm("grouptype").set(4)   # 4 = Primitives
        except: pass
        try: blast.parm("negate").set(1)      # keep the selected group, delete the rest
        except: pass
        render_src = blast

    out = geo_network.createNode("null", "OUT_geo")
    out.setInput(0, render_src, 0)
    out.setDisplayFlag(True)
    out.setRenderFlag(True)

    default_out = geo_network.node("default")
    if default_out is not None:
        try: default_out.setInput(0, out, 0)
        except: pass

    # Feed the proxy output so the USD payload's `proxy` purpose is populated.
    proxy_out = None
    for name in ("proxy", "lod1", "output1", "optional"):
        proxy_out = geo_network.node(name)
        if proxy_out is not None:
            break

    if proxy_out is not None:
        proxy_src = out
        if make_vdb_proxy:
            # Foliage proxy: the opacity-cut render mesh (loose leaf cards) makes a
            # poor proxy, so fill it into a VDB SDF and convert back to a simplified
            # watertight mesh -- a cheap blobby stand-in for the render geometry.
            vdb = geo_network.createNode("vdbfrompolygons", "proxy_vdb")
            vdb.setInput(0, out, 0)
            # Voxel size = geo height / 5 so it auto-scales to any asset. The
            # coarse divisor (was /20) yields a much lighter, blobbier proxy.
            try:
                vdb.parm("voxelsize").setExpression(
                    f'bbox("../{out.name()}", D_YSIZE) / 5', hou.exprLanguage.Hscript)
            except Exception:
                try: vdb.parm("voxelsize").set(0.01)
                except Exception: pass

            conv = geo_network.createNode("convertvdb", "proxy_convert")
            conv.setInput(0, vdb, 0)
            try: conv.parm("conversion").set("poly")
            except Exception: pass
            try: conv.parm("adaptivity").set(0.5)
            except Exception: pass
            proxy_src = conv

        try: proxy_out.setInput(0, proxy_src, 0)
        except: pass

    geo_network.layoutChildren()
    return out


# Cached so we only inspect the mtlximage menu once per Houdini session.
# Maps purpose ('srgb_texture' / 'none') -> token that's actually in the menu.
_CSPACE_CACHE = {}

def _resolve_colorspace(img_node, purpose):
    """Pick a colorspace token from img_node's `colorspace` menu that matches
    `purpose`. Returns the original purpose string as a last-resort fallback.

    Why: Karma's default config uses tokens like 'srgb_texture' / 'none'.
    With an ACES OCIO config those tokens don't exist; the menu lists things
    like 'Utility - sRGB - Texture' / 'sRGB - Texture' / 'Utility - Raw'.
    Setting the wrong token silently leaves the parm at 'auto' (file-extension
    guess), which mis-tags EXR/TIFF as linear and makes diffuse look dark.
    """
    if purpose in _CSPACE_CACHE:
        return _CSPACE_CACHE[purpose]

    p = img_node.parm('colorspace')
    if p is None:
        return purpose
    try:
        tokens = list(p.menuItems())
        labels = [l.lower() for l in p.menuLabels()]
    except Exception:
        return purpose

    # Prioritised candidates per purpose: Karma default first, then ACES variants
    if purpose == 'srgb_texture':
        candidates = [
            'srgb_texture',
            'sRGB - Texture',
            'Utility - sRGB - Texture',
            'Input - Generic - sRGB - Texture',
            'srgb_tx',
            'sRGB',
        ]
        # Fuzzy fallback: any menu label containing both 'srgb' AND 'texture'
        for i, lbl in enumerate(labels):
            if 'srgb' in lbl and ('texture' in lbl or 'tex' in lbl):
                candidates.append(tokens[i])
    elif purpose == 'none':
        candidates = ['none', 'raw', 'Raw', 'Utility - Raw', 'lin_rec709']
        for i, lbl in enumerate(labels):
            if lbl == 'raw' or lbl.endswith(' - raw') or lbl == 'utility - raw':
                candidates.append(tokens[i])
    else:
        candidates = [purpose]

    # First candidate that's actually in the menu wins
    for c in candidates:
        if c in tokens:
            _CSPACE_CACHE[purpose] = c
            return c

    _CSPACE_CACHE[purpose] = purpose
    return purpose


# mtlxstandard_surface input name -> mtlxopen_pbr_surface input name.
# Lets _TEX_SLOTS stay declared against standard_surface while we build an
# OpenPBR surface. Key change: translucency (transmission_color on
# standard_surface) is routed to subsurface_color so foliage/leaf translucency
# drives OpenPBR's subsurface scattering instead of transmission.
_STD_TO_OPENPBR_INPUT = {
    "base_color":         "base_color",
    "specular_roughness": "specular_roughness",
    "specular_color":     "specular_color",
    "metalness":          "base_metalness",
    "emission_color":     "emission_color",
    "opacity":            "geometry_opacity",
    "normal":             "geometry_normal",
    "transmission_color": "subsurface_color",
}


def _build_karma_mtlx(lib_nd, mat_name, textures, create_displacement=True, wire_opacity=True):
    """Create a Karma MaterialX Builder inside lib_nd and wire textures.

    wire_opacity=False  -> skip building the opacity image+wiring entirely
                          (caller will handle opacity via Karma stencil map instead)
    """
    safe_name = _hou_safe_name(mat_name)

    old = lib_nd.node(safe_name)
    if old:
        try: old.destroy()
        except: pass

    mat = None
    try:
        import voptoolutils
        mat = voptoolutils._setupMtlXBuilderSubnet(
            subnet_node=None,
            destination_node=lib_nd,
            name=safe_name,
            mask=voptoolutils.KARMAMTLX_TAB_MASK,
            folder_label='Karma Material Builder',
            render_context='kma',
        )
    except Exception:
        pass

    if mat is None:
        for ntype in ('materialxbuilder', 'subnet'):
            try:
                mat = lib_nd.createNode(ntype, safe_name); break
            except: pass

    if mat is None:
        raise RuntimeError("Could not create Karma MaterialX Builder node")

    # -- mtlxopen_pbr_surface --
    # The Karma builder ships a default mtlxstandard_surface wired to the surface
    # suboutput. Swap it for an OpenPBR surface, reusing that same suboutput so
    # the material keeps a valid surface output.
    surface = None
    for c in mat.children():
        if c.type().name() == 'mtlxopen_pbr_surface':
            surface = c; break

    if surface is None:
        std = None
        for c in mat.children():
            if c.type().name() == 'mtlxstandard_surface':
                std = c; break

        # Find the suboutput the surface currently feeds (follow std's output
        # connection, else fall back to a node named/typed like the output).
        surf_out, surf_out_idx = None, 0
        if std is not None:
            for conn in std.outputConnections():
                surf_out     = conn.outputNode()
                surf_out_idx = conn.inputIndex()
                break
        if surf_out is None:
            surf_out = mat.node('surface_output')
        if surf_out is None:
            for c in mat.children():
                if c.type().name() == 'suboutput':
                    surf_out = c; break

        try:
            surface = mat.createNode('mtlxopen_pbr_surface', 'mtlxopen_pbr_surface1')
            if surf_out is None:
                surf_out = mat.createNode('suboutput', 'surface_output')
            surf_out.setInput(surf_out_idx, surface, 0)
        except Exception:
            surface = std   # OpenPBR node unavailable -> keep the standard surface

        # Drop the now-orphaned standard surface (only if we actually swapped).
        if (std is not None and surface is not None
                and surface.type().name() == 'mtlxopen_pbr_surface'):
            try: std.destroy()
            except Exception: pass

    # -- mtlxdisplacement (only if disp texture present and enabled) --
    disp = None
    if create_displacement and 'disp' in textures:
        disp = mat.node('mtlxdisplacement') or mat.node('mtlxdisplacement1')
        if disp is None:
            for c in mat.children():
                if c.type().name() == 'mtlxdisplacement':
                    disp = c; break
        if disp is None:
            try:
                disp = mat.createNode('mtlxdisplacement', 'mtlxdisplacement1')
                disp_out = mat.node('displacement_output') or mat.createNode('suboutput', 'displacement_output')
                disp_out.setInput(0, disp, 0)
            except Exception:
                pass
        if disp is not None:
            try: disp.parm('scale').set(0.01)
            except: pass

    if surface is None:
        mat.layoutChildren()
        return mat

    # Sensible surface defaults (OpenPBR param names) — Karma's MaterialX
    # defaults can steal energy from diffuse via Fresnel and make textured
    # base_color look darker than expected. These tame it. Any roughness/specular
    # texture found later will override these via setNamedInput().
    defaults = [('base_weight', 1.0), ('specular_weight', 0.5),
                ('specular_roughness', 0.5)]

    # If a translucency texture is detected, drive OpenPBR subsurface: turn ON
    # subsurface_weight and flag the surface thin-walled (single-sided) so Karma
    # cuts the energy correctly for leaves/foliage. The texture itself is wired
    # into subsurface_color elsewhere.
    if 'translucency' in textures:
        defaults += [('subsurface_weight', 0.5), ('geometry_thin_walled', 1)]

    for pname, pval in defaults:
        p = surface.parm(pname)
        if p is not None:
            try: p.set(pval)
            except Exception: pass

    # -- Texture nodes --
    y = 6.0
    for slot, (tp, surf_in, dtype, cspace, post) in textures.items():
        if slot == 'opacity' and not wire_opacity:
            continue  # opacity handled via rendergeometrysettings stencil map
        try:
            img = mat.createNode('mtlximage', f'img_{slot}')
            img.parm('file').set(_udimify(_to_hip(tp)))
            try: img.parm('signature').set(dtype)
            except: pass
            try: img.parm('colorspace').set(_resolve_colorspace(img, cspace))
            except: pass
            img.setPosition([-8, y])
            last_node = img
        except Exception:
            y -= 2.5; continue

        if post == 'normalmap':
            try:
                nm = mat.createNode('mtlxnormalmap', f'nm_{slot}')
                nm.setInput(0, last_node, 0)
                nm.setPosition([-4, y])
                last_node = nm
            except Exception:
                pass

        if surf_in and surface is not None:
            pbr_in = _STD_TO_OPENPBR_INPUT.get(surf_in, surf_in)
            try: surface.setNamedInput(pbr_in, last_node, 0)
            except: pass
        elif slot == 'disp' and disp is not None:
            try: disp.setNamedInput('displacement', last_node, 0)
            except: pass

        y -= 2.5

    mat.layoutChildren()
    return mat


def _add_usd_rop(stage, last_node, asset_name):
    """Append a usd_rop LOP that saves the chain to $HIP/usd/assets/<name>/<name>.usdc"""
    safe = _hou_safe_name(asset_name)
    rop = stage.createNode("usd_rop", _uname(stage, safe + "_save_usd"))
    if last_node is not None:
        try: rop.setInput(0, last_node, 0)
        except Exception: pass

    out_path = f"$HIP/usd/assets/{safe}/{safe}.usdc"
    for pname in ("lopoutput", "outputfile", "file", "filename"):
        p = rop.parm(pname)
        if p is not None:
            try: p.set(out_path); break
            except Exception: pass

    style_p = rop.parm("savestyle")
    if style_p is not None:
        try: style_p.set("flattenstage")
        except Exception: pass

    return rop


def _add_opacity_stencil(stage, last_node, opacity_path, prim_pattern, asset_name):
    """Create a rendergeometrysettings LOP that applies the opacity texture as
    Karma's object stencil map, so Karma cuts out leaves/foliage without the cost
    of a real opacity input on the surface shader.

    In the SOP component build this sits right after componentgeometry (see
    _build_sop_karma_component), which keeps componentoutput as the terminal node.
    """
    if opacity_path is None:
        return last_node

    op_stem = re.sub(r'[^a-zA-Z0-9_]', '_', Path(opacity_path).stem)
    safe    = _hou_safe_name(asset_name)
    rgs     = stage.createNode("rendergeometrysettings",
                               _uname(stage, f"rgs_{safe}_{op_stem}"))
    try: rgs.setInput(0, last_node, 0)
    except Exception: pass

    try: rgs.parm("primpattern").set(prim_pattern)
    except Exception: pass

    # Turn the stencil-map property ON. Its control menu must be "set" -- the
    # default "none" writes the map but ignores it. Parm name is the encoded
    # Karma object property; keep the older alias as a fallback.
    for pname in ("xn__primvarskarmaobjectstencilmap_control_e1bfg",
                  "karma_stencilmap_set"):
        ctl_p = rgs.parm(pname)
        if ctl_p is not None:
            try:
                toks = ctl_p.menuItems()
                ctl_p.set('set' if 'set' in toks else 0)
            except Exception:
                pass
            break

    # Stencil-map file path
    for pname in ("xn__primvarskarmaobjectstencilmap_dobfg", "karma_stencilmap"):
        val_p = rgs.parm(pname)
        if val_p is not None:
            try: val_p.set(_to_hip(opacity_path)); break
            except Exception: pass

    return rgs


def _add_result_reference(stage, out_nd, asset_name):
    """Add a standalone `reference` LOP that loads the USD componentoutput writes
    to disk, so the saved result can be previewed quickly in the viewport.

    It reads componentoutput's own `lopoutput` path, so it always points at
    wherever that node will save. NOTE: the file only exists after you click
    'Save to Disk' on the componentoutput -- until then this preview is empty.
    """
    safe = _hou_safe_name(asset_name)

    # Resolve the exact file componentoutput will write ($HIP/usd/assets/.../*.usd).
    out_path = None
    p = out_nd.parm("lopoutput")
    if p is not None:
        try: out_path = p.eval()
        except Exception: out_path = None

    ref = None
    for ntype in ("reference::2.0", "reference"):
        try:
            ref = stage.createNode(ntype, _uname(stage, safe + "_preview"))
            break
        except Exception:
            ref = None
    if ref is None:
        return None

    # Standalone (no input) so it shows ONLY the saved file, not the live stage.
    if out_path:
        for pname in ("filepath1", "reffilepath1", "file", "filepath"):
            fp = ref.parm(pname)
            if fp is not None:
                try: fp.set(_to_hip(out_path)); break
                except Exception: pass

    # Sit it to the right of componentoutput and make it the displayed node so the
    # saved result is what you see.
    try:
        pos = out_nd.position()
        ref.setPosition([pos[0] + 3.0, pos[1] - 1.0])
    except Exception: pass
    try: ref.setDisplayFlag(True)
    except Exception: pass

    return ref


def _distinct_variant_names(file_str):
    """Cook a throwaway file->unpack once and return the distinct prim 'name'
    attribute values (order preserved). Used to decide whether an asset holds
    multiple geometry variants. Returns [] when there is no 'name' attribute.

    The probe is built in /obj, read, then destroyed -- no trace is left behind.
    """
    obj = hou.node("/obj") or hou.node("/").createNode("objnet", "obj")
    tmp = None
    try:
        tmp = obj.createNode("geo", _uname(obj, "vc_name_probe"))
        for ch in list(tmp.children()):
            try: ch.destroy()
            except Exception: pass
        f = tmp.createNode("file", "probe_file")
        try: f.parm("file").set(file_str)
        except Exception: pass
        u = tmp.createNode("unpack", "probe_unpack")
        u.setInput(0, f, 0)
        u.setDisplayFlag(True); u.setRenderFlag(True)
        names = []
        try:
            g = u.geometry()
            if g is not None and g.findPrimAttrib("name") is not None:
                seen = set()
                for v in g.primStringAttribValues("name"):
                    if v and v not in seen:
                        seen.add(v); names.append(v)
        except Exception:
            pass
        return names
    except Exception:
        return []
    finally:
        if tmp is not None:
            try: tmp.destroy()
            except Exception: pass


def _build_sop_karma_component_variants(stage, asset, file_str, textures,
                                        variant_names, opacity_mode="none",
                                        displacement=False):
    """Component build with a USD geometry variant set: one componentgeometry per
    distinct prim 'name' value, collected by a componentgeometryvariants LOP.

    Chosen when the imported asset has >1 named piece (e.g. grass OL, OL_001...).
    All variants share ONE material (same textures). Variant set name is derived
    from the asset name and stays constant across every variant; only the per-
    input 'Geo Variant Name' changes -- that is the golden rule for variant sets.

    Node order:
        componentgeometry[V0] -\\
        componentgeometry[V1] --> componentgeometryvariants -> [rgs] -> componentmaterial -> componentoutput
             ...              -/         (variantset=asset)    materiallibrary --^
    """
    node_name  = _hou_safe_name(asset["name"])
    mat_name   = "MAT_" + node_name
    variantset = node_name                       # derived from asset, constant across variants
    make_proxy = ('opacity' in textures)

    # -- one componentgeometry per variant, each isolating its 'name' piece --
    geo_nodes = []
    for vname in variant_names:
        cg = stage.createNode("componentgeometry",
                              _uname(stage, node_name + "_geo_" + _hou_safe_name(vname)))
        _setup_sop_geometry(cg, file_str, make_vdb_proxy=make_proxy, isolate_name=vname)
        # "Geo Variant Name" (Advanced tab) -> this input's variant name. Its
        # internal id is 'variantname'; fall back defensively, and even if the
        # set fails the node name carries the variant name as the doc's default.
        for pn in ("variantname", "geovariantname", "variant_name"):
            p = cg.parm(pn)
            if p is not None:
                try: p.set(vname); break
                except: pass
        geo_nodes.append(cg)

    # -- collect the variants into one geometry variant set --
    cgv = stage.createNode("componentgeometryvariants",
                          _uname(stage, node_name + "_variants"))
    for i, cg in enumerate(geo_nodes):
        try: cgv.setInput(i, cg)
        except Exception: pass
    for pn in ("variantset", "variantsetname"):
        p = cgv.parm(pn)
        if p is not None:
            try: p.set(variantset); break
            except: pass

    lib_nd = stage.createNode("materiallibrary",   _uname(stage, node_name + "_matlib"))
    mtl_nd = stage.createNode("componentmaterial",  _uname(stage, node_name + "_mtl"))
    out_nd = stage.createNode("componentoutput",    _uname(stage, node_name + "_output"))

    try: lib_nd.parm("matpathprefix").set("/ASSET/mtl/")
    except: pass

    nodes = list(geo_nodes) + [cgv, lib_nd, mtl_nd, out_nd]

    # Opacity stencil map: inserted between the variants node and componentmaterial
    # (skipped for 'shader' and 'none' modes), same as the single-component build.
    geo_source = cgv
    if opacity_mode == "stencil" and 'opacity' in textures:
        op_path = textures['opacity'][0]
        rgs = _add_opacity_stencil(stage, cgv, op_path, "/ASSET/geo/render", asset["name"])
        if rgs is not cgv:
            geo_source = rgs
            nodes.append(rgs)

    mtl_nd.setInput(0, geo_source)
    mtl_nd.setInput(1, lib_nd)
    out_nd.setInput(0, mtl_nd)

    # Tidy the graph: wrap the N componentgeometry + the variants collector into a
    # single subnet ("<asset>_geo_variants"), so /stage shows one clean box instead
    # of N+1 flat nodes. Done AFTER wiring so the cgv->downstream link is turned
    # into the subnet's output. Falls back to the flat layout if collapse fails.
    try:
        geo_unit = stage.collapseIntoSubnet(tuple(geo_nodes) + (cgv,),
                                            node_name + "_geo_variants")
        try: geo_unit.layoutChildren()   # tidy the collapsed nodes inside the subnet
        except Exception: pass
        nodes = [n for n in nodes if n not in geo_nodes and n is not cgv]
        nodes.insert(0, geo_unit)
    except Exception:
        pass

    # -- single shared material for every variant --
    wire_to_shader = (opacity_mode == "shader")
    create_disp    = displacement and ('disp' in textures)
    _build_karma_mtlx(lib_nd, mat_name, textures, create_disp, wire_opacity=wire_to_shader)
    mat_usd_path = "/ASSET/mtl/" + _hou_safe_name(mat_name)

    # Assign that one material to /ASSET/geo/render -- the variant set swaps the
    # geometry under this same prim path, so one assignment covers all variants.
    try:
        count_p = None
        for cn in ('nummaterials', 'materials', 'numentries', 'numassignments'):
            count_p = mtl_nd.parm(cn)
            if count_p is not None: break
        if count_p is not None:
            count_p.set(1)
            for pname in ('primitives1', 'primpattern1', 'primitivepath1'):
                p = mtl_nd.parm(pname)
                if p is not None:
                    p.set("/ASSET/geo/render"); break
            for pname in ('matpath1', 'matspecpath1', 'materialpath1', 'material1'):
                p = mtl_nd.parm(pname)
                if p is not None:
                    p.set(mat_usd_path); break
    except Exception:
        pass

    try: out_nd.setDisplayFlag(True)
    except: pass

    ref = _add_result_reference(stage, out_nd, asset["name"])
    if ref is not None:
        nodes.append(ref)

    print(f"[VC] Variants ({len(variant_names)}): {', '.join(variant_names)}")
    return nodes


def _build_sop_karma_component(stage, asset, file_path, opacity_mode="none",
                               displacement=False, make_variants=False):
    """Full component-based Karma MTLX build for SOP-importable assets.

    Node order:
        componentgeometry -> [rendergeometrysettings] -> componentmaterial -> componentoutput
                                                materiallibrary --^
        componentoutput  ~~>  reference (standalone preview of the saved USD)
    The optional rendergeometrysettings (opacity stencil map) is inserted right
    after componentgeometry, so componentoutput stays the terminal node and no
    separate usd_rop is needed -- componentoutput writes the component itself.
    A standalone reference node reads that written file back for a quick preview.

    opacity_mode:
      'none'    -> no opacity at all
      'stencil' -> rendergeometrysettings (Karma stencil map) inserted after
                   componentgeometry; opacity NOT wired into the surface shader
      'shader'  -> opacity texture wired into the surface shader; no stencil node
    displacement=True -> add mtlxdisplacement node inside the MaterialX builder
                         (only if a disp texture was found)
    make_variants=True -> if the geo has >1 distinct prim 'name', build a USD
                         geometry variant set instead of a single component.
                         Opt-in (off by default) -- see the import dialog checkbox.
    """
    node_name = _hou_safe_name(asset["name"])
    mat_name  = "MAT_" + node_name
    file_str  = _to_hip(file_path)
    textures  = asset["textures"]

    # Multi-variant gate: only when the user opted in AND the imported geo has >1
    # distinct prim 'name' value (e.g. grass OL, OL_001, ...). Otherwise fall
    # through to the normal single-component build below.
    variant_names = _distinct_variant_names(file_str) if make_variants else []
    if len(variant_names) > 1:
        return _build_sop_karma_component_variants(
            stage, asset, file_str, textures, variant_names,
            opacity_mode=opacity_mode, displacement=displacement)

    geo_nd = stage.createNode("componentgeometry", _uname(stage, node_name + "_geo"))
    lib_nd = stage.createNode("materiallibrary",   _uname(stage, node_name + "_matlib"))
    mtl_nd = stage.createNode("componentmaterial", _uname(stage, node_name + "_mtl"))
    out_nd = stage.createNode("componentoutput",   _uname(stage, node_name + "_output"))

    try: lib_nd.parm("matpathprefix").set("/ASSET/mtl/")
    except: pass

    # Foliage (opacity map present) gets a VDB-based proxy instead of reusing the
    # opacity-cut render mesh.
    _setup_sop_geometry(geo_nd, file_str, make_vdb_proxy=('opacity' in textures))

    nodes = [geo_nd, lib_nd, mtl_nd, out_nd]

    # Opacity stencil map: inserted between componentgeometry and
    # componentmaterial (skipped for 'shader' and 'none' modes).
    geo_source = geo_nd
    if opacity_mode == "stencil" and 'opacity' in textures:
        op_path = textures['opacity'][0]
        rgs = _add_opacity_stencil(stage, geo_nd, op_path, "/ASSET/geo/render", asset["name"])
        if rgs is not geo_nd:
            geo_source = rgs
            nodes.append(rgs)

    mtl_nd.setInput(0, geo_source)
    mtl_nd.setInput(1, lib_nd)
    out_nd.setInput(0, mtl_nd)

    # Wire opacity into the shader only when the user picked 'shader' mode
    wire_to_shader = (opacity_mode == "shader")
    create_disp    = displacement and ('disp' in textures)
    _build_karma_mtlx(lib_nd, mat_name, textures, create_disp, wire_opacity=wire_to_shader)
    mat_usd_path = "/ASSET/mtl/" + _hou_safe_name(mat_name)

    # Fill componentmaterial entry (single material per asset)
    try:
        count_p = None
        for cn in ('nummaterials', 'materials', 'numentries', 'numassignments'):
            count_p = mtl_nd.parm(cn)
            if count_p is not None: break
        if count_p is not None:
            count_p.set(1)
            for pname in ('primitives1', 'primpattern1', 'primitivepath1'):
                p = mtl_nd.parm(pname)
                if p is not None:
                    p.set("/ASSET/geo/render"); break
            for pname in ('matpath1', 'matspecpath1', 'materialpath1', 'material1'):
                p = mtl_nd.parm(pname)
                if p is not None:
                    p.set(mat_usd_path); break
    except Exception:
        pass

    # componentoutput is the terminal node (no usd_rop -- it writes the component)
    try: out_nd.setDisplayFlag(True)
    except: pass

    # Standalone preview: reference the USD componentoutput will save, so the
    # result can be viewed quickly (empty until it's actually saved to disk).
    ref = _add_result_reference(stage, out_nd, asset["name"])
    if ref is not None:
        nodes.append(ref)

    return nodes


def _build_usd_karma_reference(stage, asset, file_path, opacity_mode="none", displacement=False):
    """Lightweight USD reference + assignmaterial.

    opacity_mode:
      'none'    -> no opacity
      'stencil' -> rendergeometrysettings + Karma stencil map (opacity NOT in shader)
      'shader'  -> opacity wired into mtlxstandard_surface.opacity input
    displacement=True -> add mtlxdisplacement in the MaterialX builder
    """
    node_name = _hou_safe_name(asset["name"])
    mat_name  = "MAT_" + node_name
    file_str  = _to_hip(file_path)
    prim_root = "/" + node_name
    textures  = asset["textures"]

    # Create reference node (try modern reference::2.0, then plain reference, then sublayer)
    ref = None
    for ntype in ('reference::2.0', 'reference', 'sublayer'):
        try:
            ref = stage.createNode(ntype, _uname(stage, node_name + "_ref"))
            break
        except Exception:
            ref = None
    if ref is None:
        raise RuntimeError("Could not create reference / sublayer node for USD asset")

    for pname in ('filepath1', 'reffilepath1', 'file', 'filepath'):
        p = ref.parm(pname)
        if p is not None:
            try: p.set(file_str); break
            except: pass

    for pname in ('primpath', 'primpath1', 'refprimpath1'):
        p = ref.parm(pname)
        if p is not None:
            try: p.set(prim_root); break
            except: pass

    nodes = [ref]
    last  = ref

    if textures:
        lib_nd = stage.createNode("materiallibrary", _uname(stage, node_name + "_matlib"))
        try: lib_nd.parm("matpathprefix").set("/ASSET/mtl/")
        except: pass
        lib_nd.setInput(0, last)

        # Wire opacity into the shader only when the user picked 'shader' mode
        wire_to_shader = (opacity_mode == "shader")
        create_disp    = displacement and ('disp' in textures)
        _build_karma_mtlx(lib_nd, mat_name, textures, create_disp, wire_opacity=wire_to_shader)
        mat_usd_path = "/ASSET/mtl/" + _hou_safe_name(mat_name)

        asgn = stage.createNode("assignmaterial", _uname(stage, node_name + "_assign"))
        asgn.setInput(0, lib_nd)
        try: asgn.parm("primpattern1").set(prim_root + "//*")
        except: pass
        try: asgn.parm("matspecpath1").set(mat_usd_path)
        except: pass

        nodes.extend([lib_nd, asgn])
        last = asgn

    try: last.setDisplayFlag(True)
    except: pass

    # Stencil-map branch (skipped for 'shader' and 'none' modes)
    if opacity_mode == "stencil" and 'opacity' in textures:
        op_path  = textures['opacity'][0]
        prim_pat = prim_root + "//*"
        rgs = _add_opacity_stencil(stage, last, op_path, prim_pat, asset["name"])
        if rgs is not last:
            try: last.setDisplayFlag(False)
            except: pass
            try: rgs.setDisplayFlag(True)
            except: pass
            nodes.append(rgs)
            last = rgs

    usd_rop = _add_usd_rop(stage, last, asset["name"])
    nodes.append(usd_rop)

    return nodes


def build_karma_component(asset, opacity_mode="none", displacement=False, make_variants=False):
    """Build a Karma MaterialX setup for an asset.

    SOP-based assets (FBX/OBJ/ABC/GLB/GLTF) get the full component chain:
      componentgeometry -> componentmaterial -> componentoutput
                          materiallibrary --^

    USD assets get a lightweight: reference -> materiallibrary -> assignmaterial

    opacity_mode:
      'none'    -> no opacity wired anywhere
      'stencil' -> opacity texture set on rendergeometrysettings as Karma stencil map
                   (not wired into the surface shader)
      'shader'  -> opacity texture wired into mtlxstandard_surface.opacity input
                   (higher fidelity / soft alpha; no stencil node created)
    displacement=True -> add mtlxdisplacement node in the MaterialX builder
    make_variants=True -> build a USD geometry variant set for multi-'name' SOP
                         assets (opt-in; ignored for USD assets)
    """
    if asset.get("file"):
        file_path = Path(asset["file"]); ext = file_path.suffix.lower()
    else:
        raise RuntimeError("no geometry bound - asset.json names none")

    if file_path is None:
        raise RuntimeError(f"No 3D file found in {asset['dir']}")

    stage = hou.node("/stage") or hou.node("/").createNode("lopnet", "stage")

    # Snapshot existing children so we can place the new chain to their right
    existing = list(stage.children())

    if ext in LOP_EXTS:
        nodes = _build_usd_karma_reference(stage, asset, file_path,
                                            opacity_mode=opacity_mode,
                                            displacement=displacement)
    else:
        nodes = _build_sop_karma_component(stage, asset, file_path,
                                            opacity_mode=opacity_mode,
                                            displacement=displacement,
                                            make_variants=make_variants)

    # Lay out ONLY the new nodes as a connected graph (around origin)
    try: stage.layoutChildren(items=nodes)
    except Exception: pass

    # Shift the new chain so its left edge sits to the right of existing nodes
    if existing and nodes:
        try:
            right_edge = max(c.position()[0] for c in existing) + 4.0
            min_new_x  = min(n.position()[0] for n in nodes)
            shift = right_edge - min_new_x
            if shift > 0:
                for n in nodes:
                    pos = n.position()
                    n.setPosition([pos[0] + shift, pos[1]])
        except Exception:
            pass

    # Snap the standalone preview reference directly under the componentoutput.
    # layoutChildren scatters it (it has no input), so we place it last, after
    # everything else is positioned. LOP flow is top-to-bottom, so "after" = below.
    try:
        out_node  = next((n for n in nodes
                          if n.type().name() == 'componentoutput'), None)
        prev_node = next((n for n in nodes
                          if n.type().name().startswith('reference')
                          and not n.inputs()), None)
        if out_node is not None and prev_node is not None:
            ox, oy = out_node.position()
            prev_node.setPosition([ox, oy - 2.0])
    except Exception:
        pass

    print(f"[VC] Karma DONE: {asset['name']}")
    # The original ended here, returning None - it was called for effect from a
    # menu handler that ignored the result. The library reports what it built,
    # so the nodes come back.
    return nodes




# ---------------------------------------------------------------------------
# THE SEAM - asset.json in, the shape above out
# ---------------------------------------------------------------------------

BIGGEST = "__biggest__"
ALL_VARIANTS = "__all__"


def texture_rels(asset: Asset, opts: dict) -> dict:
    """`{slot: package-relative texture}` this build will use, before any baking.

    Factored out because two things need the same answer and must not drift:
    `textures_for()` binds them, and the pre-bake window converts them. A list
    that disagreed would mean baking one size and rendering another - and the
    bake would look like it had silently done nothing.
    """
    opts = opts or {}
    want = opts.get("res") or BIGGEST
    out = {}
    for slot, rel in (asset.textures or {}).items():
        # A specific size was asked for and this slot has it. Otherwise the
        # binding already names the biggest, because commit promoted it.
        sizes = (asset.resolutions or {}).get(slot) or {}
        out[slot] = sizes[want] if (want != BIGGEST and want in sizes) else rel
    return out


def textures_for(asset: Asset, asset_dir: Path, cfg, opts: dict) -> dict:
    """`{slot: (path, mtlx_input, dtype, colorspace, post_node)}` - the shape the
    ported builders expect, built from BINDINGS rather than from filenames.

    This is the whole point of the library standing between the two. The
    original walked the folder, lowercased every stem and raced twenty keyword
    lists on every run; the answers are now in asset.json, decided once with a
    person looking at them. Same tuple out, so nothing downstream changed.

    `mtlx_input`, `dtype`, `colorspace` and `post_node` come from
    texture_slots.json, which IS the table the original carried inline as
    _TEX_SLOTS. One copy now, and it is the one the importer already used.
    """
    by_key = {s["key"]: s for s in cfg.slots_cfg["slots"]}
    opts = opts or {}
    want = opts.get("res") or BIGGEST

    out = {}
    for slot, rel in texture_rels(asset, opts).items():
        spec = by_key.get(slot)
        if spec is None:
            continue

        # A baked .rat instead of the source, when one exists or can be made.
        #
        # This is the only place it has to happen, and it has to happen HERE
        # rather than in the shader builders: give Karma a .jpg and it converts
        # it itself, writing the result into tex/ beside the source, which is
        # how 60 orphan .rat files appeared in the library. Hand it a .rat and
        # there is nothing left to convert.
        #
        # Falling back to the source on every failure is the whole contract: no
        # Houdini converter, an unreadable texture, a conversion that times out
        # - all of them mean "render from the original", never "do not render".
        baked = None
        if opts.get("derived", True):
            try:
                if "<UDIM>" in rel:
                    baked = derived.ensure_udim(asset, asset_dir, rel,
                                                generate=opts.get("bake", True))
                else:
                    baked = derived.ensure(asset_dir, rel,
                                           generate=opts.get("bake", True))
            except Exception:                           # noqa: BLE001
                baked = None

        # UDIM: asset.json stores the token path, which is already the spelling
        # Houdini resolves. The original had to regex the tile back out of a
        # filename and guess whether a four-digit number was a tile or a
        # resolution; that guess is gone.
        out[slot] = (asset_dir / (baked or rel), spec.get("mtlx_input"),
                     spec.get("dtype"), spec.get("colorspace"),
                     spec.get("post_node"))
    return out


def geometry_for(asset: Asset, asset_dir: Path, opts: dict) -> list:
    """Every geometry to build, as [(variant_name_or_None, path)].

    A LIST, because "all variants" means all of them. It returned one path and
    built only the first, which looked like the variant had not imported when in
    fact it was sitting in the package unbuilt - the failure the whole variant
    dimension exists to prevent, reappearing one layer further on.

    Ordered primary-first, so a single-variant asset and an asset whose variant
    was chosen by hand both come back as a one-item list and the caller needs no
    special case.
    """
    entries = [e for e in (asset.representations or []) if e.get("file")]
    if not entries:
        raise RuntimeError(f"{asset.name}: asset.json binds no geometry")

    want = (opts or {}).get("variant") or ALL_VARIANTS
    if want != ALL_VARIANTS:
        chosen = [e for e in entries if e.get("variant") == want]
        entries = chosen or entries[:1]

    # One build per DISTINCT variant. Several formats of one variant are one
    # asset - componentgeometry takes a single file - so the primary wins there,
    # which is the same rule _promote_lod_geo already applied on the way in.
    seen, out = set(), []
    for entry in entries:
        variant = entry.get("variant")
        if variant in seen:
            continue
        seen.add(variant)
        out.append((variant, asset_dir / entry["file"]))
    return out


def _localize(asset: Asset, asset_dir: Path, cfg) -> Path:
    """Copy the package next to the hip file and return the copy's folder.

    The default is NOT this: a network that points into the library is what
    makes an asset shared rather than duplicated, and is the reason the library
    exists in one place. Localizing trades that for a scene that survives being
    handed to someone without the library, at the cost of a second copy of every
    texture - which for a four-resolution Megascans plant is not small.

    The package mirrors under $HIP keeping its library-relative shape, so
    `texture/concrete/concrete014` lands as `$HIP/library/texture/concrete/
    concrete014` and stays identifiable rather than becoming a loose folder.
    _to_hip() then rewrites the baked paths to $HIP/... on its own.
    """
    import shutil

    hip = hou.text.expandString("$HIP")
    if not hip or hip == "$HIP":
        raise hou.Error("$HIP is not set - save the hip file before localizing")

    # Whichever root holds it. relative_to(cfg.library) raised ValueError on a
    # downloaded asset, and "localize" is exactly the button someone presses on
    # one - it is the asset they do not have a permanent copy of.
    root = cfg.root_containing(asset_dir) or cfg.library
    rel = asset_dir.relative_to(root)
    dest = Path(hip) / root.name / rel
    for src in asset_dir.rglob("*"):
        if src.is_file():
            target = dest / src.relative_to(asset_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, target)
    return dest


def karma_component(asset: Asset, asset_dir: Path, cfg, opts: dict | None = None):
    """Build one asset. The only function the library side calls.

    Takes truth and a dict of choices; makes nodes. No dialogs, no menus, no
    filesystem walking - every decision was made in `ui/import_houdini.py`
    before this was reached.
    """
    opts = dict(opts or {})
    if opts.get("localize"):
        asset_dir = _localize(asset, asset_dir, cfg)

    def _build():
        return _build_all(asset, asset_dir, cfg, opts)

    # Bake first, then build - and when anything has to be baked, RETURN TO
    # HOUDINI in between. The conversion runs on a pool thread and the nodes
    # are made from an idle callback once it finishes.
    #
    # An earlier version baked here on the main thread behind a progress bar
    # that pumped Qt events. The bar animated and Houdini still froze, because
    # Qt's events are not Houdini's: its event loop cannot run while a Python
    # script is on the main thread, and pumping Qt does not hand control back.
    # Only returning does.
    #
    # The consequence is real and is not hidden: a build that had to bake
    # returns None, because the nodes do not exist yet.
    try:
        from .bakewindow import run_when_baked

        return run_when_baked(asset, asset_dir, opts, _build)
    except Exception as exc:                            # noqa: BLE001
        # Any failure in the deferring machinery falls back to the old
        # behaviour: bake inline inside textures_for() and build now. Slower
        # and it blocks, but it is correct and it returns nodes.
        print(f"[assetlib] deferred bake unavailable ({exc}); building inline")
        return _build()


def _build_all(asset: Asset, asset_dir: Path, cfg, opts: dict) -> list:
    """The build itself, with every texture assumed already baked.

    Split out so it can be called either directly or from an idle callback.
    Everything here touches `hou` and therefore only ever runs on the main
    thread.
    """
    textures = textures_for(asset, asset_dir, cfg, opts)
    built = []
    for variant, geo in geometry_for(asset, asset_dir, opts):
        # The variant goes in the NODE name, not just the file path. Two
        # componentoutputs called the same thing would be disambiguated by
        # _uname into x_output and x_output1, which says nothing about which
        # mesh is which.
        legacy = {
            "name": f"{asset.name}_{variant}" if variant else asset.name,
            "dir": str(asset_dir),
            "file": str(geo),
            # Shared deliberately: Megascans ships ONE texture set for both the
            # Big and the Small mesh, and the import recorded it once.
            "textures": textures,
        }
        nodes = build_karma_component(
            legacy,
            opacity_mode=opts.get("opacity", "none"),
            displacement=bool(opts.get("displacement")),
            make_variants=bool(opts.get("variant_set")),
        )
        built.extend(nodes or [])
    return built
