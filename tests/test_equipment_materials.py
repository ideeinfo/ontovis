"""Read-only material relay, fixed documents and ordinary analysis-photo contracts."""
import copy
from hashlib import sha256
from io import BytesIO
from email.message import Message
from random import Random
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4

from apps.api.authority import Authority, PreviewError
from apps.api.equipment_reader import EquipmentReader
from apps.api.fixed_documents import FixedDocuments
from apps.api.analysis_evidence import validate_descriptor
from apps.api.analysis_source_reader import AnalysisSourceReader
from apps.api.analysis_queries import recommendations
from tests import test_equipment_http as base, test_scene_engineering as engineering
from tests.test_scene_evidence import PNG

SPEC, REV, TEMPLATE, DOC, VERSION = [str(uuid4()) for _ in range(5)]
MODEL = dict(specificationId=SPEC, revisionId=REV, headRevisionId=REV, templateRevisionId=TEMPLATE,
    name='Synthetic independent model', code='SYNTHETIC', objectKind='equipment', nature='equipment', status='active', revision=1,
    classificationRef={'revisionId':str(uuid4()), 'code':'E'}, manufacturer=None)
ROLES = [dict(value='model',kind='model',name=None),dict(value='root',kind='root',name=None),
         dict(value='role:cabinet',kind='role',name='Synthetic cabinet')]
MATERIAL = dict(documentId=DOC,contentVersionId=VERSION,title='Synthetic PDF',kind='pdf',documentKind='manual',
    versionNumber=2,pageCount=3,availability='available',scopes=['role:cabinet'],origins=['model'])


def specification_revision(model, values=()):
    snapshot_keys=('name','manufacturer','objectKind','nature','classificationRef','templateRevisionId')
    snapshot={key:model.get(key) for key in snapshot_keys}|{'values':list(values)}
    return {key:value for key,value in model.items() if key not in snapshot_keys}|{'snapshot':snapshot}


class DocumentReader:
    prefix='/api/v1/projects/P'
    project_code='P'
    def __init__(self):
        self.document=dict(id=DOC,name='Synthetic material',status='active',kind='manual',current_version_id=str(uuid4()))
        self.version=dict(id=VERSION,document_id=DOC,version_number=2,preview_kind='pdf',page_count=3,
                          preview_error=None,source_sha256='a'*64)
        self.calls=[]
        self.authority=SimpleNamespace(document_page=Mock(return_value=dict(content=PNG,mediaType='image/png',sha256='b'*64)))
    def _request(self,method,path,body=None):
        self.calls.append((method,path,body))
        return {'item':copy.deepcopy(self.version if '/versions/' in path else self.document)}


class FixedMaterialTests(unittest.TestCase):
    def test_pdf_page_and_photo_use_fixed_version_not_current_head_or_location(self):
        source=DocumentReader(); reader=FixedDocuments(source)
        fixed=reader.metadata(dict(documentId=DOC,contentVersionId=VERSION,pageNumber=2))
        self.assertTrue(fixed['newerVersionAvailable']);self.assertIsNone(fixed['selector'])
        reader.content(dict(documentId=DOC,contentVersionId=VERSION,pageNumber=2,sourceSha256='a'*64))
        path=source.authority.document_page.call_args.args[0]
        self.assertEqual(parse_qs(urlsplit(path).query),{'version_id':[VERSION],'rendition':['display'],'page':['2']})
        self.assertEqual(source.authority.document_page.call_args.kwargs,{'photo':False})
        source.version['preview_kind']='image'
        reader.content(dict(documentId=DOC,contentVersionId=VERSION))
        self.assertEqual(source.authority.document_page.call_args.kwargs,{'photo':True})

    def test_invalid_input_and_changed_identity_or_digest_cannot_read_bytes(self):
        source=DocumentReader();reader=FixedDocuments(source);body=dict(documentId=DOC,contentVersionId=VERSION)
        for change in ({'pageNumber':True},{'pageNumber':0},{'sourceSha256':'bad'},{'url':'https://outside.invalid'}):
            with self.subTest(change=change),self.assertRaises(PreviewError) as error:reader.content(body|change)
            self.assertEqual(error.exception.status,422)
        self.assertEqual(source.calls,[])
        for field,value,status in [('document_id',str(uuid4()),409),('source_sha256','c'*64,409),('preview_error','failed',409)]:
            with self.subTest(field=field):
                before=source.version[field];source.version[field]=value
                with self.assertRaises(PreviewError) as error:reader.content(body|{'sourceSha256':'a'*64})
                self.assertEqual(error.exception.status,status);source.version[field]=before
        source.document['status']='recycled'
        with self.assertRaises(PreviewError) as error:reader.content(body)
        self.assertEqual(error.exception.status,410);source.authority.document_page.assert_not_called()

    def test_current_fixed_photo_uses_version_from_document_response(self):
        source = DocumentReader()
        document = dict(source.document, current_version_id=VERSION)
        version = dict(source.version, preview_kind='image')
        source._request = Mock(return_value={'item':document,'current_version':version})
        body = dict(documentId=DOC,contentVersionId=VERSION,sourceSha256='a'*64)
        reader = FixedDocuments(source)
        self.assertEqual(reader.metadata(body)['kind'],'photo')
        source._request.assert_called_once_with('GET',f'{source.prefix}/documents/{DOC}')
        version['source_sha256'] = 'd'*64
        with self.assertRaises(PreviewError) as failure:
            reader.metadata(body)
        self.assertEqual(failure.exception.code,'SOURCE_CHANGED')
        source.authority.document_page.assert_not_called()

    def test_photo_preview_is_bounded_cached_and_still_revalidates_before_every_read(self):
        from PIL import Image
        source=DocumentReader();source.version['preview_kind']='image'
        image=BytesIO();Image.new('RGB',(5000,20),'green').save(image,'PNG')
        source.authority.document_page.return_value=dict(content=image.getvalue(),mediaType='image/png',sha256='b'*64)
        fixed=FixedDocuments(source);body=dict(documentId=DOC,contentVersionId=VERSION,sourceSha256='a'*64,representation='preview')
        first=fixed.content(body);self.assertEqual(first['mediaType'],'image/jpeg')
        with Image.open(BytesIO(first['content'])) as preview:self.assertEqual(preview.width,4096)
        self.assertEqual(fixed.content(body),first);self.assertEqual(source.authority.document_page.call_count,1)
        self.assertEqual(len(source.calls),4)
        self.assertEqual(fixed.content(body|{'representation':'display'})['content'],image.getvalue())
        source.document['status']='recycled'
        with self.assertRaises(PreviewError):fixed.content(body)
        self.assertEqual(source.authority.document_page.call_count,2)
        with self.assertRaises(PreviewError):fixed.content(body|{'representation':'arbitrary'})

    def test_full_resolution_photo_compresses_only_normal_photos_and_keeps_pixel_dimensions(self):
        from PIL import Image

        source = DocumentReader()
        source.document['kind'] = 'photo'
        source.version['preview_kind'] = 'image'
        size = (1600, 1000)
        exif = Image.Exif()
        exif[274] = 6
        raw = BytesIO()
        Image.frombytes('RGB', size, Random(42).randbytes(size[0] * size[1] * 3)).save(raw, 'PNG', exif=exif)
        data = raw.getvalue()
        fixed_sha = sha256(data).hexdigest()
        self.assertGreater(len(data), 4_000_000)
        source.authority.document_page.return_value = {'content': data, 'mediaType': 'image/png', 'sha256': fixed_sha}
        reader = FixedDocuments(source)
        body = dict(documentId=DOC, contentVersionId=VERSION, sourceSha256='a' * 64)
        request = {**body, 'representation': 'full_resolution'}
        compressed = reader.content(request)
        self.assertLess(len(compressed['content']), 4_000_000)
        self.assertEqual(compressed['sha256'], sha256(compressed['content']).hexdigest())
        self.assertEqual(compressed['fixedPhotoSha256'], fixed_sha)
        self.assertNotEqual(compressed['sha256'], fixed_sha)
        with Image.open(BytesIO(compressed['content'])) as image:
            self.assertEqual(image.size, size)
            self.assertEqual(image.getexif()[274], 6)
        self.assertEqual(reader.content(body)['content'], data)
        # The same cached content is returned byte-for-byte for a fixed spherical version.
        source.version['media_projection'] = 'spherical_equirectangular'
        self.assertEqual(reader.content(request)['content'], data)
        self.assertEqual(reader.content(request | {'representation': 'full_resolution_avif'})['content'], data)
        source.version['media_projection'] = None
        source.document['kind'] = 'other'
        self.assertEqual(reader.content(request)['content'], data)
        source.document['status'] = 'recycled'
        with self.assertRaises(PreviewError) as error:
            reader.content(request)
        self.assertEqual(error.exception.status, 410)

    def test_avif_is_a_separate_full_resolution_representation_with_a_compatible_fallback(self):
        from PIL import Image, features
        from apps.api.analysis_media import encode_full_resolution

        source = DocumentReader()
        source.document['kind'] = 'photo'
        source.version['preview_kind'] = 'image'
        size = (1600, 1000)
        raw = BytesIO()
        Image.frombytes('RGB', size, Random(17).randbytes(size[0] * size[1] * 3)).save(raw, 'PNG')
        original = raw.getvalue()
        digest = sha256(original).hexdigest()
        source_value = {'content': original, 'mediaType': 'image/png', 'sha256': digest}
        source.authority.document_page.return_value = source_value
        reader = FixedDocuments(source)
        body = dict(documentId=DOC, contentVersionId=VERSION, sourceSha256='a' * 64)
        fallback = reader.content({**body, 'representation': 'full_resolution'})
        variant = reader.content({**body, 'representation': 'full_resolution_avif'})
        for value in (fallback, variant):
            self.assertEqual(value['fixedPhotoSha256'], digest)
            self.assertEqual(value['sha256'], sha256(value['content']).hexdigest())
            self.assertLess(len(value['content']), 4_000_000)
            with Image.open(BytesIO(value['content'])) as image:
                self.assertEqual(image.size, size)
        self.assertEqual(variant['mediaType'], 'image/avif' if features.check('avif') else 'image/jpeg')
        self.assertEqual(fallback['mediaType'], 'image/jpeg')
        with patch('PIL.features.check', return_value=False):
            self.assertEqual(encode_full_resolution(source_value, prefer_avif=True),
                             (fallback['content'], fallback['mediaType']))

    def test_ordinary_photo_registers_whole_image_and_never_claims_old_object_region(self):
        reader=DocumentReader();reader.version['preview_kind']='image'
        source=AnalysisSourceReader(reader,None,None,lambda:None,'owner')
        selector=dict(sourceType='project_document',documentId=DOC,contentVersionId=VERSION)
        descriptor=source.resolve('photo',selector);validate_descriptor('photo',descriptor)
        self.assertEqual(set(descriptor),set(selector)|{'sourceSha256'})
        value=source.read('photo',descriptor);self.assertIsNone(value['selector'])
        self.assertEqual(source.content('photo',descriptor)['content'],PNG)
        for change in ({'bbox':[0,0,1,1]},{'entityUid':'device'},{'evidenceRef':'forged'},{'renditionId':'forged'}):
            with self.assertRaises(PreviewError):validate_descriptor('photo',descriptor|change)

    def test_source_photo_binary_accepts_actual_mime_but_pdf_requires_png(self):
        authority=Authority('http://127.0.0.1:1');authority.token='synthetic-only'
        for mime,data in [('image/png',PNG),('image/jpeg',b'\xff\xd8\xffsynthetic'),('image/webp',b'RIFF1234WEBPsynthetic')]:
            headers=Message();headers['Content-Type']=mime
            response=Mock();response.headers=headers;response.read.return_value=data
            response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
            with patch.object(authority.opener,'open',return_value=response):
                self.assertEqual(authority.document_page('/fixed',photo=True)['mediaType'],mime)
                if mime!='image/png':
                    with self.assertRaises(PreviewError):authority.document_page('/fixed')
        headers.replace_header('Content-Type','text/html')
        with patch.object(authority.opener,'open',return_value=response),self.assertRaises(PreviewError):authority.document_page('/fixed',photo=True)

    def test_project_library_includes_unlinked_unpublished_files_and_keeps_cursor(self):
        reader=DocumentReader()
        rows=[dict(id=DOC,current_version_id=VERSION,name='Unlinked PDF',preview_kind='pdf',kind='manual'),
              dict(id=str(uuid4()),current_version_id=str(uuid4()),name='Whole photo',preview_kind='image',kind='photo')]
        reader._request=Mock(return_value={'items':rows,'next_cursor':'opaque:next'})
        value=recommendations(SimpleNamespace(reader=reader),{'entry':{'projectOnly':True},'section':'project_documents','q':'needle','cursor':'opaque:before'})
        self.assertEqual([x['kind'] for x in value['items']],['document','photo']);self.assertEqual(value['nextCursor'],'opaque:next')
        self.assertEqual(value['items'][1]['selector']['sourceType'],'project_document')
        self.assertNotIn('entityUid',value['items'][1]['selector'])
        query=parse_qs(urlsplit(reader._request.call_args.args[1]).query)
        self.assertEqual(query['cursor'],['opaque:before']);self.assertEqual(query['q'],['needle'])
        rows[1]['preview_error']='unavailable'
        self.assertEqual(recommendations(SimpleNamespace(reader=reader),{'entry':{'projectOnly':True},'section':'project_documents'})['items'][1]['availability'],'unavailable')


class MaterialAuthority(base.EquipmentAuthority):
    def __init__(self,url):
        super().__init__(url);self.material_role='role:cabinet';self.material_revision=7;self.after_material=None
        self.adopted_model=copy.deepcopy(MODEL);self.current_model=copy.deepcopy(MODEL)
        self.document_reader=DocumentReader()
    def request(self,method,path,body=None):
        plain=urlsplit(path).path
        if '/equipment-materials/' in plain:
            self.source_calls.append((method,path,body))
            if self.after_material:self.after_material()
            if plain.endswith('/devices/resolve'):
                if body['expectedEntityRevision']!='fixed:1':raise PreviewError(409,'ENTITY_CHANGED')
                return dict(model=self.adopted_model,role=self.material_role,roles=ROLES,revision=self.material_revision,
                    items=[] if self.material_role=='root' else [MATERIAL],nextCursor=None,canManage=True)
            if plain.endswith('/candidates'):
                return dict(items=[{k:v for k,v in MATERIAL.items() if k not in ('scopes','origins')}|{'selected':True}],nextCursor='opaque:next')
            return dict(model=self.current_model,roles=ROLES,revision=self.material_revision,total=13,items=[MATERIAL],nextCursor='opaque:next',canManage=True)
        if plain.endswith('/specification-revisions/'+self.current_model['revisionId']):
            self.source_calls.append((method,path,body))
            return specification_revision(self.current_model)
        if plain.endswith('/attribute-form'):
            self.source_calls.append((method,path,body))
            return dict(device={'entityUid':engineering.ROOT},model=None,available=True,fields=[],values=[],scope={'source':'common'})
        if '/documents/' in plain:
            self.source_calls.append((method,path,body));return self.document_reader._request(method,path,body)
        result=super().request(method,path,body)
        if plain.endswith('/equipment/resolve'):
            for row in result['items']:row['model']=copy.deepcopy(self.adopted_model) if row['item']['entityUid']==engineering.ROOT else None
        return result
    def document_page(self,path,*,photo=False):
        self.source_calls.append(('GET',path,None))
        if self.after_material:self.after_material()
        return dict(content=PNG,mediaType='image/png',sha256='b'*64)


class MaterialHttpTests(unittest.TestCase):
    request=base.EquipmentHttpTests.request
    login=base.EquipmentHttpTests.login
    authority=base.EquipmentHttpTests.authority
    upload_calibrated=base.EquipmentHttpTests.upload_calibrated
    metadata=base.EquipmentHttpTests.metadata
    listing=base.EquipmentHttpTests.listing
    upload=base.EquipmentHttpTests.upload
    calibration=base.EquipmentHttpTests.calibration
    calibrate=base.EquipmentHttpTests.calibrate
    def setUp(self):
        self.enterContext(patch.object(base,'EquipmentAuthority',MaterialAuthority))
        base.EquipmentHttpTests.setUp(self)
        self.selection=dict(entityUid=engineering.ROOT,expectedEntityRevision='fixed:1',installationContextId=engineering.CTX,expectedHierarchyRevision='tree:1')
    def test_model_catalogue_candidates_and_device_selection_are_explicit_and_paginated(self):
        status,value,_=self.request(base.ROOT+'/materials/models',dict(specificationId=SPEC,scope='role:cabinet',kind='pdf',cursor='opaque:before',limit=1))
        self.assertEqual(status,200,value);self.assertEqual(value['total'],13);self.assertEqual(len(value['items']),1)
        query=parse_qs(urlsplit(next(call[1] for call in reversed(self.authority().source_calls) if '/equipment-materials/' in call[1])).query)
        self.assertEqual(query['cursor'],['opaque:before']);self.assertEqual(query['scope'],['role:cabinet'])
        self.assertEqual(self.request(base.ROOT+'/materials/candidates',dict(specificationId=SPEC,revision=7,limit=1))[1]['items'][0]['selected'],True)
        status,value,_=self.request(base.ROOT+'/materials/resolve',self.selection|{'cursor':None,'limit':1})
        self.assertEqual(status,200,value);self.assertEqual(value['role'],'role:cabinet')
        self.assertEqual(next(call[2] for call in reversed(self.authority().source_calls) if '/equipment-materials/' in call[1])['entityUid'],engineering.ROOT)
        self.authority().material_role='root'
        self.assertEqual(self.request(base.ROOT+'/materials/resolve',self.selection)[1]['items'],[])
        self.authority().material_revision=8
        self.assertEqual(self.request(base.ROOT+'/materials/resolve',self.selection)[1]['revision'],8)

    def test_new_parameters_reject_arbitrary_urls_invalid_pages_and_missing_candidate_revision(self):
        invalid=[('/materials/models',{'specificationId':SPEC,'url':'https://outside.invalid'}),
            ('/materials/models',{'specificationId':SPEC,'scope':'http://outside.invalid'}),
            ('/materials/models',{'specificationId':SPEC,'kind':'glb'}),
            ('/materials/models',{'specificationId':SPEC,'limit':True}),
            ('/materials/candidates',{'specificationId':SPEC}),
            ('/materials/resolve',self.selection|{'installationContextId':None}),
            ('/materials/resolve',self.selection|{'cursor':''}),
            ('/attribute-form',{'entityUid':engineering.ROOT,'templateRevisionId':TEMPLATE}),
            ('/materials/content',{'documentId':DOC,'contentVersionId':VERSION,'pageNumber':0})]
        for path,body in invalid:
            before=len([call for call in self.authority().source_calls if '/equipment-materials/' in call[1] or '/documents/' in call[1] or '/attribute-form' in call[1]])
            with self.subTest(path=path,body=body):self.assertEqual(self.request(base.ROOT+path,body)[0],422)
            self.assertEqual(len([call for call in self.authority().source_calls if '/equipment-materials/' in call[1] or '/documents/' in call[1] or '/attribute-form' in call[1]]),before)
        for path in ('/materials/models/save','/materials/preview','/materials/operations','/materials/content/extra'):
            self.assertEqual(self.request(base.ROOT+path,{})[0],404)

    def test_device_model_is_preserved_and_child_does_not_inherit_parent_model(self):
        status,value,_=self.request(base.ROOT+'/resolve',{'entityUids':[engineering.ROOT,engineering.CABINET]})
        self.assertEqual(status,200,value);self.assertEqual(value['items'][0]['model']['specificationId'],SPEC)
        self.assertIsNone(value['items'][1]['model'])
        status,value,_=self.request(base.ROOT+'/attribute-form',{'entityUid':engineering.ROOT})
        self.assertEqual(status,200,value);self.assertEqual(value['scope']['source'],'common');self.assertIsNone(value['model'])

    def test_current_device_view_follows_the_same_model_without_changing_adoption_or_document_version(self):
        source=self.authority();head=str(uuid4())
        source.adopted_model['headRevisionId']=head
        source.current_model.update(headRevisionId=head,revisionId=head,revision=2,name='Renamed model')
        path=base.ROOT+'/resolve';selection={'entityUids':[engineering.ROOT]}
        status,original,_=self.request(path,selection)
        self.assertEqual(status,200,original)
        status,value,_=self.request(path,selection|{'includeCurrentModel':True})
        self.assertEqual(status,200,value)
        item=value['items'][0];latest=item.pop('currentModel')
        self.assertEqual(item,original['items'][0]);self.assertEqual(latest['name'],'Renamed model')
        self.assertEqual(latest['revision'],2)
        status,materials,_=self.request(base.ROOT+'/materials/resolve',self.selection)
        self.assertEqual(status,200,materials)
        self.assertEqual(materials['currentModel'],latest);self.assertEqual(materials['model'],item['model'])
        self.assertEqual(materials['items'],[MATERIAL]);self.assertEqual(materials['revision'],7)
        self.assertEqual(self.request(path,{'entityUids':[engineering.ROOT,engineering.CABINET],'includeCurrentModel':True})[0],422)
        self.assertEqual(self.request(path,selection|{'includeCurrentModel':True,'specificationId':SPEC})[0],422)
        source.allowed=False
        self.assertEqual(self.request(path,selection|{'includeCurrentModel':True})[0],403)

    def test_fixed_page_bytes_are_private_and_cannot_switch_version_or_late_access(self):
        body=dict(documentId=DOC,contentVersionId=VERSION,pageNumber=2,sourceSha256='a'*64)
        status,value,headers=self.request(base.ROOT+'/materials/content',body)
        self.assertEqual((status,value),(200,PNG));self.assertEqual(headers['Cache-Control'],'no-store')
        query=parse_qs(urlsplit(next(call[1] for call in reversed(self.authority().source_calls) if '/content?' in call[1])).query)
        self.assertEqual(query['version_id'],[VERSION]);self.assertEqual(query['page'],['2'])
        self.assertEqual(self.request(base.ROOT+'/materials/content',body|{'sourceSha256':'c'*64})[0],409)
        self.authority().after_material=lambda:setattr(self.authority(),'grant','grant:changed')
        self.assertEqual(self.request(base.ROOT+'/materials/content',body)[0],409)

    def test_anonymous_revoked_stale_session_source_conflict_and_late_access_have_no_materials(self):
        body={'specificationId':SPEC}
        self.assertEqual(self.request(base.ROOT+'/materials/models',body,client=False)[0],401)
        self.assertEqual(self.request(base.ROOT+'/materials/models',body|{'expectedSessionRevision':'stale'})[0],409)
        self.assertEqual(self.request(base.ROOT+'/materials/resolve',self.selection|{'expectedEntityRevision':'changed'})[0],409)
        self.authority().allowed=False
        self.assertEqual(self.request(base.ROOT+'/materials/models',body)[0],403)
        self.authority().allowed=True;self.authority().after_material=lambda:setattr(self.authority(),'grant','grant:changed')
        self.assertEqual(self.request(base.ROOT+'/materials/models',body)[0],409)


if __name__=='__main__':unittest.main()
