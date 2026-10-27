"""Launch an isolated local service, drive it over HTTP, retain evidence, and clean up."""
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
from contextlib import closing
from pathlib import Path

import httpx


def main():
    root = Path(__file__).resolve().parent
    evidence = root / 'evidence'
    evidence.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as scratch:
        db = Path(scratch) / 'votes.sqlite3'
        env = dict(os.environ, APP_ENV='local', VOTING_BACKEND='sqlite', IDENTITY_MODE='local', SQLITE_PATH=str(db))
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '18763'], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with httpx.Client(base_url='http://127.0.0.1:18763', timeout=5) as client:
                deadline = time.monotonic() + 15
                while True:
                    if process.poll() is not None:
                        raise RuntimeError('Owned server exited before readiness')
                    try:
                        ready = client.get('/health')
                        if ready.json() == {'status': 'ok'}:
                            break
                    except httpx.ConnectError:
                        if time.monotonic() > deadline:
                            raise RuntimeError('Server did not become ready') from None
                        time.sleep(0.1)
                runs = []
                for run in range(5):
                    latencies = []
                    errors = []
                    for i in range(20):
                        started = time.perf_counter()
                        response = client.post('/votes', json={'team': 'TABS'}, headers={'Authorization': f'Bearer local:run-{run}-{i}'})
                        latencies.append((time.perf_counter() - started) * 1000)
                        if response.status_code != 200:
                            errors.append({'index': i, 'status': response.status_code, 'body': response.text})
                    results = client.get('/results').json()
                    assert not errors and results['counts'] == {'TABS': (run + 1) * 20, 'SPACES': 0}, (errors, results)
                    runs.append({'requests': 20, 'errors': errors, 'latency_ms': latencies, 'counts': results['counts']})
                with closing(sqlite3.connect(db)) as connection:
                    rows = connection.execute('SELECT COUNT(*) FROM votes').fetchone()[0]
                assert rows == 100
                receipt = {'platform': platform.platform(), 'python': sys.version, 'httpx': httpx.__version__, 'mode': 'local SQLite and synthetic identity; not Google Cloud', 'doctor': ready.json(), 'action': 'five sequential batches of twenty distinct authenticated votes', 'runs': runs, 'durable_rows': rows, 'results': results}
                encoded = json.dumps(receipt, indent=2).encode()
                (evidence / 'http-proof.json').write_bytes(encoded)
                (evidence / 'http-proof.sha256').write_text(hashlib.sha256(encoded).hexdigest() + '  http-proof.json\n')
        finally:
            process.terminate()
            process.wait(timeout=10)
    assert (evidence / 'http-proof.json').exists()
    print('Doctor, drive, durable rows, evidence and cleanup passed:', evidence / 'http-proof.json')


if __name__ == '__main__':
    main()
