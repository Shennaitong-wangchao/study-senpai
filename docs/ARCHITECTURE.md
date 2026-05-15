# Architecture

Study Senpai is a local-first companion framework built around one Python backend and multiple user surfaces.

## Runtime Paths

- **Discord**: `src/bot/` receives Discord messages and routes them into the companion service.
- **Dashboard**: `src/dashboard/server.py` exposes FastAPI routes for review, observability, memory governance, and operations.
- **Mobile API**: `/mobile/*` routes live in the Dashboard app and reuse the same stores and services.
- **iOS**: `ios/Lover/` is a SwiftUI client for mobile chat, timeline, attachments, settings, and dashboard panels.

## Core Backend Flow

1. A user message arrives from Discord or `/mobile/chat/stream`.
2. `CompanionService` writes the user message, updates presence, plans tools, and builds reply context.
3. `ReplyService` calls the configured LLM through `LLMClient`.
4. The assistant message is stored in SQLite.
5. Background post-processing extracts candidate memories, summaries, facts, relationship state, and observability metrics.
6. Dashboard/mobile views read the same SQLite-backed stores for review and display.

## Storage

SQLite is the default local store:

- Chat messages and sessions.
- Long-term memories and candidate memories.
- Structured facts and relationship states.
- Dashboard audit/security events.
- Background tasks and product observability.

The first open-source phase does not change database schema.

## Configuration

Backend configuration is environment-driven through `src/core/settings.py`. Local secrets belong in `.env`, which is ignored by git.

Important boundaries:

- `DATABASE_PATH` and `LOG_FILE_PATH` control local state paths.
- `MOBILE_API_TOKEN` gates `/mobile/*` outside localhost/dev.
- `DASHBOARD_AUTH_*` controls Dashboard login and session behavior.
- `RUN_DISCORD_BOT`, `RUN_BACKGROUND_WORKER`, and `DASHBOARD_ENABLED` control runtime roles.

## Persona

沈知微 is the default example persona. Today it is implemented in Python modules and prompt files:

- `src/persona/`
- `src/llm/prompts/`

The planned direction is a data-driven persona registry. See `docs/PERSONA_SYSTEM.md`.

## Security Boundary

Dashboard auth and mobile token auth are separate:

- Dashboard routes use session auth and CSRF checks.
- `/mobile/*` uses Bearer token auth when `MOBILE_API_TOKEN` is set.
- Empty mobile token mode is for localhost/dev only.

Do not expose the backend publicly without setting Dashboard auth, `MOBILE_API_TOKEN`, and network-level protection.
