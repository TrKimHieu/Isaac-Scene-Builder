"""
migrate_maps.py - Rewrite saved map JSON files on the current grid (1 m cells).

Maps from before the 1 m grid (3 m cells, no "cell" key) still open everywhere - they are
converted on load (src/map_format.py). This tool converts the files themselves, so they can
be edited at 1 m resolution and diffed. A file already on the current grid is left alone.

Usage:
    python tools/migrate_maps.py                     # data/maps/*.json
    python tools/migrate_maps.py path/to/map.json ...
"""
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

import map_format  # noqa: E402
from config import MAPS_DIR  # noqa: E402


def main(paths):
    paths = paths or sorted(glob.glob(os.path.join(MAPS_DIR, "*.json")))
    changed = 0
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            md = json.load(fh)
        if map_format.is_current(md):
            print("  ok        %s" % os.path.basename(p))
            continue
        new = map_format.upgrade(md)
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(new, fh, indent=1)
        changed += 1
        print("  migrated  %s  %s -> %s cells" % (os.path.basename(p), "x".join(map(str, md["grid"])),
                                                  "x".join(map(str, new["grid"]))))
    print("%d of %d map(s) converted to %.0f m cells" % (changed, len(paths), map_format.CELL))


if __name__ == "__main__":
    main(sys.argv[1:])
