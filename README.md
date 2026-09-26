# NativeX World Studio

**A local world browser and experimental level editor for Skate 3 on Xbox 360.**

Bring your own extracted game files. Browse real world geometry and textures, fly around levels, inspect collision and grind paths, save layouts, and experiment with the supported Black Box export workflow.

**Alpha / research software.** This repository is the desktop tool. It does not include Skate 3, extracted game assets, an Xbox executable, the NativeX in-game menu, Microsoft SDK files, or console plugins.

## Start here

You need **Python 3.11 or newer**, a modern WebGL2 browser, and a readable extracted Skate 3 installation. The browser renderer is bundled; starting Studio does not require npm, a server account, Codex, or an API key.

```sh
git clone https://github.com/NativeXex/nativex-world-studio.git
cd nativex-world-studio
python3 -m studio.server --open
```

On Windows, use `py -3` in place of `python3`. On macOS, you can also run `Launch NativeX World Studio.command`. Keep the terminal open while using Studio.

Studio listens at **http://127.0.0.1:8378**. If that port is occupied, use `--port 8380`. Launching again at the same port reopens an existing Studio session.

### Use an SSD containing Skate 3

1. Connect the SSD and make sure your computer can read its files.
2. In Studio, enter the path to the extracted **Skate 3 game folder**, or directly to its **data/content** folder.
3. Choose **Use this folder**. Studio looks for known `.big` archives; it does not scan the entire drive.
4. Choose **Import local archive** on a world card. Start with **Black Box Park**.
5. Wait for decoding to finish, then choose **Open world**.

For example, an extracted installation contains:

```text
Skate 3/
  default.xex                  # Your file; never copied into this repository
  data/
    content/
      worldDIST_BlackBoxPark.big
      worldDIST_University.big
      parkassets.big
```

An SSD alone is not enough if its filesystem is unreadable by your OS, or the game exists only as an ISO/GOD container. This tool does not mount FATX, decrypt containers, or extract disc images. Supply a readable game folder you are entitled to use.

Imports read the source and write a verified local copy/cache inside this checkout. **The SSD's game installation is not edited by import.** Cached worlds can be browsed after disconnecting the source drive. Allow space for the archive copy, extracted resources, decoded textures and subsequent exports; larger districts need substantially more space than Black Box.

You can also import from a terminal:

```sh
python3 -m studio.importer --game-dir "/path/to/Skate 3" --world blackbox
python3 -m studio.server --open
```

Available world keys appear in `python3 -m studio.importer --help`. Being listed does not mean every resource in that world is supported. Partial imports retain explicit error reports. Mega Park is an overlay and requires a composed University base; standalone import is blocked.

For the optional object-library workspace:

```sh
python3 -m studio.importer --game-dir "/path/to/Skate 3" --assets
```

Restart Studio after building that catalogue, then open `/objects.html`.

## What works, and what does not

| Feature | Current status |
| --- | --- |
| Start with no game files; select a local SSD/game folder | Supported |
| Local geometry/texture browsing | Black Box, University and Skate School exercised during development; other worlds may be partial |
| Fly/orbit, select sections, move/rotate/copy/hide, undo/redo, save `.nxlevel.json` plans | Local editor preview |
| Collision and grind overlays; walking a decoded archive/layout | Local diagnostics, not Xbox certification |
| Rearrange three curated Black Box obstacle groups | Native writer; moved-object builds have been tested on Xbox |
| Build/reopen translated Black Box sections | Experimental, limited to admitted source/layouts |
| Duplicate complete sections with working Xbox collision | **Unresolved; install blocked for copied sections** |
| Arbitrary world export, new geometry, general rotation/deletion export | Not supported |
| In-game NativeX free-camera/world editor | Separate project; not bundled here |
| Live object-layout adapter | Requires the exact separate NativeX V37 build; not compatible with arbitrary menu versions |
| Skate 2 previews | Experimental source decoder; no Skate 3 conversion or runtime support |

The curated writer moves the manual pad, wedge/ledge, and rear platform/rail as complete groups. It checks footprint/floor coverage and moves the admitted geometry, collision and grind data together. It does not rebuild baked lighting, so old shadows can remain.

A whole world section is different from an independently spawned object. In the observed duplicate failure, graphics moved but static collision was registered at the original location. The browser's transformed collision preview can therefore look correct even when Xbox physics is not. See [current limitations and roadmap](docs/STATUS.md).

## Controls and saved work

- **World inspector:** drag to orbit, right-drag to pan, scroll to zoom; select a section; W/E for move/rotate, Q to select, F to focus.
- **Flight:** drag to look; WASD to move; Q/E down/up; Shift faster.
- **Collision walk:** WASD, drag to look, Space to jump, Escape for overview.
- **Curated park editor:** W move, Q select, F focus, arrows to nudge, Escape to cancel.

Original source copies, decoded caches, settings, plans, exports and reports are stored in ignored `data/` and `web/worlds/` directories. Back those up yourself if you need them. Source archives are kept separate from exports. Do not upload archives or extracted assets in issues or pull requests.

## Optional Xbox connection

Offline use needs no Xbox. Network collection/testing needs a separately configured Xbox 360 with **XBDM**, reachable on the same trusted LAN. This repository does not install XBDM, modify firmware, supply title updates, or deploy the NativeX menu.

```sh
python3 -m studio.server --xbox 192.168.1.50 --open
```

Replace that example with your console's address. There is no default console address and no automatic connection on startup. The default console content path is `Hdd:\skate 3\data\content`; set `NATIVEX_XBOX_CONTENT` before launch if yours differs. See [Xbox setup and recovery](docs/XBOX.md).

For supported map experiments, the workflow is:

1. Save the layout and **Build Xbox map**.
2. Reopen the actual exported `.big`, walk it locally, and save the report.
3. Quit Skate 3 to **Aurora**.
4. **Install test map**: preserve original/previous files, transfer, and verify complete readback.
5. Launch Skate 3 and test the map and collision yourself.

Passing local checks is not proof that the console will load or skate correctly. The installer rejects changed sources, missing walk evidence, known failed builds and copied-section layouts. Recovery controls restore the original or previous map. Keep the tool and its local reports until the test is complete.

## Optional Codex workflow

Yes—Codex can work with this tool locally. Open this cloned folder as a local project on the computer that can read your SSD, and use the included CLI/API. A GitHub connection provides repository access; it does not itself mount your SSD or connect to an Xbox.

```sh
python3 -m studio.cli status
python3 -m studio.cli worlds
python3 -m studio.cli connect-folder "/path/to/Skate 3"
python3 -m studio.cli import-world blackbox
```

Studio must already be running. Codex is optional and is not embedded in the application. There is no bundled NativeX MCP server or automatic AI model integration. See [Codex and local API instructions](docs/CODEX.md), including example prompts and the distinction between local and cloud tasks.

## Development

The Python runtime uses the standard library. JavaScript development tests use the pinned Three.js package:

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm ci --ignore-scripts
npm test
python3 tools/audit_public.py
```

These tests use synthetic fixtures and need no game files or console. CI runs them on Linux, macOS and Windows. Real-archive and hardware validation remain separate, user-supplied tests. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License and credits

NativeX-authored software is [MIT licensed](LICENSE), copyright NativeX contributors. Bundled Three.js and SK8-Engine decoder code retain their own MIT notices and provenance; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Game names are used for identification. This project is independent of Electronic Arts and Microsoft. The software license does not grant rights to game data, maps, textures, audio, executables or SDKs. **No game content is distributed in this repository.**
