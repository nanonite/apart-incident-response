"""Local research control panel. Run with PYTHONPATH=src python -m apart_incident_response.panel."""
import argparse
import io
import json
import mimetypes
import secrets
import threading
import uuid
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .analysis import analyze, summarize
from .events import EventStore
from .experiment import BatchRunner, validate_config
from .importing import import_jsonl
from .tasks import public_tasks

ROOT = Path(__file__).resolve().parents[2]


def state(store, selected=None):
    all_events = store.read()
    batches = []
    for batch_id in dict.fromkeys(e['batch_id'] for e in all_events):
        events = [e for e in all_events if e['batch_id'] == batch_id]
        batch, _ = summarize(events)
        if batch:
            batches.append(batch)
    selected = selected or (batches[-1]['id'] if batches else None)
    events = [e for e in all_events if e['batch_id'] == selected]
    batch, runs = summarize(events)
    metrics = analyze(events)
    by_difficulty = {}
    for row in metrics:
        key = str(row.get('difficulty'))
        by_difficulty.setdefault(key, {'difficulty': row.get('difficulty'), 'rows': 0, 'scores': [], 'entropy_bits': []})
        by_difficulty[key]['rows'] += 1
        if row.get('score') is not None:
            by_difficulty[key]['scores'].append(row['score'])
        if row.get('entropy_bits') is not None:
            by_difficulty[key]['entropy_bits'].append(row['entropy_bits'])
    for item in by_difficulty.values():
        item['accuracy'] = sum(item['scores']) / len(item['scores']) if item['scores'] else None
        item['mean_entropy_bits'] = sum(item['entropy_bits']) / len(item['entropy_bits']) if item['entropy_bits'] else None
        del item['scores']; del item['entropy_bits']
    return {'schema_version':'1.1', 'mode':'live', 'tasks':public_tasks(), 'batches':list(reversed(batches)),
            'batch':batch, 'runs':runs, 'events':events, 'metrics':metrics,
            'difficulty_metrics': sorted(by_difficulty.values(), key=lambda x: (x['difficulty'] is None, x['difficulty'])),
            'audit':research_actions(all_events)}


def report_markdown(data):
    batch = data.get('batch') or {}
    lines = [f"# Experiment report: {batch.get('id', 'unknown')}", '',
             f"Status: **{batch.get('status', 'unknown')}**", '',
             '| Difficulty | Rows | Accuracy | Mean answer-class entropy (bits) |',
             '|---:|---:|---:|---:|']
    for row in data.get('difficulty_metrics', []):
        acc = '' if row.get('accuracy') is None else f"{row['accuracy']:.3f}"
        ent = '' if row.get('mean_entropy_bits') is None else f"{row['mean_entropy_bits']:.3f}"
        lines.append(f"| {row.get('difficulty')} | {row.get('rows', 0)} | {acc} | {ent} |")
    warnings = [e for e in data.get('events', []) if e.get('kind') == 'minute_violation' or
                (e.get('kind') == 'task_update' and e.get('payload', {}).get('termination_state') == 'stalled_no_generation')]
    lines += ['', f"Warnings: **{len(warnings)}** minute violations or stalled submissions.",
              '', 'Metrics are derived from stored events and never fed back into a running agent.']
    return '\n'.join(lines) + '\n'


def responses(events):
    observations = {e['event_id']:e['payload'] for e in events if e['kind'] == 'agent_observation'}
    evaluations = {e['payload']['update_id']:e['payload'] for e in events if e['kind'] == 'evaluator_result'}
    for e in events:
        if e['kind'] == 'task_update':
            yield dict(e['payload'], event_id=e['event_id'], timestamp=e['timestamp'],
                       observation=observations.get(e['payload'].get('observation_id')),
                       evaluator=evaluations.get(e['event_id']))


def research_actions(events):
    """Audit trail: what a researcher did in the panel, in event order."""
    return [dict(e['payload'], seq=e['seq'], event_id=e['event_id'], batch_id=e['batch_id'],
                 timestamp=e['timestamp']) for e in events if e['kind'] == 'researcher_action']


def audit_action(store, batch_id, action, **detail):
    return store.append(batch_id or 'research', 'researcher_action', dict(action=action, **detail))


def projection_step(events, step, agent_order=('A', 'B')):
    """Global vs per-agent visibility at a discrete 0-based step, from stored records only.

    The global pane includes private evidence and evaluator truth that no agent ever sees.
    Each agent pane contains exactly the events the agent could have received
    (stored ``visible_event_ids``) plus its own records for that step.
    """
    global_up = [e for e in events if e['payload'].get('step') is None or e['payload']['step'] <= step]
    agents, communication = {}, {}
    for agent in agent_order:
        obs = next((e for e in events if e['kind'] == 'agent_observation'
                    and e['payload'].get('agent_id') == agent and e['payload'].get('step') == step), None)
        visible = set((obs or {}).get('payload', {}).get('visible_event_ids') or [])
        for e in events:
            if e['kind'] == 'task_update' and e['payload'].get('agent_id') == agent and e['payload'].get('step') == step:
                visible |= set(e['payload'].get('visible_event_ids') or [])
        agents[agent] = {'visible_event_ids': sorted(visible),
                         'visible_events': [e for e in global_up if e['event_id'] in visible],
                         'observation': obs['payload'] if obs else None}
        communication[agent] = bool(obs['payload'].get('communication_available')) if obs else None
    return {'step': step, 'minute': step + 1, 'global': global_up, 'agents': agents,
            'communication_available': communication,
            'note': 'Global includes private evidence and evaluator truth that no agent sees.',
            'source': 'stored_visible_event_ids'}


def bundle(data):
    output = io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        def jl(name, values):
            z.writestr(name, ''.join(json.dumps(v,ensure_ascii=False,allow_nan=False)+'\n' for v in values))
        jl('events.jsonl', data['events'])
        jl('responses.jsonl', responses(data['events']))
        jl('metrics.jsonl', data['metrics'])
        z.writestr('manifest.json', json.dumps({k:v for k,v in data.items() if k not in ('events','metrics','session_key')},ensure_ascii=False,indent=2))
        z.writestr('README.md', '''# Research handoff

Events are the researcher-visible ground truth. Each response links to its exact supplied observation, evaluator and source events. See manifest.json for protocol, configuration, model provenance, task definitions and completion status.

C0 is isolation; C1 shares previous-step responses; C2 unlocks earlier permitted responses at the configured step. Neither agent sees the other's current-step output. Private evidence and evaluator truth never enter shared history.

Sources: local_model/remote_model = actual inference; fixture = deterministic non-LLM plumbing data; imported = user-supplied, unverified provenance. Failed/incomplete records are not silently filled.

metrics.jsonl contains per-agent cross-run ANSWER-CLASS ENTROPY PROXIES in bits for the finite task options. It is NOT entailment-based semantic entropy and is not a causal metric. Fewer than two classified samples yields null, not zero. Repetitions and agents are not independent observations. Correctness scores assess the selected option, not the quality of the full explanation.

For semantic entropy, cluster response_text (or a versioned answer extraction) using an explicitly validated equivalence rule. Preserve source_event_ids and grouping scope. Different evolving histories are not identical fixed-checkpoint contexts. No analysis is fed back to the agents.

The university security task is synthetic static text. No real university website is accessed. The batch export's hash chain may start from an earlier event in another batch; verify against the full store for global continuity.
''')
    return output.getvalue()


class App:
    def __init__(self, store):
        self.store = store
        self.key = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.runner = None
        self.thread = None
        self.batch_id = None

    def launch(self, config):
        validate_config(config)
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError('A batch is already running')
            snapshot = state(self.store)
            if any(b['status'] == 'running' for b in snapshot['batches']):
                raise ValueError('A CLI or earlier batch is running; wait for its terminal event')
            self.runner = BatchRunner(self.store)
            self.batch_id = 'batch-' + uuid.uuid4().hex[:12]
            self.thread = threading.Thread(target=self.runner.run, args=(config, self.batch_id), daemon=True)
            self.thread.start()
            return self.batch_id


def serve(store, port):
    app = App(store)
    static = ROOT / 'dashboard' / 'dist'

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if args and isinstance(args[0], str) and '/api/state' in args[0]:
                return
            super().log_message(fmt, *args)

        def reply(self, status, body, kind='application/json', filename=None):
            if kind == 'application/json':
                body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'")
            if filename:
                self.send_header('Content-Disposition',f'attachment; filename="{filename}"')
            self.end_headers()
            self.wfile.write(body)

        def trusted_host(self):
            return self.headers.get('Host') in (f'localhost:{port}', f'127.0.0.1:{port}')

        def do_GET(self):
            if not self.trusted_host():
                return self.reply(403, {'error':'Local host required'})
            parsed = urlparse(self.path)
            selected = parse_qs(parsed.query).get('batch', [None])[0]
            if parsed.path == '/api/state':
                data = state(store, selected)
                data['session_key'] = app.key
                data['can_stop'] = bool(app.thread and app.thread.is_alive())
                return self.reply(200, data)
            if parsed.path == '/api/projections':
                try:
                    step = int(parse_qs(parsed.query).get('step', [''])[0])
                except ValueError:
                    return self.reply(400, {'error': 'step (0-based) is required'})
                run_id = parse_qs(parsed.query).get('run', [None])[0]
                events = state(store, selected)['events']
                if run_id:
                    events = [e for e in events if e.get('run_id') == run_id or not e.get('run_id')]
                return self.reply(200, projection_step(events, step))
            if parsed.path == '/api/audit':
                return self.reply(200, research_actions(state(store, selected)['events']))
            if parsed.path == '/api/task-pool':
                return self.reply(200, {'mode': 'read_only', 'tasks': public_tasks(),
                                        'message': 'Task editing is intentionally disabled for controlled runs.'})
            if parsed.path == '/api/report':
                data = state(store, selected)
                if not data['batch']:
                    return self.reply(404, {'error': 'Batch not found'})
                audit_action(store, data['batch']['id'], 'report_generated')
                return self.reply(200, report_markdown(data).encode(), 'text/markdown', 'experiment-report.md')
            if parsed.path == '/api/export':
                data = state(store, selected)
                if not data['batch']:
                    return self.reply(404, {'error':'Batch not found'})
                audit_action(store, data['batch']['id'], 'export_bundle', batches=1)
                return self.reply(200, bundle(data), 'application/zip','apart-research-bundle.zip')
            if parsed.path == '/api/responses':
                data = ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in responses(state(store,selected)['events'])).encode()
                return self.reply(200,data,'application/x-ndjson','responses.jsonl')
            path = (static / ('index.html' if parsed.path == '/' else parsed.path.lstrip('/'))).resolve()
            if static.resolve() not in path.parents or not path.is_file():
                return self.reply(404, {'error':'Not found'})
            return self.reply(200,path.read_bytes(),mimetypes.guess_type(str(path))[0] or 'application/octet-stream')

        def do_POST(self):
            origin = self.headers.get('Origin')
            if not self.trusted_host() or (origin and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}')) or self.headers.get('X-Session-Key') != app.key:
                return self.reply(403, {'error':'Use this panel from its local origin'})
            try:
                length = int(self.headers.get('Content-Length',0))
                if not 0 < length <= 10_000_000:
                    raise ValueError('Payload must be between 1 byte and 10 MB')
                if self.headers.get('Content-Type','').split(';')[0] != 'application/json':
                    raise ValueError('Use application/json')
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict):
                    raise ValueError('Request must be an object')
                if self.path == '/api/run':
                    batch_id = app.launch(body)
                    audit_action(store, batch_id, 'launch', conditions=body.get('conditions'),
                                 task_ids=body.get('task_ids'), adapter=body.get('adapter'),
                                 model=body.get('model'), steps=body.get('steps'),
                                 unlock_step=body.get('unlock_step'), repeats=body.get('repeats'),
                                 engagement_mode=body.get('engagement_mode'), study_id=body.get('study_id'))
                    return self.reply(202, {'batch_id': batch_id})
                if self.path == '/api/stop':
                    if not app.runner or not app.thread or not app.thread.is_alive():
                        raise ValueError('No panel-controlled batch is running')
                    app.runner.stop.set()
                    store.append(app.batch_id, 'stop_requested', {'policy':'stop before next request; retain in-flight result'})
                    audit_action(store, app.batch_id, 'stop_requested', policy='stop before next request')
                    return self.reply(200, {'status':'stopping_after_current_request'})
                if self.path == '/api/import':
                    batch_id = import_jsonl(store, body.get('jsonl'))
                    records = sum(1 for line in (body.get('jsonl') or '').splitlines() if line.strip())
                    audit_action(store, batch_id, 'import', records=records)
                    return self.reply(201, {'batch_id': batch_id})
                return self.reply(404, {'error':'Not found'})
            except (ValueError, TypeError) as exc:
                return self.reply(400, {'error':str(exc)})
            except Exception:
                return self.reply(500, {'error':'Server error; existing events remain preserved'})

    server = ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(f'Observatory ready: http://127.0.0.1:{port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        if app.runner:
            app.runner.stop.set()
    finally:
        server.server_close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default='artifacts/observatory.sqlite')
    p.add_argument('--port',type=int,default=8765)
    p.add_argument('--snapshot',help='Write a portable dashboard snapshot, without starting the server')
    p.add_argument('--batch')
    args=p.parse_args()
    store=EventStore(args.db)
    if args.snapshot:
        selected = args.batch
        audit_action(store, selected or 'snapshot', 'snapshot_written', path=args.snapshot)
        data=state(store,selected); data['mode']='snapshot'
        Path(args.snapshot).write_text(json.dumps(data,ensure_ascii=False,indent=2))
    else:
        serve(store,args.port)


if __name__ == '__main__':
    main()
