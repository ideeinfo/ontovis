"""Regional coordinate and raster sampling checks using the real PROJ runtime."""
import copy
from dataclasses import FrozenInstanceError
import math
import os
import unittest
from unittest.mock import patch

from apps.api.terrain_coordinates import (
    CONVERGENCE_RULE, CoordinateError, LocalPlacement, ProjectedFrame,
    SAMPLING_RULE, TerrainHeight, normalize_heading, preview_anchor,
    resolve_height, sample_bilinear,
)


class CoordinateHelpers:
    def expect(self, code, action):
        with self.assertRaises(CoordinateError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    def frame(self, longitude=113.20076944444444, latitude=33.45344722222222, datum='EGM2008'):
        return ProjectedFrame(longitude, latitude, 300, datum, 'frame-fixture-1')


class CoordinateChecks(CoordinateHelpers, unittest.TestCase):
    def test_known_utm_origin_at_equator_and_southern_false_northing(self):
        north = self.frame(111, 0)
        self.assertEqual(north.horizontal_crs, 'EPSG:32649')
        self.assertAlmostEqual(north.origin_easting_m, 500000, places=6)
        self.assertAlmostEqual(north.origin_northing_m, 0, places=6)
        south = self.frame(111, -1)
        self.assertEqual(south.horizontal_crs, 'EPSG:32749')
        self.assertAlmostEqual(south.origin_easting_m, 500000, places=6)
        self.assertGreater(south.origin_northing_m, 9_800_000)

    def test_real_projection_multiple_points_round_trip(self):
        frame = self.frame()
        points = [(113.1, 33.35), (113.3, 33.35), (113.1, 33.55), (113.3, 33.55), (113.2, 33.45)]
        for longitude, latitude in points:
            with self.subTest(longitude=longitude, latitude=latitude):
                display = frame.to_display(longitude, latitude, 412.5, vertical_datum='EGM2008')
                result = frame.from_display(*display)
                self.assertAlmostEqual(result[0], longitude, places=10)
                self.assertAlmostEqual(result[1], latitude, places=10)
                self.assertAlmostEqual(result[2], 412.5, places=9)

    def test_display_axes_and_origin_height_are_explicit(self):
        frame = self.frame(111, 33)
        self.assertEqual(frame.to_display(111, 33, 300, vertical_datum='EGM2008'), (0, 0, 0))
        east = frame.to_display(111.001, 33, 310, vertical_datum='EGM2008')
        north = frame.to_display(111, 33.001, 300, vertical_datum='EGM2008')
        self.assertGreater(east[0], 90)
        self.assertEqual(east[1], 10)
        self.assertLess(north[2], -100)
        self.assertAlmostEqual(north[0], 0, places=6)

    def test_locked_zone_hemisphere_radius_and_poles_are_rejected(self):
        frame = self.frame(113.99, 33)
        self.expect('OUTSIDE_PROJECTION_AREA', lambda: frame.project(114.01, 33))
        self.expect('OUTSIDE_COVERAGE', lambda: frame.project(113.99, 34))
        equator = self.frame(111, .001)
        self.expect('OUTSIDE_PROJECTION_AREA', lambda: equator.project(111, -.001))
        self.expect('OUTSIDE_PROJECTION_AREA', lambda: self.frame(111, 85))
        dateline = self.frame(179.99, 1)
        self.expect('OUTSIDE_PROJECTION_AREA', lambda: dateline.project(-179.99, 1))

    def test_non_finite_boolean_swapped_and_unlabelled_coordinates_fail(self):
        frame = self.frame()
        for longitude, latitude in [(math.nan, 33), (113, math.inf), (True, 33), (33, 113)]:
            self.expect('INVALID_COORDINATE', lambda: frame.project(longitude, latitude))
        self.expect('UNSUPPORTED_CRS', lambda: frame.project(113.2, 33.45, coordinate_system='GCJ-02'))
        self.expect('INVALID_COORDINATE', lambda: ProjectedFrame(111, 33, 0, 'EGM2008', 'r', max_radius_m=50001))

    def test_true_north_direction_matches_an_independent_forward_difference(self):
        from rasterio.warp import transform
        for longitude in (109, 111, 113):
            frame = self.frame(longitude, 33)
            east, north = transform('EPSG:4326', frame.horizontal_crs, [longitude, longitude], [33, 33.0001])
            independently_measured = math.degrees(math.atan2(east[1] - east[0], north[1] - north[0])) % 360
            got = frame.true_heading_to_grid(0, longitude, 33)
            error = (got - independently_measured + 180) % 360 - 180
            self.assertLess(abs(error), .0001)
            self.assertAlmostEqual(frame.grid_heading_to_true(got, longitude, 33), 0, places=8)

    def test_convergence_sign_and_three_yaw_are_not_interchanged(self):
        central = self.frame(111, 33)
        self.assertAlmostEqual(central.north_grid_heading(111, 33), 0, places=7)
        self.assertAlmostEqual(central.true_heading_to_three_yaw(90, 111, 33), -math.pi / 2, places=8)
        west, east = self.frame(109, 33), self.frame(113, 33)
        self.assertGreater(west.north_grid_heading(109, 33), 0)
        self.assertLess(east.north_grid_heading(113, 33), 0)
        self.assertEqual(normalize_heading(-30), 330)

    def test_frame_is_immutable_and_records_non_enu_runtime(self):
        frame = self.frame()
        with self.assertRaises(FrozenInstanceError):
            frame.origin_height_m = 0
        record = frame.record()
        self.assertFalse(record['isStrictEnu'])
        self.assertIn('rasterio-', record['transformId'])
        self.assertEqual(record['convergenceRuleId'], CONVERGENCE_RULE)
        self.assertIn('WGS', record['horizontalCrsWkt'])
        self.assertEqual(record['originHeight'], 300)

    def test_projection_turns_off_inherited_network_configuration(self):
        from rasterio.warp import transform
        from rasterio.env import get_gdal_config
        def checked(*args, **kwargs):
            self.assertEqual(os.environ['PROJ_NETWORK'],'OFF')
            self.assertFalse(get_gdal_config('PROJ_NETWORK'))
            return transform(*args, **kwargs)
        with patch.dict(os.environ,{'PROJ_NETWORK':'ON'}), patch('rasterio.warp.transform',side_effect=checked):
            self.frame()

    def test_vertical_datum_conflict_never_applies_implicit_conversion(self):
        frame = self.frame()
        self.expect('VERTICAL_DATUM_CONFLICT', lambda: frame.to_display(113.2, 33.45, 300, vertical_datum='WGS84_ELLIPSOIDAL'))
        self.expect('VERTICAL_DATUM_CONFLICT', lambda: self.frame(datum='wgs84'))
        self.expect('VERTICAL_DATUM_CONFLICT', lambda: self.frame(datum=[]))


class RasterSamplingChecks(CoordinateHelpers, unittest.TestCase):
    def test_pixel_centres_interpolate_and_outer_half_pixel_is_rejected(self):
        data = [[10, 20, 30], [30, 40, 50], [50, 60, 70]]
        affine = (2, 0, 100, 0, -2, 200)
        self.assertEqual(sample_bilinear(data, affine, 101, 199), 10)
        self.assertEqual(sample_bilinear(data, affine, 102, 198), 25)
        self.assertEqual(sample_bilinear(data, affine, 105, 195), 70)
        self.expect('OUTSIDE_COVERAGE', lambda: sample_bilinear(data, affine, 100, 199))
        self.expect('OUTSIDE_COVERAGE', lambda: sample_bilinear(data, affine, 106, 199))
        self.assertIn('four-valid', SAMPLING_RULE)

    def test_all_four_neighbours_must_be_valid_even_at_zero_weight(self):
        data = [[10, 20], [30, -9999]]
        affine = (1, 0, 0, 0, -1, 0)
        self.expect('NO_DATA', lambda: sample_bilinear(data, affine, .5, -.5, nodata=-9999))
        self.expect('NO_DATA', lambda: sample_bilinear([[10, 20], [30, math.nan]], affine, 1, -1))
        self.expect('NO_DATA', lambda: sample_bilinear([[10, 20], [30, math.inf]], affine, 1, -1))
        self.expect('NO_DATA', lambda: sample_bilinear([[10, 20], [30, 40]], affine, .5, -.5, mask=[[255, 255], [255, 0]]))
        self.expect('NO_DATA', lambda: sample_bilinear([[10, 20], [30, 40]], affine, .5, -.5, mask=[[255, 255], [255, math.nan]]))

    def test_rotated_affine_uses_exact_inverse(self):
        data = [[0, 10], [20, 30]]
        affine = (2, .5, 100, .25, -3, 200)
        # Pixel-corner (1,1) lies midway between all four centres.
        self.assertAlmostEqual(sample_bilinear(data, affine, 102.5, 197.25), 15)

    def test_singular_ragged_and_invalid_mask_fail(self):
        self.expect('INVALID_TERRAIN', lambda: sample_bilinear([[1, 2], [3, 4]], (1, 1, 0, 1, 1, 0), .5, .5))
        self.expect('INVALID_TERRAIN', lambda: sample_bilinear([[1, 2], [3]], (1, 0, 0, 0, 1, 0), .5, .5))
        self.expect('INVALID_TERRAIN', lambda: sample_bilinear([[1, 2], [3, 4]], (1, 0, 0, 0, 1, 0), .5, .5, mask=[[1]]))
        self.expect('INVALID_TERRAIN', lambda: sample_bilinear(None, (1, 0, 0, 0, 1, 0), .5, .5))
        self.expect('INVALID_TERRAIN', lambda: sample_bilinear([[1, 2], [3, 4]], (1, 0, 0, 0, 1, 0, 1, 0, 1), 1, 1))

    def test_numpy_values_and_validity_mask_use_real_data_scalars(self):
        import numpy as np
        data = np.array([[1, 3], [5, 7]], dtype='float32')
        self.assertEqual(sample_bilinear(data, (1, 0, 0, 0, 1, 0), 1, 1, mask=np.ones((2, 2), dtype='uint8')), 4)
        self.assertEqual(sample_bilinear(data, (1, 0, 0, 0, 1, 0), 1, 1, mask=np.ones((2, 2), dtype='bool')), 4)


class HeightAndAnchorChecks(CoordinateHelpers, unittest.TestCase):
    def test_height_strategies_preserve_declared_datum(self):
        self.assertEqual(resolve_height({'mode': 'local_relative', 'relativeHeightM': 4}, frame_mode='local_plane', vertical_datum=None), 4)
        self.assertEqual(resolve_height({'mode': 'terrain_ground', 'sampledHeightM': 200, 'offsetM': 2, 'verticalDatum': 'EGM2008'},
                                        frame_mode='projected_site', vertical_datum='EGM2008', terrain_vertical_datum='EGM2008'), 202)
        self.assertEqual(resolve_height({'mode': 'absolute', 'valueM': 300, 'verticalDatum': 'EGM2008', 'sourceNote': 'Survey fixture'},
                                        frame_mode='projected_site', vertical_datum='EGM2008'), 300)

    def test_unknown_relative_is_ground_only_and_mixed_datum_is_rejected(self):
        self.assertEqual(resolve_height({'mode': 'terrain_ground', 'sampledHeightM': 20, 'offsetM': 2, 'verticalDatum': 'UNKNOWN_RELATIVE'},
                                        frame_mode='projected_site', vertical_datum='UNKNOWN_RELATIVE', terrain_vertical_datum='UNKNOWN_RELATIVE'), 22)
        self.expect('VERTICAL_DATUM_CONFLICT', lambda: resolve_height({'mode': 'absolute', 'valueM': 300, 'verticalDatum': 'UNKNOWN_RELATIVE', 'sourceNote': 'Fixture'},
                    frame_mode='projected_site', vertical_datum='UNKNOWN_RELATIVE'))
        self.expect('VERTICAL_DATUM_CONFLICT', lambda: resolve_height({'mode': 'terrain_ground', 'sampledHeightM': 200, 'offsetM': 0, 'verticalDatum': 'EGM2008'},
                    frame_mode='projected_site', vertical_datum='EGM2008', terrain_vertical_datum='WGS84_ELLIPSOIDAL'))
        self.expect('VERTICAL_DATUM_CONFLICT', lambda: resolve_height({'mode': 'local_relative', 'relativeHeightM': 4},
                    frame_mode='projected_site', vertical_datum='EGM2008'))

    def test_anchor_preview_is_new_rigid_layout_and_does_not_modify_input(self):
        frame = self.frame(111, 33)
        placements = [LocalPlacement('a', 12, -8, 3, 0), LocalPlacement('b', 112, -8, 0, 90)]
        before = copy.deepcopy(placements)
        result = preview_anchor(placements, frame, local_anchor=(12, -8), geographic_anchor=(111, 33),
                                true_north_heading_deg=90, anchor_height=TerrainHeight(310, 'EGM2008'))
        self.assertEqual(placements, before)
        self.assertEqual(result[0].instance_id, 'a')
        self.assertAlmostEqual(result[0].display[0], 0, places=6)
        self.assertAlmostEqual(result[0].display[1], 13, places=6)
        self.assertAlmostEqual(result[0].display[2], 0, places=6)
        self.assertAlmostEqual(result[1].display[0], 0, places=6)
        self.assertAlmostEqual(result[1].display[2], 100, places=6)
        self.assertAlmostEqual(result[0].heading_deg, 90, places=7)

    def test_anchor_resampling_preserves_offset_and_rejects_datum_conflict(self):
        frame = self.frame(111, 33)
        arguments = dict(local_anchor=(0, 0), geographic_anchor=(111, 33), true_north_heading_deg=0,
                         anchor_height=TerrainHeight(310, 'EGM2008'), height_strategy='resample_each_ground', ground_offset_m=2)
        result = preview_anchor([LocalPlacement('a', 0, 0, 3)], frame, **arguments, terrain_sample=lambda _x, _y: TerrainHeight(200, 'EGM2008'))
        self.assertEqual(result[0].height_m, 205)
        self.expect('VERTICAL_DATUM_CONFLICT', lambda: preview_anchor([LocalPlacement('a', 0, 0)], frame, **arguments,
                    terrain_sample=lambda _x, _y: TerrainHeight(200, 'WGS84_ELLIPSOIDAL')))
        self.expect('INVALID_COORDINATE', lambda: preview_anchor([LocalPlacement('a', 0, 0)], frame, **arguments))

    def test_anchor_rejects_duplicates_invalid_numbers_and_out_of_region(self):
        frame = self.frame(111, 33)
        arguments = dict(local_anchor=(0, 0), geographic_anchor=(111, 33), true_north_heading_deg=0, anchor_height=TerrainHeight(300, 'EGM2008'))
        self.expect('INVALID_COORDINATE', lambda: preview_anchor([LocalPlacement('a', 0, 0), LocalPlacement('a', 1, 1)], frame, **arguments))
        self.expect('INVALID_COORDINATE', lambda: preview_anchor([LocalPlacement('a', math.nan, 0)], frame, **arguments))
        self.expect('OUTSIDE_COVERAGE', lambda: preview_anchor([LocalPlacement('a', 60000, 0)], frame, **arguments))
        self.expect('SCENE_LIMIT_EXCEEDED', lambda: preview_anchor([LocalPlacement(str(i), 0, 0) for i in range(101)], frame, **arguments))


if __name__ == '__main__':
    unittest.main()
