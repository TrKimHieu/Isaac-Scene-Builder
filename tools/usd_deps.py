"""
usd_deps.py - List the files a USD / MDL file depends on, in pure Python (no pxr).

Used by the asset-library tools to know which textures/materials/sublayers must be
downloaded next to a prop. Supports:
  - USDC (binary crate): reads the TOKENS section (LZ4-compressed) - asset paths are tokens.
  - USDA (text): @asset/path@ references.
  - MDL: texture_2d("...") + relative module imports (import .::Foo / using ..::Bar).

The result is a list of raw reference strings exactly as authored; use resolve() to turn
them into paths relative to the referencing file.
"""
import posixpath
import re
import struct

DEP_EXTS = (".usd", ".usda", ".usdc", ".usdz", ".mdl", ".png", ".jpg", ".jpeg",
            ".exr", ".hdr", ".tga", ".dds", ".tif", ".tiff", ".bmp", ".ktx")


# ----------------------------------------------------------------------------
# LZ4 block + TfFastCompression
# ----------------------------------------------------------------------------
def lz4_block_decompress(src, size_hint=0):
    """Decompress one raw LZ4 block (no frame header)."""
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]
        i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i + lit]
        i += lit
        if i >= n:                       # last sequence has literals only
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        ml = token & 15
        if ml == 15:
            while True:
                b = src[i]
                i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - off
        if off >= ml:
            dst += dst[start:start + ml]
        else:                            # overlapping copy
            for k in range(ml):
                dst.append(dst[start + k])
    return bytes(dst)


def tf_decompress(buf):
    """TfFastCompression: 1 byte chunk count (0 = single block), then [int32 size, block]*."""
    nchunks = buf[0]
    if nchunks == 0:
        return lz4_block_decompress(buf[1:])
    out, i = bytearray(), 1
    for _ in range(nchunks):
        (sz,) = struct.unpack_from("<i", buf, i)
        i += 4
        out += lz4_block_decompress(buf[i:i + sz])
        i += sz
    return bytes(out)


# ----------------------------------------------------------------------------
# USDC tokens
# ----------------------------------------------------------------------------
def usdc_tokens(data):
    """All tokens of a USDC crate file (list of str)."""
    if data[:8] != b"PXR-USDC":
        raise ValueError("not a USDC file")
    major, minor = data[8], data[9]
    (toc,) = struct.unpack_from("<q", data, 16)
    (nsec,) = struct.unpack_from("<Q", data, toc)
    sections = {}
    for k in range(nsec):
        off = toc + 8 + k * 32
        name = data[off:off + 16].split(b"\0", 1)[0].decode()
        start, size = struct.unpack_from("<qq", data, off + 16)
        sections[name] = (start, size)
    if "TOKENS" not in sections:
        return []
    start, _ = sections["TOKENS"]
    (ntok,) = struct.unpack_from("<Q", data, start)
    if (major, minor) < (0, 4):
        (nbytes,) = struct.unpack_from("<Q", data, start + 8)
        raw = data[start + 16:start + 16 + nbytes]
    else:
        _usize, csize = struct.unpack_from("<QQ", data, start + 8)
        raw = tf_decompress(data[start + 24:start + 24 + csize])
    toks = raw.split(b"\0")[:ntok]
    return [t.decode("utf-8", "replace") for t in toks]


# ----------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------
_USDA_REF = re.compile(r"@([^@\n]+)@")
_MDL_TEX = re.compile(r'texture_2d\(\s*"([^"]+)"')
_MDL_IMPORT = re.compile(r"^\s*import\s+([\w:.]+(?:::\*)?)\s*;", re.M)
_MDL_USING = re.compile(r"^\s*(?:export\s+)?using\s+([\w:.]+)\s+import\b", re.M)
# MDL standard / renderer-provided modules: never files next to the material.
MDL_BUILTIN = {"anno", "base", "debug", "df", "limits", "math", "scene", "state", "std",
               "tex", "nvidia", "alg", "adobe", "OmniPBR", "OmniPBR_ClearCoat", "OmniSurface",
               "OmniGlass", "OmniHair", "OmniSurfaceLite", "OmniPBRBase", "OmniVolumeDensity"}


def _mdl_modules(txt):
    """Module paths imported by an MDL file, e.g. '::OmniUe4Base', '.::Foo'."""
    mods = set(_MDL_USING.findall(txt))
    for m in _MDL_IMPORT.findall(txt):
        if m.endswith("::*"):
            mods.add(m[:-3])
        elif "::" in m.strip(":"):
            mods.add(m.rsplit("::", 1)[0])      # import ::mod::member
    out = set()
    for m in mods:
        first = m.lstrip(".:").split("::")[0]
        if first and first not in MDL_BUILTIN:
            out.add(m)
    return out


def _looks_like_file(s):
    s = s.strip()
    return bool(s) and s.lower().endswith(DEP_EXTS) and "\n" not in s and len(s) < 512


def _mdl_module_to_path(mod):
    """'.::Foo' -> 'Foo.mdl', '..::A::B' -> '../A/B.mdl', '::Foo' -> 'Foo.mdl'.

    Absolute modules are looked up next to the material (how the Isaac/ArchVis packs ship
    OmniUe4Base & co.); callers should treat a missing file as renderer-provided.
    """
    out = [".." if p == ".." else p for p in mod.split("::") if p not in (".", "")]
    return "/".join(out) + ".mdl"


def deps_from_bytes(data, filename):
    """Raw dependency strings referenced by one file's content."""
    low = filename.lower()
    if low.endswith(".mdl"):
        txt = data.decode("utf-8", "replace")
        found = _MDL_TEX.findall(txt)
        found += [_mdl_module_to_path(m) for m in _mdl_modules(txt)]
        return sorted(set(found))
    if data[:8] == b"PXR-USDC":
        cands = usdc_tokens(data)
    elif low.endswith((".usd", ".usda")):
        cands = _USDA_REF.findall(data.decode("utf-8", "replace"))
    else:
        return []
    return sorted({c.strip() for c in cands if _looks_like_file(c)})


def resolve(ref, parent):
    """Resolve a reference string relative to the parent file path (posix).

    Returns a normalized posix path, the URL itself for http(s) refs, or None for
    references that are not files we can fetch (omniverse://, MDL core modules, UDIM...).
    """
    ref = ref.strip().replace("\\", "/")
    if ref.startswith(("http://", "https://")):
        return ref
    if "://" in ref or "<UDIM>" in ref or "<UVTILE" in ref:
        return None
    if ref.startswith("/"):
        ref = ref.lstrip("/")
        base = ""
    else:
        base = posixpath.dirname(parent)
    return posixpath.normpath(posixpath.join(base, ref))
