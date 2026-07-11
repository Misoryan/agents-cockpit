# Agents Cockpit

A lightweight browser console for local Codex and Claude Code sessions.

This build uses structured web rendering:

- Creating a conversation opens the built-in web-rendered Codex or Claude view.
- The browser talks to `web.py`; `web.py` supervises `manager.py`.
- Claude sessions run the Claude CLI in stream-json mode through `native.py`.
- Codex sessions run `codex app-server --stdio` through `codex_native.py`.

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
| `[approval] auto_approve` | `1` | Pass `--dangerously-skip-permissions`; set `0` for web approval gates |
| `[security] session_ttl` | `86400` | Login cookie lifetime in seconds |
| `[security] cookie_secure` | `0` | Set `1` only behind HTTPS |

## Session Model

- New conversation: choose a local directory and select Codex or Claude.
- Claude resume history is read from `~/.claude/projects/**/*.jsonl`; Codex running sessions are recovered from `.agent-cockpit/` after manager soft-restart.
- Multiple browsers can watch the same session through the app WebSocket.
- `manager.py` can soft-restart and recover persisted native session state from `.agent-cockpit/`.

## Security Notes

This app can execute commands on the host through Codex or Claude tools. Use a strong password and expose it only on trusted networks or behind HTTPS/VPN.

For password hashes:

```bash
python -c "import common; print(common.hash_password('your-password'))"
```

## License

MIT
