"""
check_density_distribution.py - How dense / navigable is a set of maps?

    python tools/check_density_distribution.py                        # data/maps/generated/*.json
    python tools/check_density_distribution.py --maps "data/maps/*.json" --target 0.1 0.3

Per map (map_generator.map_metrics): furniture footprint / floor area (density), items per
10 m2, free space a robot fits in, share of it reachable from the spawn, doors, windows,
waypoints. Prints a table + summary per theme, writes output/density_report.csv and a
histogram output/density_hist.png, and lists outliers (density outside the target range,
reachable < --min-reach, rooms without a waypoint).
"""
import argparse
import csv
import glob
import json
import os
import statistics
import sys

from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(_HERE), "src"))
import map_generator as mg  # noqa: E402
from config import MAPS_DIR, OUTPUT_DIR  # noqa: E402

THEME_COL = {"office": (99, 102, 241), "hospital": (20, 184, 166), "warehouse": (217, 119, 6),
             "residential": (219, 39, 119), "": (148, 163, 184)}


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--maps", default=os.path.join(MAPS_DIR, "generated", "*.json"))
    ap.add_argument("--target", nargs=2, type=float, default=(0.08, 0.30), metavar=("LO", "HI"))
    ap.add_argument("--min-reach", type=float, default=0.85)
    ap.add_argument("--bins", type=int, default=12)
    ap.add_argument("--csv", default=os.path.join(OUTPUT_DIR, "density_report.csv"))
    ap.add_argument("--png", default=os.path.join(OUTPUT_DIR, "density_hist.png"))
    return ap.parse_args()


def histogram(rows, path, bins, lo_t, hi_t):
    """Stacked density histogram per theme (Pillow only) with the target band shaded."""
    W, H, M = 900, 420, 50
    vals = [r["density"] for r in rows]
    top = max(max(vals) * 1.05, hi_t * 1.2, 0.05)
    edges = [top * k / bins for k in range(bins + 1)]
    themes = sorted({r["theme"] for r in rows})
    stack = {t: [0] * bins for t in themes}
    for r in rows:
        b = min(bins - 1, int(r["density"] / top * bins))
        stack[r["theme"]][b] += 1
    tot = [sum(stack[t][b] for t in themes) for b in range(bins)]
    ymax = max(tot + [1])
    img = Image.new("RGB", (W, H), (255, 255, 255))
    d = ImageDraw.Draw(img)

    def X(v):
        return M + (W - 2 * M) * v / top

    def Y(c):
        return H - M - (H - 2 * M) * c / ymax
    d.rectangle([X(lo_t), M, X(hi_t), H - M], fill=(236, 253, 245))
    bw = (W - 2 * M) / bins
    for b in range(bins):
        base = 0
        for t in themes:
            c = stack[t][b]
            if c:
                d.rectangle([M + b * bw + 2, Y(base + c), M + (b + 1) * bw - 2, Y(base)],
                            fill=THEME_COL.get(t, THEME_COL[""]))
            base += c
    d.line([M, H - M, W - M, H - M], fill=(0, 0, 0))
    d.line([M, M, M, H - M], fill=(0, 0, 0))
    for k in range(0, bins + 1, max(1, bins // 6)):
        d.text((X(edges[k]) - 12, H - M + 6), "%.2f" % edges[k], fill=(0, 0, 0))
    for c in range(0, ymax + 1, max(1, ymax // 5)):
        d.text((M - 28, Y(c) - 6), str(c), fill=(0, 0, 0))
    d.text((M, 12), "Furniture density (footprint / floor), %d maps; target %.2f-%.2f shaded"
           % (len(rows), lo_t, hi_t), fill=(0, 0, 0))
    lx = W - M - 130
    for k, t in enumerate(themes):
        d.rectangle([lx, 30 + k * 16, lx + 10, 40 + k * 16], fill=THEME_COL.get(t, THEME_COL[""]))
        d.text((lx + 16, 29 + k * 16), t or "(none)", fill=(0, 0, 0))
    img.save(path)


def main():
    args = parse_args()
    files = sorted(glob.glob(args.maps))
    if not files:
        raise SystemExit("Khong co map nao: %s" % args.maps)
    rows = []
    for f in files:
        with open(f, encoding="utf-8") as fh:
            md = json.load(fh)
        m = mg.map_metrics(md)
        m["map"] = os.path.basename(f)
        rows.append(m)
    print("%-22s %-11s %6s %5s %6s %8s %6s %6s %4s" % ("map", "theme", "grid", "items",
          "dens", "it/10m2", "free", "reach", "wp"))
    for r in rows:
        print("%-22s %-11s %6s %5d %6.3f %8.2f %6.2f %6s %4d" % (
            r["map"][:22], r["theme"], r["grid"], r["items"], r["density"], r["items_per_10m2"],
            r["robot_free_ratio"], "-" if r["reachable_ratio"] is None else "%.2f" % r["reachable_ratio"],
            r["waypoints"]))
    print("\nTheo theme:")
    for t in sorted({r["theme"] for r in rows}):
        ds = [r["density"] for r in rows if r["theme"] == t]
        print("  %-11s n=%3d density min %.3f  mean %.3f  max %.3f  sd %.3f" % (
            t or "(none)", len(ds), min(ds), statistics.mean(ds), max(ds),
            statistics.pstdev(ds)))
    lo, hi = args.target
    out = []
    for r in rows:
        why = []
        if not lo <= r["density"] <= hi:
            why.append("density %.3f" % r["density"])
        if r["reachable_ratio"] is not None and r["reachable_ratio"] < args.min_reach:
            why.append("reach %.2f" % r["reachable_ratio"])
        if r["rooms"] and r["waypoints"] < r["rooms"]:
            why.append("waypoints %d/%d" % (r["waypoints"], r["rooms"]))
        if why:
            out.append((r["map"], ", ".join(why)))
    print("\nNgoai le (%d/%d):" % (len(out), len(rows)))
    for m, w in out:
        print("  %s: %s" % (m, w))
    os.makedirs(os.path.dirname(args.csv), exist_ok=True)
    with open(args.csv, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for r in rows:
            w.writerow(r)
    histogram(rows, args.png, args.bins, lo, hi)
    print("\nCSV: %s\nHistogram: %s" % (args.csv, args.png))


if __name__ == "__main__":
    main()
