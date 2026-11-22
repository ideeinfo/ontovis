"""Build, activate or roll back a validated regional wind directory batch."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

from apps.api.regional_catalog import FIELDS, MAX_CATALOG_BYTES, catalogue_path, connect, metadata
from tools.wind_catalog import SOURCES, geometry_bounds


def dump(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def revision(path):
    if not 0 < path.stat().st_size <= MAX_CATALOG_BYTES:
        raise ValueError('Unexpected publication size')
    with path.open('rb') as stream:
        return hashlib.file_digest(stream,'sha256').hexdigest()


def build(batch: Path, artifact: Path):
    manifest=json.loads((batch/'manifest.json').read_text())
    if (manifest.get('state') != 'complete' or manifest.get('schema_version') != 1
            or manifest.get('sources') != SOURCES):
        raise ValueError('Expected a complete admitted EMODnet/REPD staging batch')
    with closing(connect(batch/'catalog.sqlite')) as staging:
        if staging.execute('pragma integrity_check').fetchone() != ('ok',):
            raise ValueError('Staging database integrity check failed')
        groups=staging.execute('select source,layer,count(*) from observation group by source,layer order by source,layer').fetchall()
        if ([dict(source=s,layer=l,count=n) for s,l,n in groups] != manifest['counts']
                or {(s,l) for s,l,n in groups if n>0} != {('emodnet','windfarms'),('emodnet','windfarmspoly'),('repd','wind')}
                or sum(n for _,_,n in groups) != manifest['observations']):
            raise ValueError('The admitted sources and row counts must match the staging batch')
        publication=dict(retrievedAt=manifest['retrieved_at'],repdRelease=manifest['repd_release'],
            sources={name:{'attribution':s['attribution'],'metadataUrl':s['metadata'],'licenseUrl':s['license']}
                     for name,s in SOURCES.items()}, sourceObservations=manifest['observations'])
        rows=staging.execute('''select source,layer,source_id,trim(name),country,status,installation,capacity_mw,turbine_count,
           source_updated,coordinate_quality,geometry_json from observation where trim(name) != '' order by source,layer,source_id''')
        with artifact.open('xb'):
            pass
        try:
            with closing(sqlite3.connect(artifact)) as result, result:
                result.executescript('''
                    create table publication(json text not null);
                    create table observation(
                      id text primary key,source text not null,layer text not null,sourceId text not null,name text not null,
                      country text,status text,installation text,capacityMw real,turbineCount integer,sourceUpdated text,
                      locationAccuracy text not null,longitude real,latitude real,searchName text not null,
                      geometry text,west real,south real,east real,north real);
                    create index observation_list on observation(searchName,source,layer,sourceId);
                    create index observation_filter on observation(source,country,status);
                ''')
                for source,layer,source_id,name,country,status,installation,mw,count,updated,accuracy,raw in rows:
                    if not 0 < len(name) <= 300 or not 0 < len(source_id) <= 220:
                        raise ValueError('Invalid public observation name or identity')
                    geometry=json.loads(raw) if raw else None
                    expected={'source_site_point':('Point',),'source_site_boundary':('Polygon','MultiPolygon'),
                              'unresolved_source_grid':()}
                    if accuracy not in expected or geometry and geometry['type'] not in expected[accuracy]:
                        raise ValueError('Source geometry does not match its location statement')
                    bounds=geometry_bounds(geometry)
                    lon,lat=geometry['coordinates'][:2] if geometry and accuracy=='source_site_point' else (None,None)
                    result.execute('insert into observation values('+','.join('?' for _ in range(20))+')',
                        (source+':'+layer+':'+source_id,source,layer,source_id,name,country,status,installation,mw,count,updated,
                         accuracy,lon,lat,name.casefold(),dump(geometry) if geometry else None,*(bounds or (None,)*4)))
                publication['visibleObservations']=result.execute('select count(*) from observation').fetchone()[0]
                result.execute('insert into publication values(?)',(dump(publication),))
        except BaseException:
            artifact.unlink(missing_ok=True)
            raise
    return {**publication,'catalogRevision':revision(artifact)}


def check(path):
    identity=revision(path)
    with closing(connect(path)) as db:
        if db.execute('pragma integrity_check').fetchone()!=('ok',):
            raise ValueError('Invalid publication database')
        meta=metadata(db)
        count=db.execute('select count(*) from observation').fetchone()[0]
        if meta['visibleObservations']!=count or not 0<count<=100000:
            raise ValueError('Invalid publication row count')
        if tuple(column[1] for column in db.execute('pragma table_info(observation)'))[:len(FIELDS)]!=FIELDS:
            raise ValueError('Invalid publication columns')
    return identity


def _replace(root: Path, destination: Path, write):
    fd, name=tempfile.mkstemp(dir=root)
    path=Path(name)
    try:
        with os.fdopen(fd,'wb') as stream:
            write(stream)
            stream.flush()
            os.fsync(stream.fileno())
        path.chmod(0o644)
        path.replace(destination)
    finally:
        path.unlink(missing_ok=True)


def activate(root: Path, artifact: Path):
    identity=check(artifact)
    root.mkdir(mode=0o755,parents=True,exist_ok=True)
    target=root/(identity+'.sqlite')
    if not target.exists() or revision(target) != identity:
        def copy(stream):
            transferred=hashlib.sha256()
            with artifact.open('rb') as original:
                for chunk in iter(lambda:original.read(1024*1024),b''):
                    transferred.update(chunk)
                    stream.write(chunk)
            if transferred.hexdigest()!=identity:
                raise ValueError('Publication changed during copy')
        _replace(root,target,copy)
    return rollback(root,identity)


def rollback(root: Path, identity: str):
    if check(catalogue_path(root,identity)) != identity:
        raise ValueError('Publication digest differs from its identity')
    _replace(root,root/'current',lambda stream:stream.write((identity+'\n').encode('ascii')))
    return identity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    actions=parser.add_subparsers(dest='action',required=True)
    for action, arguments in (('build',(('--batch',Path),('--artifact',Path))),
                              ('activate',(('--root',Path),('--artifact',Path))),
                              ('rollback',(('--root',Path),('--revision',str)))):
        sub=actions.add_parser(action)
        for flag, value_type in arguments:
            sub.add_argument(flag,type=value_type,required=True)
    args=parser.parse_args()
    value=(build(args.batch,args.artifact) if args.action=='build' else
           {'catalogRevision':activate(args.root,args.artifact) if args.action=='activate' else rollback(args.root,args.revision)})
    print(dump(value))


if __name__=='__main__':
    main()
