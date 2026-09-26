"""Planar floor coverage by triangle subtraction, including overlapping triangles.

Works in world X/Z at a separately verified floor elevation. This is a hole
detector, not a native terrain writer or a validator for arbitrary sloped ground.
"""
import math


def area(poly):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(poly, poly[1:]+poly[:1])))*.5


def clip(poly, a, b, sign, inside):
    result = []
    if not poly:
        return result
    def distance(p):
        d = sign*((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))
        return d if inside else -d
    previous, dp = poly[-1], distance(poly[-1])
    for current in poly:
        dc = distance(current)
        if (dp >= 0) != (dc >= 0):
            t = dp/(dp-dc)
            result.append([previous[i]+t*(current[i]-previous[i]) for i in (0, 1)])
        if dc >= 0:
            result.append(list(current))
        previous, dp = current, dc
    clean = []
    for p in result:
        if not clean or math.dist(p, clean[-1]) > 1e-9:
            clean.append(p)
    if len(clean) > 1 and math.dist(clean[0], clean[-1]) < 1e-9:
        clean.pop()
    return clean if len(clean) >= 3 and area(clean) > 1e-10 else []


def subtract_triangle(poly, triangle):
    a, b, c = triangle
    cross = (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    if abs(cross) < 1e-10:
        return [poly]
    sign = 1 if cross > 0 else -1
    remainder, outside = poly, []
    for a, b in zip(triangle, triangle[1:]+triangle[:1]):
        part = clip(remainder, a, b, sign, False)
        if part:
            outside.append(part)
        remainder = clip(remainder, a, b, sign, True)
        if not remainder:
            break
    return outside


def coverage(bb, triangles, tolerance=1e-5):
    x0, z0, x1, z1 = bb[0][0], bb[0][2], bb[1][0], bb[1][2]
    if not all(math.isfinite(v) for v in (x0, z0, x1, z1)) or x1 <= x0 or z1 <= z0:
        raise ValueError('Invalid floor footprint')
    pieces = [[[x0, z0], [x1, z0], [x1, z1], [x0, z1]]]
    for points in triangles:
        tri = [[p[0], p[2]] for p in points]
        if max(p[0] for p in tri) < x0 or min(p[0] for p in tri) > x1 or max(p[1] for p in tri) < z0 or min(p[1] for p in tri) > z1:
            continue
        pieces = [part for poly in pieces for part in subtract_triangle(poly, tri)]
        if len(pieces) > 10000:
            raise ValueError('Floor coverage exceeds the supported polygon complexity')
        if not pieces:
            break
    missing = sum(area(p) for p in pieces)
    return dict(covered=missing <= tolerance, footprintArea=(x1-x0)*(z1-z0),
                uncoveredArea=missing, toleranceArea=tolerance,
                holes=[[[x, 0., z] for x, z in p] for p in pieces if area(p) > tolerance])
