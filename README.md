# Study Senpai

Local-first AI companion framework for learning, memory, and proactive care.

Study Senpai is a self-hosted Python + SQLite companion system with an iOS client, Discord bot path, and auditable Dashboard. It is built for people who want learning support and long-running memory while keeping state under their own control.

## Core Value

- **Auditable long-term memory**: review, approve, archive, restore, and inspect memory candidates before they influence future replies.
- **Study companion workflows**: learning mode, attachments, reminders, proactive nudges, and session summaries support sustained study routines.
- **iOS + Discord + Dashboard experience**: use the iOS app or Discord for chat, then inspect state and memory decisions in the Dashboard.

## Demo Placeholders

| Demo | GIF placeholder | What it should show |
| --- | --- | --- |
| iOS chat demo | `docs/assets/demo-ios-chat.gif` | Mobile chat, streaming reply, and local backend configuration |
| Memory dashboard demo | `docs/assets/demo-memory-dashboard.gif` | Candidate review, memory audit, archive, and restore |
| Study workflow demo | `docs/assets/demo-study-workflow.gif` | Learning mode, study planning, and a proactive check-in |

## Who Is This For?

- Builders experimenting with local-first AI companions.
- Learners who want a study partner with inspectable memory instead of opaque cloud state.
- Researchers and hobbyists exploring persona, memory governance, and proactive care workflows.
- Self-hosters who are comfortable running a Python backend and keeping private data local.

## What Makes It Different?

- **User-controlled state**: SQLite, logs, generated artifacts, and memory exports stay local unless you choose to deploy or sync them.
- **Memory is reviewable**: memory candidates and structured facts can be inspected before becoming durable context.
- **Multi-endpoint by design**: the same backend serves Discord, Dashboard, and iOS/mobile flows.
- **Persona is explicit**: 沈知微 is included as the default example persona, not a fixed product identity.

## Quick Start

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
