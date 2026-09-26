# Third-party notices

## Three.js 0.180.0

Files in `web/vendor/` implement the renderer and its official controls/helpers. Upstream: https://github.com/mrdoob/three.js/tree/r180. The MIT notice is preserved in `web/vendor/THREE-LICENSE.txt` and source headers. The development dependency is pinned in `package-lock.json`.

## SK8-Engine decoders

Upstream: https://github.com/SK8-ENGINE/SK8-Engine, commit `311cd40e8a8f2c824586e4485f79d8aee8dcde8b`.

`studio/skate3/vendor/` contains the stream, collision and grind decoders with their original MIT license and per-file provenance in `LICENSE-SK8-ENGINE.txt` and `PROVENANCE.json`. NativeX's collision decoder change treats compression-mode-1 offsets as unsigned 16-bit values while preserving signed bases.

The Xbox tiled-address and packed-tail texture decoding in `studio/skate3/world_textures.py` also draws on SK8-Engine's MIT `retail_texture_decode.py`. Preserve the same attribution/license when redistributing that derived implementation.

## Format metadata

`research/v37_park_catalog.h` is an authored lookup table of display labels, categories and numeric recipe/arena identifiers used by the optional V37 adapter. It contains no meshes, textures, collision payloads, native executable code or game archive members. Hashes and resource identifiers elsewhere in the source are validation/format metadata, not distributable game content.

The licenses above cover software only. No upstream runtime, Xbox SDK, game archive or extracted game asset is bundled.
