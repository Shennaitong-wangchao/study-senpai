# Security Policy

## Supported Scope

This repository is a local-first companion framework. The current security posture is intended for local development, private servers, and carefully controlled personal deployments.

## Sensitive Data

Never commit or disclose:

- `.env` files or environment-specific config.
- API keys, Discord tokens, mobile API tokens, cookies, session secrets, or dashboard passwords.
- SQLite databases, WAL/SHM files, backups, memory exports, chat logs, generated images, attachments, or local logs.
- iOS signing files, provisioning profiles, private xcconfig files, or local secret Swift files.

Use `[REDACTED]` when reporting an issue that involves a secret or private user content.

## Mobile API Authentication

`/mobile/*` is protected by a minimal Bearer token gate:

- Set `MOBILE_API_TOKEN` in the backend environment for any non-local deployment.
- Send `Authorization: Bearer <token>` from the iOS client or any mobile API caller.
- If `MOBILE_API_TOKEN` is empty, the backend only allows localhost/dev-style requests.

Example:

```bash
export MOBILE_API_TOKEN="replace-with-a-long-random-token"
```

```bash
curl -H "Authorization: Bearer $MOBILE_API_TOKEN" \
  http://127.0.0.1:8099/mobile/bootstrap
```

Do not rely on the empty-token localhost fallback behind a public reverse proxy. Set a token before exposing the backend.

## Dashboard Security

- Keep `DASHBOARD_AUTH_ENABLED=true` outside local experiments.
- Set a strong `DASHBOARD_AUTH_PASSWORD` or change the generated bootstrap password immediately.
- Use `DASHBOARD_SESSION_SECRET` in production-like environments.
- Prefer TLS termination and `DASHBOARD_SESSION_HTTPS_ONLY=true` when serving over HTTPS.
- If binding `DASHBOARD_HOST=0.0.0.0`, also set `DASHBOARD_PUBLIC_BIND_ACKNOWLEDGED=true` and protect the service with a firewall, VPN, or reverse proxy.

## Reporting Vulnerabilities

Open a private advisory or contact the maintainer directly. Do not include real secrets, chat logs, database rows, or user-identifying data. Replace sensitive values with `[REDACTED]`.

Please include:

- A concise impact statement.
- Affected path or endpoint.
- Reproduction steps using dummy data.
- Suggested fix, if known.
