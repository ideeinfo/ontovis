"""Release checks must catch present-but-unused login media."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.build_workbench import stage_media, verify_media_build


class LoginMediaBuildTests(unittest.TestCase):
    def test_compiled_references_and_exact_media_are_both_required(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'source'; source.mkdir()
            (source / 'login-background.mp4').write_bytes(b'\x00\x00\x00\x18ftypmp42')
            (source / 'login-background-poster.webp').write_bytes(b'RIFF\x04\x00\x00\x00WEBP')
            build = root / 'build'; manifest = stage_media(source, build)
            (build / 'assets').mkdir(); bundle = build / 'assets/login.js'
            bundle.write_text('static fallback only')
            with self.assertRaisesRegex(ValueError, 'reference'): verify_media_build(build, manifest)
            bundle.write_text(json.dumps([item['url'] for item in manifest.values()]))
            verify_media_build(build, manifest)
            (build / manifest['login-background.mp4']['url'].lstrip('/')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'changed'): verify_media_build(build, manifest)


if __name__ == '__main__': unittest.main()
