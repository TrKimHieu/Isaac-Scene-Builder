"""
capture_all.py - Capture every library prop with Isaac Sim, robust to GPU out-of-memory.

Runs src/isaac_bev_capture.py in short rounds (a fresh Isaac process each round frees all
VRAM), resuming with --skip-existing. If Isaac crashes, the prop it was capturing is
written to output/mesh_shapes/renders/_failed.txt and skipped next round.
Then (optional) runs build_furniture_shapes.py.

Chay (Python thuong, KHONG phai python cua Isaac):
    python tools/capture_all.py                       # --library, rounds of 15, chunk 1
    python tools/capture_all.py --per-round 10 --build
    python tools/capture_all.py --set office          # Office pack furniture palette
    set ISAACSIM=D:\\isaacsim  (if Isaac Sim is not in C:\\isaacsim)
"""
import argparse
import os
import subprocess
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
from config import RENDER_DIR  # noqa: E402

FAILED = os.path.join(RENDER_DIR, "_failed.txt")


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--isaacsim", default=os.environ.get("ISAACSIM", r"C:\isaacsim"))
    ap.add_argument("--set", choices=("library", "office"), default="library",
                    help="library = curated asset library; office = Office furniture palette")
    ap.add_argument("--per-round", type=int, default=15, help="props per Isaac process")
    ap.add_argument("--chunk", type=int, default=1, help="props on the GPU at once")
    ap.add_argument("--max-rounds", type=int, default=100)
    ap.add_argument("--build", action="store_true", help="run build_furniture_shapes.py after")
    ap.add_argument("--log", default=os.path.join(RENDER_DIR, "_capture_round.log"))
    return ap.parse_args()


def _failed():
    if not os.path.isfile(FAILED):
        return []
    with open(FAILED, encoding="utf-8") as fh:
        return [ln.strip() for ln in fh if ln.strip()]


def run_round(args):
    """One Isaac process. Returns (ok_names, crashed_on or None, exit_code)."""
    env = dict(os.environ, OMNI_KIT_ACCEPT_EULA="YES", PYTHONNOUSERSITE="1")
    cmd = [os.path.join(args.isaacsim, "python.bat"), os.path.join("src", "isaac_bev_capture.py"),
           "--" + args.set, "--skip-existing", "--chunk", str(args.chunk),
           "--limit", str(args.per_round), "--exclude-file", FAILED]
    os.makedirs(RENDER_DIR, exist_ok=True)
    with open(args.log, "w", encoding="utf-8", errors="replace") as log:
        rc = subprocess.call(cmd, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    started, ok = [], set()
    with open(args.log, encoding="utf-8", errors="replace") as fh:
        for ln in fh:
            if ln.startswith("[start] "):
                started.append(ln.split(" ", 1)[1].strip())
            elif ln.startswith("[ok] "):
                ok.add(ln.split()[2][:-4])                       # "[ok] i/n NAME.png ..."
    pending = [n for n in started if n not in ok]
    crashed = pending[-1] if (pending and "DONE:" not in open(
        args.log, encoding="utf-8", errors="replace").read()) else None
    return ok, crashed, rc


def main():
    args = parse_args()
    if not os.path.isfile(os.path.join(args.isaacsim, "python.bat")):
        raise SystemExit("Khong tim thay Isaac Sim tai %s (dung --isaacsim)" % args.isaacsim)
    total_ok = 0
    for rnd in range(1, args.max_rounds + 1):
        t0 = time.time()
        ok, crashed, rc = run_round(args)
        total_ok += len(ok)
        print("round %d: +%d anh (%.0f s)%s" % (rnd, len(ok), time.time() - t0,
              ", CRASH tai %s -> bo qua" % crashed if crashed else ""), flush=True)
        if crashed:
            with open(FAILED, "a", encoding="utf-8") as fh:
                fh.write(crashed + "\n")
        if not ok and not crashed:
            break                                   # nothing left (or nothing capturable)
    print("Xong: %d anh moi; loi: %s" % (total_ok, ", ".join(_failed()) or "khong"))
    if args.build:
        subprocess.call([sys.executable, os.path.join("src", "build_furniture_shapes.py")],
                        cwd=ROOT)


if __name__ == "__main__":
    main()
