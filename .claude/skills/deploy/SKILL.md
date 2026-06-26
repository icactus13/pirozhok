---
name: deploy
description: Deploy the Telegram bot (tgbot) to the remote production server (root@88.218.169.142:2233). Use whenever the user asks to deploy, push to server, rebuild on server, ship the bot, "залить на сервер", "задеплой", "обнови на сервере", "перекинь на прод", or similar.
---

# Deploy tgbot

Repo: `/Users/zlo/dev/tgbot/`. Production: `root@88.218.169.142:/root/tgbot` (SSH port 2233).

The deploy script handles file sync + container management. Don't `scp` files manually anymore — use the script.

## Usage

```bash
./scripts/deploy.sh                    # default: rsync + rebuild + restart
./scripts/deploy.sh --logs             # also tail bot logs after deploy
./scripts/deploy.sh --no-rebuild       # rare: skip rebuild, only restart
./scripts/deploy.sh --sync-content     # ALSO overwrite prompt.txt/skills/settings.json
./scripts/deploy.sh --dry-run          # show what rsync would do, no changes
./scripts/deploy.sh --help             # full help
```

## Why default is rebuild

Python code is **baked into the image** at `docker build` time — it's not volume-mounted. So `docker compose restart` keeps running the OLD code even after rsync drops new files on disk. **Don't use `--no-rebuild` unless you only touched these volume-mounted files**:

- `prompt.txt` (volume-mounted → restart picks up)
- `settings.json` (volume-mounted)
- `skills/*.md` (volume-mounted)
- `searxng/settings.yml` (volume-mounted into searxng container — needs `docker compose restart searxng`, not bot)

For anything else (any `.py` under `src/`, `Dockerfile`, `pyproject.toml`, `uv.lock`, `docker-compose.yml`) — leave the default rebuild on.

## What's excluded from sync by default

Never overwrite on the server:
- `data/` (SQLite, Qdrant, Redis, fastembed cache — runtime state)
- `.env` (secrets — production has its own)
- `prompt.txt`, `settings.json`, `skills/` (bot edits these live via `update_prompt` / `create_or_update_skill` admin tools; overwriting nukes user's runtime edits)
- `.git/`, `__pycache__/`, `.venv/`, `MEMORY.md`, `.claude/`, `scripts/`

Use `--sync-content` only when you explicitly want to push a new prompt/skill set from the repo to the server (e.g. first-time setup or rolling back live edits).

## Before overwriting prompt.txt / skills (REQUIRED)

The user edits `prompt.txt` live (via the bot / `/setprompt`), and new skills may be
created on the server at runtime. So the server can legitimately have content the repo
doesn't. **Never silently overwrite it.**

- **Skills:** rsync runs WITHOUT `--delete`, so server-only skills are preserved — keep it
  that way. Never delete a skill that exists only on the server.
- **prompt.txt:** before running `--sync-content`, diff the server prompt against the repo,
  understand exactly what diverged, and **ask the user what to keep vs overwrite**. Do not
  decide yourself.

  ```bash
  ssh -p 2233 root@88.218.169.142 'cat /root/tgbot/prompt.txt' | diff - prompt.txt
  ```

If you only changed `.py` / `Dockerfile` / `pyproject.toml` / `uv.lock`, use the **default deploy
(no `--sync-content`)** — it leaves prompt.txt, skills/ and settings.json untouched.

## Verification after deploy

The script shows container status and (with `--logs`) tails 20 lines. Healthy startup looks like:

```
[INFO] Settings: model=google/gemini-2.5-flash, history=10
[INFO] SQLite ready
[INFO] Qdrant ready
[INFO] Redis client ready
[INFO] Skills: N loaded
[INFO] Application started
[INFO] Пирожок is running. Press Ctrl+C to stop.
```

If any of these are missing, or there's a Python traceback — investigate before considering the deploy done.

## Troubleshooting

- **`ssh: connect to host ...: Connection refused`** — server unreachable or wrong port. Confirm with `ssh -p 2233 root@88.218.169.142 'echo ok'`.
- **`rsync: ... permission denied`** — likely an SSH agent issue, not a server problem.
- **Bot starts then dies** — check `docker logs tgbot-bot-1` for the traceback. Common: missing env var (e.g. `OPENWEATHER_API_KEY`), or new dependency without `--rebuild`.
- **Bot won't pick up code changes** — you forgot `--rebuild` after a dependency change (`pyproject.toml`/`uv.lock`), or the volume mount is shadowing a file. Try `--rebuild` first.

## Env overrides

If the server moves or you're testing against a staging box:

```bash
TGBOT_HOST=user@staging.example.com TGBOT_PORT=22 TGBOT_PATH=/srv/tgbot ./scripts/deploy.sh
```
