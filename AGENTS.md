# Firestore voting app

Use the isolated .venv and requirements.txt. Run `.venv/Scripts/python -m pytest -q`, `.venv/Scripts/python -m ruff check app.py tests verify.py benchmark.py`, and `.venv/Scripts/python verify.py`. The maintained driver is .agents/skills/verify-firestore-voting-app/SKILL.md. Dedicated emulator commands and receipts are under tests/ and evidence/; normal tests skip the official emulator when it is absent.

app.py owns production identity, conditional vote creation and native count queries. static/ owns the Firebase browser client. Local identity and SQLite require APP_ENV=local and are forbidden in production. Never log tokens or publish credentials. Current tests use synthetic identities and a demo emulator project. Old shared-counter contention receipts are historical and must remain.

UI work follows .agents/design-reference.md and the global design-with-evidence skill. Browser checks remain CUA-only. No cloud deployment or paid resources without authorization.
