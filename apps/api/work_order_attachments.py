"""Work order references to versioned files owned by OntoBase."""
from pathlib import PurePosixPath
from urllib.parse import urlencode

from .analysis_drafts import identifier
from .analysis_evidence import sha
from .fixed_documents import FixedDocuments
from .work_orders import require, text

PART_BYTES = 4 * 1024 * 1024
MAX_BYTES = 128 * 1024 * 1024
PHOTO_BYTES = 32 * 1024 * 1024
PHOTO_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.webp'}
EXTENSIONS = PHOTO_EXTENSIONS | {
    '.pdf', '.docx', '.xlsx', '.md', '.txt', '.csv', '.json', '.jsonld', '.ttl',
    '.doc', '.xls', '.ppt', '.pptx', '.svg', '.mp4',
}


def fixed_metadata(reader, body):
    document_id = identifier(body['documentId'])
    version_id = identifier(body['contentVersionId'])
    prefix = reader.prefix + '/documents/' + document_id
    document = reader._request('GET', prefix)['item']
    version = reader._request('GET', prefix + '/versions/' + version_id)['item']
    require(document['id'] == document_id and document['project_code'] == reader.project_code
            and version['id'] == version_id and version['document_id'] == document_id,
            'SOURCE_CHANGED', 409)
    require(document['status'] in ('active', 'archived'), 'ANALYSIS_SOURCE_UNAVAILABLE', 410)
    require(type(version['byte_size']) is int and 0 < version['byte_size'] <= MAX_BYTES,
            'CONTENT_SIZE_LIMIT', 413)
    sha(version['source_sha256'])
    return {
        'documentId': document_id, 'contentVersionId': version_id, 'sourceSha256': version['source_sha256'],
        'title': document['name'], 'filename': version['original_filename'], 'kind': document['kind'],
        'versionNumber': version['version_number'], 'byteSize': version['byte_size'],
        'mediaType': version['media_type'], 'previewKind': version.get('preview_kind'),
        'pageCount': version.get('page_count'), 'previewAvailable': (
            version.get('preview_kind') in ('image', 'pdf') and not version.get('preview_error')
        ),
    }


def catalogue(reader, body):
    require(set(body) <= {'q', 'cursor'})
    q = text(body.get('q', ''), 200, empty=True)
    cursor = text(body.get('cursor') or '0', 500)
    value = reader._request('GET', reader.prefix + '/documents?' + urlencode({
        'q': q, 'status': 'active', 'limit': 20, 'cursor': cursor,
    }))
    return {
        'items': [
            {'documentId': item['id'], 'contentVersionId': item['current_version_id'],
             'title': item['name'], 'kind': item['kind']}
            for item in value['items'] if item['current_version_id']
        ],
        'nextCursor': value.get('next_cursor'),
    }


def upload(reader, action, body, *, stream=None, length=None):
    upload_id = identifier(body['uploadId'])
    prefix = reader.prefix + '/document-uploads'
    path = prefix + '/' + upload_id
    if action == 'start':
        require(set(body) == {'uploadId', 'filename', 'byteSize', 'sourceSha256'})
        filename = text(body['filename'], 500)
        require(PurePosixPath(filename).name == filename and '\\' not in filename)
        suffix = PurePosixPath(filename).suffix.lower()
        require(suffix in EXTENSIONS, 'document_format_unsupported', 422)
        kind = 'photo' if suffix in PHOTO_EXTENSIONS else 'other'
        size = body['byteSize']
        require(type(size) is int and 0 < size <= (PHOTO_BYTES if kind == 'photo' else MAX_BYTES),
                'CONTENT_SIZE_LIMIT', 413)
        digest = sha(body['sourceSha256'])
        result = reader._request('POST', prefix, {
            'upload_id': upload_id, 'filename': filename, 'name': filename,
            'byte_size': size, 'kind': kind, 'source_sha256': digest,
        })
        require(result.get('upload_id') == upload_id and result.get('part_size') == PART_BYTES
                and result.get('byte_size') == size, 'SOURCE_UNAVAILABLE', 502)
        return {'uploadId': upload_id, 'partBytes': PART_BYTES, 'parts': result['parts']}
    if action == 'part':
        require(set(body) == {'uploadId', 'index'} and type(body['index']) is int
                and 0 <= body['index'] < MAX_BYTES // PART_BYTES)
        require(type(length) is int and 0 < length <= PART_BYTES)
        content = stream.read(length)
        require(len(content) == length)
        result = reader.authority.document_upload_part(path + '/parts/' + str(body['index']), content)
        require(result.get('received_bytes') == length and result.get('index') == body['index'],
                'SOURCE_UNAVAILABLE', 502)
        return result
    require(action == 'complete' and set(body) == {'uploadId'})
    result = reader._request('POST', path + '/complete')
    return fixed_metadata(reader, {
        'documentId': result['item']['id'], 'contentVersionId': result['version_id'],
    })


def content(reader, attachment, *, page=None):
    selector = {k: attachment[k] for k in ('documentId', 'contentVersionId')}
    if page is not None:
        require(attachment['previewAvailable'], 'document_preview_unavailable', 409)
        return FixedDocuments(reader).content({
            **selector, 'sourceSha256': attachment['sourceSha256'], 'pageNumber': page,
        })
    fixed = fixed_metadata(reader, selector)
    require(fixed['sourceSha256'] == attachment['sourceSha256'], 'SOURCE_CHANGED', 409)
    path = reader.prefix + '/documents/' + fixed['documentId'] + '/content?' + urlencode({
        'version_id': fixed['contentVersionId'], 'rendition': 'original',
    })
    value = reader.authority.source_bytes(path, (fixed['mediaType'],), max_bytes=fixed['byteSize'])
    require(value['sha256'] == fixed['sourceSha256'] and len(value['content']) == fixed['byteSize'],
            'CONTENT_CHANGED', 409)
    return {**value, 'mediaType': 'application/octet-stream'}
