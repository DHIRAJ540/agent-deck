#!/usr/bin/env python3
"""
Agent Deck v2.7: live multi-session dashboard & local browser workspace for
Antigravity (agy), Claude Code (claude), and developer terminals across tmux and macOS.

Key capabilities
  - Top-level filter tab to view Antigravity (agy), Claude Code, or Both side-by-side
  - Discovers tmux panes, macOS Terminal.app / iTerm2 tabs, Ghostty surfaces, third-party TTYs
    (Warp, VS Code, Cursor, Antigravity IDE), and live agy brain sessions
  - Extracts terminal/conversation title, git branch, local dev server port, and current task
  - Direct terminal reply & 1-click option/approval buttons across tmux, Ghostty, iTerm2 & Terminal.app
  - Full ANSI color rendering (16 / 256 / TrueColor), SSE live updates, zero pip deps
"""

import argparse
import hashlib
import json
import os
import queue
import re
import secrets
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

# ---------------------------------------------------------------------------
# Constants & detection patterns
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
IS_MAC = sys.platform == "darwin"
MY_PID = os.getpid()

SHELLS = {
    "bash", "zsh", "fish", "sh", "dash", "ksh", "tcsh", "csh",
    "nu", "pwsh", "login", "-zsh", "-bash", "-fish", "-sh",
}

WRAPPERS = {"env", "nohup", "caffeinate", "arch", "nice", "time", "sudo"}

# Background helper daemons spawned by editors/CLI tools that do not mean an active user command is running.
DAEMON_SUBTOOLS = {
    "esbuild", "tsserver", "watchman", "fseventsd",
    "gitstatusd", "gitstatusd-darwin-arm64", "gitstatusd-darwin-x86_64",
}
DAEMON_ARG_RE = re.compile(r"(?:^|\s)(?:--ping|--service(?:=|\s)|--lsp|--stdio)(?:\s|$)", re.I)

DEV_SERVER_RE = re.compile(
    r"(?:^|/|\s)(?:vite|next\s+dev|nuxt\s+dev|webpack-dev-server|react-scripts\s+start|ng\s+serve|astro\s+dev)(?:\s|$)"
    r"|\b(?:npm|pnpm|bun)\s+run\s+(?:dev|start|serve)\b"
    r"|\byarn\s+(?:--cwd\s+\S+\s+)?(?:run\s+)?(?:dev|start|serve)\b",
    re.I,
)
PORT_ARG_RE = re.compile(r"(?:--port|-p)(?:=|\s+)(\d{2,5})\b")
ABS_PATH_TOKEN_RE = re.compile(r"((?:/Users/|/home/|/tmp/wt-)[^\s\"'`]+)")

# Detect Claude Code CLI processes (native binary, Homebrew, or npm package).
CLAUDE_PROC_RE = re.compile(
    r"(?:^|/|\s)claude(?:-code)?(?:\s|$)|@anthropic-ai/claude-code|/\.local/share/claude/versions/",
    re.IGNORECASE,
)

KNOWN_AGENTS = [
    ("agy", re.compile(r"(?:^|/)(?:agy|antigravity(?:-cli)?)(?:\s|$)", re.I)),
    ("claude", CLAUDE_PROC_RE),
    ("codex", re.compile(r"(?:^|/)codex(?:\s|$)", re.I)),
    ("gemini", re.compile(r"(?:^|/)gemini(?:-cli)?(?:\s|$)", re.I)),
    ("aider", re.compile(r"(?:^|/)aider(?:\s|$)", re.I)),
    ("opencode", re.compile(r"(?:^|/)opencode(?:\s|$)", re.I)),
    ("goose", re.compile(r"(?:^|/)goose(?:\s|$)", re.I)),
]

HOST_APP_MATCHERS = [
    ("iTerm2", re.compile(r"iTerm2|iTermServer", re.I)),
    ("Terminal.app", re.compile(r"(?:^|/)Terminal(?:\.app|$|\s)", re.I)),
    ("Ghostty", re.compile(r"ghostty", re.I)),
    ("Warp", re.compile(r"(?:^|/)Warp", re.I)),
    ("Antigravity IDE", re.compile(r"Antigravity\.app", re.I)),
    ("Cursor", re.compile(r"Cursor\.app", re.I)),
    ("VS Code", re.compile(r"Visual Studio Code|Code Helper", re.I)),
    ("Kitty", re.compile(r"kitty", re.I)),
    ("Alacritty", re.compile(r"alacritty", re.I)),
    ("WezTerm", re.compile(r"wezterm", re.I)),
    ("SSH", re.compile(r"(?:^|/)sshd", re.I)),
]

WORKING_WINDOW = 3.5
TURN_WORK_THRESHOLD = 1.4
EXTERNAL_SCAN_INTERVAL = 2.5

ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
    r"|\x1b[@-Z\\-_]"
)

INPUT_PATTERNS = [
    r"\(y/n\)",
    r"\[y/n\]",
    r"\[Y/n\]",
    r"\[y/N\]",
    r"\byes/no\b",
    r"do you want to (?:proceed|continue|run|allow|edit|create|delete|execute)",
    r"do you want to make this edit",
    r"tell claude what to do",
    r"would you like to (?:proceed|continue|run|allow)",
    r"\ballow\b.*\?",
    r"\ballow once\b",
    r"\balways allow\b",
    r"\bbypass\s*sandbox\b.*\?",
    r"\bapprove\b.*\?",
    r"requires? (?:manual )?(?:user )?approval",
    r"waiting for (?:your )?(?:input|approval|confirmation|answer)",
    r"press enter to (?:continue|confirm|proceed)",
    r"\bproceed\?",
    r"\bcontinue\?",
    r"reauthentication required",
    r"enter (?:your )?(?:choice|selection|password|passcode|otp)",
    r"select an option",
    r"choose an option",
    r"^\s*[❯>›➜]\s*[1-9]\.\s+\S",
]

BUSY_PATTERNS = [
    r"esc to (?:interrupt|cancel)",
    r"ctrl\+c to (?:interrupt|cancel)",
    r"\bthinking\b\s*\.{0,3}",
    r"\bworking\b\.{1,3}$",
    r"\brunning\b\.{1,3}$",
    r"\bgenerating\b",
    r"\binvoking subagent\b",
    r"\bexecuting\b\.{0,3}$",
    r"[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷✻✽✶✢·•]\s*(?:thinking|working|running|reading|writing|editing|searching|analyzing|planning)",
    r"^[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷]\s+\S",
]

DONE_PATTERNS = [
    r"task (?:is )?(?:complete|completed|done|finished)",
    r"\ball (?:tasks )?done\b",
    r"\bfinished\b.*\btask",
    r"completed successfully",
    r"^Ticket:\s+\S+",
]

ERROR_PATTERNS = [
    r"\btraceback \(most recent call last\)",
    r"\b(?:syntax|type|reference|runtime|permission|connection)error:",
    r"\bfatal:\s",
    r"\bpanic:\s",
    r"\bcommand failed\b",
    r"\breauthentication failed\b",
]

MENU_OPTION_RE = re.compile(r"^\s*(?:[❯>›➜\*]\s*)?([1-9])[\.\)]\s+(.{2,120}?)\s*$")
YN_RE = re.compile(r"(\[Y/n\]|\[y/N\]|\[y/n\]|\(y/n\)|\byes/no\b)", re.I)
PROMPT_LINE_RE = re.compile(r"^\s*[❯›>]\s+(.{3,100}?)\s*$")
SPINNER_LINE_RE = re.compile(r"^\s*[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷✻✽✶✢]\s+(.{3,90}?)\s*$")
CLAUDE_SPINNER_CHARS = frozenset("⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⣾⣽⣻⢿⡿⣟⣯⣷✻✽✶✢⠐⠂⠄⠆⠇⠚⠒⠖⠦")
CLAUDE_IDLE_CHARS = frozenset("✳•·")

CHECK_DONE = re.compile(r"^[\s\-\*•⎿│└├]*(?:\[[xX]\]|☒|✔|✓|✅|◉|●)\s+\S")
CHECK_TODO = re.compile(r"^[\s\-\*•⎿│└├]*(?:\[ \]|☐|◻|○|□|◯)\s+\S")
STEP_RE = re.compile(
    r"\b(?:step|task|todo|item|phase)s?\s*(\d{1,3})\s*(?:/|of)\s*(\d{1,3})\b"
    r"|\b(\d{1,3})\s*/\s*(\d{1,3})\s+(?:tasks?|steps?|todos?|done|completed)\b",
    re.IGNORECASE,
)
TICKET_RE = re.compile(r"^Ticket:\s*([A-Za-z0-9_-]{4,64})\s*$", re.MULTILINE)
USER_REQ_RE = re.compile(r"<USER_REQUEST>\s*(.*?)\s*</USER_REQUEST>", re.DOTALL)

STATE_DIR = Path.home() / ".agent-deck"
LABELS_FILE = STATE_DIR / "labels.json"
META_FILE = STATE_DIR / "meta.json"
AGY_CLI_DIR = Path.home() / ".gemini" / "antigravity-cli"
AGY_BRAIN_DIR = AGY_CLI_DIR / "brain"
AGY_PRESENCE_DIR = AGY_CLI_DIR / "presence"
AGY_SUMMARIES_DB = AGY_CLI_DIR / "conversation_summaries.db"
CLAUDE_DIR = Path.home() / ".claude"
CLAUDE_PROJECTS_DIR = CLAUDE_DIR / "projects"


def _compile(patterns):
    return [re.compile(p, re.IGNORECASE | re.MULTILINE) for p in patterns]


INPUT_RE = _compile(INPUT_PATTERNS)
BUSY_RE = _compile(BUSY_PATTERNS)
DONE_RE = _compile(DONE_PATTERNS)
ERROR_RE = _compile(ERROR_PATTERNS)

TOKEN = secrets.token_urlsafe(24)
HOME = str(Path.home())
LOCK = threading.Lock()
SEQ = 0
SERVER_PORT = 7878
STATE = {
    "seq": 0,
    "sessions": [],
    "events": [],
    "recent_cwds": [],
    "local_ports": [],
    "error": None,
    "now": time.time(),
    "home": HOME,
}
TRACK = {}
OUTPUT_CACHE = {}
GIT_CACHE = {}
PORT_CACHE = {"ts": 0.0, "pid_ports": {}, "all_ports": []}
DEV_CMD_CACHE = {}
MANAGED_SERVERS = {}
EXTERNAL_CACHE = {"ts": 0.0, "sessions": []}
GHOSTTY_CACHE = {"ts": 0.0, "terminals": []}
AGY_SUMMARY_CACHE = {"ts": 0.0, "data": {}}
AGY_PRESENCE_CACHE = {"ts": 0.0, "pid_to_conv": {}, "active_convs": set()}
AGY_TRANSCRIPT_CACHE = {}
CLAUDE_TRANSCRIPT_CACHE = {}
OSASCRIPT_BLOCKED = set()
EVENTS = []
LABELS = {}
BROWSER_URLS = {}
PINNED = set()
DISMISSED = set()
RECENT_CWDS = []
SSE_CLIENTS = set()
SSE_LOCK = threading.Lock()

KEY_OK = re.compile(
    r"^(Enter|Escape|C-c|C-d|C-l|C-r|C-u|C-z|Up|Down|Left|Right|"
    r"Tab|BTab|Space|BSpace|PageUp|PageDown|/[a-z-]+|[A-Za-z0-9])$"
)
SESSION_ID_OK = re.compile(r"^(%\d+|tty:[A-Za-z0-9_/-]+|agy:[A-Za-z0-9_-]+|claude:[A-Za-z0-9_-]+)$")
SESSION_NAME_OK = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def load_persistence():
    global LABELS, BROWSER_URLS, PINNED, DISMISSED, RECENT_CWDS
    try:
        if LABELS_FILE.exists():
            LABELS = json.loads(LABELS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        LABELS = {}
    try:
        if META_FILE.exists():
            meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            PINNED = set(meta.get("pinned", []))
            DISMISSED = set(meta.get("dismissed", []))
            RECENT_CWDS = [p for p in meta.get("recent_cwds", []) if isinstance(p, str)]
            raw_urls = meta.get("browser_urls", {})
            BROWSER_URLS = (
                {str(k): str(v) for k, v in raw_urls.items() if isinstance(v, str) and v.strip()}
                if isinstance(raw_urls, dict)
                else {}
            )
    except (OSError, ValueError):
        PINNED = set()
        DISMISSED = set()
        RECENT_CWDS = []
        BROWSER_URLS = {}

    defaults = [
        os.getcwd(),
        str(BASE_DIR),
        HOME,
    ]
    for d in defaults:
        if os.path.isdir(d) and d not in RECENT_CWDS:
            RECENT_CWDS.append(d)


def save_persistence():
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        tmp_labels = LABELS_FILE.with_suffix(".tmp")
        tmp_labels.write_text(json.dumps(LABELS, indent=2), encoding="utf-8")
        tmp_labels.replace(LABELS_FILE)

        tmp_meta = META_FILE.with_suffix(".tmp")
        tmp_meta.write_text(
            json.dumps(
                {
                    "pinned": sorted(PINNED),
                    "dismissed": sorted(DISMISSED)[-100:],
                    "recent_cwds": RECENT_CWDS[:12],
                    "browser_urls": BROWSER_URLS,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp_meta.replace(META_FILE)
    except OSError:
        pass


def record_cwd(cwd):
    if not cwd or not os.path.isdir(cwd):
        return
    if cwd in RECENT_CWDS:
        RECENT_CWDS.remove(cwd)
    RECENT_CWDS.insert(0, cwd)
    del RECENT_CWDS[12:]


# ---------------------------------------------------------------------------
# Subprocess & tmux helpers
# ---------------------------------------------------------------------------

def tmux(*args, timeout=5):
    try:
        return subprocess.run(
            ["tmux", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError:
        return subprocess.CompletedProcess(
            ["tmux", *args],
            127,
            "",
            "no server running (tmux not installed; install with: brew install tmux)",
        )


PANE_FORMAT = "\t".join([
    "#{pane_id}",
    "#{pane_pid}",
    "#{session_name}",
    "#{window_index}",
    "#{window_name}",
    "#{pane_index}",
    "#{pane_current_command}",
    "#{pane_current_path}",
    "#{pane_dead}",
    "#{pane_dead_status}",
    "#{session_created}",
    "#{pane_width}",
    "#{pane_height}",
    "#{pane_title}",
])


def list_panes():
    r = tmux("list-panes", "-a", "-F", PANE_FORMAT)
    if r.returncode != 0:
        msg = (r.stderr or "").lower()
        if (
            "no server running" in msg
            or "no sessions" in msg
            or "error connecting" in msg
            or "no such file" in msg
        ):
            return []
        raise RuntimeError(r.stderr.strip() or "tmux list-panes failed")
    panes = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 13:
            continue
        (
            pid, pane_pid, sess, win, wname, pidx,
            cmd, path, dead, dead_status, created, width, height,
        ) = parts[:13]
        ptitle = parts[13].strip() if len(parts) > 13 else ""
        panes.append({
            "id": pid,
            "pane_pid": int(pane_pid) if pane_pid.isdigit() else 0,
            "session": sess,
            "window": win,
            "window_name": wname,
            "pane": pidx,
            "pane_title": ptitle,
            "cmd": cmd,
            "cwd": path,
            "dead": dead == "1",
            "dead_status": dead_status,
            "created": int(created or 0),
            "width": int(width or 0),
            "height": int(height or 0),
            "target": f"{sess}:{win}.{pidx}",
        })
    return panes


def capture_ansi(pane_id, lines=260):
    r = tmux("capture-pane", "-e", "-p", "-J", "-t", pane_id, "-S", f"-{int(lines)}")
    if r.returncode != 0:
        return ""
    return r.stdout.rstrip("\n ")


def strip_ansi(text):
    return ANSI_RE.sub("", text)


# ---------------------------------------------------------------------------
# Process-tree & TTY scanner
# ---------------------------------------------------------------------------

def _extract_flag(args_str, flag):
    m = re.search(rf"(?:^|\s){re.escape(flag)}(?:=|\s+)([^\s]+)", args_str)
    return m.group(1) if m else None


def parse_agent_meta(kind, args_str):
    meta = {"kind": kind}
    if kind == "agy":
        mode = _extract_flag(args_str, "--mode")
        effort = _extract_flag(args_str, "--effort")
        model = _extract_flag(args_str, "--model")
        conv = _extract_flag(args_str, "--conversation")
        if mode:
            meta["mode"] = mode
        if effort:
            meta["effort"] = effort
        if model:
            meta["model"] = model
        if conv:
            meta["conversation"] = conv
        if re.search(r"(?:^|\s)(?:--continue|-c)(?:\s|$)", args_str):
            meta["resumed"] = True
        if "--sandbox" in args_str:
            meta["sandbox"] = True
        if "--dangerously-skip-permissions" in args_str:
            meta["skip_perms"] = True
        if "--remote-agent" in args_str:
            meta["remote"] = True
    elif kind == "claude":
        mode = _extract_flag(args_str, "--permission-mode")
        model = _extract_flag(args_str, "--model")
        conv = _extract_flag(args_str, "--resume") or _extract_flag(args_str, "-r")
        if mode:
            meta["mode"] = mode
        if model:
            meta["model"] = model
        if conv and not conv.startswith("-"):
            meta["conversation"] = conv
        if re.search(r"(?:^|\s)(?:--continue|-c)(?:\s|$)", args_str):
            meta["resumed"] = True
        if "--dangerously-skip-permissions" in args_str:
            meta["skip_perms"] = True
    return meta


def _parse_ps_etime(etime_str):
    """Parses POSIX ps etime '[[dd-]hh:]mm:ss' into elapsed seconds."""
    s = (etime_str or "").strip()
    if not s:
        return None
    days = 0
    if "-" in s:
        d_part, s = s.split("-", 1)
        if not d_part.isdigit():
            return None
        days = int(d_part)
    parts = s.split(":")
    try:
        nums = [int(x) for x in parts]
    except ValueError:
        return None
    if len(nums) == 2:
        hh, mm, ss = 0, nums[0], nums[1]
    elif len(nums) == 3:
        hh, mm, ss = nums[0], nums[1], nums[2]
    else:
        return None
    return days * 86400 + hh * 3600 + mm * 60 + ss


def _parse_iso_ts(val):
    if not val or not isinstance(val, str):
        return None
    s = val.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def scan_process_table(now=None):
    if now is None:
        now = time.time()
    try:
        r = subprocess.run(
            ["ps", "-axo", "pid=,ppid=,tty=,etime=,args="],
            capture_output=True,
            text=True,
            timeout=2,
        )
        if r.returncode != 0:
            return None
    except (OSError, subprocess.SubprocessError):
        return None

    children = {}
    procs = {}
    for raw in r.stdout.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        tty = parts[2]
        elapsed = _parse_ps_etime(parts[3])
        started_at = (now - elapsed) if elapsed is not None else None
        args = parts[4].strip()
        m_app = re.match(r"^(/[^\n]*?\.app/Contents/MacOS/[^\s]+|\S+)", args)
        comm_raw = m_app.group(1) if m_app else args
        comm = os.path.basename(comm_raw)
        procs[pid] = {
            "ppid": ppid,
            "tty": tty,
            "started_at": started_at,
            "comm": comm,
            "comm_raw": comm_raw,
            "args": args,
        }
        children.setdefault(ppid, []).append(pid)
    return procs, children


def _shorten_cmd(args_str, max_len=76):
    s = re.sub(r"\s+", " ", (args_str or "").strip())
    parts = s.split(" ")
    if parts:
        first_base = os.path.basename(parts[0])
        # Unwrap leading node/python interpreter if second arg is a script/binary path
        if first_base.lower() in {"node", "python", "python3"} and len(parts) >= 2 and "/" in parts[1]:
            parts = parts[1:]
            parts[0] = os.path.basename(parts[0])
        elif "/" in parts[0]:
            parts[0] = first_base
        s = " ".join(parts)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"


def _nearest_git_root(path_str):
    if not path_str:
        return None
    clean = path_str.split("/node_modules")[0].rstrip("/")
    if not clean:
        return None
    p = Path(clean)
    if p.is_file():
        p = p.parent
    if not p.is_dir():
        return None
    for anc in [p, *p.parents]:
        if (anc / ".git").exists():
            return str(anc)
    return None


def _extract_dev_server_info(args_str):
    if not args_str or not DEV_SERVER_RE.search(args_str):
        return None, None
    pm = PORT_ARG_RE.search(args_str)
    label = f"dev :{pm.group(1)}" if pm else "dev server"
    dev_cwd = None
    for m in ABS_PATH_TOKEN_RE.finditer(args_str):
        tok = m.group(1)
        if "/.gemini/" in tok or "/.nvm/" in tok or "/opt/homebrew/" in tok:
            continue
        root = _nearest_git_root(tok)
        if root:
            dev_cwd = root
            break
    return label, dev_cwd


def inspect_lineage(lineage, dead=False, fallback_cmd="zsh", root_tty=None):
    """
    Analyzes a list of (pid, depth, comm, args[, proc_tty]) tuples.
    Identifies AI coding agents (Antigravity agy, Claude Code, Codex, Gemini, etc.)
    and separates background dev servers / daemon child PTYs from foreground subtools.
    """
    target_pid = lineage[0][0] if lineage else 0
    norm = [
        (item[0], item[1], item[2], item[3], item[4] if len(item) > 4 else None)
        for item in lineage
    ]

    found_agent = None
    agent_depth = -1
    for pid, depth, comm, args, _ptty in norm:
        haystack = f"{comm} {args}"
        for kind, pat in KNOWN_AGENTS:
            if pat.search(haystack):
                found_agent = (pid, kind, comm, args)
                agent_depth = depth
                break
        if found_agent:
            break

    if found_agent:
        a_pid, kind, comm, args = found_agent
        subtool = None
        subtool_cmd = None
        dev_server = None
        dev_cwd = None

        for pid, depth, c_comm, c_args, c_tty in norm:
            if depth <= agent_depth:
                continue
            ds_label, ds_cwd = _extract_dev_server_info(c_args)
            if ds_label:
                if not dev_server or ":" in ds_label:
                    dev_server = ds_label
                if ds_cwd and not dev_cwd:
                    dev_cwd = ds_cwd

        for pid, depth, c_comm, c_args, c_tty in reversed(norm):
            if depth <= agent_depth:
                continue
            base = c_comm.lower()
            if base in SHELLS or base in WRAPPERS or base in {kind, "node", "claude", "agy"}:
                continue
            if re.match(r"^\d+\.\d+\.\d+", base):
                continue
            if base in DAEMON_SUBTOOLS or DAEMON_ARG_RE.search(c_args or ""):
                continue
            if DEV_SERVER_RE.search(c_args or ""):
                continue
            # Background daemon spawned on a separate child PTY by agy / claude
            if root_tty and c_tty and c_tty != "??" and c_tty != root_tty:
                continue
            subtool = c_comm
            subtool_cmd = _shorten_cmd(c_args)
            break
        return {
            "is_claude": kind == "claude",
            "focus_pid": a_pid,
            "agent_running": not dead,
            "agent_kind": kind,
            "agent_cmd": kind,
            "agent_meta": parse_agent_meta(kind, args),
            "subtool": subtool,
            "subtool_cmd": subtool_cmd,
            "dev_server": dev_server,
            "dev_cwd": dev_cwd,
            "lineage_pids": [pid for pid, depth, *_ in norm if depth > agent_depth],
        }

    for pid, depth, comm, args, _ptty in norm:
        if depth == 0 and comm.lower() in SHELLS:
            continue
        base = comm.lower()
        if base not in SHELLS and base not in WRAPPERS:
            ds_label, ds_cwd = _extract_dev_server_info(args)
            return {
                "is_claude": False,
                "focus_pid": pid,
                "agent_running": not dead,
                "agent_kind": "program",
                "agent_cmd": comm,
                "agent_meta": {},
                "subtool": None,
                "subtool_cmd": _shorten_cmd(args),
                "dev_server": ds_label,
                "dev_cwd": ds_cwd,
                "lineage_pids": [l_pid for l_pid, _, l_comm, *_ in norm if l_comm.lower() not in SHELLS],
            }

    return {
        "is_claude": False,
        "focus_pid": target_pid,
        "agent_running": False,
        "agent_kind": None,
        "agent_cmd": fallback_cmd,
        "agent_meta": {},
        "subtool": None,
        "subtool_cmd": None,
        "dev_server": None,
        "dev_cwd": None,
        "lineage_pids": [],
    }


def inspect_pane_processes(pane, proc_snapshot):
    fallback_cmd = pane["cmd"]
    fallback_base = os.path.basename(fallback_cmd).lower()

    if not proc_snapshot or not pane["pane_pid"]:
        hay = f"{fallback_cmd} {pane.get('window_name', '')}"
        for kind, pat in KNOWN_AGENTS:
            if pat.search(hay):
                return {
                    "is_claude": kind == "claude",
                    "agent_running": not pane["dead"],
                    "agent_kind": kind,
                    "agent_cmd": kind,
                    "agent_meta": {"kind": kind},
                    "subtool": None,
                    "subtool_cmd": None,
                    "dev_server": None,
                    "dev_cwd": None,
                }
        is_prog = (not pane["dead"]) and (fallback_base not in SHELLS)
        return {
            "is_claude": False,
            "agent_running": is_prog,
            "agent_kind": "program" if is_prog else None,
            "agent_cmd": fallback_cmd,
            "agent_meta": {},
            "subtool": None,
            "subtool_cmd": fallback_cmd if is_prog else None,
            "dev_server": None,
            "dev_cwd": None,
        }

    procs, children = proc_snapshot
    root_pid = pane["pane_pid"]
    root_tty = procs.get(root_pid, {}).get("tty")
    lineage = []
    q = [(root_pid, 0)]
    visited = {root_pid}
    while q:
        curr, depth = q.pop(0)
        if curr in procs:
            p = procs[curr]
            lineage.append((curr, depth, p["comm"], p["args"], p.get("tty")))
        for ch in children.get(curr, []):
            if ch not in visited:
                visited.add(ch)
                q.append((ch, depth + 1))

    return inspect_lineage(lineage, dead=pane["dead"], fallback_cmd=fallback_cmd, root_tty=root_tty)


# ---------------------------------------------------------------------------
# Current Task Extractor
# ---------------------------------------------------------------------------

def infer_current_task(plain_text, proc_info, status, label=""):
    """Determines a concise human-readable description of what the terminal is currently doing."""
    if label:
        if proc_info.get("subtool"):
            return f"{label} · running {proc_info['subtool']}"
        return label

    if status == "exited":
        return "Process exited"

    lines = non_empty_tail(plain_text, 22)

    if status == "needs_input":
        for ln in reversed(lines[-10:]):
            if any(p.search(ln) for p in INPUT_RE):
                cleaned = re.sub(r"\s+", " ", ln).strip()
                return f"Waiting for input: {cleaned[:72]}"
        return "Waiting for your confirmation"

    if proc_info.get("subtool_cmd"):
        return f"Running: {proc_info['subtool_cmd']}"

    if proc_info.get("agent_running"):
        # Check for spinner / live activity banner first
        for ln in reversed(lines[-8:]):
            sm = SPINNER_LINE_RE.match(ln)
            if sm:
                return sm.group(1).strip()[:76]
        # Check for most recent user prompt on screen (e.g. '❯ fix login bug')
        for ln in reversed(lines):
            pm = PROMPT_LINE_RE.match(ln)
            if pm:
                candidate = pm.group(1).strip()
                if not re.match(r"^[1-9][\.\)]\s", candidate):
                    return candidate[:76]
        if status == "working":
            return f"{proc_info.get('agent_cmd', 'Agent')} working…"
        if status == "done":
            return "Turn finished — ready for next prompt"
        return f"{proc_info.get('agent_cmd', 'Agent')} ready at prompt"

    return "Idle shell"


# ---------------------------------------------------------------------------
# External TTYs, macOS Terminal.app / iTerm2 Bridge, & Open Terminal Action
# ---------------------------------------------------------------------------

def batch_lsof_cwds(pids):
    clean_pids = sorted({int(p) for p in pids if p and int(p) > 0})
    if not clean_pids:
        return {}
    pid_arg = ",".join(str(p) for p in clean_pids[:60])
    try:
        r = subprocess.run(
            ["lsof", "-a", "-p", pid_arg, "-d", "cwd", "-Fn"],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        return {}

    cwds = {}
    curr_pid = None
    for line in r.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            curr_pid = int(line[1:])
        elif line.startswith("n") and curr_pid is not None:
            path = line[1:].strip()
            if path.startswith("/"):
                cwds[curr_pid] = path
    return cwds


def _running_gui_terminals(procs):
    apps = set()
    if not procs:
        return apps
    for p in procs.values():
        hay = f"{p['comm']} {p['args']}"
        if "Terminal.app/Contents/MacOS/Terminal" in hay or p["comm"] == "Terminal":
            apps.add("Terminal.app")
        if "iTerm.app" in hay or p["comm"] == "iTerm2":
            apps.add("iTerm2")
        if "Ghostty.app/Contents/MacOS/ghostty" in hay or p["comm"].lower() == "ghostty":
            apps.add("Ghostty")
    return apps


DECK_SEP = "<<<DECK_TAB_SEP>>>"
GHOSTTY_FIELD_SEP = "<<<DECK_GFIELD>>>"
GHOSTTY_ROW_SEP = "<<<DECK_GROW>>>"


def macos_list_ghostty_terminals(now=None):
    """Enumerates open Ghostty terminal surfaces (id, title, working directory) via Ghostty's AppleScript suite."""
    if not IS_MAC or "Ghostty" in OSASCRIPT_BLOCKED:
        return []
    ts_now = now if now is not None else time.time()
    if ts_now - GHOSTTY_CACHE["ts"] < 2.5 and GHOSTTY_CACHE["terminals"]:
        return GHOSTTY_CACHE["terminals"]

    script = (
        'tell application "Ghostty"\n'
        '  set outRows to {}\n'
        '  repeat with t in terminals\n'
        '    try\n'
        f'      set end of outRows to (id of t) & "{GHOSTTY_FIELD_SEP}" & (name of t) & "{GHOSTTY_FIELD_SEP}" & (working directory of t)\n'
        '    end try\n'
        '  end repeat\n'
        f'  set AppleScript\'s text item delimiters to "\\n{GHOSTTY_ROW_SEP}\\n"\n'
        '  return outRows as text\n'
        'end tell'
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=1.8,
        )
        if r.returncode != 0:
            err = (r.stderr or "").lower()
            if "not authorized" in err or "-1743" in err:
                OSASCRIPT_BLOCKED.add("Ghostty")
            return GHOSTTY_CACHE.get("terminals", [])
    except (OSError, subprocess.SubprocessError):
        return GHOSTTY_CACHE.get("terminals", [])

    terms = []
    raw_out = (r.stdout or "").strip()
    if raw_out:
        for row in raw_out.split(f"\n{GHOSTTY_ROW_SEP}\n"):
            parts = row.split(GHOSTTY_FIELD_SEP)
            if len(parts) < 3:
                continue
            gid, gname, gcwd = parts[0].strip(), parts[1].strip(), parts[2].strip().rstrip("/")
            if not gid:
                continue
            # Skip Agent Deck's own server tab
            if "agent_deck.py" in gname:
                continue
            terms.append({"id": gid, "name": gname, "cwd": gcwd})

    GHOSTTY_CACHE["ts"] = ts_now
    GHOSTTY_CACHE["terminals"] = terms
    return terms


def _clean_claude_tab_title(raw_title):
    """
    Normalizes a Claude Code terminal title (e.g. '✳ Fix login redirect' or '⠐ Refactoring…').
    Returns (clean_title, is_spinning, has_claude_marker).
    """
    t = (raw_title or "").strip()
    if not t:
        return "", False, False
    first_ch = t[0]
    is_spinning = first_ch in CLAUDE_SPINNER_CHARS
    has_marker = is_spinning or (first_ch in CLAUDE_IDLE_CHARS) or bool(CLAUDE_PROC_RE.search(t))
    i = 0
    while i < len(t) and (t[i] in CLAUDE_SPINNER_CHARS or t[i] in CLAUDE_IDLE_CHARS or t[i].isspace()):
        i += 1
    cleaned = t[i:].strip()
    if " — " in cleaned:
        cleaned = cleaned.split(" — ")[0].strip()
    cleaned = re.sub(r"\s*—\s*-?(?:zsh|bash|fish).*$", "", cleaned).strip()
    if cleaned.lower() in {"claude", "claude code", "zsh", "bash", "fish", "-zsh", "-bash"}:
        cleaned = ""
    return cleaned, is_spinning, has_marker


def match_ghostty_surfaces(records, ghostty_terms):
    """
    Maps discovered Ghostty TTY records to their exact Ghostty AppleScript terminal UUID.
    `records` is a list of dicts: {sid, conv_title, launch_cwd, cwd, agent_cmd, agent_kind}.
    Returns {sid: {"id": ..., "name": ..., "cwd": ...}}.
    """
    if not records or not ghostty_terms:
        return {}

    matched = {}
    used_ids = set()

    def _norm_dir(p):
        return (p or "").rstrip("/")

    def _is_claude_surface(gname):
        _, _, has_marker = _clean_claude_tab_title(gname)
        return has_marker

    # Pass 1: exact Antigravity or Claude conversation title match
    for rec in records:
        ctitle = (rec.get("conv_title") or "").strip()
        if not ctitle:
            continue
        rkind = rec.get("agent_kind") or ""
        rcwds = {_norm_dir(rec.get("launch_cwd")), _norm_dir(rec.get("cwd"))} - {""}
        candidates = []
        for g in ghostty_terms:
            if g["id"] in used_ids:
                continue
            gname = g["name"]
            g_is_claude = _is_claude_surface(gname)
            if rkind == "agy" and g_is_claude:
                continue
            if rkind == "claude" and not g_is_claude and " — " in gname and not gname.lower().startswith("claude"):
                continue
            g_clean_claude, _, _ = _clean_claude_tab_title(gname)
            g_prefix = gname.split(" — ")[0].strip()
            if (
                gname == ctitle
                or g_prefix == ctitle
                or gname.startswith(ctitle + " — ")
                or (g_clean_claude and g_clean_claude == ctitle)
            ):
                cwd_score = 0 if (_norm_dir(g["cwd"]) in rcwds) else 1
                candidates.append((cwd_score, g))
        if candidates:
            candidates.sort(key=lambda item: item[0])
            chosen = candidates[0][1]
            matched[rec["sid"]] = chosen
            used_ids.add(chosen["id"])

    # Pass 2: agent-specific & non-shell foreground command match in the same working directory
    for rec in records:
        if rec["sid"] in matched:
            continue
        rkind = (rec.get("agent_kind") or "").strip().lower()
        acmd = (rec.get("agent_cmd") or "").strip().lower()
        if not acmd or acmd in SHELLS:
            continue
        rcwds = {_norm_dir(rec.get("launch_cwd")), _norm_dir(rec.get("cwd"))} - {""}
        for g in ghostty_terms:
            if g["id"] in used_ids:
                continue
            gname = g["name"]
            gcwd = _norm_dir(g["cwd"])
            cwd_ok = (not rcwds) or (gcwd in rcwds)
            if rkind == "claude":
                if _is_claude_surface(gname) and cwd_ok:
                    matched[rec["sid"]] = g
                    used_ids.add(g["id"])
                    break
            else:
                if not _is_claude_surface(gname) and acmd in gname.lower() and cwd_ok:
                    matched[rec["sid"]] = g
                    used_ids.add(g["id"])
                    break

    # Pass 2b: if a single unmatched Claude TTY and a single unused Claude Ghostty surface remain, pair them
    unmatched_claude = [r for r in records if r["sid"] not in matched and r.get("agent_kind") == "claude"]
    unused_claude_g = [g for g in ghostty_terms if g["id"] not in used_ids and _is_claude_surface(g["name"])]
    if len(unmatched_claude) == 1 and len(unused_claude_g) == 1:
        matched[unmatched_claude[0]["sid"]] = unused_claude_g[0]
        used_ids.add(unused_claude_g[0]["id"])

    # Pass 3: unambiguous working-directory match when counts align 1-to-1
    unmatched_by_cwd = {}
    for rec in records:
        if rec["sid"] in matched:
            continue
        lcwd = _norm_dir(rec.get("launch_cwd"))
        if lcwd:
            unmatched_by_cwd.setdefault(lcwd, []).append(rec)

    unused_by_cwd = {}
    for g in ghostty_terms:
        if g["id"] in used_ids:
            continue
        gcwd = _norm_dir(g["cwd"])
        if gcwd:
            unused_by_cwd.setdefault(gcwd, []).append(g)

    for lcwd, recs_in_dir in unmatched_by_cwd.items():
        g_in_dir = unused_by_cwd.get(lcwd) or []
        if len(recs_in_dir) == 1 and len(g_in_dir) == 1:
            rec0, g0 = recs_in_dir[0], g_in_dir[0]
            if rec0.get("agent_kind") == "agy" and _is_claude_surface(g0["name"]):
                continue
            matched[rec0["sid"]] = g0
            used_ids.add(g0["id"])

    return matched


def macos_read_tty_tab(app_name, dev_tty):
    """Returns (tab_title, screen_contents) for an open Terminal.app or iTerm2 tab."""
    if not IS_MAC or app_name in OSASCRIPT_BLOCKED:
        return "", None

    if app_name == "Terminal.app":
        script = (
            'on run argv\n'
            '  set targetTty to item 1 of argv\n'
            '  tell application "Terminal"\n'
            '    repeat with w in windows\n'
            '      repeat with t in tabs of w\n'
            '        try\n'
            '          if (tty of t) is targetTty then\n'
            '            set tTitle to custom title of t\n'
            '            if tTitle is "" then set tTitle to name of w\n'
            f'            return tTitle & "\\n{DECK_SEP}\\n" & (contents of t)\n'
            '          end if\n'
            '        end try\n'
            '      end repeat\n'
            '    end repeat\n'
            '  end tell\n'
            '  return ""\n'
            'end run'
        )
    elif app_name == "iTerm2":
        script = (
            'on run argv\n'
            '  set targetTty to item 1 of argv\n'
            '  tell application "iTerm2"\n'
            '    repeat with w in windows\n'
            '      repeat with t in tabs of w\n'
            '        repeat with s in sessions of t\n'
            '          try\n'
            '            if (tty of s) is targetTty then\n'
            f'              return (name of s) & "\\n{DECK_SEP}\\n" & (contents of s)\n'
            '            end if\n'
            '          end try\n'
            '        end repeat\n'
            '      end repeat\n'
            '    end repeat\n'
            '  end tell\n'
            '  return ""\n'
            'end run'
        )
    else:
        return "", None

    try:
        r = subprocess.run(
            ["osascript", "-e", script, dev_tty],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        if r.returncode != 0:
            err = (r.stderr or "").lower()
            if "not authorized" in err or "-1743" in err:
                OSASCRIPT_BLOCKED.add(app_name)
            return "", None
        if DECK_SEP in r.stdout:
            title_part, _, body_part = r.stdout.partition(f"\n{DECK_SEP}\n")
            return title_part.strip(), body_part.rstrip("\n ")
        return "", None
    except (OSError, subprocess.SubprocessError):
        return "", None


def macos_focus_tty(app_name, dev_tty, ghostty_id=""):
    if not IS_MAC:
        return False, "Opening/focusing GUI terminals requires macOS."
    if app_name == "Ghostty" and ghostty_id:
        script = (
            'on run argv\n'
            '  set targetId to item 1 of argv\n'
            '  tell application "Ghostty"\n'
            '    activate\n'
            '    repeat with t in terminals\n'
            '      try\n'
            '        if (id of t) is targetId then\n'
            '          focus t\n'
            '          return "ok"\n'
            '        end if\n'
            '      end try\n'
            '    end repeat\n'
            '  end tell\n'
            '  return "missing"\n'
            'end run'
        )
        try:
            r = subprocess.run(["osascript", "-e", script, ghostty_id], capture_output=True, text=True, timeout=2)
            if r.returncode == 0 and "ok" in r.stdout:
                return True, ""
        except (OSError, subprocess.SubprocessError):
            pass
    if app_name == "Terminal.app":
        script = (
            'on run argv\n'
            '  set targetTty to item 1 of argv\n'
            '  tell application "Terminal"\n'
            '    repeat with w in windows\n'
            '      repeat with t in tabs of w\n'
            '        try\n'
            '          if (tty of t) is targetTty then\n'
            '            set selected of t to true\n'
            '            set index of w to 1\n'
            '            activate\n'
            '            return "ok"\n'
            '          end if\n'
            '        end try\n'
            '      end repeat\n'
            '    end repeat\n'
            '  end tell\n'
            '  return "missing"\n'
            'end run'
        )
    elif app_name == "iTerm2":
        script = (
            'on run argv\n'
            '  set targetTty to item 1 of argv\n'
            '  tell application "iTerm2"\n'
            '    repeat with w in windows\n'
            '      repeat with t in tabs of w\n'
            '        repeat with s in sessions of t\n'
            '          try\n'
            '            if (tty of s) is targetTty then\n'
            '              select w\n'
            '              select t\n'
            '              select s\n'
            '              activate\n'
            '              return "ok"\n'
            '            end if\n'
            '          end try\n'
            '        end repeat\n'
            '      end repeat\n'
            '    end repeat\n'
            '  end tell\n'
            '  return "missing"\n'
            'end run'
        )
    else:
        app_map = {
            "Ghostty": "Ghostty",
            "Warp": "Warp",
            "VS Code": "Visual Studio Code",
            "Cursor": "Cursor",
            "Antigravity IDE": "Antigravity",
            "Kitty": "kitty",
            "Alacritty": "Alacritty",
            "WezTerm": "WezTerm",
        }
        mac_app = app_map.get(app_name)
        if not mac_app:
            return False, f"Cannot auto-focus {app_name}."
        try:
            r = subprocess.run(
                ["osascript", "-e", 'on run argv\ntell application (item 1 of argv) to activate\nend run', mac_app],
                capture_output=True,
                text=True,
                timeout=2,
            )
            return (r.returncode == 0), (r.stderr.strip() or "Failed to activate app.")
        except (OSError, subprocess.SubprocessError) as e:
            return False, str(e)

    try:
        r = subprocess.run(["osascript", "-e", script, dev_tty], capture_output=True, text=True, timeout=2)
        if r.returncode == 0 and "ok" in r.stdout:
            return True, ""
        return False, r.stderr.strip() or "Tab not found."
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def macos_open_in_terminal_app(shell_cmd="", cwd=""):
    """
    Opens a native macOS terminal window/tab (prefers iTerm2 if running, else Terminal.app)
    running `shell_cmd` (e.g. `tmux attach -t session`) or opening `cwd`.
    """
    if not IS_MAC:
        return False, "Open Terminal requires macOS."

    snap = scan_process_table()
    running_gui = _running_gui_terminals(snap[0]) if snap else set()

    if not shell_cmd and cwd:
        # Safe single-quoted cd command
        quoted_cwd = "'" + cwd.replace("'", "'\\''") + "'"
        shell_cmd = f"cd {quoted_cwd} && clear"

    if "iTerm2" in running_gui:
        script = (
            'on run argv\n'
            '  set cmdStr to item 1 of argv\n'
            '  tell application "iTerm2"\n'
            '    activate\n'
            '    if (count of windows) is 0 then\n'
            '      set newWin to (create window with default profile)\n'
            '      if cmdStr is not "" then tell current session of newWin to write text cmdStr\n'
            '    else\n'
            '      tell current window\n'
            '        set newTab to (create tab with default profile)\n'
            '        if cmdStr is not "" then tell current session of newTab to write text cmdStr\n'
            '      end tell\n'
            '    end if\n'
            '  end tell\n'
            '  return "ok"\n'
            'end run'
        )
        try:
            r = subprocess.run(["osascript", "-e", script, shell_cmd], capture_output=True, text=True, timeout=3)
            if r.returncode == 0:
                return True, ""
        except (OSError, subprocess.SubprocessError):
            pass

    # Fallback: macOS built-in Terminal.app
    script_term = (
        'on run argv\n'
        '  set cmdStr to item 1 of argv\n'
        '  tell application "Terminal"\n'
        '    activate\n'
        '    do script cmdStr\n'
        '  end tell\n'
        '  return "ok"\n'
        'end run'
    )
    try:
        r = subprocess.run(["osascript", "-e", script_term, shell_cmd], capture_output=True, text=True, timeout=3)
        if r.returncode == 0:
            return True, ""
        return False, r.stderr.strip() or "Could not open Terminal.app."
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def macos_send_tty_text(app_name, dev_tty, text, press_enter=True):
    if not IS_MAC:
        return False, "Direct external terminal send requires macOS Terminal.app or iTerm2."
    if app_name == "iTerm2":
        nl_clause = "" if press_enter else " newline no"
        script = (
            'on run argv\n'
            '  set targetTty to item 1 of argv\n'
            '  set msg to item 2 of argv\n'
            '  tell application "iTerm2"\n'
            '    repeat with w in windows\n'
            '      repeat with t in tabs of w\n'
            '        repeat with s in sessions of t\n'
            '          try\n'
            '            if (tty of s) is targetTty then\n'
            f'              tell s to write text msg{nl_clause}\n'
            '              return "ok"\n'
            '            end if\n'
            '          end try\n'
            '        end repeat\n'
            '      end repeat\n'
            '    end repeat\n'
            '  end tell\n'
            '  return "missing"\n'
            'end run'
        )
    elif app_name == "Terminal.app":
        script = (
            'on run argv\n'
            '  set targetTty to item 1 of argv\n'
            '  set msg to item 2 of argv\n'
            '  tell application "Terminal"\n'
            '    repeat with w in windows\n'
            '      repeat with t in tabs of w\n'
            '        try\n'
            '          if (tty of t) is targetTty then\n'
            '            do script msg in t\n'
            '            return "ok"\n'
            '          end if\n'
            '        end try\n'
            '      end repeat\n'
            '    end repeat\n'
            '  end tell\n'
            '  return "missing"\n'
            'end run'
        )
    else:
        return False, f"{app_name} does not allow external keystroke injection — click 'Resume in tmux' to control it."

    try:
        r = subprocess.run(["osascript", "-e", script, dev_tty, text], capture_output=True, text=True, timeout=2.5)
        if r.returncode == 0 and "ok" in r.stdout:
            return True, ""
        return False, r.stderr.strip() or "Could not write to terminal tab."
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


GHOSTTY_KEY_MAP = {
    "Enter": ("enter", ""),
    "Escape": ("escape", ""),
    "Up": ("up", ""),
    "Down": ("down", ""),
    "Left": ("left", ""),
    "Right": ("right", ""),
    "Tab": ("tab", ""),
    "BTab": ("tab", "shift"),
    "Space": ("space", ""),
    "BSpace": ("backspace", ""),
    "PageUp": ("page_up", ""),
    "PageDown": ("page_down", ""),
    "C-c": ("c", "control"),
    "C-d": ("d", "control"),
    "C-l": ("l", "control"),
    "C-r": ("r", "control"),
    "C-u": ("u", "control"),
    "C-z": ("z", "control"),
}


def macos_send_ghostty_text(ghostty_id, text, press_enter=True):
    """Inputs text (and optional Enter key) directly into a Ghostty terminal surface without stealing window focus."""
    if not IS_MAC or not ghostty_id:
        return False, "Ghostty terminal surface ID is unavailable."
    cleaned = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    script = (
        'on run argv\n'
        '  set targetId to item 1 of argv\n'
        '  set msg to item 2 of argv\n'
        '  set doEnter to item 3 of argv\n'
        '  tell application "Ghostty"\n'
        '    repeat with t in terminals\n'
        '      try\n'
        '        if (id of t) is targetId then\n'
        '          if msg is not "" then input text msg to t\n'
        '          if doEnter is "1" then\n'
        '            delay 0.06\n'
        '            send key "enter" to t\n'
        '          end if\n'
        '          return "ok"\n'
        '        end if\n'
        '      end try\n'
        '    end repeat\n'
        '  end tell\n'
        '  return "missing"\n'
        'end run'
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script, ghostty_id, cleaned, "1" if press_enter else "0"],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        if r.returncode == 0 and "ok" in r.stdout:
            return True, ""
        if "missing" in (r.stdout or ""):
            GHOSTTY_CACHE["ts"] = 0.0
            return False, "Ghostty tab changed — retrying scan, try again in a second."
        return False, r.stderr.strip() or "Could not send input to Ghostty."
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def macos_send_ghostty_keys(ghostty_id, keys):
    """Sends a sequence of keystrokes or slash commands directly to a Ghostty terminal surface."""
    if not IS_MAC or not ghostty_id:
        return False, "Ghostty terminal surface ID is unavailable."

    ops = []
    for k in keys:
        if k.startswith("/") and len(k) > 1:
            ops.append(("text_enter", k, ""))
        elif k in GHOSTTY_KEY_MAP:
            kname, mods = GHOSTTY_KEY_MAP[k]
            ops.append(("key", kname, mods))
        elif len(k) == 1 and k.isalnum():
            if k.isupper():
                ops.append(("key", k.lower(), "shift"))
            else:
                ops.append(("key", k.lower(), ""))
        else:
            return False, f"Unsupported Ghostty key: {k}"

    # Encode ops as newline-separated records passed safely through argv (zero AppleScript injection risk)
    encoded_ops = "\n".join(f"{kind}\t{val}\t{mods}" for kind, val, mods in ops)
    script = (
        'on run argv\n'
        '  set targetId to item 1 of argv\n'
        '  set rawOps to paragraphs of (item 2 of argv)\n'
        '  tell application "Ghostty"\n'
        '    repeat with t in terminals\n'
        '      try\n'
        '        if (id of t) is targetId then\n'
        '          set AppleScript\'s text item delimiters to tab\n'
        '          set idx to 0\n'
        '          repeat with opLine in rawOps\n'
        '            if (length of opLine) > 0 then\n'
        '              if idx > 0 then delay 0.05\n'
        '              set parts to text items of opLine\n'
        '              set opKind to item 1 of parts\n'
        '              set opVal to item 2 of parts\n'
        '              set opMod to ""\n'
        '              if (count of parts) > 2 then set opMod to item 3 of parts\n'
        '              if opKind is "text_enter" then\n'
        '                input text opVal to t\n'
        '                delay 0.06\n'
        '                send key "enter" to t\n'
        '              else if opMod is not "" then\n'
        '                send key opVal modifiers opMod to t\n'
        '              else\n'
        '                send key opVal to t\n'
        '              end if\n'
        '              set idx to idx + 1\n'
        '            end if\n'
        '          end repeat\n'
        '          return "ok"\n'
        '        end if\n'
        '      end try\n'
        '    end repeat\n'
        '  end tell\n'
        '  return "missing"\n'
        'end run'
    )
    try:
        r = subprocess.run(
            ["osascript", "-e", script, ghostty_id, encoded_ops],
            capture_output=True,
            text=True,
            timeout=3.0,
        )
        if r.returncode == 0 and "ok" in r.stdout:
            return True, ""
        if "missing" in (r.stdout or ""):
            GHOSTTY_CACHE["ts"] = 0.0
            return False, "Ghostty tab changed — retrying scan, try again in a second."
        return False, r.stderr.strip() or "Could not send keystrokes to Ghostty."
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def _detect_host_app_and_tmux(pid, procs):
    curr = pid
    visited = set()
    host_app = "Terminal"
    in_tmux = False
    while curr and curr > 1 and curr not in visited and curr in procs:
        visited.add(curr)
        p = procs[curr]
        hay = f"{p['comm']} {p['comm_raw']} {p['args']}"
        if p["comm"].startswith("tmux"):
            in_tmux = True
            break
        if host_app == "Terminal":
            for label, pat in HOST_APP_MATCHERS:
                if pat.search(hay):
                    host_app = label
                    break
        curr = p["ppid"]
    return in_tmux, host_app


def get_agy_summaries(now):
    if now - AGY_SUMMARY_CACHE["ts"] < 2.5 and AGY_SUMMARY_CACHE["data"]:
        return AGY_SUMMARY_CACHE["data"]
    if not AGY_SUMMARIES_DB.is_file():
        return {}
    out = {}
    try:
        con = sqlite3.connect(f"file:{AGY_SUMMARIES_DB}?mode=ro", uri=True, timeout=0.5)
        try:
            rows = con.execute(
                "SELECT conversation_id, title, preview, status, not_fully_idle, "
                "last_modified_time, last_user_input_time FROM conversation_summaries"
            ).fetchall()
            for cid, title, preview, status, not_idle, mod_str, input_str in rows:
                out[cid] = {
                    "title": (title or "").strip(),
                    "preview": (preview or "").strip(),
                    "status": (status or "").strip(),
                    "not_fully_idle": bool(not_idle),
                    "last_modified_ts": _parse_iso_ts(mod_str),
                    "last_user_input_ts": _parse_iso_ts(input_str),
                }
        except sqlite3.OperationalError:
            rows = con.execute(
                "SELECT conversation_id, title, preview, status, not_fully_idle FROM conversation_summaries"
            ).fetchall()
            for cid, title, preview, status, not_idle in rows:
                out[cid] = {
                    "title": (title or "").strip(),
                    "preview": (preview or "").strip(),
                    "status": (status or "").strip(),
                    "not_fully_idle": bool(not_idle),
                    "last_modified_ts": None,
                    "last_user_input_ts": None,
                }
        finally:
            con.close()
        AGY_SUMMARY_CACHE["ts"] = now
        AGY_SUMMARY_CACHE["data"] = out
    except (sqlite3.Error, OSError):
        return AGY_SUMMARY_CACHE.get("data", {})
    return out


def get_agy_presence(now):
    if now - AGY_PRESENCE_CACHE["ts"] < 2.5:
        return AGY_PRESENCE_CACHE["pid_to_conv"], AGY_PRESENCE_CACHE["active_convs"]
    if not AGY_PRESENCE_DIR.is_dir():
        return {}, None
    pid_to_conv = {}
    active_convs = set()
    try:
        r = subprocess.run(
            ["lsof", "-Fn", "+D", str(AGY_PRESENCE_DIR)],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
        curr_pid = None
        for ln in r.stdout.splitlines():
            if ln.startswith("p") and ln[1:].isdigit():
                curr_pid = int(ln[1:])
            elif ln.startswith("n") and ln.endswith(".lock"):
                cid = os.path.basename(ln[1:])[:-5]
                if cid:
                    active_convs.add(cid)
                    if curr_pid:
                        pid_to_conv[curr_pid] = cid
        AGY_PRESENCE_CACHE["ts"] = now
        AGY_PRESENCE_CACHE["pid_to_conv"] = pid_to_conv
        AGY_PRESENCE_CACHE["active_convs"] = active_convs
    except (OSError, subprocess.SubprocessError):
        return AGY_PRESENCE_CACHE["pid_to_conv"], AGY_PRESENCE_CACHE["active_convs"] or None
    return pid_to_conv, active_convs


def _read_agy_transcript_steps(conv_id):
    if not conv_id:
        return None
    tfile = AGY_BRAIN_DIR / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
    try:
        if not tfile.is_file():
            return None
        st = tfile.stat()
    except OSError:
        return None

    cached = AGY_TRANSCRIPT_CACHE.get(conv_id)
    if cached and cached["mtime"] == st.st_mtime and cached["size"] == st.st_size:
        return cached

    try:
        with open(tfile, "rb") as f:
            head_raw = f.read(8192).decode("utf-8", "replace")
            if st.st_size > 8192:
                f.seek(max(0, st.st_size - 60000))
                tail_raw = f.read().decode("utf-8", "replace")
            else:
                tail_raw = head_raw
    except OSError:
        return None

    head_steps = []
    for ln in head_raw.splitlines()[:10]:
        try:
            head_steps.append(json.loads(ln))
        except ValueError:
            pass

    tail_steps = []
    for ln in tail_raw.splitlines()[1 if st.st_size > 8192 else 0:]:
        try:
            tail_steps.append(json.loads(ln))
        except ValueError:
            pass

    if not tail_steps:
        return None

    entry = {
        "mtime": st.st_mtime,
        "size": st.st_size,
        "head": head_steps,
        "tail": tail_steps,
    }
    AGY_TRANSCRIPT_CACHE[conv_id] = entry
    return entry


def _extract_cwd_from_steps(steps, fallback_cwd="", dev_cwd=""):
    git_candidates = []
    dir_candidates = []
    for st in steps:
        for tc in st.get("tool_calls") or []:
            args = tc.get("args") or {}
            raw_paths = []
            for key in ("Path", "DirectoryPath", "SearchPath", "TargetFile"):
                val = str(args.get(key) or "").strip('"')
                if val.startswith("/"):
                    raw_paths.append(val)
            cmd_line = str(args.get("CommandLine") or "")
            for m in ABS_PATH_TOKEN_RE.finditer(cmd_line):
                raw_paths.append(m.group(1))

            for raw_p in raw_paths:
                if "/.gemini/" in raw_p or "/.nvm/" in raw_p or "/opt/homebrew/" in raw_p:
                    continue
                groot = _nearest_git_root(raw_p)
                if groot:
                    git_candidates.append(groot)
                else:
                    target_dir = raw_p if os.path.isdir(raw_p) else os.path.dirname(raw_p)
                    if target_dir and os.path.isdir(target_dir) and not target_dir.startswith("/tmp"):
                        dir_candidates.append(target_dir)

    if git_candidates:
        return git_candidates[-1]
    if dev_cwd and os.path.isdir(dev_cwd):
        return dev_cwd
    if fallback_cwd:
        fb_git = _nearest_git_root(fallback_cwd)
        if fb_git:
            return fb_git
        if os.path.isdir(fallback_cwd):
            return fallback_cwd
    if dir_candidates:
        return dir_candidates[-1]
    return HOME


def _extract_agy_task(steps, label="", summary_title=""):
    if label:
        return label
    latest_user = ""
    latest_activity = ""
    for st in steps[-24:]:
        stype = st.get("type", "")
        if stype == "USER_INPUT":
            m = USER_REQ_RE.search(st.get("content") or "")
            txt = (m.group(1) if m else (st.get("content") or "")).strip()
            if txt:
                first_line = next((l.strip() for l in txt.splitlines() if l.strip()), "")
                if first_line and first_line.lower() not in {"hi", "hello", "hey", "ok", "okay", "yes"}:
                    latest_user = first_line[:90]
        elif stype == "PLANNER_RESPONSE":
            for tc in st.get("tool_calls") or []:
                targs = tc.get("args") or {}
                tsum = str(targs.get("toolSummary") or "").strip('"')
                if tsum:
                    latest_activity = tsum[:90]
            thinking = (st.get("thinking") or "").strip()
            if thinking:
                hm = re.findall(r"\*\*([^*]{4,85})\*\*", thinking)
                if hm:
                    latest_activity = hm[-1].strip()[:90]
    return latest_activity or latest_user or summary_title or "Antigravity conversation"


def _parse_transcript_arg(val):
    if val is None or isinstance(val, (dict, list, bool, int, float)):
        return val
    s = str(val).strip()
    if not s:
        return ""
    for _ in range(2):
        if isinstance(s, str) and len(s) >= 2 and s[0] in ('"', "[", "{"):
            try:
                s = json.loads(s)
                continue
            except ValueError:
                break
        break
    if isinstance(s, str):
        return s.strip('"')
    return s


def extract_agy_pending_action(summary_row, t_entry):
    """
    Extracts structured pending questions or permission approvals for Antigravity (agy)
    sessions from transcript.jsonl and conversation_summaries.db.
    """
    s_raw = (summary_row or {}).get("status", "")
    is_waiting = "WAITING" in s_raw
    last_step = t_entry["tail"][-1] if (t_entry and t_entry.get("tail")) else None
    last_type = last_step.get("type", "") if last_step else ""
    last_tcs = (last_step.get("tool_calls") or []) if (last_step and last_type == "PLANNER_RESPONSE") else []

    # 1. Explicit multiple-choice question via ask_question tool call
    for tc in last_tcs:
        if tc.get("name") != "ask_question":
            continue
        targs = tc.get("args") or {}
        q_list = _parse_transcript_arg(targs.get("questions"))
        if not isinstance(q_list, list) or not q_list:
            continue
        q0 = q_list[0] if isinstance(q_list[0], dict) else {}
        q_text = str(q0.get("question") or "Select an option").strip()
        raw_opts = q0.get("options") if isinstance(q0.get("options"), list) else []
        multi = bool(q0.get("is_multi_select"))

        if len(q_list) > 1:
            q_title = f"{q_text} (1/{len(q_list)})"
            extra_qs = [
                str(q.get("question") or "").strip()
                for q in q_list[1:3]
                if isinstance(q, dict) and q.get("question")
            ]
            q_detail = ("Next: " + " · ".join(extra_qs))[:160] if extra_qs else ""
        else:
            q_title = q_text
            q_detail = "Select all that apply, then press Submit." if multi else ""

        choices = []
        for idx, opt in enumerate(raw_opts[:6], start=1):
            opt_clean = re.sub(r"\s+", " ", str(opt or "")).strip()
            if not opt_clean:
                continue
            is_rec = opt_clean.lower().startswith("(recommended)")
            disp = re.sub(r"^\(recommended\)\s*", "", opt_clean, flags=re.I)
            short_disp = disp if len(disp) <= 44 else disp[:43] + "…"
            choices.append({
                "type": "keys",
                "keys": [str(idx)],
                "label": f"{idx}. {short_disp}",
                "tooltip": f"{idx}. {opt_clean}",
                "style": "primary" if (idx == 1 and is_rec and not multi) else "",
            })
        if multi:
            choices.append({
                "type": "keys",
                "keys": ["Enter"],
                "label": "Submit (Enter)",
                "tooltip": "Submit selected choices",
                "style": "primary",
            })
        choices.append({
            "type": "keys",
            "keys": ["Escape"],
            "label": "Cancel (Esc)",
            "tooltip": "Cancel question prompt",
            "style": "subtle",
        })
        return {
            "kind": "question",
            "title": q_title[:140],
            "detail": q_detail,
            "choices": choices,
        }

    # 2. Tool / command / sandbox approval gate (CASCADE_RUN_STATUS_WAITING)
    if is_waiting:
        chosen_tc = None
        for tc in reversed(last_tcs):
            if tc.get("name") == "run_command":
                chosen_tc = tc
                break
        if not chosen_tc and last_tcs:
            chosen_tc = last_tcs[-1]

        title = "Action approval required"
        detail = ""
        if chosen_tc:
            tname = chosen_tc.get("name") or "tool"
            targs = chosen_tc.get("args") or {}
            if tname == "run_command":
                cmd_line = str(_parse_transcript_arg(targs.get("CommandLine")) or "").strip()
                tsum = str(_parse_transcript_arg(targs.get("toolSummary")) or "").strip()
                bypass = str(_parse_transcript_arg(targs.get("BypassSandbox")) or "").lower() == "true"
                prefix = "Approve unsandboxed command" if bypass else "Approve command"
                title = f"{prefix}: {tsum or _shorten_cmd(cmd_line, 56) or 'terminal command'}"
                detail = cmd_line[:180]
            else:
                target_val = str(
                    _parse_transcript_arg(
                        targs.get("Path") or targs.get("DirectoryPath") or targs.get("url") or targs.get("toolSummary")
                    ) or ""
                ).strip()
                short_t = os.path.basename(target_val.rstrip("/")) if target_val.startswith("/") else target_val[:56]
                title = f"Approve {tname}{f': {short_t}' if short_t else ''}"
                detail = target_val[:180] if target_val != short_t else ""
        elif summary_row and summary_row.get("preview"):
            detail = summary_row["preview"][:150]

        choices = [
            {
                "type": "keys",
                "keys": ["1"],
                "label": "1. Allow once",
                "tooltip": "Approve this action once",
                "style": "primary",
            },
            {
                "type": "keys",
                "keys": ["2"],
                "label": "2. Always allow",
                "tooltip": "Approve and persist allow rule",
                "style": "",
            },
            {
                "type": "keys",
                "keys": ["Escape"],
                "label": "Deny (Esc)",
                "tooltip": "Reject / cancel action",
                "style": "danger",
            },
        ]
        return {
            "kind": "approval",
            "title": title[:140],
            "detail": detail,
            "choices": choices,
        }

    return None


def _trim_code_block(raw_text, max_lines=14, max_line_len=140):
    if not raw_text:
        return []
    cleaned_lines = []
    for ln in str(raw_text).replace("\r\n", "\n").replace("\r", "\n").splitlines():
        s = strip_ansi(ln).rstrip()
        if not s.strip() and (not cleaned_lines or not cleaned_lines[-1]):
            continue
        if len(s) > max_line_len:
            s = s[: max_line_len - 1] + "…"
        cleaned_lines.append(s)
    while cleaned_lines and not cleaned_lines[-1]:
        cleaned_lines.pop()
    if len(cleaned_lines) > max_lines:
        omitted = len(cleaned_lines) - max_lines
        cleaned_lines = cleaned_lines[:max_lines] + [f"… ({omitted} more lines)"]
    return cleaned_lines


def _extract_generic_cmd_output(raw_content):
    if not raw_content or "Command output:" not in raw_content:
        return []
    _, _, after = raw_content.partition("Command output:\n")
    if not after.strip():
        return []
    # Strip trailing system-message wrappers if present
    after = after.split("\n\nThe following is a <SYSTEM_MESSAGE>", 1)[0]
    return _trim_code_block(after, max_lines=14, max_line_len=140)


def _render_agy_transcript(conv_id, steps, cwd, header_prefix="Antigravity Live Session", title="", pending_action=None):
    title_str = f" — {title}" if title else ""
    lines = [
        f"\x1b[1;36m{header_prefix}{title_str}\x1b[0m  \x1b[2m({conv_id})\x1b[0m",
        f"\x1b[2mWorkspace: {cwd}\x1b[0m",
        "\x1b[2m" + ("─" * 68) + "\x1b[0m",
    ]
    last_had_run_cmd = False
    for st in steps[-28:]:
        stype = st.get("type", "")
        content = st.get("content") or ""
        if stype == "USER_INPUT":
            last_had_run_cmd = False
            m = USER_REQ_RE.search(content)
            user_txt = (m.group(1) if m else content).strip()
            if user_txt:
                short_u = user_txt if len(user_txt) <= 700 else user_txt[:700] + " …"
                lines.append(f"\n\x1b[1;32m❯ User\x1b[0m\n{short_u}")
        elif stype == "PLANNER_RESPONSE":
            last_had_run_cmd = False
            thinking = (st.get("thinking") or "").strip()
            if thinking:
                hm = re.findall(r"\*\*([^*]{4,80})\*\*", thinking)
                if hm:
                    lines.append(f"\x1b[2m  • {hm[-1]}\x1b[0m")
            for tc in st.get("tool_calls") or []:
                tname = tc.get("name", "tool")
                targs = tc.get("args") or {}
                if tname == "run_command":
                    last_had_run_cmd = True
                    cmd_str = str(_parse_transcript_arg(targs.get("CommandLine")) or "").strip()
                    tsum = str(_parse_transcript_arg(targs.get("toolSummary")) or "").strip()
                    if tsum:
                        lines.append(f"\x1b[33m  ⚙ {tsum}\x1b[0m")
                    if cmd_str:
                        lines.append(f"\x1b[1;32m  $ {cmd_str[:160]}\x1b[0m")
                elif tname in ("edit_file", "write_file"):
                    fpath = str(_parse_transcript_arg(targs.get("Path")) or "").strip()
                    short_f = os.path.basename(fpath) if fpath else fpath
                    lines.append(f"\x1b[36m  ✎ {tname}\x1b[0m \x1b[1m{short_f}\x1b[0m \x1b[2m{fpath}\x1b[0m")
                    snippet_raw = _parse_transcript_arg(targs.get("Replacement") or targs.get("Content") or "")
                    for sln in _trim_code_block(snippet_raw, max_lines=8, max_line_len=130):
                        lines.append(f"\x1b[2m    │ {sln}\x1b[0m")
                else:
                    summary = (
                        str(_parse_transcript_arg(targs.get("toolSummary") or targs.get("Path") or targs.get("CommandLine")) or "")
                        .strip()[:100]
                    )
                    lines.append(f"\x1b[33m  ⚙ {tname}\x1b[0m \x1b[2m{summary}\x1b[0m")
            if content.strip():
                lines.append(f"\n\x1b[1;34m◆ Antigravity\x1b[0m\n{content.strip()}")
        elif stype == "GENERIC" and last_had_run_cmd:
            out_lines = _extract_generic_cmd_output(content)
            for oln in out_lines:
                lines.append(f"\x1b[2m    {oln}\x1b[0m")
            if out_lines:
                last_had_run_cmd = False
    if pending_action:
        lines.append("\n\x1b[1;33m● Action Needed — " + pending_action["title"] + "\x1b[0m")
        if pending_action.get("detail"):
            lines.append(f"\x1b[2m  {pending_action['detail']}\x1b[0m")
        for ch in pending_action.get("choices") or []:
            lines.append(f"  \x1b[36m[{ch['label']}]\x1b[0m")
    return "\n".join(lines)


def _classify_agy_from_metadata(summary_row, t_entry, info, now):
    subtool = info.get("subtool")
    if t_entry:
        last_step = t_entry["tail"][-1]
        last_type = last_step.get("type", "")
        last_tcs = last_step.get("tool_calls") or []
        age = now - t_entry["mtime"]
        if last_type == "PLANNER_RESPONSE" and any(tc.get("name") == "ask_question" for tc in last_tcs) and age < 7200:
            return "needs_input", subtool
        if summary_row:
            s_raw = summary_row.get("status", "")
            if "WAITING" in s_raw:
                return "needs_input", subtool
            if "RUNNING" in s_raw or summary_row.get("not_fully_idle"):
                if not subtool and last_tcs:
                    subtool = last_tcs[-1].get("name")
                return "working", subtool
            if subtool:
                return "working", subtool
            if age < 1800 and last_type == "PLANNER_RESPONSE" and not last_tcs:
                return "done", None
            return "idle", None
        if age < 90 and (last_tcs or last_type in ("USER_INPUT", "GENERIC")):
            if not subtool and last_tcs:
                subtool = last_tcs[-1].get("name")
            return "working", subtool
        if subtool:
            return "working", subtool
        if age < 1800 and last_type == "PLANNER_RESPONSE" and not last_tcs:
            return "done", None
        return "idle", None

    if summary_row:
        s_raw = summary_row.get("status", "")
        if "WAITING" in s_raw:
            return "needs_input", subtool
        if "RUNNING" in s_raw or summary_row.get("not_fully_idle") or subtool:
            return "working", subtool
    return ("working" if subtool else "idle"), subtool


def _clean_claude_user_text(raw_text):
    txt = (raw_text or "").strip()
    if not txt:
        return ""
    if "<command-message>" in txt or "<local-command" in txt or txt.startswith("<system-reminder>"):
        cm = re.search(r"<command-name>\s*(/[^\s<]+)\s*</command-name>", txt)
        return cm.group(1) if cm else ""
    txt = re.sub(r"<system-reminder>.*?</system-reminder>", "", txt, flags=re.DOTALL).strip()
    if txt.startswith("[Request interrupted"):
        return ""
    return txt


def _find_claude_transcript_path(launch_cwd, conv_id="", claimed_ids=None, now=None):
    if not CLAUDE_PROJECTS_DIR.is_dir():
        return None
    ts_now = now if now is not None else time.time()

    if conv_id:
        if launch_cwd:
            for slug in (re.sub(r"[^A-Za-z0-9-]", "-", launch_cwd), launch_cwd.replace("/", "-")):
                cand = CLAUDE_PROJECTS_DIR / slug / f"{conv_id}.jsonl"
                if cand.is_file():
                    return cand
        try:
            for pdir in CLAUDE_PROJECTS_DIR.iterdir():
                if pdir.is_dir():
                    cand = pdir / f"{conv_id}.jsonl"
                    if cand.is_file():
                        return cand
        except OSError:
            return None
        return None

    if not launch_cwd:
        return None

    seen_dirs = set()
    candidates = []
    for slug in (re.sub(r"[^A-Za-z0-9-]", "-", launch_cwd), launch_cwd.replace("/", "-")):
        pdir = CLAUDE_PROJECTS_DIR / slug
        if pdir in seen_dirs or not pdir.is_dir():
            continue
        seen_dirs.add(pdir)
        try:
            for jf in pdir.iterdir():
                if not jf.name.endswith(".jsonl") or jf.name.startswith("agent-"):
                    continue
                stem = jf.stem
                if claimed_ids and stem in claimed_ids:
                    continue
                st = jf.stat()
                if ts_now - st.st_mtime <= 86400:
                    candidates.append((st.st_mtime, jf))
        except OSError:
            continue

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _read_claude_transcript(jpath):
    if not jpath:
        return None
    try:
        st = jpath.stat()
    except OSError:
        return None

    key = str(jpath)
    cached = CLAUDE_TRANSCRIPT_CACHE.get(key)
    if cached and cached["mtime"] == st.st_mtime and cached["size"] == st.st_size:
        return cached

    try:
        with open(jpath, "rb") as f:
            head_raw = f.read(8192).decode("utf-8", "replace")
            if st.st_size > 8192:
                f.seek(max(0, st.st_size - 56000))
                tail_raw = f.read().decode("utf-8", "replace")
            else:
                tail_raw = head_raw
    except OSError:
        return None

    head_objs = []
    for ln in head_raw.splitlines()[:14]:
        try:
            head_objs.append(json.loads(ln))
        except ValueError:
            pass

    tail_objs = []
    for ln in tail_raw.splitlines()[1 if st.st_size > 8192 else 0:]:
        try:
            tail_objs.append(json.loads(ln))
        except ValueError:
            pass

    if not head_objs and not tail_objs:
        return None

    summary_title = ""
    first_user_title = ""
    detected_cwd = ""
    for obj in head_objs + tail_objs:
        if not isinstance(obj, dict):
            continue
        ocwd = obj.get("cwd")
        if isinstance(ocwd, str) and ocwd.startswith("/") and os.path.isdir(ocwd):
            detected_cwd = ocwd
        if obj.get("type") == "summary" and obj.get("summary"):
            summary_title = str(obj["summary"]).strip()
        elif obj.get("customTitle"):
            summary_title = str(obj["customTitle"]).strip()
        elif not first_user_title and obj.get("type") == "user":
            msg = obj.get("message") or {}
            content = msg.get("content")
            raw_u = ""
            if isinstance(content, str):
                raw_u = content
            elif isinstance(content, list):
                for blk in content:
                    if isinstance(blk, dict) and blk.get("type") == "text":
                        raw_u = blk.get("text") or ""
                        break
            cleaned_u = _clean_claude_user_text(raw_u)
            if cleaned_u and not cleaned_u.startswith("/"):
                first_ln = next((l.strip() for l in cleaned_u.splitlines() if l.strip()), "")
                if first_ln and first_ln.lower() not in {"hi", "hello", "hey", "ok", "yes", "continue"}:
                    first_user_title = first_ln[:64]

    pending_tools = []
    tool_id_names = {}
    turns = []
    latest_task = ""
    last_conv_role = ""
    last_user_ts = None

    for obj in tail_objs[-45:]:
        if not isinstance(obj, dict):
            continue
        otype = obj.get("type")
        msg = obj.get("message") if isinstance(obj.get("message"), dict) else {}
        content = msg.get("content")

        if otype == "user":
            ts_val = _parse_iso_ts(obj.get("timestamp"))
            if isinstance(content, str):
                utxt = _clean_claude_user_text(content)
                if utxt:
                    pending_tools.clear()
                    last_conv_role = "user"
                    if ts_val:
                        last_user_ts = ts_val
                    first_ln = next((l.strip() for l in utxt.splitlines() if l.strip()), "")
                    if first_ln:
                        latest_task = first_ln[:88]
                    turns.append(("user", utxt))
            elif isinstance(content, list):
                answered = {
                    blk.get("tool_use_id")
                    for blk in content
                    if isinstance(blk, dict) and blk.get("type") == "tool_result"
                }
                if answered:
                    pending_tools = [t for t in pending_tools if t.get("id") not in answered]
                for blk in content:
                    if not isinstance(blk, dict):
                        continue
                    if blk.get("type") == "tool_result":
                        tuid = blk.get("tool_use_id")
                        src_tool = tool_id_names.get(tuid, "")
                        is_err = bool(blk.get("is_error"))
                        if src_tool == "Bash" or is_err:
                            rc = blk.get("content")
                            if isinstance(rc, list):
                                rc = "\n".join(
                                    str(x.get("text") or "")
                                    for x in rc
                                    if isinstance(x, dict) and x.get("type") == "text"
                                )
                            out_preview = _trim_code_block(rc, max_lines=12, max_line_len=140)
                            if out_preview:
                                turns.append(("output", out_preview, is_err))
                    elif blk.get("type") == "text":
                        utxt = _clean_claude_user_text(blk.get("text") or "")
                        if utxt:
                            pending_tools.clear()
                            last_conv_role = "user"
                            if ts_val:
                                last_user_ts = ts_val
                            first_ln = next((l.strip() for l in utxt.splitlines() if l.strip()), "")
                            if first_ln:
                                latest_task = first_ln[:88]
                            turns.append(("user", utxt))
        elif otype == "assistant" and isinstance(content, list):
            last_conv_role = "assistant"
            for blk in content:
                if not isinstance(blk, dict):
                    continue
                btype = blk.get("type")
                if btype == "tool_use":
                    tname = str(blk.get("name") or "tool")
                    tid = blk.get("id")
                    if tid:
                        tool_id_names[tid] = tname
                    tinp = blk.get("input") if isinstance(blk.get("input"), dict) else {}
                    pending_tools.append({"id": tid, "name": tname, "input": tinp})
                    tsum = str(
                        tinp.get("description")
                        or tinp.get("command")
                        or tinp.get("file_path")
                        or tinp.get("pattern")
                        or ""
                    ).strip()
                    if tsum:
                        short_s = os.path.basename(tsum) if tsum.startswith("/") and " " not in tsum else _shorten_cmd(tsum, 72)
                        latest_task = f"{tname}: {short_s}"[:88]
                    cmd_str = str(tinp.get("command") or "").strip() if tname == "Bash" else ""
                    code_snip = []
                    if tname in ("Edit", "Write"):
                        code_snip = _trim_code_block(
                            tinp.get("new_string") or tinp.get("content") or "",
                            max_lines=8,
                            max_line_len=130,
                        )
                    turns.append(("tool", tname, tsum[:110], cmd_str[:160], code_snip))
                elif btype == "text":
                    atxt = str(blk.get("text") or "").strip()
                    if atxt:
                        turns.append(("assistant", atxt))

    entry = {
        "session_id": jpath.stem,
        "mtime": st.st_mtime,
        "size": st.st_size,
        "title": summary_title or first_user_title,
        "cwd": detected_cwd,
        "latest_task": latest_task,
        "turns": turns[-26:],
        "pending_tools": pending_tools,
        "last_role": last_conv_role,
        "last_user_ts": last_user_ts,
    }
    CLAUDE_TRANSCRIPT_CACHE[key] = entry
    return entry


def extract_claude_pending_action(c_entry, info, now, tab_spinning=False):
    if not c_entry or not c_entry.get("pending_tools"):
        return None
    age = now - c_entry["mtime"]
    if age > 7200:
        return None

    for tc in c_entry["pending_tools"]:
        if tc.get("name") != "AskUserQuestion":
            continue
        tinp = tc.get("input") or {}
        q_list = tinp.get("questions") if isinstance(tinp.get("questions"), list) else []
        if not q_list:
            continue
        q0 = q_list[0] if isinstance(q_list[0], dict) else {}
        q_text = str(q0.get("question") or "Select an option").strip()
        multi = bool(q0.get("multiSelect"))
        raw_opts = q0.get("options") if isinstance(q0.get("options"), list) else []
        choices = []
        for idx, opt in enumerate(raw_opts[:6], start=1):
            lbl_raw = opt.get("label") if isinstance(opt, dict) else str(opt or "")
            desc_raw = opt.get("description") if isinstance(opt, dict) else ""
            lbl_clean = re.sub(r"\s+", " ", str(lbl_raw or "")).strip()
            if not lbl_clean:
                continue
            short_l = lbl_clean if len(lbl_clean) <= 42 else lbl_clean[:41] + "…"
            tip = f"{idx}. {lbl_clean}" + (f" — {desc_raw}" if desc_raw else "")
            choices.append({
                "type": "keys",
                "keys": [str(idx)],
                "label": f"{idx}. {short_l}",
                "tooltip": tip[:160],
                "style": "primary" if (idx == 1 and not multi) else "",
            })
        if multi:
            choices.append({"type": "keys", "keys": ["Enter"], "label": "Submit (Enter)", "style": "primary"})
        choices.append({"type": "keys", "keys": ["Escape"], "label": "Cancel (Esc)", "style": "subtle"})
        return {
            "kind": "question",
            "title": q_text[:140],
            "detail": "Select all that apply, then press Submit." if multi else "",
            "choices": choices,
        }

    if info.get("subtool") or tab_spinning or (info.get("agent_meta") or {}).get("skip_perms") or age < 2.5:
        return None

    tc = c_entry["pending_tools"][-1]
    tname = tc.get("name") or ""
    if tname not in ("Bash", "Edit", "MultiEdit", "Write", "NotebookEdit") and not tname.startswith("mcp__"):
        return None
    tinp = tc.get("input") or {}
    if tname == "Bash":
        cmd_line = str(tinp.get("command") or "").strip()
        desc = str(tinp.get("description") or "").strip()
        title = f"Approve Bash: {desc or _shorten_cmd(cmd_line, 56) or 'shell command'}"
        detail = cmd_line[:180]
    else:
        fpath = str(tinp.get("file_path") or tinp.get("notebook_path") or "").strip()
        short_f = os.path.basename(fpath.rstrip("/")) if fpath.startswith("/") else fpath[:56]
        title = f"Approve {tname}{f': {short_f}' if short_f else ''}"
        detail = fpath[:180] if fpath != short_f else ""

    return {
        "kind": "approval",
        "title": title[:140],
        "detail": detail,
        "choices": [
            {"type": "keys", "keys": ["1"], "label": "1. Yes", "tooltip": "Approve once", "style": "primary"},
            {"type": "keys", "keys": ["2"], "label": "2. Yes, allow similar", "tooltip": "Approve and remember for session", "style": ""},
            {"type": "keys", "keys": ["Escape"], "label": "No (Esc)", "tooltip": "Reject / cancel action", "style": "danger"},
        ],
    }


def _render_claude_transcript(conv_id, c_entry, cwd, header_prefix="Claude Code Session", title="", pending_action=None):
    title_str = f" — {title}" if title else ""
    lines = [
        f"\x1b[1;33m{header_prefix}{title_str}\x1b[0m  \x1b[2m({conv_id[:12]})\x1b[0m",
        f"\x1b[2mWorkspace: {cwd}\x1b[0m",
        "\x1b[2m" + ("─" * 68) + "\x1b[0m",
    ]
    for item in (c_entry.get("turns") or [])[-26:]:
        kind = item[0]
        if kind == "user":
            utxt = item[1]
            short_u = utxt if len(utxt) <= 700 else utxt[:700] + " …"
            lines.append(f"\n\x1b[1;32m❯ User\x1b[0m\n{short_u}")
        elif kind == "tool":
            tname = item[1]
            tsum = item[2]
            cmd_str = item[3] if len(item) > 3 else ""
            code_snip = item[4] if len(item) > 4 else []
            if tname == "Bash" and cmd_str:
                if tsum and tsum != cmd_str:
                    lines.append(f"\x1b[33m  ⚙ {tsum}\x1b[0m")
                lines.append(f"\x1b[1;32m  $ {cmd_str}\x1b[0m")
            elif tname in ("Edit", "MultiEdit", "Write"):
                short_f = os.path.basename(tsum) if tsum.startswith("/") else tsum
                lines.append(f"\x1b[36m  ✎ {tname}\x1b[0m \x1b[1m{short_f}\x1b[0m \x1b[2m{tsum}\x1b[0m")
                for sln in code_snip:
                    lines.append(f"\x1b[2m    │ {sln}\x1b[0m")
            else:
                lines.append(f"\x1b[33m  ⚙ {tname}\x1b[0m \x1b[2m{tsum}\x1b[0m")
        elif kind == "output":
            out_lines, is_err = item[1], item[2]
            clr = "\x1b[31m" if is_err else "\x1b[2m"
            for oln in out_lines:
                lines.append(f"{clr}    {oln}\x1b[0m")
        elif kind == "assistant":
            lines.append(f"\n\x1b[1;35m◆ Claude\x1b[0m\n{item[1]}")
    if pending_action:
        lines.append("\n\x1b[1;33m● Action Needed — " + pending_action["title"] + "\x1b[0m")
        if pending_action.get("detail"):
            lines.append(f"\x1b[2m  {pending_action['detail']}\x1b[0m")
        for ch in pending_action.get("choices") or []:
            lines.append(f"  \x1b[36m[{ch['label']}]\x1b[0m")
    return "\n".join(lines)


def discover_external_ttys(proc_snapshot, now):
    if not proc_snapshot:
        return [], set()

    procs, children = proc_snapshot
    running_gui = _running_gui_terminals(procs)
    summaries = get_agy_summaries(now)
    pid_to_conv, _ = get_agy_presence(now)

    # Exclude Agent Deck's own process tree (and any running agent_deck.py server + its subprocesses)
    self_pids = {
        pid for pid, p in procs.items()
        if pid == MY_PID or "agent_deck.py" in (p.get("args") or "")
    }
    sq = list(self_pids)
    while sq:
        cur = sq.pop()
        for ch in children.get(cur, []):
            if ch not in self_pids:
                self_pids.add(ch)
                sq.append(ch)

    by_tty = {}
    for pid, p in procs.items():
        tty = p["tty"]
        if not tty or tty == "??" or not tty.startswith("tty"):
            continue
        if pid in self_pids:
            continue
        by_tty.setdefault(tty, []).append(pid)

    tty_entries = []
    pids_for_cwd = []

    for tty, pids in sorted(by_tty.items()):
        tty_set = set(pids)
        roots = [pid for pid in pids if procs[pid]["ppid"] not in tty_set]
        if not roots:
            roots = [min(pids)]
        root_pid = roots[0]

        in_tmux, host_app = _detect_host_app_and_tmux(root_pid, procs)
        if in_tmux:
            continue

        # Skip sub-PTYs spawned by a process that already runs inside another TTY (e.g. agy background tasks)
        is_sub_pty = False
        anc_pid = procs[root_pid]["ppid"]
        seen_anc = {root_pid}
        while anc_pid and anc_pid > 1 and anc_pid not in seen_anc and anc_pid in procs:
            seen_anc.add(anc_pid)
            anc_tty = procs[anc_pid].get("tty") or ""
            if anc_tty.startswith("tty") and anc_tty != tty:
                is_sub_pty = True
                break
            anc_pid = procs[anc_pid]["ppid"]
        if is_sub_pty:
            continue

        lineage = []
        q = [(root_pid, 0)]
        visited = {root_pid}
        while q:
            curr, depth = q.pop(0)
            if curr == MY_PID:
                continue
            if curr in procs:
                pr = procs[curr]
                lineage.append((curr, depth, pr["comm"], pr["args"], pr.get("tty")))
            for ch in children.get(curr, []):
                if ch not in visited:
                    visited.add(ch)
                    q.append((ch, depth + 1))

        if not lineage:
            continue

        info = inspect_lineage(lineage, dead=False, fallback_cmd=procs[root_pid]["comm"], root_tty=tty)

        root_comm = procs[root_pid]["comm"].lower()
        if not info["agent_running"] and root_comm not in SHELLS:
            continue

        focus_pid = info["focus_pid"] or root_pid
        pids_for_cwd.extend([focus_pid, root_pid])
        tty_entries.append((tty, root_pid, focus_pid, host_app, info, lineage))

    cwd_map = batch_lsof_cwds(pids_for_cwd)
    results = []
    seen_convs = set()
    claimed_claude_ids = set()

    prepared = []
    ghostty_candidates = []

    for tty, root_pid, focus_pid, host_app, info, lineage in tty_entries:
        sid = f"tty:{tty}"
        if sid in DISMISSED:
            continue
        launch_cwd = cwd_map.get(focus_pid) or cwd_map.get(root_pid) or HOME
        cwd = launch_cwd

        conv_id = (info["agent_meta"] or {}).get("conversation")
        if not conv_id and info["agent_kind"] == "agy":
            conv_id = pid_to_conv.get(focus_pid)
            if not conv_id:
                for l_pid, *_ in lineage:
                    if l_pid in pid_to_conv:
                        conv_id = pid_to_conv[l_pid]
                        break
            if conv_id:
                info["agent_meta"] = dict(info["agent_meta"] or {}, conversation=conv_id)

        if conv_id and info["agent_kind"] == "agy":
            seen_convs.add(conv_id)

        summary_row = summaries.get(conv_id) if (conv_id and info["agent_kind"] == "agy") else None
        conv_title = (summary_row or {}).get("title", "")
        t_entry = _read_agy_transcript_steps(conv_id) if (conv_id and info["agent_kind"] == "agy") else None

        c_entry = None
        if info["agent_kind"] == "claude":
            c_path = _find_claude_transcript_path(
                launch_cwd,
                conv_id=conv_id or "",
                claimed_ids=claimed_claude_ids,
                now=now,
            )
            c_entry = _read_claude_transcript(c_path) if c_path else None
            if c_entry:
                conv_id = c_entry["session_id"]
                claimed_claude_ids.add(conv_id)
                info["agent_meta"] = dict(info["agent_meta"] or {}, conversation=conv_id)
                if c_entry.get("title"):
                    conv_title = c_entry["title"]

        if t_entry:
            cwd = _extract_cwd_from_steps(
                t_entry["tail"],
                fallback_cwd=launch_cwd,
                dev_cwd=info.get("dev_cwd") or "",
            )
        elif c_entry and c_entry.get("cwd"):
            cwd = _nearest_git_root(c_entry["cwd"]) or c_entry["cwd"]
        elif info.get("dev_cwd"):
            cwd = info["dev_cwd"]

        rec = {
            "sid": sid,
            "tty": tty,
            "root_pid": root_pid,
            "focus_pid": focus_pid,
            "host_app": host_app,
            "info": info,
            "launch_cwd": launch_cwd,
            "cwd": cwd,
            "conv_id": conv_id,
            "summary_row": summary_row,
            "conv_title": conv_title,
            "t_entry": t_entry,
            "c_entry": c_entry,
            "agent_cmd": info["agent_cmd"],
            "agent_kind": info["agent_kind"],
        }
        prepared.append(rec)
        if host_app == "Ghostty" and "Ghostty" in running_gui:
            ghostty_candidates.append(rec)

    ghostty_map = (
        match_ghostty_surfaces(ghostty_candidates, macos_list_ghostty_terminals(now))
        if ghostty_candidates
        else {}
    )

    for rec in prepared:
        sid = rec["sid"]
        tty = rec["tty"]
        root_pid = rec["root_pid"]
        focus_pid = rec["focus_pid"]
        host_app = rec["host_app"]
        info = rec["info"]
        cwd = rec["cwd"]
        conv_id = rec["conv_id"]
        summary_row = rec["summary_row"]
        conv_title = rec["conv_title"]
        t_entry = rec["t_entry"]
        c_entry = rec["c_entry"]
        dev_tty = f"/dev/{tty}"

        g_surf = ghostty_map.get(sid)
        ghostty_id = g_surf["id"] if g_surf else ""

        can_script = host_app in running_gui and host_app in ("Terminal.app", "iTerm2")
        tab_title, raw_screen = macos_read_tty_tab(host_app, dev_tty) if can_script else ("", None)
        if not tab_title and g_surf:
            tab_title = g_surf.get("name") or ""

        claude_tab_title, claude_tab_spinning, _ = (
            _clean_claude_tab_title(tab_title)
            if info["agent_kind"] == "claude"
            else ("", False, False)
        )
        if info["agent_kind"] == "claude" and claude_tab_title and not conv_title:
            conv_title = claude_tab_title

        agy_action = (
            extract_agy_pending_action(summary_row, t_entry)
            if info["agent_kind"] == "agy" and (summary_row or t_entry)
            else None
        )
        claude_action = (
            extract_claude_pending_action(c_entry, info, now, tab_spinning=claude_tab_spinning)
            if info["agent_kind"] == "claude" and c_entry
            else None
        )

        if raw_screen:
            ansi_text = raw_screen[-18000:]
            plain_text = strip_ansi(ansi_text)
        elif t_entry:
            ansi_text = _render_agy_transcript(
                conv_id,
                t_entry["tail"],
                cwd,
                header_prefix=f"{host_app} · {tty}",
                title=conv_title,
                pending_action=agy_action,
            )
            plain_text = strip_ansi(ansi_text)
        elif c_entry:
            ansi_text = _render_claude_transcript(
                conv_id or tty,
                c_entry,
                cwd,
                header_prefix=f"{host_app} · {tty}",
                title=conv_title,
                pending_action=claude_action,
            )
            plain_text = strip_ansi(ansi_text)
        else:
            kind_str = (info["agent_kind"] or info["agent_cmd"] or "shell").upper()
            sub_str = f" → {info['subtool_cmd']}" if info.get("subtool_cmd") else ""
            ctrl_note = (
                "Direct reply & keystroke control enabled via Ghostty AppleScript."
                if ghostty_id
                else f"Click 'Open Terminal' to jump to its window, or 'Resume in tmux' to control this {kind_str} session inside Agent Deck."
            )
            ansi_text = (
                f"\x1b[1;36m{host_app} · {dev_tty}\x1b[0m\n"
                f"Process:  \x1b[1m{info['agent_cmd']}{sub_str}\x1b[0m (PID {focus_pid})\n"
                f"Folder:   {cwd}\n\n"
                f"\x1b[2m{host_app} keeps its screen buffer private on macOS.\n"
                f"{ctrl_note}\x1b[0m"
            )
            plain_text = strip_ansi(ansi_text)

        digest = hashlib.sha1(ansi_text.encode("utf-8", "replace")).hexdigest()
        OUTPUT_CACHE[sid] = {"ansi": ansi_text, "plain": plain_text, "hash": digest, "ts": now}

        proc_started = (
            procs.get(focus_pid, {}).get("started_at")
            or procs.get(root_pid, {}).get("started_at")
        )
        summary_mod_ts = (summary_row or {}).get("last_modified_ts")
        summary_input_ts = (summary_row or {}).get("last_user_input_ts") or (c_entry.get("last_user_ts") if c_entry else None)
        known_activity_ts = max(
            [
                ts for ts in (
                    t_entry["mtime"] if t_entry else None,
                    c_entry["mtime"] if c_entry else None,
                    summary_mod_ts,
                )
                if ts
            ],
            default=None,
        )

        tr = TRACK.setdefault(sid, {
            "hash": digest,
            "last_change": known_activity_ts or proc_started or now,
            "last_change_exact": known_activity_ts is not None,
            "first_seen": now,
            "status": None,
            "had_agent": info["agent_running"],
            "agent_since": proc_started or (now if info["agent_running"] else None),
            "agent_since_exact": proc_started is not None,
            "agent_ended": None,
            "work_started_at": None,
            "worked_in_turn": False,
        })
        if proc_started is not None:
            tr["agent_since"] = proc_started
            tr["agent_since_exact"] = True
        if known_activity_ts is not None:
            tr["last_change"] = known_activity_ts
            tr["last_change_exact"] = True
            tr["hash"] = digest
        elif tr["hash"] != digest:
            tr["hash"] = digest
            tr["last_change"] = now
            tr["last_change_exact"] = True

        effective_subtool = info.get("subtool")
        pending_action = None
        if raw_screen:
            fake_p = {"dead": False}
            status, choices = classify(fake_p, plain_text, info, tr, now)
            ext_action = agy_action or claude_action
            if ext_action and status != "working":
                status = "needs_input"
                pending_action = ext_action
                choices = ext_action["choices"]
            elif status == "needs_input":
                pending_action = extract_screen_pending_action(plain_text, choices)
                choices = pending_action["choices"]
        elif info["agent_kind"] == "agy" and (summary_row or t_entry):
            status, effective_subtool = _classify_agy_from_metadata(summary_row, t_entry, info, now)
            if status == "needs_input" and agy_action:
                pending_action = agy_action
                choices = agy_action["choices"]
            elif status == "needs_input":
                pending_action = {
                    "kind": "approval",
                    "title": "Waiting for your confirmation",
                    "detail": "",
                    "choices": [
                        {"type": "keys", "keys": ["1"], "label": "1. Allow once", "style": "primary"},
                        {"type": "keys", "keys": ["2"], "label": "2. Always allow", "style": ""},
                        {"type": "keys", "keys": ["Escape"], "label": "Deny (Esc)", "style": "danger"},
                    ],
                }
                choices = pending_action["choices"]
            else:
                choices = []
        elif info["agent_kind"] == "claude":
            if claude_action:
                status = "needs_input"
                pending_action = claude_action
                choices = claude_action["choices"]
            elif info.get("subtool") or claude_tab_spinning or (c_entry and (now - c_entry["mtime"]) < 3.0):
                status = "working"
                choices = []
            elif c_entry and (now - c_entry["mtime"]) < 1800 and c_entry.get("last_role") == "assistant" and not c_entry.get("pending_tools"):
                status = "done"
                choices = []
            else:
                status = "idle"
                choices = []
        else:
            if info["agent_running"]:
                status = "working" if info.get("subtool") else "idle"
            else:
                status = "shell"
            choices = []

        if status == "working":
            if tr["work_started_at"] is None:
                tr["work_started_at"] = summary_input_ts or now
        else:
            tr["work_started_at"] = None

        turn_since = (summary_input_ts or tr["work_started_at"]) if status == "working" else None
        if tr["status"] is not None and tr["status"] != status:
            add_event({"id": sid, "target": sid, "session": conv_title or tty}, tr["status"], status, now)
        tr["status"] = status
        git_info = get_git_info(cwd, now)
        folder_name = os.path.basename(cwd.rstrip("/")) or tty
        clean_tab = claude_tab_title if info["agent_kind"] == "claude" else re.sub(r"\s*—\s*-?(?:zsh|bash|fish).*$", "", tab_title or "").strip()
        if conv_title:
            terminal_name = conv_title
        elif clean_tab:
            terminal_name = clean_tab.split(" — ")[0].strip() if " — " in clean_tab else clean_tab
        else:
            terminal_name = f"{folder_name} ({tty})"

        label_val = LABELS.get(sid, "")
        if pending_action and not label_val:
            current_task = pending_action["title"]
        elif t_entry and not raw_screen:
            if label_val:
                current_task = label_val
            elif info.get("subtool_cmd"):
                current_task = f"Running: {info['subtool_cmd']}"
            else:
                current_task = _extract_agy_task(t_entry["tail"], label="", summary_title=conv_title)
        elif c_entry and not raw_screen:
            if label_val:
                current_task = label_val
            elif info.get("subtool_cmd"):
                current_task = f"Running: {info['subtool_cmd']}"
            else:
                current_task = c_entry.get("latest_task") or conv_title or "Claude Code ready at prompt"
        else:
            current_task = infer_current_task(plain_text, info, status, label=label_val)

        ticket_match = None
        if raw_screen or t_entry or c_entry:
            for m in TICKET_RE.finditer("\n".join(non_empty_tail(plain_text, 30))):
                ticket_match = m.group(1)

        adopt_cmd = ""
        if info["agent_kind"] == "agy":
            adopt_cmd = f"agy --conversation {conv_id}" if conv_id else "agy --continue"
        elif info["agent_kind"] == "claude":
            adopt_cmd = f"claude --resume {conv_id}" if conv_id else "claude --continue"

        if can_script and host_app == "iTerm2":
            backend = "iterm2"
        elif can_script:
            backend = "terminal_app"
        elif ghostty_id:
            backend = "ghostty"
        else:
            backend = "tty"

        can_send = backend in ("ghostty", "iterm2", "terminal_app")
        can_keys = backend in ("ghostty", "iterm2", "terminal_app")

        results.append({
            "id": sid,
            "target": sid,
            "backend": backend,
            "can_send": can_send,
            "can_keys": can_keys,
            "ghostty_id": ghostty_id,
            "host_app": host_app,
            "tty": dev_tty,
            "tty_short": tty,
            "conversation_id": conv_id,
            "conversation_title": conv_title,
            "folder_name": folder_name,
            "dev_server": info.get("dev_server"),
            "_lineage_pids": info.get("lineage_pids") or [],
            "adopt_cmd": adopt_cmd,
            "session": terminal_name,
            "terminal_name": terminal_name,
            "current_task": current_task,
            "window": tty.replace("ttys", ""),
            "window_name": host_app,
            "pane": "ext",
            "cmd": info["agent_cmd"],
            "agent_cmd": info["agent_cmd"],
            "agent_kind": info["agent_kind"],
            "agent_meta": info["agent_meta"] or {},
            "subtool": effective_subtool,
            "cwd": cwd,
            "git": git_info,
            "status": status,
            "choices": choices,
            "pending_action": pending_action,
            "dead_status": "",
            "label": label_val,
            "pinned": sid in PINNED,
            "ticket": ticket_match if ticket_match and ticket_match.lower() != "none" else None,
            "error_hint": bool(t_entry and t_entry["tail"][-1].get("status") == "ERROR"),
            "progress": parse_progress(plain_text) if raw_screen else None,
            "preview": non_empty_tail(plain_text, 2) if raw_screen else [],
            "output_hash": digest,
            "last_change": tr["last_change"],
            "last_change_exact": tr.get("last_change_exact", False),
            "turn_since": turn_since,
            "agent_since": tr.get("agent_since"),
            "agent_since_exact": tr.get("agent_since_exact", False),
            "agent_ended": None,
            "created": int(now),
            "width": 120,
            "height": 40,
        })

    return results, seen_convs


def discover_agy_brain_sessions(already_tracked_convs, now):
    if not AGY_BRAIN_DIR.is_dir():
        return []

    summaries = get_agy_summaries(now)
    _, active_convs = get_agy_presence(now)

    candidates = []
    try:
        for child in AGY_BRAIN_DIR.iterdir():
            if not child.is_dir() or child.name.startswith("."):
                continue
            conv_id = child.name
            if conv_id in already_tracked_convs:
                continue
            sid = f"agy:{conv_id}"
            if sid in DISMISSED:
                continue
            # When presence tracking is available, only list conversations that are actively open
            # (e.g. inside Antigravity IDE) or currently running, skipping closed historical sessions.
            s_row = summaries.get(conv_id) or {}
            is_running = "RUNNING" in s_row.get("status", "") or s_row.get("not_fully_idle")
            if active_convs is not None and (conv_id not in active_convs) and not is_running:
                continue
            tfile = child / ".system_generated" / "logs" / "transcript.jsonl"
            if not tfile.is_file():
                continue
            st = tfile.stat()
            age = now - st.st_mtime
            if age <= 43200:
                candidates.append((st.st_mtime, conv_id))
    except OSError:
        return []

    candidates.sort(reverse=True)
    out = []

    for mtime, conv_id in candidates[:6]:
        sid = f"agy:{conv_id}"
        t_entry = _read_agy_transcript_steps(conv_id)
        if not t_entry:
            continue

        tail_steps = t_entry["tail"]
        all_sample = t_entry["head"] + tail_steps
        cwd = _extract_cwd_from_steps(all_sample)
        summary_row = summaries.get(conv_id)
        conv_title = (summary_row or {}).get("title", "")

        status, subtool = _classify_agy_from_metadata(summary_row, t_entry, {"subtool": None}, now)
        pending_action = extract_agy_pending_action(summary_row, t_entry) if status == "needs_input" else None
        choices = pending_action["choices"] if pending_action else []

        ansi_text = _render_agy_transcript(conv_id, tail_steps, cwd, title=conv_title, pending_action=pending_action)
        plain_text = strip_ansi(ansi_text)
        digest = hashlib.sha1(ansi_text.encode("utf-8", "replace")).hexdigest()
        OUTPUT_CACHE[sid] = {"ansi": ansi_text, "plain": plain_text, "hash": digest, "ts": now}

        ticket_match = None
        for m in TICKET_RE.finditer("\n".join(non_empty_tail(plain_text, 30))):
            ticket_match = m.group(1)

        folder_name = os.path.basename(cwd.rstrip("/")) or "agy"
        sess_name = conv_title or f"{folder_name} ({conv_id[:6]})"
        label_val = LABELS.get(sid, "")
        if pending_action and not label_val:
            current_task = pending_action["title"]
        else:
            current_task = _extract_agy_task(tail_steps, label=label_val, summary_title=conv_title)
        git_info = get_git_info(cwd, now)

        summary_mod_ts = (summary_row or {}).get("last_modified_ts")
        summary_input_ts = (summary_row or {}).get("last_user_input_ts")
        eff_mtime = max([ts for ts in (mtime, summary_mod_ts) if ts], default=mtime)

        out.append({
            "id": sid,
            "target": sid,
            "backend": "agy_live",
            "can_send": False,
            "can_keys": False,
            "host_app": "Antigravity",
            "conversation_id": conv_id,
            "conversation_title": conv_title,
            "folder_name": folder_name,
            "dev_server": None,
            "adopt_cmd": f"agy --conversation {conv_id}",
            "session": sess_name,
            "terminal_name": sess_name,
            "current_task": current_task,
            "window": "live",
            "window_name": "transcript",
            "pane": conv_id[:4],
            "cmd": "agy",
            "agent_cmd": "agy",
            "agent_kind": "agy",
            "agent_meta": {"kind": "agy", "conversation": conv_id},
            "subtool": subtool,
            "cwd": cwd,
            "git": git_info,
            "status": status,
            "choices": choices,
            "pending_action": pending_action,
            "dead_status": "",
            "label": label_val,
            "pinned": sid in PINNED,
            "ticket": ticket_match if ticket_match and ticket_match.lower() != "none" else None,
            "error_hint": tail_steps[-1].get("status") == "ERROR",
            "progress": None,
            "preview": non_empty_tail(plain_text, 2),
            "output_hash": digest,
            "last_change": eff_mtime,
            "last_change_exact": True,
            "turn_since": summary_input_ts if status == "working" else None,
            "agent_since": eff_mtime,
            "agent_since_exact": False,
            "agent_ended": None,
            "created": int(mtime),
            "width": 120,
            "height": 40,
        })

    return out


# ---------------------------------------------------------------------------
# Git branch & working-tree helper
# ---------------------------------------------------------------------------

def get_git_info(cwd, now):
    if not cwd or not os.path.isdir(cwd):
        return None
    cached = GIT_CACHE.get(cwd)
    if cached and (now - cached["ts"] < 5.0):
        return cached["data"]

    env = dict(os.environ, GIT_OPTIONAL_LOCKS="0")
    data = None
    try:
        r = subprocess.run(
            ["git", "-C", cwd, "status", "--porcelain", "-b", "--untracked-files=no"],
            capture_output=True,
            text=True,
            timeout=1.2,
            env=env,
        )
        if r.returncode == 0 and r.stdout:
            lines = r.stdout.splitlines()
            head = lines[0] if lines else ""
            branch = ""
            if head.startswith("## "):
                raw_b = head[3:].split("...")[0].strip()
                if "HEAD (no branch)" in raw_b or "No commits yet" in raw_b:
                    branch = "HEAD"
                else:
                    branch = raw_b
            dirty = sum(1 for l in lines[1:] if l.strip())
            if branch:
                data = {"branch": branch, "dirty": dirty}
    except (OSError, subprocess.SubprocessError):
        data = None

    GIT_CACHE[cwd] = {"data": data, "ts": now}
    return data


# ---------------------------------------------------------------------------
# Live Local Browser Port Scanner & Dev Server Manager
# ---------------------------------------------------------------------------

IGNORED_LISTEN_COMMS = {
    "controlcenter", "rapportd", "sharingd", "airplayxpchelper",
    "tmux", "sshd", "drsprinto", "figma_agent", "figmaagent", "figmaagen",
    "code", "cursor", "antigravi", "antigravity", "esbuild", "watchman", "tsserver",
    "postgres", "mysqld", "redis-server", "redis-ser", "mongod", "docker", "com.docke",
    "raycast", "slack", "discord", "spotify", "linear",
}
NON_HTTP_DB_PORTS = {3306, 5432, 6379, 27017}
AIRPLAY_PORTS = {5000, 7000}
WEB_RUNTIME_COMMS = {
    "node", "vite", "next-server", "python", "python3", "ruby",
    "bun", "deno", "go", "uvicorn", "gunicorn", "flask", "php", "java",
}


def normalize_browser_url(raw):
    val = str(raw or "").strip()
    if not val:
        return ""
    if val.startswith(":"):
        val = "http://localhost" + val
    elif re.match(r"^\d{2,5}(?:/.*)?$", val):
        val = "http://localhost:" + val
    elif re.match(r"^(?:localhost|127\.0\.0\.1|\[::1\])(?::\d+)?(?:/.*)?$", val, re.I):
        val = "http://" + val
    parsed = urlparse(val)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return ""
    return val[:500]


def detect_dev_command(cwd, now=None):
    if not cwd or not os.path.isdir(cwd):
        return None
    ts_now = now if now is not None else time.time()
    cached = DEV_CMD_CACHE.get(cwd)
    if cached and (ts_now - cached["ts"] < 15.0):
        return cached["data"]

    data = None
    pkg_file = Path(cwd) / "package.json"
    if pkg_file.is_file():
        try:
            pkg = json.loads(pkg_file.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts") if isinstance(pkg, dict) else None
            if isinstance(scripts, dict):
                script_name = None
                for cand in ("dev", "start", "serve"):
                    if isinstance(scripts.get(cand), str) and scripts[cand].strip():
                        script_name = cand
                        break
                if script_name:
                    pm = None
                    if (Path(cwd) / "yarn.lock").is_file() and shutil.which("yarn"):
                        pm = "yarn"
                    elif (Path(cwd) / "pnpm-lock.yaml").is_file() and shutil.which("pnpm"):
                        pm = "pnpm"
                    elif ((Path(cwd) / "bun.lockb").is_file() or (Path(cwd) / "bun.lock").is_file()) and shutil.which("bun"):
                        pm = "bun"
                    elif shutil.which("npm"):
                        pm = "npm"
                    elif shutil.which("yarn"):
                        pm = "yarn"
                    if pm:
                        data = {
                            "pm": pm,
                            "script": script_name,
                            "script_body": scripts[script_name],
                            "display": f"{pm} {script_name}" if pm == "yarn" else f"{pm} run {script_name}",
                        }
        except (OSError, ValueError):
            data = None

    DEV_CMD_CACHE[cwd] = {"ts": ts_now, "data": data}
    return data


def _port_sort_key(p):
    return (0 if 3000 <= p <= 9999 else 1, p)


def scan_listening_ports(proc_snapshot, now, force=False):
    if not force and (now - PORT_CACHE["ts"] < 2.5):
        return PORT_CACHE["pid_ports"], PORT_CACHE["all_ports"]

    procs = proc_snapshot[0] if proc_snapshot else {}
    try:
        r = subprocess.run(
            ["lsof", "-nP", "-iTCP", "-sTCP:LISTEN", "-Fpcfn"],
            capture_output=True,
            text=True,
            timeout=1.5,
        )
    except (OSError, subprocess.SubprocessError):
        return PORT_CACHE["pid_ports"], PORT_CACHE["all_ports"]

    if r.returncode != 0 and not r.stdout:
        return PORT_CACHE["pid_ports"], PORT_CACHE["all_ports"]

    raw_pid_ports = {}
    lsof_comms = {}
    curr_pid = None
    for line in r.stdout.splitlines():
        if line.startswith("p") and line[1:].isdigit():
            curr_pid = int(line[1:])
        elif line.startswith("c") and curr_pid is not None:
            lsof_comms[curr_pid] = line[1:].strip().replace("\\x20", " ")
        elif line.startswith("n") and curr_pid is not None:
            addr = line[1:].strip()
            _, sep, port_str = addr.rpartition(":")
            if not sep or not port_str.isdigit():
                continue
            port = int(port_str)
            if port < 1024 or port >= 49152 or port == SERVER_PORT or port in NON_HTTP_DB_PORTS:
                continue
            raw_pid_ports.setdefault(curr_pid, set()).add(port)

    filtered_pid_ports = {}
    pid_cwd_hint = {}
    need_cwd_pids = []

    for pid, port_set in raw_pid_ports.items():
        if pid == MY_PID:
            continue
        pr = procs.get(pid)
        comm = (pr["comm"] if pr else "") or lsof_comms.get(pid, "")
        args = pr["args"] if pr else ""
        comm_low = comm.lower().split()[0] if comm else ""
        hay = f"{comm} {args}"

        if (
            "agent_deck.py" in args
            or ".app/Contents/" in args
            or "/Library/Application Support/" in args
        ):
            continue
        if comm_low in IGNORED_LISTEN_COMMS or DAEMON_ARG_RE.search(args):
            continue
        if any(pat.search(hay) for _, pat in KNOWN_AGENTS) or CLAUDE_PROC_RE.search(hay):
            continue

        valid_ports = [
            p for p in port_set
            if ((p not in AIRPLAY_PORTS) or (comm_low in WEB_RUNTIME_COMMS))
            and (p < 12000 or comm_low in WEB_RUNTIME_COMMS)
        ]
        if not valid_ports:
            continue

        valid_ports.sort(key=_port_sort_key)
        filtered_pid_ports[pid] = valid_ports

        hint_cwd = None
        for m in ABS_PATH_TOKEN_RE.finditer(args):
            tok = m.group(1)
            if "/.gemini/" in tok or "/.nvm/" in tok or "/opt/homebrew/" in tok:
                continue
            root = _nearest_git_root(tok)
            if root:
                hint_cwd = root
                break
        if hint_cwd:
            pid_cwd_hint[pid] = hint_cwd
        else:
            need_cwd_pids.append(pid)

    if need_cwd_pids:
        lsof_cwds = batch_lsof_cwds(need_cwd_pids)
        for pid, raw_c in lsof_cwds.items():
            pid_cwd_hint[pid] = _nearest_git_root(raw_c) or raw_c

    by_port = {}
    for pid, ports in filtered_pid_ports.items():
        pr = procs.get(pid)
        comm = pr["comm"] if pr else "server"
        pcwd = pid_cwd_hint.get(pid, "")
        folder = os.path.basename(pcwd.rstrip("/")) if pcwd else ""
        for p in ports:
            if p not in by_port or (pcwd and not by_port[p]["cwd"]):
                by_port[p] = {
                    "port": p,
                    "url": f"http://localhost:{p}",
                    "pid": pid,
                    "cmd": comm,
                    "cwd": pcwd,
                    "folder": folder,
                }

    all_ports = [by_port[p] for p in sorted(by_port, key=_port_sort_key)]
    PORT_CACHE["ts"] = now
    PORT_CACHE["pid_ports"] = filtered_pid_ports
    PORT_CACHE["all_ports"] = all_ports
    return filtered_pid_ports, all_ports


def _prune_managed_servers():
    dead = [t for t, info in MANAGED_SERVERS.items() if info["proc"].poll() is not None]
    for t in dead:
        MANAGED_SERVERS.pop(t, None)


def attach_browser_metadata(sessions, proc_snapshot, now):
    _prune_managed_servers()
    pid_ports, all_ports = scan_listening_ports(proc_snapshot, now)
    listening_set = {item["port"] for item in all_ports}
    claimed_ports = set()
    assigned_port = {}

    # Pass 1: exact process-tree child PID match or Agent Deck managed dev server
    for s in sessions:
        sid = s["id"]
        target = s["target"]
        port = None
        for l_pid in s.get("_lineage_pids") or []:
            if l_pid in pid_ports:
                port = pid_ports[l_pid][0]
                break
        if port is None and target in MANAGED_SERVERS:
            port = MANAGED_SERVERS[target]["port"]
        if port is None and s.get("dev_server"):
            m = re.search(r":(\d{2,5})\b", str(s["dev_server"]))
            if m and int(m.group(1)) in listening_set:
                port = int(m.group(1))
        if port is not None:
            assigned_port[sid] = port
            claimed_ports.add(port)

    # Pass 2: unclaimed local port running in the exact same git worktree
    for s in sessions:
        sid = s["id"]
        if sid in assigned_port:
            continue
        scwd = s.get("cwd") or ""
        if not scwd:
            continue
        for item in all_ports:
            if item["port"] not in claimed_ports and item["cwd"] and item["cwd"] == scwd:
                assigned_port[sid] = item["port"]
                claimed_ports.add(item["port"])
                break

    for s in sessions:
        s.pop("_lineage_pids", None)
        target = s["target"]
        port = assigned_port.get(s["id"])
        auto_url = f"http://localhost:{port}" if port else ""
        custom_url = BROWSER_URLS.get(target, "")
        browser_url = custom_url or auto_url

        if port:
            s["dev_server"] = f"dev :{port}"
        s["dev_port"] = port
        s["auto_url"] = auto_url
        s["custom_url"] = custom_url
        s["browser_url"] = browser_url
        s["managed_dev"] = target in MANAGED_SERVERS
        dev_cmd = detect_dev_command(s.get("cwd") or "", now)
        s["can_start_dev"] = bool(dev_cmd)
        s["dev_cmd_preview"] = dev_cmd["display"] if dev_cmd else ""

    return all_ports


# ---------------------------------------------------------------------------
# Status, prompt-option, and progress detection
# ---------------------------------------------------------------------------

def non_empty_tail(text, n):
    lines = [l for l in text.split("\n") if l.strip()]
    return lines[-n:]


def extract_prompt_choices(lines):
    recent = lines[-12:]
    menu = []
    seen_nums = set()
    for line in recent:
        m = MENU_OPTION_RE.match(line)
        if m:
            num, label = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
            if num not in seen_nums and len(label) <= 115:
                seen_nums.add(num)
                short_lbl = label if len(label) <= 42 else label[:41] + "…"
                low_lbl = label.lower()
                style = ""
                if num == "1" and low_lbl.startswith(("yes", "allow", "proceed", "approve")):
                    style = "primary"
                elif low_lbl.startswith(("no", "deny", "reject", "cancel")):
                    style = "danger"
                menu.append({
                    "type": "keys",
                    "keys": [num],
                    "label": f"{num}. {short_lbl}",
                    "tooltip": f"{num}. {label}",
                    "style": style,
                })
    if len(menu) >= 2:
        return menu[:5]

    joined = "\n".join(recent[-6:])
    if YN_RE.search(joined):
        return [
            {"type": "keys", "keys": ["y", "Enter"], "label": "Yes (y)"},
            {"type": "keys", "keys": ["n", "Enter"], "label": "No (n)"},
        ]
    if re.search(r"\ballow once\b", joined, re.I):
        return [
            {"type": "keys", "keys": ["1"], "label": "1. Allow once", "style": "primary"},
            {"type": "keys", "keys": ["2"], "label": "2. Always allow", "style": ""},
            {"type": "keys", "keys": ["Escape"], "label": "Deny (Esc)", "style": "danger"},
        ]
    return []


def extract_screen_pending_action(plain_text, choices=None):
    lines = non_empty_tail(plain_text, 14)
    if choices is None:
        choices = extract_prompt_choices(lines)
    if not choices:
        choices = [
            {"type": "keys", "keys": ["y", "Enter"], "label": "Yes (y)", "style": "primary"},
            {"type": "keys", "keys": ["n", "Enter"], "label": "No (n)", "style": ""},
            {"type": "keys", "keys": ["Enter"], "label": "Enter", "style": ""},
            {"type": "keys", "keys": ["Escape"], "label": "Esc", "style": "subtle"},
        ]

    title = "Waiting for your response"
    # Prefer a question/prompt line above numbered menu rows
    first_menu_idx = next((i for i, ln in enumerate(lines) if MENU_OPTION_RE.match(ln)), -1)
    if first_menu_idx > 0:
        for ln in reversed(lines[:first_menu_idx]):
            cleaned = re.sub(r"\s+", " ", ln).strip()
            if len(cleaned) >= 4:
                title = cleaned[:130]
                break
    else:
        for ln in reversed(lines[-10:]):
            if MENU_OPTION_RE.match(ln):
                continue
            if any(p.search(ln) for p in INPUT_RE):
                title = re.sub(r"\s+", " ", ln).strip()[:130]
                break

    return {
        "kind": "prompt",
        "title": title,
        "detail": "",
        "choices": choices,
    }


def parse_progress(text):
    recent = text.split("\n")[-150:]
    done = todo = 0
    for line in recent:
        if CHECK_DONE.match(line):
            done += 1
        elif CHECK_TODO.match(line):
            todo += 1
    if done + todo >= 2:
        return {"done": done, "total": done + todo, "source": "checklist"}
    for line in reversed(recent):
        m = STEP_RE.search(line)
        if m:
            a = int(m.group(1) or m.group(3))
            b = int(m.group(2) or m.group(4))
            if 0 < a <= b <= 500:
                return {"done": a, "total": b, "source": "steps"}
    return None


def classify(pane, plain_text, proc_info, tr, now):
    if pane["dead"]:
        return "exited", []

    lines14 = non_empty_tail(plain_text, 14)
    short_tail = "\n".join(lines14[-4:])
    since_change = now - tr["last_change"]
    agent_running = proc_info["agent_running"]

    if agent_running:
        last_input = max(
            (i for i, l in enumerate(lines14) if any(p.search(l) for p in INPUT_RE)),
            default=-1,
        )
        last_done = max(
            (i for i, l in enumerate(lines14) if any(p.search(l) for p in DONE_RE)),
            default=-1,
        )
        busy_text = any(p.search(short_tail) for p in BUSY_RE)
        has_subtool = bool(proc_info.get("subtool"))

        asking = last_input >= max(0, len(lines14) - 8) and last_input > last_done
        if since_change > 1.2 and asking and not busy_text:
            choices = extract_prompt_choices(lines14)
            return "needs_input", choices

        if since_change < WORKING_WINDOW or busy_text or has_subtool:
            return "working", []

        if last_done >= 0 or tr.get("worked_in_turn"):
            return "done", []

        return "idle", []

    if tr.get("had_agent"):
        return "done", []
    return "shell", []


def add_event(sess_obj, old, new, now):
    EVENTS.append({
        "t": now,
        "pane": sess_obj["id"],
        "target": sess_obj["target"],
        "session": sess_obj["session"],
        "from": old,
        "to": new,
    })
    del EVENTS[:-150]


def broadcast_sse(payload):
    msg = f"data: {json.dumps(payload)}\n\n".encode("utf-8")
    with SSE_LOCK:
        stale = []
        for q in SSE_CLIENTS:
            try:
                q.put_nowait(msg)
            except queue.Full:
                stale.append(q)
        for q in stale:
            SSE_CLIENTS.discard(q)


def refresh(force_external=False):
    global SEQ
    now = time.time()
    panes = list_panes()
    need_ext = force_external or (now - EXTERNAL_CACHE["ts"] >= EXTERNAL_SCAN_INTERVAL)
    proc_snapshot = scan_process_table(now) if (panes or need_ext) else None
    procs_dict = proc_snapshot[0] if proc_snapshot else {}

    sessions = []
    seen = set()
    tmux_convs = set()
    summaries = get_agy_summaries(now) if panes else {}
    pid_to_conv, _ = get_agy_presence(now) if panes else ({}, None)

    for p in panes:
        proc_info = inspect_pane_processes(p, proc_snapshot)

        seen.add(p["id"])
        ansi_text = capture_ansi(p["id"], 280)
        plain_text = strip_ansi(ansi_text)
        digest = hashlib.sha1(ansi_text.encode("utf-8", "replace")).hexdigest()

        OUTPUT_CACHE[p["id"]] = {
            "ansi": ansi_text,
            "plain": plain_text,
            "hash": digest,
            "ts": now,
        }

        tr = TRACK.get(p["id"])
        if tr is None:
            tr = {
                "hash": digest,
                "last_change": now - 60,
                "first_seen": now,
                "status": None,
                "had_agent": False,
                "agent_since": None,
                "agent_since_exact": False,
                "agent_ended": None,
                "work_started_at": None,
                "worked_in_turn": False,
            }
            TRACK[p["id"]] = tr
        elif tr["hash"] != digest:
            tr["hash"] = digest
            tr["last_change"] = now
            tr["last_change_exact"] = True

        agent_running = proc_info["agent_running"]
        conv = (proc_info.get("agent_meta") or {}).get("conversation")
        if not conv and proc_info.get("agent_kind") == "agy" and proc_info.get("focus_pid"):
            conv = pid_to_conv.get(proc_info["focus_pid"])
            if conv:
                proc_info["agent_meta"] = dict(proc_info.get("agent_meta") or {}, conversation=conv)
        if conv and proc_info.get("agent_kind") == "agy":
            tmux_convs.add(conv)

        summary_row = summaries.get(conv) if (conv and proc_info.get("agent_kind") == "agy") else None
        conv_title = (summary_row or {}).get("title", "")
        t_entry = _read_agy_transcript_steps(conv) if (conv and proc_info.get("agent_kind") == "agy") else None

        eff_cwd = p["cwd"]
        if t_entry:
            eff_cwd = _extract_cwd_from_steps(
                t_entry["tail"],
                fallback_cwd=p["cwd"],
                dev_cwd=proc_info.get("dev_cwd") or "",
            )
        elif proc_info.get("dev_cwd"):
            eff_cwd = proc_info["dev_cwd"]
        record_cwd(eff_cwd)

        proc_started = (
            procs_dict.get(proc_info.get("focus_pid"), {}).get("started_at")
            or (p["created"] if p.get("created") else None)
        )
        summary_mod_ts = (summary_row or {}).get("last_modified_ts")
        summary_input_ts = (summary_row or {}).get("last_user_input_ts")
        known_activity_ts = max(
            [ts for ts in (t_entry["mtime"] if t_entry else None, summary_mod_ts) if ts],
            default=None,
        )
        if known_activity_ts is not None:
            tr["last_change"] = max(tr["last_change"], known_activity_ts) if tr.get("last_change_exact") else known_activity_ts
            tr["last_change_exact"] = True

        if agent_running:
            if proc_started is not None:
                tr["agent_since"] = proc_started
                tr["agent_since_exact"] = True
            elif tr["agent_since"] is None:
                tr["agent_since"] = now
                tr["agent_since_exact"] = tr["status"] is not None
            tr["had_agent"] = True
            tr["agent_cmd"] = proc_info["agent_cmd"]
            tr["agent_kind"] = proc_info["agent_kind"]
            tr["agent_meta"] = proc_info["agent_meta"]
            tr["agent_ended"] = None
        elif tr.get("agent_since") is not None and tr.get("agent_ended") is None:
            tr["agent_ended"] = now

        status, choices = classify(p, plain_text, proc_info, tr, now)
        agy_action = (
            extract_agy_pending_action(summary_row, t_entry)
            if (proc_info.get("agent_kind") == "agy" and (summary_row or t_entry))
            else None
        )
        pending_action = None
        if agy_action and status != "working":
            status = "needs_input"
            pending_action = agy_action
            choices = agy_action["choices"]
        elif status == "needs_input":
            pending_action = extract_screen_pending_action(plain_text, choices)
            choices = pending_action["choices"]

        if status == "working":
            if tr["work_started_at"] is None:
                tr["work_started_at"] = now
            elif (now - tr["work_started_at"]) >= TURN_WORK_THRESHOLD:
                tr["worked_in_turn"] = True
        else:
            tr["work_started_at"] = None

        if tr["status"] is not None and tr["status"] != status:
            add_event(p, tr["status"], status, now)
        tr["status"] = status

        tail = non_empty_tail(plain_text, 3)
        errors = any(r.search("\n".join(non_empty_tail(plain_text, 8))) for r in ERROR_RE)
        ticket_match = None
        for m in TICKET_RE.finditer("\n".join(non_empty_tail(plain_text, 25))):
            ticket_match = m.group(1)

        git_info = get_git_info(eff_cwd, now)
        label_val = LABELS.get(p["target"], "")
        if pending_action and not label_val:
            current_task = pending_action["title"]
        elif t_entry and not label_val and not proc_info.get("subtool_cmd"):
            current_task = _extract_agy_task(t_entry["tail"], label="", summary_title=conv_title)
        else:
            current_task = infer_current_task(plain_text, proc_info, status, label=label_val)

        wname = p["window_name"]
        pane_title_clean = ""
        if proc_info.get("agent_kind") == "claude" and p.get("pane_title"):
            pane_title_clean, _, _ = _clean_claude_tab_title(p["pane_title"])
        effective_title = conv_title or pane_title_clean
        base_tmux_name = (
            f"{p['session']} / {wname}"
            if wname and wname not in SHELLS and wname != p["session"] and wname != (tr.get("agent_cmd") or "")
            else p["session"]
        )
        term_name = f"{effective_title} · {base_tmux_name}" if effective_title else base_tmux_name
        folder_name = os.path.basename(eff_cwd.rstrip("/")) or p["session"]

        sessions.append({
            "id": p["id"],
            "target": p["target"],
            "backend": "tmux",
            "can_send": True,
            "can_keys": True,
            "host_app": "tmux",
            "conversation_id": conv,
            "conversation_title": effective_title,
            "folder_name": folder_name,
            "dev_server": proc_info.get("dev_server"),
            "_lineage_pids": proc_info.get("lineage_pids") or [],
            "session": p["session"],
            "terminal_name": term_name,
            "current_task": current_task,
            "window": p["window"],
            "window_name": p["window_name"],
            "pane": p["pane"],
            "cmd": p["cmd"],
            "agent_cmd": tr.get("agent_cmd") or p["cmd"],
            "agent_kind": tr.get("agent_kind") or proc_info["agent_kind"],
            "agent_meta": tr.get("agent_meta") or proc_info["agent_meta"] or {},
            "subtool": proc_info.get("subtool"),
            "cwd": eff_cwd,
            "git": git_info,
            "status": status,
            "choices": choices,
            "pending_action": pending_action,
            "dead_status": p["dead_status"],
            "label": label_val,
            "pinned": p["target"] in PINNED,
            "ticket": ticket_match if ticket_match and ticket_match.lower() != "none" else None,
            "error_hint": errors,
            "progress": parse_progress(plain_text),
            "preview": tail,
            "output_hash": digest,
            "last_change": tr["last_change"],
            "last_change_exact": tr.get("last_change_exact", False),
            "turn_since": (summary_input_ts or tr["work_started_at"]) if status == "working" else None,
            "agent_since": tr.get("agent_since"),
            "agent_since_exact": tr.get("agent_since_exact", False),
            "agent_ended": tr.get("agent_ended"),
            "created": p["created"],
            "width": p["width"],
            "height": p["height"],
        })

    if need_ext:
        ext_ttys, ext_convs = discover_external_ttys(proc_snapshot, now)
        brain_sessions = discover_agy_brain_sessions(tmux_convs | ext_convs, now)
        EXTERNAL_CACHE["sessions"] = ext_ttys + brain_sessions
        EXTERNAL_CACHE["ts"] = now

    for ext in EXTERNAL_CACHE["sessions"]:
        if (ext.get("conversation_id") and ext.get("conversation_id") in tmux_convs) or ext["id"] in DISMISSED:
            continue
        ext_copy = dict(ext)
        # Keep manual label override synced without waiting for next external scan
        lbl = LABELS.get(ext_copy["target"], "")
        ext_copy["label"] = lbl
        ext_copy["pinned"] = ext_copy["target"] in PINNED
        if lbl:
            ext_copy["current_task"] = lbl
        seen.add(ext_copy["id"])
        sessions.append(ext_copy)

    local_ports = attach_browser_metadata(sessions, proc_snapshot, now)

    for gone in set(TRACK) - seen:
        TRACK.pop(gone, None)
        OUTPUT_CACHE.pop(gone, None)

    with LOCK:
        SEQ += 1
        STATE.update({
            "seq": SEQ,
            "sessions": sessions,
            "events": list(EVENTS[-60:]),
            "recent_cwds": list(RECENT_CWDS[:10]),
            "local_ports": local_ports,
            "error": None,
            "now": now,
        })
        snapshot = dict(STATE)

    broadcast_sse(snapshot)


def poll_loop(interval):
    while True:
        try:
            refresh()
        except Exception as e:
            with LOCK:
                STATE["error"] = f"Couldn't scan sessions: {e}"
                STATE["now"] = time.time()
        time.sleep(interval)


def get_session_by_id(sid):
    with LOCK:
        for s in STATE["sessions"]:
            if s["id"] == sid:
                return dict(s)
    return None


def trigger_fast_refresh(force_external=False):
    def _delayed():
        time.sleep(0.14)
        try:
            refresh(force_external=force_external)
        except Exception:
            pass
    threading.Thread(target=_delayed, daemon=True).start()


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def send_text_to_pane(pane, text, press_enter=True):
    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    if cleaned:
        if "\n" in cleaned:
            buf_name = f"deck-{secrets.token_hex(4)}"
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as tf:
                tf.write(cleaned)
                tmp_path = tf.name
            try:
                r1 = tmux("load-buffer", "-b", buf_name, tmp_path)
                if r1.returncode != 0:
                    return False, r1.stderr.strip() or "Failed to load tmux buffer."
                r2 = tmux("paste-buffer", "-p", "-d", "-b", buf_name, "-t", pane)
                if r2.returncode != 0:
                    return False, r2.stderr.strip() or "Failed to paste into session."
            finally:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
        else:
            r = tmux("send-keys", "-t", pane, "-l", "--", cleaned)
            if r.returncode != 0:
                return False, r.stderr.strip()
    if press_enter:
        time.sleep(0.08)
        r = tmux("send-keys", "-t", pane, "Enter")
        if r.returncode != 0:
            return False, r.stderr.strip()
    return True, ""


def reset_turn_tracking(sid):
    tr = TRACK.get(sid)
    if tr:
        tr["worked_in_turn"] = False
        tr["work_started_at"] = None


def _unique_tmux_name(base):
    clean = re.sub(r"[^A-Za-z0-9_-]+", "-", base).strip("-")[:28] or "session"
    candidate = clean
    idx = 2
    while tmux("has-session", "-t", f"={candidate}").returncode == 0:
        candidate = f"{clean}-{idx}"
        idx += 1
    return candidate


def do_adopt_into_tmux(sess):
    cwd = sess.get("cwd") or HOME
    if not os.path.isdir(cwd):
        cwd = HOME
    folder = os.path.basename(cwd.rstrip("/")) or "term"
    kind = sess.get("agent_kind")
    prefix = f"{kind}-{folder}" if kind in ("agy", "claude", "codex", "gemini") else folder
    name = _unique_tmux_name(prefix)
    cmd = sess.get("adopt_cmd") or ""

    r = tmux("new-session", "-d", "-s", name, "-c", cwd, "-x", "200", "-y", "52")
    if r.returncode != 0:
        return 500, {"ok": False, "error": r.stderr.strip() or "Failed to create tmux session."}

    r_info = tmux("display-message", "-p", "-t", f"{name}:", "#{pane_id}\t#{window_index}.#{pane_index}")
    pane_id, _, wp = r_info.stdout.strip().partition("\t")
    target = f"{name}:{wp}"

    if sess.get("label"):
        LABELS[target] = sess["label"]
        save_persistence()

    if cmd:
        time.sleep(0.18)
        send_text_to_pane(pane_id or f"{name}:", cmd, press_enter=True)

    try:
        refresh(force_external=True)
    except Exception:
        pass
    return 200, {"ok": True, "pane": pane_id, "session": name}


def do_open_terminal(sess):
    """
    Opens or focuses a native macOS terminal window for any session:
      - tmux: opens iTerm2 / Terminal.app running `tmux attach -t <session>`
      - external TTY (Terminal.app, iTerm2, Ghostty, Warp, VS Code, etc.): focuses that window/tab
      - agy_live: opens iTerm2 / Terminal.app in that session's workspace folder
    """
    backend = sess.get("backend", "tmux")
    if backend == "tmux":
        sess_name = sess.get("session", "")
        quoted = "'" + sess_name.replace("'", "'\\''") + "'"
        ok, err = macos_open_in_terminal_app(shell_cmd=f"tmux attach -t {quoted}")
        return (200, {"ok": True}) if ok else (400, {"ok": False, "error": err})

    if backend in ("ghostty", "iterm2", "terminal_app", "tty"):
        ok, err = macos_focus_tty(
            sess.get("host_app", ""),
            sess.get("tty", ""),
            ghostty_id=sess.get("ghostty_id", ""),
        )
        if ok:
            return 200, {"ok": True}
        # Fallback: open a Terminal window in the same folder
        ok2, err2 = macos_open_in_terminal_app(cwd=sess.get("cwd") or HOME)
        return (200, {"ok": True}) if ok2 else (400, {"ok": False, "error": err or err2})

    ok, err = macos_open_in_terminal_app(cwd=sess.get("cwd") or HOME)
    return (200, {"ok": True}) if ok else (400, {"ok": False, "error": err})


def is_local_port_open(port):
    for fam, host in ((socket.AF_INET, "127.0.0.1"), (socket.AF_INET6, "::1")):
        try:
            with socket.socket(fam, socket.SOCK_STREAM) as s:
                s.settimeout(0.15)
                if s.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            pass
    return False


def find_free_dev_port(start_port=3001):
    busy = {item["port"] for item in PORT_CACHE.get("all_ports", [])} | {SERVER_PORT}
    busy |= {info["port"] for info in MANAGED_SERVERS.values()}
    for candidate in range(start_port, start_port + 80):
        if candidate in busy or candidate in AIRPLAY_PORTS:
            continue
        if not is_local_port_open(candidate):
            return candidate
    return start_port + 81


def _build_dev_server_argv(dev_info, port):
    pm = dev_info["pm"]
    script = dev_info["script"]
    body_low = dev_info["script_body"].lower()
    is_vite = "vite" in body_low
    is_next = "next" in body_low
    is_astro = "astro" in body_low

    if is_vite or is_astro:
        extra = ["--port", str(port), "--strictPort", "--open", "false"] if is_vite else ["--port", str(port)]
    elif is_next:
        extra = ["-p", str(port)]
    else:
        extra = []

    if pm == "npm":
        return ["npm", "run", script] + (["--"] + extra if extra else [])
    if pm == "yarn":
        return ["yarn", "run", script] + extra
    if pm == "pnpm":
        return ["pnpm", "run", script] + extra
    if pm == "bun":
        return ["bun", "run", script] + (["--"] + extra if extra else [])
    return [pm, "run", script]


def do_start_dev_server(sess):
    target = sess["target"]
    _prune_managed_servers()
    if target in MANAGED_SERVERS:
        existing_port = MANAGED_SERVERS[target]["port"]
        return 200, {"ok": True, "port": existing_port, "url": f"http://localhost:{existing_port}"}

    cwd = sess.get("cwd") or ""
    dev_info = detect_dev_command(cwd)
    if not dev_info:
        return 400, {"ok": False, "error": "No package.json dev/start script found in this worktree."}

    port = find_free_dev_port(3001)
    argv = _build_dev_server_argv(dev_info, port)
    env = dict(os.environ, PORT=str(port), BROWSER="none", CI="false")

    try:
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as e:
        return 500, {"ok": False, "error": f"Failed to start dev server: {e}"}

    MANAGED_SERVERS[target] = {
        "proc": proc,
        "pid": proc.pid,
        "port": port,
        "cwd": cwd,
        "started_at": time.time(),
    }

    deadline = time.time() + 5.0
    while time.time() < deadline:
        if proc.poll() is not None:
            MANAGED_SERVERS.pop(target, None)
            return 500, {"ok": False, "error": f"{dev_info['display']} exited early (code {proc.returncode})."}
        if is_local_port_open(port):
            break
        time.sleep(0.15)

    PORT_CACHE["ts"] = 0.0
    try:
        refresh(force_external=True)
    except Exception:
        pass
    return 200, {"ok": True, "port": port, "url": f"http://localhost:{port}"}


def do_stop_dev_server(sess):
    target = sess["target"]
    entry = MANAGED_SERVERS.pop(target, None)
    if not entry:
        return 400, {"ok": False, "error": "This server was not started by Agent Deck."}
    proc = entry["proc"]
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            try:
                proc.terminate()
            except OSError:
                pass
        for _ in range(8):
            if proc.poll() is not None:
                break
            time.sleep(0.08)
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except OSError:
                pass

    PORT_CACHE["ts"] = 0.0
    try:
        refresh(force_external=True)
    except Exception:
        pass
    return 200, {"ok": True}


def do_action(body):
    # Support opening a blank workspace terminal without a specific pane
    if body.get("action") == "open_new_terminal":
        cwd = os.path.expanduser(str(body.get("cwd") or HOME))
        ok, err = macos_open_in_terminal_app(cwd=cwd if os.path.isdir(cwd) else HOME)
        return (200, {"ok": True}) if ok else (400, {"ok": False, "error": err})

    sid = str(body.get("pane", ""))
    sess = get_session_by_id(sid)
    if not SESSION_ID_OK.match(sid) or not sess:
        return 400, {"ok": False, "error": "That session is no longer active."}

    action = body.get("action")
    backend = sess.get("backend", "tmux")

    if action == "open_terminal" or action == "focus":
        return do_open_terminal(sess)

    if action == "start_dev_server":
        return do_start_dev_server(sess)

    if action == "stop_dev_server":
        return do_stop_dev_server(sess)

    if action == "adopt":
        return do_adopt_into_tmux(sess)

    if action == "dismiss":
        if backend != "tmux":
            DISMISSED.add(sid)
            save_persistence()
            trigger_fast_refresh(force_external=True)
            return 200, {"ok": True}
        return 400, {"ok": False, "error": "Use Close for tmux sessions."}

    if backend != "tmux":
        if action == "send":
            text = str(body.get("text", ""))
            if len(text) > 12000:
                return 400, {"ok": False, "error": "Message is too long (12,000 characters max)."}
            enter = bool(body.get("enter", True))
            if backend == "ghostty" and sess.get("ghostty_id"):
                reset_turn_tracking(sid)
                ok, err = macos_send_ghostty_text(sess["ghostty_id"], text, press_enter=enter)
                if ok:
                    trigger_fast_refresh(force_external=True)
                    return 200, {"ok": True}
                return 400, {"ok": False, "error": err}
            if backend in ("iterm2", "terminal_app"):
                reset_turn_tracking(sid)
                ok, err = macos_send_tty_text(sess["host_app"], sess["tty"], text, press_enter=enter)
                if ok:
                    trigger_fast_refresh(force_external=True)
                    return 200, {"ok": True}
                return 400, {"ok": False, "error": err}
            return 400, {
                "ok": False,
                "error": "Click 'Resume in tmux' first to send prompts & keys to this session.",
            }
        if action == "keys":
            keys = body.get("keys") or []
            if (
                not isinstance(keys, list)
                or not keys
                or len(keys) > 10
                or not all(isinstance(k, str) and KEY_OK.match(k) for k in keys)
            ):
                return 400, {"ok": False, "error": "Unsupported key sequence."}
            if backend == "ghostty" and sess.get("ghostty_id"):
                reset_turn_tracking(sid)
                ok, err = macos_send_ghostty_keys(sess["ghostty_id"], keys)
                if ok:
                    trigger_fast_refresh(force_external=True)
                    return 200, {"ok": True}
                return 400, {"ok": False, "error": err}
            if backend == "iterm2":
                key_map = {
                    "Enter": "\r",
                    "Escape": "\x1b",
                    "C-c": "\x03",
                    "C-d": "\x04",
                    "C-l": "\x0c",
                    "C-u": "\x15",
                    "Tab": "\t",
                    "BTab": "\x1b[Z",
                    "Space": " ",
                    "BSpace": "\x7f",
                    "Up": "\x1b[A",
                    "Down": "\x1b[B",
                    "Right": "\x1b[C",
                    "Left": "\x1b[D",
                }
                seq_parts = []
                for k in keys:
                    if k.startswith("/") and len(k) > 1:
                        seq_parts.append(k + "\r")
                    elif k in key_map:
                        seq_parts.append(key_map[k])
                    elif len(k) == 1:
                        seq_parts.append(k)
                seq = "".join(seq_parts)
                if seq:
                    reset_turn_tracking(sid)
                    ok, err = macos_send_tty_text("iTerm2", sess["tty"], seq, press_enter=False)
                    if ok:
                        trigger_fast_refresh(force_external=True)
                        return 200, {"ok": True}
                    return 400, {"ok": False, "error": err}
            if backend == "terminal_app":
                # Terminal.app `do script` sends line input + Enter
                printable = [k for k in keys if (len(k) == 1 and k.isalnum()) or (k.startswith("/") and len(k) > 1)]
                if printable or keys == ["Enter"]:
                    reset_turn_tracking(sid)
                    ok, err = macos_send_tty_text("Terminal.app", sess["tty"], "".join(printable), press_enter=True)
                    if ok:
                        trigger_fast_refresh(force_external=True)
                        return 200, {"ok": True}
                    return 400, {"ok": False, "error": err}
        return 400, {
            "ok": False,
            "error": "Click 'Resume in tmux' above for full interactive keystroke control.",
        }

    if action == "send":
        text = str(body.get("text", ""))
        if len(text) > 12000:
            return 400, {"ok": False, "error": "Message is too long (12,000 characters max)."}
        enter = bool(body.get("enter", True))
        reset_turn_tracking(sid)
        ok, err = send_text_to_pane(sid, text, press_enter=enter)
        if not ok:
            return 500, {"ok": False, "error": err}
        trigger_fast_refresh()
        return 200, {"ok": True}

    if action == "keys":
        keys = body.get("keys") or []
        if (
            not isinstance(keys, list)
            or not keys
            or len(keys) > 10
            or not all(isinstance(k, str) and KEY_OK.match(k) for k in keys)
        ):
            return 400, {"ok": False, "error": "Unsupported key sequence."}
        reset_turn_tracking(sid)
        for idx, k in enumerate(keys):
            if k.startswith("/") and len(k) > 1:
                ok, err = send_text_to_pane(sid, k, press_enter=True)
                if not ok:
                    return 500, {"ok": False, "error": err}
            else:
                if idx > 0:
                    time.sleep(0.05)
                r = tmux("send-keys", "-t", sid, k)
                if r.returncode != 0:
                    return 500, {"ok": False, "error": r.stderr.strip()}
        trigger_fast_refresh()
        return 200, {"ok": True}

    if action == "ack":
        reset_turn_tracking(sid)
        tr = TRACK.get(sid)
        if tr and tr.get("status") == "done":
            tr["status"] = "idle"
        trigger_fast_refresh()
        return 200, {"ok": True}

    if action == "respawn":
        r = tmux("respawn-pane", "-k", "-t", sid)
        if r.returncode != 0:
            return 500, {"ok": False, "error": r.stderr.strip() or "Couldn't restart pane."}
        trigger_fast_refresh()
        return 200, {"ok": True}

    if action == "kill":
        r = tmux("kill-pane", "-t", sid)
        if r.returncode != 0:
            return 500, {"ok": False, "error": r.stderr.strip()}
        trigger_fast_refresh()
        return 200, {"ok": True}

    return 400, {"ok": False, "error": "Unknown action."}


def do_new(body):
    name = str(body.get("name", "")).strip()
    raw_cwd = str(body.get("cwd", "") or "~").strip()
    cwd = os.path.expanduser(raw_cwd)
    command = str(body.get("command", "")).strip()
    prompt = str(body.get("prompt", "")).strip()
    label = str(body.get("label", "")).strip()[:120]

    if not SESSION_NAME_OK.match(name):
        return 400, {"ok": False, "error": "Use letters, numbers, - or _ for the session name (40 max)."}
    if not os.path.isdir(cwd):
        return 400, {"ok": False, "error": f"Folder not found: {cwd}"}
    if tmux("has-session", "-t", f"={name}").returncode == 0:
        return 400, {"ok": False, "error": f"A session named '{name}' already exists."}

    r = tmux("new-session", "-d", "-s", name, "-c", cwd, "-x", "200", "-y", "52")
    if r.returncode != 0:
        return 500, {"ok": False, "error": r.stderr.strip()}

    r_info = tmux("display-message", "-p", "-t", f"{name}:", "#{pane_id}\t#{window_index}.#{pane_index}")
    pane_id, _, wp = r_info.stdout.strip().partition("\t")
    target = f"{name}:{wp}"

    record_cwd(cwd)
    if label:
        LABELS[target] = label
    save_persistence()

    if command:
        time.sleep(0.18)
        send_text_to_pane(pane_id or f"{name}:", command, press_enter=True)
        if prompt:
            def _send_initial_prompt():
                time.sleep(1.6)
                send_text_to_pane(pane_id or f"{name}:", prompt, press_enter=True)
                trigger_fast_refresh()
            threading.Thread(target=_send_initial_prompt, daemon=True).start()

    try:
        refresh()
    except Exception:
        pass
    return 200, {"ok": True, "pane": pane_id}


def do_label(body):
    if body.get("restore_dismissed"):
        DISMISSED.clear()
        save_persistence()
        trigger_fast_refresh(force_external=True)
        return 200, {"ok": True}

    target = str(body.get("target", ""))[:200]
    if not target:
        return 400, {"ok": False, "error": "Missing session target."}

    if "label" in body:
        label = str(body.get("label", "")).strip()[:120]
        if label:
            LABELS[target] = label
        else:
            LABELS.pop(target, None)

    if "pinned" in body:
        if body.get("pinned"):
            PINNED.add(target)
        else:
            PINNED.discard(target)

    if "browser_url" in body:
        raw_burl = str(body.get("browser_url") or "").strip()
        if raw_burl:
            norm_burl = normalize_browser_url(raw_burl)
            if not norm_burl:
                return 400, {"ok": False, "error": "Enter a valid http:// or https:// URL or :port."}
            BROWSER_URLS[target] = norm_burl
        else:
            BROWSER_URLS.pop(target, None)

    save_persistence()
    snapshot = None
    with LOCK:
        for s in STATE["sessions"]:
            if s["target"] == target:
                lbl = LABELS.get(target, "")
                s["label"] = lbl
                if lbl:
                    s["current_task"] = lbl
                s["pinned"] = target in PINNED
                curl = BROWSER_URLS.get(target, "")
                s["custom_url"] = curl
                s["browser_url"] = curl or s.get("auto_url", "")
        snapshot = dict(STATE)
    if snapshot:
        broadcast_sse(snapshot)
    return 200, {"ok": True, "browser_url": BROWSER_URLS.get(target, "")}


# ---------------------------------------------------------------------------
# HTTP Server
# ---------------------------------------------------------------------------

LOCKED_PAGE = """<!doctype html><html lang="en"><meta charset="utf-8"><title>Agent Deck</title>
<body style="font:16px system-ui,sans-serif;max-width:36rem;margin:15vh auto;padding:0 1.25rem;line-height:1.55;color:#17202c;background:#eef1f5">
<h1 style="font-size:1.35rem;margin-bottom:.5rem">Open the private link from your terminal</h1>
<p style="color:#4a5565">Agent Deck requires the one-time token URL printed at startup (ending in <code>?token=...</code>) so other tabs or websites cannot send keystrokes to your sessions.</p>
</body></html>"""

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
}


class Handler(BaseHTTPRequestHandler):
    server_version = "AgentDeck/2.2"
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def _host_ok(self):
        host = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]")
        return host in ("127.0.0.1", "localhost", "::1")

    def _cookie_token(self):
        raw = self.headers.get("Cookie", "")
        for chunk in raw.split(";"):
            k, _, v = chunk.strip().partition("=")
            if k == "deck_token":
                return v
        return ""

    def _authed(self, qs=None):
        hdr = self.headers.get("X-Deck-Token", "")
        if hdr and secrets.compare_digest(hdr, TOKEN):
            return True
        ck = self._cookie_token()
        if ck and secrets.compare_digest(ck, TOKEN):
            return True
        if qs and secrets.compare_digest(qs.get("token", [""])[0], TOKEN):
            return True
        return False

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra_headers=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj))

    def _serve_static(self, rel_name, inject_token=False, set_cookie=False):
        target = (STATIC_DIR / rel_name).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            return self._send(404, "Not found", "text/plain; charset=utf-8")
        ctype = MIME_TYPES.get(target.suffix, "application/octet-stream")
        raw = target.read_bytes()
        if inject_token:
            raw = raw.decode("utf-8").replace("__TOKEN__", TOKEN).encode("utf-8")
        headers = {}
        if set_cookie:
            headers["Set-Cookie"] = f"deck_token={TOKEN}; Path=/; HttpOnly; SameSite=Strict"
        return self._send(200, raw, ctype, extra_headers=headers)

    def do_GET(self):
        if not self._host_ok():
            return self._send(403, "Forbidden", "text/plain; charset=utf-8")
        url = urlparse(self.path)
        qs = parse_qs(url.query)

        if url.path == "/":
            q_tok = qs.get("token", [""])[0]
            has_valid_q = bool(q_tok) and secrets.compare_digest(q_tok, TOKEN)
            if not has_valid_q and not self._authed():
                return self._send(403, LOCKED_PAGE, "text/html; charset=utf-8")
            host_only = self.headers.get("Host", "").rsplit(":", 1)[0].strip("[]")
            if host_only == "127.0.0.1" and IPV6_READY:
                loc = f"http://localhost:{SERVER_PORT}/?token={TOKEN}"
                return self._send(302, b"", "text/plain; charset=utf-8", extra_headers={"Location": loc})
            return self._serve_static("index.html", inject_token=True, set_cookie=True)

        if url.path in ("/styles.css", "/app.js"):
            if not self._authed(qs):
                return self._send(403, "Forbidden", "text/plain; charset=utf-8")
            return self._serve_static(url.path.lstrip("/"))

        if not self._authed(qs):
            return self._json(403, {"ok": False, "error": "Missing or invalid token."})

        if url.path == "/api/state":
            with LOCK:
                return self._json(200, STATE)

        if url.path == "/api/output":
            sid = qs.get("pane", [""])[0]
            sess = get_session_by_id(sid)
            if not SESSION_ID_OK.match(sid) or not sess:
                return self._json(404, {"ok": False, "error": "Unknown session."})
            try:
                lines = max(80, min(3000, int(qs.get("lines", ["800"])[0])))
            except ValueError:
                lines = 800
            client_hash = qs.get("hash", [""])[0]

            if sess.get("backend") != "tmux" or (lines <= 280 and sid in OUTPUT_CACHE):
                cached = OUTPUT_CACHE.get(sid, {"ansi": "", "plain": "", "hash": ""})
                ansi_text = cached["ansi"]
                plain_text = cached["plain"]
                digest = cached["hash"]
            else:
                ansi_text = capture_ansi(sid, lines)
                plain_text = strip_ansi(ansi_text)
                digest = hashlib.sha1(ansi_text.encode("utf-8", "replace")).hexdigest()

            if client_hash and client_hash == digest:
                return self._json(200, {"ok": True, "unchanged": True, "hash": digest})
            return self._json(200, {
                "ok": True,
                "ansi": ansi_text,
                "text": plain_text,
                "hash": digest,
            })

        if url.path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()

            q = queue.Queue(maxsize=8)
            with SSE_LOCK:
                SSE_CLIENTS.add(q)
            try:
                with LOCK:
                    initial = f"data: {json.dumps(STATE)}\n\n".encode("utf-8")
                self.wfile.write(initial)
                self.wfile.flush()
                while True:
                    try:
                        chunk = q.get(timeout=15)
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            finally:
                with SSE_LOCK:
                    SSE_CLIENTS.discard(q)
            return

        return self._json(404, {"ok": False, "error": "Not found."})

    def do_POST(self):
        if not self._host_ok() or not self._authed():
            return self._json(403, {"ok": False, "error": "Forbidden."})
        try:
            length = min(int(self.headers.get("Content-Length", "0")), 128_000)
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self._json(400, {"ok": False, "error": "Malformed JSON body."})

        path = urlparse(self.path).path
        try:
            if path == "/api/action":
                code, out = do_action(body)
            elif path == "/api/new":
                code, out = do_new(body)
            elif path == "/api/label":
                code, out = do_label(body)
            else:
                code, out = 404, {"ok": False, "error": "Endpoint not found."}
        except subprocess.TimeoutExpired:
            code, out = 504, {"ok": False, "error": "Terminal command timed out."}
        return self._json(code, out)


IPV6_READY = False


class ReusableThreadingHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class ReusableIPv6HTTPServer(ReusableThreadingHTTPServer):
    address_family = socket.AF_INET6


def find_free_port(preferred):
    if not is_local_port_open(preferred):
        return preferred
    for candidate in range(preferred + 1, preferred + 25):
        if not is_local_port_open(candidate):
            return candidate
    return preferred


def _shutdown_managed_servers():
    for target in list(MANAGED_SERVERS):
        entry = MANAGED_SERVERS.pop(target, None)
        if not entry:
            continue
        proc = entry["proc"]
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except OSError:
                try:
                    proc.terminate()
                except OSError:
                    pass


def main():
    global SERVER_PORT, IPV6_READY
    ap = argparse.ArgumentParser(
        description="Live dashboard for Antigravity (agy) & terminals across tmux and macOS."
    )
    ap.add_argument("--port", type=int, default=7878, help="port to serve on (default 7878)")
    ap.add_argument("--auto-port", action="store_true", help="pick next free port if busy")
    ap.add_argument("--interval", type=float, default=1.0, help="seconds between scans (default 1.0)")
    ap.add_argument("--no-browser", action="store_true", help="do not launch browser automatically")
    args = ap.parse_args()

    if not shutil.which("tmux"):
        print("  Note: tmux is not installed — external terminal & live browser views work out of the box.")
        print("        Install tmux (`brew install tmux`) if you also want managed tmux sessions.")

    if not (STATIC_DIR / "index.html").is_file():
        print(f"Static UI files missing in {STATIC_DIR}")
        sys.exit(1)

    port = find_free_port(args.port) if args.auto_port else args.port
    SERVER_PORT = port

    load_persistence()
    try:
        refresh(force_external=True)
    except Exception as e:
        print(f"Warning: initial scan issue ({e}). Will keep retrying.")

    threading.Thread(target=poll_loop, args=(args.interval,), daemon=True).start()

    try:
        server = ReusableThreadingHTTPServer(("127.0.0.1", port), Handler)
    except OSError as e:
        print(
            f"Couldn't bind to 127.0.0.1:{port} ({e}).\n"
            f"Try: python3 {sys.argv[0]} --port {port + 1}  (or pass --auto-port)"
        )
        sys.exit(1)

    try:
        v6_server = ReusableIPv6HTTPServer(("::1", port), Handler)
        threading.Thread(target=v6_server.serve_forever, daemon=True).start()
        IPV6_READY = True
    except OSError:
        IPV6_READY = False

    host_label = "localhost" if IPV6_READY else "127.0.0.1"
    url = f"http://{host_label}:{port}/?token={TOKEN}"
    print("\n  Agent Deck v2.7 is running.")
    print(f"  Open:  {url}")
    print("  Press Ctrl+C to stop.\n")

    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        _shutdown_managed_servers()
        print("\n  Stopped.")


if __name__ == "__main__":
    main()
