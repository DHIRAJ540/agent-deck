# Agent Deck

One live dashboard and side-by-side local browser workspace for all your **Antigravity (`agy`)** and developer terminal sessions — with **zero external `pip` or `npm` packages** (pure Python 3.8+ standard library).

## Highlights

- **Discovers All Your Active Terminals Automatically:** Tracks `tmux` panes, macOS `Terminal.app` & `iTerm2` tabs, external TTYs (`Ghostty`, `Warp`, `Cursor`, `VS Code`, `Antigravity IDE`), and live `agy` conversations (`~/.gemini/antigravity-cli/`).
- **Clear Per-Session Context (Resizable Left Panel):** Shows the renamed conversation/terminal title, status (`Needs you`, `Working`, `Ready`, `Quiet`), active git worktree folder, git branch + dirty count, current task, accurate turn/activity duration, and a 1-click **Open** terminal button.
- **Side-by-Side Live Local Browser (Right Panel):**
  - Automatically detects listening dev server ports (`:3000`–`:9999` — Vite, Next.js, Astro, Uvicorn, etc.) inside each session's process tree (`lsof`) and maps each card to `http://localhost:<port>`.
  - Keeps a **stateful per-session `<iframe>` pool** so switching cards on the left switches browser views instantaneously without losing SPA route, open modals, or form state.
  - Serves on `http://localhost:7878` (dual-stack `127.0.0.1` + `::1`) so embedded `http://localhost:<port>` apps stay same-site and share `IndexedDB` (e.g. Firebase Auth), `localStorage`, and cookies.
  - Includes a **1-click `Start dev server`** launcher (`yarn dev` / `pnpm dev` / `npm run dev` on an auto-assigned free port), running local port quick-switcher, mobile/desktop viewport toggle, and custom URL override.

---

## Install as an Antigravity (`agy`) Skill

### Global Install (All Repos on Your Machine)

```bash
git clone https://github.com/DHIRAJ540/agent-deck.git ~/agent-deck
mkdir -p ~/.gemini/config/skills
ln -s ~/agent-deck/skills/agent-deck ~/.gemini/config/skills/agent-deck
```

Then ask `agy` in any project: **"start agent deck"** or **"open the terminal dashboard"**.

### Repo-Level Team Install

Copy `skills/agent-deck` into `<your-repo>/.agents/skills/agent-deck` and commit to Git so every teammate gets the skill automatically.

---

## Direct CLI Usage

```bash
bash ~/agent-deck/skills/agent-deck/scripts/start_agent_deck.sh
```

Or run the server directly:

```bash
python3 ~/agent-deck/agent_deck.py --auto-port
```

Helper flags:
- `bash skills/agent-deck/scripts/start_agent_deck.sh --status` — Check running PID & private URL
- `bash skills/agent-deck/scripts/start_agent_deck.sh --stop` — Stop background server
- `--port 7878` — Preferred port (default `7878`)
- `--auto-port` — Automatically pick the next free port if busy
- `--no-browser` — Print the private `?token=...` URL without opening a browser tab

*(Note: `tmux` is optional. External terminal discovery and live browser views work out of the box with Python 3.8+; install `tmux` via `brew install tmux` if you also want managed `tmux` sessions.)*

---

## Keyboard Shortcuts

| Key | Action |
|---|---|
| `j` / `k` or `↑` / `↓` | Switch session card |
| `1` – `9` | Jump to session 1–9 |
| `r` | Reload active session's browser view |
| `b` | Toggle right panel between **Browser** and **Logs** |
| `/` or `i` | Focus URL bar (in Browser view) or prompt composer (in Logs view) |
| `v` | Toggle Focus Workspace / Multi-Session Grid Wall |
| `n` | Start a new `tmux` session |
