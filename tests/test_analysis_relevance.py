"""Evidence ordering, bounded source paging and context-bound continuation."""
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from apps.api import analysis_recommendations as r
from apps.api.authority import PreviewError


class RelatedRelevanceTests(TestCase):
    def setUp(self):
        self.reader=SimpleNamespace(actor='owner',authorize=Mock(),reader=SimpleNamespace(
            connection_id='source',project_code='P'))
        self.chosen={'item':{'entityUid':'cabinet','entityRevision':'r1'},'context':None}
        self.body={'entry':{'projectOnly':True},'section':'materials'}
        self.key=b'synthetic-cursor-key-for-tests-only'

    def item(self, name, basis='object_association'):
        return r.recommendation('drawing',name,{'evidenceRef':name},name,relevance=basis)

    def read(self, **changes):
        return r.related_recommendations(self.reader,self.body|changes,None,self.chosen,cursor_key=self.key,session_revision='login:1')

    def test_mixed_types_interleave_before_weaker_sources_across_pages(self):
        def source(_reader,_chosen,_dataset,_section,name,cursor,_query,_memo):
            if name in ('drawings','photos'):
                return [self.item(name+str(i)) for i in range(14)],None
            return ([self.item('weak','model_applicable')] if name=='applicable' else []),None
        with patch.object(r,'_source_page',side_effect=source):
            first=self.read();second=self.read(cursor=first['nextCursor']);third=self.read(cursor=second['nextCursor'])
        self.assertEqual([x['title'] for x in first['items'][:4]],['drawings0','photos0','drawings1','photos1'])
        self.assertTrue(all(x['relevancePriority']==10 for x in first['items']+second['items']))
        all_rows=first['items']+second['items']+third['items']
        self.assertEqual(len({x['key'] for x in all_rows}),29);self.assertEqual(all_rows[-1]['title'],'weak')
        self.assertIsNone(third['nextCursor']);self.assertEqual(self.reader.authorize.call_count,6)

    def test_cursor_cannot_move_between_actor_project_login_object_type_query_or_entry(self):
        with patch.object(r,'_source_page',return_value=([self.item(str(i)) for i in range(15)],None)):
            token=self.read()['nextCursor']
            for field,changed in [('actor','other'),('project','other'),('login','login:2'),('object','other'),
                                  ('section','photos'),('q','new'),('entry',{'projectOnly':False})]:
                with self.subTest(field=field):
                    reader=SimpleNamespace(actor='other' if field=='actor' else 'owner',authorize=Mock(),
                        reader=SimpleNamespace(connection_id='source',project_code='other' if field=='project' else 'P'))
                    chosen={'item':{'entityUid':'other' if field=='object' else 'cabinet','entityRevision':'r1'},'context':None}
                    body=self.body|{'cursor':token}|({field:changed} if field in ('section','q','entry') else {})
                    with self.assertRaises(PreviewError) as error:r.related_recommendations(reader,body,None,chosen,
                        cursor_key=self.key,session_revision='login:2' if field=='login' else 'login:1')
                    self.assertEqual(error.exception.code,'ANALYSIS_RECOMMENDATIONS_CHANGED')
            with self.assertRaises(PreviewError):self.read(cursor=token[:-1]+('a' if token[-1]!='a' else 'b'))
            with patch.object(r.time,'time',return_value=10_000):
                with self.assertRaises(PreviewError):self.read(cursor=r.encode_cursor(self.key,
                    r.scope_digest(self.reader,self.body,'login:1',r.selected(self.chosen)),{},expires=9_999))

    def test_changed_partially_consumed_source_is_rejected_before_returning_next_page(self):
        items=[self.item(str(i)) for i in range(15)]
        with patch.object(r,'_source_page',return_value=(items,None)):
            first=self.read()
            items[0]=self.item('changed')
            with self.assertRaises(PreviewError) as error:self.read(cursor=first['nextCursor'])
        self.assertEqual(error.exception.code,'ANALYSIS_RECOMMENDATIONS_CHANGED')

    def test_unmatched_pages_are_bounded_and_continue_without_promoting_weaker_items(self):
        def source(_reader,_chosen,_dataset,_section,name,cursor,_query,_memo):
            if name=='drawings':return [],'page:'+str(int((cursor or 'page:0').split(':')[1])+1)
            if name=='applicable':return [self.item('weak','model_applicable')],None
            return [],None
        with patch.object(r,'_source_page',side_effect=source) as called:
            value=self.read(q='needle');self.assertEqual(value['items'],[]);self.assertIsNotNone(value['nextCursor'])
            self.assertLessEqual(called.call_count,r.MAX_PAGE_READS)
            self.assertNotIn('applicable',[call.args[4] for call in called.call_args_list])
            following=self.read(q='needle',cursor=value['nextCursor']);self.assertIsNotNone(following['nextCursor'])

    def test_source_errors_cannot_hide_revocation_or_identity_changes(self):
        for status in (401,403,409,410,422):
            with patch.object(r,'_source_page',side_effect=PreviewError(status,'SOURCE_CHANGED')):
                with self.assertRaises(PreviewError):self.read()
        def gap(_reader,_chosen,_dataset,_section,name,*_args):
            if name=='drawings':raise PreviewError(503,'SOURCE_UNAVAILABLE')
            return ([self.item('photo')] if name=='photos' else []),None
        with patch.object(r,'_source_page',side_effect=gap):
            value=self.read();self.assertEqual(len(value['items']),1);self.assertIn('drawings: SOURCE_UNAVAILABLE',value['gaps'])

    def test_empty_or_nonadvancing_source_cursor_is_rejected(self):
        with patch.object(r,'_source_page',return_value=([],'repeat')):
            with self.assertRaises(PreviewError):self.read()

    def test_deduplication_uses_fixed_identity_not_title(self):
        one=self.item('one');two=self.item('two');two['title']=one['title']
        def source(_reader,_chosen,_dataset,_section,name,*_args):
            return ([one,two] if name=='drawings' else [one] if name=='photos' else []),None
        with patch.object(r,'_source_page',side_effect=source):
            self.assertEqual([x['key'] for x in self.read()['items']],[one['key'],two['key']])

    def test_available_fixed_photo_is_not_hidden_by_an_unavailable_stronger_source(self):
        field=self.item('field','field_record')|{'assetKey':'photo:one:v1','availability':'unavailable'}
        direct=self.item('direct')|{'assetKey':'photo:one:v1','availability':'available'}
        def source(_reader,_chosen,_dataset,_section,name,*_args):
            return ([field] if name=='field' else [direct] if name=='photos' else []),None
        with patch.object(r,'_source_page',side_effect=source):
            self.assertEqual(self.read()['items'],[direct])
