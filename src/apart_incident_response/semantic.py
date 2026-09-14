"""Artifact-only semantic analysis contracts. No model, runtime, or storage imports."""
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
import random
from typing import Protocol


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


@dataclass(frozen=True)
class SemanticJudgment:
    left_id: str
    right_id: str
    context_hash: str
    left_entails_right: bool
    right_entails_left: bool
    judge_version: str
    rationale: str


class EquivalenceJudge(Protocol):
    version: str
    def judge(self, left: dict, right: dict, context: dict) -> SemanticJudgment: ...


class ProbabilityModel(Protocol):
    version: str
    def estimate(self, samples: list[dict], partition: dict) -> dict: ...


def validate_samples(samples):
    if not samples:
        raise ValueError('No samples supplied')
    seen, strata = set(), set()
    required = ('sample_id','context_hash','task_id','task_version','model_metadata','model_config',
                'prompt_version','agent_role','condition_id','source_event_ids','extraction_version',
                'response_text','status','seed','source')
    for sample in samples:
        if any(key not in sample for key in required):
            raise ValueError('Missing semantic sample provenance')
        if not sample['sample_id'] or sample['sample_id'] in seen:
            raise ValueError('Sample IDs must be nonempty and unique')
        seen.add(sample['sample_id'])
        if sample['status'] != 'valid' or not sample['response_text'].strip():
            raise ValueError('Partition only valid nonempty samples; report failures separately')
        if not sample['source_event_ids']:
            raise ValueError('Samples need source event IDs')
        strata.add(fingerprint({k:sample[k] for k in ('context_hash','task_id','task_version','model_metadata',
            'model_config','prompt_version','agent_role','condition_id','extraction_version','source')}))
    if len(strata) != 1:
        raise ValueError('Fixed-context samples cannot mix contexts, models, roles, tasks, or extraction rules')
    return samples[0]['context_hash']


def partition_samples(samples, judgments, rule_version):
    """Deterministic complete-link grouping; contradictory/missing judgments fail closed."""
    context_hash = validate_samples(samples)
    if not rule_version:
        raise ValueError('A partition rule version is required')
    ids = {s['sample_id'] for s in samples}
    evidence = {}
    versions = set()
    for j in judgments:
        if not isinstance(j, SemanticJudgment) or j.left_id not in ids or j.right_id not in ids or j.left_id==j.right_id:
            raise ValueError('Invalid judgment sample reference')
        if j.context_hash != context_hash or not j.judge_version or type(j.left_entails_right) is not bool or type(j.right_entails_left) is not bool:
            raise ValueError('Invalid judgment context/version/decision')
        key = tuple(sorted((j.left_id,j.right_id)))
        if key in evidence:
            raise ValueError('Duplicate pair judgment')
        evidence[key] = j.left_entails_right and j.right_entails_left
        versions.add(j.judge_version)
    if len(versions)>1 or len(evidence)!=len(ids)*(len(ids)-1)//2:
        raise ValueError('Require complete pair judgments from one judge version')
    clusters = []
    for sample_id in sorted(ids):
        compatible = next((c for c in clusters if all(evidence[tuple(sorted((sample_id,other)))] for other in c)), None)
        if compatible is None:
            clusters.append([sample_id])
        else:
            compatible.append(sample_id)
    result = {'context_hash':context_hash,'rule_version':rule_version,'algorithm':'complete-link-sorted-v1',
        'judge_versions':sorted(versions),'clusters':{str(i):c for i,c in enumerate(clusters)},
        'judgments':[asdict(j) for j in judgments], 'sample_ids':sorted(ids),
        'limitation':'Pairwise entailment may be nontransitive; grouping depends on the recorded algorithm.'}
    result['partition_id'] = fingerprint(result)
    return result


def validate_partition(samples, partition):
    context_hash=validate_samples(samples)
    if partition.get('context_hash')!=context_hash or not partition.get('rule_version') or not partition.get('partition_id'):
        raise ValueError('Invalid partition provenance')
    members=[sample_id for c in partition['clusters'].values() for sample_id in c]
    if len(members)!=len(set(members)) or set(members)!={s['sample_id'] for s in samples}:
        raise ValueError('Partition must assign every sample exactly once')
    if any(not c for c in partition['clusters'].values()):
        raise ValueError('Empty cluster')


def probability_state(samples, partition, probabilities, version, scope):
    return {'probabilities':probabilities, 'probability_model_version':version, 'scope':scope,
            'partition_id':partition['partition_id'],'context_hash':partition['context_hash'],
            'sample_count':len(samples), 'sample_ids':[s['sample_id'] for s in samples],
            'source_event_ids':list(dict.fromkeys(i for s in samples for i in s['source_event_ids'])),
            'source':samples[0]['source'], 'provenance':{k:samples[0][k] for k in ('task_id','task_version',
                'model_metadata','model_config','prompt_version','agent_role','condition_id','extraction_version')}}


class EmpiricalClusters:
    version='semantic-frequency-v1'
    def estimate(self, samples, partition):
        validate_partition(samples,partition)
        return probability_state(samples,partition,{k:len(c)/len(samples) for k,c in partition['clusters'].items()},
            self.version,'empirical_fixed_context_semantic_clusters')


class ObservedSequenceMass:
    """Explicitly normalized observed support, not full-distribution semantic entropy."""
    version='observed-sequence-mass-v1'
    def estimate(self, samples, partition):
        validate_partition(samples,partition)
        mapping={i:k for k,c in partition['clusters'].items() for i in c}
        unique={}
        for s in samples:
            likelihood=s.get('sequence_likelihood') or {}
            value=likelihood.get('log_probability')
            if likelihood.get('reliable') is not True or likelihood.get('scope')!='complete_raw_sequence' or not likelihood.get('provider_version'):
                raise ValueError('Reliable complete-sequence likelihood provenance is required')
            if type(value) not in (int,float) or not math.isfinite(value) or value>0 or not s.get('raw_response'):
                raise ValueError('Invalid sequence probability')
            key=s['raw_response']
            pair=(mapping[s['sample_id']],value)
            if key in unique and unique[key]!=pair:
                raise ValueError('Identical sequence has inconsistent likelihood or partition')
            unique[key]=pair
        maximum=max(value for _,value in unique.values())
        mass={key:0.0 for key in partition['clusters']}
        for cluster,value in unique.values():
            mass[cluster]+=math.exp(value-maximum)
        total=sum(mass.values())
        state=probability_state(samples,partition,{k:v/total for k,v in mass.items()},self.version,
                                'normalized_observed_sequence_support_proxy')
        state['unobserved_probability_mass']='not_estimated'
        state['semantic_entropy_claim']=False
        return state


def entropy_metric(state, base=2):
    p=list(state['probabilities'].values())
    if not p or any(not math.isfinite(x) or x<0 for x in p) or not math.isclose(sum(p),1,abs_tol=1e-9):
        raise ValueError('Entropy requires normalized finite probabilities')
    if not math.isfinite(base) or base<=1:
        raise ValueError('Entropy base must exceed one')
    n=state['sample_count']
    return {**state,'metric_version':'cluster-shannon-v1','log_base':base,'unit':'bits' if base==2 else 'nats' if base==math.e else f'log_base_{base}',
        'value':-sum(x*math.log(x,base) for x in p if x) if n>=2 else None,
        'status':'descriptive' if n>=2 else 'insufficient_samples',
        'confidence_interval':None, 'limitation':'Finite-sample uncertainty estimate; not an epistemic/aleatoric decomposition.'}


def bootstrap_interval(samples, partition, draws=500, seed=17, level=0.95):
    validate_partition(samples,partition)
    if type(draws) is not int or not 20<=draws<=10000 or not 0<level<1:
        raise ValueError('Invalid bootstrap settings')
    if len(samples)<2:
        return {'interval':None,'reason':'insufficient_samples'}
    assignments=[key for key,cluster in partition['clusters'].items() for _ in cluster]
    rng=random.Random(seed)
    values=[]
    for _ in range(draws):
        counts=Counter(rng.choices(assignments,k=len(assignments)))
        values.append(-sum((n/len(assignments))*math.log2(n/len(assignments)) for n in counts.values()))
    values.sort()
    alpha=(1-level)/2
    return {'interval':[values[int(alpha*(draws-1))],values[int((1-alpha)*(draws-1))]],
        'method':'conditional_fixed_partition_percentile_bootstrap','level':level,'seed':seed,'draws':draws,
        'limitation':'Does not cover judge error, unseen meanings, dependent draws, or changing prompts.'}
