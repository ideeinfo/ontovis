"""Serve fixed synthetic evidence and real project/session authorization."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from threading import Event
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from apps.api.authority import PreviewError
from apps.api.assistant_store import DEFAULT
from apps.api.simulated_faults import identity
from apps.api.user_sessions import MAX_SECONDS
from tests.test_analysis_drafts import snapshot
from tests.test_equipment_materials import DOC, VERSION, DocumentReader
from tests.test_scene_evidence import PDF, PNG
from tests.test_work_order_workflow_integration import ANALYSIS
from tests.work_order_13002_fixture import EndToEnd, PROJECT, serve_workbench


@contextmanager
def browser_site(public: Path):
    fixture = EndToEnd()
    fixture.setUpClass()
    try:
        fixture.setUp()
        source = fixture.source
        source.projects = {PROJECT:'Q-26 固定资料试验','B':'Q-26 另一项目'}
        source.permissions = {'writer':{PROJECT:'admin','B':'admin'}}
        fixture.admin = fixture.login('writer')
        blocked = Event()
        photo_blocked = Event()
        original = source.request
        fixed = DocumentReader()
        photo = DocumentReader()
        photo_id, photo_version = str(uuid4()), str(uuid4())
        photo.document.update(id=photo_id, kind='photo', name='Q-23 合成固定照片', current_version_id=photo_version)
        photo.version.update(id=photo_version, document_id=photo_id, preview_kind='image')
        sample = identity('13003')
        def project_object(uid, title, tag, kind):
            return dict(entityUid=uid,entityRevision='object:1',lifecycle='active',objectScope='definition',
                        displayName=title,objectKind=kind,reviewStatus='accepted',hasChildren=False,
                        identifiers=[dict(scheme='RDS',value=tag,role='primary',scopeType='project',
                                          scopeKey=PROJECT,status='accepted')])
        primary = project_object('fixture-surge-protector','合成浪涌保护器',sample['primaryRds'],'device')
        cabinet = project_object('fixture-cabinet','合成机舱动力柜','=WEC+CN1','cabinet')
        module = project_object('fixture-feedback-module','合成反馈输入模块','=WEC+CN1-105A3','device')
        terminal = project_object('fixture-terminal','合成端子','=WEC+CN1-X1','device')
        objects = {item['entityUid']:item for item in (primary,cabinet,module,terminal)}
        tags = {item['identifiers'][0]['value']:item for item in objects.values()}
        project_prefix = f'/api/v1/projects/{PROJECT}'
        drawing = 'fixture-13003-wiring'
        member_drawing = 'fixture-13003-member-wiring'
        member_title = 'Q-26 合成柜内接线图'
        power_title = 'Q-26 合成动力柜供电图'
        img = dict(content=PNG,mediaType='image/png',sha256=sha256(PNG).hexdigest())
        pdf = dict(content=PDF,mediaType='application/pdf',sha256=sha256(PDF).hexdigest())

        def request(account, method, path, body=None):
            url = urlsplit(path)
            route = url.path
            if route in (project_prefix+'/ontovis-assistant/service', project_prefix+'/ontovis-assistant/profile'):
                return dict(serviceRef=DEFAULT['serviceRef'],purpose='ontovis_analysis',serviceRevision='a'*64,
                            accessRevision=PROJECT+':admin',enabled=True,canRun=True,modelId='synthetic-model')
            if f'/documents/{photo_id}' in route:
                if photo_blocked.is_set():
                    raise PreviewError(403,'NOT_FOUND_OR_FORBIDDEN')
                return photo._request(method,path,body)
            if '/documents/' in route:
                if blocked.is_set():
                    raise PreviewError(403,'NOT_FOUND_OR_FORBIDDEN')
                return {'outline':[]} if route.endswith('/navigation') else fixed._request(method,path,body)
            if route in (f'/api/v1/drawings/{drawing}', f'/api/v1/drawings/{member_drawing}'):
                uid = route.rsplit('/', 1)[-1]
                return dict(project_code=PROJECT,drawing_uid=uid,
                            drawing_name=member_title if uid==member_drawing else '合成接线图',
                            source_page_number=90 if uid==member_drawing else 89)
            if route==project_prefix+'/objects':
                items = [tags[tag] for tag in parse_qs(url.query).get('primaryIdentifier',[]) if tag in tags]
                return dict(projectCode=PROJECT,items=items,total=len(items),nextCursor=None)
            if route==project_prefix+'/objects/resolve':
                return dict(projectCode=PROJECT,resolutionMode='live',items=[dict(resolution='exact',
                    requestedEntityUid=uid,canonicalEntityUid=uid,object=objects[uid],canonicalObject=objects[uid])
                    for uid in body['entityUids']])
            if route==f'/api/v1/drawings/{drawing}/object-locations':
                return {'items':[dict(id='position-'+item['entityUid'],project_code=PROJECT,drawing_uid=drawing,
                                      entity_uid=item['entityUid'],display_name=item['displayName'])
                                 for item in (primary, terminal)]}
            if route in (project_prefix+'/object-evidence/resolve', project_prefix+'/object-evidence/related'):
                subject = objects[body['entityUid']]
                main = subject==primary
                scope = dict(entityUid=body['entityUid'],entityRevision=body['expectedEntityRevision'],
                             installationContextId=None,hierarchyRevision=None)
                if route.endswith('/resolve'):
                    rows = [dict(title=power_title,evidenceRef=f'location:supply-{idx}',sourceRelation='direct',
                                 sourceEntityUid=primary['entityUid'],sourceEntityRevision=primary['entityRevision'],
                                 sourceTemplateRevision=None,sourceRevision=str(idx)*64,recordDigest=str(idx)*64,
                                 contentSha256=pdf['sha256'],availability='available',precision='page',region=None,
                                 pageNumber=88,mediaType='application/pdf',versionMode='current_content_snapshot')
                            for idx in (1,2)] if main else []
                    return {**scope,'complete':True,'versionMode':'current_content_snapshot','items':rows}
                def page(uid, title, match):
                    return dict(drawingUid=uid,title=title,drawingNumber=None,pageNumber=90 if uid==member_drawing else 89,sourceRevision='a'*64,
                                contentSha256=pdf['sha256'],availability='available',precision='page',region=None,
                                matchedObjects=[{**match,'viaEntityUid':primary['entityUid'],'viaName':primary['displayName']}])
                direct = {key:primary[key] for key in ('entityUid','entityRevision','displayName')} | {'relation':'self'}
                member = dict(entityUid='fixture-terminal',entityRevision='object:1',displayName='合成端子',relation='definition_descendant')
                items = [page(drawing,'合成接线图',direct),page(member_drawing,member_title,member)] if main else []
                return {**scope,'includeDescendants':True,'scopeComplete':True,'nextCursor':None,'snapshotRevision':'b'*64,
                        'total':len(items),'items':items}
            if route.endswith(('/object-locations','/installations','/objects','/result-relation-imports')):
                return {'items':[],'total':0,'nextCursor':None}
            return original(account,method,path,body)

        source.request = request

        def expire_browser_sessions():
            with fixture.sessions.lock:
                for session in fixture.sessions.rows.values():
                    if session.revision!=fixture.admin['revision'] and session.status=='active':
                        session.created = fixture.sessions.clock()-MAX_SECONDS-1

        commands = {'/test-evidence/withdraw-document':blocked.set,
                    '/test-evidence/withdraw-photo':photo_blocked.set,
                    '/test-evidence/expire-session':expire_browser_sessions,
                    '/test-evidence/withdraw-project':lambda:source.permissions['writer'].pop(PROJECT,None)}
        def restore():
            blocked.clear()
            photo_blocked.clear()
            source.permissions['writer'][PROJECT] = 'admin'

        with patch.object(source,'document_page',lambda *_args,**_kw:img,create=True), \
                patch.object(source,'source_bytes',lambda *_args,**_kw:pdf,create=True), \
                patch.object(source,'image',side_effect=AssertionError('Only drawing metadata is needed'),create=True), \
                patch('apps.api.analysis_media.drawing_image',return_value=img):
            record = '本单已记录合成处置结果，用于固定资料权限验收。'
            order = fixture.new('Q-26 合成历史工单')
            order = fixture.update(order,'accept')
            order = fixture.update(order,'record',text=record)
            order = fixture.ok('workflow-detail',dict(orderId=order['orderId']))
            board = snapshot()
            title = '13003 · 隔离固定资料权限验收'
            board.update(schemaVersion=2,projectCode=PROJECT,ontobaseConnectionId='ontobase-primary',title=title,
                reuse=dict(faultCode=sample['faultCode'],faultSystem=sample['sourceConnectionId'],equipment=sample['primaryRds'],
                           simulated=True,summary='固定手册、图纸和处置记录的隔离验收。',advice='核对权限变化后的固定来源。'))
            first = fixture.ok(ANALYSIS+'/create',dict(snapshot=board,requestId=str(uuid4())))
            analysis_id = first['analysisSessionId']
            keys = ('faultCode','sourceConnectionId','datasetId','datasetRevision','branch','timeFrom','timeTo')
            board['context'].update({key:sample[key] for key in keys},eventId=sample['datasetId']+'-event-1')
            entries = [
                ('document','Q-26 合成固定手册',dict(documentId=DOC,contentVersionId=VERSION,pageNumber=2)),
                ('photo',photo.document['name'],dict(sourceType='project_document',documentId=photo_id,contentVersionId=photo_version)),
                ('drawing','Q-26 合成固定图纸',dict(drawingUid=drawing,expectedContentSha256=pdf['sha256'])),
                ('work_order','Q-26 合成固定工单',dict(orderId=order['orderId'],expectedOrderRevision=order['orderRevision'])),
                ('alarm','13003 合成报警',{key:board['context'][key] for key in ('eventId','datasetId','datasetRevision')}),
                ('trend','合成接点状态',{key:sample[key] for key in ('datasetId','datasetRevision','timeFrom','timeTo')} | {'metricId':'device_feedback'}),
                ('object',primary['displayName'],dict(entityUid=primary['entityUid'],expectedEntityRevision=primary['entityRevision'])),
            ]
            frames = [dict(id='current',title='本次调查',x=-560,y=-500,width=1040,height=275),
                      dict(id='history',title='历史参考 · 合成处置',x=-560,y=60,width=700,height=550)]
            board['frames'] = frames
            board['cards'][0].update(x=180,y=103)
            positions = [(-540,-457,'current'),(-200,-457,'current'),(-540,103,'history'),
                         (-200,103,'history'),(140,-457,'current'),(-540,380,'history'),(-200,360,'history')]
            cards = {}
            for (kind,name,selector),(x,y,frame_id) in zip(entries,positions,strict=True):
                ref = fixture.ok(ANALYSIS+'/evidence/register',dict(analysisSessionId=analysis_id,
                    expectedAnalysisRevision=1,requestId=str(uuid4()),sourceKind=kind,selector=selector))
                cards[kind] = dict(title=name,id='fixed-'+kind,ref=ref['evidenceRefId'],x=x,y=y,width=320,height=205,frameId=frame_id)
                board['cards'].append(dict(kind=kind,title=name,id=cards[kind]['id'],x=x,y=y,
                    width=320,height=205,frameId=frame_id,pinned=False,source=dict(id=ref['evidenceRefId'],revision=ref['sourceRevision'],
                    system='ontovis' if kind in ('work_order','alarm','trend') else 'ontobase',projectCode=PROJECT,ontobaseConnectionId='ontobase-primary')))
            board['relations'].append({'id':'grouped-reference','from':cards['document']['id'],'to':cards['photo']['id'],
                                       'kind':'reference','origin':'manual','reason':'合成分组连线'})
            saved = fixture.ok(ANALYSIS+'/save',dict(analysisSessionId=analysis_id,expectedAnalysisRevision=1,
                snapshot=board,requestId=str(uuid4())))
            policy = fixture.ok('/api/workbench/assistant/policy',{})
            fixture.ok('/api/workbench/assistant/publish',dict(requestId=str(uuid4()),expectedRevision=policy['revision'],
                       expectedAccessRevision=policy['accessRevision'],expectedServiceRevision=policy['service']['serviceRevision'],
                       policy={**DEFAULT, 'enabled':True}))

            def verify():
                result = fixture.ok(ANALYSIS+'/detail',dict(analysisSessionId=analysis_id))
                assert (result['analysisRevision'],result['contentSha256'])==(2,saved['contentSha256'])
                ids = [card['ref'] for card in cards.values()]
                evidence = fixture.ok(ANALYSIS+'/evidence/batch',dict(analysisSessionId=analysis_id,evidenceRefIds=ids))
                assert [(item['evidenceRefId'],item['availability']) for item in evidence['items']]==[(key,'available') for key in ids]
                assert fixture.ok('workflow-detail',dict(orderId=order['orderId']))['snapshotSha256']==order['snapshotSha256']
                available = fixture.ok(ANALYSIS+'/history-candidates',dict(entry={key:sample[key] for key in ('datasetId','datasetRevision')}))
                assert [(item['analysisSessionId'],item['relevance']) for item in available['items']]==[(analysis_id,'same_event')]

            with serve_workbench(public.resolve(strict=True),fixture.sessions,commands) as origin:
                yield dict(origin=origin,analysisId=analysis_id,title=title,cards=cards,frames=frames,record=record,
                           memberDrawingTitle=member_title,powerDrawingTitle=power_title,
                           drawingObjectTitle=terminal['displayName'],
                           additionalObjectTitles=[cabinet['displayName'],module['displayName']],
                           datasetId=sample['datasetId'],datasetRevision=sample['datasetRevision']),restore,verify
    finally:
        fixture.doCleanups()
        fixture.tearDownClass()
