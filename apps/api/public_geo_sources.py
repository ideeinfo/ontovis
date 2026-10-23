"""Fixed anonymous overview sources; no caller-supplied URL is accepted."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import math
import re
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .authority import PreviewError

STAC = 'https://earth-search.aws.element84.com/v1/search'
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_RADIUS_KM = 10
SENTINEL_PREFIX = 'https://e84-earth-search-sentinel-data.s3.us-west-2.amazonaws.com/'
DEM_PREFIX = 'https://copernicus-dem-30m.s3.eu-central-1.amazonaws.com/'


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise PreviewError(502, 'PUBLIC_SOURCE_UNAVAILABLE')


def request_json(url, payload=None, *, max_bytes=MAX_JSON_BYTES):
    if url != STAC:
        raise PreviewError(422, 'INVALID_REQUEST')
    headers = {'User-Agent': 'ONTOVis/0.1 (explicit project overview acquisition)', 'Accept': 'application/json'}
    raw = None if payload is None else json.dumps(payload, allow_nan=False).encode()
    if raw is not None: headers['Content-Type'] = 'application/json'
    try:
        with build_opener(NoRedirect()).open(Request(url, data=raw, headers=headers), timeout=12) as response:
            length = response.headers.get('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > max_bytes):
                raise PreviewError(502, 'PUBLIC_SOURCE_UNAVAILABLE')
            data = response.read(max_bytes + 1)
        if len(data) > max_bytes: raise PreviewError(502, 'PUBLIC_SOURCE_UNAVAILABLE')
        return json.loads(data)
    except PreviewError:
        raise
    except (OSError, ValueError, UnicodeError, RecursionError):
        raise PreviewError(502, 'PUBLIC_SOURCE_UNAVAILABLE') from None


def region(value):
    fields = {'longitude', 'latitude', 'radiusKm', 'name', 'terrain', 'imagery', 'clientRequestId'}
    if type(value) is not dict or set(value) != fields:
        raise PreviewError(422, 'INVALID_REQUEST')
    longitude, latitude, radius = (value[key] for key in ('longitude', 'latitude', 'radiusKm'))
    if any(type(number) not in (int, float) or not math.isfinite(number) for number in (longitude, latitude, radius)):
        raise PreviewError(422, 'INVALID_COORDINATE')
    if not (-180 < longitude < 180 and -79.8 <= latitude <= 83.8 and .5 <= radius <= MAX_RADIUS_KM):
        raise PreviewError(422, 'INVALID_COORDINATE')
    if (type(value['name']) is not str or not 0 < len(value['name'].strip()) <= 120
            or any(ord(character) < 32 for character in value['name'])):
        raise PreviewError(422, 'INVALID_REQUEST')
    if any(type(value[key]) is not bool for key in ('terrain', 'imagery')) or not (value['terrain'] or value['imagery']):
        raise PreviewError(422, 'INVALID_REQUEST')
    # A conservative geographic enclosure of the requested metric radius. The
    # worker builds a north-up UTM grid; the circular mask is applied there.
    dy = radius / 110.5
    dx = radius / (110.5 * math.cos(math.radians(abs(latitude) + dy)))
    bbox = [longitude-dx, latitude-dy, longitude+dx, latitude+dy]
    if not (-180 < bbox[0] < bbox[2] < 180 and -80 < bbox[1] < bbox[3] < 84):
        raise PreviewError(422, 'OUTSIDE_PROJECTION_AREA')
    return {**value, 'name': value['name'].strip(), 'bbox': bbox}


def asset_url(item, key):
    try: url = item['assets'][key]['href']
    except (KeyError, TypeError): raise PreviewError(502, 'PUBLIC_SOURCE_UNAVAILABLE') from None
    if key == 'data' and type(url) is str and url.startswith('s3://copernicus-dem-30m/'):
        url = DEM_PREFIX + url.removeprefix('s3://copernicus-dem-30m/')
    if key == 'data':
        valid = type(url) is str and re.fullmatch(re.escape(DEM_PREFIX) + r'(Copernicus_DSM_COG_10_[NS]\d{2}_00_[EW]\d{3}_00_DEM)/\1\.tif', url)
    else:
        valid = type(url) is str and re.fullmatch(re.escape(SENTINEL_PREFIX) + r'sentinel-2-c1-l2a/\d{1,2}/[A-Z]/[A-Z]{2}/\d{4}/\d{1,2}/S2[ABC]_T\d{2}[A-Z]{3}_\d{8}T\d{6}_L2A/' + ('TCI' if key == 'visual' else 'SCL') + r'\.tif', url)
    if not valid: raise PreviewError(502, 'PUBLIC_SOURCE_UNAVAILABLE')
    return url


def catalog(collection, bbox):
    payload = {'collections': [collection], 'bbox': bbox, 'limit': 60 if collection.startswith('sentinel') else 9}
    if collection.startswith('sentinel'):
        now = datetime.now(timezone.utc)
        payload.update(datetime=(now-timedelta(days=550)).strftime('%Y-%m-%dT00:00:00Z') + '/' + now.strftime('%Y-%m-%dT23:59:59Z'),
                       sortby=[{'field': 'properties.datetime', 'direction': 'desc'}], query={'eo:cloud_cover': {'lte': 35}})
    result = request_json(STAC, payload)
    items = result.get('features') if type(result) is dict else None
    if type(items) is not list or not items or len(items) > payload['limit']:
        raise PreviewError(422, 'PUBLIC_COVERAGE_UNAVAILABLE')
    return items


def imagery_group(items, bbox):
    groups = {}
    for item in items:
        try:
            day = item['properties']['datetime'][:10]
            cloud = float(item['properties']['eo:cloud_cover'])
            if not math.isfinite(cloud) or not 0 <= cloud <= 35: continue
            asset_url(item, 'visual'); asset_url(item, 'scl')
            groups.setdefault(day, []).append(item)
        except (KeyError, TypeError, ValueError):
            continue
    west, south, east, north = bbox
    for day in sorted(groups, reverse=True):
        candidates = sorted(groups[day], key=lambda item: (item['properties']['eo:cloud_cover'], item['id']))[:4]
        corners = [(west, south), (west, north), (east, south), (east, north)]
        if all(any(item['bbox'][0] <= x <= item['bbox'][2] and item['bbox'][1] <= y <= item['bbox'][3]
                   for item in candidates) for x, y in corners):
            return day, candidates
    raise PreviewError(422, 'PUBLIC_COVERAGE_UNAVAILABLE')

