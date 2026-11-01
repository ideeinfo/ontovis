"""The retired migration scripts must remain inert even when imported."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


class RetiredMigrationTests(unittest.TestCase):
    def test_unsafe_migrations_are_import_safe_and_fail_closed(self):
        root = Path(__file__).resolve().parents[1]
        for name in ('insert_ontobase_turbines', 'sync_ontobase_equipment_specifications', 'migrate_model_turbine_definitions',
                     'restore_ontobase_equipment_specifications', 'import_official_turbines_to_ontobase'):
            path = root / 'tools' / (name + '.py')
            if not path.exists(): continue
            with self.subTest(name=name), patch('subprocess.run', side_effect=AssertionError('must not execute')), \
                    patch('sqlite3.connect', side_effect=AssertionError('must not open database')):
                spec = importlib.util.spec_from_file_location(name, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                with self.assertRaises(SystemExit) as caught: module.main()
                self.assertIsInstance(caught.exception.code, str)
