"""Launch the two creative tracks through the local panel, then analyze its ZIP.

The panel owns the worker so the live UI can verify execution. Analysis consumes
only the completed/partial researcher export; it never changes running agents.
"""
import argparse
import json
from pathlib import Path
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urlparse

from apart_incident_response.creative_analysis import run_analysis
import hashlib
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--panel',default='http://127.0.0.1:8766')
    parser.add_argument('--output',default='research/creative_collaboration/pilot-v2')
    parser.add_argument('--model',default='gemma2:2b')
    parser.add_argument('--adapter',choices=['fixture','ollama'],default='ollama')
    parser.add_argument('--repeats',type=int,default=1)
    parser.add_argument('--batch',help='Resume monitoring an already launched batch; does not launch new inference')
    parser.add_argument('--fixture-config',action='store_true',help='Write/test the same plan without expensive model calls')
    args=parser.parse_args();origin=args.panel.rstrip('/')
    parsed=urlparse(origin)
    if parsed.scheme!='http' or parsed.hostname not in ('127.0.0.1','localhost') or parsed.path or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Use a controller-selected local panel origin only')
    output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    cfg=json.loads(Path('config/creative-poetry-ollama.json').read_text())
    cfg.update(task_ids=['poetry-duet','civic-law-1943'],study_id='creative_tracks_v2',
               adapter='fixture' if args.fixture_config else args.adapter,model=args.model,repeats=args.repeats,
               request_timeout_seconds=150,batch_timeout_seconds=3600)
    (output/'requested-config.json').write_text(json.dumps(cfg,indent=2)+'\n')
    def get(path):
        with urllib.request.urlopen(origin+path,timeout=60) as response:return response.read()
    session=json.loads(get('/api/state'))['session_key']
    def post(path,body):
        request=urllib.request.Request(origin+path,data=json.dumps(body).encode(),
            headers={'Content-Type':'application/json','X-Session-Key':session})
        with urllib.request.urlopen(request,timeout=60) as response:return json.load(response)
    batch=args.batch or post('/api/run',cfg)['batch_id']
    print(f'Launched {batch}: {cfg["task_ids"]}, C0/C2, {args.repeats} repeat(s), 5 checkpoints. Live: {origin}',flush=True)
    query='?'+urlencode({'batch':batch});started=time.monotonic();previous=None
    snapshot={}; recovered_runs=0
    try:
        while True:
            snapshot=json.loads(get('/api/state'+query))
            if not snapshot.get('batch'):
                if time.monotonic()-started>60:
                    raise RuntimeError('Panel has not recorded the requested batch within 60 seconds')
                time.sleep(.5)
                continue
            updates=sum(e['kind']=='task_update' for e in snapshot['events'])
            activity=snapshot.get('live_activity') or {};run=activity.get('run') or {}
            status=(snapshot.get('batch') or {}).get('status')
            signature=(updates,status,run.get('id'),activity.get('step'))
            if signature!=previous:
                print(f'{updates}/{snapshot["batch"]["config"]["expected_updates"]} updates · {run.get("task_id")} {run.get("condition_id")} · checkpoint {None if activity.get("step") is None else activity["step"]+1} · {status}',flush=True)
                previous=signature
            terminal_runs=sum(r['status']!='running' for r in snapshot.get('runs',[]))
            if terminal_runs>recovered_runs:
                recovery=output/'recovery-export.zip'
                partial=output/'recovery-export.zip.partial'
                partial.write_bytes(get('/api/export'+query));partial.replace(recovery)
                recovered_runs=terminal_runs
                print(f'Durable researcher recovery export saved after {terminal_runs} terminal task run(s).',flush=True)
            if status!='running':break
            if time.monotonic()-started>cfg['batch_timeout_seconds']+180:
                print('Monitoring deadline exceeded; requesting boundary stop and exporting a partial snapshot.',flush=True)
                post('/api/stop',{});break
            time.sleep(20)
    except KeyboardInterrupt:
        post('/api/stop',{})
        print('Boundary stop requested; preserving a partial researcher export.',flush=True)
    archive=output/'research-bundle.zip'
    # A last-run recovery snapshot can precede batch_finished. Always request a
    # fresh final export instead of silently promoting that partial snapshot.
    partial=output/'research-bundle.zip.partial'
    partial.write_bytes(get('/api/export'+query));partial.replace(archive)
    with zipfile.ZipFile(archive) as z:raw=z.read('events.jsonl')
    events=[json.loads(line) for line in raw.splitlines() if line.strip()]
    result=run_analysis(events,output,hashlib.sha256(raw).hexdigest())
    (output/'run-result.json').write_text(json.dumps(dict(batch_id=batch,panel=origin,
        batch_status=(snapshot.get('batch') or {}).get('status'),analysis_version=result['analysis_version'],
        source=result['sources'],responses=result['responses']),indent=2)+'\n')
    with zipfile.ZipFile(output/'creative-study-with-analysis.zip','w',zipfile.ZIP_DEFLATED) as z:
        with zipfile.ZipFile(archive) as original:
            for name in original.namelist():
                z.writestr('raw/'+name,original.read(name))
        for path in sorted(output.iterdir()):
            if path.is_file() and path.suffix!='.zip':z.write(path,path.name)
    print(f'Saved {archive}, report.html, PNG/PDF graphs, validation/tables, and creative-study-with-analysis.zip',flush=True)


if __name__=='__main__':main()
