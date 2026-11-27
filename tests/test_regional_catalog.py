"""Regional publication, read filtering and fixed revision boundaries."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from apps.api.authority import PreviewError
from apps.api.regional_catalog import read
from tools.publish_regional_catalog import activate, build, rollback
from tools.wind_catalog import SOURCES, write_database


def observation(source, layer, source_id, name, geometry=None, bounds=None):
    return dict(source=source,layer=layer,source_id=source_id,name=name,country='Sample',status='Approved',
                installation='Wind',capacity_mw=None,turbine_count=0,source_updated='',raw={'discard':'private fixture'},
                coordinate_quality={'windfarms':'source_site_point','windfarmspoly':'source_site_boundary',
                                    'wind':'unresolved_source_grid'}[layer],geometry=geometry,bounds=bounds,issues=[])


class RegionalCatalogTests(unittest.TestCase):
    def setUp(self):
        folder=TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)/'active'
        self.folder=Path(folder.name)

    def build(self, label, *, state='complete', rename='Beta offshore'):
        batch=self.folder/label
        batch.mkdir()
        records=[
            observation('emodnet','windfarms','point','Alpha offshore',{'type':'Point','coordinates':[9,56]},[9,56,9,56]),
            observation('emodnet','windfarmspoly','boundary',rename,{'type':'Polygon','coordinates':[[[9,56],[10,56],[9,57],[9,56]]]},[9,56,10,57]),
            observation('repd','wind','uk','Gamma onshore'),
            observation('repd','wind','nameless','')]
        manifest=dict(schema_version=1,state=state,sources=SOURCES,retrieved_at='2026-10-20',observations=len(records),repd_release='fixture')
        counts=write_database(batch/'catalog.sqlite',records,manifest)
        manifest['counts']=[dict(source=s,layer=l,count=n) for s,l,n in counts]
        (batch/'manifest.json').write_text(json.dumps(manifest))
        target=self.folder/(label+'.sqlite')
        build(batch,target)
        return target

    def test_query_projects_only_public_fields_and_checks_revision(self):
        identity=activate(self.root,self.build('first'))
        first=read(self.root,dict(q='OFFSHORE',limit=1))
        self.assertEqual((first['total'],first['nextOffset'],first['catalogRevision']),(2,1,identity))
        self.assertEqual(first['items'][0]['longitude'],9)
        self.assertNotIn('raw',first['items'][0])
        second=read(self.root,dict(q='offshore',offset=1,limit=1,catalogRevision=identity))
        detail=read(self.root,dict(id=second['items'][0]['id'],catalogRevision=identity))['item']
        self.assertEqual((detail['locationAccuracy'],detail['geometry']['type'],detail['longitude']),
                         ('source_site_boundary','Polygon',None))
        uk,=read(self.root,dict(source='repd'))['items']
        self.assertEqual((uk['locationAccuracy'],uk['longitude'],uk['turbineCount']),('unresolved_source_grid',None,0))
        self.assertEqual(read(self.root,dict(bbox=[8,55,11,58]))['total'],2)
        with self.assertRaises(PreviewError) as raised:
            read(self.root,dict(offset=1))
        self.assertEqual(raised.exception.status,422)

    def test_bad_batch_preserves_current_and_activation_and_rollback_are_pinned(self):
        first=activate(self.root,self.build('first'))
        with self.assertRaises(ValueError):
            self.build('bad',state='failed')
        self.assertEqual(read(self.root,{})['catalogRevision'],first)
        next_revision=activate(self.root,self.build('second',rename='New name'))
        self.assertNotEqual(first,next_revision)
        with self.assertRaises(PreviewError) as raised:
            read(self.root,dict(offset=1,catalogRevision=first))
        self.assertEqual((raised.exception.status,raised.exception.code),(409,'CATALOG_CHANGED'))
        rollback(self.root,first)
        self.assertEqual(read(self.root,dict(q='beta'))['total'],1)
