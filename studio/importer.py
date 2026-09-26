"""Import user-owned extracted game archives from a mounted folder."""
import argparse
from . import library
from .worlds import KNOWN

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game-dir', required=True, help='Extracted game folder or data/content directory')
    parser.add_argument('--world', choices=KNOWN)
    parser.add_argument('--assets', action='store_true', help='Import the optional parkassets.big object library')
    args=parser.parse_args()
    if not args.world and not args.assets:parser.error('Choose --world <key>, --assets, or both')
    library.configure(args.game_dir)
    if args.world:
        label, filename, kind=KNOWN[args.world]
        if kind=='overlay':parser.error('Mega Park requires a composed University base and cannot be imported alone yet')
        from .skate3.world import import_world
        import_world(library.stage(filename),args.world,label)
    if args.assets:
        library.stage('parkassets.big',assets=True)
        from .catalog import build_catalog
        catalog=build_catalog()
        print('Object library imported:',len(catalog['assets']),'entries. Restart Studio to load the catalogue.')

if __name__=='__main__':main()
