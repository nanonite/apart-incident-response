import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.error
import zipfile

from apart_incident_response.adapters import FixtureAdapter, OllamaAdapter
from apart_incident_response.calibration import calibration_config
from apart_incident_response.collaboration_tasks import prepare, evaluate
from apart_incident_response.diagnostics import calibration_summary
from apart_incident_response.events import EventStore
from apart_incident_response.experiment import BatchRunner, observation, validate_config
from apart_incident_response.offline import freeze_observation, mask_peer, sample_fixed, replay_pair
from apart_incident_response.panel import App, bundle, state
from apart_incident_response.tasks import task_by_id
from apart_incident_response.task_updates import parse_update
from apart_incident_response.timing import timed_generate


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store=EventStore(Path(self.temp.name)/'test.sqlite')

    def run_batch(self, **config):
        cfg={'adapter':'fixture','task_ids':['sensor-fusion'],'conditions':['C0','C2'],
             'steps':5,'unlock_step':3,'repeats':2,'max_output_tokens':512,**config}
        batch=BatchRunner(self.store).run(cfg)
        return self.store.read(batch)

    def test_seeded_complementary_and_identical_evidence_controls(self):
        task=task_by_id('sensor-fusion')
        one=prepare(task,17,'split'); two=prepare(task,17,'identical_complete')
        self.assertEqual(one['correct'],two['correct'])
        self.assertEqual(len(one['evidence']['A']),1)
        self.assertEqual(len(one['evidence']['B']),1)
        self.assertEqual(two['evidence']['A'],two['evidence']['B'])
        events=self.run_batch()
        self.assertEqual(events[-1]['payload']['status'],'completed')
        after=[e for e in events if e['kind']=='task_update' and e['payload']['condition_id']=='C2' and e['payload']['step']==3]
        self.assertEqual(len(after),4)
        for e in after:
            result=next(r for r in events if r['kind']=='evaluator_result' and r['payload']['update_id']==e['event_id'])
            self.assertEqual(result['payload']['score'],1)
        for e in events:
            if e['kind']=='agent_observation' and e['payload']['step']<3:
                self.assertEqual(e['payload']['visible_message_ids'],[])

    def test_role_contract_and_rotation_are_enforced(self):
        events=self.run_batch(task_ids=['repair-review'],role_swap_step=2,repeats=1)
        updates=[e for e in events if e['kind']=='task_update']
        self.assertTrue(all(e['payload']['termination_state']=='checkpoint_update' for e in updates))
        self.assertTrue(any(e['kind']=='roles_rotated' for e in events))
        for e in updates:
            p=e['payload']; initial='planner' if p['agent_id']=='A' else 'critic'
            self.assertEqual(p['agent_role'],initial if p['step']<2 else ('critic' if initial=='planner' else 'planner'))
            if p['agent_role']=='critic':
                self.assertNotEqual(p['rejected_option'],p['answer_class'])
        obs=next(e['payload'] for e in events if e['kind']=='agent_observation' and e['payload']['agent_role']=='critic')
        content=json.loads(obs['messages'][-1]['content'])
        raw=json.loads(FixtureAdapter().generate(obs['messages'],17,512,content['options'])['raw_response'])
        raw['message_type']='proposal'
        with self.assertRaises(ValueError):
            parse_update(json.dumps(raw),content,content['options'])
        raw['message_type']='counterexample'; raw['referenced_message_ids']=['secret-global-event']
        with self.assertRaises(ValueError):
            parse_update(json.dumps(raw),content,content['options'])

    def test_contradiction_oracle_checks_counterexample(self):
        task=task_by_id('diagnostic-contradiction')
        good={'answer_class':'routing','evidence_ids':['D2'],'rejected_option':'logging'}
        self.assertEqual(evaluate(task,good,'critic')['role_check_score'],1)
        self.assertEqual(evaluate(task,{**good,'evidence_ids':['D1']},'critic')['role_check_score'],0)

    def test_two_solver_role_control(self):
        events=self.run_batch(task_ids=['repair-review'],role_mode='two_solvers',repeats=1)
        self.assertEqual({e['payload']['agent_role'] for e in events if e['kind']=='task_update'},{'solver'})

    def test_zero_bandwidth_omits_peer_without_changing_truth_log(self):
        events=self.run_batch(communication_budget_bytes=0,communication_cost_per_kib=1,repeats=1)
        after=[e for e in events if e['kind']=='agent_observation' and e['payload']['communication_available']]
        self.assertTrue(after)
        for e in after:
            p=e['payload']
            self.assertFalse(p['visible_message_ids'])
            self.assertTrue(p['communication_projection']['omitted_message_ids'])
            self.assertEqual(p['communication_projection']['cost'],0)
        self.assertEqual(len([e for e in events if e['kind']=='task_update']),20)
        self.assertTrue(self.store.verify())

    def test_delivery_cost_delay_and_request_gate(self):
        events=self.run_batch(communication_cost_per_kib=2,communication_delay_steps=1,
                              communication_request_required=True,repeats=1)
        by_id={e['event_id']:e for e in events}
        delivery=[e for e in events if e['kind']=='communication_delivery']
        self.assertTrue(delivery)
        for e in delivery:
            p=e['payload']
            self.assertTrue(p['requested'])
            self.assertAlmostEqual(p['cost'],p['delivered_bytes']/1024*2)
            self.assertTrue(all(by_id[i]['payload']['step']<p['step']-1 for i in p['message_ids']))
        obs=observation(task_by_id('repair-review'),[], 'A',0,'C1',validate_config({
            'task_ids':['repair-review'],'communication_request_required':True}))
        self.assertTrue(obs['communication_available'])
        self.assertFalse(obs['visible_message_ids'])

    def test_pilot_budget_and_legacy_alias(self):
        cfg=validate_config(calibration_config())
        self.assertEqual(cfg['deadline_seconds'],900)
        self.assertEqual(cfg['request_timeout_seconds'],120)
        self.assertEqual(validate_config({'timeout_seconds':20})['request_timeout_seconds'],20)
        self.assertEqual(validate_config({'request_timeout_seconds':150})['request_timeout_seconds'],150)
        with self.assertRaises(ValueError):
            validate_config({'role_swap_step':3,'task_ids':['locked-database']})

    def test_heartbeat_and_finished_owner_events(self):
        gate=threading.Event()
        class Wait(FixtureAdapter):
            def generate(self,*args):
                gate.wait(.04)
                return super().generate(*args)
        runner=BatchRunner(self.store)
        batch=runner.run({'adapter':'fixture','task_ids':['inventory'],'conditions':['C0'],
                         'steps':2,'unlock_step':1,'heartbeat_seconds':.01},adapter=Wait())
        events=self.store.read(batch)
        started=[e for e in events if e['kind']=='generation_started']
        finished=[e for e in events if e['kind']=='generation_finished']
        self.assertEqual(len(finished),len(started))
        hearts=[e for e in events if e['kind']=='worker_heartbeat']
        self.assertGreater(len(hearts),len(started))
        self.assertEqual({e['payload']['worker_id'] for e in hearts},{runner.owner['worker_id']})
        self.assertEqual(App(self.store).snapshot(batch)['execution']['state'],'terminal')

    def test_900_second_deadline_clips_final_request_without_waiting_15_minutes(self):
        clock=[0.0]; observed=[]
        def slow(*args,**kwargs):
            observed.append(args[-1]); clock[0]+=args[-1]
            return None,args[-1]*1000,TimeoutError('deadline')
        with patch('apart_incident_response.experiment.time.monotonic',side_effect=lambda:clock[0]), \
             patch('apart_incident_response.experiment.timed_generate',side_effect=slow):
            events=self.run_batch(deadline_seconds=900,request_timeout_seconds=250,conditions=['C0'],repeats=1)
        self.assertEqual(observed,[250,250,250,150])
        end=next(e for e in events if e['kind']=='run_finished')
        self.assertEqual(end['payload']['status'],'over_deadline')
        self.assertEqual(calibration_summary(events)['missing_updates'],6)

    def test_real_timeout_stops_further_requests_and_marks_unknown_cancellation(self):
        class RealFixture(FixtureAdapter):
            source='local_model'
        with patch('apart_incident_response.experiment.timed_generate',return_value=(None,10,TimeoutError('wait exceeded'))):
            BatchRunner(self.store).run({'adapter':'fixture','task_ids':['inventory'],'conditions':['C0','C2']},adapter=RealFixture())
        events=self.store.read()
        self.assertEqual(sum(e['kind']=='generation_started' for e in events),1)
        self.assertEqual(events[-1]['kind'],'batch_finished')
        self.assertEqual(events[-1]['payload']['provider_cancellation_status'],'unknown')

    def test_logprob_http_error_does_not_retry(self):
        adapter=OllamaAdapter(logprobs=True)
        obs=observation(task_by_id('inventory'),[],'A',0,'C0',validate_config({}))
        with patch.object(adapter,'request',side_effect=urllib.error.HTTPError('http://localhost',400,'unsupported',{},None)) as call:
            with self.assertRaises(urllib.error.HTTPError):
                adapter.generate(obs['messages'],17,220,{'27':'27'})
            self.assertEqual(call.call_count,1)

    def test_offline_sampling_and_masked_replay_preserve_source(self):
        events=self.run_batch(repeats=1)
        source=next(e for e in events if e['kind']=='agent_observation' and e['payload']['step']==3 and e['payload']['communication_available'])
        frozen=freeze_observation(events,source['event_id'])
        masked=mask_peer(frozen)
        self.assertEqual(frozen['task_state_hash'],masked['task_state_hash'])
        self.assertNotEqual(frozen['context_hash'],masked['context_hash'])
        self.assertTrue(frozen['observation']['visible_message_ids'])
        self.assertFalse(masked['observation']['visible_message_ids'])
        count=len(self.store.read())
        samples=sample_fixed(frozen,FixtureAdapter(),count=3)
        self.assertEqual(samples['valid_samples'],3)
        self.assertEqual({s['context_hash'] for s in samples['samples']},{frozen['context_hash']})
        pair=replay_pair(frozen,FixtureAdapter(),masked_first=True)
        self.assertEqual(pair['execution_order'],['masked','visible'])
        self.assertEqual(pair['arms']['visible']['seed'],pair['arms']['masked']['seed'])
        self.assertEqual(len(self.store.read()),count)
        self.assertFalse(pair['metric']['causal_effect_estimated'])

    def test_offline_rejects_partial_batch_and_changed_model(self):
        events=self.run_batch(repeats=1)
        source=next(e for e in events if e['kind']=='agent_observation')
        with self.assertRaises(ValueError):
            freeze_observation([e for e in events if e['kind']!='batch_finished'],source['event_id'])
        frozen=freeze_observation(events,source['event_id']); frozen['model_metadata']['model']='different'
        with self.assertRaises(ValueError):
            sample_fixed(frozen,FixtureAdapter())

    def test_export_contains_reliability_costs_and_original_context_hash(self):
        events=self.run_batch(repeats=1)
        with zipfile.ZipFile(io.BytesIO(bundle(state(self.store)))) as z:
            self.assertIn('team-metrics.jsonl',z.namelist())
            self.assertEqual(json.loads(z.read('calibration.json'))['valid_output_rate'],1)
            rows=[json.loads(line) for line in z.read('checkpoint-grid.jsonl').splitlines()]
            by_id={e['event_id']:e for e in events}
            self.assertTrue(all(row['context_hash']==by_id[row['observation_id']]['payload']['context_hash'] for row in rows))


if __name__=='__main__':
    unittest.main()
