# Public snapshot validation

Validated locally on macOS with Python 3.14.6 and Node.js 22.23.2:

- 19 source-only Python tests: empty-checkout HTTP startup, Host/Origin/token checks, path traversal refusal, game-folder discovery, verified copies, source preservation, disconnected drive handling, different-cache refusal, no default Xbox connection, duplicate-install refusal, and simulated backup/rollback flows.
- 5 source-only JavaScript tests: selection identity, snapped movement, preview preservation, transform conventions and local collision-walk placement. Local collision tests do not establish Xbox collision correctness.
- Fresh Black Box import through the new SSD/folder importer: four sections, 132 mesh parts, 12,978 render triangles, 88 textures, 12,597 decoded collision triangles, 120 grind rails. No missing diffuse texture references. Source and copied archive match byte-for-byte; unchanged reconstruction also matches.
- Browser check: the standalone instance renders the imported Black Box environment, section list and import evidence. No Xbox connection is configured or used by these checks.
- CLI check: status reaches the local service; session tokens are not included in its output.
- Publication audit: only approved text source/docs and licensed dependencies are tracked. Local test archives, generated world bundles, settings and all game content remain ignored.

CI repeats the synthetic Python/JavaScript checks and publication audit on Linux, macOS and Windows. Check the workflow result for the particular commit you use. Real game import behavior was exercised locally on macOS; other platform game-import behavior still needs user testing.
