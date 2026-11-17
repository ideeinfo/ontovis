"""Fixed project-document images for equipment previews and analysis sources."""
from urllib.parse import urlencode

from . import analysis_drafts as d
from .analysis_media import FULL_PHOTO_REPRESENTATIONS, full_resolution_photo


class FixedDocuments:
    def __init__(self, reader):
        self.reader = reader

    def metadata(self, body):
        d.require(type(body) is dict and {'documentId', 'contentVersionId'} <= set(body)
                  <= {'documentId', 'contentVersionId', 'pageNumber', 'sourceSha256'}, 'INVALID_REQUEST', 422)
        document_id = d.identifier(body['documentId']); version_id = d.identifier(body['contentVersionId'])
        page = body.get('pageNumber', 1)
        d.require(type(page) is int and 1 <= page <= 10000, 'INVALID_REQUEST', 422)
        if 'sourceSha256' in body:
            sha=body['sourceSha256']
            d.require(type(sha) is str and len(sha)==64 and all(c in '0123456789abcdef' for c in sha), 'INVALID_REQUEST', 422)
        prefix = self.reader.prefix + '/documents/' + document_id
        document = self.reader._request('GET', prefix)['item']
        version = self.reader._request('GET', prefix + '/versions/' + version_id)['item']
        d.require(document.get('id') == document_id and version.get('id') == version_id
                  and version.get('document_id') == document_id, 'SOURCE_CHANGED', 409)
        d.require(document.get('status') in ('active', 'archived'), 'ANALYSIS_SOURCE_UNAVAILABLE', 410)
        kind = version.get('preview_kind')
        d.require(kind in ('pdf', 'image') and not version.get('preview_error'), 'ANALYSIS_SOURCE_UNAVAILABLE', 409)
        pages = version.get('page_count') if kind == 'pdf' else 1
        d.require(type(pages) is int and 1 <= page <= pages, 'ANALYSIS_DOCUMENT_PAGE_UNAVAILABLE', 409)
        sha = version.get('source_sha256')
        d.require(type(sha) is str and len(sha) == 64 and all(c in '0123456789abcdef' for c in sha), 'SOURCE_CHANGED', 409)
        d.require('sourceSha256' not in body or body['sourceSha256'] == sha, 'SOURCE_CHANGED', 409)
        return dict(documentId=document_id, contentVersionId=version_id, sourceSha256=sha,
            title=document['name'], kind='pdf' if kind == 'pdf' else 'photo', documentKind=document.get('kind'),
            mediaProjection=version.get('media_projection'),
            pageNumber=page, pageCount=pages, versionNumber=version['version_number'],
            newerVersionAvailable=document['current_version_id'] != version_id, sourceType='project_document', selector=None)

    def content(self, body):
        d.require(type(body) is dict, 'INVALID_REQUEST', 422)
        representation = body.get('representation', 'display')
        d.require(representation in ('preview', 'display', *FULL_PHOTO_REPRESENTATIONS), 'INVALID_REQUEST', 422)
        fixed = self.metadata({key:value for key,value in body.items() if key!='representation'})
        path = self.reader.prefix + '/documents/' + fixed['documentId'] + '/content?' + urlencode({
            'version_id': fixed['contentVersionId'], 'rendition': 'display', 'page': fixed['pageNumber']})
        def read():return self.reader.authority.document_page(path,photo=fixed['kind']=='photo')
        if fixed['kind']=='photo' and representation=='preview':
            from .analysis_media import derived,photo_image
            return derived(('project-photo-4096-jpeg-82',getattr(self.reader,'connection_id',''),self.reader.prefix,
                fixed['documentId'],fixed['contentVersionId'],fixed['sourceSha256']),lambda:photo_image(read()))
        value = read()
        if fixed['documentKind'] == 'photo' and fixed['kind'] == 'photo' and representation in FULL_PHOTO_REPRESENTATIONS:
            value = full_resolution_photo(value, fixed['mediaProjection'],
                                          prefer_avif=representation == 'full_resolution_avif')
        return value
