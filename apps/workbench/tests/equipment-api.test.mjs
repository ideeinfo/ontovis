import assert from 'node:assert/strict';
import test from 'node:test';
import {WorkbenchApi} from '../src/api.ts';
import {EquipmentApi} from '../src/equipmentApi.ts';

const selection={entityUid:'shared-sensor',expectedEntityRevision:'entity:4',installationContextId:null,
  expectedHierarchyRevision:null,photoPurpose:'object_location'};
const photo={evidenceRef:'photo:fixture',sourceRevision:'a'.repeat(64),contentVersionId:'fixed-photo',
  sourceSha256:'b'.repeat(64),selector:{displayRevision:'c'.repeat(64)}};
const project={ontobaseConnectionId:'fixture-source',projectCode:'fixture-project'};

test('equipment photos accept JPEG previews and PNG originals with the fixed reference and project scope',async()=>{
  for(const [full,mime] of [[false,'image/jpeg'],[false,'image/webp'],[true,'image/png']]){
    let sent;
    const api=new WorkbenchApi(async(path,options)=>{sent={path,body:JSON.parse(options.body)};
      return new Response('synthetic-image',{headers:{'Content-Type':mime,'X-Session-Revision':'session:1'}});});
    api.session('session:1');api.selectProject(project);
    const blob=await new EquipmentApi(api).photoContent(selection,photo,full);
    assert.equal(blob.type,mime);assert.equal(await blob.text(),'synthetic-image');
    assert.equal(sent.path,'/api/workbench/objects/photos/content');
    assert.deepEqual(sent.body,{...selection,evidenceRef:photo.evidenceRef,expectedSourceRevision:photo.sourceRevision,
      expectedContentVersionId:photo.contentVersionId,expectedSourceSha256:photo.sourceSha256,
      expectedDisplayRevision:photo.selector.displayRevision,representation:full?'display':'preview',
      projectRef:project,expectedSessionRevision:'session:1'});
  }
});

test('a late equipment photo is discarded after project selection changes',async()=>{
  let finish;
  const api=new WorkbenchApi(()=>new Promise(resolve=>{finish=resolve;}));api.session('session:1');api.selectProject(project);
  const pending=new EquipmentApi(api).photoContent(selection,photo);
  api.selectProject({...project,projectCode:'another-project'});
  finish(new Response('synthetic-image',{headers:{'Content-Type':'image/jpeg','X-Session-Revision':'session:1'}}));
  await assert.rejects(pending,{name:'AbortError'});
});

test('source application binding writes only its fixed reference and geometry mappings',async()=>{
  let sent;
  const api=new WorkbenchApi(async(path,options)=>{sent={path,body:JSON.parse(options.body)};return new Response('{}',{headers:{'Content-Type':'application/json','X-Session-Revision':'session:1'}});});
  api.session('session:1');api.selectProject(project);
  const projectApplicationRef={applicationId:'source-application',applicationRevisionId:'fixed-application',specificationRevisionId:'fixed-specification'};
  const models=[{modelVersionId:'fixed-model',mappings:[]}];
  await new EquipmentApi(api).save('binding','binding:1',{displayName:'Never write source names',objectKind:'pump',rootDefinition:null,projectApplicationRef,models});
  assert.equal(sent.path,'/api/workbench/equipment/configurations/save');assert.deepEqual(sent.body.snapshot,{projectApplicationRef,models});assert.deepEqual(sent.body.projectRef,project);
});

test('shared photo pages and renditions keep source identity and request limits',async()=>{
  const sent=[];
  const api=new WorkbenchApi(async(path,options)=>{sent.push({path,body:JSON.parse(options.body)});return new Response(path.endsWith('/content')?'image':'{}',{headers:{'Content-Type':path.endsWith('/content')?'image/jpeg':'application/json','X-Session-Revision':'session:1'}});});
  api.session('session:1');api.selectProject(project);
  const service=new EquipmentApi(api),{photoPurpose,...identity}=selection;
  const shared={documentId:'doc',contentVersionId:'version',renditionId:'display',displayRevision:'digest'};
  await service.sharedPhotos(identity);await service.sharedRegions(identity,shared);await service.sharedContent(identity,shared,'thumbnail');
  assert.equal(sent[0].body.limit,12);assert.equal(sent[1].body.limit,50);assert.equal(sent[2].body.representation,'thumbnail');assert.equal(sent[2].body.expectedDisplayRevision,'digest');assert.equal(sent[2].body.contentVersionId,'version');
  assert.ok(sent.every(call=>call.body.entityUid===identity.entityUid&&call.body.projectRef.projectCode===project.projectCode));
});
