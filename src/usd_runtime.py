"""
usd_runtime.py - Make OpenUSD (pxr) importable.

Order: an already-installed pxr (usd-core, Isaac Sim's python inside Kit) -> the OpenUSD
build bundled with Isaac Sim (extscache/omni.usd.libs-*), loaded WITHOUT starting Kit
(works from any CPython of the same minor version, e.g. 3.12). Isaac Sim is looked up in
$ISAACSIM, then C:\\isaacsim.

    from usd_runtime import pxr_available
    if pxr_available(): from pxr import Usd, ...
"""
import glob
import os
import sys

_STATE = {"tried": False, "ok": False, "source": None}


def _isaac_roots():
    roots = [os.environ.get("ISAACSIM"), r"C:\isaacsim", os.path.expanduser("~/isaacsim")]
    return [r for r in roots if r and os.path.isdir(r)]


def _add_isaac_usd():
    tag = "cp%d%d" % sys.version_info[:2]
    for root in _isaac_roots():
        for libs in sorted(glob.glob(os.path.join(root, "extscache", "omni.usd.libs-*")),
                           reverse=True):
            if tag not in os.path.basename(libs) or not os.path.isdir(os.path.join(libs, "pxr")):
                continue
            bin_dir = os.path.join(libs, "bin")
            if hasattr(os, "add_dll_directory") and os.path.isdir(bin_dir):
                os.add_dll_directory(bin_dir)
            os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
            if libs not in sys.path:
                sys.path.append(libs)
            return libs
    return None


def pxr_available():
    """True if `from pxr import Usd` works (tries Isaac Sim's bundled USD once)."""
    if _STATE["tried"]:
        return _STATE["ok"]
    _STATE["tried"] = True
    try:
        from pxr import Usd  # noqa: F401
        _STATE.update(ok=True, source="installed")
        return True
    except ImportError:
        pass
    exe = os.path.normcase(os.path.abspath(sys.executable))
    if any(exe.startswith(os.path.normcase(os.path.abspath(r))) for r in _isaac_roots()):
        return False      # Isaac's own python: Kit provides pxr once SimulationApp starts
    libs = _add_isaac_usd()
    if libs:
        try:
            from pxr import Usd  # noqa: F401,F811  (retry after adding Isaac paths)
            _STATE.update(ok=True, source=libs)
            return True
        except ImportError:
            pass
    return False


def source():
    pxr_available()
    return _STATE["source"]
