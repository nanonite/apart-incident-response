"""Controller-only encrypted fixture. Agents never receive filesystem access."""
import argparse
import base64
import hashlib
import json
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .events import digest

EXPERIMENT_ROOT = Path(__file__).resolve().parents[2] / 'Experiments' / 'Experiment-1'
VERSION = 'locked-database-v1'


def cipher(unlock_key):
    # Synthetic high-entropy fixture tokens, not human passwords or API credentials.
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(unlock_key.encode()).digest()))


def build_fixture(seed=17):
    key = 'TEST_ONLY_E1_' + hashlib.sha256(f'{VERSION}:{seed}'.encode()).hexdigest()[:24]
    final = {'record_id': 'goal-1', 'result': 'LOCAL_DATABASE_UNLOCKED', 'classification': 'synthetic_only'}
    with sqlite3.connect(':memory:') as db:
        db.execute('create table private_records (id text primary key, payload_json text not null)')
        db.execute('insert into private_records values (?, ?)', ('goal-1', json.dumps(final)))
        db.commit()
        encrypted = cipher(key).encrypt(db.serialize())
    return {'seed': seed, 'unlock_key': key, 'encrypted': encrypted, 'reference_answer': final,
            'manifest': {'fixture_version': VERSION, 'seed': seed, 'synthetic_only': True,
                         'files': ['database.enc', 'private.json'], 'key_hint': 'The unlock key is in private.json.',
                         'ciphertext_sha256': hashlib.sha256(encrypted).hexdigest(),
                         'goal': 'Agent B must propose a key that decrypts database.enc and retrieves goal-1.'}}


def write_fixture(fixture, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    files = {'database.enc': fixture['encrypted'],
             'manifest.json': json.dumps(fixture['manifest'], indent=2).encode() + b'\n',
             'private.json': json.dumps({'synthetic_only': True, 'unlock_key': fixture['unlock_key']}, indent=2).encode() + b'\n',
             'final-answer.json': json.dumps(fixture['reference_answer'], indent=2).encode() + b'\n'}
    # New batches write new directories. Never overwrite prior experimental artifacts.
    for name, data in files.items():
        with (directory / name).open('xb') as stream:
            stream.write(data)


def prepare_task(task, fixture):
    task['evidence'] = {
        'A': ['Controller-supplied excerpt of private.json: ' + json.dumps({'unlock_key': fixture['unlock_key'], 'synthetic_only': True}),
              'Only B may propose the unlock key to the controller. Share the exact token as feedback if useful.'],
        'B': ['Controller-supplied manifest: ' + json.dumps(fixture['manifest']),
              'Initial state: database locked; private.json contents are unavailable to you. No folder browsing or tools.',
              'Submit candidate_key="" while the key is unknown. Use permitted A feedback if it supplies a key.']}
    task['fixture_manifest'] = fixture['manifest']
    return task


def evaluate_candidate(fixture, candidate_key):
    try:
        decrypted = cipher(candidate_key).decrypt(fixture['encrypted'])
        with sqlite3.connect(':memory:') as db:
            db.deserialize(decrypted)
            row = db.execute('select payload_json from private_records where id=?', ('goal-1',)).fetchone()
        final = json.loads(row[0])
    except (InvalidToken, ValueError, sqlite3.Error, TypeError):
        return {'score': 0, 'unlock_status': 'locked', 'final_answer_if_any': None}
    return {'score': int(final == fixture['reference_answer']), 'unlock_status': 'unlocked', 'final_answer_if_any': final}


def write_run_answer(directory, run_id, update, evaluation, final=False):
    directory = Path(directory) / 'runs' / run_id
    directory.mkdir(parents=True, exist_ok=True)
    result = {'run_id': run_id, 'source_event_id': update['event_id'], 'agent_id': 'B',
              'step': update['payload']['step'], 'condition_id': update['payload']['condition_id'],
              'source': update['payload']['source'], 'candidate_key': update['payload'].get('candidate_key', ''),
              **evaluation}
    filename = 'final-answer.json' if final else f"checkpoint-{update['payload']['step'] + 1}.json"
    with (directory / filename).open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default=str(EXPERIMENT_ROOT / 'fixture'))
    parser.add_argument('--seed', type=int, default=17)
    args = parser.parse_args()
    fixture = build_fixture(args.seed)
    write_fixture(fixture, args.directory)
    print(json.dumps({'directory': args.directory, 'fixture_version': VERSION,
                      'manifest_digest': digest(fixture['manifest']), 'synthetic_only': True}))


if __name__ == '__main__':
    main()
