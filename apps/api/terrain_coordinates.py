"""Bounded regional projection, pixel-centre sampling and anchor previews.

The display frame is a WGS84 UTM projection in metres, not a strict ENU frame.
No function changes an engineering record, downloads a grid, or writes a scene.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from numbers import Real
import os
from typing import Callable, Mapping, Sequence

MAX_SITE_RADIUS_M = 50_000.0
MAX_ABS_HEIGHT_M = 100_000.0
SAMPLING_RULE = 'pixel-centres-four-valid-clamped-centres-v1'
CONVERGENCE_RULE = 'projected-central-true-north-derivative-v1'
VERTICAL_DATUMS = frozenset(('EGM2008', 'EGM96', 'WGS84_ELLIPSOIDAL', 'UNKNOWN_RELATIVE'))


class CoordinateError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require(condition: bool, code: str, message: str) -> None:
    if not condition:
        raise CoordinateError(code, message)


def _number(value: object, name: str, limit: float = 1e9) -> float:
    _require(isinstance(value, Real) and not isinstance(value, bool), 'INVALID_COORDINATE', f'{name} must be a finite number.')
    result = float(value)
    _require(math.isfinite(result) and abs(result) <= limit, 'INVALID_COORDINATE', f'{name} exceeds the numeric range.')
    return result


def _longitude_latitude(longitude: object, latitude: object, coordinate_system: str = 'WGS84') -> tuple[float, float]:
    _require(coordinate_system == 'WGS84', 'UNSUPPORTED_CRS', 'Only explicitly WGS84 longitude/latitude is accepted.')
    longitude = _number(longitude, 'longitude', 180)
    latitude = _number(latitude, 'latitude', 90)
    _require(-80 <= latitude <= 84, 'OUTSIDE_PROJECTION_AREA', 'The regional UTM frame excludes polar areas.')
    return longitude, latitude


def _zone(longitude: float) -> int:
    return min(60, int(math.floor((longitude + 180) / 6)) + 1)


def _transform(source: str, target: str, xs: Sequence[float], ys: Sequence[float]) -> tuple[list[float], list[float]]:
    # Import at use time so the ordinary workbench can start without the optional GIS worker runtime.
    os.environ['PROJ_NETWORK'] = 'OFF'
    try:
        import rasterio
        from rasterio.warp import transform
    except ImportError as error:
        raise CoordinateError('PROCESSING_UNAVAILABLE', 'The validated terrain projection runtime is unavailable.') from error
    try:
        with rasterio.Env(PROJ_NETWORK='OFF'):
            out_x, out_y = transform(source, target, list(xs), list(ys))
    except Exception as error:
        raise CoordinateError('INVALID_COORDINATE', 'The coordinate transformation failed.') from error
    _require(all(math.isfinite(v) for v in (*out_x, *out_y)), 'INVALID_COORDINATE', 'The transformation returned a non-finite value.')
    return out_x, out_y


def _distance_m(longitude1: float, latitude1: float, longitude2: float, latitude2: float) -> float:
    dlat, dlon = math.radians(latitude2 - latitude1), math.radians(longitude2 - longitude1)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(latitude1)) * math.cos(math.radians(latitude2)) * math.sin(dlon / 2) ** 2
    return 6_378_137 * 2 * math.asin(min(1.0, math.sqrt(h)))


def normalize_heading(heading_deg: object) -> float:
    return _number(heading_deg, 'heading', 1e6) % 360.0


@dataclass(frozen=True)
class ProjectedFrame:
    origin_longitude: float
    origin_latitude: float
    origin_height_m: float
    vertical_datum: str
    frame_revision: str
    max_radius_m: float = MAX_SITE_RADIUS_M
    horizontal_crs: str = field(init=False)
    origin_easting_m: float = field(init=False)
    origin_northing_m: float = field(init=False)
    transform_id: str = field(init=False)

    def __post_init__(self) -> None:
        longitude, latitude = _longitude_latitude(self.origin_longitude, self.origin_latitude)
        height = _number(self.origin_height_m, 'origin height', MAX_ABS_HEIGHT_M)
        radius = _number(self.max_radius_m, 'site radius', MAX_SITE_RADIUS_M)
        _require(radius > 0, 'INVALID_COORDINATE', 'The site radius must be positive.')
        _require(isinstance(self.vertical_datum, str) and self.vertical_datum in VERTICAL_DATUMS,
                 'VERTICAL_DATUM_CONFLICT', 'An explicit supported vertical datum is required.')
        _require(isinstance(self.frame_revision, str) and 0 < len(self.frame_revision) <= 200, 'INVALID_COORDINATE', 'The frame revision is required.')
        epsg = (32600 if latitude >= 0 else 32700) + _zone(longitude)
        crs = f'EPSG:{epsg}'
        east, north = _transform('EPSG:4326', crs, [longitude], [latitude])
        import rasterio
        runtime = f'rasterio-{rasterio.__version__}-gdal-{rasterio.__gdal_version__}-proj-{rasterio.__proj_version__}'
        for name, value in (('origin_longitude', longitude), ('origin_latitude', latitude), ('origin_height_m', height),
                            ('max_radius_m', radius), ('horizontal_crs', crs), ('origin_easting_m', east[0]),
                            ('origin_northing_m', north[0]), ('transform_id', f'utm-wgs84-v1:{crs}:{runtime}')):
            object.__setattr__(self, name, value)

    def _geographic(self, longitude: object, latitude: object, coordinate_system: str = 'WGS84') -> tuple[float, float]:
        longitude, latitude = _longitude_latitude(longitude, latitude, coordinate_system)
        _require(_zone(longitude) == _zone(self.origin_longitude) and (latitude >= 0) == (self.origin_latitude >= 0),
                 'OUTSIDE_PROJECTION_AREA', 'The point crosses the locked UTM zone or hemisphere.')
        _require(_distance_m(self.origin_longitude, self.origin_latitude, longitude, latitude) <= self.max_radius_m,
                 'OUTSIDE_COVERAGE', 'The point exceeds the validated regional radius.')
        return longitude, latitude

    def project(self, longitude: object, latitude: object, *, coordinate_system: str = 'WGS84') -> tuple[float, float]:
        longitude, latitude = self._geographic(longitude, latitude, coordinate_system)
        east, north = _transform('EPSG:4326', self.horizontal_crs, [longitude], [latitude])
        return east[0], north[0]

    def unproject(self, easting_m: object, northing_m: object) -> tuple[float, float]:
        east, north = _number(easting_m, 'easting', 2e7), _number(northing_m, 'northing', 2e7)
        longitude, latitude = _transform(self.horizontal_crs, 'EPSG:4326', [east], [north])
        return self._geographic(longitude[0], latitude[0])

    def to_display(self, longitude: object, latitude: object, height_m: object, *, vertical_datum: str,
                   coordinate_system: str = 'WGS84') -> tuple[float, float, float]:
        _same_datum(vertical_datum, self.vertical_datum)
        east, north = self.project(longitude, latitude, coordinate_system=coordinate_system)
        height = _number(height_m, 'height', MAX_ABS_HEIGHT_M)
        return east - self.origin_easting_m, height - self.origin_height_m, -(north - self.origin_northing_m)

    def from_display(self, x_m: object, y_m: object, z_m: object) -> tuple[float, float, float]:
        x, y, z = (_number(value, name, MAX_ABS_HEIGHT_M) for value, name in ((x_m, 'x'), (y_m, 'y'), (z_m, 'z')))
        longitude, latitude = self.unproject(self.origin_easting_m + x, self.origin_northing_m - z)
        height = self.origin_height_m + y
        _require(abs(height) <= MAX_ABS_HEIGHT_M, 'INVALID_COORDINATE', 'The resulting height exceeds the numeric range.')
        return longitude, latitude, height

    def north_grid_heading(self, longitude: object, latitude: object) -> float:
        """Clockwise angle from grid north to true north; measured, not a guessed sign."""
        longitude, latitude = self._geographic(longitude, latitude)
        delta = 1e-5
        east, north = _transform('EPSG:4326', self.horizontal_crs, [longitude, longitude], [latitude - delta, latitude + delta])
        return math.degrees(math.atan2(east[1] - east[0], north[1] - north[0]))

    def true_heading_to_grid(self, heading_deg: object, longitude: object, latitude: object) -> float:
        return (normalize_heading(heading_deg) + self.north_grid_heading(longitude, latitude)) % 360.0

    def grid_heading_to_true(self, heading_deg: object, longitude: object, latitude: object) -> float:
        return (normalize_heading(heading_deg) - self.north_grid_heading(longitude, latitude)) % 360.0

    def true_heading_to_three_yaw(self, heading_deg: object, longitude: object, latitude: object) -> float:
        """Radians for a calibrated model facing -Z; positive Three Y rotation turns west."""
        return -math.radians(self.true_heading_to_grid(heading_deg, longitude, latitude))

    def record(self) -> dict:
        from rasterio.crs import CRS
        return {'mode': 'projected_site', 'frameRevision': self.frame_revision, 'horizontalCrs': self.horizontal_crs,
                'horizontalCrsWkt': CRS.from_string(self.horizontal_crs).to_wkt(), 'verticalDatum': self.vertical_datum,
                'transformId': self.transform_id, 'convergenceRuleId': CONVERGENCE_RULE,
                'originEasting': self.origin_easting_m, 'originNorthing': self.origin_northing_m,
                'originHeight': self.origin_height_m, 'maxRadiusM': self.max_radius_m,
                'displayAxes': 'X_GRID_EAST_Y_UP_Z_GRID_SOUTH', 'isStrictEnu': False}


def _same_datum(actual: object, expected: object) -> None:
    _require(isinstance(actual, str) and isinstance(expected, str)
             and actual in VERTICAL_DATUMS and expected in VERTICAL_DATUMS and actual == expected,
             'VERTICAL_DATUM_CONFLICT', 'Vertical datums differ; no implicit vertical conversion is available.')


def resolve_height(strategy: Mapping[str, object], *, frame_mode: str, vertical_datum: str | None,
                   terrain_vertical_datum: str | None = None) -> float:
    """Validate height arithmetic only; the resource service must verify sample/version fields."""
    _require(isinstance(strategy, Mapping), 'INVALID_COORDINATE', 'A height strategy is required.')
    mode = strategy.get('mode')
    if frame_mode == 'local_plane':
        _require(mode == 'local_relative' and vertical_datum is None, 'VERTICAL_DATUM_CONFLICT', 'A local plane only accepts relative height.')
        return _number(strategy.get('relativeHeightM'), 'relative height', MAX_ABS_HEIGHT_M)
    _require(frame_mode == 'projected_site' and isinstance(vertical_datum, str) and vertical_datum in VERTICAL_DATUMS,
             'VERTICAL_DATUM_CONFLICT', 'An explicit projected vertical datum is required.')
    datum = strategy.get('verticalDatum')
    _same_datum(datum, vertical_datum)
    if mode == 'terrain_ground':
        _same_datum(terrain_vertical_datum, vertical_datum)
        value = _number(strategy.get('sampledHeightM'), 'sampled height', MAX_ABS_HEIGHT_M)
        offset = _number(strategy.get('offsetM'), 'height offset', MAX_ABS_HEIGHT_M)
        result = value + offset
        _require(abs(result) <= MAX_ABS_HEIGHT_M, 'INVALID_COORDINATE', 'The resulting height exceeds the numeric range.')
        return result
    _require(mode == 'absolute' and vertical_datum != 'UNKNOWN_RELATIVE', 'VERTICAL_DATUM_CONFLICT', 'Unknown relative terrain cannot support absolute height.')
    note = strategy.get('sourceNote')
    _require(isinstance(note, str) and 0 < len(note.strip()) <= 2000, 'INVALID_COORDINATE', 'An absolute height source is required.')
    return _number(strategy.get('valueM'), 'absolute height', MAX_ABS_HEIGHT_M)


def sample_bilinear(data: Sequence[Sequence[float]], affine: Sequence[float], x: object, y: object,
                    *, mask: Sequence[Sequence[object]] | None = None, nodata: float | None = None) -> float:
    """Sample raster coordinates with (a,b,c,d,e,f) pixel-corner affine coefficients.

    Rasterio already accounts for AREA_OR_POINT. Values lie at pixel centres.
    Only the closed centre-to-centre domain is sampled; its edges use the last
    two centres, without extrapolating the half-pixel outer rim. All four source
    values must be valid, even when an interpolation weight is zero.
    """
    try:
        height = len(data)
        width = len(data[0]) if height else 0
        rectangular = height >= 2 and width >= 2 and all(len(row) == width for row in data)
        mask_matches = mask is None or len(mask) == height and all(len(row) == width for row in mask)
    except (TypeError, IndexError) as error:
        raise CoordinateError('INVALID_TERRAIN', 'A rectangular raster and matching validity mask are required.') from error
    _require(rectangular, 'INVALID_TERRAIN', 'A rectangular raster of at least 2 by 2 is required.')
    _require(mask_matches, 'INVALID_TERRAIN', 'The validity mask shape does not match.')
    _require(affine is not None and hasattr(affine, '__len__') and len(affine) in (6, 9),
             'INVALID_TERRAIN', 'Six pixel-corner affine coefficients are required.')
    if len(affine) == 9:
        _require(tuple(affine[6:]) == (0, 0, 1), 'INVALID_TERRAIN', 'Perspective raster transforms are unsupported.')
    _require(nodata is None or isinstance(nodata, Real), 'INVALID_TERRAIN', 'The NoData marker must be numeric.')
    a, b, c, d, e, f = (_number(value, 'affine coefficient') for value in affine[:6])
    determinant = a * e - b * d
    _require(abs(determinant) > 1e-20, 'INVALID_TERRAIN', 'The affine transform is singular.')
    x, y = _number(x, 'sample x'), _number(y, 'sample y')
    column = (e * (x - c) - b * (y - f)) / determinant - .5
    row = (-d * (x - c) + a * (y - f)) / determinant - .5
    epsilon = 1e-9
    _require(-epsilon <= column <= width - 1 + epsilon and -epsilon <= row <= height - 1 + epsilon,
             'OUTSIDE_COVERAGE', 'The point is outside the raster centre-to-centre sampling domain.')
    column, row = min(width - 1, max(0., column)), min(height - 1, max(0., row))
    left, top = min(width - 2, math.floor(column)), min(height - 2, math.floor(row))
    tx, ty = column - left, row - top
    values = []
    for r, col in ((top, left), (top, left + 1), (top + 1, left), (top + 1, left + 1)):
        value = data[r][col]
        _require(isinstance(value, Real) and not isinstance(value, bool), 'NO_DATA', 'A required sample is not a valid elevation.')
        value = float(value)
        valid_mask = True
        if mask is not None:
            mask_value = mask[r][col]
            try:
                valid_mask = math.isfinite(mask_value) and bool(mask_value)
            except (TypeError, ValueError):
                valid_mask = False
        _require(valid_mask and math.isfinite(value) and (nodata is None or value != nodata), 'NO_DATA', 'A required interpolation neighbour is missing.')
        values.append(value)
    return (values[0] * (1 - tx) + values[1] * tx) * (1 - ty) + (values[2] * (1 - tx) + values[3] * tx) * ty


@dataclass(frozen=True)
class LocalPlacement:
    instance_id: str
    x_m: float
    z_m: float
    relative_height_m: float = 0.
    heading_deg: float = 0.


@dataclass(frozen=True)
class AnchoredPlacement:
    instance_id: str
    longitude: float
    latitude: float
    height_m: float
    heading_deg: float
    display: tuple[float, float, float]


@dataclass(frozen=True)
class TerrainHeight:
    value_m: float
    vertical_datum: str


def preview_anchor(placements: Sequence[LocalPlacement], frame: ProjectedFrame, *, local_anchor: Sequence[float],
                   geographic_anchor: Sequence[float], true_north_heading_deg: float, anchor_height: TerrainHeight,
                   height_strategy: str = 'keep_relative_to_anchor', ground_offset_m: float = 0.,
                   terrain_sample: Callable[[float, float], TerrainHeight] | None = None) -> tuple[AnchoredPlacement, ...]:
    """Return a new layout for explicit review; never confirm or persist the anchor.

    The local -Z axis is rotated to the requested true bearing at the anchor.
    Placement headings preserve that same rigid grid rotation; true headings
    vary slightly across the projected region as convergence changes.
    """
    _require(len(placements) <= 100, 'SCENE_LIMIT_EXCEEDED', 'The anchor preview exceeds 100 placements.')
    _require(len(local_anchor) == 2 and len(geographic_anchor) == 2, 'INVALID_COORDINATE', 'An explicit local and geographic anchor is required.')
    lx, lz = (_number(value, 'local anchor', MAX_ABS_HEIGHT_M) for value in local_anchor)
    longitude, latitude = geographic_anchor
    ae, an = frame.project(longitude, latitude)
    _same_datum(anchor_height.vertical_datum, frame.vertical_datum)
    anchor_h = _number(anchor_height.value_m, 'anchor height', MAX_ABS_HEIGHT_M)
    offset = _number(ground_offset_m, 'ground offset', MAX_ABS_HEIGHT_M)
    _require(height_strategy in ('keep_relative_to_anchor', 'resample_each_ground'), 'INVALID_COORDINATE', 'Unknown anchor height strategy.')
    _require(height_strategy != 'resample_each_ground' or callable(terrain_sample), 'INVALID_COORDINATE', 'Ground resampling requires an explicit sampler.')
    _require(height_strategy != 'keep_relative_to_anchor' or offset == 0, 'INVALID_COORDINATE', 'Keep-relative heights already include the anchor offset.')
    heading = frame.true_heading_to_grid(true_north_heading_deg, longitude, latitude)
    angle = math.radians(heading)
    sine, cosine = math.sin(angle), math.cos(angle)
    ids, result = set(), []
    for placement in placements:
        _require(isinstance(placement, LocalPlacement) and isinstance(placement.instance_id, str) and 0 < len(placement.instance_id) <= 200,
                 'INVALID_COORDINATE', 'A valid local placement is required.')
        _require(placement.instance_id not in ids, 'INVALID_COORDINATE', 'Duplicate placement identifiers are not allowed.')
        ids.add(placement.instance_id)
        dx = _number(placement.x_m, 'local x', MAX_ABS_HEIGHT_M) - lx
        dz = _number(placement.z_m, 'local z', MAX_ABS_HEIGHT_M) - lz
        east = ae + dx * cosine - dz * sine
        north = an - dx * sine - dz * cosine
        point_lon, point_lat = frame.unproject(east, north)
        relative = _number(placement.relative_height_m, 'relative height', MAX_ABS_HEIGHT_M)
        if height_strategy == 'resample_each_ground':
            sample = terrain_sample(point_lon, point_lat)
            _require(isinstance(sample, TerrainHeight), 'INVALID_COORDINATE', 'The sampler must return a height and datum.')
            _same_datum(sample.vertical_datum, frame.vertical_datum)
            height = _number(sample.value_m, 'sampled height', MAX_ABS_HEIGHT_M) + offset + relative
        else:
            height = anchor_h + relative
        display = frame.to_display(point_lon, point_lat, height, vertical_datum=frame.vertical_datum)
        true_heading = frame.grid_heading_to_true(heading + normalize_heading(placement.heading_deg), point_lon, point_lat)
        result.append(AnchoredPlacement(placement.instance_id, point_lon, point_lat, height, true_heading, display))
    return tuple(result)
