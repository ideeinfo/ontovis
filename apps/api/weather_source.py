"""Bounded MET Norway forecast reads; never a station or equipment observation."""
from __future__ import annotations
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
import zlib

ENDPOINT = 'https://api.met.no/weatherapi/locationforecast/2.0/compact'
MAX_BYTES = 512 * 1024
SOURCE = dict(provider='met_no', name='MET Norway', url='https://api.met.no/',
              license='CC BY 4.0', licenseUrl='https://creativecommons.org/licenses/by/4.0/',
              kind='forecast', transformation='Selected forecast period; normalized units and weather display')


class WeatherFailure(Exception):
    def __init__(self, code, retry=600):
        self.code, self.retry = code, retry


def timestamp(value):
    if not isinstance(value, str) or len(value) > 40: raise ValueError('timestamp')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if date.tzinfo is None: raise ValueError('timezone')
    return date.timestamp()


def iso(value): return datetime.fromtimestamp(value, timezone.utc).isoformat().replace('+00:00', 'Z')


def http_time(value, default):
    try: return parsedate_to_datetime(value).timestamp()
    except (TypeError, ValueError, OverflowError): return default


class SameOriginRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if (target.scheme != 'https' or target.netloc != 'api.met.no'
                or not target.path.startswith('/weatherapi/locationforecast/')):
            raise WeatherFailure('WEATHER_REDIRECT_REFUSED')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(point, contact, modified=None):
    query = urlencode({'lat': format(point['latitude'], '.4f'), 'lon': format(point['longitude'], '.4f')})
    headers = {'User-Agent': 'vis.ontobase.ai/1.0 ' + contact, 'Accept': 'application/json',
               'Accept-Encoding': 'gzip, deflate'}
    if modified: headers['If-Modified-Since'] = modified
    try:
        try: response = build_opener(SameOriginRedirect()).open(Request(ENDPOINT + '?' + query, headers=headers), timeout=9)
        except HTTPError as error:
            if error.code == 304: response = error
            else:
                with error:
                    retry = error.headers.get('Retry-After', '')
                    retry = min(86400, max(600, int(retry))) if retry.isdecimal() else 1800
                    raise WeatherFailure('WEATHER_RATE_LIMITED' if error.code == 429 else 'WEATHER_PROVIDER_UNAVAILABLE', retry)
        with response:
            meta = {key.lower(): response.headers.get(key) for key in ('Expires', 'Last-Modified')}
            if response.code == 304: return 304, None, meta
            if response.code != 200: raise WeatherFailure('WEATHER_PROVIDER_UNAVAILABLE')
            if response.headers.get_content_type() != 'application/json': raise WeatherFailure('WEATHER_INVALID_DATA')
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES: raise WeatherFailure('WEATHER_INVALID_DATA')
            encoding = response.headers.get('Content-Encoding', '').lower()
            if encoding in ('gzip', 'deflate'):
                decoder = zlib.decompressobj(16 + zlib.MAX_WBITS if encoding == 'gzip' else zlib.MAX_WBITS)
                data = decoder.decompress(data, MAX_BYTES + 1)
                if len(data) > MAX_BYTES or not decoder.eof or decoder.unused_data: raise WeatherFailure('WEATHER_INVALID_DATA')
            elif encoding: raise WeatherFailure('WEATHER_INVALID_DATA')
            def invalid(_): raise ValueError('non-finite number')
            value = json.loads(data, parse_constant=invalid)
            validate_document(value, point)
            return 200, value, meta
    except WeatherFailure: raise
    except (TimeoutError, OSError, URLError): raise WeatherFailure('WEATHER_PROVIDER_UNAVAILABLE') from None
    except (ValueError, TypeError, KeyError, zlib.error): raise WeatherFailure('WEATHER_INVALID_DATA') from None


def validate_document(value, point):
    try:
        coords = value['geometry']['coordinates']
        if value['type'] != 'Feature' or len(coords) != 3: raise ValueError('geometry')
        for actual, expected in zip(coords[:2], (point['longitude'], point['latitude'])):
            if type(actual) not in (float, int) or not math.isfinite(actual) or abs(actual - expected) > .0002: raise ValueError('point')
        properties = value['properties']; timestamp(properties['meta']['updated_at'])
        if type(properties['meta']['units']) is not dict: raise ValueError('units')
        steps = properties['timeseries']
        if type(steps) is not list or not 1 <= len(steps) <= 200: raise ValueError('steps')
        times = [timestamp(row['time']) for row in steps]
        if times != sorted(set(times)): raise ValueError('order')
    except (KeyError, TypeError, ValueError, OverflowError): raise WeatherFailure('WEATHER_INVALID_DATA') from None


def condition(symbol):
    base = symbol.split('_')[0] if isinstance(symbol, str) else ''
    # Unknown provider symbols must not become apparently clear weather.
    if not re.fullmatch(r'(clearsky|fair|partlycloudy|cloudy|fog|(?:light|heavy)?(?:rain|snow|sleet)(?:showers)?(?:andthunder)?)', base): return 'unknown'
    if 'sleet' in base: return 'sleet'
    if 'snow' in base: return 'snow'
    if 'rain' in base: return 'rain'
    if base == 'fog': return 'fog'
    if base in ('cloudy', 'partlycloudy'): return 'cloud'
    return 'clear'


def forecast(value, now):
    try:
        properties = value['properties']; units = properties['meta']['units']
        updated = timestamp(properties['meta']['updated_at'])
        rows = [row for row in properties['timeseries'] if timestamp(row['time']) <= now]
        if not rows: return None
        row = rows[-1]; start = timestamp(row['time']); data = row['data']
        hours = next((h for h in (1, 6, 12) if isinstance(data.get(f'next_{h}_hours'), dict)), None)
        if hours is None: return None
        period = data[f'next_{hours}_hours']; details = data.get('instant', {}).get('details', {})
        symbol = period.get('summary', {}).get('symbol_code')
        def number(source, key, unit, low, high):
            result = source.get(key)
            return result if (units.get(key) == unit and type(result) in (float, int)
                              and math.isfinite(result) and low <= result <= high) else None
        kind = condition(symbol)
        return dict(validFrom=iso(start), validTo=iso(start + hours * 3600), updatedAt=iso(updated),
                    intervalHours=hours, symbol=symbol if kind != 'unknown' else None, condition=kind,
                    temperatureC=number(details, 'air_temperature', 'celsius', -100, 70),
                    windSpeedMs=number(details, 'wind_speed', 'm/s', 0, 150),
                    windFromDeg=number(details, 'wind_from_direction', 'degrees', 0, 360),
                    cloudPercent=number(details, 'cloud_area_fraction', '%', 0, 100),
                    precipitationMm=number(period.get('details', {}), 'precipitation_amount', 'mm', 0, 3000),
                    usable=start <= now < start + hours * 3600 and now - 43200 <= updated <= now + 300 and kind != 'unknown')
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError): return None
