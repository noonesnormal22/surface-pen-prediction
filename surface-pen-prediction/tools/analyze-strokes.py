#!/usr/bin/env python3
"""
Analyze a daemon trace (raw input vs emitted output) to quantify:
  - stop overshoot per stroke, bucketed by stroke length (short lines vs long)
  - ellipse roundness (raw vs output radial consistency)

Usage: analyze-strokes.py /path/to/trace.csv
Trace columns: t,tool,raw_x,raw_y,out_x,out_y,conf
Device resolution: ABS_X 37 u/mm, ABS_Y 42 u/mm.
"""

import sys
import csv
import math

RES_X = 37.0
RES_Y = 42.0
GAP_S = 0.10   # split strokes on time gaps larger than this


def mm(dx, dy):
    return math.hypot(dx / RES_X, dy / RES_Y)


def load(path):
    rows = []
    with open(path) as f:
        for r in csv.DictReader(f):
            rows.append((
                float(r['t']), int(r['tool']),
                float(r['raw_x']), float(r['raw_y']),
                float(r['out_x']), float(r['out_y']),
                float(r.get('conf', 0)),
            ))
    return rows


def segment(rows):
    """Split into strokes: contiguous tool==1 runs, also broken on time gaps."""
    strokes, cur, last_t = [], [], None
    for t, tool, rx, ry, ox, oy, conf in rows:
        if tool == 1:
            if last_t is not None and (t - last_t) > GAP_S and cur:
                strokes.append(cur); cur = []
            cur.append((t, rx, ry, ox, oy, conf))
            last_t = t
        else:
            if cur:
                strokes.append(cur); cur = []
            last_t = None
    if cur:
        strokes.append(cur)
    return [s for s in strokes if len(s) >= 4]


def raw_len(s):
    return sum(mm(s[i][1]-s[i-1][1], s[i][2]-s[i-1][2]) for i in range(1, len(s)))


def end_overshoot(s):
    """Signed mm the output endpoint sits past the raw endpoint along the
    final travel direction. Positive = overshoot, negative = undershoot."""
    # final raw direction from a few samples back
    k = min(4, len(s) - 1)
    rdx = s[-1][1] - s[-1-k][1]
    rdy = s[-1][2] - s[-1-k][2]
    mag = math.hypot(rdx, rdy)
    if mag < 1:
        # barely moving at the end — measure plain distance instead
        return mm(s[-1][3]-s[-1][1], s[-1][4]-s[-1][2])
    ux, uy = rdx/mag, rdy/mag
    # output endpoint minus raw endpoint, projected on direction (device units→mm)
    ex = s[-1][3] - s[-1][1]
    ey = s[-1][4] - s[-1][2]
    proj_units = ex*ux + ey*uy
    # convert projected device units to mm using direction-weighted resolution
    res = math.hypot(ux*RES_X, uy*RES_Y) / math.hypot(ux, uy)
    return proj_units / res


def end_hook(s):
    """Max forward excursion (mm) of the output past the raw endpoint during
    the last portion of the stroke — captures the transient 'hook' where the
    line shoots past the stop before settling back. Positive = hook present."""
    k = min(8, len(s) - 1)
    rdx = s[-1][1] - s[-1-k][1]
    rdy = s[-1][2] - s[-1-k][2]
    mag = math.hypot(rdx, rdy)
    if mag < 1:
        return 0.0
    ux, uy = rdx/mag, rdy/mag
    res = math.hypot(ux*RES_X, uy*RES_Y) / math.hypot(ux, uy)
    rex, rey = s[-1][1], s[-1][2]   # raw endpoint
    worst = 0.0
    for p in s[-k:]:
        # output point projected onto direction, relative to raw endpoint
        proj = ((p[3]-rex)*ux + (p[4]-rey)*uy) / res
        worst = max(worst, proj)
    return worst


def roundness(points, ix, iy):
    """Coefficient of variation of radius from centroid (lower = rounder)."""
    cx = sum(p[ix] for p in points) / len(points)
    cy = sum(p[iy] for p in points) / len(points)
    radii = [mm(p[ix]-cx, p[iy]-cy) for p in points]
    mean = sum(radii) / len(radii)
    if mean < 1:
        return None
    var = sum((r-mean)**2 for r in radii) / len(radii)
    return math.sqrt(var) / mean


def is_closed(s):
    return mm(s[0][1]-s[-1][1], s[0][2]-s[-1][2]) < 0.3 * raw_len(s) / math.pi


def main():
    if len(sys.argv) < 2:
        print("usage: analyze-strokes.py trace.csv"); sys.exit(1)
    rows = load(sys.argv[1])
    strokes = segment(rows)
    if not strokes:
        print("No strokes found."); return

    print(f"Trace: {len(rows)} events, {len(strokes)} strokes\n")

    # Bucket by length
    buckets = {'short (<15mm)': [], 'medium (15-50mm)': [], 'long (>50mm)': []}
    hooks   = {'short (<15mm)': [], 'medium (15-50mm)': [], 'long (>50mm)': []}
    ellipses = []
    for s in strokes:
        L = raw_len(s)
        ov = end_overshoot(s)
        hk = end_hook(s)
        key = 'short (<15mm)' if L < 15 else 'medium (15-50mm)' if L < 50 else 'long (>50mm)'
        buckets[key].append(ov)
        hooks[key].append(hk)
        if is_closed(s) and L > 20:
            rr = roundness(s, 1, 2); orr = roundness(s, 3, 4)
            if rr and orr:
                ellipses.append((rr, orr))

    print("FINAL ENDPOINT (mm, +=past stop, -=short of it)")
    print(f"{'bucket':<20}{'n':>4}{'mean':>9}{'max':>9}{'min':>9}")
    for name, vals in buckets.items():
        if vals:
            mean = sum(vals)/len(vals)
            print(f"{name:<20}{len(vals):>4}{mean:>9.2f}{max(vals):>9.2f}{min(vals):>9.2f}")
        else:
            print(f"{name:<20}{0:>4}{'—':>9}{'—':>9}{'—':>9}")

    print("\nEND HOOK (mm, max forward excursion past stop before settling)")
    print(f"{'bucket':<20}{'n':>4}{'mean':>9}{'max':>9}")
    for name, vals in hooks.items():
        if vals:
            print(f"{name:<20}{len(vals):>4}{sum(vals)/len(vals):>9.2f}{max(vals):>9.2f}")
        else:
            print(f"{name:<20}{0:>4}{'—':>9}{'—':>9}")

    if ellipses:
        rraw = sum(e[0] for e in ellipses)/len(ellipses)
        rout = sum(e[1] for e in ellipses)/len(ellipses)
        print(f"\nELLIPSE ROUNDNESS (radial CoV, lower=rounder)  n={len(ellipses)}")
        print(f"  raw input : {rraw:.3f}")
        print(f"  output    : {rout:.3f}   ({'smoother' if rout<rraw else 'rougher'} than raw)")

    print("\nNote: large positive short-bucket overshoot = over-correction on")
    print("short-line stops (the symptom under investigation).")


if __name__ == '__main__':
    main()
