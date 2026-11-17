"""Photo and drawing display derivatives with bounded rendering and caching."""
from collections import OrderedDict
from io import BytesIO
import hashlib
import threading
from time import perf_counter

from .authority import PreviewError

_cache = OrderedDict()
_lock = threading.Lock()
_render = threading.Semaphore(1)
MAX_CACHE = 32 * 1024 * 1024
PHOTO_LIMIT = 4_000_000
PHOTO_PIXEL_LIMIT = 90_000_000
FULL_PHOTO_REPRESENTATIONS = ('full_resolution', 'full_resolution_avif')


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
            if image.width * image.height > PHOTO_PIXEL_LIMIT:raise PreviewError(413,'CONTENT_SIZE_LIMIT')
            output=BytesIO();display=ImageOps.exif_transpose(image).convert('RGB')
            display.thumbnail((4096,4096),Image.Resampling.LANCZOS)
            display.save(output,'JPEG',quality=82,optimize=True,progressive=True)
            return output.getvalue(),'image/jpeg'
    except (OSError,ValueError):raise PreviewError(502,'SOURCE_UNAVAILABLE') from None


def full_resolution_photo(source, projection=None, *, prefer_avif=False):
    """Return display bytes at the fixed pixel dimensions, with a separate digest."""
    value = source
    encode_ms = None
    if projection is None and len(source['content']) >= PHOTO_LIMIT:
        key = ('full-resolution-avif-v1' if prefer_avif else 'full-resolution-photo-v1', source['sha256'])
        encode_ms = 0.0

        def generate():
            nonlocal encode_ms
            start = perf_counter()
            result = encode_full_resolution(source, prefer_avif=prefer_avif)
            encode_ms = round((perf_counter() - start) * 1000, 2)
            return result

        value = derived(key, generate)
    return {**value, 'fixedPhotoSha256': source['sha256'], 'photoEncodeMs': encode_ms}


def encode_full_resolution(source, *, prefer_avif=False):
    from PIL import Image, features

    try:
        with Image.open(BytesIO(source['content'])) as image:
            xmp = image.info.get('xmp') or image.info.get('XML:com.adobe.xmp') or b''
            if isinstance(xmp, str):
                xmp = xmp.encode()
            if b'ns.google.com/photos/1.0/panorama/' in xmp:
                return source['content'], source['mediaType']
            if image.width * image.height > PHOTO_PIXEL_LIMIT or getattr(image, 'n_frames', 1) != 1:
                raise PreviewError(413, 'PHOTO_FULL_RESOLUTION_LIMIT')

            transparent = 'A' in image.getbands() or 'transparency' in image.info
            mode = 'RGBA' if transparent else 'L' if image.mode == 'L' else 'RGB'
            options = {}
            orientation = image.getexif().get(274)
            if orientation in range(2, 9):
                exif = Image.Exif()
                exif[274] = orientation
                options['exif'] = exif.tobytes()
            profile = image.info.get('icc_profile')
            if profile and image.mode in ('L', 'RGB', 'RGBA', 'P'):
                options['icc_profile'] = profile
            if transparent:
                format_name, mime = 'WEBP', 'image/webp'
                options.update(method=4, alpha_quality=100)
            else:
                format_name, mime = 'JPEG', 'image/jpeg'
                options.update(optimize=True, progressive=True)
            pixels = image if image.mode == mode else image.convert(mode)
            # The compatibility path preserves browser-managed EXIF orientation and alpha.
            if prefer_avif and not transparent and orientation in (None, 1) and features.check('avif'):
                avif = BytesIO()
                try:
                    pixels.save(avif, 'AVIF', quality=54, speed=9, max_threads=4,
                                icc_profile=options.get('icc_profile'))
                    if 0 < avif.tell() < PHOTO_LIMIT:
                        return avif.getvalue(), 'image/avif'
                except (OSError, ValueError):
                    pass
            for quality in (86, 78, 70, 62, 54, 46, 38, 30, 22, 14, 8, 4, 1):
                output = BytesIO()
                pixels.save(output, format_name, quality=quality, **options)
                if output.tell() < PHOTO_LIMIT:
                    return output.getvalue(), mime
    except (OSError, ValueError, Image.DecompressionBombError):
        raise PreviewError(502, 'SOURCE_UNAVAILABLE') from None
    raise PreviewError(413, 'PHOTO_FULL_RESOLUTION_LIMIT')


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
