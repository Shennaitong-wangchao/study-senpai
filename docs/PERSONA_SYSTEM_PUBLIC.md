# Persona Registry Design

Study Senpai currently keeps persona behavior in versioned Python modules and prompt templates. The planned public direction is a data-driven persona registry that separates product code from persona configuration without storing private chats, private prompts, or user-specific memories in git.

## Goals

- Keep persona identity, voice constraints, safety boundaries, and memory policy declarative.
- Allow multiple example personas without changing core chat logic.
- Make the public repository safe to clone by keeping private persona drafts and local seed data outside git.
- Validate persona files with schema checks before they are loaded by the application.

## Proposed Shape

A future registry can use YAML or JSON files with sections such as:

- `identity`: public name, role, locale, and high-level style.
- `voice`: response tone, formatting preferences, and phrase-level constraints.
- `boundaries`: topics or behaviors the persona must avoid.
- `memory_policy`: what may be remembered, summarized, or ignored.
- `examples`: synthetic examples only, never real private conversations.

## Privacy Rules

- Do not commit real chats, exported conversations, private prompts, seed memories, tokens, or deployment-specific configuration.
- Keep local-only persona drafts in ignored files.
- Use synthetic examples for tests, docs, demos, and screenshots.
- Treat persona registry changes as product behavior changes and review them before release.

## Migration Notes

The current source modules under `src/persona/` and prompt templates under `src/llm/prompts/` remain the source of truth until the registry loader and validation flow are implemented.
