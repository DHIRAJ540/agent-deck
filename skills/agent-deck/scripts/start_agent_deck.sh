#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="${HOME}/.agent-deck"
PID_FILE="${STATE_DIR}/server.pid"
LOG_FILE="${STATE_DIR}/server.log"
INSTALL_DIR="${HOME}/agent-deck"

MODE="start"
EXTRA_ARGS=()
OPEN_BROWSER=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --status)
      MODE="status"
      shift
      ;;
    --stop)
      MODE="stop"
      shift
      ;;
    --install)
      MODE="install"
      shift
      ;;
    --no-browser)
      OPEN_BROWSER=0
      EXTRA_ARGS+=("--no-browser")
      shift
      ;;
    *)
      EXTRA_ARGS+=("$1")
      shift
      ;;
  esac
done

mkdir -p "${STATE_DIR}"

is_running() {
  if [[ -f "${PID_FILE}" ]]; then
    local pid
    pid="$(cat "${PID_FILE}" 2>/dev/null || true)"
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      return 0
    fi
  fi
  return 1
}

extract_url() {
  if [[ -f "${LOG_FILE}" ]]; then
    grep -Eo 'http://(localhost|127\.0\.0\.1):[0-9]+/\?token=[A-Za-z0-9_-]+' "${LOG_FILE}" | tail -n 1 || true
  fi
}

if [[ "${MODE}" == "install" ]]; then
  mkdir -p "${INSTALL_DIR}/static"
  cp "${SCRIPT_DIR}/agent_deck.py" "${INSTALL_DIR}/agent_deck.py"
  cp "${SCRIPT_DIR}/static/index.html" "${INSTALL_DIR}/static/index.html"
  cp "${SCRIPT_DIR}/static/styles.css" "${INSTALL_DIR}/static/styles.css"
  cp "${SCRIPT_DIR}/static/app.js" "${INSTALL_DIR}/static/app.js"
  chmod +x "${INSTALL_DIR}/agent_deck.py"
  echo "Installed Agent Deck to ${INSTALL_DIR}"
  echo "Run with: python3 ${INSTALL_DIR}/agent_deck.py --auto-port"
  exit 0
fi

if [[ "${MODE}" == "stop" ]]; then
  if is_running; then
    pid="$(cat "${PID_FILE}")"
    kill "${pid}" 2>/dev/null || true
    rm -f "${PID_FILE}"
    echo "Stopped Agent Deck (PID ${pid})."
  else
    rm -f "${PID_FILE}"
    echo "Agent Deck is not currently running via start_agent_deck.sh."
  fi
  exit 0
fi

if [[ "${MODE}" == "status" ]]; then
  if is_running; then
    pid="$(cat "${PID_FILE}")"
    url="$(extract_url)"
    echo "Agent Deck is running (PID ${pid})."
    [[ -n "${url}" ]] && echo "Open: ${url}"
    exit 0
  else
    echo "Agent Deck is not running."
    exit 1
  fi
fi

if is_running; then
  pid="$(cat "${PID_FILE}")"
  url="$(extract_url)"
  echo "Agent Deck is already running (PID ${pid})."
  if [[ -n "${url}" ]]; then
    echo "Open: ${url}"
    if [[ "${OPEN_BROWSER}" -eq 1 ]] && command -v open >/dev/null 2>&1; then
      open "${url}" >/dev/null 2>&1 || true
    fi
  fi
  exit 0
fi

APP_PY="${SCRIPT_DIR}/agent_deck.py"
if [[ -f "${INSTALL_DIR}/agent_deck.py" && "${INSTALL_DIR}/agent_deck.py" -nt "${APP_PY}" ]]; then
  APP_PY="${INSTALL_DIR}/agent_deck.py"
fi

: > "${LOG_FILE}"
nohup python3 -u "${APP_PY}" --auto-port --no-browser "${EXTRA_ARGS[@]+"${EXTRA_ARGS[@]}"}" >> "${LOG_FILE}" 2>&1 &
NEW_PID=$!
echo "${NEW_PID}" > "${PID_FILE}"

URL=""
for _ in {1..25}; do
  if ! kill -0 "${NEW_PID}" 2>/dev/null; then
    echo "Agent Deck exited unexpectedly:" >&2
    cat "${LOG_FILE}" >&2
    rm -f "${PID_FILE}"
    exit 1
  fi
  URL="$(extract_url)"
  if [[ -n "${URL}" ]]; then
    break
  fi
  sleep 0.15
done

echo "Agent Deck started (PID ${NEW_PID})."
if [[ -n "${URL}" ]]; then
  echo "Open: ${URL}"
  if [[ "${OPEN_BROWSER}" -eq 1 ]] && command -v open >/dev/null 2>&1; then
    open "${URL}" >/dev/null 2>&1 || true
  fi
else
  cat "${LOG_FILE}"
fi
