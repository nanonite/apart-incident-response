"""Offline, provenance-preserving creative-study analysis of exported events.

No agent adapters, experiment execution, or database access. Metrics operate on
stored provider probabilities, one token position at a time. Charts never imply
that predictive token uncertainty is artistic quality or semantic entropy.
"""
import argparse
from collections import Counter, defaultdict
import csv
import gzip
import hashlib
import html
import json
import math
from pathlib import Path
import random
import re
import statistics
import zipfile

from .analysis import analyze, checkpoint_grid, intervention_changes
from .probability_artifacts import normalize_token_probability, ProbabilityArtifactError

VERSION = 'creative-export-analysis-v1'
COLORS = {'C0': '#2266ad', 'C1': '#15856b', 'C2': '#d55e00'}
METRIC_CATALOG = [
    dict(metric='artifact_h_renorm_bits', unit='bits/token', definition='Mean positional Shannon entropy on normalized reported token support inside response_text', limitation='Truncated support; evolving contexts; not semantic entropy'),
    dict(metric='artifact_h_lower_bits', unit='bits/token', definition='Mean positional truncated -sum(p log2 p)', limitation='Unreported vocabulary mass omitted'),
    dict(metric='artifact_h_residual_bucket_bits', unit='bits/token', definition='Mean positional entropy with all unreported mass in one residual bucket', limitation='Residual words are collapsed into one outcome'),
    dict(metric='artifact_coverage', unit='probability mass', definition='Mean sampled-and-reported deduplicated token probability mass', limitation='Provider and decoding dependent'),
    dict(metric='reference_given_delivery', unit='binary/update', definition='Valid update cites at least one actually delivered peer source ID', limitation='Reference proxy; does not prove reading, useful transfer, or causality'),
    dict(metric='own_lexical_distance', unit='Jaccard distance', definition='Word-set distance to own previous valid artifact', limitation='Lexical trajectory proxy; not semantic distance'),
    dict(metric='difference_in_changes_bits', unit='bits/token', definition='Complete-run C2 post-minus-pre minus matched C0 post-minus-pre', limitation='Descriptive contrast; no randomized causal estimate or quality judgment'),
    dict(metric='partial_difference_in_changes_bits', unit='bits/token', definition='Same contrast using only available valid, measured artifacts', limitation='Selection bias from rejected/missing updates; diagnostic only'),
]


def average(values):
    finite = [v for v in values if v is not None and math.isfinite(v)]
    return statistics.mean(finite) if finite else None


def lexical_distance(left, right):
    """Word-set Jaccard distance: a lexical proxy, never semantic or causal."""
    a, b = (set(re.findall(r'\w+', s.lower())) for s in (left, right))
    return 1 - len(a & b) / len(a | b) if a | b else None


def token_measurement(entry):
    record = {'token': entry.get('token'), 'logprob': entry.get('logprob'),
              'top_logprobs': entry.get('top') or entry.get('top_logprobs') or []}
    normalized = normalize_token_probability(record)
    probabilities = [normalized['sampled_probability']] + [x['probability'] for x in normalized['top_alternatives']]
    coverage = normalized['covered_mass']
    lower = -sum(p * math.log2(p) for p in probabilities if p > 0)
    renorm = lower / coverage + math.log2(coverage)
    residual = 1 - coverage
    block = lower - (residual * math.log2(residual) if residual > 0 else 0)
    error = max(abs(renorm - normalized['entropy']['partial_entropy_bits']),
                abs(block - normalized['entropy']['residual_bucket_entropy_bits']))
    top = record['top_logprobs']
    return dict(h_lower_bits=lower, h_renorm_bits=renorm, h_residual_bucket_bits=block,
                coverage=coverage, surprise_bits=normalized['entropy']['sampled_surprise_bits'],
                sampled_in_top=any(t.get('token') == record['token'] for t in top),
                unique_support=len(probabilities), recomputation_error=error)


def artifact_token_indices(raw, entries):
    """Include only tokens wholly inside the raw JSON response_text string.

    No first-token approximation. If bytes cannot reconstruct the actual output,
    artifact-specific measurements remain unknown; whole-JSON metrics may exist.
    """
    pieces = []
    for entry in entries:
        value = entry.get('bytes')
        try:
            piece = bytes(value) if isinstance(value, list) else entry['token'].encode('utf-8')
        except (ValueError, TypeError, KeyError, AttributeError):
            return set(), 'unavailable_token_alignment'
        pieces.append(piece)
    raw_bytes = raw.encode('utf-8')
    if b''.join(pieces) != raw_bytes:
        return set(), 'unavailable_token_alignment'
    match = re.search(rb'"response_text"\s*:\s*"((?:[^"\\]|\\.)*)"', raw_bytes)
    if not match:
        return set(), 'unavailable_response_text_span'
    start, stop = match.span(1)
    indices, offset = set(), 0
    for index, piece in enumerate(pieces):
        end = offset + len(piece)
        if offset >= start and end <= stop and end > offset:
            indices.add(index)
        offset = end
    return indices, 'aligned_response_text_value'


def validate_hash_chain(events):
    previous = None
    errors = []
    for event in events:
        if 'hash' not in event or 'previous_hash' not in event:
            errors.append({'event_id': event.get('event_id'), 'error': 'missing_hash'})
            continue
        payload = {k: v for k, v in event.items() if k not in ('seq', 'hash', 'previous_hash')}
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
        expected = hashlib.sha256((event['previous_hash'] + encoded).encode()).hexdigest()
        if expected != event['hash'] or previous is not None and event['previous_hash'] != previous:
            errors.append({'event_id': event['event_id'], 'error': 'hash_mismatch_or_gap'})
        previous = event['hash']
    return {'checked_events': len(events), 'errors': errors,
            'status': 'verified_export_segment' if not errors else 'failed',
            'scope': 'segment_integrity_only; first predecessor may belong to another batch'}


def analyze_events(events):
    by_id = {e['event_id']: e for e in events}
    batches = {e['batch_id']: e['payload'] for e in events if e['kind'] == 'batch_started'}
    runs = {e['run_id']: e['payload'] for e in events if e['kind'] == 'run_started'}
    finished = {e['run_id']: e['payload'] for e in events if e['kind'] == 'run_finished'}
    rows, tokens = [], []
    valid_text = {}
    for event in events:
        if event['kind'] != 'task_update':
            continue
        p = event['payload']; run = runs[event['run_id']]; batch = batches[event['batch_id']]
        cfg = batch['config']; obs = by_id.get(p.get('observation_id'), {}).get('payload', {})
        generation = by_id.get(p.get('attempt_event_id'), {}).get('payload', {})
        entries = generation.get('logprobs') or []
        indices, alignment = artifact_token_indices(generation.get('raw_response', ''), entries) if entries else (set(), 'probabilities_unavailable')
        provenance = dict(batch_id=event['batch_id'], run_id=event['run_id'],
                          task_id=p['task_id'], task_version=run['task_version'], condition=p['condition_id'],
                          repeat=p['repeat'], seed=run['seed'], step=p['step'], checkpoint=p['step'] + 1,
                          inferred_call_seed=run['seed']+p['step']*2+(p['agent_id']=='B'),
                          call_seed_rule='response_dynamics_v1:run_seed+2*step+(agent_is_B)',
                          agent_id=p['agent_id'], agent_role=p.get('agent_role'), model=p['model'],
                          model_digest=p.get('model_metadata', {}).get('digest'), source=p['source'],
                          prompt_version=p['prompt_version'], config_hash=batch['config_hash'],
                          context_hash=obs.get('context_hash'), source_event_id=event['event_id'],
                          generation_event_id=p.get('attempt_event_id'), observation_id=p.get('observation_id'))
        measured, artifact_measured = [], []
        for index, entry in enumerate(entries):
            try:
                metric = token_measurement(entry)
                token = dict(source_event_id=event['event_id'], generation_event_id=p.get('attempt_event_id'), token_index=index, token=entry.get('token'),
                             scope='artifact' if index in indices else 'json_structure_or_other', status='valid', **metric)
                measured.append(metric)
                if index in indices:
                    artifact_measured.append(metric)
            except (ProbabilityArtifactError, TypeError, ValueError) as exc:
                token = dict(source_event_id=event['event_id'], generation_event_id=p.get('attempt_event_id'), token_index=index, token=entry.get('token'),
                             scope='artifact' if index in indices else 'json_structure_or_other', status='invalid', error=str(exc))
            tokens.append(token)
        text = p.get('response_text', '')
        try:
            generated_text = json.loads(generation.get('raw_response', '')).get('response_text')
        except (ValueError, AttributeError):
            generated_text = None
        valid = p.get('termination_state') == 'checkpoint_update' and bool(text.strip())
        # The current runner uses checkpoint_update for valid updates; imports can differ and
        # remain in the grid without being silently promoted to valid model evidence.
        key = (event['run_id'], p['agent_id'])
        own_previous = valid_text.get(key)
        content = json.loads(obs['messages'][-1]['content']) if obs.get('messages') else {}
        peers = [h for h in content.get('permitted_history', []) if h.get('agent') != p['agent_id']]
        peer_ids = list(obs.get('visible_message_ids') or [])
        references = p.get('referenced_message_ids') or []
        checked_refs = [i for i in references if i in peer_ids]
        row = dict(provenance, status='valid' if valid else 'stalled_or_invalid',
                   submission_state='valid' if valid else ('rejected_generated_output' if generation.get('raw_response','').strip() else 'stalled_no_generation'),
                   run_status=finished.get(event['run_id'], {}).get('status', 'missing_terminal'),
                   response_text=text, generated_response_text=generated_text,
                   rejection_reason=None if valid else p.get('done_reason'),
                   answer_class=p.get('answer_class'), words=len(text.split()),
                   latency_seconds=(p.get('latency_ms') or 0)/1000, input_tokens=p.get('token_counts', {}).get('input'),
                   output_tokens=p.get('token_counts', {}).get('output'), context_bytes=obs.get('context_bytes'),
                   planned_checkpoints=cfg['steps'], unlock_step=cfg['unlock_step'], communication_available=bool(obs.get('communication_available')),
                   delivered_message_count=len(peer_ids), checked_reference_count=len(checked_refs),
                   reference_given_delivery=int(bool(checked_refs)) if peer_ids and valid else None,
                   own_lexical_distance=lexical_distance(own_previous, text) if own_previous and valid else None,
                   peer_lexical_distance=lexical_distance(peers[-1]['response_text'], text) if peers and valid else None,
                   token_count=len(entries), validated_token_count=len(measured), artifact_token_count=len(artifact_measured),
                   token_alignment=alignment, invalid_probability_count=len(entries)-len(measured),
                   artifact_h_lower_bits=average([t['h_lower_bits'] for t in artifact_measured]),
                   artifact_h_renorm_bits=average([t['h_renorm_bits'] for t in artifact_measured]),
                   artifact_h_residual_bucket_bits=average([t['h_residual_bucket_bits'] for t in artifact_measured]),
                   artifact_coverage=average([t['coverage'] for t in artifact_measured]),
                   whole_json_h_renorm_bits=average([t['h_renorm_bits'] for t in measured]),
                   probability_status=('partial_invalid' if len(measured) < len(entries) else 'available') if artifact_measured else 'unavailable',
                   measurement_version=VERSION, semantic_entropy_status='not_computed', causal_claim=False)
        if valid:
            valid_text[key] = text
        rows.append(row)
    groups = defaultdict(list)
    for row in rows:
        groups[(row['batch_id'], row['config_hash'], row['task_id'], row['task_version'], row['model'], row['model_digest'], row['agent_role'], row['agent_id'], row['repeat'])].append(row)
    contrasts = []
    for key, group in groups.items():
        arms = {c: [r for r in group if r['condition'] == c] for c in ('C0', 'C2')}
        item = dict(zip(('batch_id','config_hash','task_id','task_version','model','model_digest','agent_role','agent_id','repeat'), key))
        sources = []
        for condition, arm in arms.items():
            pre = [r for r in arm if r['step'] < r['unlock_step']]
            post = [r for r in arm if r['step'] >= r['unlock_step']]
            complete = bool(arm) and len(arm)==arm[0]['planned_checkpoints'] and {r['step'] for r in arm}==set(range(arm[0]['planned_checkpoints'])) and all(r['run_status'] == 'completed' and r['status'] == 'valid' for r in arm)
            sufficient = complete and bool(pre and post) and all(r['artifact_h_renorm_bits'] is not None and r['probability_status']=='available' for r in arm)
            before = average([r['artifact_h_renorm_bits'] for r in pre]) if sufficient else None
            after = average([r['artifact_h_renorm_bits'] for r in post]) if sufficient else None
            item.update({condition+'_pre_bits': before, condition+'_post_bits': after,
                         condition+'_delta_bits': after-before if sufficient else None})
            measured_pre = [r for r in pre if r['status']=='valid' and r['artifact_h_renorm_bits'] is not None and r['probability_status']=='available']
            measured_post = [r for r in post if r['status']=='valid' and r['artifact_h_renorm_bits'] is not None and r['probability_status']=='available']
            partial_before = average([r['artifact_h_renorm_bits'] for r in measured_pre])
            partial_after = average([r['artifact_h_renorm_bits'] for r in measured_post])
            item.update({condition+'_measured_pre_count': len(measured_pre), condition+'_measured_post_count': len(measured_post),
                         condition+'_partial_delta_bits': partial_after-partial_before if measured_pre and measured_post else None})
            sources += [r['source_event_id'] for r in arm]
        left, right = item['C2_delta_bits'], item['C0_delta_bits']
        item.update(difference_in_changes_bits=left-right if left is not None and right is not None else None,
                    source_event_ids=sources, causal_claim=False, scope='paired_descriptive_pre_post_contrast')
        partial_left, partial_right = item['C2_partial_delta_bits'], item['C0_partial_delta_bits']
        item['partial_difference_in_changes_bits'] = partial_left-partial_right if partial_left is not None and partial_right is not None else None
        contrasts.append(item)
    return rows, tokens, contrasts


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with (gzip.open(path,'wt',newline='',encoding='utf-8') if path.suffix=='.gz' else path.open('w', newline='', encoding='utf-8')) as f:
        writer = csv.DictWriter(f, fieldnames=fields or ['status'])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict,list)) else v for k,v in row.items()})


def plot_results(rows, output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.size': 10, 'axes.spines.top': False, 'axes.spines.right': False})
    tasks = sorted({r['task_id'] for r in rows})
    specifications = [('entropy', 'artifact_h_renorm_bits', 'Reported-support token entropy (bits)'),
                      ('coverage', 'artifact_coverage', 'Reported token probability mass'),
                      ('references', 'reference_given_delivery', 'Explicit reference / delivered response'),
                      ('latency', 'latency_seconds', 'Generation latency (seconds)'),
                      ('trajectory', 'own_lexical_distance', 'Within-agent lexical Jaccard distance (proxy)')]
    names = []
    for name, metric, ylabel in specifications:
        fig, axes = plt.subplots(max(len(tasks),1),2,figsize=(11,3.8*max(len(tasks),1)),squeeze=False)
        for ti, task in enumerate(tasks):
            for ai, agent in enumerate(('A','B')):
                ax = axes[ti,ai]
                sub = [r for r in rows if r['task_id'] == task and r['agent_id'] == agent]
                role = sub[0]['agent_role'] if sub else ''
                for condition in sorted({r['condition'] for r in sub}):
                    x, y, lo, hi = [], [], [], []
                    for step in sorted({r['step'] for r in sub}):
                        values = [r[metric] for r in sub if r['condition']==condition and r['step']==step and r[metric] is not None and r['status']=='valid']
                        x.append(step+1); y.append(average(values) if values else math.nan)
                        lo.append(min(values) if values else math.nan); hi.append(max(values) if values else math.nan)
                    if any(math.isfinite(v) for v in y):
                        ax.plot(x,y,'o-',color=COLORS.get(condition,'grey'),label=condition)
                        ax.fill_between(x,lo,hi,color=COLORS.get(condition,'grey'),alpha=.12)
                if sub:
                    ax.axvline(sub[0]['unlock_step']+.5,color='#666',linestyle='--',label='C2 unlock')
                    ax.set_xticks(sorted({r['checkpoint'] for r in sub}))
                if not any(r['status']=='valid' and r[metric] is not None for r in sub):
                    ax.text(.5,.5,'Not estimable from captured data',ha='center',transform=ax.transAxes)
                ax.set(title=f'{task} · {agent} ({role})',xlabel='Logical checkpoint',ylabel=ylabel)
                ax.grid(alpha=.2)
                handles, labels = ax.get_legend_handles_labels()
                if handles: ax.legend(handles,labels,fontsize=8)
        fig.suptitle('Exploratory pilot · gaps = rejected/missing measurements · shading = repeat range, not a confidence interval',fontsize=10)
        fig.tight_layout(rect=(0,0,1,.96))
        path=output/(name+'.png');fig.savefig(path,dpi=160)
        fig.savefig(output/(name+'.pdf'));plt.close(fig);names.append(path.name)
    return names


def run_analysis(events, output, input_hash=None, plots=True):
    output = Path(output); output.mkdir(parents=True, exist_ok=True)
    rows,tokens,contrasts = analyze_events(events)
    strata={(r['batch_id'],r['config_hash'],r['model'],r['model_digest'],r['source'],r['prompt_version']) for r in rows}
    if len(strata)>1:
        raise ValueError('Analyze one batch/model/configuration per report; do not silently pool different model trajectories')
    write_csv(output/'responses.csv',rows)
    with (output/'token-uncertainty-metrics.jsonl').open('w',encoding='utf-8') as f:
        for row in rows:
            for metric in ('artifact_h_lower_bits','artifact_h_renorm_bits','artifact_h_residual_bucket_bits','artifact_coverage'):
                value=row[metric] if row['status']=='valid' and row['probability_status']=='available' else None
                result={k:row[k] for k in ('batch_id','run_id','task_id','task_version','condition','repeat','seed','inferred_call_seed','call_seed_rule','step',
                    'agent_id','agent_role','model','model_digest','source','prompt_version','config_hash','context_hash')}
                result.update(metric=metric,value=value,unit='probability_mass' if metric=='artifact_coverage' else 'bits/token',
                    status='measured' if value is not None else row['submission_state'] if row['status']!='valid' else 'probabilities_unavailable_or_invalid',
                    source_event_ids=[i for i in (row['source_event_id'],row['generation_event_id'],row['observation_id']) if i],
                    measured_token_positions=row['artifact_token_count'],log_base=2 if metric!='artifact_coverage' else None,
                    metric_version=VERSION,scope='evolving_context_positional_token_uncertainty',
                    probability_class='partial_reported_support',semantic_entropy_claim=False,causal_claim=False,confidence_interval=None)
                f.write(json.dumps(result,ensure_ascii=False,allow_nan=False)+'\n')
    write_csv(output/'tokens.csv.gz',tokens)
    write_csv(output/'contrasts.csv',contrasts)
    write_csv(output/'metric-catalog.csv',METRIC_CATALOG)
    grid = checkpoint_grid(events)
    write_csv(output/'checkpoint-grid.csv',grid)
    task_catalog = {e['payload']['task_version']: e['payload']['task'] for e in events if e['kind']=='run_started'}
    (output/'task-catalog.json').write_text(json.dumps(task_catalog,ensure_ascii=False,indent=2)+'\n')
    terminal = {e['run_id']: e['payload'] for e in events if e['kind']=='run_finished'}
    matrix = []
    for e in events:
        if e['kind']!='run_started':continue
        p=e['payload'];sub=[r for r in rows if r['run_id']==e['run_id']]
        end=terminal.get(e['run_id'],{})
        expected=next(b['payload']['config']['steps']*2 for b in events if b['kind']=='batch_started' and b['batch_id']==e['batch_id'])
        matrix.append(dict(batch_id=e['batch_id'],run_id=e['run_id'],task_id=p['task_id'],task_version=p['task_version'],
            condition=p['condition_id'],repeat=p['repeat'],seed=p['seed'],expected_updates=expected,recorded_updates=len(sub),
            valid_updates=sum(r['status']=='valid' for r in sub),rejected_or_stalled_updates=sum(r['status']!='valid' for r in sub),
            rejected_generated_outputs=sum(r['submission_state']=='rejected_generated_output' for r in sub),
            stalled_without_generation=sum(r['submission_state']=='stalled_no_generation' for r in sub),
            missing_updates=max(0,expected-len(sub)),run_status=end.get('status','missing_terminal'),
            elapsed_seconds=end.get('elapsed_seconds'),source_event_id=e['event_id']))
    write_csv(output/'experiment-matrix.csv',matrix)
    write_csv(output/'answer-class-proxy.csv',analyze(events))
    write_csv(output/'answer-class-intervention-proxy.csv',intervention_changes(analyze(events),
        next((e['payload']['config']['unlock_step'] for e in events if e['kind']=='batch_started'),None)))
    review = [dict(source_event_id=r['source_event_id'],task_id=r['task_id'],agent_role=r['agent_role'],
                   response_text=r['response_text'],reviewer='',coherence='',novelty='',
                   integrates_or_contests_peer='',rights_or_form_tradeoff='',rationale='') for r in rows if r['status']=='valid']
    random.Random(20260913).shuffle(review)
    write_csv(output/'blind-review-sheet.csv',review)
    inventory = []
    for task in sorted({r['task_id'] for r in rows}):
        for condition in sorted({r['condition'] for r in rows if r['task_id']==task}):
            sub=[r for r in rows if r['task_id']==task and r['condition']==condition]
            delivered=[r for r in sub if r['delivered_message_count'] and r['status']=='valid']
            inventory.append(dict(task_id=task,condition=condition,recorded=len(sub),valid=sum(r['status']=='valid' for r in sub),
                probabilities_available=sum(r['probability_status']=='available' for r in sub),
                delivered_responses=len(delivered),explicitly_referencing=sum(bool(r['checked_reference_count']) for r in delivered),
                mean_latency_s=average([r['latency_seconds'] for r in sub])))
    write_csv(output/'inventory.csv',inventory)
    validation = dict(analysis_version=VERSION, analysis_source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      analysis_dependency_sha256={name:hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ('analysis.py','probability_artifacts.py','semantic.py')},
                      input_sha256=input_hash,hash_chain=validate_hash_chain(events),
                      events=len(events),responses=len(rows),captured_token_positions=len(tokens),
                      invalid_probability_positions=sum(t['status']=='invalid' for t in tokens),
                      max_recomputation_error=max((t['recomputation_error'] for t in tokens if t['status']=='valid'),default=None),
                      sources=sorted({r['source'] for r in rows}),
                      unavailable_artifact_entropy=sum(r['probability_status']=='unavailable' for r in rows),
                      token_alignment_counts=dict(Counter(r['token_alignment'] for r in rows)),
                      metric_scope='response_text value only, with separate whole-JSON diagnostic',
                      semantic_entropy_status='not_computed',causal_claim=False,
                      batch_terminal_events=[dict(batch_id=e['batch_id'],source_event_id=e['event_id'],**e['payload']) for e in events if e['kind']=='batch_finished'],
                      batches=[e['payload'] for e in events if e['kind']=='batch_started'])
    (output/'validation.json').write_text(json.dumps(validation,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    figures=plot_results(rows,output) if plots else []
    lines=['# Creative communication study','',f'Analysis: `{VERSION}`. Input SHA-256: `{input_hash}`.','',
           '## Recorded evidence','', '| Task | Condition | Recorded | Valid | Raw generations with probabilities | Delivered | Referencing |',
           '|---|---|---:|---:|---:|---:|---:|']
    for item in inventory:
        lines.append('| '+' | '.join(str(item[k]) for k in ('task_id','condition','recorded','valid','probabilities_available','delivered_responses','explicitly_referencing'))+' |')
    lines += ['', '## Signed entropy contrasts','',
              'Pre = checkpoints before unlock; post = checkpoints at/after unlock. Each row is one repeat and role. Complete valid runs with measured artifact tokens are required.', '',
              '| Task | Role | Repeat | C0 post−pre (bits) | C2 post−pre (bits) | Difference in changes (bits) |',
              '|---|---|---:|---:|---:|---:|']
    def show(v):return 'not estimable' if v is None else f'{v:.4f}'
    for c in contrasts:
        lines.append(f"| {c['task_id']} | {c['agent_role']} | {c['repeat']+1} | {show(c['C0_delta_bits'])} | {show(c['C2_delta_bits'])} | {show(c['difference_in_changes_bits'])} |")
    lines += ['', '### Incomplete-run diagnostics','',
              'Available valid artifacts only. Counts show measured pre/post updates per role. Rejections can select the surviving samples, so these differences are diagnostics, not complete-run effects.', '',
              '| Task | Role | C0 pre/post n | C2 pre/post n | C0 partial change | C2 partial change | Partial difference |',
              '|---|---|---:|---:|---:|---:|---:|']
    for c in contrasts:
        lines.append(f"| {c['task_id']} | {c['agent_role']} | {c['C0_measured_pre_count']}/{c['C0_measured_post_count']} | {c['C2_measured_pre_count']}/{c['C2_measured_post_count']} | {show(c['C0_partial_delta_bits'])} | {show(c['C2_partial_delta_bits'])} | {show(c['partial_difference_in_changes_bits'])} |")
    lines += ['', '## Definitions and validation','',
              'At EACH token position, deduplicate sampled/reported alternatives and let C = Σp. '
              'H_lower = −Σp log₂p is a truncated lower-bound sum. H_renorm = H_lower/C + log₂C is Shannon entropy on the normalized reported support. '
              'H_residual_bucket = H_lower − (1−C)log₂(1−C) groups unreported vocabulary mass into one bucket. None is full-vocabulary entropy.', '',
              'Only tokens wholly inside the captured JSON response_text string enter artifact entropy. '
              'Byte reconstruction must match the raw output exactly. Unalignable or invalid probabilities are missing, never zero. '
              'The same algebra is recomputed independently against probability_artifacts normalization. validation.json preserves the input hash, chain verification, errors, source versions and configurations.', '',
              f"Captured token positions: {len(tokens)}; invalid positions: {validation['invalid_probability_positions']}; "
              f"maximum recomputation discrepancy: {validation['max_recomputation_error']}. Export-segment hash-chain status: {validation['hash_chain']['status']}.", '',
              '## Interpretation and limits','',
              'These are evolving-context TOKEN uncertainty trajectories. Creativity, correctness, collaboration value and predictive semantic uncertainty are different quantities. '
              'Answer-class diversity here describes workflow labels (draft/revision/synthesis), not artistic meanings. '
              'Explicit source-ID reference is a reference proxy; it does not prove useful transfer. Lexical Jaccard distances measure word-set overlap, not meaning or causal effect.', '',
              'There is no objective correct poem or regulation and no quality score. Use the shuffled blind-review-sheet.csv for independently judged coherence, novelty, peer integration and trade-offs. '
              'Correlations between entropy and creative value cannot be estimated until those judgments exist. '
              'A fixed historical role and assigned editor structure may increase references mechanically. The small number of repeats supports descriptive analysis only; agents/checkpoints/tokens are not independent replicates.', '',
              'C2 and C0 use matched seeds and configurations. The runner reverses condition order across repeats, but the one-repeat pilot always runs C0 first and therefore has no effective order counterbalance. Context length, excerpting, roles, task length, constrained JSON decoding, latency and provider nondeterminism remain confounders. '
              'Condition labels and random event IDs in serialized history can make paired prompts differ byte-for-byte even before unlock; matching seeds does not guarantee identical fixed contexts. '
              'The task-specific context window and explicit artifact excerpts mean shared-from-unlock does not reveal every full historical artifact. Full original text remains in events.jsonl. '
              'Both agents see the prior committed checkpoint, so B does not see the current A response within the same checkpoint.', '',
              'No placebo arm was run. The earlier analysis_temperature_1 scripts use base/switch/placebo, 30 action turns and an action-class joint distribution; they cannot be applied unchanged to this five-checkpoint artifact protocol. '
              'This report carries over integrity checks, probability recomputation, descriptive trajectories and matched pre/post contrasts; it does not invent READ/WRITE probabilities, mutual information, ITS significance or detector results.', '',
              'Semantic entropy requires fixed-context repeated sampling, a declared equivalence rule, and semantic clusters. '
              'Entailment rules developed for factual QA do not automatically define equivalent artistic works. Establish the unit (e.g. poem interpretation or policy propositions) with the physics team before assigning semantic probabilities. '
              'See [Kuhn et al., Semantic Uncertainty](https://arxiv.org/abs/2302.09664) and [Farquhar et al., Nature semantic entropy](https://www.nature.com/articles/s41586-024-07421-0).', '',
              '## Files','', 'experiment-matrix.csv distinguishes valid, rejected/stalled and missing updates for each task/condition run. task-catalog.json is copied from the recorded run definitions, not current source files. metric-catalog.csv defines units and limitations. '
              'token-uncertainty-metrics.jsonl exposes derived metrics with source IDs and rejected/missing measurements as null; raw metrics.jsonl in the ZIP remains unchanged. '
              'responses.csv, tokens.csv.gz, inventory.csv, contrasts.csv, checkpoint-grid.csv, answer-class-proxy.csv, validation.json and blind-review-sheet.csv preserve source IDs. '
              'Join source_event_id / observation_id / generation_event_id to events.jsonl for exact text, contexts and provider probabilities.']
    for name in figures:lines += ['',f'![{name}]({name})']
    (output/'report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    body='<h1>Creative communication study</h1><p>Exploratory evidence. Token uncertainty does not measure creative quality or semantic entropy.</p>'
    body+='<p><a href="report.md">Full methods and results</a> · <a href="validation.json">Probability validation</a> · <a href="responses.csv">Source-linked responses</a> · <a href="blind-review-sheet.csv">Blind review sheet</a></p>'
    body+='<pre>'+html.escape('\n'.join(lines[:lines.index('## Definitions and validation')]))+'</pre>'
    for name in figures:body+=f'<img src="{name}" alt="{html.escape(name)}">'
    body+='<h2>Last valid recorded artifacts</h2><p>These are the latest accepted texts, not necessarily completed joint solutions. Rejected raw generations remain in the export and generated_response_text column.</p>'
    for row in rows:
        if row['status']=='valid' and row['step']==max(r['step'] for r in rows if r['run_id']==row['run_id'] and r['agent_id']==row['agent_id'] and r['status']=='valid'):
            body+=f"<details><summary>{html.escape(row['task_id'])} · {row['condition']} · repeat {row['repeat']+1} · {html.escape(row['agent_role'])} · checkpoint {row['checkpoint']} · {row['run_status']}</summary><pre>{html.escape(row['response_text'])}</pre><small>Source: {row['source_event_id']}</small></details>"
    (output/'report.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><title>Creative communication study</title><style>body{font:16px system-ui;max-width:1100px;margin:40px auto;padding:20px;color:#152638}img{width:100%}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f8;padding:18px}details{margin:16px 0}</style>'+body+'</html>')
    return validation


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events',required=True,help='Exported events.jsonl or researcher ZIP')
    parser.add_argument('--output',required=True)
    parser.add_argument('--no-plots',action='store_true')
    args=parser.parse_args();path=Path(args.events)
    if path.suffix=='.zip':
        with zipfile.ZipFile(path) as z:raw=z.read('events.jsonl')
    else:raw=path.read_bytes()
    events=[json.loads(line) for line in raw.splitlines() if line.strip()]
    result=run_analysis(events,args.output,hashlib.sha256(raw).hexdigest(),not args.no_plots)
    print(json.dumps({k:result[k] for k in ('responses','captured_token_positions','invalid_probability_positions','semantic_entropy_status')}))


if __name__=='__main__':main()
