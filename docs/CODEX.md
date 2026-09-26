# Use NativeX World Studio with Codex

Studio works independently. For optional assistance, clone this repository and open the folder as a **local project** in Codex on the computer with your mounted game drive. Tell Codex the game folder path and allow the local file access needed for that task.

A GitHub connector lets an assistant work with repository source. It does not provide access to your SSD or console. A cloud task cannot automatically reach your local drive, localhost server or Xbox LAN address. Use a local task for those operations.

## Local CLI

Start Studio in a terminal:

```sh
python3 -m studio.server --open
```

Then an assistant or script can use:

```sh
python3 -m studio.cli status
python3 -m studio.cli connect-folder "/path/to/Skate 3"
python3 -m studio.cli import-world blackbox
python3 -m studio.cli worlds
python3 -m studio.cli projects
python3 -m studio.cli save-plan data/level-projects/my-plan.nxlevel.json
python3 -m studio.cli build data/level-projects/my-plan.nxlevel.json
python3 -m studio.cli build-status BUILD_SHA256
```

`--port` goes before the subcommand when using a non-default server port. Import runs in the local background worker; query `worlds` for progress. The client fetches a per-session token for local write requests and never prints that token in `status`.

Example prompt:

> Read README.md and AGENTS.md. My own extracted Skate 3 installation is at [path]. Start Studio locally, connect that folder, import Black Box and open the world editor. Keep my source files unchanged. Do not connect to or install anything on my Xbox yet.

For a console test, explicitly name the console and requested install. Keep the original/previous backups and complete readback verification. Do not ask an assistant to bypass the known duplicate-collision block.

## API and MCP

The CLI calls the existing loopback HTTP API. Read routes include `/api/worlds`, `/api/library`, `/api/levels` and `/api/level-builds/<id>`. POST requests need the token returned by `/api/bootstrap` in `X-NativeX-Token`; the service checks the local Host and Origin. Do not expose this service publicly.

This release does **not** include a NativeX MCP server, Codex plugin, model API integration or API-key requirement. Codex can operate the CLI using its normal local tools. An MCP wrapper could be added later for explicit tool discovery; it is not required to use this repository.

Official references: [local desktop projects](https://learn.chatgpt.com/docs/app) and [Codex MCP configuration](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). These describe Codex itself, not an endorsement or automatic integration of NativeX.

Game files stay outside Git. If sharing a Codex task, issue or transcript, avoid including raw game contents, credentials or private filesystem details.
