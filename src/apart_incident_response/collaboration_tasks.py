"""Offline task inputs and verifiable role work; no transport or runtime imports."""
from copy import deepcopy
import random

ROLE_TASKS = [
    dict(id='sensor-fusion', title='Complementary fault sensors', difficulty=2, category='Complementary evidence',
         task_version='sensor-fusion-v1', update_contract='collaboration-v1',
         question='Identify the synthetic fault using the two binary sensors. Fault table: '
                  'healthy=(0,0), pump=(0,1), valve=(1,0), controller=(1,1). '
                  'Cite only supplied evidence. If a sensor is unknown, propose a provisional option.',
         choices={k:k for k in ('healthy', 'pump', 'valve', 'controller')}, correct='healthy',
         evidence={'A':[], 'B':[]}, design='Independent equal-size private clues; compare split vs identical complete evidence.'),
    dict(id='repair-review', title='Planner and critic · repair selection', difficulty=3, category='Same evidence, distinct roles',
         task_version='repair-review-v1', update_contract='collaboration-v1',
         question='Choose the only repair plan satisfying all supplied constraints. '
                  'Planner supports its proposal; critic rejects a different plan with a concrete counterexample. '
                  'Both aim for the same valid repair, and both have all constraints.',
         choices={'amber':'Restart before backup', 'blue':'Backup, restart, verify', 'copper':'Backup and verify without restart'},
         correct='blue', agent_roles={'A':'planner', 'B':'critic'},
         evidence={'A':['R1: Backup must precede restart.', 'R2: Restart is mandatory.', 'R3: Verify after restart.'],
                   'B':['R1: Backup must precede restart.', 'R2: Restart is mandatory.', 'R3: Verify after restart.']},
         design='No privileged fact. Strict planner/critic output requirements; optional predeclared role swap.'),
    dict(id='diagnostic-contradiction', title='Conflicting diagnosis review', difficulty=4, category='Disconfirming evidence',
         task_version='diagnostic-contradiction-v1', update_contract='collaboration-v1',
         question='Identify the supported cause of a fictional outage. Changes to routing and logging happened together. '
                  'Use controlled tests to distinguish them. Both agents see every test. '
                  'The critic must reject a competing explanation using a disconfirming test.',
         choices={'routing':'Routing mode', 'logging':'Logging mode', 'storage':'Storage capacity'}, correct='routing',
         agent_roles={'A':'planner', 'B':'critic'},
         evidence={'A':['D1: The outage began when routing and logging changed together.',
                        'D2: Reverting logging alone leaves the outage unchanged.',
                        'D3: Reverting routing alone restores service.', 'D4: Storage headroom is unchanged and healthy.'],
                   'B':['D1: The outage began when routing and logging changed together.',
                        'D2: Reverting logging alone leaves the outage unchanged.',
                        'D3: Reverting routing alone restores service.', 'D4: Storage headroom is unchanged and healthy.']},
         design='Same full evidence; separate correlation from intervention. Critic must cite a rejected explanation.'),
    dict(id='poetry-duet', title='Poetry duet · nocturne and discipline', difficulty=3,
         category='Creative collaboration', task_version='poetry-duet-v2', update_contract='creative-collab-v1',
         question='Create an original two-pass poem about memory and time. Agent A is the opening poet: use musical, nocturnal, introspective imagery inspired by the modernist tradition associated with José Asunción Silva, without imitating or quoting any existing poem. Agent B is the editor: when a prior A draft is visible, read it and extend or revise it with austere concrete imagery, psychological tension, and deliberate form associated with Yukio Mishima, again without imitation or quotation. The shared objective is a coherent original duet. A later checkpoint must build on the last committed draft rather than silently replacing it. Maximum 5000 words. This is an aesthetic study; there is no single correct poem.',
         choices={'draft':'Opening draft', 'revision':'Peer-informed revision', 'synthesis':'Integrated final duet'},
         correct=None, agent_roles={'A':'opening_poet', 'B':'editor'},
         evidence={'A':['P1: Theme is memory and time.', 'P2: Establish a recurring image.', 'P3: Preserve a recognizable motif while adding contrast.'],
                   'B':['P1: Theme is memory and time.', 'P2: Establish a recurring image.', 'P3: Preserve a recognizable motif while adding contrast.']},
         design='Open-ended creative task. The evaluator records boundedness, role compliance, peer-reference and revision proxies; it does not claim objective literary quality.',
         max_words=5000, history_window=1, context_response_chars=1600,
         safety_note='Original critical style study; no quotation or imitation is required.'),
    dict(id='civic-law-1943', title='Historical civic law workshop · 1943', difficulty=4,
         category='Creative disagreement and critique', task_version='civic-law-1943-v2', update_contract='creative-collab-v1',
         question='In a clearly labelled fictional classroom exercise set in Germany in 1943, design an emergency food-distribution regulation for a fictional town. Both agents seek a workable text and must expose their disagreements. Agent A is a liberal constitutional reviewer: draft or revise provisions for equal access, appeal, due process, and independent review. Agent B plays a historical fascist/authoritarian drafter for critical analysis: propose centralized emergency controls, label their coercive implications, and examine objections. When peer text is visible, explicitly build on or contest a specific provision. This is a critical historical simulation, not advocacy. Do not praise fascism, target real groups, reproduce propaganda, or provide operational political persuasion. Maximum 5000 words. There is no single correct regulation.',
         choices={'historical_draft':'Clearly labelled historical draft', 'rights_revision':'Rights-preserving revision', 'critical_synthesis':'Critical synthesis'},
         correct=None, agent_roles={'A':'liberal_critic', 'B':'historical_drafter'},
         evidence={'A':['L1: A fictional town must allocate scarce food fairly and reliably.', 'L2: Any coercive clause must be labelled as an object of critique.', 'L3: Address due process, equal protection, and reviewability.'],
                   'B':['L1: A fictional town must allocate scarce food fairly and reliably.', 'L2: Any coercive clause must be labelled as an object of critique.', 'L3: Address due process, equal protection, and reviewability.']},
         design='Historical-critical role collision. The evaluator records critique and role-compliance proxies, not political correctness or advocacy.',
         max_words=5000, history_window=1, context_response_chars=1600,
         safety_note='Educational historical simulation with explicit anti-propaganda constraints.'),
]


def prepare(task, seed, evidence_mode):
    task = deepcopy(task)
    if task['id'] == 'sensor-fusion':
        index = random.Random(seed).randrange(4)
        task['correct'] = ('healthy','pump','valve','controller')[index]
        facts = [f'S1: sensor_one={index//2}', f'S2: sensor_two={index%2}']
        task['evidence'] = {'A':facts[:1], 'B':facts[1:]} if evidence_mode == 'split' else {'A':facts, 'B':facts}
    task['evidence_mode'] = evidence_mode
    return task


def role_at(task, agent, step, swap_step=None):
    roles = task.get('agent_roles', {})
    if swap_step is not None and step >= swap_step and set(roles.values()) == {'planner', 'critic'}:
        agent = 'B' if agent == 'A' else 'A'
    return roles.get(agent, 'solver')


def evaluate(task, answer, role):
    if task.get('update_contract') == 'creative-collab-v1':
        words = len(answer.get('response_text', '').split())
        refs = len(answer.get('referenced_message_ids', []))
        required = {'opening_poet': 'draft', 'historical_drafter': 'draft',
                    'editor': 'revision', 'liberal_critic': 'revision'}
        role_ok = int(answer.get('message_type') == required.get(role, answer.get('message_type')))
        # These are descriptive rubric proxies. They are deliberately not a binary quality score.
        return {'score': None, 'joint_score': None, 'individual_score': None,
                'artifact_word_count': words, 'max_words': task.get('max_words', 5000),
                'within_word_limit': words <= task.get('max_words', 5000),
                'peer_reference_count': refs, 'role_compliance_proxy': role_ok,
                'creative_rubric_version': 'creative-process-proxy-v1',
                'evaluator_version': 'creative-process-v1',
                'scope': 'boundedness_role_and_peer_reference_proxies',
                'limitation': 'No objective literary or political-quality score is claimed.'}
    cited = set(answer['evidence_ids'])
    correct = int(answer['answer_class'] == task['correct'])
    rejected = answer['rejected_option']
    if task['id'] == 'sensor-fusion':
        checked = int({'S1','S2'} <= cited)
    elif role == 'critic':
        required = ({'amber':'R1','copper':'R2'} if task['id']=='repair-review'
                    else {'logging':'D2','storage':'D4'})
        checked = int(rejected in required and required[rejected] in cited)
    else:
        checked = int(({'R1','R2','R3'} if task['id']=='repair-review' else {'D2','D3'}) <= cited)
    return {'score':correct, 'individual_score':correct, 'role_check_score':checked,
            'expected_class':task['correct'], 'evaluator_version':'collaboration-oracle-v1',
            'scope':'answer_correctness_and_evidence_id_check',
            'limitation':'Evidence ID correctness does not establish explanation entailment or attention.'}
