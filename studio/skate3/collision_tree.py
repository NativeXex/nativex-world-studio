"""Checked retail triangle-cluster provenance and conservative KD-tree refits.

Admits the Xbox triangle-unit layout measured in Black Box Park. Nodes, leaf
ordering, unit indices, edge codes and surface IDs are never rebuilt or reordered.
"""
from collections import Counter
import struct
import math

from .archive import u32
from .vendor.retail_collision_mesh import _decode_vertices, decode_clustered_mesh


def bounds(points):
    return [[fn(p[a] for p in points) for a in range(3)] for fn in (min, max)]


def union(items):
    items = [x for x in items if x is not None]
    return bounds([p for b in items for p in b]) if items else None


class TriangleTree:
    def __init__(self, data):
        self.data = bytes(data)
        self.mesh = decode_clustered_mesh(self.data)
        self.granularity = struct.unpack_from('>f', data, 56)[0]
        self.kd = u32(data, 48)
        self.node_start, self.node_count, entry_count = struct.unpack_from('>3I', data, self.kd)
        table = u32(data, 52)
        if self.node_start != self.kd+48 or self.node_start+self.node_count*32 != table:
            raise ValueError('Unsupported collision tree storage')
        self.vertices = {}
        self.vertex_storage = {}
        self.units = []
        self.unit_lookup = {}
        for ci in range(self.mesh.cluster_count):
            start = u32(data, table+ci*4)
            unit_count, unit_bytes, blocks = struct.unpack_from('>3H', data, start)
            size = struct.unpack_from('>H', data, start+8)[0]
            count, mode = data[start+10], data[start+12]
            vertex_end = (blocks+1)*16
            points = _decode_vertices(data[start:start+size], count, mode, self.granularity, vertex_end)
            base = struct.unpack_from('>3i', data, start+16) if mode == 1 else None
            for vi, point in enumerate(points):
                key = (ci, vi)
                self.vertices[key] = point
                offset = start+28+vi*6 if mode == 1 else start+16+vi*(12 if mode == 2 else 16)
                self.vertex_storage[key] = (offset, mode, base)
            unit_start = start+vertex_end
            cursor = unit_start
            for _ in range(unit_count):
                relative = cursor-unit_start
                flags = data[cursor]
                if flags & 15 != 1 or flags & 0x10:
                    raise ValueError('Writer requires native triangle units')
                indices = tuple(data[cursor+1:cursor+4])
                if any(i >= count for i in indices):
                    raise ValueError('Invalid collision unit vertex')
                cursor += 4
                if flags & 0x20:
                    cursor += 3
                if flags & 0x40:
                    cursor += self.mesh.group_id_width
                if flags & 0x80:
                    cursor += self.mesh.surface_id_width
                key = (ci, relative)
                self.unit_lookup[key] = len(self.units)
                self.units.append(dict(key=key, vertices=[(ci, vi) for vi in indices]))
            if cursor != unit_start+unit_bytes:
                raise ValueError('Collision unit provenance did not consume its stream')
        if entry_count != len(self.units) or entry_count != len(self.mesh.triangles):
            raise ValueError('Collision KD entry count mismatch')
        for unit, triangle in zip(self.units, self.mesh.triangles):
            if tuple(self.vertices[v] for v in unit['vertices']) != (triangle.a, triangle.b, triangle.c):
                raise ValueError('Independent collision decoder disagrees with provenance')
        self.nodes = [struct.unpack_from('>6I2f', data, self.node_start+i*32) for i in range(self.node_count)]
        self._walk(validate=True)

    def leaf_units(self, count, packed):
        if not count:
            return []
        key = (packed >> 16, packed & 0xffff)
        if key not in self.unit_lookup:
            raise ValueError('KD leaf references an unknown unit address')
        start = self.unit_lookup[key]
        if start+count > len(self.units):
            raise ValueError('KD leaf exceeds native units')
        return list(range(start, start+count))

    def unit_bounds(self, index):
        return bounds([self.vertices[v] for v in self.units[index]['vertices']])

    def _walk(self, validate=False, output=None):
        visited = set()
        coverage = Counter()
        changed = []
        tolerance = self.granularity*2.1

        def node(index, parent):
            if index >= self.node_count or index in visited:
                raise ValueError('Cyclic or shared KD branch')
            visited.add(index)
            p, axis, lc, li, rc, ri, left_extent, right_extent = self.nodes[index]
            if p != parent or axis > 2:
                raise ValueError('Invalid KD parent or split axis')
            child_bounds = []
            for count, first in ((lc, li), (rc, ri)):
                if count == 0xffffffff:
                    child_bounds.append(node(first, index))
                else:
                    ids = self.leaf_units(count, first)
                    coverage.update(ids)
                    child_bounds.append(union([self.unit_bounds(i) for i in ids]))
            left, right = child_bounds
            if validate:
                if left and left[1][axis] > left_extent+tolerance:
                    raise ValueError(f'KD left extent misses geometry at node {index}')
                if right and right[0][axis] < right_extent-tolerance:
                    raise ValueError(f'KD right extent misses geometry at node {index}')
            if output is not None:
                # Expand existing intervals only where changed vertices leave
                # them. Overlap is valid: retail trees already use overlapping
                # intervals. Retain the exact native topology and leaf IDs.
                for at, old, new in ((24, left_extent, left[1][axis]+tolerance if left and left[1][axis] > left_extent+tolerance else left_extent),
                                     (28, right_extent, right[0][axis]-tolerance if right and right[0][axis] < right_extent-tolerance else right_extent)):
                    if new != old:
                        struct.pack_into('>f', output, self.node_start+index*32+at, new)
                        changed.append(dict(node=index, field='leftMax' if at == 24 else 'rightMin', before=old, after=new))
            return union(child_bounds)

        overall = node(0, 0)
        if len(visited) != self.node_count or coverage != Counter(range(len(self.units))):
            raise ValueError('KD tree does not cover every native triangle exactly once')
        if any(overall[0][a] < self.mesh.bounds_min[a]-tolerance or overall[1][a] > self.mesh.bounds_max[a]+tolerance for a in range(3)):
            raise ValueError('Geometry leaves original collision broad-phase bounds')
        return changed

    def candidates(self, low, high):
        result = set()
        pending = [0]
        while pending:
            i = pending.pop()
            _, axis, lc, li, rc, ri, left_extent, right_extent = self.nodes[i]
            for take, count, first in ((low[axis] <= left_extent, lc, li), (high[axis] >= right_extent, rc, ri)):
                if take:
                    if count == 0xffffffff:
                        pending.append(first)
                    else:
                        result.update(self.leaf_units(count, first))
        return result

    def encode_translations(self, translations, *, rebase=False):
        """Encode all final positions together, preserving every stationary vertex.

        Rebase only overflowing 16-bit clusters. Counts/topology/allocation remain
        unchanged; a span that needs splitting is rejected before any file write.
        """
        selected = set(translations)
        if not selected or any(type(i) is not int or i < 0 or i >= len(self.units) for i in selected):
            raise ValueError('Invalid collision selection')
        owners = {}
        for i, delta in translations.items():
            if len(delta) != 3 or any(not math.isfinite(d) for d in delta):
                raise ValueError('Invalid collision translation')
            steps = tuple(round(d/self.granularity) for d in delta)
            if any(abs(steps[a]*self.granularity-delta[a]) > 1e-5 for a in range(3)):
                raise ValueError('Move is not aligned to native collision quantisation')
            for key in self.units[i]['vertices']:
                if key in owners and owners[key] != steps:
                    raise ValueError('Shared collision vertex has conflicting translations')
                owners[key] = steps
        if any(any(v in owners for v in unit['vertices']) for i, unit in enumerate(self.units) if i not in selected):
            raise ValueError('Selected collision shares a vertex with stationary geometry')
        output, rebased = bytearray(self.data), []
        clusters = {key[0] for key in owners}
        for ci in sorted(clusters):
            keys = [k for k in self.vertices if k[0] == ci]
            base = self.vertex_storage[keys[0]][2]
            values = {}
            for key in keys:
                at, mode, _ = self.vertex_storage[key]
                if mode != 1:
                    raise ValueError('Writer requires measured 16-bit offset vertices')
                old = struct.unpack_from('>3H', self.data, at)
                steps = owners.get(key, (0, 0, 0))
                values[key] = tuple(base[a]+old[a]+steps[a] for a in range(3))
            low = [min(p[a] for p in values.values()) for a in range(3)]
            high = [max(p[a] for p in values.values()) for a in range(3)]
            if any(high[a]-low[a] > 65535 for a in range(3)):
                if not rebase:
                    raise ValueError('Move exceeds the preserved cluster vertex range')
                raise ValueError(f'Collision cluster {ci} needs splitting: final vertex span exceeds 65,535 quantised steps')
            new_base = tuple(min(low[a], max(base[a], high[a]-65535)) for a in range(3))
            if new_base != base:
                if not rebase:
                    raise ValueError('Move exceeds the preserved cluster vertex range')
                if any(v < -2147483648 or v > 2147483647 for v in new_base):
                    raise ValueError('Collision cluster origin exceeds signed 32-bit range')
                first = self.vertex_storage[(ci, 0)][0]
                struct.pack_into('>3i', output, first-12, *new_base)
                rebased.append(dict(cluster=ci, before=list(base), after=list(new_base), vertices=len(keys)))
            for key, value in values.items():
                at = self.vertex_storage[key][0]
                struct.pack_into('>3H', output, at, *(value[a]-new_base[a] for a in range(3)))
        return output, owners, rebased

    def translate(self, selected_units, delta, *, rebase=False):
        return self.translate_many({i: delta for i in selected_units}, rebase=rebase)

    def translate_many(self, translations, *, rebase=False):
        output, owners, rebased = self.encode_translations(translations, rebase=rebase)
        moved = decode_clustered_mesh(bytes(output))
        original_vertices = self.vertices
        try:
            self.vertices = dict(self.vertices)
            for unit, tri in zip(self.units, moved.triangles):
                for key, point in zip(unit['vertices'], (tri.a, tri.b, tri.c)):
                    self.vertices[key] = point
            changes = self._walk(output=output)
        finally:
            self.vertices = original_vertices
        checked = TriangleTree(bytes(output))
        for key, before in self.vertices.items():
            wanted = tuple(before[a]+owners.get(key, (0, 0, 0))[a]*self.granularity for a in range(3))
            if any(abs(checked.vertices[key][a]-wanted[a]) > 2e-5 for a in range(3)):
                raise ValueError('Collision movement escaped its selection')
        for before, after in zip(self.mesh.triangles, checked.mesh.triangles):
            if (before.surface, before.edge_codes, before.group_id, before.unit_flags) != (after.surface, after.edge_codes, after.group_id, after.unit_flags):
                raise ValueError('Native collision attributes changed')
        for i, tri in enumerate(checked.mesh.triangles):
            centre = [sum(p[a] for p in (tri.a, tri.b, tri.c))/3 for a in range(3)]
            if i not in checked.candidates([x-.003 for x in centre], [x+.003 for x in centre]):
                raise ValueError('Refitted KD tree cannot find a collision triangle')
        return bytes(output), dict(triangles=len(translations), vertices=len(owners), kdExtentChanges=changes,
                                   clustersRebased=rebased, stationaryVerticesPreserved=True,
                                   trianglesQueried=len(checked.units), nodesChecked=self.node_count)
