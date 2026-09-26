"""CLI entry point for export → reopen → local collision test."""
import argparse
import json
from pathlib import Path
from . import parks, walktests, level_builds


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--export-plan', type=Path, help='Native Black Box layout JSON')
    group.add_argument('--level-plan', type=Path, help='Black Box section layout: build native archive and reopen it')
    group.add_argument('--world', help='Existing imported source key; does not convert game formats')
    parser.add_argument('--section')
    args = parser.parse_args()
    if args.level_plan:
        result = level_builds.build(json.loads(args.level_plan.read_text()))
        print(json.dumps(dict(buildId=result['buildId'], path=result['path'], walkTest=result['walkTest'],
                              readyToInstall=result['readyToInstall'], nextStep=result['nextStep']), indent=2))
    elif args.export_plan:
        result = parks.export(json.loads(args.export_plan.read_text()))
        print(json.dumps(dict(path=result['path'], walkTest=result['walkTest']), indent=2))
    else:
        source = walktests.describe(args.world, args.section)
        print(json.dumps({k:v for k,v in source.items() if k!='manifest'}, indent=2))

if __name__ == '__main__': main()
