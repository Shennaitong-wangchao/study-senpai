# Roadmap

This roadmap keeps the project useful as a local-first framework while preparing it for safer public collaboration.

## Phase 1: Safe Open-Source Packaging

- Harden `.gitignore` for local state, secrets, SQLite, logs, chats, and iOS private files.
- Add minimal mobile Bearer token auth.
- Remove hardcoded iOS backend URLs.
- Rewrite README around Study Senpai.
- Add baseline open-source docs and policy files.

## Phase 1.5: Release Acceptance And Public Face

- Tighten pre-publish sensitive file checks.
- Improve README first-screen positioning for GitHub visitors.
- Add public demo recordings after they are captured from a clean demo database.
- Add GitHub issue, pull request, conduct, changelog, and CI hygiene files.
- Keep CI lightweight: install Python dependencies and run contract/smoke scripts.

## Phase 2: Config And Deployment Hardening

- Add generated secret checks in CI.
- Add a production deployment guide with reverse proxy, HTTPS, firewall, and token rotation.
- Add a sample `.env.local.example` for Dashboard-only, Discord-only, and full-stack modes.
- Add a health endpoint profile that does not leak private app state.
- Add rate limits for mobile and Dashboard write endpoints.

## Phase 3: Persona Registry

- Move persona metadata and style rules into YAML/JSON.
- Validate persona configs with a typed schema.
- Support multiple personas without changing core chat code.
- Add migration notes for existing 沈知微 defaults.

## Phase 4: Memory Governance

- Add explicit retention controls.
- Add memory export/import with redaction.
- Add review queues for sensitive memories.
- Add audit views for which memories influenced a reply.

## Phase 5: Study Workflows

- Add goal plans, study sessions, spaced review, and progress summaries.
- Add attachment-to-study-note flows.
- Add local analytics for focus, cadence, and streaks without cloud sync by default.

## Phase 6: iOS Maturity

- Add server profile management.
- Add token validation and connection diagnostics.
- Add authenticated media caching.
- Add better offline timeline behavior.
