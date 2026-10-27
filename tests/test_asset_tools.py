"""Tests for tools/usd_deps.py and the pure helpers of tools/asset_library.py (no network)."""
import os
import struct
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "tools"))

import usd_deps as U  # noqa: E402


def _lz4_literal_block(data):
    """Minimal valid LZ4 block: one literal-only sequence."""
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    rest, ext = n - 15, bytearray()
    while rest >= 255:
        ext.append(255)
        rest -= 255
    ext.append(rest)
    return bytes([0xF0]) + bytes(ext) + data


def _fake_usdc(tokens, version=(0, 8, 0)):
    """Crate file with only a TOKENS section (enough for usdc_tokens)."""
    raw = b"\0".join(t.encode() for t in tokens) + b"\0"
    comp = b"\0" + _lz4_literal_block(raw)            # TfFastCompression, single chunk
    tok = struct.pack("<QQQ", len(tokens), len(raw), len(comp)) + comp
    start = 88
    toc = start + len(tok)
    head = b"PXR-USDC" + bytes(version) + b"\0" * 5 + struct.pack("<q", toc)
    head += b"\0" * (start - len(head))
    sec = b"TOKENS".ljust(16, b"\0") + struct.pack("<qq", start, len(tok))
    return head + tok + struct.pack("<Q", 1) + sec


class TestLz4:
    def test_literals(self):
        assert U.lz4_block_decompress(_lz4_literal_block(b"hello")) == b"hello"

    def test_long_literals(self):
        data = bytes(range(256)) * 3
        assert U.lz4_block_decompress(_lz4_literal_block(data)) == data

    def test_overlapping_match(self):
        # literal 'ab' then match offset 2 length 6 -> 'abababab'
        block = bytes([(2 << 4) | 2]) + b"ab" + struct.pack("<H", 2)
        assert U.lz4_block_decompress(block) == b"abababab"


class TestUsdc:
    def test_tokens_roundtrip(self):
        toks = ["", "World", "../Materials/MI_Wall.mdl", "textures/T_bc.png"]
        assert U.usdc_tokens(_fake_usdc(toks)) == toks

    def test_deps_from_usdc(self):
        data = _fake_usdc(["Geo", "../Materials/MI_Wall.mdl", "T_n.png", "not a path"])
        assert U.deps_from_bytes(data, "SM_Wall.usd") == ["../Materials/MI_Wall.mdl", "T_n.png"]


class TestTextFormats:
    def test_usda_refs(self):
        txt = b'#usda 1.0\nover "A" (references = @./sub/Chair.usd@)\n{ asset t = @tex/a.png@ }'
        assert U.deps_from_bytes(txt, "x.usda") == ["./sub/Chair.usd", "tex/a.png"]

    def test_mdl_textures_and_imports(self):
        mdl = b"""mdl 1.6;
import ::math::*;
import ::state::normal;
import ::OmniUe4Base::*;
import .::Local::*;
using ..::Shared import fn;
export material M() = OmniUe4Base(tex: texture_2d("./Textures/T_bc.png", ::tex::gamma_srgb));
"""
        deps = U.deps_from_bytes(mdl, "MI_A.mdl")
        assert "./Textures/T_bc.png" in deps
        assert "OmniUe4Base.mdl" in deps
        assert "Local.mdl" in deps
        assert "../Shared.mdl" in deps
        assert not any(d.startswith(("math", "state")) for d in deps)


class TestResolve:
    def test_relative(self):
        assert U.resolve("../Materials/M.mdl", "A/Props/x.usd") == "A/Materials/M.mdl"
        assert U.resolve("./T.png", "A/B/x.mdl") == "A/B/T.png"

    def test_unfetchable(self):
        assert U.resolve("omniverse://host/a.usd", "x.usd") is None
        assert U.resolve("tex/a.<UDIM>.png", "x.usd") is None

    def test_http_passthrough(self):
        assert U.resolve("https://h/a.usd", "x.usd") == "https://h/a.usd"


class TestLibraryHelpers:
    def setup_method(self):
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
        import asset_library
        self.L = asset_library

    def test_family_isaac(self):
        f = self.L.family_key
        assert f("isaac", "SM_Gurney_01a.usd") == f("isaac", "SM_Gurney_01b_12.usd")
        assert f("isaac", "SM_Chair_01a.usd") != f("isaac", "SM_Chair_02a.usd")

    def test_family_name(self):
        f = self.L.family_key
        assert f("name", "Tables/Caprice/CapriceTable_A.usd") == \
            f("name", "Tables/Caprice/CapriceTable_Yin.usd")
        assert f("name", "Bookshelves/Fenton.usd") == f("name", "Bookshelves/Fenton_Var01.usd")
        assert f("name", "Bookshelves/Fenton.usd") != f("name", "Bookshelves/Ladue.usd")

    def test_family_folder(self):
        f = self.L.family_key
        assert f("folder", "Carts/UtilityCart_A/UtilityCart_A01_01.usd") == \
            f("folder", "Carts/UtilityCart_A/UtilityCart_A02_01.usd")

    def test_categorize(self):
        c = self.L.categorize
        assert c("Furniture/Chairs/Armchair") == "seating"
        assert c("SM_HospitalBed_01b") == "medical"
        assert c("Shelving/Racks/Rack_A") == "shelving"
        assert c("Shipping/Pallets/Wood/Block_A") == "pallet"
        assert c("Equipment/Carts/UtilityCart_A") == "cart"
        assert c("Tables/OakTableLarge") == "table"

    def test_lib_path(self):
        assert self.L.lib_path_for_key("Assets/ArchVis/X/Y.usd") == "nvidia/ArchVis/X/Y.usd"
