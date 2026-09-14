"""Controller-only frozen-context sampling/replay, writing separate research artifacts."""
import argparse
from copy import deepcopy
import json
import time
import uuid
import zipfile
from pathlib import Path
from typing import Protocol

from .semantic import fingerprint
from .task_updates import parse_update
from .timing import timed_generate


class FixedContextSampler(Protocol):
    def generate(self, messages, seed, max_output_tokens, choices) -> dict: ...


class InfluenceMetric(Protocol):
    version: str
    def compare(self, visible: dict, masked: dict) -> dict: ...


def freeze_observation(events, observation_id):
    event=next((e for e in events if e['event_id']==observation_id and e['kind']=='agent_observation'),None)
    if not event:
        raise ValueError('Observation not found')
    batch=next(e for e in events if e['batch_id']==event['batch_id'] and e['kind']=='batch_started')
    if not any(e['kind']=='batch_finished' and e['batch_id']==event['batch_id'] for e in events):
        raise ValueError('Offline work requires a terminal batch; a partial export cannot authorize sampling')
    run=next(e for e in events if e['kind']=='run_started' and e['run_id']==event['run_id'])
    metadata=next(e['payload'] for e in events if e['kind']=='model_metadata' and e['batch_id']==event['batch_id'])
    obs=deepcopy(event['payload'])
    messages=obs['messages']
    if obs.get('context_hash') and obs['context_hash']!=fingerprint(messages):
        raise ValueError('Observation context hash mismatch')
    cfg=batch['payload']['config']
    return {'observation':obs,'context_hash':fingerprint(messages),'task_state':deepcopy(run['payload']['task']),
            'task_id':run['payload']['task_id'],'task_version':run['payload']['task_version'],
            'model_metadata':deepcopy(metadata),'model_config':{k:cfg[k] for k in ('model','temperature','num_ctx','max_output_tokens')},
            'config_hash':batch['payload']['config_hash'], 'prompt_version':obs['prompt_version'],
            'agent_role':obs.get('agent_role','solver'),'agent_id':obs['agent_id'], 'step':obs['step'],
            'condition_id':run['payload']['condition_id'],'run_id':event['run_id'], 'batch_id':event['batch_id'],
            'source_event_ids':[event['event_id'],run['event_id'],batch['event_id']],
            'source':batch['payload']['source'], 'seed':run['payload']['seed'],
            'task_state_hash':fingerprint(run['payload']['task'])}


def mask_peer(frozen):
    result=deepcopy(frozen)
    obs=result['observation']
    actor=obs['agent_id']
    content=json.loads(obs['messages'][-1]['content'])
    history=content.get('permitted_history',[])
    content['permitted_history']=[x for x in history if x['agent']==actor]
    if 'shared_key_insights' in content:
        content['shared_key_insights']=[]
    if 'visible_message_ids' in content:
        content['visible_message_ids']=[]
    if 'allowed_evidence_ids' in content:
        allowed={x.split(':',1)[0] for x in content['private_evidence']}
        allowed.update(i for h in content['permitted_history'] for i in h.get('evidence_ids',[]))
        content['allowed_evidence_ids']=sorted(allowed)
    removed=list(obs['visible_message_ids'])
    obs['visible_event_ids']=[x for x in obs['visible_event_ids'] if x not in removed]
    obs['visible_message_ids']=[]
    obs['shared_key_insights']=[]
    obs['messages'][-1]['content']=json.dumps(content,ensure_ascii=False)
    obs['context_hash']=fingerprint(obs['messages'])
    result['context_hash']=obs['context_hash']
    result['intervention']={'kind':'remove_current_peer_projection','source_context_hash':frozen['context_hash'],
        'masked_message_ids':removed,'availability_unchanged':True,
        'limitation':'Own history may retain earlier peer influence; prompt length changes; not a total-effect replay.'}
    return result


def verify_adapter(frozen, adapter):
    metadata=adapter.metadata()
    if adapter.source!=frozen['source']:
        raise ValueError('Replay cannot replace a real source with fixture or another transport')
    original=frozen['model_metadata']
    for key in ('model','digest','runtime'):
        if key in original and original[key]!=metadata.get(key):
            raise ValueError('Model/runtime provenance differs: '+key)
    return metadata


def sample_once(frozen, adapter, seed, timeout_seconds=60):
    obs=frozen['observation']
    content=json.loads(obs['messages'][-1]['content'])
    result, elapsed, error=timed_generate(adapter,obs['messages'],seed,
        frozen['model_config']['max_output_tokens'],content['options'],timeout_seconds)
    answer=None
    if result is not None and error is None:
        try:
            answer=parse_update(result['raw_response'],content,content['options'])
            if result.get('done_reason')=='length':
                raise ValueError('Output limit reached')
        except (ValueError,KeyError,TypeError) as exc:
            error=exc
    return {**{k:deepcopy(frozen[k]) for k in ('context_hash','task_id','task_version','model_metadata','model_config',
            'config_hash','prompt_version','agent_role','agent_id','step','condition_id','run_id','batch_id',
            'source_event_ids','source','task_state_hash')},
        'sample_id':uuid.uuid4().hex,'seed':seed,'extraction_version':'structured-response-text-v1',
        'response_text':answer['response_text'] if answer and not error else '', 'answer':answer if not error else None,
        'raw_response':result.get('raw_response') if result else None,'generation_result':result,
        'status':'valid' if not error else 'timeout' if isinstance(error,TimeoutError) else 'failed',
        'error':str(error) if error else None,'latency_ms':elapsed,
        'provider_cancellation_status':'unknown' if error and not result else 'not_needed',
        'sequence_likelihood':None,
        'likelihood_note':'Raw token logprobs, if present, need independent completeness/scope validation before weighting.',
        'intervention':frozen.get('intervention')}


def sample_fixed(frozen, adapter, count=5, seed=17, timeout_seconds=60, deadline_seconds=300):
    if type(count) is not int or not 1<=count<=20 or timeout_seconds<=0 or deadline_seconds<=0:
        raise ValueError('Bounded sample settings required')
    verify_adapter(frozen,adapter)
    rows=[]; started=time.monotonic()
    for i in range(count):
        remaining=deadline_seconds-(time.monotonic()-started)
        if remaining<=0:
            break
        row=sample_once(frozen,adapter,seed+i,min(timeout_seconds,remaining))
        rows.append(row)
        if row['status']=='timeout':
            break
    return {'kind':'fixed_context_sample_set','frozen_observation':frozen,'samples':rows,
            'requested_samples':count,'valid_samples':sum(r['status']=='valid' for r in rows),
            'status':'completed' if len(rows)==count and all(r['status']=='valid' for r in rows) else 'incomplete'}


class AnswerChange:
    version='paired-answer-change-v1'
    def compare(self, visible, masked):
        if visible['status']!='valid' or masked['status']!='valid':
            return {'metric':self.version,'status':'incomplete','value':None}
        return {'metric':self.version,'status':'descriptive','value':int(visible['answer']['answer_class']!=masked['answer']['answer_class']),
                'candidate_key_changed':visible['answer'].get('candidate_key')!=masked['answer'].get('candidate_key'),
                'source_sample_ids':[visible['sample_id'],masked['sample_id']],
                'scope':'single_paired_behavioral_intervention_contrast','causal_effect_estimated':False}


def replay_pair(frozen, adapter, seed=17, timeout_seconds=60, deadline_seconds=300, masked_first=False):
    if not frozen['observation'].get('visible_message_ids'):
        raise ValueError('Selected observation has no delivered peer content to mask')
    verify_adapter(frozen,adapter)
    arms={'visible':frozen,'masked':mask_peer(frozen)}
    order=['masked','visible'] if masked_first else ['visible','masked']
    rows={}; start=time.monotonic()
    for arm in order:
        remaining=deadline_seconds-(time.monotonic()-start)
        if remaining<=0:
            break
        rows[arm]=sample_once(arms[arm],adapter,seed,min(timeout_seconds,remaining))
        if rows[arm]['status']=='timeout':
            break
    metric=AnswerChange().compare(rows['visible'],rows['masked']) if len(rows)==2 else {'status':'incomplete','value':None}
    return {'kind':'paired_replay','pair_id':uuid.uuid4().hex,'seed':seed,'execution_order':order,
            'seed_determinism':'requested_not_guaranteed','frozen_observation':frozen,
            'intervention':arms['masked']['intervention'],'arms':rows,'metric':metric}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--events',required=True,help='events.jsonl or exported ZIP; never reads the runtime DB')
    parser.add_argument('--observation',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--mode',choices=['sample','replay'],default='sample')
    parser.add_argument('--adapter',choices=['fixture','ollama'],default='fixture')
    parser.add_argument('--count',type=int,default=5)
    parser.add_argument('--seed',type=int,default=17)
    parser.add_argument('--timeout',type=float,default=60)
    parser.add_argument('--deadline',type=float,default=300)
    parser.add_argument('--masked-first',action='store_true')
    args=parser.parse_args()
    path=Path(args.events)
    if path.suffix=='.zip':
        with zipfile.ZipFile(path) as z:
            text=z.read('events.jsonl').decode()
    else:
        text=path.read_text()
    frozen=freeze_observation([json.loads(line) for line in text.splitlines() if line.strip()],args.observation)
    from .adapters import FixtureAdapter, OllamaAdapter
    adapter=FixtureAdapter() if args.adapter=='fixture' else OllamaAdapter(frozen['model_config']['model'])
    if adapter.source not in ('fixture','local_model'):
        raise ValueError('This offline pilot supports local model transport only')
    with Path(args.output).open('x') as stream:
        result=(sample_fixed(frozen,adapter,args.count,args.seed,args.timeout,args.deadline) if args.mode=='sample' else
                replay_pair(frozen,adapter,args.seed,args.timeout,args.deadline,args.masked_first))
        stream.write(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(args.output)


if __name__=='__main__':
    main()
