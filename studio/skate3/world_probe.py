"""Narrow, size-preserving Black Box texture export experiment.

This is not a level-plan exporter. It admits one hash-pinned source archive and
replaces one BC1 texture's GPU payload. Every archive/stream header, resource
placement and non-target byte remains intact. No console operations occur here.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import tempfile

from .archive import BigArchive, refpack
from .arena import Arena
from .vendor.skate3_streams import read_atoc, read_sfil, decompress_refpack
from .world_textures import decode as decode_texture

ROOT = Path(__file__).resolve().parents[2]
SOURCE_SHA256 = '735468fbfdbd1e6d070cb71588f9a19eb3204dd4d3bdf5cbca13e0db716d31ff'
TARGET_ASSET = 0xb0af183cdb807f29
TARGET_TEXTURE = '2c70170a0007009a'
STREAM_PREFIX = 'data/content/world/stream/dist_blackboxpark/'
TARGET_MEMBER = STREAM_PREFIX + 'cpres_global.xsf'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def fixed_size_repeat(block, decoded_size, stored_size):
    """Encode repeated 8-byte blocks in RefPack at an exact stored length.

Eight-byte literals cost nine bytes; short and medium back-references cost two
and three. Mixing them permits this experiment to retain the original compressed
span, without trailing junk, changed sizes or assumptions about unused padding.
"""
    if len(block) != 8 or decoded_size < 16 or decoded_size % 8 or decoded_size > 0xffffff:
        raise ValueError('Probe requires a whole number of 8-byte BC1 blocks')
    count = decoded_size // 8 - 1
    minimum = 5 + 9 + count * 2 + 1
    if stored_size < minimum:
        raise ValueError('Original compressed span is too small for this encoder')
    literals, medium_refs = divmod(stored_size - minimum, 7)
    if literals > count or medium_refs > count - literals:
        raise ValueError('Cannot encode this exact compressed length')
    encoded = (b'\x10\xfb' + decoded_size.to_bytes(3, 'big') + b'\xe1' + block
               + (b'\xe1' + block) * literals
               + b'\x84\x00\x07' * medium_refs
               + b'\x14\x07' * (count - literals - medium_refs) + b'\xfc')
    if len(encoded) != stored_size:
        raise ValueError('Compressed size mismatch')
    expected = block * (decoded_size // 8)
    # Both existing readers must agree, including the stricter end-of-stream check.
    if refpack(encoded) != expected or decompress_refpack(encoded) != expected:
        raise ValueError('RefPack verification failed')
    return encoded


def load_assets(directory):
    result = {}
    occurrences = 0
    for table in sorted(directory.glob('*.xst')):
        if table.name.startswith('.'):
            continue
        records = read_atoc(table)
        expected = {r.asset_id for r in records}
        seen = set()
        stream = table.stem.rsplit('_', 1)[1]
        for path in sorted(directory.glob('c' + stream + '_*.xsf')):
            for asset in read_sfil(path, records, require_all_records=False):
                aid = asset.record.asset_id
                if aid in result and result[aid].data != asset.data:
                    raise ValueError('Conflicting asset copies')
                result[aid] = asset
                seen.add(aid)
                occurrences += 1
        if seen != expected:
            raise ValueError('Source stream is incomplete')
    return result, occurrences


def build(output, source=None):
    output = Path(output)
    source = Path(source) if source else ROOT / 'data/world-source/worldDIST_BlackBoxPark.big'
    archive = BigArchive(source)
    if sha(archive.data) != SOURCE_SHA256:
        raise ValueError('This experiment only admits the verified original Black Box archive')
    preserved = ROOT / 'data/world-source/blackbox/files'
    manifest = json.loads((ROOT / 'web/worlds/blackbox/manifest.json').read_text())
    if manifest['sourceSha256'] != SOURCE_SHA256:
        raise ValueError('Source manifest changed')
    if {f['path'] for f in manifest['sourceFiles']} != set(archive.entries):
        raise ValueError('Source member coverage mismatch')

    # Rebuild from extracted members, retaining only original header and padding.
    rebuilt = bytearray(archive.data)
    for item in manifest['sourceFiles']:
        entry = archive.entries[item['path']]
        payload = (preserved / item['path']).read_bytes()
        if entry['packed'] or len(payload) != entry['size'] or sha(payload) != item['sha256']:
            raise ValueError('Preserved archive member changed')
        rebuilt[entry['offset']:entry['offset'] + entry['size']] = payload
    if bytes(rebuilt) != archive.data:
        raise ValueError('Unchanged reconstruction failed')

    assets, occurrence_count = load_assets(preserved / STREAM_PREFIX)
    if len(assets) != 110:
        raise ValueError('Unexpected source resource count')
    target = assets[TARGET_ASSET]
    if target.record.asset_type != 0x1000 or target.source_path.name != 'cpres_global.xsf':
        raise ValueError('Unexpected texture ownership')
    arena = Arena(target.data)
    gpu_ids = arena.indices(0x10031)
    if len(gpu_ids) != 1:
        raise ValueError('Expected one GPU section')
    gpu_section = arena.sections[gpu_ids[0]]
    meta, before_png = decode_texture(target.data)
    if (meta['id'], meta['width'], meta['height'], meta['format'], meta['endian']) != (TARGET_TEXTURE, 512, 512, 18, 1):
        raise ValueError('Unexpected target texture layout')
    stream = bytearray(archive.read(TARGET_MEMBER))
    values = struct.unpack_from('>11I', stream, target.source_offset + 128)
    cpu_size, cpu_stored, cpu_compression = values[:3]
    gpu_size, gpu_stored, gpu_compression = values[8:11]
    if (cpu_size, cpu_stored, cpu_compression, gpu_size, gpu_stored, gpu_compression) != (568, 568, 0, 196608, 161743, 1):
        raise ValueError('Unexpected SFIL storage layout')
    if gpu_section['offset'] != cpu_size or gpu_section['size'] != gpu_size:
        raise ValueError('GPU section does not match the SFIL resource span')

    # BC1 opaque magenta: RGB565 endpoint F81F, selector zero. Xbox endian=1
    # swaps bytes within each 16-bit word. Uniform blocks cover every mip/tail.
    block = bytes.fromhex('f81f000000000000')
    gpu = block * (gpu_size // 8)
    compressed = fixed_size_repeat(block, gpu_size, gpu_stored)
    payload_start = target.source_offset + 208 + cpu_stored
    payload_end = payload_start + gpu_stored
    stream[payload_start:payload_end] = compressed
    expected_arena = target.data[:cpu_size] + gpu
    _, after_png = decode_texture(expected_arena)
    member = archive.entries[TARGET_MEMBER]
    absolute_start = member['offset'] + payload_start
    absolute_end = member['offset'] + payload_end
    edited = bytearray(rebuilt)
    edited[member['offset']:member['offset'] + member['size']] = stream
    if (len(edited) != len(rebuilt) or edited[:absolute_start] != rebuilt[:absolute_start]
            or edited[absolute_end:] != rebuilt[absolute_end:]):
        raise ValueError('Bytes outside the admitted texture payload changed')

    # Re-extract the actual output and compare every decoded resource, not only
    # the PNG generated from our intended replacement bytes.
    with tempfile.TemporaryDirectory(prefix='nativex-world-probe-') as tmp:
        tmp = Path(tmp)
        test_path = tmp / 'edited.big'
        test_path.write_bytes(edited)
        reread = BigArchive(test_path)
        if reread.entries != archive.entries:
            raise ValueError('Archive directory changed')
        changed_members = []
        for name in archive.entries:
            payload = reread.read(name)
            if payload != archive.read(name):
                changed_members.append(name)
            destination = tmp / 'members' / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        reread_assets, reread_count = load_assets(tmp / 'members' / STREAM_PREFIX)
        if reread_count != occurrence_count or set(reread_assets) != set(assets):
            raise ValueError('Stream coverage changed')
        changed_assets = [aid for aid, asset in reread_assets.items() if asset.data != assets[aid].data]
        if changed_members != [TARGET_MEMBER] or changed_assets != [TARGET_ASSET]:
            raise ValueError('Unexpected resource changes')
        if reread_assets[TARGET_ASSET].data != expected_arena:
            raise ValueError('Output texture differs from the intended replacement')
        if decode_texture(reread_assets[TARGET_ASSET].data)[1] != after_png:
            raise ValueError('Reimported texture preview differs')

    output.mkdir(parents=True, exist_ok=True)
    outputs = {'unchanged.big': bytes(rebuilt), 'magenta-floor.big': bytes(edited),
               'floor-before.png': before_png, 'floor-after.png': after_png}
    for name, payload in outputs.items():
        path = output / name
        if path.exists() and path.read_bytes() != payload:
            raise ValueError('Refusing to overwrite a different experiment: ' + name)
        path.write_bytes(payload)
    report = dict(format='nativex-world-texture-probe', version=1, sourceSha256=SOURCE_SHA256,
                  sourceArchive=str(source), targetAsset=f'{TARGET_ASSET:016x}', textureGuid=TARGET_TEXTURE,
                  description='Black Box concrete-floor diffuse texture becomes opaque magenta at every mip level',
                  archiveBytes=len(edited), outputSha256=sha(edited), changedMembers=changed_members,
                  changedResources=[f'{aid:016x}' for aid in changed_assets], resourcesCompared=len(assets),
                  changedByteCount=sum(a != b for a, b in zip(rebuilt, edited)),
                  allowedByteRange=[absolute_start, absolute_end], gpuDecodedBytes=gpu_size,
                  gpuStoredBytes=gpu_stored, unchangedArchiveByteIdentical=True,
                  allNonTextureDataByteIdentical=True, geometryCollisionGrindsChanged=False,
                  archiveAndStreamHeadersByteIdentical=True, nativeGameReloadTested=False,
                  levelPlanExportSupported=False)
    (output / 'build-report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.output), indent=2))
