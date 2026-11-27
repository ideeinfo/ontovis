#!/usr/bin/env python3
"""Same-origin user sessions for the single approved demonstration installation.

Run behind the site's loopback reverse proxy. No business writes or arbitrary
upstream routes are exposed; passwords are used once and never retained.
"""
from __future__ import annotations

import argparse
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.installation_preview import Authority, InstallationPreview, PreviewError, load_manifest

from apps.api.user_sessions import COOKIE, IDLE_SECONDS, MAX_SECONDS, UserSessions


class Sessions(UserSessions):
    def __init__(self, base_url, manifest, *, clock=time.monotonic, factory=Authority):
        self.manifest = manifest
        super().__init__(base_url, manifest['projectCode'], clock=clock, factory=factory)

    def read(self, sid, path, query):
        with self.lock:
            row = self.current(sid, authenticated=True, touch=True)
            authority = row.authority
        try:
            revision = self.access(authority)
            preview = InstallationPreview(authority, self.manifest)
            if path == '/api/demo/context' and not query:
                value = preview.catalog()
            elif path == '/api/demo/locate' and set(query) == {'entityUid','unitLabel','contextEpoch'} and all(len(items)==1 and 0 < len(items[0]) <= 512 for items in query.values()):
                value = preview.locate(query['entityUid'][0], query['unitLabel'][0], query['contextEpoch'][0])
            else:
                raise PreviewError(422, 'INVALID_REQUEST')
            self.guard(sid, row)
            if self.access(authority) != revision:
                raise PreviewError(409, 'ACCESS_CHANGED')
            self.guard(sid, row)
            value['sessionRevision'] = row.revision
            return value
        except PreviewError as error:
            if error.status == 401: self.invalidate(sid, row)
            raise


from apps.api.session_http import handler_type


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--model-root', required=True, type=Path)
    parser.add_argument('--source', default='http://127.0.0.1:18001')
    parser.add_argument('--origin', default='https://vis.ontobase.ai')
    parser.add_argument('--port', type=int, default=18083)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest, args.model_root)
    sessions = Sessions(args.source, manifest)
    server = ThreadingHTTPServer(('127.0.0.1',args.port), handler_type(sessions,args.origin))
    print('ONTOVis read-only session service ready', flush=True)
    server.serve_forever()


if __name__ == '__main__': main()
