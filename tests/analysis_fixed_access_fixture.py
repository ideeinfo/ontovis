"""Serve fixed synthetic evidence and real project/session authorization."""
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from threading import Event
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from apps.api.authority import PreviewError
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
        sample = identity('13001')
        primary = dict(entityUid='fixture-13001-primary',entityRevision='object:1',lifecycle='active',
                       objectScope='definition',displayName='合成测温对象',objectKind='device',reviewStatus='accepted',
                       hasChildren=False,identifiers=[dict(scheme='RDS',value=sample['primaryRds'],role='primary',
                                                          scopeType='project',scopeKey=PROJECT,status='accepted')])
        project_prefix = f'/api/v1/projects/{PROJECT}'
        drawing = 'fixture-13001-wiring'
        member_drawing = 'fixture-13001-member-wiring'
        member_title = 'Q-26 合成柜内接线图'
        img = dict(content=PNG,mediaType='image/png',sha256=sha256(PNG).hexdigest())
        pdf = dict(content=PDF,mediaType='application/pdf',sha256=sha256(PDF).hexdigest())

        def request(account, method, path, body=None):
            url = urlsplit(path)
            route = url.path
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
                            drawing_name=member_title if uid==member_drawing else '合成接线图',source_page_number=89)
            if route==project_prefix+'/objects' and parse_qs(url.query).get('primaryIdentifier')==[sample['primaryRds']]:
                return dict(projectCode=PROJECT,items=[primary],total=1,nextCursor=None)
            if route==project_prefix+'/objects/resolve' and body['entityUids']==[primary['entityUid']]:
                return dict(projectCode=PROJECT,resolutionMode='live',items=[dict(resolution='exact',
                    requestedEntityUid=primary['entityUid'],canonicalEntityUid=primary['entityUid'],object=primary,canonicalObject=primary)])
            if route in (project_prefix+'/object-evidence/resolve', project_prefix+'/object-evidence/related'):
                assert body['entityUid']==primary['entityUid']
                scope = dict(entityUid=body['entityUid'],entityRevision=body['expectedEntityRevision'],
                             installationContextId=None,hierarchyRevision=None)
                if route.endswith('/resolve'):
                    return {**scope,'complete':True,'versionMode':'current_content_snapshot','items':[]}
                def page(uid, title, match):
                    return dict(drawingUid=uid,title=title,drawingNumber=None,pageNumber=89,sourceRevision='a'*64,
                                contentSha256=pdf['sha256'],availability='available',precision='page',region=None,
                                matchedObjects=[{**match,'viaEntityUid':primary['entityUid'],'viaName':primary['displayName']}])
                direct = {key:primary[key] for key in ('entityUid','entityRevision','displayName')} | {'relation':'self'}
                member = dict(entityUid='fixture-terminal',entityRevision='object:1',displayName='合成端子',relation='definition_descendant')
                return {**scope,'includeDescendants':True,'scopeComplete':True,'nextCursor':None,'snapshotRevision':'b'*64,'total':2,
                        'items':[page(drawing,'合成接线图',direct),page(member_drawing,member_title,member)]}
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
            title = '13001 · 隔离固定资料权限验收'
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
                ('alarm','13001 合成报警',{key:board['context'][key] for key in ('eventId','datasetId','datasetRevision')}),
                ('trend','合成传感器温度',{key:sample[key] for key in ('datasetId','datasetRevision','timeFrom','timeTo')} | {'metricId':'sensor_temperature'}),
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
                           memberDrawingTitle=member_title,datasetId=sample['datasetId'],datasetRevision=sample['datasetRevision']),restore,verify
    finally:
        fixture.doCleanups()
        fixture.tearDownClass()
