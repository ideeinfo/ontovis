#!/usr/bin/env python3
"""Collect official EMODnet/REPD observations into a versioned local staging database."""
from __future__ import annotations
import argparse
import csv
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
import math
from pathlib import Path
import re
import sqlite3
import sys
import urllib.parse
import urllib.request

EMODNET = 'https://ows.emodnet-humanactivities.eu/wfs'
REPD = 'https://www.gov.uk/government/publications/renewable-energy-planning-database-quarterly-extract'
SOURCES = {
    'emodnet': dict(metadata='https://emodnet.ec.europa.eu/geonetwork/srv/api/records/8201070b-4b0b-4d54-8910-abcea5dce57f', license='https://creativecommons.org/licenses/by/4.0/', attribution='EMODnet Human Activities / CETMAR, Energy, Wind Farms. CC BY 4.0.'),
    'repd': dict(metadata=REPD, license='https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/', attribution='Contains public sector information licensed under the Open Government Licence v3.0. Department for Energy Security and Net Zero / REPD.'),
}
MAX_BYTES = 40 * 1024 * 1024


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={'User-Agent': 'ONTOVis-Catalog-Research/0.1'})
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Response exceeds 40 MiB; inspect source before changing limit')
    return data


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls: list[str] = []
    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.urls += [v for k, v in attrs if k == 'href' and v]


def discover_repd(page: bytes) -> str:
    parser = Links()
    parser.feed(page.decode('utf-8'))
    candidates = list(dict.fromkeys(u for u in parser.urls if urllib.parse.urlparse(u).hostname == 'assets.publishing.service.gov.uk' and re.search(r'/REPD[^/]*\.csv$', u, re.I)))
    if len(candidates) != 1:
        raise ValueError(f'Expected one current official REPD CSV, found {len(candidates)}')
    return candidates[0]


def wfs_pages(layer: str, getter=fetch, page_size=100):
    """Reject changing counts, duplicate IDs, short/empty pages and unknown totals."""
    expected = None
    seen = set()
    offset = 0
    while True:
        url = EMODNET + '?' + urllib.parse.urlencode(dict(service='WFS', version='2.0.0', request='GetFeature', typeNames='emodnet:' + layer, outputFormat='application/json', srsName='CRS:84', count=page_size, startIndex=offset))
        raw = getter(url)
        doc = json.loads(raw)
        matched = doc.get('numberMatched')
        features = doc.get('features')
        if doc.get('type') != 'FeatureCollection' or not isinstance(matched, int) or matched <= 0 or not isinstance(features, list):
            raise ValueError('Invalid WFS response or no known positive total')
        if expected is None:
            expected = matched
        if matched != expected:
            raise ValueError('WFS total changed during collection; retry full batch')
        if len(features) != min(page_size, expected - offset) or doc.get('numberReturned') != len(features):
            raise ValueError('Incomplete WFS page')
        for feature in features:
            fid = feature.get('id')
            if not fid or fid in seen:
                raise ValueError('Missing or duplicate WFS feature ID')
            seen.add(fid)
        yield url, raw, features, expected
        offset += len(features)
        if offset == expected:
            break
        if offset > expected:
            raise ValueError('WFS count overflow')


def numeric(value, issues, field, integer=False):
    if value is None or str(value).strip() in ('', '-', 'N/A', 'Unknown'):
        return None
    try:
        n = float(str(value).replace(',', '').strip())
        if not math.isfinite(n) or n < 0 or (integer and not n.is_integer()):
            raise ValueError()
        return int(n) if integer else n
    except (ValueError, TypeError):
        issues.append('invalid_' + field)
        return None


def geometry_bounds(geometry):
    if geometry is None:
        return None
    if geometry.get('type') not in ('Point', 'Polygon', 'MultiPolygon'):
        raise ValueError('Unsupported geometry type')
    coords = geometry.get('coordinates')
    points = []
    def walk(node):
        if not isinstance(node, list) or not node:
            raise ValueError('Invalid coordinate array')
        if isinstance(node[0], (int, float)):
            if len(node) < 2 or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in node[:2]):
                raise ValueError('Non-finite coordinates')
            x, y = node[:2]
            if not -180 <= x <= 180 or not -90 <= y <= 90:
                raise ValueError('Coordinates outside lon/lat range')
            points.append((x, y))
        else:
            for child in node:
                walk(child)
    walk(coords)
    return [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]


def emodnet_record(layer, feature):
    p = feature['properties']
    issues = []
    geometry = feature.get('geometry')
    try:
        bounds = geometry_bounds(geometry)
    except ValueError:
        geometry, bounds = None, None
        issues.append('invalid_geometry')
    if geometry is None:
        issues.append('missing_geometry')
    if not str(p.get('name') or '').strip():
        issues.append('missing_name')
    return dict(source='emodnet', layer=layer, source_id=str(feature['id']), name=p.get('name') or '', country=p.get('country'), status=p.get('status'), installation=p.get('type_inst'), capacity_mw=numeric(p.get('power_mw'), issues, 'capacity'), turbine_count=numeric(p.get('n_turbines'), issues, 'turbine_count', True), source_updated=str(p.get('updateyear') or ''), coordinate_quality='source_site_point' if layer == 'windfarms' else 'source_site_boundary', geometry=geometry, bounds=bounds, raw=p, issues=issues)


def repd_records(raw):
    try:
        text = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = raw.decode('cp1252')
    reader = csv.DictReader(io.StringIO(text))
    required = {'Ref ID', 'Site Name', 'Technology Type', 'Country', 'X-coordinate', 'Y-coordinate', 'Installed Capacity (MWelec)', 'Development Status', 'No. of Turbines'}
    if not required.issubset(reader.fieldnames or []):
        raise ValueError('REPD schema changed: missing ' + ', '.join(sorted(required - set(reader.fieldnames or []))))
    seen = set()
    for row in reader:
        tech = row['Technology Type'].strip()
        if tech not in ('Wind Onshore', 'Wind Offshore'):
            continue
        fid = row['Ref ID'].strip()
        if not fid or fid in seen:
            raise ValueError('Missing/duplicate REPD identity')
        seen.add(fid)
        issues = ['grid_crs_unverified']
        if not row['Site Name'].strip():
            issues.append('missing_name')
        # X/Y are source grid values, never interpreted as decimal longitude/latitude.
        yield dict(source='repd', layer='wind', source_id=fid, name=row['Site Name'], country=row['Country'], status=row['Development Status'], installation=tech, capacity_mw=numeric(row['Installed Capacity (MWelec)'], issues, 'capacity'), turbine_count=numeric(row['No. of Turbines'], issues, 'turbine_count', True), source_updated=row.get('Record Last Updated (dd/mm/yyyy)', ''), coordinate_quality='unresolved_source_grid', geometry=None, bounds=None, raw=row, issues=issues)
    if not seen:
        raise ValueError('No wind records found; possible REPD domain/schema change')


def write_database(path: Path, records, manifest):
    db = sqlite3.connect(path)
    try:
        db.executescript('''
        CREATE TABLE dataset(source TEXT PRIMARY KEY, metadata_url TEXT NOT NULL, license_url TEXT NOT NULL, attribution TEXT NOT NULL, retrieved_at TEXT NOT NULL);
        CREATE TABLE observation(source TEXT NOT NULL, layer TEXT NOT NULL, source_id TEXT NOT NULL, name TEXT NOT NULL, country TEXT, status TEXT, installation TEXT, capacity_mw REAL CHECK(capacity_mw >= 0), turbine_count INTEGER CHECK(turbine_count >= 0), source_updated TEXT, coordinate_quality TEXT NOT NULL, geometry_json TEXT, bounds_json TEXT, raw_json TEXT NOT NULL, issues_json TEXT NOT NULL, PRIMARY KEY(source,layer,source_id), FOREIGN KEY(source) REFERENCES dataset(source));
        CREATE INDEX observation_name ON observation(name);
        CREATE INDEX observation_country ON observation(country);
        CREATE VIEW catalog_points AS SELECT * FROM observation WHERE layer != 'windfarmspoly' AND trim(name) != '';
        ''')
        with db:
            for source, meta in SOURCES.items():
                db.execute('INSERT INTO dataset VALUES (?,?,?,?,?)', (source, meta['metadata'], meta['license'], meta['attribution'], manifest['retrieved_at']))
            for r in records:
                db.execute('INSERT INTO observation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (r['source'],r['layer'],r['source_id'],r['name'],r['country'],r['status'],r['installation'],r['capacity_mw'],r['turbine_count'],r['source_updated'],r['coordinate_quality'],json.dumps(r['geometry']) if r['geometry'] else None,json.dumps(r['bounds']) if r['bounds'] else None,json.dumps(r['raw'], ensure_ascii=False),json.dumps(r['issues'])))
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed')
        return db.execute('SELECT source,layer,count(*) FROM observation GROUP BY source,layer ORDER BY source,layer').fetchall()
    finally:
        db.close()


def collect(destination: Path, getter=fetch):
    # Refuse overwrite: failure never replaces an earlier usable batch.
    destination.mkdir(parents=True, exist_ok=False)
    raw_dir = destination / 'raw'
    raw_dir.mkdir()
    manifest = dict(schema_version=1, retrieved_at=datetime.now(timezone.utc).isoformat(), state='collecting', sources=SOURCES, files=[], coverage='European offshore / UK wind observations; not a complete global catalog', gem_status='awaiting_official_download', cross_source_deduplication='not_performed', engineering_bindings=0)
    records = []
    def save(name, url, raw):
        (raw_dir / name).write_bytes(raw)
        manifest['files'].append(dict(path='raw/' + name, url=url, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    try:
        for layer in ('windfarms', 'windfarmspoly'):
            for n, (url, raw, features, expected) in enumerate(wfs_pages(layer, getter)):
                save(f'{layer}-{n:03d}.geojson', url, raw)
                records.extend(emodnet_record(layer, f) for f in features)
        page = getter(REPD)
        save('repd-source-page.html', REPD, page)
        csv_url = discover_repd(page)
        raw = getter(csv_url)
        save('repd.csv', csv_url, raw)
        records.extend(repd_records(raw))
        counts = write_database(destination / 'catalog.sqlite', records, manifest)
        manifest.update(state='complete', observations=len(records), counts=[dict(source=s,layer=l,count=n) for s,l,n in counts], issue_records=sum(bool(r['issues']) for r in records), mapped_geometries=sum(bool(r['geometry']) for r in records), repd_release=csv_url.rsplit('/',1)[-1])
        # Public normalized export retains provenance and quality. No inferred turbine positions.
        with (destination/'observations.jsonl').open('w') as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False, allow_nan=False) + '\n')
    except Exception as exc:
        manifest.update(state='failed', error=str(exc))
        (destination/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        (destination/'catalog.sqlite').unlink(missing_ok=True)
        raise
    (destination/'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='New batch directory (must not exist)')
    args = parser.parse_args()
    try:
        result = collect(args.output)
    except Exception as exc:
        print('Collection failed: ' + str(exc), file=sys.stderr)
        return 1
    print(json.dumps({k:result[k] for k in ('state','counts','mapped_geometries','coverage','gem_status')}, ensure_ascii=False, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
