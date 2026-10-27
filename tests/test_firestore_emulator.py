"""Exercise real SDK calls only against the explicitly selected local emulator."""
import os
from concurrent.futures import ThreadPoolExecutor

import pytest
from google.api_core.exceptions import Aborted, DeadlineExceeded, RetryError, ServiceUnavailable
from google.cloud import firestore

from app import FirestoreStore, key


@pytest.mark.skipif(os.getenv('FIRESTORE_EMULATOR_HOST') != '127.0.0.1:18880', reason='requires isolated Firestore emulator')
def test_create_and_count_concurrency():
    db = firestore.Client(project='demo-voting')
    store = FirestoreStore(db)
    attempts = [('same', 'TABS' if i % 2 == 0 else 'SPACES') for i in range(16)]
    attempts += [(f'user-{i}', 'TABS' if i % 2 == 0 else 'SPACES') for i in range(40)]
    def attempt(pair):
        try:
            return store.cast(*pair)
        except (Aborted, DeadlineExceeded, RetryError, ServiceUnavailable) as exc:
            return type(exc).__name__
    with ThreadPoolExecutor(max_workers=8) as executor:
        outcomes = list(executor.map(attempt, attempts))
    errors = [(pair, result) for pair, result in zip(attempts, outcomes) if isinstance(result, str)]
    snapshot = db.collection('votes').document(key('same')).get()
    if not snapshot.exists:
        assert all(isinstance(result, str) for result in outcomes[:16])
        assert store.cast('same', 'TABS')
        snapshot = db.collection('votes').document(key('same')).get()
    winner = snapshot.to_dict()['team']
    assert all(result == (pair[1] == winner) for pair, result in zip(attempts[:16], outcomes[:16]) if not isinstance(result, str))
    assert all(result is True for result in outcomes[16:] if not isinstance(result, str))
    for pair, result in errors:
        assert store.cast(*pair) == (pair[0] != 'same' or pair[1] == winner)
    assert store.cast('same', winner)
    assert not store.cast('same', 'SPACES' if winner == 'TABS' else 'TABS')
    docs = list(db.collection('votes').stream())
    expected = {'TABS': 20 + (winner == 'TABS'), 'SPACES': 20 + (winner == 'SPACES')}
    assert len(docs) == 41
    assert {doc.id for doc in docs} == {key('same')} | {key(f'user-{i}') for i in range(40)}
    stored = {doc.id: doc.to_dict()['team'] for doc in docs}
    assert stored == {key('same'): winner, **{key(f'user-{i}'): 'TABS' if i % 2 == 0 else 'SPACES' for i in range(40)}}
    assert all(set(doc.to_dict()) == {'team', 'cast_at'} for doc in docs)
    result = store.results()
    assert result['counts'] == expected
    assert all(set(item) == {'team', 'cast_at'} for item in result['recent'])
    assert not list(db.collection('aggregates').stream())
    print({'same_uid_outcomes': outcomes[:16], 'winner': winner, 'distinct_outcomes': outcomes[16:], 'errors': errors, 'durable_rows': len(docs), 'counts': expected})
    db.close()
