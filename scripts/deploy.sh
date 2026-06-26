#!/usr/bin/env bash
# Deploy tgbot to remote server.
# By default rebuilds the image because Python code is baked in (not volume-mounted).
# Use --no-rebuild only when you ONLY touched volume-mounted files
# (prompt.txt, settings.json, skills/) — but those need --sync-content too.
#
# Env overrides:
#   TGBOT_HOST (default: root@88.218.169.142)
#   TGBOT_PORT (default: 2233)
#   TGBOT_PATH (default: /root/tgbot)

set -euo pipefail

HOST="${TGBOT_HOST:-root@88.218.169.142}"
PORT="${TGBOT_PORT:-2233}"
REMOTE_PATH="${TGBOT_PATH:-/root/tgbot}"

REBUILD=true
SHOW_LOGS=false
SYNC_CONTENT=false
DRY_RUN=false

usage() {
    cat <<EOF
Usage: $0 [options]

By default: rsync + rebuild + restart bot container (because .py code is baked
into the image, not volume-mounted).

Options:
  --no-rebuild     Skip the docker image rebuild — only restart the container.
                   Use ONLY when no .py / Dockerfile / pyproject.toml / uv.lock changed.
  --logs           Tail recent bot logs after deploy.
  --sync-content   Also overwrite live content on the server:
                   prompt.txt, skills/, settings.json. By default these are
                   excluded because the bot edits them at runtime.
  --dry-run        Show what rsync would do without making changes.
  -h, --help       This help.

Env:
  TGBOT_HOST  (default: ${HOST})
  TGBOT_PORT  (default: ${PORT})
  TGBOT_PATH  (default: ${REMOTE_PATH})
EOF
}

for arg in "$@"; do
    case "$arg" in
        --no-rebuild) REBUILD=false ;;
        --rebuild) REBUILD=true ;;  # kept for compat
        --logs) SHOW_LOGS=true ;;
        --sync-content) SYNC_CONTENT=true ;;
        --dry-run) DRY_RUN=true ;;
        -h|--help) usage; exit 0 ;;
        *)
            echo "Unknown option: $arg" >&2
            usage >&2
            exit 1
            ;;
    esac
done

cd "$(dirname "$0")/.."

EXCLUDES=(
    --exclude=".git/"
    --exclude=".gitignore"
    --exclude="__pycache__/"
    --exclude="*.pyc"
    --exclude=".venv/"
    --exclude="venv/"
    --exclude=".DS_Store"
    --exclude="data/"
    --exclude=".env"
    --exclude="*.db"
    --exclude="*.log"
    --exclude=".claude/"
    --exclude="MEMORY.md"
    --exclude="scripts/"
)
if ! $SYNC_CONTENT; then
    EXCLUDES+=(
        --exclude="prompt.txt"
        --exclude="settings.json"
        --exclude="skills/"
    )
fi

RSYNC_FLAGS=(-avz --human-readable)
$DRY_RUN && RSYNC_FLAGS+=(--dry-run)

echo "→ Syncing files to ${HOST}:${REMOTE_PATH} ..."
rsync -e "ssh -p ${PORT}" "${RSYNC_FLAGS[@]}" "${EXCLUDES[@]}" ./ "${HOST}:${REMOTE_PATH}/"

if $DRY_RUN; then
    echo "✓ Dry run complete (no remote changes)."
    exit 0
fi

if $REBUILD; then
    echo "→ Rebuilding image and restarting bot ..."
    ssh -p "${PORT}" "${HOST}" "cd ${REMOTE_PATH} && docker compose up -d --build bot"
else
    echo "→ Restarting bot (no rebuild) ..."
    ssh -p "${PORT}" "${HOST}" "cd ${REMOTE_PATH} && docker compose restart bot"
fi

echo "→ Container status:"
ssh -p "${PORT}" "${HOST}" "docker ps --filter name=tgbot --format 'table {{.Names}}\t{{.Status}}'"

if $SHOW_LOGS; then
    echo "→ Recent bot logs:"
    sleep 2
    ssh -p "${PORT}" "${HOST}" "docker logs tgbot-bot-1 --tail 20"
fi

echo "✓ Deploy done."
