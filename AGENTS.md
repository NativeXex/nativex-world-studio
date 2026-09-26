# NativeX World Studio contributor instructions

This repository contains the desktop tool, not the game or native menu binary. Read README.md and docs/STATUS.md before changing export or console behavior.

- Never commit user game archives, extracted/decoded assets, saved sessions, console backups, memory dumps, binaries, SDKs or secrets. data/ and web/worlds/ are intentionally ignored. Do not use git add -f for them.
- Source installations are read-only inputs. Write exports and verified caches to local generated directories. Preserve the immutable original and previous-file recovery in deployment code.
- Do not claim local collision previews validate Xbox physics. Whole-section duplicate collision is unresolved and installation must remain blocked until a separately demonstrated fix.
- Keep localhost binding, Host/Origin validation, local session tokens and exact-build/epoch checks. Console writes must be explicitly requested; ordinary browsing must remain offline.
- Test with synthetic fixtures. Run Python unittest discovery, npm test, and tools/audit_public.py. Do not request game assets for a pull request.
- NativeX in-game V37/V41/V42 development is a separate project; do not merge its game/SDK inputs here.
