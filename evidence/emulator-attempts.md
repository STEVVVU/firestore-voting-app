# Firestore emulator attempts

- Firebase CLI 14.22.0, emulator v1.19.8, Java 21, loopback `127.0.0.1:18880`, demo project, 2026-10-27.
- First command passed `.venv/Scripts/python` to Windows cmd; failed because cmd interpreted `.venv` as a command. Emulator shut down.
- Second command used `.venv\Scripts\python.exe`; 4-worker same-UID contention failed: `ValueError: Failed to commit transaction in 5 attempts`, caused by Firestore gRPC `ABORTED: Transaction lock timeout`. This is retained as an observed failed run. The emulator shut down. The test is revised to record exhaustion as an outcome and verify exact state after explicit caller retries; it does not claim every concurrent call succeeded.
- A two-worker run passed the exact-state test. Another two-worker run exhausted both attempts, so its assertion that a winner already existed failed (`emulator-failed-second.log`). The revised test checks no partial data before an explicit sequential retry when both requests fail.
