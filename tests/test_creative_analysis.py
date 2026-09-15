import json
import math
from pathlib import Path
import tempfile
import unittest

from apart_incident_response.adapters import FixtureAdapter, OllamaAdapter
from apart_incident_response.creative_analysis import (artifact_token_indices, token_measurement,
    analyze_events, run_analysis, validate_hash_chain)
from apart_incident_response.events import EventStore
from apart_incident_response.experiment import BatchRunner, observation, validate_config
from apart_incident_response.probability_artifacts import ProbabilityArtifactError
from apart_incident_response.tasks import task_by_id


class ProbabilityFixture(FixtureAdapter):
    def generate(self, *args):
        result = super().generate(*args)
        result['logprobs'] = [{'token':c,'bytes':list(c.encode()),'logprob':-math.log(2),
            'top':[{'token':'__other__','logprob':-math.log(2)}]} for c in result['raw_response']]
        return result


class CreativeAnalysisTests(unittest.TestCase):
    def test_ollama_preserves_bytes_needed_for_artifact_alignment(self):
        class RecordedAdapter(OllamaAdapter):
            def request(self, route, payload=None, timeout=180):
                self.payload=payload
                return {'message':{'content':'é'},'done_reason':'stop',
                    'logprobs':[{'token':'é','bytes':[195,169],'logprob':-.5,
                                 'top_logprobs':[{'token':'a','bytes':[97],'logprob':-1.0}]}]}
        adapter=RecordedAdapter(logprobs=True)
        result=adapter.generate([{'role':'user','content':'{}'}],17,512,{'draft':'Draft'})
        self.assertEqual(result['logprobs'][0]['bytes'],[195,169])
        self.assertEqual(result['logprobs'][0]['top'][0]['bytes'],[97])
        self.assertTrue(adapter.payload['logprobs'])

    def test_probability_positions_are_not_merged_across_response(self):
        uncertain = token_measurement({'token':'a','logprob':-math.log(2),
            'top':[{'token':'a','logprob':-math.log(2)}, {'token':'b','logprob':-math.log(2)}]})
        certain = token_measurement({'token':'a','logprob':0,'top':[]})
        self.assertAlmostEqual(uncertain['h_renorm_bits'],1)
        self.assertAlmostEqual(certain['h_renorm_bits'],0)
        self.assertAlmostEqual((uncertain['h_renorm_bits']+certain['h_renorm_bits'])/2,.5)
        self.assertLess(uncertain['recomputation_error'],1e-10)
        with self.assertRaises(ProbabilityArtifactError):
            token_measurement({'token':'a','logprob':0,'top':[{'token':'b','logprob':0}]})

    def test_token_bytes_exclude_json_structure_and_reject_misalignment(self):
        raw=json.dumps({'response_text':'noche azul','answer_class':'draft'})
        entries=[{'token':c,'bytes':list(c.encode())} for c in raw]
        indices,status=artifact_token_indices(raw,entries)
        self.assertEqual(status,'aligned_response_text_value')
        self.assertEqual(''.join(entries[i]['token'] for i in sorted(indices)),'noche azul')
        self.assertEqual(artifact_token_indices(raw,entries[:-1])[1],'unavailable_token_alignment')

    def test_role_assignment_equal_evidence_and_no_sixty_word_override(self):
        task=task_by_id('civic-law-1943')
        self.assertEqual(task['agent_roles'],{'A':'liberal_critic','B':'historical_drafter'})
        self.assertEqual(task['evidence']['A'],task['evidence']['B'])
        obs=observation(task,[],'A',0,'C0',validate_config({'task_ids':[task['id']]}))
        self.assertNotIn('at most 60 words',obs['messages'][0]['content'])
        self.assertEqual(json.loads(obs['messages'][-1]['content'])['history_policy']['updates_per_agent'],1)

    def test_offline_artifact_report_provenance_missingness_and_paired_contrasts(self):
        with tempfile.TemporaryDirectory() as d:
            store=EventStore(Path(d)/'events.sqlite')
            BatchRunner(store).run({'task_ids':['poetry-duet'],'adapter':'fixture','conditions':['C0','C2'],
                'steps':2,'unlock_step':1,'repeats':2},adapter=ProbabilityFixture())
            events=store.read()
            self.assertEqual(validate_hash_chain(events)['status'],'verified_export_segment')
            rows,tokens,contrasts=analyze_events(events)
            self.assertEqual(len(rows),16)
            self.assertTrue(all(r['status']=='valid' for r in rows))
            self.assertTrue(all(abs(r['artifact_h_renorm_bits']-1)<1e-10 for r in rows))
            self.assertEqual(len(contrasts),4)
            self.assertTrue(all(c['difference_in_changes_bits']==0 for c in contrasts))
            self.assertTrue(all(c['source_event_ids'] for c in contrasts))
            validation=run_analysis(events,Path(d)/'report','verified-test-input',plots=False)
            self.assertEqual(validation['invalid_probability_positions'],0)
            self.assertEqual(validation['semantic_entropy_status'],'not_computed')
            self.assertTrue((Path(d)/'report'/'report.html').exists())
            derived=[json.loads(line) for line in (Path(d)/'report'/'token-uncertainty-metrics.jsonl').read_text().splitlines()]
            self.assertEqual(len(derived),64)
            self.assertTrue(all(m['source_event_ids'] and m['semantic_entropy_claim'] is False for m in derived))
            no_probs=[dict(e,payload=dict(e['payload'],logprobs=None)) if e['kind']=='generation_result' else e for e in events]
            missing_rows,_,missing_contrasts=analyze_events(no_probs)
            self.assertTrue(all(r['artifact_h_renorm_bits'] is None for r in missing_rows))
            self.assertTrue(all(c['difference_in_changes_bits'] is None for c in missing_contrasts))
            incomplete=[e for e in events if not (e['kind']=='task_update' and e['payload']['condition_id']=='C0' and e['payload']['agent_id']=='A' and e['payload']['step']==1)]
            _,_,incomplete_contrasts=analyze_events(incomplete)
            self.assertTrue(all(c['difference_in_changes_bits'] is None for c in incomplete_contrasts if c['agent_id']=='A'))
            rejected=[dict(e,payload=dict(e['payload'],termination_state='stalled_no_generation',response_text='',done_reason='invalid_reference')) if e['kind']=='task_update' and e['payload']['step']==0 else e for e in events]
            rejected_rows,_,rejected_contrasts=analyze_events(rejected)
            self.assertTrue(all(c['partial_difference_in_changes_bits'] is None for c in rejected_contrasts))
            self.assertTrue(all(r['generated_response_text'] and r['rejection_reason']=='invalid_reference' for r in rejected_rows if r['step']==0))
            self.assertTrue(all(r['submission_state']=='rejected_generated_output' for r in rejected_rows if r['step']==0))
            self.assertTrue((Path(d)/'report'/'metric-catalog.csv').exists())
            mixed=[dict(e,payload=dict(e['payload'],model='different-model')) if e['kind']=='task_update' and e['payload']['agent_id']=='B' else e for e in events]
            with self.assertRaisesRegex(ValueError,'do not silently pool'):
                run_analysis(mixed,Path(d)/'mixed',plots=False)


if __name__=='__main__':unittest.main()
