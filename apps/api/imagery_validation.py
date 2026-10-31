"""Bounded local RGB(A) GeoTIFF probe. Imagery supplies colour, never height."""
from __future__ import annotations

import json
import math
from pathlib import Path
import sys

MAX_BYTES = 64 * 1024 * 1024
MAX_SIDE = 4096


class ImageryError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(value, code='UNSUPPORTED_IMAGERY'):
    if not value:
        raise ImageryError(code)


def validate(source, output):
    import numpy as np
    import rasterio
    from rasterio.enums import ColorInterp
    from rasterio.warp import transform_bounds

    source, output = Path(source), Path(output)
    require(source.is_file() and not source.is_symlink() and 8 <= source.stat().st_size <= MAX_BYTES, 'IMAGERY_LIMIT_EXCEEDED')
    with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_PAM_ENABLED='NO', PROJ_NETWORK='OFF', GDAL_CACHEMAX=32*1024*1024):
        with rasterio.open(source, driver='GTiff') as dataset:
            require(dataset.driver == 'GTiff' and not dataset.subdatasets and dataset.count in (3, 4))
            require(1 <= dataset.width <= MAX_SIDE and 1 <= dataset.height <= MAX_SIDE, 'IMAGERY_LIMIT_EXCEEDED')
            require(set(dataset.dtypes) == {'uint8'} and dataset.scales == (1.0,) * dataset.count and dataset.offsets == (0.0,) * dataset.count)
            expected = (ColorInterp.red, ColorInterp.green, ColorInterp.blue) + ((ColorInterp.alpha,) if dataset.count == 4 else ())
            require(dataset.colorinterp == expected)
            epsg = dataset.crs.to_epsg() if dataset.crs else None
            require(epsg == 4326 or epsg is not None and (32601 <= epsg <= 32660 or 32701 <= epsg <= 32760))
            affine = dataset.transform
            require(all(math.isfinite(x) for x in tuple(affine)) and affine.a > 0 and affine.e < 0 and affine.b == affine.d == 0)
            bounds = list(transform_bounds(dataset.crs, 'EPSG:4326', *dataset.bounds, densify_pts=21))
            require(all(math.isfinite(x) for x in bounds) and -180 <= bounds[0] < bounds[2] <= 180 and -80 <= bounds[1] < bounds[3] <= 84)
            pixels = np.empty((4, dataset.height, dataset.width), dtype='uint8')
            pixels[:3] = dataset.read((1, 2, 3))
            mask = dataset.dataset_mask()
            pixels[3] = np.minimum(dataset.read(4), mask) if dataset.count == 4 else mask
            valid = int(np.count_nonzero(pixels[3]))
            require(valid > 0, 'IMAGERY_NO_VALID_PIXELS')
            pixels[:3, pixels[3] == 0] = 0
            report = {'schemaVersion': 1, 'purpose': 'overview', 'width': dataset.width, 'height': dataset.height,
                      'bands': dataset.count, 'dtype': 'uint8', 'horizontalCrs': f'EPSG:{epsg}',
                      'pixelCornerAffine': [affine.a, affine.b, affine.c, affine.d, affine.e, affine.f],
                      'pixelSize': [affine.a, -affine.e], 'coverageWgs84': bounds,
                      'validPixels': valid, 'transparentPixels': dataset.width * dataset.height - valid,
                      'fieldAccuracyVerified': False, 'externalResourcesFetched': 0, 'heightDataUsed': False}
        with rasterio.open(output, 'w', driver='PNG', width=report['width'], height=report['height'], count=4, dtype='uint8') as target:
            target.write(pixels)
    require(output.is_file() and output.stat().st_size <= MAX_BYTES, 'IMAGERY_LIMIT_EXCEEDED')
    return report


def main():
    import resource
    import signal
    resource.setrlimit(resource.RLIMIT_CPU, (30, 30))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_BYTES, MAX_BYTES))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    signal.alarm(45)
    try:
        print(json.dumps(validate(sys.argv[1], sys.argv[2]), allow_nan=False))
        return 0
    except (ImageryError, MemoryError) as error:
        print(json.dumps({'code': getattr(error, 'code', 'IMAGERY_LIMIT_EXCEEDED')}))
        return 2
    except Exception:
        print(json.dumps({'code': 'UNSUPPORTED_IMAGERY'}))
        return 2
    finally:
        signal.alarm(0)


if __name__ == '__main__':
    sys.exit(main())
