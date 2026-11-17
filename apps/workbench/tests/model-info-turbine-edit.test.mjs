import test from 'node:test';
import assert from 'node:assert/strict';
import {modelRepresentationFields} from '../src/resourceForms.ts';

const original={definitionEntityUid:'entity:00000000-0000-0000-0000-000000000001',modelCode:'original',representationType:'detailed'};
test('renaming while the source catalogue is unavailable does not clear association metadata',()=>{
  assert.deepEqual(modelRepresentationFields(original,original.definitionEntityUid,'detailed',[]),{representationType:'detailed'});
  assert.deepEqual(modelRepresentationFields({},'','',[]),{representationType:null});
});
test('clearing or changing an association sends the selected code, and cannot invent a missing definition',()=>{
  assert.deepEqual(modelRepresentationFields(original,'','',[]),{definitionEntityUid:null,modelCode:null,representationType:null});
  const target={definitionEntityUid:'entity:00000000-0000-0000-0000-000000000002',modelCode:'new'};
  assert.deepEqual(modelRepresentationFields(original,target.definitionEntityUid,'appearance',[target]),{...target,representationType:'appearance'});
  assert.throws(()=>modelRepresentationFields(original,'missing','detailed',[]),error=>error.code==='ENGINEERING_CHANGED');
});
test('project application identities never become engineering object identities',()=>{
  const applicationOnly={catalogueKey:'application:00000000-0000-0000-0000-000000000002',definitionEntityUid:null,modelCode:'SPEC-1',
    projectApplicationRef:{applicationId:'00000000-0000-0000-0000-000000000002',applicationRevisionId:'fixed',specificationRevisionId:'spec'}};
  assert.throws(()=>modelRepresentationFields({},applicationOnly.projectApplicationRef.applicationId,'appearance',[applicationOnly]),error=>error.code==='ENGINEERING_CHANGED');
  assert.deepEqual(modelRepresentationFields(original,original.definitionEntityUid,'detailed',[applicationOnly]),{representationType:'detailed'});
});
