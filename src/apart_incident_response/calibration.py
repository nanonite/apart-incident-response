"""Small two-agent pilot; explicit local inference, no paid or remote fallback."""
import argparse
import json
from pathlib import Path
from .adapters import OllamaAdapter
from .diagnostics import calibration_summary
from .events import EventStore
from .experiment import BatchRunner


def calibration_config(adapter='fixture', model='gemma2:2b', task='sensor-fusion', deadline=900, request_timeout=120):
    return {'adapter':adapter,'model':model,'task_ids':[task],'conditions':['C2'],'steps':5,'unlock_step':3,
            'repeats':2,'deadline_seconds':deadline,'request_timeout_seconds':request_timeout,
            'batch_timeout_seconds':deadline*2+60,'max_output_tokens':512,
            'schedule':'synchronous_snapshot_serial_inference', 'shared_context_mode':'key_insights_plus_history',
            'study_id':'collaboration_calibration_v1'}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--db',default='artifacts/audit-calibration.sqlite')
    p.add_argument('--output',required=True)
    p.add_argument('--model',default='gemma2:2b')
    p.add_argument('--task',default='sensor-fusion')
    p.add_argument('--with-ollama',action='store_true')
    p.add_argument('--deadline',type=float,default=900)
    p.add_argument('--request-timeout',type=float,default=120)
    args=p.parse_args()
    model=OllamaAdapter(args.model) if args.with_ollama else None
    if model and model.source!='local_model':
        raise ValueError('Calibration requires a local Ollama origin')
    store=EventStore(args.db)
    result=[]
    with Path(args.output).open('x') as output:
        for adapter in (['fixture','ollama'] if args.with_ollama else ['fixture']):
            config=calibration_config(adapter,args.model,args.task,args.deadline,args.request_timeout)
            batch=BatchRunner(store).run(config,adapter=model if adapter=='ollama' else None)
            row={'batch_id':batch,'config':config,**calibration_summary(store.read(batch))}
            output.write(json.dumps(row,allow_nan=False)+'\n'); output.flush()
            result.append(row)
            print(json.dumps(row,allow_nan=False),flush=True)
    if not store.verify():
        raise ValueError('Event chain verification failed')


if __name__=='__main__':
    main()
