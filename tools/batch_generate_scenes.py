"""
batch_generate_scenes.py - Generate many procedural maps (+ BEV + USD) in one go.

    python tools/batch_generate_scenes.py --count 20                    # mixed themes
    python tools/batch_generate_scenes.py --count 10 --theme hospital --density 0.1 0.3
    python tools/batch_generate_scenes.py --count 5 --seed 100 --size 8 6 --no-usd
    python tools/batch_generate_scenes.py --count 10 --robot turtlebot4      # paths sized for it

Each map is deterministic in its seed:
    data/maps/generated/<prefix>_<seed>.json   map (editable in scene_editor.py)
    output/bev/<prefix>_<seed>/                BEV (+ height occupancy, Nav2 files)
    output/scenes/<prefix>_<seed>.usd          Isaac Sim scene (colliders, semantics)
    data/maps/generated/index.csv              metrics of every generated map
"""
import argparse
import csv
import json
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
import map_generator as mg  # noqa: E402
import bev_export as bev  # noqa: E402
import scene_builder as sb  # noqa: E402
import robots  # noqa: E402
from config import MAPS_DIR, SCENES_DIR  # noqa: E402

GEN_DIR = os.path.join(MAPS_DIR, "generated")


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--seed", type=int, default=1, help="first seed (seeds are consecutive)")
    ap.add_argument("--theme", choices=mg.THEMES + ("mixed",), default="mixed")
    ap.add_argument("--size", nargs=2, type=int, metavar=("NX", "NY"), default=None)
    ap.add_argument("--density", nargs=2, type=float, metavar=("LO", "HI"), default=(0.12, 0.3))
    ap.add_argument("--robot", default=None,
                    help="robot model in data/robots (default %s)" % robots.DEFAULT_ROBOT)
    ap.add_argument("--prefix", default="gen")
    ap.add_argument("--out", default=GEN_DIR)
    ap.add_argument("--no-bev", action="store_true")
    ap.add_argument("--no-usd", action="store_true")
    ap.add_argument("--skip-existing", action="store_true")
    return ap.parse_args()


def main():
    args = parse_args()
    os.makedirs(args.out, exist_ok=True)
    assets = mg.Assets()
    do_usd = not args.no_usd and sb.Usd is not None
    if not args.no_usd and sb.Usd is None:
        print("[!] OpenUSD not found (Isaac Sim / usd-core) -> skipping .usd")
    rows = []
    t_all = time.time()
    for k in range(args.count):
        seed = args.seed + k
        stem = "%s_%04d" % (args.prefix, seed)
        path = os.path.join(args.out, stem + ".json")
        if args.skip_existing and os.path.isfile(path):
            continue
        rng = random.Random(seed * 7919)
        theme = args.theme if args.theme != "mixed" else mg.THEMES[seed % len(mg.THEMES)]
        dens = rng.uniform(*args.density)
        t0 = time.time()
        md = mg.generate_map(seed, theme, size=tuple(args.size) if args.size else None,
                             density=dens, assets=assets, robot=args.robot)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(md, fh, indent=1)
        info = ""
        if not args.no_bev:
            st = bev.export_scene(md, stem=stem)
            info += " bev%s" % ("+occ" if st.get("occ") else "")
        if do_usd:
            st = sb.build_scene(md, os.path.join(SCENES_DIR, stem + ".usd"))
            info += " usd(%d col)" % st["colliders"]
        m = mg.map_metrics(md)
        m.update(stem=stem, seed=seed, density_target=round(dens, 3),
                 seconds=round(time.time() - t0, 1))
        rows.append(m)
        print("[%d/%d] %s %-11s %s rooms=%d items=%d density=%.3f (target %.2f) reach=%.2f%s"
              % (k + 1, args.count, stem, theme, m["grid"], m["rooms"], m["items"],
                 m["density"], dens, m["reachable_ratio"] or 0, info), flush=True)
    if rows:
        index = os.path.join(args.out, "index.csv")
        old = []
        if os.path.isfile(index):
            with open(index, encoding="utf-8") as fh:
                old = [r for r in csv.DictReader(fh) if r["stem"] not in {x["stem"] for x in rows}]
        fields = list(rows[0].keys())
        with open(index, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            for r in old + rows:
                w.writerow(r)
        print("Xong %d map (%.0f s) -> %s ; index: %s" % (len(rows), time.time() - t_all,
                                                         args.out, index))


if __name__ == "__main__":
    main()
