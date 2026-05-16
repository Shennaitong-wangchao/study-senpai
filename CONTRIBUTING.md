# Contributing

Thanks for helping improve Study Senpai. This repository is still early and contains local-first companion, memory, Discord, Dashboard, and iOS paths, so contributions should stay small and easy to audit.

## Ground Rules

- Do not commit `.env`, SQLite databases, logs, exported chats, cookies, tokens, generated media, or local iOS signing/config files.
- Do not paste real API keys, Discord tokens, cookies, private chat logs, or database contents into issues, pull requests, or tests.
- Keep database schema changes out of small fixes unless the change is explicitly scoped as a migration.
- Keep core chat and memory behavior changes covered by focused tests.
- Preserve the existing Python backend, Discord bot, Dashboard, and iOS paths unless a task explicitly says otherwise.

## Local Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
cp .env.example .env
```

For Dashboard/mobile-only development:

```bash
RUN_DISCORD_BOT=false
DASHBOARD_ENABLED=true
```

## Checks

Run the smallest relevant checks before opening a PR:

```bash
python3 scripts/verify_product.py
python3 scripts/dashboard_contracts.py
python3 scripts/mobile_contracts.py
```

For Dashboard UI changes, also run:

```bash
python3 scripts/dashboard_e2e.py
python3 scripts/dashboard_visual_regression.py
```

## Pull Requests

Include:

- What changed and why.
- Which paths are affected: backend, Discord, Dashboard, mobile API, iOS, docs.
- Which checks were run.
- Any privacy or deployment impact.

## Persona Changes

沈知微 is the default example persona. Keep persona changes isolated and documented. The planned direction is a YAML/JSON persona registry; see `docs/PERSONA_SYSTEM_PUBLIC.md`.
