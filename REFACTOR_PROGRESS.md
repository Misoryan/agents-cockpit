# codex-web refactor progress

This note records the current refactor state for the local Agents Cockpit
checkout. It is intentionally concise so future changes can stay incremental.

## Current Structure

- `app.py` selects web mode, manager mode, or stop/help commands.
- `web.py` owns browser login, restart/stop endpoints, static assets, and proxying to the manager.
- `manager.py` is now a thin HTTP/WebSocket shell; session lifecycle lives in `manager_sessions.py`, internal gate/control endpoints in `manager_internal_api.py`, and browser APIs in `manager_user_api.py`.
- `common.py` is now mostly a compatibility facade over focused helpers such as `common_auth.py`, `common_process.py`, `common_history.py`, `common_registry.py`, and `common_http.py`.
- `native.py` keeps the Claude session class while delegating CLI argv/process/replay/gate helpers to `native_*.py` modules.
- `codex_native.py` keeps the Codex session class while delegating app-server client, routing, requests, replay, text/form/history, thread-history conversion, and notification lifecycle helpers to `codex_*.py` modules.
- `index.html` is now mostly markup. Frontend assets live under `assets/`, split into app shell/sidebar/state/native/replay/socket/action/auth/icon files.

## Completed Items

- Multi-user gate calls carry internal auth and user context through `gate_mcp.py` and per-session MCP config.
- Manager internal routes are separated from browser routes and covered by boundary tests.
- `/api/nsend` has a backend busy guard.
- Claude replay/polling has stable `seq`/dedupe support.
- Codex replay recovery avoids startup app-server I/O and drops recovery-only noise.
- Frontend history loading requests live Codex history with `live_codex=1`.
- Unused launch/settings `args` UI was removed because the backend does not consume it.
- Static frontend CSS/JS is served through `/assets/*` with traversal protection.

## Optional Follow-ups

- Reduce `codex_native.py` further only if the remaining session core grows again; thread-history conversion is now in `codex_thread_history.py`.
- Decide whether `web.py` should be split into auth, proxy, and lifecycle helpers; current size is acceptable but still mixed.
- For release hardening, restart web/manager and manually exercise login, launch, replay, ask/approve, and reconnect flows.

## Validation Bundle

Run this bundle after behavior changes:

```powershell
python -m py_compile app.py web.py common.py manager.py native.py codex_native.py gate_mcp.py codex_client.py codex_events.py codex_forms.py codex_history.py codex_replay.py codex_requests.py codex_routing.py codex_session_events.py codex_text.py codex_thread_history.py common_auth.py common_binaries.py common_browse.py common_ccswitch.py common_history.py common_http.py common_notify.py common_process.py common_registry.py common_users.py common_ws.py manager_internal_api.py manager_sessions.py manager_user_api.py native_cli.py native_config.py native_gate.py native_replay.py
Get-ChildItem assets\*.js | Sort-Object Name | ForEach-Object { node --check $_.FullName }
Get-ChildItem tests\check_*.py | Sort-Object Name | ForEach-Object { python $_.FullName }
git diff --check
```
