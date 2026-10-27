---
name: verify-firestore-voting-app
description: Drive the voting API through HTTP in an isolated local process and inspect its durable-state boundary.
---

# Verification

Run from the project root: `.venv/Scripts/python verify.py` (or `.venv/bin/python verify.py` on Unix). Install `requirements.txt` into the virtual environment first. Port 18763 must be free.

**Launch:** the driver starts its own Uvicorn process with an isolated temporary SQLite database and local synthetic identity. It checks process ownership and polls readiness.

**Doctor:** `GET /health` must return `{"status":"ok"}`.

**Drive:** the driver sends five batches of 20 distinct `POST /votes` requests using local bearer identities and checks `GET /results` after each batch. It checks the SQLite row count independently.

**Evidence:** `evidence/http-proof.json` records all latencies, errors, counts, final response, environment, and row count. `evidence/http-proof.sha256` hashes it. These paths are outside scratch storage. This local mode does not exercise Firebase or Firestore.

**Cleanup:** the driver terminates only its owned process and deletes its temporary database, then verifies evidence persists. An occupied port or startup failure must be investigated, not worked around by stopping another process.

**Helpers:** `verify.py` implements the entire lifecycle. Use `maintain-verification-skill` if product paths drift.

For Firestore SDK integration use the isolated official emulator command in the README and inspect `evidence/emulator-create-count.log`; errors must be reported, not silently discarded. Earlier transaction-based receipts are retained separately. `benchmark.py` records five batches each at concurrency 1 and 4, every response, row-count oracles and hashes in `evidence/http-concurrency.json`. Browser steps are in the [feature map](features/browser.md).
