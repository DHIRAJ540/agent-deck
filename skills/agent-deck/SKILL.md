---
name: agent-deck
description: >-
  Launches, manages, installs, or customizes Agent Deck — a zero-dependency live
  terminal dashboard and side-by-side local browser workspace for Antigravity
  (agy), Claude Code (claude), tmux panes, and open macOS terminals (Ghostty,
  iTerm2, Terminal.app, Warp, Cursor, VS Code). Use when the user asks to start,
  stop, check, share, or customize the terminal dashboard, view running agent
  tasks and git branches across terminals, or preview each session's localhost
  dev server in one UI.
---

# Agent Deck — Live Terminal & Local Browser Dashboard

Agent Deck gives developers a single live browser workspace (`http://localhost:7878`) for every active **Antigravity (`agy`)**, **Claude Code (`claude`)**, and terminal session on their machine — with **zero external `pip` or `npm` dependencies** (pure Python 3.8+ standard library).

## Key Capabilities

- **Top Agent Filter Tabs (`Both` · `agy` · `Claude`):** Switch at the top header between viewing **Both** agents together, **Antigravity (`agy`)** only, or **Claude Code (`claude`)** only — with live session counts and attention indicators.
- **Multi-Terminal Discovery:** Automatically tracks `tmux` panes, macOS `Terminal.app` & `iTerm2` tabs, external TTYs (`Ghostty`, `Warp`, `Cursor`, `VS Code`, `Antigravity IDE`), active `agy` conversations (`~/.gemini/antigravity-cli/`), and Claude Code sessions (`~/.claude/projects/`).
- **Rich Session Cards (Resizable Left Panel):** Displays the renamed `agy` / `claude` conversation or terminal title, status (`Needs you`, `Working`, `Ready`, `Quiet`), active git worktree folder, git branch + dirty count, current task, exact turn/activity timestamps, inline **Reply** composer, and `1-click Open` terminal jump button.
- **Direct Terminal Reply & 1-Click Option Selection:**
  - Sends prompts and keystrokes (`Enter`, `Esc`, `Ctrl+C`, `1`–`9`, `agy` & `claude` slash commands) directly to **Ghostty** (native Ghostty AppleScript `input text` + `send key`, without stealing window focus), **iTerm2**, **Terminal.app**, and **`tmux`** — right from the session card or the reply dock beneath the Live Browser.
  - Extracts pending `agy` (`ask_question` & command approvals) and `claude` (`AskUserQuestion` & `Bash`/`Edit`/`Write` permission prompts) plus TUI menus so users can click any option directly from Agent Deck.
- **Side-by-Side Live Browser Workspace (Right Panel):**
  - Auto-detects listening web server ports (`:3000`–`:9999`, Vite, Next.js, Astro, Uvicorn, etc.) inside each session's child process tree (`lsof`) and maps each card to `http://localhost:<port>`.
  - Maintains a **persistent per-session `<iframe>` pool** so switching cards on the left switches live browser views instantaneously without losing SPA route, scroll position, or React state.
  - Serves on `http://localhost:7878` (dual-stack `127.0.0.1` + `::1`) so embedded `http://localhost:<port>` apps stay **same-site** and preserve Firebase Auth (`IndexedDB`), `localStorage`, and cookies.
  - Includes a **1-click `Start dev server`** button (`yarn dev` / `pnpm dev` / `npm run dev` on an auto-picked free port), running local port quick-switcher, mobile/desktop viewport toggle, and custom per-session URL override.

---

## Launching & Managing Agent Deck

All runtime files are bundled inside [`./scripts/`](./scripts/).

### 1. Start (or Focus) the Dashboard

Run the bundled launcher helper:

```bash
bash <skill_dir>/scripts/start_agent_deck.sh
```

- Pass `--no-browser` when starting headlessly and returning the private `?token=...` URL to the user in chat.
- Pass `--port 7879` (or rely on default `--auto-port`) if port `7878` is busy.
- If running inside a terminal sandbox that blocks local port binding or host `ps`/`lsof` inspection, try sandboxed first and only retry `start_agent_deck.sh` outside the sandbox if blocked.

### 2. Check Status or Stop

```bash
bash <skill_dir>/scripts/start_agent_deck.sh --status
bash <skill_dir>/scripts/start_agent_deck.sh --stop
```

### 3. Install Standalone Copy to `~/agent-deck` (Optional)

If the user wants `~/agent-deck/agent_deck.py` installed in their home directory for direct terminal invocation:

```bash
bash <skill_dir>/scripts/start_agent_deck.sh --install
```

---

## Sharing This Skill With Teammates

Teammates only need **Python 3.8+** (`tmux` is optional and only required if creating managed `tmux` sessions). Share the entire `agent-deck/` skill folder via either method:

1. **Repo-wide (recommended for teams):**
   Copy the `agent-deck/` folder into `<repo>/.agents/skills/agent-deck/` and commit to Git. Every teammate using Antigravity in that repository automatically gets the `agent-deck` skill.
2. **Machine-wide (across all repositories):**
   Copy the `agent-deck/` folder into `~/.gemini/config/skills/agent-deck/`.

---

## Customizing or Extending Agent Deck

Before modifying backend discovery, port mapping, or UI components:

1. Read [references/architecture.md](./references/architecture.md) for data-flow details, API endpoints, and UI design rules.
2. Validate Python and JavaScript syntax after any edit:
   - `python3 -m py_compile <path>/agent_deck.py`
   - `node --check <path>/static/app.js`
3. If both `~/agent-deck/` and `<skill_dir>/scripts/` exist on the machine, keep both copies synced or run `--install` after updating `<skill_dir>/scripts/`.
