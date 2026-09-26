# Optional Xbox collection, install and recovery

Normal world browsing and editing run on your computer. Only use the Xbox paths if you have an independently configured console with XBDM and a supported Skate 3 installation. No console plugin, game, title update, firmware tool or native-menu binary is supplied here.

Start with an explicit console IPv4 address:

```sh
python3 -m studio.server --xbox 192.168.1.50
```

The default game content path is `Hdd:\skate 3\data\content`. For a different path, set `NATIVEX_XBOX_CONTENT` before starting Python, for example:

```sh
# macOS/Linux
export NATIVEX_XBOX_CONTENT='Usb0:\Games\Skate 3\data\content'
python3 -m studio.server --xbox 192.168.1.50
```

```powershell
# Windows PowerShell
$env:NATIVEX_XBOX_CONTENT = 'Usb0:\Games\Skate 3\data\content'
py -3 -m studio.server --xbox 192.168.1.50
```

Use your own address/path. Collection reads the named original archive and then builds a local cache. The console and Studio should remain on a trusted local network.

## Experimental map deployment

Build from the admitted immutable source, reopen the exported archive, and save a walked route report. Quit Skate 3 to Aurora before installing. The installer verifies the running dashboard, source hashes and plan identity, stages the archive, verifies the full staged bytes, preserves original/previous archives, replaces the live archive, and verifies full readback. It does not launch the game for you.

The current writer is tied to verified Black Box source bytes. A different release, modified source, missing evidence or known failure causes refusal. Do not bypass it. Copied sections are currently blocked because their Xbox collision is unresolved.

Use **Restore original Xbox map** or **Restore previous working map** with Aurora open if a test fails. Keep local build/deployment reports and the console backup folder at `Hdd:\Apps\NativeXWorldStudio\SectionTests`. An uncertain network result must be inspected before retrying; never delete the backup to make a retry succeed.

## Separate V37 live-object adapter

The `/objects.html` workspace contains a legacy adapter for one exact NativeX V37 build and Skate 3 TU3. It uses guarded command mailboxes and tracked object serials. It does not accept V41/V42 or an arbitrary plugin with a similar name. Without that separate exact plugin, the adapter will refuse; offline world import/editor features still work.

The in-game world editor is a separate development effort. Downloading this repository does not install it.
