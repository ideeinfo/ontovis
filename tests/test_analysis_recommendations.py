from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from apps.api.analysis_queries import recommendations
from apps.api.analysis_recommendations import registered_recommendation_revisions
from apps.api import simulated_faults as sim
from apps.api.authority import PreviewError


class MaterialRecommendationTests(TestCase):
    def reader(self, project='Demo-PDS'):
        return SimpleNamespace(reader=SimpleNamespace(project_code=project, _request=Mock(side_effect=AssertionError('Unexpected engineering read'))))

    def entry(self, code='13001', recurrence=False):
        dataset=sim.identity(code,recurrence=recurrence)
        return {key:dataset[key] for key in ('datasetId','datasetRevision')}

    def test_alarm_candidates_prioritize_current_fixed_event_and_keep_recurrence_separate(self):
        reader=self.reader();entry=self.entry(recurrence=True)
        value=recommendations(reader,{'entry':entry,'section':'alarms'})
        catalogue=sim.catalogue('Demo-PDS')['items']
        self.assertCountEqual([row['selector']['datasetId'] for row in value['items']],
            [item['datasetId'] for item in catalogue])
        self.assertEqual(value['items'][0]['selector']['datasetId'],entry['datasetId'])
        self.assertEqual(len({row['key'] for row in value['items']}),len(catalogue))
        for row in value['items']:
            descriptor=row['selector'];self.assertEqual(descriptor['eventId'],descriptor['datasetId']+'-event-1')
            self.assertEqual(row['preview']['dataset'],sim.dataset(descriptor['datasetId'],descriptor['datasetRevision']))
        reader.reader._request.assert_not_called()

    def test_manual_analysis_can_choose_an_alarm_and_filter_without_loading_trends(self):
        with patch.object(sim,'trend',side_effect=AssertionError('No sample prefetch')):
            value=recommendations(self.reader(),{'entry':{'projectOnly':True},'section':'alarms','q':'13002'})
        self.assertEqual(len(value['items']),1);self.assertEqual(value['items'][0]['preview']['dataset']['faultCode'],'13002')
        other=recommendations(self.reader('OTHER'),{'entry':{'projectOnly':True},'section':'alarms'})
        self.assertEqual(other['items'],[]);self.assertIn('SIMULATION_PROJECT_REQUIRED',other['gaps'])

    def test_object_recommendations_explain_the_alarm_target_and_cable_check(self):
        reader=self.reader()
        reader._rds=Mock(side_effect=lambda tag: {
            'item':{'entityUid':tag,'entityRevision':'r1'},'context':None})
        value=recommendations(reader,{'entry':self.entry('13033'),'section':'objects'})
        rows={row['identifier']:row for row in value['items']}
        target=rows['=WEC+CN1']
        self.assertEqual(target['relevance'],'simulation_mapping')
        self.assertEqual(target['reason'],'由 13033 的报警配置指定')
        self.assertEqual(target['reasonEn'],'Specified by the alarm configuration for 13033')
        cable=rows['=WEC+CN1-80W1']
        self.assertEqual(cable['relevance'],'simulation_rule')
        self.assertEqual(cable['reason'],'24VDC供电线缆 · 13033 排查清单')
        self.assertEqual(cable['reasonEn'],'Listed in the 13033 troubleshooting checklist')

    def test_canvas_object_recommendations_keep_each_objects_source_cards(self):
        dataset = sim.identity('13003')
        primary = {'entityUid': 'protector', 'entityRevision': 'r1', 'displayName': '+CN1-1U2'}
        cabinet = {'entityUid': 'cabinet', 'entityRevision': 'r1', 'displayName': 'CN1 机舱动力柜'}
        module = {'entityUid': 'module', 'entityRevision': 'r1', 'displayName': '+CN1-105A3'}
        tags = dict(zip((dataset['primaryRds'], '=WEC+CN1', '=WEC+CN1-105A3'), (primary, cabinet, module)))
        reader = self.reader()
        reader._rds = Mock(side_effect=lambda tag: {'item': tags[tag]})
        reader.read = Mock(side_effect=lambda kind, _: {'dataset': dataset} if kind in ('alarm', 'trend')
                           else {'item': {'entityUid': 'other', 'entityRevision': 'r2', 'displayName': '另一工程对象'}})
        fixed = [(dict(evidenceRefId=ref, sourceKind=kind), {})
                 for ref, kind in [('alarm-card', 'alarm'), ('trend-card', 'trend'), ('object-card', 'object')]]
        value = recommendations(reader, {'entry': {'projectOnly': True}, 'section': 'objects'}, canvas_sources=fixed)
        self.assertEqual([], value['gaps'])
        rows = {item['selector']['entityUid']: item['relatedSourceRefs'] for item in value['items']}
        self.assertEqual(len(value['items']), len(rows))
        self.assertEqual({**dict.fromkeys(('protector', 'cabinet', 'module'), ['alarm-card', 'trend-card']),
                          'other': ['object-card']}, rows)
        self.assertEqual(3, reader._rds.call_count)

    def test_alarm_search_accepts_displayed_title_with_the_same_fixed_revision(self):
        reader=self.reader()
        body={'entry':{'projectOnly':True},'section':'alarms'}
        previous=recommendations(reader,body|{'q':'24V空开状态演练'})['items']
        current=recommendations(reader,body|{'q':'24V空开状态测试'})['items']
        self.assertEqual(len(current),1)
        self.assertEqual(current,previous)
        self.assertEqual(current[0]['selector']['datasetRevision'],sim.identity('13033')['datasetRevision'])

    def test_registered_matches_distinguish_document_pages_versions_and_knowledge_anchors(self):
        selector = dict(documentId='document', contentVersionId='current', pageNumber=2)
        fixed = {**selector, 'sourceSha256': 'a' * 64}
        registered = [
            ('document', fixed, 'matching'),
            ('document', {**fixed, 'pageNumber': 3}, 'another page'),
            ('document', {**fixed, 'contentVersionId': 'older'}, 'another version'),
            ('document', {**fixed, 'knowledgeReleaseId': 'release', 'knowledgeNodeId': 'node'}, 'knowledge'),
        ]
        self.assertEqual(registered_recommendation_revisions({'kind': 'document', 'selector': selector}, registered),
                         ['matching'])

    def test_registered_model_matches_expected_fields_against_its_fixed_content(self):
        selector = dict(modelAssetId='asset', modelVersionId='version', expectedContentRevision='revision', expectedSha256='sha')
        descriptor = dict(modelAssetId='asset', modelVersionId='version', contentRevision='revision',
                          sha256='sha', configurationRefs=[])
        self.assertEqual(registered_recommendation_revisions({'kind': 'model', 'selector': selector},
                         [('model', descriptor, 'matching')]), ['matching'])

    def test_trends_offer_fixed_descriptors_only_and_preserve_current_event_window(self):
        for code,count in (('13001',5),('13004',3)):
            with patch.object(sim,'trend',side_effect=AssertionError('No sample prefetch')):
                value=recommendations(self.reader(),{'entry':self.entry(code),'section':'trends'})
            self.assertEqual(len(value['items']),count)
            for row in value['items']:
                self.assertEqual(row['selector']['timeFrom'],value['dataset']['timeFrom'])
                self.assertEqual(row['selector']['datasetRevision'],value['dataset']['datasetRevision'])
        value=recommendations(self.reader(),{'entry':self.entry(),'section':'trends','q':'reference_temperature'})
        self.assertEqual([row['selector']['metricId'] for row in value['items']],['reference_temperature'])
        manual=recommendations(self.reader(),{'entry':{'projectOnly':True},'section':'trends'})
        self.assertEqual(manual['items'],[]);self.assertTrue(manual['gaps'])

    def test_versions_and_query_shape_cannot_bypass_source_checks(self):
        for body in ({'entry':{**self.entry(),'datasetRevision':'changed'},'section':'alarms'},
            {'entry':self.entry(),'section':'trends','q':['bad']},
            {'entry':self.entry(),'section':'alarms','url':'https://outside.invalid'}):
            with self.assertRaises(PreviewError):recommendations(self.reader(),body)

    def test_drawing_and_photo_categories_only_resolve_the_selected_material_type(self):
        reader=self.reader();reader._rds=Mock(return_value={'item':{'entityUid':'object','entityRevision':'r1'},'context':None})
        reader.reader.prefix='/api/v1/projects/Demo-PDS';reader.reader._request=Mock(return_value={'projectCode':'Demo-PDS','items':[],'nextCursor':None})
        reader.photos=SimpleNamespace(resolve=Mock(return_value={'items':[{'title':'Photo','evidenceRef':'photo','selector':{'bbox':{} }}]}))
        with patch('apps.api.scene_evidence.SceneEvidenceReader') as drawing,patch('apps.api.related_drawings.RelatedDrawingsReader') as related:
            related.return_value.resolve.return_value={'items':[],'nextCursor':None}
            drawing.return_value.resolve.return_value={'items':[{'title':'Drawing','evidenceRef':'drawing',
                'availability':'available','contentSha256':'a'*64,'pageNumber':1}]}
            rows=recommendations(reader,{'entry':self.entry(),'section':'drawings'})['items']
            self.assertEqual([row['kind'] for row in rows],['drawing']);reader.photos.resolve.assert_not_called()
            drawing.reset_mock();related.reset_mock()
            rows=recommendations(reader,{'entry':self.entry(),'section':'photos'})['items']
            self.assertEqual([row['kind'] for row in rows],['photo']);drawing.assert_not_called();related.assert_not_called()

    def test_drawing_recommendations_merge_one_fixed_page_and_keep_all_registered_positions(self):
        reader = self.reader()
        reader._rds = Mock(return_value={'item': {'entityUid': 'object', 'entityRevision': 'r1'}, 'context': None})
        first = dict(title='Power supply', evidenceRef='location:one', availability='available',
                     contentSha256='a'*64, pageNumber=89, sourceRevision='b'*64)
        second = {**first, 'evidenceRef': 'location:two', 'sourceRevision': 'c'*64}
        different_revision = {**first, 'evidenceRef': 'location:three', 'contentSha256': 'd'*64}
        different_page = {**first, 'evidenceRef': 'location:four', 'pageNumber': 90}
        retained = dict(entityUid='object', expectedEntityRevision='r1', evidenceRef=second['evidenceRef'],
                        expectedSourceRevision=second['sourceRevision'], expectedContentSha256=second['contentSha256'])
        descendant = {**first, 'drawingUid': 'fixed-page', 'matchedObjects': [{'relation': 'definition_descendant'}]}
        with patch('apps.api.scene_evidence.SceneEvidenceReader') as drawing, \
                patch('apps.api.related_drawings.RelatedDrawingsReader') as related:
            drawing.return_value.resolve.return_value = {'items': [first, second, different_revision, different_page]}
            related.return_value.resolve.return_value = {'items': [descendant], 'nextCursor': None}
            registered = [('drawing', retained, 'retained-second'),
                          ('drawing', {**retained, 'expectedContentSha256': 'f'*64}, 'stale-page')]
            rows = recommendations(reader, {'entry': self.entry('13003'), 'section': 'drawings'},
                                   registered_sources=registered)['items']
        self.assertEqual([row['selector']['evidenceRef'] for row in rows],
                         ['location:one', 'location:three', 'location:four'])
        self.assertEqual(rows[0]['registeredSourceRevisions'], ['retained-second'])
        self.assertEqual(rows[0]['relevance'], 'object_association')
        self.assertTrue(all('registeredSourceRevisions' not in row for row in rows[1:]))

    def cabinet_reader(self):
        from apps.api.scene_engineering import SceneEngineeringReader
        reader=self.reader();reader.reader=Mock(spec=SceneEngineeringReader,project_code='Demo-PDS',prefix='/api/v1/projects/Demo-PDS',authority=SimpleNamespace(image=Mock()))
        reader.reader.context_for_object=Mock(return_value={'item':{'entityUid':'cabinet','entityRevision':'r7'},'context':None})
        reader._rds=Mock(side_effect=AssertionError('The selected cabinet must override the fault object'))
        reader.photos=SimpleNamespace(resolve=Mock(return_value={'items':[]}))
        rows=[{'documentId':str(uuid4()),'contentVersionId':str(uuid4()),'title':'Cabinet '+side,
               'availability':'available','sources':['member'],'regionCount':9} for side in ('left','front','right')]
        reader.reader._request=Mock(return_value={'projectCode':'Demo-PDS','items':rows,'nextCursor':None})
        return reader,rows

    def test_selected_cabinet_recommends_member_photos_as_whole_fixed_images(self):
        reader,photos=self.cabinet_reader()
        value=recommendations(reader,{'entry':self.entry('13004'),'section':'photos','entityUid':'cabinet','expectedEntityRevision':'r7'})
        self.assertEqual([row['title'] for row in value['items']],[row['title'] for row in photos])
        reader.reader.context_for_object.assert_called_once_with('cabinet','r7');reader._rds.assert_not_called()
        call=reader.reader._request.call_args
        self.assertEqual(call.args[:2],('POST','/api/v1/projects/Demo-PDS/equipment/shared-photos/query'))
        self.assertEqual(call.args[2],dict(entityUid='cabinet',expectedEntityRevision='r7',installationContextId=None,
            expectedHierarchyRevision=None,limit=12,cursor=None))
        for row,photo in zip(value['items'],photos):
            self.assertEqual(row['selector'],dict(sourceType='project_document',documentId=photo['documentId'],contentVersionId=photo['contentVersionId']))
            self.assertNotIn('preview',row);self.assertNotIn('bbox',row['selector']);self.assertNotIn('entityUid',row['selector'])
            self.assertIn('下级',row['reason']);self.assertEqual(row['availability'],'available')

    def test_shared_photo_cursor_and_unavailable_state_are_preserved(self):
        reader,photos=self.cabinet_reader();photos[1]['availability']='unavailable'
        photos += [dict(photos[0],documentId=str(uuid4()),title='Extra '+str(i)) for i in range(9)]
        def page(method,path,body):return {'projectCode':'Demo-PDS','items':photos if body['cursor'] is None else [dict(photos[0],documentId=str(uuid4()))],
            'nextCursor':'opaque:next' if body['cursor'] is None else None}
        reader.reader._request.side_effect=page
        body={'entry':{'projectOnly':True},'section':'photos','entityUid':'cabinet','expectedEntityRevision':'r7'}
        value=recommendations(reader,body)
        self.assertTrue(value['nextCursor'].startswith('rec1.'));self.assertIsNone(value['nextOffset'])
        self.assertEqual(value['items'][1]['availability'],'unavailable')
        more=recommendations(reader,{**body,'cursor':value['nextCursor']});self.assertEqual(len(more['items']),1)
        self.assertEqual(reader.reader._request.call_args.args[2]['cursor'],'opaque:next')
        with self.assertRaises(PreviewError):
            recommendations(reader,{'entry':{'projectOnly':True},'section':'photos','entityUid':'cabinet','offset':1})

    def test_existing_direct_photo_regions_are_not_replaced_by_cabinet_whole_images(self):
        reader,photos=self.cabinet_reader()
        photo={'title':'Located photo','evidenceRef':'photo:fixed','documentId':photos[0]['documentId'],'contentVersionId':photos[0]['contentVersionId'],
            'selector':{'bbox':{'x':.2,'y':.3,'width':.1,'height':.1}}}
        reader.photos.resolve.return_value={'items':[photo]}
        value=recommendations(reader,{'entry':{'projectOnly':True},'section':'photos','entityUid':'cabinet','expectedEntityRevision':'r7'})
        self.assertEqual(len(value['items']),3);self.assertEqual(value['items'][0]['preview'],photo)
        self.assertEqual(value['items'][0]['selector']['evidenceRef'],'photo:fixed');reader.reader._request.assert_called_once()

    def test_photo_fallback_does_not_hide_revocation_or_changed_identity(self):
        for status in (401,403,409):
            reader,_=self.cabinet_reader();reader.photos.resolve.side_effect=PreviewError(status,'SOURCE_CHANGED')
            body={'entry':{'projectOnly':True},'section':'photos','entityUid':'cabinet','expectedEntityRevision':'r7'}
            with self.assertRaises(PreviewError) as error:recommendations(reader,body)
            self.assertEqual(error.exception.status,status)
            reader.reader._request.assert_not_called()
        reader,_=self.cabinet_reader();reader.reader._request.side_effect=PreviewError(403,'PROJECT_FORBIDDEN')
        with self.assertRaises(PreviewError):recommendations(reader,body)
        reader,_=self.cabinet_reader();reader.reader._request.return_value['projectCode']='OTHER'
        with self.assertRaises(PreviewError):recommendations(reader,body)
