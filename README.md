# Study Senpai

Local-first companion framework for learning, memory, and proactive care.

Study Senpai is a self-hosted Python + SQLite companion system with an iOS client, Discord bot path, and auditable Dashboard. It is built for people who want learning support and long-running memory while keeping state under their own control.

## What Is Included

- Python backend with SQLite persistence.
- FastAPI Dashboard for memory review, observability, and local operations.
- Mobile API used by the SwiftUI iOS client under `ios/Lover/`.
- Optional Discord bot runtime.
- Memory extraction, review, archive/restore, summaries, and proactive check-in flows.

沈知微 is included as the default example persona. Treat it as sample product behavior, not a fixed hosted service identity.

## Status

This is an early source release. It is suitable for local development and personal self-hosting, but production deployment still needs normal operator work: TLS, reverse proxy or firewall rules, backups, token rotation, and monitoring.

## Quick Start

Use Python 3.11 or newer. The CI workflow currently tests with Python 3.11.

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

Edit `.env` and fill only the values you need:

```bash
LLM_API_KEY=
LLM_MODEL=gpt-4.1-mini
RUN_DISCORD_BOT=false
DASHBOARD_ENABLED=true
DASHBOARD_HOST=127.0.0.1
DASHBOARD_PORT=8099
MOBILE_API_TOKEN=
```

Start the backend and Dashboard:

```bash
python3 -m src.main
```

Open the Dashboard locally:

```text
http://127.0.0.1:8099
```

Run the lightweight checks:

```bash
python3 scripts/mobile_contracts.py
python3 scripts/dashboard_contracts.py
python3 scripts/verify_product.py
```

## Environment Variables

Required for backend replies:

- `LLM_API_KEY`: model provider key. Keep it in `.env`; never commit it.
- `LLM_MODEL`: default model name.
- `LLM_BASE_URL`: optional OpenAI-compatible API base URL.
- `LLM_PROMPT_CACHING_ENABLED`: defaults to `true`; keeps static prompt content first for OpenAI-style automatic caching
  and uses Anthropic native cache breakpoints when `LLM_BASE_URL` points at Anthropic.

Discord path:

- `RUN_DISCORD_BOT`: set `true` to start Discord.
- `DISCORD_BOT_TOKEN`: required only when `RUN_DISCORD_BOT=true`.
- `DISCORD_APPLICATION_ID`: optional application id.

Local state:

- `DATABASE_PATH`: defaults to a SQLite file under `data/`.
- `LOG_FILE_PATH`: defaults to a log file under `logs/`.
- `BOT_TIMEZONE`: defaults to `Asia/Shanghai`.

Dashboard and mobile API:

- `DASHBOARD_ENABLED`: starts the FastAPI Dashboard/mobile backend.
- `DASHBOARD_HOST` / `DASHBOARD_PORT`: bind address and port.
- `DASHBOARD_AUTH_ENABLED`, `DASHBOARD_AUTH_USERNAME`, `DASHBOARD_AUTH_PASSWORD`: Dashboard login.
- `MOBILE_API_TOKEN`: optional Bearer token for `/mobile/*`. Set it before exposing mobile APIs beyond localhost.

## iOS Backend Configuration

The iOS app does not contain a hardcoded public or private backend URL.

- Debug default Server Base URL: `http://127.0.0.1:8000`.
- In the iOS app, open **Settings** and edit **Server Base URL**.
- If your Python backend uses the repository default port, set it to `http://127.0.0.1:8099`.
- If `MOBILE_API_TOKEN` is set on the backend, enter the same value in **Mobile API Token**.

For simulator testing with the iOS default, start the backend with:

```bash
DASHBOARD_PORT=8000 python3 -m src.main
```

## Project Structure

```text
src/
  core/          Settings, logging, shared types
  db/            SQLite schema and migrations
  memory/        Memory extraction, retrieval, writing, summaries
  persona/       Default Shen Zhiwei persona and reply policies
  services/      Companion, reply, and memory orchestration
  bot/           Discord client and message routing
  dashboard/     FastAPI Dashboard and /mobile API
  mobile/        Mobile API schemas
  product/       Attachments, proactive care, day engine, observability
ios/Lover/       SwiftUI iOS client
scripts/         Contract, smoke, and regression checks
docs/            Architecture, roadmap, operations, demos
```

## Persona

沈知微 is the default example persona. The current implementation keeps that persona in Python modules under `src/persona/` and prompt files under `src/llm/prompts/`. See [docs/PERSONA_SYSTEM_PUBLIC.md](docs/PERSONA_SYSTEM_PUBLIC.md) for the planned YAML/JSON persona registry direction.

## Security And Privacy

- Study Senpai is local-first and self-hosted, but it is not automatically private if you bind it to a public host.
- `.env`, SQLite databases, `data/`, `logs/`, `secrets/`, and iOS local config/signing files are ignored by default.
- `/mobile/*` requires `Authorization: Bearer <MOBILE_API_TOKEN>` when `MOBILE_API_TOKEN` is set.
- If `MOBILE_API_TOKEN` is not set, `/mobile/*` accepts localhost/dev requests only. Do not expose it publicly in that mode.
- Dashboard auth is separate from mobile token auth. Keep Dashboard auth enabled outside local development.
- Do not commit API keys, Discord tokens, cookies, chat logs, generated media, SQLite files, or exported memory data.

See [SECURITY.md](SECURITY.md) before publishing or deploying.

## Roadmap

- Stage 1.5 release polish: GitHub hygiene files, demo scripts, and lightweight CI.
- Persona registry: move persona definitions into auditable YAML/JSON configs.
- Safer public deployment profile: reverse proxy examples, HTTPS guidance, token rotation workflow.
- Mobile polish: persisted server profiles, token validation screen, generated media cache.
- Memory governance: export/import controls, redaction workflow, retention settings.
- Study workflows: goals, plans, spaced review, and learning-session analytics.

More detail: [docs/ROADMAP.md](docs/ROADMAP.md).

## License

MIT. See [LICENSE](LICENSE).
