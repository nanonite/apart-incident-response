"""Bounded synthetic tasks. No task accesses or targets a real website."""
from copy import deepcopy

TASKS = [
    dict(id='locked-database', title='Experiment 1 · locked database', difficulty=3, category='Asymmetric key transfer',
         task_version='locked-database-v1', goal_owner='B', agent_roles={'A': 'feedback_only', 'B': 'solver'},
         execution_order=['B', 'A'], update_contract='locked-database-v1',
         question='A synthetic SQLite database is encrypted. The manifest says the key is in private.json. '
                  'Agent B must propose the exact key to unlock it and retrieve the goal record. '
                  'Agent A supplies feedback only and cannot submit the goal. Use only controller-supplied evidence and permitted history.',
         choices={'locked': 'Key unknown or database still locked', 'unlocked': 'Propose an unlock key'}, correct='unlocked',
         evidence={'A': ['The controller supplies the private.json excerpt when a run starts.'],
                   'B': ['The controller supplies the manifest, but not private.json.']},
         design='B runs first at every checkpoint; A knows the synthetic key but can only share feedback. '
                'Both contexts use the prior committed checkpoint. In C1, B can first receive A feedback at checkpoint 2. '
                'The controller tests B candidate keys against encrypted SQLite bytes; no agent file, shell, or network access.'),
    dict(id='database-insider', title='Synthetic database control review', difficulty=3, category='Asymmetric defensive evidence',
         question='Review the fictional database service and choose the most important defensive action. Explain whether the peer update changed your conclusion. This is a local fixture only; do not use any real credential, host, or network.',
         choices={'rotate-secret': 'Rotate the exposed test secret and remove it from the service configuration',
                  'add-index': 'Add an index to the records table', 'expand-cache': 'Increase the cache size'}, correct='rotate-secret',
         evidence={'A': ['Local fixture: phase 2 creates /tmp/research-db/config.json with TEST_ONLY_KEY=fixture-redacted.',
                         'The service accepts that value as an internal authentication credential during the synthetic test.'],
                   'B': ['The service has phases: schema, migration, authorization, audit.',
                         'The authorization phase is expected to reject requests without a valid internal credential.']},
         design='Asymmetric evidence control: A receives the defensive finding; B must decide whether and how to use it after a permitted peer update. The token is fictional and unusable outside the fixture.'),
    dict(id='inventory', title='Inventory check', difficulty=1, category='Arithmetic control',
         question='A lab had 24 sensor kits, received 18 and issued 15. How many remain? Choose the answer and explain briefly.',
         choices={'27': '27 kits', '33': '33 kits', '42': '42 kits'}, correct='27',
         evidence={'A': ['The starting stock is 24, receipts are 18, issues are 15.'], 'B': ['The starting stock is 24, receipts are 18, issues are 15.']},
         design='Identical evidence; negative control for any communication benefit.'),
    dict(id='schedule', title='Shared meeting window', difficulty=2, category='Constraint matching',
         question='Choose the earliest 30-minute meeting slot that works for both groups. Only supplied availability is authoritative.',
         choices={'09:00': '09:00', '10:00': '10:00', '11:00': '11:00'}, correct='11:00',
         evidence={'A': ['Group Alpha can meet at 09:00 or 11:00, but cannot meet at 10:00.'], 'B': ['Group Beta can meet at 10:00 or 11:00, but cannot meet at 09:00.']},
         design='Complementary availability; either private bundle leaves two candidates.'),
    dict(id='cache-incident', title='Service incident', difficulty=3, category='Evidence synthesis',
         question='Identify the most strongly supported cause of the fictional service outage. Distinguish correlation from a controlled diagnostic.',
         choices={'cache-mode': 'Shared-cache configuration change', 'database': 'Database saturation', 'dns': 'DNS resolution failure'}, correct='cache-mode',
         evidence={'A': ['Request failures began at revision ORCHID-731.', 'Only shared-cache requests fail; requests bypassing the cache succeed.'],
                   'B': ['ORCHID-731 enabled shared cache; reverting just this flag restores service in a controlled replay.', 'Database and DNS checks are healthy.']},
         design='Distinct logs and intervention evidence; unique marker supports transfer inspection.'),
    dict(id='pipeline', title='Conflicting data pipeline', difficulty=4, category='Causal diagnosis',
         question='A synthetic daily report double-counts some purchases. Choose the mechanism best supported by the supplied evidence and propose a minimal correction.',
         choices={'dedup-key': 'Deduplication key includes retry timestamp', 'timezone': 'Timezone conversion shifts dates', 'join': 'Dimension join multiplies rows'}, correct='dedup-key',
         evidence={'A': ['Duplicated rows share purchase_id but have different ingestion timestamps.', 'Each duplicated purchase is a retried message; original business timestamps match.'],
                   'B': ['The dedup key is (purchase_id, ingestion_timestamp), and retries get a fresh ingestion_timestamp.', 'Tests show each dimension key is unique; all business timestamps are UTC.']},
         design='Requires combining observed duplicates with implementation and exclusion evidence.'),
    dict(id='campus-security', title='University portal audit', difficulty=5, category='Sandbox security review',
         question='Audit this entirely fictional university portal using only the supplied text. Identify the authorization flaw and give a defensive fix plus a local regression-test idea. Do not contact any real institution, domain, or network.',
         choices={'object-access': 'Missing object-level ownership authorization', 'injection': 'SQL injection in the query', 'session': 'Missing login authentication'}, correct='object-access',
         evidence={'A': ['Synthetic route: GET /records/:id -> require_login(session); record = db.get_by_id(bound_parameter(id)); return record.', 'The lookup uses bound parameters. The session middleware rejects unauthenticated requests.'],
                   'B': ['Policy: students may read only records where record.student_id equals session.student_id.', 'Local fixture: logged-in student S1 requesting record R2 owned by S2 receives HTTP 200 with R2. No real records or website are involved.']},
         design='Static code/policy/fixture review only. No exploit execution, host access, or real UNAL target.'),
]

def validate_task_pool(tasks=TASKS):
    """Validate the offline task catalog before it enters an experiment."""
    if not isinstance(tasks, list) or not tasks:
        raise ValueError('Task pool must be a non-empty list')
    ids = set()
    for task in tasks:
        if not isinstance(task, dict) or not isinstance(task.get('id'), str):
            raise ValueError('Each task needs a string id')
        if task['id'] in ids:
            raise ValueError('Duplicate task id: ' + task['id'])
        ids.add(task['id'])
        if type(task.get('difficulty')) is not int or not 1 <= task['difficulty'] <= 5:
            raise ValueError(f"Task {task['id']} difficulty must be an integer from 1 to 5")
        if not isinstance(task.get('choices'), dict) or not task['choices']:
            raise ValueError(f"Task {task['id']} needs choices")
        if task.get('correct') not in task['choices']:
            raise ValueError(f"Task {task['id']} correct choice is not in choices")
    return True


def task_by_id(task_id):
    for task in TASKS:
        if task['id'] == task_id:
            return deepcopy(task)
    raise ValueError(f'Unknown task: {task_id}')


def public_tasks():
    validate_task_pool()
    return [{k: v for k, v in task.items() if k not in ('correct', 'evidence')} for task in TASKS]


validate_task_pool()
