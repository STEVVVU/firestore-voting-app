"""HTTPX concurrency sample against the real local API and isolated SQLite adapter."""
import hashlib
import json
import os
import platform
import sqlite3
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

import httpx


def main():
    root = Path(__file__).resolve().parent
    output = root / 'evidence' / 'http-concurrency.json'
    output.parent.mkdir(exist_ok=True)
    receipt = {'platform': platform.platform(), 'processor': platform.processor(), 'cpu_count': os.cpu_count(), 'python': sys.version, 'httpx': httpx.__version__, 'workload': 'Five batches per concurrency; ten unique users per batch; each posts TABS, repeats TABS, then conflicts with SPACES.', 'mode': 'loopback Uvicorn, local synthetic identity and SQLite; not cloud', 'source_sha256': {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ('app.py', 'benchmark.py')}, 'runs': []}
    with tempfile.TemporaryDirectory() as scratch:
        db = Path(scratch) / 'votes.sqlite3'
        env = dict(os.environ, APP_ENV='local', VOTING_BACKEND='sqlite', IDENTITY_MODE='local', SQLITE_PATH=str(db))
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '18764'], cwd=root, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            deadline = time.monotonic() + 15
            while True:
                if process.poll() is not None:
                    raise RuntimeError('Server exited before readiness')
                try:
                    if httpx.get('http://127.0.0.1:18764/health').json() == {'status': 'ok'}:
                        break
                except httpx.ConnectError:
                    if time.monotonic() > deadline:
                        raise RuntimeError('Readiness timeout') from None
                    time.sleep(.1)
            def user(prefix, index):
                events = []
                with httpx.Client(base_url='http://127.0.0.1:18764', timeout=15) as client:
                    for team in ('TABS', 'TABS', 'SPACES'):
                        start = time.perf_counter()
                        try:
                            response = client.post('/votes', json={'team': team}, headers={'Authorization': f'Bearer local:{prefix}-{index}'})
                            events.append({'team': team, 'status': response.status_code, 'body': response.json(), 'latency_ms': (time.perf_counter() - start) * 1000})
                        except httpx.HTTPError as exc:
                            events.append({'team': team, 'error': type(exc).__name__, 'latency_ms': (time.perf_counter() - start) * 1000})
                return events
            expected = 0
            for concurrency in (1, 4):
                for run in range(5):
                    start = time.perf_counter()
                    with ThreadPoolExecutor(max_workers=concurrency) as pool:
                        events = list(pool.map(lambda i: user(f'{concurrency}-{run}', i), range(10)))
                    elapsed = (time.perf_counter() - start) * 1000
                    expected += 10
                    result = httpx.get('http://127.0.0.1:18764/results').json()
                    with closing(sqlite3.connect(db)) as conn:
                        rows = conn.execute('SELECT COUNT(*) FROM votes').fetchone()[0]
                    failures = [{'user': i, 'events': e} for i, e in enumerate(events) if [x.get('status') for x in e] != [200, 200, 409]]
                    receipt['runs'].append({'concurrency': concurrency, 'repeat': run + 1, 'elapsed_ms': elapsed, 'events': events, 'failures': failures, 'results_counts': result['counts'], 'durable_rows': rows, 'expected_rows': expected})
                    output.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
                    if failures or rows != expected or result['counts'] != {'TABS': expected, 'SPACES': 0}:
                        raise AssertionError('Oracle failed; partial receipt retained')
        finally:
            process.terminate()
            process.wait(timeout=10)
    (output.with_suffix('.sha256')).write_text(hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name + '\n')
    print('Ten runs completed; evidence:', output)


if __name__ == '__main__':
    main()
