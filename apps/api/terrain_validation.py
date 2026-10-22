"""Private, bounded GeoTIFF-to-regional-mesh probe; no HTTP or scene writes.

Run with a separately provisioned rasterio/numpy worker runtime. The CLI applies
candidate process limits; the ordinary workbench does not import GIS libraries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
from uuid import uuid4

from .terrain_coordinates import ProjectedFrame, CoordinateError, SAMPLING_RULE, VERTICAL_DATUMS

MAX_BYTES = 256 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_GRID_SIDE = 501
MAX_TRIANGLES = 500_000
MAX_ABS_HEIGHT_M = 100_000
MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
PLACEMENT_SAMPLING_RULE = 'mesh-triangle-tr-bl-cell-mask-v2'
CELL_COVERAGE_RULE = 'source-validity-min-warp-one-pixel-buffer-v1'


class TerrainError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise TerrainError(code, message)


def _hash(path):
    result = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def _runtime():
    # These are also set before imports by the standalone CLI. A parent worker
    # must start a fresh process to enforce native-library thread/memory limits.
    for name in ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS'):
        os.environ[name] = '1'
    os.environ['PROJ_NETWORK'] = 'OFF'
    try:
        import numpy as np
        import rasterio
        from rasterio.windows import Window
        from rasterio.warp import transform
    except ImportError as error:
        raise TerrainError('PROCESSING_UNAVAILABLE', 'The validated GIS worker runtime is unavailable.') from error
    return np, rasterio, Window, transform


def _input(path):
    text = os.fspath(path)
    require(isinstance(text, str) and ':' not in text and not text.startswith('/vsi'),
            'INVALID_TERRAIN', 'Only a private local GeoTIFF file is accepted.')
    path = Path(text)
    require(not path.is_symlink(), 'INVALID_TERRAIN', 'Symlink inputs are not accepted.')
    try:
        info = path.stat()
    except OSError as error:
        raise TerrainError('INVALID_TERRAIN', 'The private input is unavailable.') from error
    require(stat.S_ISREG(info.st_mode), 'INVALID_TERRAIN', 'The input must be a regular file.')
    require(8 <= info.st_size <= MAX_BYTES, 'TERRAIN_LIMIT_EXCEEDED', 'The input file budget is exceeded.')
    with path.open('rb') as file:
        signature = file.read(4)
    require(signature in (b'II*\x00', b'MM\x00*', b'II+\x00', b'MM\x00+'),
            'INVALID_TERRAIN', 'Only TIFF bytes are accepted; external-reference formats are disabled.')
    return path.resolve(), info


def _vertical_declaration(dataset, declared):
    tags = {**dataset.tags(), **{'band:'+key:value for key,value in dataset.tags(1).items()}}
    found=[]
    def parse(value):
        require(isinstance(value,str) and len(value)<=2000, 'VERTICAL_DATUM_CONFLICT', 'The embedded vertical declaration is not supported.')
        normalized=''.join(c for c in value.upper() if c.isalnum())
        if 'EGM2008' in normalized or 'EPSG3855' in normalized: return 'EGM2008'
        if 'EGM96' in normalized or 'EPSG5773' in normalized: return 'EGM96'
        if 'WGS84ELLIPSOIDAL' in normalized or 'ELLIPSOIDALHEIGHT' in normalized: return 'WGS84_ELLIPSOIDAL'
        if normalized=='UNKNOWNRELATIVE': return 'UNKNOWN_RELATIVE'
        raise TerrainError('VERTICAL_DATUM_CONFLICT','An embedded vertical declaration is unrecognized and must not be overridden.')
    for key,value in tags.items():
        normalized=key.upper().removeprefix('BAND:')
        if normalized in ('VERTICAL_DATUM','VERTICAL_CRS','HEIGHT_DATUM','VERTICAL_REFERENCE'):
            found.append(parse(value))
    wkt=dataset.crs.to_wkt() if dataset.crs else ''
    if 'VERT_CS[' in wkt or 'VERTCRS[' in wkt:
        # Compound/vertical CRS inputs remain outside the first input subset,
        # but a conflicting declared datum must fail before horizontal parsing.
        start=max(wkt.find('VERT_CS['),wkt.find('VERTCRS['))
        found.append(parse(wkt[start:]))
    require(all(value==declared for value in found), 'VERTICAL_DATUM_CONFLICT', 'Embedded and operator vertical declarations conflict.')
    return {'embeddedVerticalDatums':sorted(set(found)),
            'verticalDeclarationSource':'embedded_and_operator' if found else 'operator_source_evidence'}


def _read_window(dataset, window, np):
    values = dataset.read(1, window=window, out_dtype='float64')
    valid = dataset.read_masks(1, window=window) != 0
    require(not np.any(valid & ~np.isfinite(values)), 'INVALID_TERRAIN', 'An unmasked elevation is non-finite.')
    values = values * float(dataset.scales[0]) + float(dataset.offsets[0])
    require(not np.any(valid & (~np.isfinite(values) | (np.abs(values) > MAX_ABS_HEIGHT_M))),
            'TERRAIN_LIMIT_EXCEEDED', 'An elevation exceeds the supported numeric range.')
    return values, valid


def _scan(dataset, np, Window):
    count = 0
    low, high = math.inf, -math.inf
    for row in range(0, dataset.height, 256):
        for column in range(0, dataset.width, 256):
            values, valid = _read_window(dataset, Window(column, row, min(256, dataset.width-column), min(256, dataset.height-row)), np)
            count += int(valid.sum())
            if valid.any():
                low = min(low, float(values[valid].min()))
                high = max(high, float(values[valid].max()))
    require(count > 0, 'NO_DATA', 'The raster contains no valid elevation.')
    return {'validPixels': count, 'missingPixels': dataset.width * dataset.height-count,
            'heightRangeM': [low, high]}


def _bounds(dataset, transform, aoi):
    affine = dataset.transform
    corners = [(affine.a*column+affine.c, affine.e*row+affine.f) for column,row in ((.5, .5), (dataset.width-.5, .5), (.5, dataset.height-.5), (dataset.width-.5, dataset.height-.5))]
    longitude, latitude = transform(dataset.crs, 'EPSG:4326', [p[0] for p in corners], [p[1] for p in corners])
    geographic = [min(longitude), min(latitude), max(longitude), max(latitude)]
    require(all(math.isfinite(x) for x in geographic), 'INVALID_TERRAIN', 'The geographic coverage is non-finite.')
    if aoi is not None:
        require(isinstance(aoi, (list, tuple)) and len(aoi) == 4 and all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in aoi),
                'INVALID_REQUEST', 'AOI must contain west, south, east and north.')
        west, south, east, north = map(float, aoi)
        require(-180 <= west < east <= 180 and -80 <= south < north <= 84, 'INVALID_REQUEST', 'The AOI is invalid or crosses the date line/polar boundary.')
        # The half-pixel outer rim has no four-centre interpolation domain.
        # Intersect only that rim; do not silently crop an unrelated AOI.
        outer = dataset.bounds
        outer_x, outer_y = transform(dataset.crs, 'EPSG:4326', [outer.left, outer.right], [outer.bottom, outer.top])
        require(min(outer_x)-1e-8 <= west and east <= max(outer_x)+1e-8 and min(outer_y)-1e-8 <= south and north <= max(outer_y)+1e-8,
                'OUTSIDE_COVERAGE', 'The AOI is outside the input coverage.')
        geographic = [max(west, geographic[0]), max(south, geographic[1]), min(east, geographic[2]), min(north, geographic[3])]
    require(geographic[0] < geographic[2] and geographic[1] < geographic[3], 'OUTSIDE_COVERAGE', 'The centre-to-centre sampling coverage is empty.')
    return geographic


def _cell_coverage(dataset, np, frame, e0, n1, step_e, step_n, rows, columns):
    """Conservatively keep holes that fall between downsampled mesh vertices."""
    from rasterio.enums import Resampling
    from rasterio.transform import Affine
    from rasterio.warp import reproject

    valid = dataset.read_masks(1) != 0
    # A missing source pixel also invalidates its bilinear support. The one-pixel
    # buffer is intentionally conservative around a reprojected hole boundary.
    padded = np.pad(valid, 1, mode='edge')
    supported = valid.copy()
    for dr in range(3):
        for dc in range(3):
            supported &= padded[dr:dr+dataset.height, dc:dc+dataset.width]
    source = supported.astype('uint8') * 255
    coverage = np.zeros((rows-1, columns-1), dtype='uint8')
    # Zero is a valid mask value, never nodata. Declaring dst_nodata=0 makes
    # GDAL reserve it and may rewrite a genuine minimum of zero to one.
    reproject(source, coverage, src_transform=dataset.transform, src_crs=dataset.crs,
              dst_transform=Affine(step_e, 0, e0, 0, -step_n, n1), dst_crs=frame.horizontal_crs,
              resampling=Resampling.min, src_nodata=None, dst_nodata=None,
              init_dest_nodata=False, num_threads=1, warp_mem_limit=16)
    return coverage == 255


def _triangles(np, cells, columns):
    rr, cc = np.nonzero(cells)
    top_left = rr*columns+cc
    triangles = np.empty((len(top_left)*2, 3), dtype='<u4')
    triangles[::2] = np.column_stack((top_left, top_left+columns, top_left+1))
    triangles[1::2] = np.column_stack((top_left+1, top_left+columns, top_left+columns+1))
    return triangles


def _grid(dataset, np, Window, transform, geographic, vertical_datum, fingerprint, side):
    west, south, east, north = geographic
    frame_key = hashlib.sha256(json.dumps([fingerprint,geographic,vertical_datum,side],separators=(',',':')).encode()).hexdigest()
    frame = ProjectedFrame((west+east)/2, (south+north)/2, 0, vertical_datum, 'terrain-frame:'+frame_key[:24])
    # Explicit AOI clipping is required before projecting a source tile larger
    # than the independently tested regional frame.
    points = [frame.project(lon, lat) for lon in (west, east) for lat in (south, north)]
    e0, e1 = min(p[0] for p in points), max(p[0] for p in points)
    n0, n1 = min(p[1] for p in points), max(p[1] for p in points)
    columns = min(side, dataset.width)
    rows = min(side, dataset.height)
    require(columns >= 2 and rows >= 2, 'INVALID_TERRAIN', 'A two-dimensional mesh is required.')
    eastings = np.linspace(e0, e1, columns)
    northings = np.linspace(n1, n0, rows)
    heights = np.full((rows, columns), np.nan, dtype='float64')
    mask = np.zeros((rows, columns), dtype='uint8')
    affine = dataset.transform
    epsilon = 1e-7
    for row, northern in enumerate(northings):
        lng, lat = transform(frame.horizontal_crs, 'EPSG:4326', eastings.tolist(), [float(northern)]*columns)
        sx, sy = transform('EPSG:4326', dataset.crs, lng, lat)
        xs, ys = np.asarray(sx), np.asarray(sy)
        pixel_x = (xs-affine.c)/affine.a-.5
        pixel_y = (ys-affine.f)/affine.e-.5
        eligible = ((np.asarray(lng) >= west-1e-10) & (np.asarray(lng) <= east+1e-10)
                    & (np.asarray(lat) >= south-1e-10) & (np.asarray(lat) <= north+1e-10)
                    & (pixel_x >= -epsilon) & (pixel_x <= dataset.width-1+epsilon)
                    & (pixel_y >= -epsilon) & (pixel_y <= dataset.height-1+epsilon))
        if not eligible.any():
            continue
        indices = np.flatnonzero(eligible)
        px = np.clip(pixel_x[indices], 0, dataset.width-1)
        py = np.clip(pixel_y[indices], 0, dataset.height-1)
        left = np.minimum(dataset.width-2, np.floor(px).astype('int64'))
        top = np.minimum(dataset.height-2, np.floor(py).astype('int64'))
        c0, r0 = int(left.min()), int(top.min())
        window = Window(c0, r0, int(left.max())-c0+2, int(top.max())-r0+2)
        values, valid = _read_window(dataset, window, np)
        c, r = left-c0, top-r0
        four_valid = valid[r, c] & valid[r, c+1] & valid[r+1, c] & valid[r+1, c+1]
        tx, ty = px-left, py-top
        interpolated = ((values[r,c]*(1-tx)+values[r,c+1]*tx)*(1-ty)
                        +(values[r+1,c]*(1-tx)+values[r+1,c+1]*tx)*ty)
        good = indices[four_valid]
        heights[row, good] = interpolated[four_valid]
        mask[row, good] = 1
    require(mask.any(), 'NO_DATA', 'The selected AOI has no usable mesh vertices.')
    step_e, step_n = float((e1-e0)/(columns-1)), float((n1-n0)/(rows-1))
    vertex_quads = mask[:-1,:-1] & mask[:-1,1:] & mask[1:,:-1] & mask[1:,1:]
    coverage = _cell_coverage(dataset, np, frame, e0, n1, step_e, step_n, rows, columns)
    cells = (vertex_quads & coverage).astype('uint8')
    triangles = _triangles(np, cells, columns)
    require(0 < len(triangles) <= MAX_TRIANGLES, 'NO_DATA' if not len(triangles) else 'TERRAIN_LIMIT_EXCEEDED', 'The mesh has no usable surface or exceeds the triangle budget.')
    xx, nn = np.meshgrid(eastings, northings)
    positions = np.empty((rows, columns, 3), dtype='<f4')
    positions[:,:,0] = xx-frame.origin_easting_m
    positions[:,:,1] = np.where(mask, heights-frame.origin_height_m, 0)
    positions[:,:,2] = -(nn-frame.origin_northing_m)
    contact_error = float(np.max(np.abs(positions[:,:,1][mask.astype(bool)].astype('float64')+frame.origin_height_m-heights[mask.astype(bool)])))
    require(contact_error <= .02, 'TERRAIN_LIMIT_EXCEEDED', 'The float32 display contact error exceeds the candidate budget.')
    metadata = {'rows':rows, 'columns':columns, 'eastingMinM':float(e0), 'northingMaxM':float(n1),
                'stepEastingM':step_e, 'stepNorthingM':step_n,
                'vertices':rows*columns, 'validVertices':int(mask.sum()), 'triangles':len(triangles),
                'validCells':int(cells.sum()), 'cellCoverageRule':CELL_COVERAGE_RULE,
                'sourceVertexSamplingRule':SAMPLING_RULE, 'placementSamplingRule':PLACEMENT_SAMPLING_RULE,
                'placementCoordinatePrecision':'fixed_display_float32_vertices',
                'displayContactMaxErrorM':contact_error, 'sourceSurfaceApproximationErrorM':None,
                'sourceSurfaceApproximationStatus':'not_measured_not_a_field_accuracy_claim',
                'heightExaggeration':1, 'frame':frame.record()}
    return metadata, heights.astype('<f8'), mask, cells, positions, triangles


def validate(path: Path, output_dir: Path, *, vertical_datum: str, source_note: str, license_note: str,
             height_unit: str = 'm', relative_reference_id: str | None = None,
             aoi: tuple[float,float,float,float] | None = None, grid_side: int = MAX_GRID_SIDE) -> dict:
    """Inspect all input pixels, then atomically write one bounded fixed mesh.

    No output directory is published on failure. All four source neighbours
    must be valid. Placement subsequently samples this fixed triangulated mesh,
    not a different-resolution source surface.
    """
    require(vertical_datum in VERTICAL_DATUMS, 'VERTICAL_DATUM_CONFLICT', 'An explicit supported vertical datum is required.')
    require(height_unit == 'm', 'UNSUPPORTED_TERRAIN', 'The first terrain slice accepts explicitly metre elevations only.')
    for note in (source_note, license_note):
        require(isinstance(note,str) and 0 < len(note.strip()) <= 2000 and not any(ord(c)<32 for c in note), 'INVALID_REQUEST', 'A bounded source and license declaration is required.')
    if vertical_datum == 'UNKNOWN_RELATIVE':
        require(isinstance(relative_reference_id,str) and 0 < len(relative_reference_id) <= 200, 'VERTICAL_DATUM_CONFLICT', 'Unknown relative height requires an explicit reference identity.')
    require(type(grid_side) is int and 2 <= grid_side <= MAX_GRID_SIDE, 'TERRAIN_LIMIT_EXCEEDED', 'The derived mesh size exceeds its budget.')
    path, initial = _input(path)
    output_dir = Path(output_dir)
    require(not output_dir.exists() and not output_dir.is_symlink() and output_dir.parent.is_dir(), 'OUTPUT_EXISTS', 'Use a new private output directory.')
    temporary = output_dir.parent / ('.terrain-'+uuid4().hex)
    fingerprint = _hash(path)
    np, rasterio, Window, transform = _runtime()
    options = {'GDAL_DISABLE_READDIR_ON_OPEN':'EMPTY_DIR', 'GDAL_PAM_ENABLED':'NO', 'GDAL_NUM_THREADS':'1',
               'GDAL_CACHEMAX':16*1024*1024, 'VSI_CACHE':False, 'PROJ_NETWORK':'OFF', 'GDAL_HTTP_MAX_RETRY':'0'}
    try:
        with rasterio.Env(**options):
            with rasterio.open(path, driver='GTiff') as dataset:
                require(dataset.driver == 'GTiff' and not dataset.subdatasets, 'UNSUPPORTED_TERRAIN', 'Only one embedded GTiff raster is supported.')
                require(len(dataset.files) == 1 and Path(dataset.files[0]).resolve() == path, 'UNSUPPORTED_TERRAIN', 'External sidecars or references are not accepted.')
                require(dataset.count == 1, 'UNSUPPORTED_TERRAIN', 'A single elevation band is required.')
                require(2 <= dataset.width and 2 <= dataset.height and dataset.width*dataset.height <= MAX_PIXELS, 'TERRAIN_LIMIT_EXCEEDED', 'The decoded pixel budget is exceeded.')
                require(dataset.dtypes[0] in ('uint8','int8','uint16','int16','uint32','int32','uint64','int64','float32','float64'), 'UNSUPPORTED_TERRAIN', 'Complex or unsupported samples are disabled.')
                require(dataset.crs is not None, 'CRS_REQUIRED', 'The raster has no embedded horizontal CRS.')
                vertical_record = _vertical_declaration(dataset,vertical_datum)
                epsg = dataset.crs.to_epsg()
                require(epsg == 4326 or epsg is not None and (32601 <= epsg <= 32660 or 32701 <= epsg <= 32760), 'UNSUPPORTED_CRS', 'The first slice supports WGS84 geographic or WGS84 UTM rasters.')
                affine = dataset.transform
                require(all(math.isfinite(v) for v in tuple(affine)[:6]) and affine.a > 0 and affine.e < 0 and affine.b == 0 and affine.d == 0,
                        'UNSUPPORTED_TERRAIN', 'A finite north-up, unrotated affine transform is required.')
                require(not dataset.gcps[0], 'UNSUPPORTED_TERRAIN', 'GCP/geolocation rasters require a separate verified path.')
                require(all(math.isfinite(float(x)) for x in (*dataset.scales,*dataset.offsets)), 'INVALID_TERRAIN', 'Scale and offset must be finite.')
                require(dataset.units[0] in (None,'m','metre','meter','metres','meters'), 'UNSUPPORTED_TERRAIN', 'Embedded elevation units conflict with metre declaration.')
                stats = _scan(dataset, np, Window)
                coverage = _bounds(dataset, transform, aoi)
                mesh, heights, mask, cells, positions, triangles = _grid(dataset,np,Window,transform,coverage,vertical_datum,fingerprint,grid_side)
                source = {'sha256':fingerprint,'bytes':initial.st_size,'width':dataset.width,'height':dataset.height,
                          'bands':1,'dtype':dataset.dtypes[0],'horizontalCrs':dataset.crs.to_string(),
                          'horizontalCrsWkt':dataset.crs.to_wkt(),'pixelCornerAffine':list(tuple(affine)[:6]),
                          'areaOrPoint':dataset.tags().get('AREA_OR_POINT','Area'), 'heightUnit':'m',
                          'scale':float(dataset.scales[0]),'offset':float(dataset.offsets[0]),
                          'verticalDatum':vertical_datum, **vertical_record,
                          'relativeReferenceId':relative_reference_id if vertical_datum=='UNKNOWN_RELATIVE' else None,
                          'sourceNote':source_note,'licenseNote':license_note,'samplingCentreCoverageWgs84':coverage,
                          'requestedAoiWgs84':list(aoi) if aoi is not None else None, **stats}
        after = path.stat()
        require((initial.st_dev,initial.st_ino,initial.st_size,initial.st_mtime_ns) == (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)
                and fingerprint == _hash(path), 'RESOURCE_CHANGED', 'The source changed during validation.')
        temporary.mkdir(mode=0o700)
        artifacts=[]
        for name, array, kind in (('heights.f64',heights,'float64_le'),('mask.u8',mask,'uint8'),('cells.u8',cells,'uint8'),
                                  ('positions.f32',positions,'float32_le'),('triangles.u32',triangles,'uint32_le')):
            target=temporary/name
            raw=array.tobytes(order='C')
            require(len(raw) <= MAX_ARTIFACT_BYTES, 'TERRAIN_LIMIT_EXCEEDED', 'The derived artifact budget is exceeded.')
            with target.open('xb') as file:
                file.write(raw); file.flush(); os.fsync(file.fileno())
            os.chmod(target,0o600)
            artifacts.append({'artifactId':name,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'format':kind})
        report={'schemaVersion':1,'state':'ready','source':source,'mesh':mesh,'artifacts':artifacts,
                'externalResourcesFetched':0,'verticalConversionApplied':False,'fieldAccuracyVerified':False,
                'limits':{'maxBytes':MAX_BYTES,'maxPixels':MAX_PIXELS,'maxTriangles':MAX_TRIANGLES,'maxGridSide':MAX_GRID_SIDE}}
        report_file=temporary/'report.json'
        with report_file.open('x') as file:
            json.dump(report,file,ensure_ascii=False,allow_nan=False,separators=(',',':')); file.flush(); os.fsync(file.fileno())
        os.chmod(report_file,0o600)
        os.replace(temporary,output_dir)
        return report
    except CoordinateError as error:
        raise TerrainError(error.code,str(error)) from error
    except TerrainError:
        raise
    except (OSError,ValueError,RuntimeError,MemoryError) as error:
        raise TerrainError('INVALID_TERRAIN','The GeoTIFF could not be processed within the supported subset.') from error
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def sample_mesh(output_dir: Path, easting_m: float, northing_m: float, *, expected_report_sha256: str | None = None) -> float:
    """Sample the displayed diagonal and reject omitted cells or changed artifacts.

    The resource library must supply its trusted report digest. Without it this
    standalone helper checks internal consistency, not the report's provenance.
    """
    np, *_ = _runtime()
    try:
        root=Path(output_dir)
        require(not root.is_symlink(), 'INVALID_TERRAIN', 'A private mesh directory is required.')
        report_file=root/'report.json'
        require(not report_file.is_symlink() and report_file.stat().st_size <= 65536, 'INVALID_TERRAIN', 'The fixed report is invalid.')
        if expected_report_sha256 is not None:
            require(isinstance(expected_report_sha256,str) and len(expected_report_sha256)==64
                    and all(c in '0123456789abcdef' for c in expected_report_sha256), 'INVALID_REQUEST', 'A trusted report SHA256 is required.')
            require(_hash(report_file)==expected_report_sha256, 'RESOURCE_CHANGED', 'The fixed mesh report changed.')
        report=json.loads(report_file.read_text())
        require(report.get('state')=='ready' and report.get('schemaVersion')==1, 'INVALID_TERRAIN', 'A ready fixed mesh is required.')
        grid=report['mesh']; rows,columns=grid['rows'],grid['columns']
        for key in ('eastingMinM','northingMaxM','stepEastingM','stepNorthingM'):
            require(isinstance(grid[key],(int,float)) and not isinstance(grid[key],bool) and math.isfinite(grid[key]), 'INVALID_TERRAIN', 'The fixed mesh coordinate metadata is invalid.')
        require(grid['stepEastingM']>0 and grid['stepNorthingM']>0, 'INVALID_TERRAIN', 'The fixed mesh spacing must be positive.')
        for key in ('originEasting','originNorthing','originHeight'):
            require(isinstance(grid['frame'][key],(int,float)) and not isinstance(grid['frame'][key],bool) and math.isfinite(grid['frame'][key]), 'INVALID_TERRAIN', 'The fixed mesh origin is invalid.')
        require(type(rows) is int and type(columns) is int and 2<=rows<=MAX_GRID_SIDE and 2<=columns<=MAX_GRID_SIDE, 'INVALID_TERRAIN', 'The mesh dimensions are invalid.')
        entries=report['artifacts']
        names=('heights.f64','mask.u8','cells.u8','positions.f32','triangles.u32')
        require(type(entries) is list and len(entries)==len(names) and all(type(item) is dict for item in entries),
                'INVALID_TERRAIN', 'The fixed artifact manifest is invalid.')
        artifacts={item['artifactId']:item for item in entries}
        require(set(artifacts)==set(names), 'INVALID_TERRAIN', 'The fixed artifact manifest is invalid.')
        triangle_count=grid['triangles']
        require(type(triangle_count) is int and 0<triangle_count<=MAX_TRIANGLES and triangle_count%2==0,
                'INVALID_TERRAIN', 'The fixed triangle count is invalid.')
        arrays={}
        for name,dtype,size in (('heights.f64','<f8',rows*columns*8),('mask.u8','uint8',rows*columns),
                               ('cells.u8','uint8',(rows-1)*(columns-1)),('positions.f32','<f4',rows*columns*3*4),
                               ('triangles.u32','<u4',triangle_count*3*4)):
            target=root/name
            require(not target.is_symlink() and target.stat().st_size==size and artifacts[name]['bytes']==size and _hash(target)==artifacts[name]['sha256'], 'RESOURCE_CHANGED', 'The fixed mesh artifact changed.')
            shape=(rows,columns,3) if name=='positions.f32' else (rows-1,columns-1) if name=='cells.u8' else (triangle_count,3) if name=='triangles.u32' else (rows,columns)
            arrays[name]=np.fromfile(target,dtype=dtype).reshape(shape)
        require(all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in (easting_m,northing_m)), 'INVALID_COORDINATE', 'The sample coordinate is non-finite.')
        positions=arrays['positions.f32']; frame=grid['frame']
        mask,cells=arrays['mask.u8'],arrays['cells.u8']
        require(bool(np.isin(mask,(0,1)).all()) and bool(np.isin(cells,(0,1)).all()), 'INVALID_TERRAIN', 'The fixed validity masks are invalid.')
        vertex_quads=mask[:-1,:-1] & mask[:-1,1:] & mask[1:,:-1] & mask[1:,1:]
        require(not bool((cells & ~vertex_quads).any()), 'INVALID_TERRAIN', 'A displayed cell contains a missing vertex.')
        expected_triangles=_triangles(np,cells,columns)
        require(len(expected_triangles)==triangle_count and np.array_equal(arrays['triangles.u32'],expected_triangles),
                'INVALID_TERRAIN', 'The triangles do not match the fixed cell mask and diagonal.')
        valid=mask.astype(bool); heights=arrays['heights.f64']
        require(bool(np.isfinite(heights[valid]).all()) and bool(np.isfinite(positions).all())
                and np.array_equal(positions[:,:,1][valid],(heights[valid]-frame['originHeight']).astype('<f4')),
                'INVALID_TERRAIN', 'The display heights and fixed elevation/origin disagree.')
        xs=positions[0,:,0].astype('float64'); zs=positions[:,0,2].astype('float64')
        require(bool((np.diff(xs)>0).all()) and bool((np.diff(zs)>0).all()), 'INVALID_TERRAIN', 'The displayed mesh axes are not monotone.')
        expected_x=grid['eastingMinM']-frame['originEasting']+np.arange(columns)*grid['stepEastingM']
        expected_z=frame['originNorthing']-grid['northingMaxM']+np.arange(rows)*grid['stepNorthingM']
        tolerance=max(1e-5,float(max(np.abs(expected_x).max(),np.abs(expected_z).max()))*np.finfo('float32').eps*2)
        require(bool(np.allclose(positions[:,:,0],expected_x[None,:],rtol=0,atol=tolerance))
                and bool(np.allclose(positions[:,:,2],expected_z[:,None],rtol=0,atol=tolerance)),
                'INVALID_TERRAIN', 'The displayed coordinates and fixed spacing/origin disagree.')
        x=easting_m-frame['originEasting']; z=frame['originNorthing']-northing_m
        require(xs[0]-1e-7<=x<=xs[-1]+1e-7 and zs[0]-1e-7<=z<=zs[-1]+1e-7, 'OUTSIDE_COVERAGE', 'The point is outside the fixed displayed mesh.')
        x,z=float(np.clip(x,xs[0],xs[-1])),float(np.clip(z,zs[0],zs[-1]))
        # Sample the very same float32 XY/Y vertices sent to the renderer.
        # Using ideal float64 grid coordinates on steep cells would otherwise
        # turn horizontal rounding into an unreported contact-height error.
        column=min(columns-2,max(0,int(np.searchsorted(xs,x+1e-8,side='right'))-1))
        row=min(rows-2,max(0,int(np.searchsorted(zs,z+1e-8,side='right'))-1))
        tx=(x-xs[column])/(xs[column+1]-xs[column]); ty=(z-zs[row])/(zs[row+1]-zs[row])
        tx,ty=min(1.,max(0.,tx)),min(1.,max(0.,ty))
        require(bool(cells[row,column]), 'NO_DATA', 'The displayed quad is omitted because its source coverage is missing.')
        a,b,c,d=(float(v)+frame['originHeight'] for v in (positions[row,column,1],positions[row,column+1,1],positions[row+1,column,1],positions[row+1,column+1,1]))
        value=a+tx*(b-a)+ty*(c-a) if tx+ty<=1 else d+(1-tx)*(c-d)+(1-ty)*(b-d)
        require(math.isfinite(value), 'INVALID_TERRAIN', 'The fixed mesh height is non-finite.')
        return float(value)
    except TerrainError:
        raise
    except (OSError,ValueError,KeyError,TypeError,OverflowError) as error:
        raise TerrainError('INVALID_TERRAIN','The fixed mesh cannot be sampled.') from error


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input',type=Path); parser.add_argument('output',type=Path)
    parser.add_argument('--vertical-datum',required=True,choices=sorted(VERTICAL_DATUMS))
    parser.add_argument('--source',required=True); parser.add_argument('--license',required=True,dest='license_note')
    parser.add_argument('--height-unit',required=True,choices=['m'])
    parser.add_argument('--relative-reference-id')
    parser.add_argument('--aoi',nargs=4,type=float,metavar=('WEST','SOUTH','EAST','NORTH'))
    args=parser.parse_args(argv)
    import resource
    import signal
    resource.setrlimit(resource.RLIMIT_CPU,(30,30))
    if sys.platform.startswith('linux'):
        resource.setrlimit(resource.RLIMIT_AS,(512*1024*1024,512*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE,(64*1024*1024,64*1024*1024))
    def timeout(_signal,_frame):
        raise TerrainError('TERRAIN_LIMIT_EXCEEDED','The wall clock budget expired.')
    signal.signal(signal.SIGALRM,timeout); signal.alarm(60)
    try:
        result=validate(args.input,args.output,vertical_datum=args.vertical_datum,source_note=args.source,
                        license_note=args.license_note,height_unit=args.height_unit,relative_reference_id=args.relative_reference_id,
                        aoi=tuple(args.aoi) if args.aoi else None)
        result['processLimits']={'cpuSeconds':30,'wallSeconds':60,'addressSpaceBytes':512*1024*1024 if sys.platform.startswith('linux') else None,
                                 'addressSpaceEnforced':sys.platform.startswith('linux')}
        print(json.dumps(result,ensure_ascii=False,allow_nan=False))
        return 0
    except (TerrainError,MemoryError) as error:
        print(json.dumps({'code':getattr(error,'code','TERRAIN_LIMIT_EXCEEDED')}))
        return 2
    finally:
        signal.alarm(0)


if __name__=='__main__':
    sys.exit(main())
