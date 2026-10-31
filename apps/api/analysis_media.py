"""Small display derivatives; source bytes and oriented coordinates stay intact."""
from collections import OrderedDict
from io import BytesIO
import hashlib
import threading

from .authority import PreviewError

_cache = OrderedDict()
_lock = threading.Lock()
_render = threading.Semaphore(1)
MAX_CACHE = 32 * 1024 * 1024


def derived(key, generate):
    with _lock:
        if key in _cache:
            _cache.move_to_end(key); return _cache[key]
    with _render:
        with _lock:
            if key in _cache:
                _cache.move_to_end(key); return _cache[key]
        raw, mime = generate()
        value = {'content': raw, 'mediaType': mime, 'sha256': hashlib.sha256(raw).hexdigest()}
        with _lock:
            _cache[key] = value
            while len(_cache) > 12 or sum(len(v['content']) for v in _cache.values()) > MAX_CACHE:
                _cache.popitem(last=False)
        return value


def photo_preview(reader, descriptor):
    if descriptor.get('sourceType')=='project_document':
        from .fixed_documents import FixedDocuments
        value=FixedDocuments(reader.reader).content({key:descriptor[key] for key in ('documentId','contentVersionId','sourceSha256')}|{'representation':'preview'})
        reader.authorize();return value
    # Revalidate the actual association before accessing shared, content-keyed bytes.
    reader.read('photo', descriptor)
    key = ('photo-4096-jpeg-82', descriptor['expectedDisplayRevision'])
    def generate():
        return photo_image(reader.content('photo', descriptor))
    return derived(key, generate)


def photo_image(source):
    from PIL import Image, ImageOps
    try:
        with Image.open(BytesIO(source['content'])) as image:
            if image.width * image.height > 90_000_000:raise PreviewError(413,'CONTENT_SIZE_LIMIT')
            output=BytesIO();display=ImageOps.exif_transpose(image).convert('RGB')
            display.thumbnail((4096,4096),Image.Resampling.LANCZOS)
            display.save(output,'JPEG',quality=82,optimize=True,progressive=True)
            return output.getvalue(),'image/jpeg'
    except (OSError,ValueError):raise PreviewError(502,'SOURCE_UNAVAILABLE') from None


def drawing_image(source):
    def generate():
        import fitz
        try:
            with fitz.open(stream=source['content'], filetype='pdf') as pdf:
                if len(pdf) != 1 or pdf.needs_pass: raise PreviewError(422, 'SINGLE_PAGE_REQUIRED')
                page = pdf[0]; scale = min(3, 4096 / max(page.rect.width, page.rect.height))
                return page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes('png'), 'image/png'
        except (RuntimeError, ValueError): raise PreviewError(502, 'SOURCE_UNAVAILABLE') from None
    return derived(('drawing', source['sha256']), generate)
