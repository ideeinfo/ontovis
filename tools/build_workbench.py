"""Build the workbench with explicitly supplied, local-only login media.

The source video stays outside Git. This packages a pre-encoded H.264 MP4 and
its matching WebP poster as same-origin static assets, never as API uploads.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path(__file__).resolve().parents[1]
FILES = {'login-background.mp4': 12 * 1024 * 1024,
         'login-background-poster.webp': 2 * 1024 * 1024}
BUILD = ROOT / 'output/compact-workbench-20261021/workbench-dist'


def verify_media_build(destination: Path, manifest: dict) -> None:
    """Media files alone do not prove that the compiled login page uses them."""
    bundles = '\n'.join(path.read_text() for path in (destination / 'assets').glob('*.js'))
    if json.loads((destination / 'login-media-manifest.json').read_text()) != manifest:
        raise ValueError('Login media manifest does not match this build.')
    for item in manifest.values():
        path = destination / item['url'].lstrip('/')
        if (not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != item['sha256']
                or item['url'] not in bundles):
            raise ValueError('Compiled login media reference or file is missing or changed.')


def stage_media(source: Path, destination: Path) -> dict:
    source = source.resolve(strict=True)
    destination.mkdir(parents=True, exist_ok=True)
    media = destination / 'media'
    media.mkdir(exist_ok=True)
    result = {}
    for name, limit in FILES.items():
        path = source / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
            raise ValueError('A bounded regular MP4 and matching WebP poster are required.')
        data = path.read_bytes()
        if name.endswith('.mp4'):
            if len(data) < 12 or data[4:8] != b'ftyp':
                raise ValueError('Expected an MP4 container.')
        elif data[:4] != b'RIFF' or data[8:12] != b'WEBP':
            raise ValueError('Expected a WebP poster.')
        digest = hashlib.sha256(data).hexdigest()
        target_name = f'{path.stem}-{digest[:16]}{path.suffix}'
        target = media / target_name
        target.write_bytes(data)
        result[name] = {'url': '/media/' + target_name, 'sha256': digest, 'bytes': len(data)}
    (destination / 'login-media-manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--media-dir', type=Path, required=True)
    parser.add_argument('--public-dir', type=Path, required=True)
    parser.add_argument('--stage-only', action='store_true')
    parser.add_argument('--check', action='store_true', help='Run the complete frontend check before packaging.')
    args = parser.parse_args()
    result = stage_media(args.media_dir, args.public_dir)
    public = args.public_dir.resolve()
    env = {**os.environ, 'ONTOVIS_LOGIN_MEDIA_PUBLIC_DIR': str(public),
           'VITE_LOGIN_VIDEO_SRC': result['login-background.mp4']['url'],
           'VITE_LOGIN_POSTER_SRC': result['login-background-poster.webp']['url']}
    if not args.stage_only:
        npm = shutil.which('npm')
        if npm is None:
            raise ValueError('Node 22 and npm are required.')
        subprocess.run([npm, 'run', 'check' if args.check else 'build'],
                       cwd=ROOT / 'apps/workbench', env=env, check=True)
        verify_media_build(BUILD, result)
    print(json.dumps({'media': result, 'publicDirectory': str(public),
                      'built': not args.stage_only}, ensure_ascii=False))


if __name__ == '__main__':
    main()
