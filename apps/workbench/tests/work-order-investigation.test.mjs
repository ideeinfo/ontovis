import assert from 'node:assert/strict';
import test from 'node:test';
import {investigationComplete,photoCitation} from '../src/workOrderInvestigation.ts';

const complete={hypotheses:[{id:'h1',description:'Synthetic cause',status:'supported',basis:'Synthetic observation'}],steps:[{id:'s1',title:'Read reference',targetKey:'CN1',outcome:'gap',result:'Applicability remains unverified'}],conclusion:'Demo completed with gaps',reviewBasis:'Synthetic review'};

test('review requires recorded step outcomes, conclusion and review basis',()=>{
  assert.equal(investigationComplete(complete),true);
  for(const patch of [{conclusion:' '},{reviewBasis:''},{steps:[]},{hypotheses:[]},{steps:[{...complete.steps[0],outcome:'pending'}]},{steps:[{...complete.steps[0],result:''}]},{hypotheses:[{...complete.hypotheses[0],basis:''}]}])assert.equal(investigationComplete({...complete,...patch}),false);
  assert.equal(investigationComplete({...complete,hypotheses:[{...complete.hypotheses[0],status:'candidate',basis:''}]}),true);
});
test('photo citation includes object identity and the fixed version, without asserting a root cause',()=>{
  const citation=photoCitation({title:'Synthetic photo',versionNumber:2,evidenceRef:'synthetic-evidence',contentVersionId:'synthetic-fixed-v2',selector:{displayRevision:'a'.repeat(64)}},{item:{entityUid:'synthetic-object',displayName:'Example object'}});
  for(const value of ['Example object','synthetic-object','v2','synthetic-evidence','synthetic-fixed-v2','a'.repeat(64)])assert.ok(citation.includes(value));
});
