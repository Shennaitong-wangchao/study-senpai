# Demo Script

These scripts are for public README GIFs. Use a temporary database and fake data only. Do not record real chat history, memory rows, tokens, cookies, private backend addresses, or personal locations.

## Demo 1: iOS Chat Demo

**Recording goal**: show that the iOS client can connect to a local Study Senpai backend, send a study-oriented message, stream a reply, and keep the interaction in the mobile timeline.

**README GIF filename**: `docs/assets/demo-ios-chat.gif`

**Fake preparation data**:

- Temporary SQLite database created just for the recording.
- Fake learner name, for example `Alex`.
- Fake study prompt: `I have 45 minutes. Help me plan a focused review block for calculus.`
- Optional fake attachment: a short blank worksheet or synthetic note with no real names or account data.
- `MOBILE_API_TOKEN` may be set, but never show the value on screen.

**Recording steps**:

1. Start the backend locally with the temporary database.
2. Open the iOS app in Simulator.
3. Open **Settings** and set **Server Base URL** to the local backend.
4. If token auth is enabled, enter **Mobile API Token**, then leave Settings before recording the main flow.
5. Send the fake study prompt.
6. Wait for the streaming reply to finish.
7. Switch briefly to the timeline or home view to show that the message remains visible.

**What should appear on screen**:

- iOS chat view.
- One fake user study request.
- One assistant reply that contains a plan, time boxes, or next step.
- No token, no real endpoint beyond localhost, no real chat history.

**Safety notes**:

- Crop out Settings if a token was typed.
- Do not show push notification previews from real apps.
- Do not show real calendar, location, Discord, or account data.

## Demo 2: Memory Dashboard Demo

**Recording goal**: show that memory is auditable and reversible before it becomes durable context.

**README GIF filename**: `docs/assets/demo-memory-dashboard.gif`

**Fake preparation data**:

- Temporary SQLite database created just for the recording.
- Seed at least one fake conversation and one fake memory candidate.
- Example candidate content: `Alex prefers 25-minute focus blocks with 5-minute breaks.`
- Example structured fact: `study_style = pomodoro`.

**Recording steps**:

1. Start the backend and Dashboard locally.
2. Log in with local development credentials, avoiding any visible password field in the final recording.
3. Open the memory candidate panel.
4. Approve one fake candidate.
5. Open the long-term memory panel and show the approved fake memory.
6. Archive the fake memory.
7. Restore it to show reversibility.
8. Open an audit or detail panel if it does not reveal private data.

**What should appear on screen**:

- Dashboard memory/candidate panels.
- A clearly fake memory candidate.
- Approve, archive, and restore controls.
- Status changes or audit rows for the fake memory.

**Safety notes**:

- Never record a real production database.
- Do not show raw SQL tools or filesystem paths containing user names.
- Keep browser autocomplete, password managers, and address history hidden.

## Demo 3: Study Workflow Demo

**Recording goal**: show how learning mode, planning, and proactive care work together for a study session.

**README GIF filename**: `docs/assets/demo-study-workflow.gif`

**Fake preparation data**:

- Temporary SQLite database created just for the recording.
- Fake study goal: `Review derivatives and complete 10 practice problems.`
- Fake availability: `45 minutes before dinner`.
- Fake proactive preference: opt in for a check-in after the first study block.

**Recording steps**:

1. Start the backend locally with fake data.
2. In iOS or Discord, enable learning mode.
3. Send the fake study goal and availability.
4. Show the assistant creating a short study plan.
5. Open the Dashboard mode or proactive panel.
6. Show the fake proactive preference and one generated check-in.
7. Return to chat and show the next study step.

**What should appear on screen**:

- Learning mode enabled.
- A short study plan with concrete steps.
- Dashboard state reflecting mode/proactive settings.
- One fake proactive check-in or planned nudge.

**Safety notes**:

- Use fake goals and fake schedule data only.
- Do not show real notification history or personal calendars.
- Do not expose `MOBILE_API_TOKEN`, Dashboard credentials, private hostnames, or real chat records.

## Recording Checklist

- Use a temporary database under an ignored local directory.
- Use placeholder model and Discord credentials in any visible setup screen.
- Redact secrets as `[REDACTED]` if a setup screen must be shown.
- Keep all visible data synthetic.
- Export the GIFs to the exact filenames listed above.
