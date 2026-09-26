"""Deterministic RefPack encoder for bounded native-resource experiments."""
from collections import defaultdict, deque

from .archive import refpack
from .vendor.skate3_streams import decompress_refpack


def compress(data, chain_limit=128):
    if not data or len(data) > 0xffffff:
        raise ValueError('RefPack writer requires 1..16777215 bytes')
    data = bytes(data)
    out = bytearray(b'\x10\xfb' + len(data).to_bytes(3, 'big'))
    chains = defaultdict(lambda: deque(maxlen=chain_limit))
    at = literal_start = 0

    def remember(pos):
        if pos + 3 <= len(data):
            chains[data[pos:pos+3]].append(pos)

    def literals(end):
        nonlocal literal_start
        while end - literal_start >= 4:
            size = min(112, (end - literal_start) // 4 * 4)
            out.append(0xe0 + size // 4 - 1)
            out.extend(data[literal_start:literal_start+size])
            literal_start += size

    while at < len(data):
        best_length = best_distance = 0
        best_gain = 0
        limit = min(1028, len(data) - at)
        if limit >= 3:
            for previous in reversed(chains.get(data[at:at+3], ())):
                distance = at - previous
                if distance > 131072:
                    break
                length = 3
                while length < limit and data[previous+length] == data[at+length]:
                    length += 1
                candidates = []
                if distance <= 1024:
                    candidates.append((min(length, 10), 2))
                if distance <= 16384 and length >= 4:
                    candidates.append((min(length, 67), 3))
                if length >= 5:
                    candidates.append((length, 4))
                for count, cost in candidates:
                    if count-cost > best_gain:
                        best_length, best_distance, best_gain = count, distance, count-cost
                if best_length == limit:
                    break
        if not best_length:
            remember(at)
            at += 1
            continue
        literals(at)
        pending = at-literal_start
        distance = best_distance-1
        length = best_length
        if length <= 10 and best_distance <= 1024:
            out.extend((((distance >> 8) << 5) | ((length-3) << 2) | pending, distance & 255))
        elif length <= 67 and best_distance <= 16384:
            out.extend((0x80 | (length-4), (pending << 6) | (distance >> 8), distance & 255))
        else:
            out.extend((0xc0 | ((distance >> 16) << 4) | (((length-5) >> 8) << 2) | pending,
                        (distance >> 8) & 255, distance & 255, (length-5) & 255))
        out.extend(data[literal_start:at])
        for pos in range(at, at+length):
            remember(pos)
        at += length
        literal_start = at
    literals(at)
    out.append(0xfc + at-literal_start)
    out.extend(data[literal_start:at])
    encoded = bytes(out)
    if refpack(encoded) != data or decompress_refpack(encoded) != data:
        raise ValueError('Independent RefPack round-trip failed')
    return encoded
