"""
asset_library.py - Curated multi-environment asset library (office / residential / hospital /
warehouse) assembled from NVIDIA's public asset server + Poly Haven (CC0).

    python tools/asset_library.py select [--budget-gb 20]  # scan sources, dedupe, crawl deps
                                                          #   -> data/asset_manifest.json
    python tools/asset_library.py fetch                    # download every file of the manifest
    python tools/asset_library.py check                    # verify all files are on disk
    python tools/asset_library.py sheet [--env office]     # thumbnail contact sheets for review

Selection = source rules (which folders / names) -> family dedupe (variants of the same model
collapse to one) -> per (env, category) caps -> overrides (data/asset_overrides.json)
-> dependency crawl (textures / materials / sublayers) -> size budget.

Files are mirrored with the same relative layout as on the server so internal references keep
working:  assets/library/nvidia/<key without 'Assets/'>  and  assets/library/polyhaven/<id>/...
NVIDIA content stays local (not versioned / not redistributed); assets are used unmodified.
"""
import argparse
import collections
import json
import os
import re
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
import nv_s3  # noqa: E402
import usd_deps  # noqa: E402
from config import (LIBRARY_DIR, ASSET_MANIFEST,  # noqa: E402
                    ASSET_OVERRIDES, STYLES)

CACHE_DIR = os.path.join(LIBRARY_DIR, "_cache")
LISTING_CACHE = os.path.join(CACHE_DIR, "listings")
SIZE_CACHE = os.path.join(CACHE_DIR, "sizes.json")
POLYHAVEN_API = "https://api.polyhaven.com"
ISAAC = "Assets/Isaac/5.1/Isaac/"
WORKERS = 16

LICENSE_NV = "NVIDIA Omniverse content license"
LICENSE_NV_LIMITED = "NVIDIA Omniverse - Limited Use Content (Isaac/Environments, unmodified)"
LICENSE_CC0 = "CC0 (Poly Haven)"

# ----------------------------------------------------------------------------
# Source rules
#   family: how variants collapse -> 'isaac' (strip instance/letter suffix), 'name'
#           (strip variant suffix), 'folder' (one per leaf folder: DigitalTwin families)
#   include/exclude: regex on the path relative to prefix
# ----------------------------------------------------------------------------
SOURCES = [
    dict(src="HOS", env="hospital", prefix=ISAAC + "Environments/Hospital/Props/",
         family="isaac", license=LICENSE_NV_LIMITED,
         include=r"(Bed|Gurney|WheelChair|Chair_0|Desk_|ReceptionDesk|Cabinet|MedShelf|"
                 r"ShelfSet|Shelf_0|SupplyCart|GasCart|Cart_01|Chart_Rack|SideTable|"
                 r"DrinksMachine|WaterDispenser|TrashCan|SM_Toilet\.|Washbasin|Scale_01|"
                 r"DisposalStand|MopSet|WetFloorSign)",
         exclude=r"^Geo_"),
    dict(src="WH", env="warehouse", prefix=ISAAC + "Environments/Simple_Warehouse/Props/",
         family="isaac", license=LICENSE_NV_LIMITED,
         include=r"(BarelPlastic|SM_CardBox[A-D]\.|CratePlastic_|PaletteA|PushcartA|"
                 r"FireExtinguisher|TrafficCone|WetFloorSign|BucketPlastic)"),
    dict(src="AV", env="office", prefix="Assets/ArchVis/Commercial/", family="name",
         license=LICENSE_NV, include=r".*"),
    dict(src="AV", env="residential", prefix="Assets/ArchVis/Residential/", family="name",
         license=LICENSE_NV,
         include=r"^(Furniture/|Appliances/(Dishwashers|Refrigerators|Oven)/|"
                 r"Lighting/Floor Lamps/|Plants/|Outdoors/Planters/|Decor/Clocks/Grandfather|"
                 r"Entertainment/GameRoom/(BilliardTable|ArcadeMachine)|Misc/Ladders/)",
         exclude=r"(Lemay(BackPillow|RollArm|Seat|SideArm|Wedge|_)|Furniture/Outdoors/|"
                 r"curtain_valance|_Variants|LivingRoom|Shelf_Pieces)"),
    dict(src="AV", env="warehouse", prefix="Assets/ArchVis/Industrial/", family="name",
         license=LICENSE_NV,
         include=r"^(Containers/|Pallets/|Racks/|Shelves/|Railing/|Piles/)"),
    dict(src="DT", env="warehouse", prefix="Assets/DigitalTwin/Assets/Warehouse/",
         family="folder", license=LICENSE_NV,
         include=r"^(Equipment/(Carts|Forklifts|Hand_Trucks|Pallet_Trucks|Fans/Pedestal|"
                 r"Compressors|Security/(Turnstile|BaggageScanner|ScannerDoor)|"
                 r"Ladders/(AlumStep_A|RollingScaffold|TiltAndRoll|Workplatform))|"
                 r"Facilities/(Cleaning|Recycling|Trash_Cans)|Furnishing/|"
                 r"Safety/(Barriers/(SafetyBollard|GuardRail|RetractableCrowdControl_A|"
                 r"ColumnProtector_A|RackProtector_B|SafetyRailing|WireSecurityRoom_A|"
                 r"PortableWarningPost)|Cones/(Traffic|Heavy-Duty)|"
                 r"Fire_Protection/(ABCFire|FireCabinet|FireExtinguisherStand)|"
                 r"Floor_Signs/(WetFloor_A|Warning_A|FoldingWarning))|Shelving/|"
                 r"Shipping/(Pallets|Wood_Crates|Cardboard_Boxes_on_Pallet)/|"
                 r"Storage/(Drums|IBC_Tanks|Totes|Containers|Bins|Boxes|Cases)/)",
         exclude=r"(ModularParts|/Conveyor)"),
]

POLYHAVEN = dict(src="PH", env="residential", license=LICENSE_CC0, resolution="1k",
                 top=("Furniture", "Appliances", "Plants"),
                 min_footprint_mm=300, min_height_mm=250)

# (env, category) -> max assets after family dedupe; default DEFAULT_CAP
DEFAULT_CAP = 10
CAPS = {
    ("office", "seating"): 16, ("office", "table"): 12, ("office", "storage"): 12,
    ("residential", "seating"): 16, ("residential", "table"): 14,
    ("residential", "storage"): 12, ("residential", "sofa"): 8, ("residential", "plant"): 8,
    ("residential", "appliance"): 6, ("residential", "lighting"): 4, ("residential", "bed"): 3,
    ("hospital", "medical"): 14, ("hospital", "seating"): 6, ("hospital", "storage"): 10,
    ("warehouse", "container"): 20, ("warehouse", "shelving"): 18, ("warehouse", "cart"): 16,
    ("warehouse", "safety"): 14, ("warehouse", "pallet"): 8, ("warehouse", "table"): 10,
    ("warehouse", "seating"): 6, ("warehouse", "equipment"): 10,
}

# keyword -> category (first match wins; matched on the lower-cased relative path + name)
CATEGORY_RULES = [
    ("medical", r"gurney|hospitalbed|wheelchair|medshelf|medicalcabinet|supplycart|gascart|"
                r"chart_rack|xray|disposalstand|scale_01"),
    ("bed", r"bed(?!side)|daybed"),
    ("table", r"console|sofatable|workbench|worktable"),
    ("equipment", r"ladder|scaffold|workplatform"),
    ("sofa", r"sofa|loveseat|couch|zag_|birch_"),
    ("seating", r"chair|stool|seat|bench|bleacher|ottoman|rocker|seating/"),
    ("lighting", r"lamp"),
    ("plant", r"plant|planter|yucca|succulent|anza|fluted"),
    ("appliance", r"fridge|refrigerator|dishwasher|stove|oven|drinksmachine|waterdispenser|"
                  r"arcade|fan|compressor|heater"),
    ("fixture", r"toilet|washbasin|sink|urinal"),
    ("safety", r"cone|barrier|bollard|guardrail|railing|rail_|fencing|extinguisher|fire|"
               r"turnstile|scanner|warning|wetfloor|crowdcontrol|protector|securityroom|ramp"),
    ("pallet", r"pallet(?!_asm)|palette"),
    ("cart", r"cart|trolley|wagon|handtruck|hand_truck|forklift|pallettruck|pallet_truck|"
             r"dolly|pushcart|scaffold|ladder|workplatform"),
    ("shelving", r"rack|shelving|bookshel|shelf|bulkstorage"),
    ("table", r"(?<!nes)table|desk|workbench|worktable|console|reception|podium|counter|conference|"
              r"tables/|billiard"),
    ("storage", r"cabinet|storage|hutch|file|locker|closet|dresser|unit|wardrobe|"
                r"contemporary|standard_|whitehome|dentist"),
    ("container", r"bin|tote|drum|barel|barrel|pail|ibc|tank|container|crate|box|case|"
                  r"bucket|trash|recycl|pile|jug"),
    ("decor", r"clock|vase|sculpture|statue|mirror|fountain"),
]


# ----------------------------------------------------------------------------
# Small utils
# ----------------------------------------------------------------------------
def categorize(text):
    t = text.lower()
    for cat, pat in CATEGORY_RULES:
        if re.search(pat, t):
            return cat
    return "misc"


def family_key(mode, rel):
    d, f = os.path.split(rel)
    stem = os.path.splitext(f)[0]
    if mode == "folder":
        return d
    if mode == "isaac":
        s = re.sub(r"_\d+$", "", stem)                 # scene instance copies: _12
        s = re.sub(r"_[A-Z]$", "", s)                  # variants: SM_BarelPlastic_A.._D
        return re.sub(r"(\d+)[a-z]$", r"\1", s)        # letter variants: _01a/_01b
    s = re.sub(r"_?Var\d+$", "", stem)
    for _ in range(2):
        s = re.sub(r"[_]?(?:[A-Z]\d*|\d+[a-z]?|Yin|Blue|Red|Black|DarkGreen|Yellow)$", "", s)
    return (d.split("/")[0] + "/" + s) if s else d


def _too_small(name, min_cm=30):
    """DigitalTwin names carry a size code (..._46x33x24cm_...): skip desk-top items."""
    m = re.search(r"_(\d+)x(\d+)x(\d+)cm", name)
    return bool(m) and max(int(m.group(1)), int(m.group(2))) < min_cm


def safe_id(s):
    return re.sub(r"[^A-Za-z0-9_]+", "_", s).strip("_")


def lib_path_for_key(key):
    """Server key -> path relative to LIBRARY_DIR."""
    return "nvidia/" + (key[len("Assets/"):] if key.startswith("Assets/") else key)


def _load_json(path, default):
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    return default


def _save_json(path, data, indent=1):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=indent, ensure_ascii=False)
    os.replace(tmp, path)


# ----------------------------------------------------------------------------
# Remote sizes (listings + HEAD fallback)
# ----------------------------------------------------------------------------
class Sizes:
    def __init__(self):
        self.map = _load_json(SIZE_CACHE, {})

    def add_listing(self, objs):
        for k, s in objs:
            self.map[k] = s

    def get(self, key):
        """Size of key, or -1 if it does not exist on the server."""
        if key in self.map:
            return self.map[key]
        try:
            with nv_s3._open(nv_s3.key_url(key), 60, method="HEAD") as r:
                v = int(r.headers.get("Content-Length", 0))
        except urllib.error.HTTPError as e:
            v = -1 if e.code in (403, 404) else None
        except Exception:
            v = None
        if v is not None:
            self.map[key] = v
        return -1 if v is None else v

    def save(self):
        _save_json(SIZE_CACHE, self.map, indent=None)


# ----------------------------------------------------------------------------
# Candidates
# ----------------------------------------------------------------------------
def nvidia_candidates(sizes):
    out = []
    for rule in SOURCES:
        objs = nv_s3.list_objects(rule["prefix"], LISTING_CACHE)
        sizes.add_listing(objs)
        inc, exc = re.compile(rule["include"]), re.compile(rule.get("exclude", r"(?!x)x"))
        for key, size in objs:
            rel = key[len(rule["prefix"]):]
            if not rel.lower().endswith(".usd") or re.search(
                    r"(^|/)(\.SubUSDs|materials|Materials|Textures|textures|SubUSDs)/", rel):
                continue
            if not inc.search(rel) or exc.search(rel):
                continue
            name = os.path.splitext(os.path.basename(rel))[0]
            if name.endswith("_Variants") or _too_small(name):
                continue
            d = os.path.dirname(key)
            out.append(dict(
                src=rule["src"], env=rule["env"], name=name, key=key, rel=rel,
                category=categorize(rel), family=rule["src"] + ":" + family_key(rule["family"], rel),
                root_mb=round(size / 1e6, 2), license=rule["license"],
                thumb=nv_s3.key_url("%s/.thumbs/256x256/%s.png" % (d, os.path.basename(key)))))
    return out


def polyhaven_candidates():
    cfg = POLYHAVEN
    data = json.loads(nv_s3.fetch_bytes(POLYHAVEN_API + "/assets?t=models"))
    out = []
    for aid, info in sorted(data.items()):
        cat_path = info.get("category") or ""
        if not cat_path.startswith(cfg["top"]):
            continue
        dims = info.get("dimensions") or [0, 0, 0]
        if max(dims[0], dims[1]) < cfg["min_footprint_mm"] or dims[2] < cfg["min_height_mm"]:
            continue
        rel = cat_path + "/" + aid
        out.append(dict(
            src="PH", env=cfg["env"], name=aid, key=aid, rel=rel,
            category=categorize(rel), family="PH:" + re.sub(r"_\d+$", "", aid).lower(),
            root_mb=0.0, license=cfg["license"], dims_m=[round(x / 1000.0, 3) for x in dims],
            thumb=info.get("thumbnail_url", "")))
    return out


def dedupe_and_cap(cands, overrides):
    excl = tuple(overrides.get("exclude", []))     # id prefixes (drop a whole family)
    force = set(overrides.get("include", []))
    keep_n = overrides.get("family_keep", {})
    caps = dict(CAPS)
    for k, v in overrides.get("caps", {}).items():
        env, cat = k.split("/")
        caps[(env, cat)] = v
    cat_over = overrides.get("category", {})

    for c in cands:
        c["id"] = safe_id("%s_%s" % (c["src"], c["name"]))
    # disambiguate ids
    seen = collections.Counter(c["id"] for c in cands)
    for c in cands:
        if seen[c["id"]] > 1:
            c["id"] = safe_id("%s_%s_%s" % (c["src"], os.path.dirname(c["rel"]).split("/")[-1],
                                            c["name"]))
        c["category"] = cat_over.get(c["id"], c["category"])

    fams = collections.defaultdict(list)
    for c in cands:
        if excl and c["id"].startswith(excl):
            continue
        fams[c["family"]].append(c)
    picked = []
    for fam, items in fams.items():
        items.sort(key=lambda c: (c["id"] not in force, c["root_mb"], len(c["name"]), c["name"]))
        n = keep_n.get(fam, 1)
        picked += items[:n] + [c for c in items[n:] if c["id"] in force]

    by_bucket = collections.defaultdict(list)
    for c in picked:
        by_bucket[(c["env"], c["category"])].append(c)
    out = []
    for bucket, items in sorted(by_bucket.items()):
        cap = caps.get(bucket, DEFAULT_CAP)
        # cheapest first, but round-robin over sources so one pack does not fill the bucket
        items.sort(key=lambda c: (c["id"] not in force, c["root_mb"], c["id"]))
        by_src = collections.defaultdict(collections.deque)
        for c in items:
            by_src[c["src"]].append(c)
        chosen = [c for c in items if c["id"] in force]
        while len(chosen) < cap and any(by_src.values()):
            for s in sorted(by_src):
                if by_src[s] and len(chosen) < cap:
                    c = by_src[s].popleft()
                    if c not in chosen:
                        chosen.append(c)
        out += chosen
    return sorted(out, key=lambda c: (c["env"], c["category"], c["id"]))


# ----------------------------------------------------------------------------
# Dependency crawl
# ----------------------------------------------------------------------------
_PARSE = (".usd", ".usda", ".usdc", ".mdl")


def crawl(root_keys, sizes, download_all=False, log=print):
    """Closure of every root over USD/MDL references.

    USD/MDL files are always downloaded (they must be parsed); other files only when
    download_all. Returns (closure: {root: set(keys)}, missing: {key: referrer}).
    """
    edges, exists, referrer = {}, {}, {}
    frontier = list(dict.fromkeys(root_keys))
    level = 0

    def dl(k):
        return nv_s3.download(nv_s3.key_url(k), os.path.join(LIBRARY_DIR, lib_path_for_key(k)),
                              sizes.map.get(k))
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        while frontier:
            level += 1
            for k, s in zip(frontier, ex.map(sizes.get, frontier)):
                exists[k] = s >= 0
            live = [k for k in frontier if exists[k]]
            list(ex.map(dl, [k for k in live if download_all or k.lower().endswith(_PARSE)]))
            nxt = []
            for k in live:
                edges[k] = []
                if not k.lower().endswith(_PARSE):
                    continue
                try:
                    with open(os.path.join(LIBRARY_DIR, lib_path_for_key(k)), "rb") as fh:
                        refs = usd_deps.deps_from_bytes(fh.read(), k)
                except Exception as e:
                    log("  parse error %s: %s" % (k, e))
                    continue
                for ref in refs:
                    p = usd_deps.resolve(ref, k)
                    if p and p.startswith(("http://", "https://")):
                        p = nv_s3.url_to_key(p)
                    if not p:
                        continue
                    edges[k].append(p)
                    referrer.setdefault(p, k)
                    if p not in exists:
                        nxt.append(p)
            frontier = [p for p in dict.fromkeys(nxt) if p not in exists]
            log("  level %d: %d file moi" % (level, len(live)))
    closure = {}
    for r in root_keys:
        seen, stack = set(), [r]
        while stack:
            k = stack.pop()
            if k in seen or not exists.get(k):
                continue
            seen.add(k)
            stack += edges.get(k, [])
        closure[r] = seen
    missing = {k: referrer.get(k) for k, ok in exists.items() if not ok}
    return closure, missing


def style_material_keys():
    """Server keys of the room-style MDL materials (config.STYLES), fetched with the library."""
    keys = set()
    for st in STYLES.values():
        for slot in ("wall", "floor", "ceiling"):
            if st.get(slot):
                keys.add("Assets/" + st[slot])
    return sorted(keys)


def is_builtin_missing(key):
    base = os.path.basename(key)
    return base.lower().endswith(".mdl") and (
        base[:-4] in usd_deps.MDL_BUILTIN or base.startswith(("Omni", "nvidia")))


# ----------------------------------------------------------------------------
# Poly Haven fetch
# ----------------------------------------------------------------------------
def polyhaven_files(aid, res):
    info = json.loads(nv_s3.fetch_bytes("%s/files/%s" % (POLYHAVEN_API, aid)))
    u = info["usd"][res]["usd"]
    root = os.path.basename(u["url"])
    files = {root: (u["url"], u["size"])}
    for rel, f in (u.get("include") or {}).items():
        files[rel] = (f["url"], f["size"])
    # The usdc can reference maps missing from 'include' (e.g. *_roughness_1k.exr): index every
    # file the API lists by basename so fetch can resolve them.
    by_name = {}

    def walk(o):
        if isinstance(o, dict):
            if "url" in o and "size" in o:
                by_name.setdefault(os.path.basename(o["url"]), (o["url"], o["size"]))
            for v in o.values():
                walk(v)
    walk(info)
    return root, files, by_name


# ----------------------------------------------------------------------------
# Commands
# ----------------------------------------------------------------------------
def cmd_select(args):
    overrides = _load_json(ASSET_OVERRIDES, {})
    sizes = Sizes()
    print("Quet nguon NVIDIA ...")
    cands = nvidia_candidates(sizes)
    print("  %d USD ung vien" % len(cands))
    print("Quet Poly Haven ...")
    ph = polyhaven_candidates()
    print("  %d model ung vien" % len(ph))
    sel = dedupe_and_cap(cands + ph, overrides)
    print("Sau loc trung + gioi han: %d asset" % len(sel))

    nv = [c for c in sel if c["src"] != "PH"]
    print("Crawl dependency (%d root) ..." % len(nv))
    closure, missing = crawl([c["key"] for c in nv] + style_material_keys(), sizes)
    sizes.save()

    users = collections.Counter(k for ks in closure.values() for k in ks)
    for c in nv:
        ks = closure[c["key"]]
        c["total_mb"] = round(sum(max(sizes.map.get(k, 0), 0) for k in ks) / 1e6, 2)
        c["unique_mb"] = round(sum(max(sizes.map.get(k, 0), 0) for k in ks
                                   if users[k] == 1) / 1e6, 2)
        c["files"] = len(ks)
    res = POLYHAVEN["resolution"]

    def ph_size(c):
        root, files, _ = polyhaven_files(c["key"], res)
        c["root"] = "polyhaven/%s/%s" % (c["key"], root)
        c["total_mb"] = c["unique_mb"] = round(sum(s for _, s in files.values()) / 1e6, 2)
        c["files"] = len(files)
        # some Poly Haven USDs point at absolute paths on their build server -> no textures
        refs = usd_deps.deps_from_bytes(nv_s3.fetch_bytes(files[root][0]), root)
        c["broken"] = any(r.startswith("/") or r[1:3] == ":/" for r in refs)
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(ph_size, [c for c in sel if c["src"] == "PH"]))
    for c in [c for c in sel if c.get("broken")]:
        print("  bo %s: texture tro duong dan tuyet doi" % c["id"])
        sel.remove(c)

    # budget: drop the assets with the most unique bytes from over-full buckets
    budget = args.budget_gb * 1e9
    all_keys = {k for ks in closure.values() for k in ks}

    def total():
        nvb = sum(max(sizes.map.get(k, 0), 0) for k in all_keys)
        return nvb + sum(c["total_mb"] * 1e6 for c in sel if c["src"] == "PH")
    t = total()
    print("Tong truoc ngan sach: %.2f GB" % (t / 1e9))
    min_keep = 3
    while t > budget:
        counts = collections.Counter((c["env"], c["category"]) for c in sel)
        cand = [c for c in sel if counts[(c["env"], c["category"])] > min_keep
                and c["id"] not in set(overrides.get("include", []))]
        if not cand:
            break
        worst = max(cand, key=lambda c: c["unique_mb"])
        sel.remove(worst)
        if worst["src"] != "PH":
            closure.pop(worst["key"], None)
            all_keys = {k for ks in closure.values() for k in ks}
        t = total()
        print("  bo %-40s (%.0f MB rieng) -> %.2f GB" % (worst["id"], worst["unique_mb"], t / 1e9))

    assets = []
    for c in sel:
        e = {k: c[k] for k in ("id", "src", "env", "category", "name", "family", "license",
                               "root_mb", "total_mb", "unique_mb", "files", "thumb")}
        if c["src"] == "PH":
            e["root"] = c["root"]
            e["polyhaven_id"] = c["key"]
            e["dims_m"] = c.get("dims_m")
        else:
            e["root"] = lib_path_for_key(c["key"])
            e["key"] = c["key"]
        assets.append(e)
    manifest = dict(
        version=1, budget_gb=args.budget_gb, polyhaven_resolution=res,
        total_gb=round(t / 1e9, 2), count=len(assets),
        missing_refs=sorted(k for k in missing if not is_builtin_missing(k)),
        materials=[lib_path_for_key(k) for k in style_material_keys()],
        assets=assets)
    _save_json(ASSET_MANIFEST, manifest)
    print_summary(manifest)


def print_summary(manifest):
    by = collections.defaultdict(lambda: [0, 0.0])
    for a in manifest["assets"]:
        b = by[(a["env"], a["category"])]
        b[0] += 1
        b[1] += a["unique_mb"]
    print("\n%-12s %-10s %5s" % ("env", "category", "n"))
    for (env, cat), (n, mb) in sorted(by.items()):
        print("%-12s %-10s %5d" % (env, cat, n))
    print("Tong: %d asset, ~%.2f GB" % (manifest["count"], manifest["total_gb"]))
    if manifest.get("missing_refs"):
        print("Tham chieu khong co tren server (%d), vd: %s" % (
            len(manifest["missing_refs"]), manifest["missing_refs"][:5]))


def cmd_fetch(args):
    manifest = _load_json(ASSET_MANIFEST, None)
    if not manifest:
        raise SystemExit("Chua co %s - chay 'select' truoc" % ASSET_MANIFEST)
    sizes = Sizes()
    nv = [a for a in manifest["assets"] if a["src"] != "PH"]
    print("Tai %d asset NVIDIA (va dependency) ..." % len(nv))
    closure, missing = crawl([a["key"] for a in nv] + style_material_keys(), sizes,
                             download_all=True)
    sizes.save()
    # drop files left by earlier selections (assets since excluded)
    keep = {os.path.normcase(os.path.join(LIBRARY_DIR, lib_path_for_key(k)))
            for ks in closure.values() for k in ks}
    nv_root = os.path.join(LIBRARY_DIR, "nvidia")
    removed = 0
    for dirpath, _, files in os.walk(nv_root, topdown=False):
        for f in files:
            p = os.path.join(dirpath, f)
            if os.path.normcase(p) not in keep:
                os.remove(p)
                removed += 1
        if dirpath != nv_root and not os.listdir(dirpath):
            os.rmdir(dirpath)
    if removed:
        print("Don %d file khong con thuoc thu vien" % removed)
    ph = [a for a in manifest["assets"] if a["src"] == "PH"]
    print("Tai %d asset Poly Haven ..." % len(ph))
    res = manifest.get("polyhaven_resolution", "1k")

    def fetch_ph(a):
        root, files, by_name = polyhaven_files(a["polyhaven_id"], res)
        base = os.path.join(LIBRARY_DIR, "polyhaven", a["polyhaven_id"])
        for rel, (url, size) in files.items():
            nv_s3.download(url, os.path.join(base, *rel.split("/")), size)
        with open(os.path.join(base, root), "rb") as fh:
            refs = usd_deps.deps_from_bytes(fh.read(), root)
        for ref in refs:
            rel = usd_deps.resolve(ref, root)
            if rel and not rel.startswith(("http", "..")) and                     not os.path.exists(os.path.join(base, *rel.split("/"))):
                hit = by_name.get(os.path.basename(rel))
                if hit:
                    nv_s3.download(hit[0], os.path.join(base, *rel.split("/")), hit[1])
    with ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(fetch_ph, ph))
    real = [k for k in missing if not is_builtin_missing(k)]
    if real:
        print("Canh bao: %d tham chieu khong co tren server, vd %s" % (len(real), real[:5]))
    return cmd_check(args)


def cmd_check(args):
    manifest = _load_json(ASSET_MANIFEST, None)
    if not manifest:
        raise SystemExit("Chua co %s" % ASSET_MANIFEST)
    bad = [a["id"] for a in manifest["assets"]
           if not os.path.isfile(os.path.join(LIBRARY_DIR, *a["root"].split("/")))]
    # local reference check of every downloaded USD/MDL
    broken = collections.Counter()
    for dirpath, _, files in os.walk(LIBRARY_DIR):
        if "_cache" in dirpath:
            continue
        for f in files:
            if not f.lower().endswith(_PARSE):
                continue
            p = os.path.join(dirpath, f)
            rel = os.path.relpath(p, LIBRARY_DIR).replace("\\", "/")
            try:
                refs = usd_deps.deps_from_bytes(open(p, "rb").read(), f)
            except Exception:
                broken["<parse error> " + rel] += 1
                continue
            for r in refs:
                q = usd_deps.resolve(r, rel)
                if q is None or q.startswith(("http://", "https://")):
                    continue
                if not os.path.exists(os.path.join(LIBRARY_DIR, *q.split("/"))) \
                        and not is_builtin_missing(q):
                    broken[q] += 1
    known_missing = {lib_path_for_key(k) for k in manifest.get("missing_refs", [])}
    broken = {k: v for k, v in broken.items() if k not in known_missing}
    print("Kiem tra %d asset: thieu root %d, tham chieu hong %d (khong tinh %d ref vang tu nguon)"
          % (len(manifest["assets"]), len(bad), len(broken), len(known_missing)))
    for b in bad[:10]:
        print("  thieu root:", b)
    for k, v in list(broken.items())[:10]:
        print("  thieu file: %s (%d ref)" % (k, v))
    return 0 if not bad and not broken else 1


def cmd_sheet(args):
    """Contact sheets (one PNG per env/category) to eyeball near-duplicates."""
    from PIL import Image, ImageDraw
    manifest = _load_json(ASSET_MANIFEST, None)
    out_dir = os.path.join(CACHE_DIR, "sheets")
    os.makedirs(out_dir, exist_ok=True)
    groups = collections.defaultdict(list)
    for a in manifest["assets"]:
        if args.env and a["env"] != args.env:
            continue
        groups[(a["env"], a["category"])].append(a)
    T, cols = 160, 6

    def thumb(a):
        p = os.path.join(CACHE_DIR, "thumbs", a["id"] + ".png")
        if not os.path.isfile(p):
            try:
                os.makedirs(os.path.dirname(p), exist_ok=True)
                data = nv_s3.fetch_bytes(a["thumb"], timeout=60)
                with open(p, "wb") as fh:
                    fh.write(data)
            except Exception:
                return None
        try:
            return Image.open(p).convert("RGB").resize((T, T))
        except Exception:
            return None
    paths = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for (env, cat), items in sorted(groups.items()):
            imgs = list(ex.map(thumb, items))
            rows = (len(items) + cols - 1) // cols
            sheet = Image.new("RGB", (cols * T, rows * (T + 14)), (255, 255, 255))
            d = ImageDraw.Draw(sheet)
            for i, (a, im) in enumerate(zip(items, imgs)):
                x, y = (i % cols) * T, (i // cols) * (T + 14)
                if im:
                    sheet.paste(im, (x, y))
                d.text((x + 2, y + T), a["id"][:26], fill=(0, 0, 0))
            p = os.path.join(out_dir, "%s_%s.png" % (env, cat))
            sheet.save(p)
            paths.append(p)
    print("\n".join(paths))


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select")
    s.add_argument("--budget-gb", type=float, default=20.0)
    sub.add_parser("fetch")
    sub.add_parser("check")
    s = sub.add_parser("sheet")
    s.add_argument("--env", default=None)
    args = ap.parse_args()
    rc = {"select": cmd_select, "fetch": cmd_fetch, "check": cmd_check,
          "sheet": cmd_sheet}[args.cmd](args)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
