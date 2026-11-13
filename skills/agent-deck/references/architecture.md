# Agent Deck Architecture & Customization Reference

## File Layout

- [`scripts/agent_deck.py`](../scripts/agent_deck.py): Single-file Python 3 stdlib HTTP + SSE server, process-tree scanner, Antigravity & Claude Code metadata reader, TCP port mapper, and managed dev-server launcher.
- [`scripts/static/index.html`](../scripts/static/index.html): Workspace shell with top agent selector tabs (`#agentTabs`: `Both` | `agy` | `Claude`), resizable left session sidebar (`#sidebar`, `#sidebarResizer`), right-hand live browser & terminal inspector (`#detail`), multi-session grid wall (`#gridWall`), and `New session` dialog (`#newDlg`).
- [`scripts/static/styles.css`](../scripts/static/styles.css): Light/dark/system theme tokens (`IBM Plex Sans` + `IBM Plex Mono`), agent selector tabs, card layout, browser toolbar & viewport frame rules, and ANSI 16/256/TrueColor classes.
- [`scripts/static/app.js`](../scripts/static/app.js): SSE live stream client, persisted `agentFilter` (`both` / `agy` / `claude`), persistent per-session `<iframe>` pool (`browserFramePool`), URL/port switcher, ANSI-to-HTML renderer, and keyboard shortcuts (`j`/`k`, `1`–`9`, `r` reload, `b` browser/logs, `i` reply, `v` grid, `n` new).
- [`scripts/start_agent_deck.sh`](../scripts/start_agent_deck.sh): Idempotent start/status/stop/install wrapper storing PID and startup log in `~/.agent-deck/`.

## Discovery & Metadata Pipeline (`agent_deck.py`)

1. **Process Snapshot (`scan_process_table`):**
   - Executes `ps -axo pid=,ppid=,tty=,etime=,args=` to capture process hierarchy, controlling TTYs, and exact elapsed uptime (`agent_since_exact`).
   - Classifies known agent CLIs (`KNOWN_AGENTS`: `agy` and `claude`, including `~/.local/share/claude/versions/*`) while excluding Agent Deck's own PID tree (`self_pids`).
   - Skips child sub-PTYs spawned under an ancestor PID that already owns another TTY so background tasks do not create duplicate cards.
   - Ignores background editor daemons (`DAEMON_SUBTOOLS` such as `esbuild --ping`, `tsserver`, `watchman`, `gitstatusd`) when determining foreground tasks.

2. **Antigravity (`agy`) & Claude Code (`claude`) Linking & Pending Action Extraction:**
   - **Antigravity (`agy`):** Matches `agy` PIDs against `~/.gemini/antigravity-cli/presence/*.lock` to resolve `conversation_id`, queries `~/.gemini/antigravity-cli/conversation_summaries.db` (read-only SQLite URI) for renamed conversation titles and run/wait status, and reads `~/.gemini/antigravity-cli/brain/<conv_id>/.system_generated/logs/transcript.jsonl` to infer active worktree, latest task, `ask_question` choices, and unsandboxed command approvals.
   - **Claude Code (`claude`):** Matches `claude` sessions against `~/.claude/projects/<sanitized-cwd>/<uuid>.jsonl` (`_find_claude_transcript_path`, `_read_claude_transcript`, `extract_claude_pending_action`) to resolve session title, active worktree, latest task, `AskUserQuestion` choices, and `Bash`/`Edit`/`Write` permission prompts.
   - **Ghostty Native AppleScript Bridge:** Maps Ghostty TTYs to Ghostty's AppleScript `terminals` UUIDs (`macos_list_ghostty_terminals`, `match_ghostty_surfaces`, distinguishing `agy` `"<title> — <folder>"` and `claude` `"✳ <title>"` / braille spinner tab titles) so Agent Deck can focus exact Ghostty tabs (`focus t`) and inject replies/choices (`input text` + `send key`) without stealing focus.

3. **Listening Port Mapping (`scan_listening_ports`, `attach_browser_metadata`):**
   - Runs `lsof -nP -iTCP -sTCP:LISTEN -Fpcfn` (cached 2.5s) to map listening TCP ports (`1024 <= port < 49152`) to owning PIDs while filtering desktop GUI apps, DB ports, and Agent Deck's own port.
   - **Pass 1:** Matches child PIDs inside a session's `lineage_pids` (or `MANAGED_SERVERS`) directly to its listening port (`dev :<port>` -> `http://localhost:<port>`).
   - **Pass 2:** Matches remaining unclaimed ports whose git worktree `cwd` equals the session's `cwd`.
   - Custom per-session URLs are persisted in `~/.agent-deck/meta.json` under `"browser_urls"`.

4. **Same-Site `localhost` Dual-Stack Server:**
   - Binds both IPv4 `127.0.0.1` and IPv6 `::1` and redirects `GET /` on `127.0.0.1` to `http://localhost:<port>/?token=...` so the top-level dashboard and embedded `http://localhost:<dev_port>` iframes share the `localhost` site boundary (unpartitioned `IndexedDB`, `localStorage`, and cookies).
   - Every HTTP/SSE request requires the random startup token (`X-Deck-Token` header, `deck_token` `HttpOnly; SameSite=Strict` cookie, or `?token=` query parameter) and verifies `Host` is loopback.

## HTTP API Summary

- `GET /?token=<token>` — Serves dashboard UI and sets `deck_token` cookie.
- `GET /api/stream?token=<token>` — Server-Sent Events stream pushing `STATE` snapshots (`sessions`, `events`, `local_ports`, `recent_cwds`).
- `GET /api/state` — Latest JSON snapshot fallback.
- `GET /api/output?pane=<id>&lines=800&hash=<sha1>` — ANSI & plain terminal/transcript buffer for a session.
- `POST /api/action` — Session actions: `open_terminal`, `open_new_terminal`, `start_dev_server`, `stop_dev_server`, `adopt`, `dismiss`, `send`, `keys`, `ack`, `respawn`, `kill`.
- `POST /api/label` — Persists `label` (note), `pinned`, `browser_url` override, or `restore_dismissed`.
- `POST /api/new` — Creates a new managed `tmux` session.
