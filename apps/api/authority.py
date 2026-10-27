"""Bounded loopback transport for ONTOVis user-authorized engineering reads."""
from __future__ import annotations
import json
import hashlib
import urllib.error
import urllib.parse
import urllib.request

class PreviewError(Exception):
    def __init__(self, status: int, code: str):
        self.status, self.code = status, code
        super().__init__(code)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise PreviewError(502, 'SOURCE_UNAVAILABLE')


class Authority:
    def __init__(self, base_url: str):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username:
            raise ValueError('The source must be the loopback SSH tunnel')
        self.base_url = base_url
        self.token: str | None = None
        self.username: str | None = None
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        headers = {'Accept': 'application/json'}
        if self.token:
            headers['Authorization'] = 'Bearer ' + self.token
        if body is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base_url + path, method=method, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise PreviewError(502, 'SOURCE_UNAVAILABLE')
                result = json.loads(raw)
                if not isinstance(result, dict):
                    raise PreviewError(502, 'SOURCE_UNAVAILABLE')
                return result
        except urllib.error.HTTPError as error:
            code = 'SOURCE_UNAVAILABLE'
            if error.code in (401, 403, 404, 409, 413, 422, 503):
                try:
                    detail = json.loads(error.read(16384)).get('detail', {})
                    code = detail.get('code') if isinstance(detail, dict) else None
                except (ValueError, AttributeError):
                    code = None
                code = code or {401:'SESSION_EXPIRED',403:'FORBIDDEN',404:'NOT_FOUND_OR_FORBIDDEN',409:'REVISION_CONFLICT',413:'CONTENT_SIZE_LIMIT',422:'INVALID_REQUEST',503:'SOURCE_UNAVAILABLE'}[error.code]
                status = error.code
                error.close()
                raise PreviewError(status, code) from None
            error.close()
            raise PreviewError(502, code) from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise PreviewError(502, 'SOURCE_UNAVAILABLE') from None

    def login(self, username: str, password: str) -> None:
        result = self.request('POST', '/api/v1/auth/login', {'username': username, 'password': password})
        self.token = result['token']
        self.username = result['user']['username']

    def image(self, path: str, body: dict) -> bytes:
        """Only the workbench's fixed evidence route calls this bounded reader."""
        request = urllib.request.Request(self.base_url + path, method='POST',
            headers={'Authorization':'Bearer ' + self.token, 'Content-Type':'application/json',
                     'Accept':'image/png', 'Cache-Control':'no-store'}, data=json.dumps(body).encode())
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(20 * 1024 * 1024 + 1)
                if (len(raw) > 20 * 1024 * 1024 or not raw.startswith(b'\x89PNG\r\n\x1a\n')
                        or response.headers.get_content_type() != 'image/png'
                        or response.headers.get('X-Source-Content-SHA256') != body['expectedContentSha256']):
                    raise PreviewError(502, 'SOURCE_UNAVAILABLE')
                return raw
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read(16384)).get('detail', {})
                code = detail.get('code') if isinstance(detail, dict) else None
            except (ValueError, AttributeError):
                code = None
            status = error.code if error.code in (401,403,404,409,413,422,503) else 502
            error.close()
            raise PreviewError(status, code or 'SOURCE_UNAVAILABLE') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise PreviewError(502, 'SOURCE_UNAVAILABLE') from None

    def photo(self, path: str, body: dict, display_sha256: str) -> dict:
        """Read only the fixed, authorized display rendition; never follow URLs."""
        request = urllib.request.Request(self.base_url + path, method='POST',
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json',
                     'Accept': 'image/png,image/jpeg,image/webp', 'Cache-Control': 'no-store'},
            data=json.dumps(body).encode())
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(20 * 1024 * 1024 + 1)
                mime = response.headers.get_content_type()
                signature = (mime == 'image/png' and raw.startswith(b'\x89PNG\r\n\x1a\n')
                    or mime == 'image/jpeg' and raw.startswith(b'\xff\xd8\xff')
                    or mime == 'image/webp' and raw.startswith(b'RIFF') and raw[8:12] == b'WEBP')
                if (not raw or len(raw) > 20 * 1024 * 1024 or not signature
                        or hashlib.sha256(raw).hexdigest() != display_sha256
                        or response.headers.get('X-Content-SHA256') != display_sha256
                        or response.headers.get('X-Document-Content-Version') != body['expectedContentVersionId']
                        or response.headers.get('X-Anchor-Applies-To') != 'display_rendition'):
                    raise PreviewError(409, 'CONTENT_CHANGED')
                return {'content': raw, 'mediaType': mime, 'sha256': display_sha256}
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read(16384)).get('detail', {})
                code = detail.get('code') if isinstance(detail, dict) else None
            except (ValueError, AttributeError):
                code = None
            status = error.code if error.code in (401, 403, 404, 409, 413, 422, 503) else 502
            error.close()
            raise PreviewError(status, code or 'SOURCE_UNAVAILABLE') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise PreviewError(502, 'SOURCE_UNAVAILABLE') from None

    def document_page(self, path: str) -> dict:
        """GET a server-constructed fixed document page, never a client URL."""
        request = urllib.request.Request(self.base_url + path, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': 'image/png', 'Cache-Control': 'no-store'})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(20 * 1024 * 1024 + 1)
                if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw) > 20 * 1024 * 1024 or response.headers.get_content_type() != 'image/png':
                    raise PreviewError(502, 'SOURCE_UNAVAILABLE')
                return {'content': raw, 'mediaType': 'image/png', 'sha256': hashlib.sha256(raw).hexdigest()}
        except urllib.error.HTTPError as error:
            status = error.code if error.code in (401,403,404,409,410,413,422,503) else 502
            error.close(); raise PreviewError(status, 'ANALYSIS_SOURCE_UNAVAILABLE') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise PreviewError(502, 'SOURCE_UNAVAILABLE') from None

    def source_bytes(self, path: str, media_types: tuple[str, ...]) -> dict:
        """A server-constructed source path; callers verify project and fixed identity."""
        request = urllib.request.Request(self.base_url + path, headers={
            'Authorization': 'Bearer ' + self.token, 'Accept': ','.join(media_types)})
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(20 * 1024 * 1024 + 1); mime = response.headers.get_content_type()
                if not raw or len(raw) > 20 * 1024 * 1024 or mime not in media_types:
                    raise PreviewError(502, 'SOURCE_UNAVAILABLE')
                return {'content': raw, 'mediaType': mime, 'sha256': hashlib.sha256(raw).hexdigest()}
        except urllib.error.HTTPError as error:
            status = error.code if error.code in (401, 403, 404, 409, 410, 413, 422, 503) else 502
            error.close(); raise PreviewError(status, 'ANALYSIS_SOURCE_UNAVAILABLE') from None
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise PreviewError(502, 'SOURCE_UNAVAILABLE') from None

