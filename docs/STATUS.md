# Status and roadmap

This public snapshot is a desktop editor/tooling alpha. Development has exercised local imports of Black Box, University and Skate School. A successful import or browser screenshot does not establish full format coverage.

## Evidence by feature

- Moving the three curated Black Box groups in the native archive has been tested in-game. Geometry, collision and admitted grind paths move together. Old baked shadows can remain.
- Source-only and storage-only control archives loaded in-game. Moved layouts were reported working.
- A visual-only section duplicate appeared in-game without added collision, as designed for that diagnostic.
- The render-plus-collision duplicate still allowed walking through the copy. Static collision registration used identity rather than the translated instance pose, leaving collision at the original location.
- The initial full-section export also produced an empty scene. Its broader grind/bounds failure has not been fully isolated. Do not conflate that failure with the later visible-copy collision problem.
- A local walker can transform decoded collision in ways that the game loader does not. Its reports are local observations only.

Public installation of layouts containing copied sections is blocked in both the status UI and installer entry point. The experimental compiler remains available for local research/reimport. Do not distribute exported archives produced from retail inputs.

## Next work

1. Resolve independent section graphics/collision/grind/bounds registration and ownership.
2. Validate source preservation, moved and duplicated collision, grind continuity, scene reload and rollback on hardware.
3. Expand verified section/piece export only after those checks.
4. Improve first-run imports, unsupported-format reports and test coverage using synthetic fixtures.

The separate in-game NativeX editor currently has user-confirmed free camera and Black Box section selection. Its crosshair/HUD candidate was staged during development. Arbitrary scenery grab/place/duplicate is unfinished. Neither that plugin nor its XDK build inputs are part of this repository.
