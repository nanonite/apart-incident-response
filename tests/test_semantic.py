from copy import deepcopy
import math
import unittest
from apart_incident_response.semantic import (SemanticJudgment, EmpiricalClusters, ObservedSequenceMass,
    partition_samples, entropy_metric, bootstrap_interval, validate_samples)


def samples():
    return [dict(sample_id=str(i),context_hash='fixed',task_id='repair',task_version='v1',
        model_metadata={'digest':'model1'},model_config={'temperature':.6},prompt_version='p1',
        agent_role='solver',condition_id='C2',source_event_ids=['observation'],extraction_version='manual-v1',
        response_text=text,raw_response=text,status='valid',seed=i,source='fixture')
        for i,text in enumerate(['Repair blue','Blue repair','Repair amber'])]


def judgments():
    return [SemanticJudgment('0','1','fixed',True,True,'human-test-v1','Equivalent chosen plan'),
            SemanticJudgment('0','2','fixed',False,False,'human-test-v1','Different plan'),
            SemanticJudgment('1','2','fixed',False,False,'human-test-v1','Different plan')]


class SemanticTests(unittest.TestCase):
    def test_semantic_groups_and_empirical_entropy(self):
        rows=samples(); part=partition_samples(rows,judgments(),'repair-meaning-v1')
        state=EmpiricalClusters().estimate(rows,part)
        self.assertEqual(sorted(state['probabilities'].values()),[1/3,2/3])
        result=entropy_metric(state)
        self.assertAlmostEqual(result['value'],-(2/3)*math.log2(2/3)-(1/3)*math.log2(1/3))
        self.assertEqual(result['source_event_ids'],['observation'])
        self.assertEqual(result['source'],'fixture')

    def test_context_role_model_and_task_mixing_is_rejected(self):
        for field in ('context_hash','agent_role','model_metadata','model_config','task_version','prompt_version','extraction_version'):
            rows=samples(); rows[1][field]='changed'
            with self.assertRaises(ValueError,msg=field):
                validate_samples(rows)

    def test_missing_judgments_one_way_entailment_and_partition_coverage(self):
        rows=samples()
        with self.assertRaises(ValueError):
            partition_samples(rows,judgments()[:1],'v1')
        js=judgments(); js[0]=SemanticJudgment('0','1','fixed',True,False,'human-test-v1','One way only')
        part=partition_samples(rows,js,'v1')
        self.assertEqual(len(part['clusters']),3)
        part['clusters']['0'].append('1')
        with self.assertRaises(ValueError):
            EmpiricalClusters().estimate(rows,part)

    def test_failures_are_not_semantic_classes_and_n_one_is_null(self):
        rows=samples(); rows[0]['status']='timeout'
        with self.assertRaises(ValueError):
            validate_samples(rows)
        rows=samples()[:1]
        part=partition_samples(rows,[],'single-v1')
        self.assertIsNone(entropy_metric(EmpiricalClusters().estimate(rows,part))['value'])

    def test_likelihood_adapter_requires_provenance_and_labels_observed_support(self):
        rows=samples(); part=partition_samples(rows,judgments(),'v1')
        with self.assertRaises(ValueError):
            ObservedSequenceMass().estimate(rows,part)
        for row,p in zip(rows,[.2,.2,.1]):
            row['sequence_likelihood']={'log_probability':math.log(p),'reliable':True,
                'scope':'complete_raw_sequence','provider_version':'test-fixture-v1'}
        state=ObservedSequenceMass().estimate(rows,part)
        self.assertAlmostEqual(state['probabilities']['0'],.8)
        self.assertFalse(state['semantic_entropy_claim'])
        self.assertEqual(state['unobserved_probability_mass'],'not_estimated')

    def test_confidence_interval_records_scope_and_seed(self):
        rows=samples();part=partition_samples(rows,judgments(),'v1')
        one=bootstrap_interval(rows,part,draws=100,seed=4)
        self.assertEqual(one,bootstrap_interval(rows,part,draws=100,seed=4))
        self.assertIn('judge error',one['limitation'])
        self.assertEqual(one['level'],.95)


if __name__=='__main__':
    unittest.main()
