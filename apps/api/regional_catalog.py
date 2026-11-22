"""Read a verified, immutable regional wind directory without entering project data."""
from contextlib import closing
import json
from pathlib import Path
import re
import sqlite3

from .authority import PreviewError


REVISION = re.compile(r'[0-9a-f]{64}')
MAX_CATALOG_BYTES = 64 * 1024 * 1024
FIELDS = ('id','source','layer','sourceId','name','country','status','installation',
          'capacityMw','turbineCount','sourceUpdated','locationAccuracy','longitude','latitude')
LIST_FIELDS = ('q','source','country','status','bbox','offset','limit','catalogRevision')


def require(condition, code='INVALID_REQUEST', status=422):
    if not condition:
        raise PreviewError(status, code)


def connect(path: Path):
    return sqlite3.connect(path.absolute().as_uri()+'?mode=ro&immutable=1', uri=True)


def catalogue_path(root: Path, revision: str):
    require(type(revision) is str and REVISION.fullmatch(revision), 'REGIONAL_CATALOG_UNAVAILABLE', 503)
    path = root/(revision+'.sqlite')
    require(path.is_file() and 0 < path.stat().st_size <= MAX_CATALOG_BYTES, 'REGIONAL_CATALOG_UNAVAILABLE', 503)
    return path


def metadata(db):
    row, = db.execute('select json from publication')
    return json.loads(row[0])


def _text(value, maximum):
    require(type(value) is str and len(value) <= maximum and all(ord(ch) >= 32 and ord(ch) != 127 for ch in value))
    return value.strip()


def _list(db, body, expected):
    require(set(body) <= set(LIST_FIELDS))
    q = _text(body.get('q',''),120).casefold()
    source = body.get('source','')
    require(source in ('','emodnet','repd'))
    country, status = (_text(body.get(key,''),100) for key in ('country','status'))
    offset, limit = body.get('offset',0), body.get('limit',50)
    require(type(offset) is int and 0 <= offset <= 100000 and type(limit) is int and 1 <= limit <= 100)
    require(not offset or expected is not None)
    clauses, values = [], []
    if q:
        clauses.append('instr(searchName,?)>0')
        values.append(q)
    for column, value in (('source',source),('country',country),('status',status)):
        if value:
            clauses.append(column+'=?')
            values.append(value)
    if 'bbox' in body:
        bbox = body['bbox']
        require(type(bbox) is list and len(bbox)==4 and all(type(n) in (int,float) and -180 <= n <= 180 for n in bbox))
        west,south,east,north = bbox
        require(-180 <= west < east <= 180 and -90 <= south < north <= 90)
        clauses.append('east>=? and north>=? and west<=? and south<=?')
        values.extend(bbox)
    where = ' where '+' and '.join(clauses) if clauses else ''
    total, = db.execute('select count(*) from observation'+where, values).fetchone()
    rows = db.execute('select '+','.join(FIELDS)+' from observation'+where+
                      ' order by searchName,source,layer,sourceId limit ? offset ?', (*values,limit,offset))
    return {'total':total, 'items':[dict(zip(FIELDS,row)) for row in rows],
            'nextOffset':offset+limit if total>offset+limit else None}


def _detail(db, body):
    require(set(body)=={'id','catalogRevision'} and _text(body['id'],300))
    row = db.execute('select '+','.join(FIELDS)+',geometry,west,south,east,north from observation where id=?',(body['id'],)).fetchone()
    require(row is not None, 'NOT_FOUND_OR_FORBIDDEN', 404)
    geometry,*bounds=row[len(FIELDS):]
    return {'item':{**dict(zip(FIELDS,row)), 'geometry':json.loads(geometry) if geometry else None,
                    'bounds':bounds if bounds[0] is not None else None}}


def read(root: Path, body: dict):
    require(type(body) is dict)
    expected = body.get('catalogRevision')
    if 'catalogRevision' in body:
        require(type(expected) is str and REVISION.fullmatch(expected))
    try:
        with (root/'current').open(encoding='ascii') as stream:
            revision = stream.read(66).strip()
        path = catalogue_path(root,revision)
        require(expected is None or expected == revision, 'CATALOG_CHANGED', 409)
        with closing(connect(path)) as db:
            result = _detail(db,body) if 'id' in body else _list(db,body,expected)
            return {**result,'catalogRevision':revision,'publication':metadata(db)}
    except (OSError, UnicodeError, sqlite3.Error, ValueError) as error:
        raise PreviewError(503,'REGIONAL_CATALOG_UNAVAILABLE') from error
