#!/usr/bin/env python3
"""Build nigeria-states.json (SVG path data for Nigeria's 36 states + FCT).

Source: geoBoundaries gbOpen NGA ADM1 (boundary source: GRID3 Nigeria State
Boundaries, 2022). Licence: CC BY 4.0. Attribution: "geoBoundaries
(www.geoboundaries.org), boundary data from GRID3 (data.grid3.org)".

Pipeline (standard library only, Python 3.8+):
  1. Load the ADM1 GeoJSON (downloaded, or a local file via --input).
  2. Project with an equirectangular projection scaled by cos(mean latitude),
     which is accurate enough for a country spanning ~10 degrees of latitude.
  3. Topology-preserving simplification: every ring is split into arcs at
     junction vertices (where the set of states sharing a vertex changes),
     and each arc is simplified once with Douglas-Peucker, so neighbouring
     states keep identical borders (no gaps or slivers).
  4. Emit compact relative SVG path strings and a label anchor (centroid) keyed by the state names used in
     the STATES array in index.html, and check that all 37 names match.

Usage:
  python3 scripts/build_states_svg.py [--input FILE] [--tolerance 1.2]
"""
import argparse
import hashlib
import json
import math
import re
import sys
import urllib.request
from pathlib import Path

SOURCE_URL = ("https://media.githubusercontent.com/media/wmgeolab/geoBoundaries/"
              "main/releaseData/gbOpen/NGA/ADM1/geoBoundaries-NGA-ADM1.geojson")
ROOT = Path(__file__).resolve().parent.parent
WIDTH = 1000.0  # viewBox width; height follows the aspect ratio
PAD = 4.0       # viewBox padding

# geoBoundaries shapeName -> name used in STATES (index.html).
# Only FCT differs; listed explicitly so a source rename fails loudly.
NAME_OVERRIDES = {"Abuja Federal Capital Territory": "FCT"}


def load_geojson(path):
    if path:
        raw = Path(path).read_bytes()
    else:
        with urllib.request.urlopen(SOURCE_URL, timeout=120) as r:
            raw = r.read()
    return json.loads(raw), hashlib.sha256(raw).hexdigest()


def states_names(index_html):
    m = re.search(r"const STATES\s*=\s*(\[.*?\]);", index_html.read_text("utf-8"), re.S)
    if not m:
        sys.exit("Could not find STATES in index.html")
    return [s["n"] for s in json.loads(m.group(1))]


def polygons_of(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    raise ValueError("Unsupported geometry " + geom["type"])


def dp(points, eps):
    """Iterative Douglas-Peucker on an open polyline (endpoints kept)."""
    n = len(points)
    if n < 3:
        return list(points)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        a, b = stack.pop()
        (ax, ay), (bx, by) = points[a], points[b]
        dx, dy = bx - ax, by - ay
        L = math.hypot(dx, dy)
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = points[i]
            d = (abs(dy * px - dx * py + bx * ay - by * ax) / L) if L else math.hypot(px - ax, py - ay)
            if d > best:
                best, idx = d, i
        if best > eps:
            keep[idx] = True
            stack += [(a, idx), (idx, b)]
    return [p for p, k in zip(points, keep) if k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="local geoBoundaries NGA ADM1 GeoJSON (default: download)")
    ap.add_argument("--tolerance", type=float, default=1.2,
                    help="simplification tolerance in viewBox units (default 1.2 of 1000 wide)")
    ap.add_argument("--output", default=str(ROOT / "nigeria-states.json"))
    args = ap.parse_args()

    gj, sha = load_geojson(args.input)
    feats = gj["features"]

    # --- projection --------------------------------------------------------
    lats = [p[1] for f in feats for poly in polygons_of(f["geometry"]) for r in poly for p in r]
    lons = [p[0] for f in feats for poly in polygons_of(f["geometry"]) for r in poly for p in r]
    k = math.cos(math.radians((min(lats) + max(lats)) / 2))
    x0, x1 = min(lons) * k, max(lons) * k
    y0, y1 = -max(lats), -min(lats)
    s = (WIDTH - 2 * PAD) / (x1 - x0)
    height = round((y1 - y0) * s + 2 * PAD)

    def proj(p):
        return ((p[0] * k - x0) * s + PAD, (-p[1] - y0) * s + PAD)

    # --- rings, keyed by original (exact) coordinates for topology ---------
    rings = []  # (state_index, polygon_index, ring_index, [orig points without closing pt])
    for fi, f in enumerate(feats):
        for pi, poly in enumerate(polygons_of(f["geometry"])):
            for ri, ring in enumerate(poly):
                pts = [tuple(p) for p in ring]
                if pts[0] == pts[-1]:
                    pts = pts[:-1]
                rings.append((fi, pi, ri, pts))

    owners = {}
    for fi, _, _, pts in rings:
        for p in pts:
            owners.setdefault(p, set()).add(fi)

    arc_cache = {}

    def simplify_arc(arc):
        fwd, rev = tuple(arc), tuple(reversed(arc))
        key = min(fwd, rev)
        if key not in arc_cache:
            arc_cache[key] = dp([proj(p) for p in key], args.tolerance)
        out = arc_cache[key]
        return out if key == fwd else list(reversed(out))

    out_rings = {}
    for fi, pi, ri, pts in rings:
        n = len(pts)
        own = [frozenset(owners[p]) for p in pts]
        nodes = [i for i in range(n) if own[i] != own[i - 1] or own[i] != own[(i + 1) % n]
                 or len(own[i]) > 2]
        if len(nodes) < 2:  # ring with no junctions (e.g. an island): pick two anchors
            far = max(range(n), key=lambda i: (pts[i][0] - pts[0][0]) ** 2 + (pts[i][1] - pts[0][1]) ** 2)
            nodes = sorted({0, far})
        simplified = []
        for j, a in enumerate(nodes):
            b = nodes[(j + 1) % len(nodes)]
            arc = pts[a:b + 1] if b > a else pts[a:] + pts[:b + 1]
            simplified.extend(simplify_arc(arc)[:-1])
        if len(simplified) < 3:
            simplified = [proj(p) for p in pts]  # never let a ring collapse
        out_rings.setdefault(fi, []).append(simplified)

    # --- SVG path strings (relative, 1 d.p., deltas from rounded absolutes) -
    def fmt(v):
        t = f"{v:.1f}".rstrip("0").rstrip(".")
        return "0" if t in ("-0", "") else t

    def ring_d(ring):
        q = [(round(x, 1), round(y, 1)) for x, y in ring]
        dedup = [q[0]] + [p for i, p in enumerate(q[1:], 1) if p != q[i - 1]]
        cmd = f"M{fmt(dedup[0][0])} {fmt(dedup[0][1])}"
        parts = []
        for (ax, ay), (bx, by) in zip(dedup, dedup[1:]):
            parts.append(f"{fmt(bx - ax)} {fmt(by - ay)}")
        return cmd + ("l" + " ".join(parts) if parts else "") + "z"

    def centroid(rings_):
        """Area-weighted centroid of the largest ring (label anchor)."""
        best, ba = None, -1.0
        for r in rings_:
            a = cx = cy = 0.0
            for (x0_, y0_), (x1_, y1_) in zip(r, r[1:] + r[:1]):
                c = x0_ * y1_ - x1_ * y0_
                a += c; cx += (x0_ + x1_) * c; cy += (y0_ + y1_) * c
            if abs(a) > ba:
                ba, best = abs(a), (cx / (3 * a), cy / (3 * a)) if a else r[0]
        return [round(best[0], 1), round(best[1], 1)]

    expected = states_names(ROOT / "index.html")
    paths, src_names, labels = {}, {}, {}
    for fi, f in enumerate(feats):
        src = f["properties"]["shapeName"]
        name = NAME_OVERRIDES.get(src, src)
        src_names[name] = src
        paths[name] = "".join(ring_d(r) for r in out_rings[fi])
        labels[name] = centroid(out_rings[fi])

    # --- name check --------------------------------------------------------
    missing = sorted(set(expected) - set(paths))
    extra = sorted(set(paths) - set(expected))
    renamed = {v: k for k, v in src_names.items() if k != v}
    print(f"STATES names: {len(expected)}, GeoJSON features: {len(paths)}")
    print(f"Renamed from source: {renamed or 'none'}")
    if missing or extra:
        print(f"MISMATCH - in STATES but not GeoJSON: {missing}; in GeoJSON but not STATES: {extra}")
        sys.exit(1)
    print("All names match STATES exactly.")

    result = {
        "viewBox": f"0 0 {WIDTH:g} {height}",
        "projection": f"equirectangular, x scaled by cos({math.degrees(math.acos(k)):.3f} deg)",
        "source": "geoBoundaries gbOpen NGA ADM1 (boundary source: GRID3 Nigeria State Boundaries, 2022)",
        "sourceUrl": SOURCE_URL,
        "sourceSha256": sha,
        "license": "CC BY 4.0",
        "attribution": "geoBoundaries (www.geoboundaries.org), boundary data from GRID3 (data.grid3.org)",
        "simplifyTolerance": args.tolerance,
        "states": {n: paths[n] for n in expected},  # same order as STATES
        "labels": {n: labels[n] for n in expected},  # label anchor [x, y] per state
    }
    Path(args.output).write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False) + "\n", "utf-8")
    pts = sum(d.count(" ") + 1 for d in paths.values()) // 2
    print(f"Wrote {args.output}: {Path(args.output).stat().st_size} bytes, ~{pts} points, viewBox {result['viewBox']}")


if __name__ == "__main__":
    main()
