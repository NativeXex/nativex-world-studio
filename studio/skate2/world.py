"""Import the measured Skate 2 AntiHero training facility for local inspection.

This imports selected members from the user's original worldmisc.big. It does
not convert assets to Skate 3 or produce an Xbox replacement archive.
"""
import argparse
from pathlib import Path
from .archive import ClassicBigArchive
from .materials import enrich
from ..skate3.world import ROOT, import_world, write_json, progress

KEY = 'skate2-training-antihero'
PREFIX = 'data/content/world/stream/dist_trainingfacility_antihero/'


def run(source):
    result = import_world(source, KEY, 'Skate 2 · AntiHero training facility',
                          archive_reader=ClassicBigArchive, member_prefix=PREFIX,
                          game_build='skate2-xbox360-local', material_enricher=enrich)
    result['compatibility'] = dict(skate3NativeExport=False, skate3RuntimeTested=False,
                                   scope='One training facility, not the entire Skate 2 city')
    result['warnings'].insert(0, 'Skate 2 source preview only. Skate 3 runtime compatibility is untested. Source coordinates and metre scale are retained; no cross-game conversion is performed.')
    for name in ('manifest.json', 'manifest.nxdata'):
        write_json(ROOT/'web/worlds'/KEY/name, result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    args = parser.parse_args()
    try:
        run(args.archive)
    except Exception as e:
        progress(KEY, str(e), state='failed')
        raise
