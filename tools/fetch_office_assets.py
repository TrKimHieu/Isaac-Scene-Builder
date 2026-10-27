"""
fetch_office_assets.py - Download the Office asset pack from NVIDIA's public Isaac Sim asset server.

The Office pack = Isaac/Environments/Office/{Props,Materials} of the Isaac Sim assets.
Props reference ../Materials/..., so both folders are downloaded with the same layout:
    assets/office/Props/SM_*.usd
    assets/office/Materials/...

Re-runnable: files already present with the same size are skipped.

Chay:
    python tools/fetch_office_assets.py                 # Isaac Sim 5.1 assets
    python tools/fetch_office_assets.py --version 4.5
    python tools/fetch_office_assets.py --check         # only verify, no download
"""
import argparse
import os
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from config import (ASSETS_DIR, REQUIRED, FURNITURE, EXTRA_FURNITURE,  # noqa: E402
                    STRUCTURE_CHOICES)

BUCKET = "https://omniverse-content-production.s3-us-west-2.amazonaws.com"
OFFICE_PREFIX = "Assets/Isaac/{version}/Isaac/Environments/Office/"
SUBDIRS = ["Props", "Materials"]
_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--version", default="5.1", help="Isaac Sim asset version (4.5, 5.0, 5.1, ...)")
    ap.add_argument("--dest", default=os.path.join(ASSETS_DIR, "office"))
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--check", action="store_true", help="only verify required props exist")
    return ap.parse_args()


def list_objects(prefix):
    """All (key, size) under an S3 prefix (follows marker pagination)."""
    out, marker = [], ""
    while True:
        q = urllib.parse.urlencode({"prefix": prefix, "marker": marker})
        with urllib.request.urlopen("%s/?%s" % (BUCKET, q), timeout=60) as r:
            root = ET.fromstring(r.read())
        keys = []
        for c in root.iter(_NS + "Contents"):
            key = c.find(_NS + "Key").text
            keys.append(key)
            if not key.endswith("/"):
                out.append((key, int(c.find(_NS + "Size").text)))
        if root.find(_NS + "IsTruncated").text != "true" or not keys:
            return out
        marker = keys[-1]


def download(key, size, dest):
    """Download one object to dest. Returns 'skip' / 'ok'."""
    if os.path.isfile(dest) and os.path.getsize(dest) == size:
        return "skip"
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    url = "%s/%s" % (BUCKET, urllib.parse.quote(key))
    tmp = dest + ".part"
    with urllib.request.urlopen(url, timeout=120) as r, open(tmp, "wb") as fh:
        while True:
            chunk = r.read(1 << 16)
            if not chunk:
                break
            fh.write(chunk)
    os.replace(tmp, dest)
    return "ok"


def fetch(version, dest_root, workers):
    base = OFFICE_PREFIX.format(version=version)
    jobs = []
    for sub in SUBDIRS:
        objs = [(k, s) for k, s in list_objects(base + sub + "/") if "/.thumbs/" not in k]
        if not objs:
            raise SystemExit("Khong tim thay %s%s/ tren server (version %s?)" % (base, sub, version))
        print("%-10s %4d file, %.1f MB" % (sub, len(objs), sum(s for _, s in objs) / 1e6))
        jobs += [(k, s, os.path.join(dest_root, *k[len(base):].split("/"))) for k, s in objs]

    counts = {"ok": 0, "skip": 0, "fail": 0}
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(download, k, s, d): k for k, s, d in jobs}
        for i, f in enumerate(as_completed(futs), 1):
            try:
                counts[f.result()] += 1
            except Exception as e:  # keep going; report at the end
                counts["fail"] += 1
                print("  LOI %s: %s" % (futs[f], e))
            if i % 200 == 0 or i == len(jobs):
                print("  %d/%d" % (i, len(jobs)))
    print("Tai moi: %(ok)d, bo qua (da co): %(skip)d, loi: %(fail)d" % counts)
    return counts["fail"] == 0


def check(dest_root):
    """Verify every prop the project relies on is present. Returns list of missing names."""
    names = set(REQUIRED) | {n for n, _ in FURNITURE} | set(EXTRA_FURNITURE)
    for choices in STRUCTURE_CHOICES.values():
        names |= set(choices)
    props = os.path.join(dest_root, "Props")
    missing = sorted(n for n in names if not os.path.isfile(os.path.join(props, n + ".usd")))
    print("Kiem tra %d prop can thiet: %s" % (
        len(names), "du" if not missing else "THIEU %d: %s" % (len(missing), ", ".join(missing))))
    return missing


def main():
    args = parse_args()
    ok = True
    if not args.check:
        print("Tai Office pack (Isaac %s) -> %s" % (args.version, args.dest))
        ok = fetch(args.version, args.dest, args.workers)
    missing = check(args.dest)
    sys.exit(0 if ok and not missing else 1)


if __name__ == "__main__":
    main()
