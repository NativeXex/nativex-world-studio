# Contributing

Open an issue or pull request describing the concrete behavior, reproduction steps and validation. Keep game data on your own computer. Use synthetic examples and redacted error messages in reports; do not attach `.big`, `.rx2`, decoded meshes/textures, memory dumps, game executables or SDK files.

Run the Python and JavaScript tests plus `tools/audit_public.py` from the README. New parser and file-writing behavior should include meaningful malformed-input, source-preservation and failure/recovery tests. Preserve third-party copyright/license notices.

For exports, report separately: source/archive validation, local reimport/walk result, full transfer/readback, and actual Xbox gameplay result. A visible mesh is not evidence of collision or grinds. Do not relax source-hash, exact-plugin, backup, Aurora or full-readback checks to make a test pass.

Do not copy local session reports into this repository. Add synthetic regression fixtures for a discovered format issue instead. Test optional hardware changes only on a user-authorized console with a recoverable original backup.
