import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('catalog', Path(__file__).parents[1]/'tools/wind_catalog.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)

class CatalogTests(unittest.TestCase):
    def page(self, ids, matched=3):
        return json.dumps(dict(type='FeatureCollection', numberMatched=matched, numberReturned=len(ids), features=[dict(id=x) for x in ids])).encode()
    def test_pagination(self):
        pages=iter([self.page(['a','b']),self.page(['c'])])
        self.assertEqual(sum(len(x[2]) for x in c.wfs_pages('windfarms',lambda _:next(pages),2)),3)
    def test_duplicate_page_rejected(self):
        pages=iter([self.page(['a','b']),self.page(['a'])])
        with self.assertRaisesRegex(ValueError,'duplicate'):
            list(c.wfs_pages('windfarms',lambda _:next(pages),2))
    def test_changing_count_rejected(self):
        pages=iter([self.page(['a','b']),self.page(['c'],4)])
        with self.assertRaisesRegex(ValueError,'changed'):
            list(c.wfs_pages('windfarms',lambda _:next(pages),2))
    def test_short_page_rejected(self):
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            list(c.wfs_pages('windfarms',lambda _:self.page(['a']),2))
    def test_nonfinite_and_fractional_counts(self):
        issues=[]
        self.assertIsNone(c.numeric('NaN',issues,'capacity'))
        self.assertIsNone(c.numeric('2.4',issues,'turbines',True))
        self.assertEqual(len(issues),2)
    def test_geometry_axis_bounds(self):
        self.assertEqual(c.geometry_bounds(dict(type='Point',coordinates=[2.84,51.69])),[2.84,51.69,2.84,51.69])
        with self.assertRaises(ValueError):
            c.geometry_bounds(dict(type='Point',coordinates=[51,180]))
    def test_repd_grid_not_mistaken_for_wgs84(self):
        raw=b'Ref ID,Site Name,Technology Type,Country,X-coordinate,Y-coordinate,Installed Capacity (MWelec),Development Status,No. of Turbines\n1,Farm,Wind Onshore,England,300000,400000,10,Operational,4\n'
        row=list(c.repd_records(raw))[0]
        self.assertIsNone(row['geometry'])
        self.assertEqual(row['raw']['X-coordinate'],'300000')
        self.assertIn('grid_crs_unverified',row['issues'])
    def test_discovery_rejects_ambiguous_or_untrusted(self):
        with self.assertRaises(ValueError):
            c.discover_repd(b'<a href="https://example.com/REPD.csv">Download</a>')
    def test_failed_batch_cannot_look_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'batch'
            def fail(_): raise ValueError('offline')
            with self.assertRaises(ValueError): c.collect(p,fail)
            self.assertEqual(json.loads((p/'manifest.json').read_text())['state'],'failed')
            self.assertFalse((p/'catalog.sqlite').exists())
            with self.assertRaises(FileExistsError): c.collect(p,fail)
    def test_missing_source_name_is_quarantined(self):
        r=c.emodnet_record('windfarms',dict(id='windfarms.9',properties={},geometry=None))
        self.assertIn('missing_name',r['issues'])
        self.assertEqual(r['name'],'')
    def test_source_scoped_ids_remain_separate(self):
        feature=dict(id='windfarms.1',properties=dict(name='Example',country='France',power_mw=10,n_turbines=2),geometry=dict(type='Point',coordinates=[-2,47]))
        r=c.emodnet_record('windfarms',feature)
        r2=dict(r,layer='windfarmspoly',coordinate_quality='source_site_boundary')
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'catalog.sqlite'
            c.write_database(p,[r,r2],dict(retrieved_at='2026-10-20'))
            with sqlite3.connect(p) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM observation').fetchone()[0],2)
                self.assertEqual(db.execute('SELECT count(*) FROM catalog_points').fetchone()[0],1)

if __name__=='__main__':unittest.main()
