"""
nv_s3.py - Small helpers for NVIDIA's public Omniverse/Isaac asset bucket (anonymous S3).

    list_objects(prefix)              -> [(key, size)]  (paginated, optional JSON cache)
    download(url_or_key, dest, size)  -> 'ok' | 'skip'
"""
import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

BUCKET = "https://omniverse-content-production.s3-us-west-2.amazonaws.com"
_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
# Some hosts (Poly Haven) reject Python's default user agent.
USER_AGENT = "Isaac-Scene-Builder/1.0 (+https://github.com/TrKimHieu/Isaac-Scene-Builder)"


def _open(url, timeout, method=None):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def key_url(key):
    return "%s/%s" % (BUCKET, urllib.parse.quote(key))


def url_to_key(url):
    """Bucket URL (any host spelling of this bucket) -> key, else None."""
    for host in ("omniverse-content-production.s3-us-west-2.amazonaws.com",
                 "omniverse-content-production.s3.us-west-2.amazonaws.com"):
        for scheme in ("http://", "https://"):
            pre = scheme + host + "/"
            if url.startswith(pre):
                return urllib.parse.unquote(url[len(pre):])
    return None


def list_objects(prefix, cache_dir=None):
    """All (key, size) under prefix, skipping folder markers and .thumbs/."""
    cache = None
    if cache_dir:
        os.makedirs(cache_dir, exist_ok=True)
        cache = os.path.join(cache_dir, prefix.strip("/").replace("/", "__") + ".json")
        if os.path.isfile(cache):
            with open(cache, encoding="utf-8") as fh:
                return [tuple(x) for x in json.load(fh)]
    out, marker = [], ""
    while True:
        q = urllib.parse.urlencode({"prefix": prefix, "marker": marker})
        with _open("%s/?%s" % (BUCKET, q), 120) as r:
            root = ET.fromstring(r.read())
        keys = []
        for c in root.iter(_NS + "Contents"):
            key = c.find(_NS + "Key").text
            keys.append(key)
            if not key.endswith("/") and "/.thumbs/" not in key:
                out.append((key, int(c.find(_NS + "Size").text)))
        if root.find(_NS + "IsTruncated").text != "true" or not keys:
            break
        marker = keys[-1]
    if cache:
        with open(cache, "w", encoding="utf-8") as fh:
            json.dump(out, fh)
    return out


def fetch_bytes(url, timeout=120):
    with _open(url, timeout) as r:
        return r.read()


def download(url, dest, size=None, retries=3):
    """Download url to dest (atomic). Skips when dest exists with the expected size."""
    if os.path.isfile(dest) and (size is None or os.path.getsize(dest) == size):
        return "skip"
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    tmp = dest + ".part"
    for attempt in range(retries):
        try:
            with _open(url, 180) as r, open(tmp, "wb") as fh:
                while True:
                    chunk = r.read(1 << 16)
                    if not chunk:
                        break
                    fh.write(chunk)
            os.replace(tmp, dest)
            return "ok"
        except Exception:
            if attempt == retries - 1:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
