# Agents Cockpit

A lightweight browser console for local Codex and Claude Code sessions.

This build uses structured web rendering:

- Creating a conversation opens the built-in web-rendered Codex or Claude view.
- The browser talks to `web.py`; `web.py` supervises `manager.py`.
- Claude sessions run the Claude CLI in stream-json mode through `native.py`.
- Codex sessions run `codex app-server --stdio` through `codex_native.py`.
- Frontend CSS/JS is served from `assets/`; `index.html` is kept as mostly markup.

## Requirements

- Python 3.8+ (standard library only for the core app)
- Codex CLI installed and runnable as `codex`, Claude Code CLI installed and runnable as `claude`, or either configured in `config.ini` under `[binaries]`
- An `auth.txt` login file copied from `auth.txt.example`

## Quick Start

```bash
cp auth.txt.example auth.txt
# edit auth.txt and set a strong password
python app.py
```

On Windows you can also use:

- `start.cmd` for background mode
- `start-fg.cmd` for foreground/debug mode
- `stop.cmd` to stop web, manager, and running sessions

On Linux/macOS:

- `./start.sh`
- `./start-fg.sh`
- `./stop.sh`

The console URL and login user are printed on startup.

## Configuration

Copy `config.example` to `config.ini` when you need overrides.

Common keys:

| Key | Default | Description |
| --- | --- | --- |
| `[server] port` | `7682` | Browser-facing port |
| `[server] host` | `0.0.0.0` | Browser-facing bind address |
| `[manager] port` | `server.port + 1000` | Local manager port |
| `[binaries] claude` | auto-detect | Absolute path to Claude CLI |
| `[binaries] codex` | auto-detect | Absolute path to Codex CLI |
| `[paths] claude_home` | `~/.claude` | Claude transcript/config home |
| `[paths] auth_file` | `auth.txt` | Login credential file |
| `[users] data_dir` | `.agent-cockpit/users` | Local per-user cockpit state |
| `[users] default_workspace_root` | `.agent-cockpit/users/{uid}/workspace` | Default workspace root for each login user |
| `[users] allow_unconfigured_paths` | `1` | Allow any local path; set `0` to restrict to workspace roots |
| `[users] primary_user_uses_default_homes` | `1` | First `auth.txt` user keeps default Codex/Claude homes |
| `[approval] auto_approve` | `1` | Pass `--dangerously-skip-permissions`; set `0` for web approval gates |
| `[codex_dynamic_tools] <tool>` | empty | Explicitly map safe Codex dynamic tools to `mcp:<server>/<tool>` passthrough targets |
| `[security] session_ttl` | `86400` | Login cookie lifetime in seconds |
| `[security] cookie_secure` | `0` | Set `1` only behind HTTPS |

`[codex_dynamic_tools]` is an allowlist, not a wildcard execution mode. Use
keys like `namespace.tool`, `namespace.*`, or `tool`; unmapped dynamic tools
fail visibly instead of being executed or reported as successful.

## Session Model

- New conversation: choose a local directory and select Codex or Claude.
- Codex conversations support image paste/file selection; images are stored in
  the session upload directory and sent to Codex as `localImage` inputs.
- Each login user has separate cockpit state under `.agent-cockpit/users/<uid>/` and may only browse or launch inside their configured workspace roots.
- Claude history and config are per-user through `CLAUDE_CONFIG_DIR`; Codex app-server runs with per-user `CODEX_HOME` under the cockpit state directory.
- For compatibility, the first `auth.txt` user keeps the normal Codex/Claude homes when `[users] primary_user_uses_default_homes = 1`.
- Running sessions are recovered from the per-user cockpit state after manager soft-restart.
- Multiple browsers can watch the same session through the app WebSocket.
- `manager.py` can soft-restart and recover persisted native session state from `.agent-cockpit/`.

## Code Layout

- `common_*.py` contains shared auth, process, registry, history, browse, notify, websocket, and HTTP helpers; `common.py` re-exports the compatibility surface.
- `manager_sessions.py`, `manager_user_api.py`, and `manager_internal_api.py` hold the manager's lifecycle and API logic.
- `native_*.py` contains Claude CLI config, gate, replay, and process helpers used by `native.py`.
- `codex_*.py` contains Codex app-server client, event, request, replay, routing, text/form, history, and session-event helpers used by `codex_native.py`.
- `assets/` contains the split browser app scripts and stylesheet.
- `REFACTOR_PROGRESS.md` records the current split status, remaining targets, and validation bundle.

## Security Notes

This app can execute commands on the host through Codex or Claude tools. Use a strong password and expose it only on trusted networks or behind HTTPS/VPN.

For password hashes:

```bash
python -c "import common; print(common.hash_password('your-password'))"
```

## License

MIT
