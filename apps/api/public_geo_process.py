"""Bounded GIS subprocess for fixed public overview COGs, never arbitrary URLs."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import signal
import sys

from .authority import PreviewError
from .public_geo_sources import asset_url, catalog, imagery_group


def emit(value):
    print(json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True)


def fetch(request, directory, *, source_catalog=catalog, source_url=asset_url):
    import numpy as np
    import rasterio
    from rasterio.enums import ColorInterp, Resampling
    from rasterio.transform import from_origin
    from rasterio.vrt import WarpedVRT
    from rasterio.warp import transform

    longitude, latitude = request['longitude'], request['latitude']
    radius = request['radiusKm'] * 1000
    zone = min(60, int((longitude+180)//6)+1)
    crs = f'EPSG:{32600+zone if latitude >= 0 else 32700+zone}'
    xs, ys = transform('EPSG:4326', crs, [longitude], [latitude])
    easting, northing = xs[0], ys[0]
    results = {}
    env = {'GDAL_DISABLE_READDIR_ON_OPEN': 'EMPTY_DIR', 'CPL_VSIL_CURL_ALLOWED_EXTENSIONS': '.tif',
           'GDAL_HTTP_TIMEOUT': '15', 'GDAL_HTTP_CONNECTTIMEOUT': '5', 'GDAL_HTTP_MAX_RETRY': '0',
           'CPL_VSIL_CURL_CACHE_SIZE': 16*1024*1024, 'GDAL_CACHEMAX': 32*1024*1024,
           'PROJ_NETWORK': 'OFF', 'GDAL_HTTP_NETRC': 'NO'}
    for kind, resolution in [('terrain', 30), ('imagery', 20)]:
        if not request[kind]: continue
        emit({'stage': 'terrain_source' if kind == 'terrain' else 'imagery_source'})
        items = source_catalog('cop-dem-glo-30' if kind == 'terrain' else 'sentinel-2-c1-l2a', request['bbox'])
        day = None
        if kind == 'imagery': day, items = imagery_group(items, request['bbox'])
        if len(items) > (9 if kind == 'terrain' else 4): raise PreviewError(413, 'PUBLIC_LIMIT_EXCEEDED')
        # The one-pixel border encloses the requested circle; no interpolation
        # claims are made for the masked rim of the final terrain mesh.
        left = math.floor((easting-radius)/resolution)*resolution-resolution
        top = math.ceil((northing+radius)/resolution)*resolution+resolution
        side = math.ceil((2*radius)/resolution)+4
        affine = from_origin(left, top, resolution, resolution)
        rows, cols = np.indices((side, side))
        circle = (left+(cols+.5)*resolution-easting)**2 + (top-(rows+.5)*resolution-northing)**2 <= radius**2
        seen = np.zeros((side, side), dtype=bool)
        data = np.full((1 if kind == 'terrain' else 4, side, side), -9999 if kind == 'terrain' else 0,
                       dtype='float32' if kind == 'terrain' else 'uint8')
        records = []
        with rasterio.Env(**env):
            for item in items:
                emit({'stage': 'terrain_read' if kind == 'terrain' else 'imagery_read'})
                url = source_url(item, 'data' if kind == 'terrain' else 'visual')
                with rasterio.open(url, driver='GTiff') as source:
                    native_resolution = list(source.res)
                    if kind == 'terrain':
                        if source.count != 1 or source.crs.to_epsg() != 4326: raise PreviewError(502, 'PUBLIC_SOURCE_UNAVAILABLE')
                    elif (source.count != 3 or source.dtypes[:3] != ('uint8', 'uint8', 'uint8')
                          or source.crs is None or source.crs.to_epsg() is None
                          or not (32601 <= source.crs.to_epsg() <= 32660 or 32701 <= source.crs.to_epsg() <= 32760)
                          or any(abs(size-10) > 1e-6 for size in source.res)):
                        raise PreviewError(502, 'PUBLIC_SOURCE_UNAVAILABLE')
                    options = {'crs': crs, 'transform': affine, 'width': side, 'height': side,
                               'resampling': Resampling.bilinear if kind == 'terrain' else Resampling.average}
                    with WarpedVRT(source, **options, nodata=-9999 if kind == 'terrain' else 0) as view:
                        values = view.read(1 if kind == 'terrain' else [1, 2, 3])
                        valid = (view.read_masks(1) > 0) & circle & ~seen
                    if kind == 'imagery':
                        scl_url = source_url(item, 'scl')
                        with rasterio.open(scl_url, driver='GTiff') as classes:
                            if (classes.count != 1 or classes.dtypes != ('uint8',) or classes.crs != source.crs
                                    or any(abs(size-20) > 1e-6 for size in classes.res)):
                                raise PreviewError(502, 'PUBLIC_SOURCE_UNAVAILABLE')
                            with WarpedVRT(classes, **{**options, 'resampling': Resampling.nearest}, nodata=0) as quality:
                                valid &= ~np.isin(quality.read(1), [0, 1, 3, 7, 8, 9, 10, 11])
                        data[:3, valid] = values[:, valid]
                        data[3, valid] = 255
                    else: data[0, valid] = values[valid]
                    seen |= valid
                    records.append({'itemId': item['id'], 'url': url, 'nativeResolution': native_resolution,
                                    **({'sclUrl': scl_url, 'sceneCloudPercent': item['properties']['eo:cloud_cover']} if kind == 'imagery' else {})})
        count = int(seen.sum())
        if not count: raise PreviewError(422, 'PUBLIC_COVERAGE_UNAVAILABLE')
        path = directory / f'{kind}.tif'
        with rasterio.open(path, 'w', driver='GTiff', width=side, height=side, count=data.shape[0], dtype=str(data.dtype),
                           crs=crs, transform=affine, nodata=-9999 if kind == 'terrain' else None,
                           compress='deflate', tiled=True, blockxsize=256, blockysize=256) as target:
            target.write(data)
            if kind == 'terrain': target.update_tags(VERTICAL_DATUM='EGM2008')
            else: target.colorinterp = (ColorInterp.red, ColorInterp.green, ColorInterp.blue, ColorInterp.alpha)
            target.update_tags(SOURCE_ITEMS=json.dumps([record['itemId'] for record in records]),
                               SOURCE_URLS=json.dumps([record['url'] for record in records]),
                               PURPOSE='Public regional overview, not engineering positioning',
                               CENTER_WGS84=json.dumps([longitude, latitude]), RADIUS_KM=str(request['radiusKm']))
        os.chmod(path, 0o600)
        if path.stat().st_size > 32*1024*1024: raise PreviewError(413, 'PUBLIC_LIMIT_EXCEEDED')
        results[kind] = {'records': records, 'resolutionMeters': resolution, 'nativeResolutionMeters': 30 if kind == 'terrain' else 10,
                         'validFractionOfCircle': count/max(1, int(circle.sum())), 'crs': crs, 'acquiredAt': day,
                         'resampling': 'bilinear to 30 m UTM' if kind == 'terrain' else 'average RGB to 20 m; nearest 20 m SCL conservative mask',
                         'grid': [side, side]}
    return results


def main():
    if len(sys.argv) != 2: return 2
    directory = Path(sys.argv[1])
    if not directory.is_absolute() or not directory.is_dir() or directory.is_symlink(): return 2
    def expired(*_): raise PreviewError(413, 'PUBLIC_LIMIT_EXCEEDED')
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(240)
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CPU, (90, 95))
        if sys.platform.startswith('linux'): resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024, 512*1024*1024))
        resource.setrlimit(resource.RLIMIT_FSIZE, (40*1024*1024, 40*1024*1024))
        resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
        request = json.loads((directory/'request.json').read_text())
        result = fetch(request, directory)
        emit({'result': result})
        return 0
    except PreviewError as error:
        emit({'code': error.code}); return 2
    except MemoryError:
        emit({'code': 'PUBLIC_LIMIT_EXCEEDED'}); return 2
    except (ImportError, OSError, ValueError, TypeError, KeyError, RuntimeError, OverflowError, RecursionError):
        emit({'code': 'PUBLIC_SOURCE_UNAVAILABLE'}); return 2
    finally: signal.alarm(0)


if __name__ == '__main__':
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    os.environ['PROJ_NETWORK'] = 'OFF'
    os.environ['GDAL_HTTP_NETRC'] = 'NO'
    os.environ['GDAL_CONFIG_FILE'] = os.devnull
    raise SystemExit(main())
