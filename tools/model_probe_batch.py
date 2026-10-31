#!/usr/bin/env python3
"""Cancel/resume a private, sequential batch of the existing local GLB probe (Q-09)."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import subprocess
import sys
import tempfile
import threading
import time

if __package__:
    from .model_probe import MAX_BYTES, ProbeError, run_probe, strict_json
else:
    from model_probe import MAX_BYTES, ProbeError, run_probe, strict_json

MAX_MODELS = 100
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
MAX_JSON_BYTES = 256 * 1024
MAX_RESULT_BYTES = 64 * 1024 * 1024
RESULT_FILES = {'report.json', 'components.json'}
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')


class BatchError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def require(condition, code, message):
    if not condition:
        raise BatchError(code, message)


def safe_path(path):
    path = Path(os.path.abspath(path))
    for part in (*reversed(path.parents), path):
        require(not part.is_symlink(), 'UNSAFE_PATH', 'Linked paths are outside this local batch scope.')
    return path


def fingerprint(path, limit, stop=None):
    path = safe_path(path)
    before = path.stat()
    require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
            'UNSAFE_PATH', 'A regular file with one link is required.')
    require(before.st_size <= limit, 'LIMIT_EXCEEDED', 'Local file budget exceeded.')
    digest = hashlib.sha256()
    size = 0
    with path.open('rb') as file:
        while chunk := file.read(1024 * 1024):
            require(stop is None or not stop(), 'CANCELLED', 'Batch cancelled during input verification.')
            size += len(chunk)
            require(size <= limit, 'LIMIT_EXCEEDED', 'File grew beyond the local budget.')
            digest.update(chunk)
        after = os.fstat(file.fileno())
    require((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns),
            'INPUT_CHANGED', 'File changed while being fingerprinted.')
    return {'sha256': digest.hexdigest(), 'bytes': after.st_size}


def read_json(path, limit=MAX_JSON_BYTES):
    fingerprint(path, limit)
    return strict_json(path.read_bytes())


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()


def atomic_json(path, value):
    if path.exists():
        fingerprint(path, MAX_RESULT_BYTES)
    fd, temporary = tempfile.mkstemp(prefix='.checkpoint-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as file:
            file.write(json_bytes(value))
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        Path(temporary).unlink(missing_ok=True)


@contextmanager
def batch_lock(output):
    path = safe_path(output / '.lock')
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, 'UNSAFE_PATH', 'Invalid batch lock.')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BatchError('BATCH_BUSY', 'Another process still owns this batch.') from None
        yield fd
    finally:
        # A worker inherits the same lock; closing preserves ownership if the parent was killed.
        os.close(fd)


def processors():
    return {name: fingerprint(Path(__file__).with_name(name), MAX_BYTES)['sha256']
            for name in ('model_probe.py', 'model_probe_batch.py')}


def load_plan(manifest, timeout, stop):
    require(type(timeout) is int and 1 <= timeout <= 600, 'INVALID_MANIFEST', 'Timeout must be 1–600 seconds.')
    raw = read_json(safe_path(manifest))
    require(isinstance(raw, dict) and set(raw) == {'schemaVersion', 'models'} and type(raw['schemaVersion']) is int
            and raw['schemaVersion'] == 1 and isinstance(raw['models'], list)
            and 1 <= len(raw['models']) <= MAX_MODELS, 'INVALID_MANIFEST', 'Expected schemaVersion 1 and 1–100 models.')
    models, identifiers, paths, total = [], set(), set(), 0
    for row in raw['models']:
        require(isinstance(row, dict) and set(row) == {'id', 'source', 'sha256'}
                and isinstance(row['id'], str) and ID.fullmatch(row['id'])
                and isinstance(row['source'], str) and row['source']
                and isinstance(row['sha256'], str) and SHA256.fullmatch(row['sha256']),
                'INVALID_MANIFEST', 'Each model requires a unique safe id, local source and lowercase SHA256.')
        source = safe_path(manifest.parent / row['source'])
        require(row['id'] not in identifiers and source not in paths,
                'INVALID_MANIFEST', 'Duplicate model id or source path.')
        actual = fingerprint(source, MAX_BYTES, stop)
        require(actual['sha256'] == row['sha256'], 'INPUT_CHANGED', 'Input differs from the manifest fingerprint.')
        total += actual['bytes']
        require(total <= MAX_TOTAL_BYTES, 'LIMIT_EXCEEDED', 'Batch input exceeds the 1 GiB local budget.')
        identifiers.add(row['id'])
        paths.add(source)
        models.append({'id': row['id'], 'source': str(source), **actual})
    return {'schemaVersion': 1, 'timeoutSeconds': timeout, 'models': models}


def save(output, state):
    state['updatedAt'] = datetime.now(timezone.utc).isoformat()
    state['counts'] = {key: sum(item['status'] == key for item in state['items'])
                       for key in ('pending', 'running', 'passed', 'failed')}
    atomic_json(output / 'checkpoint.json', state)


def emit(state, event, item=None):
    print(json.dumps({'event': event, 'status': state['status'], 'counts': state['counts'],
                      **({'id': item['id']} if item else {}), 'releaseEligible': False}), flush=True)


def attempt_path(output, index, number):
    return safe_path(output / 'items' / f'{index:03d}' / f'attempt-{number:03d}')


def result_files(path):
    if not path.exists():
        return {}
    require(path.is_dir(), 'OUTPUT_CHANGED', 'Missing attempt directory.')
    names = {entry.name for entry in path.iterdir()}
    require(names <= RESULT_FILES, 'OUTPUT_CHANGED', 'Unexpected file in a completed attempt.')
    return {name: fingerprint(path / name, MAX_RESULT_BYTES) for name in sorted(names)}


def load_checkpoint(output, stop):
    state = read_json(output / 'checkpoint.json', MAX_RESULT_BYTES)
    plan = read_json(output / 'plan.json')
    require(isinstance(state, dict) and isinstance(plan, dict) and state.get('schemaVersion') == 1
            and plan.get('schemaVersion') == 1 and isinstance(plan.get('models'), list)
            and 1 <= len(plan['models']) <= MAX_MODELS and type(plan.get('timeoutSeconds')) is int
            and 1 <= plan['timeoutSeconds'] <= 600 and isinstance(state.get('items'), list),
            'INVALID_CHECKPOINT', 'Invalid batch checkpoint.')
    require(state.get('planSha256') == fingerprint(output / 'plan.json', MAX_JSON_BYTES)['sha256'],
            'PLAN_CHANGED', 'Frozen input plan changed.')
    require(state.get('processors') == processors(), 'PROCESSOR_CHANGED', 'Processor files changed; start a new batch.')
    require(state.get('status') in ('running', 'cancelled', 'passed', 'failed')
            and state.get('verificationScope') == 'local_batch_only' and state.get('releaseEligible') is False
            and len(state['items']) == len(plan['models']), 'INVALID_CHECKPOINT', 'Invalid batch status or item count.')
    identifiers, paths, total = set(), set(), 0
    for index, (model, item) in enumerate(zip(plan['models'], state['items'])):
        require(isinstance(model, dict) and set(model) == {'id', 'source', 'sha256', 'bytes'}
                and isinstance(model['id'], str) and ID.fullmatch(model['id'])
                and isinstance(model['source'], str) and Path(model['source']).is_absolute()
                and isinstance(model['sha256'], str) and SHA256.fullmatch(model['sha256'])
                and type(model['bytes']) is int and 0 <= model['bytes'] <= MAX_BYTES
                and model['id'] not in identifiers and model['source'] not in paths
                and isinstance(item, dict) and item.get('id') == model['id']
                and item.get('status') in ('pending', 'running', 'passed', 'failed')
                and isinstance(item.get('attempts'), list), 'INVALID_CHECKPOINT', 'Invalid frozen model or item.')
        identifiers.add(model['id'])
        paths.add(model['source'])
        total += model['bytes']
        require(total <= MAX_TOTAL_BYTES, 'LIMIT_EXCEEDED', 'Batch input exceeds its budget.')
        require(fingerprint(Path(model['source']), MAX_BYTES, stop)
                == {key: model[key] for key in ('sha256', 'bytes')}, 'INPUT_CHANGED', 'Frozen input changed; results cannot be reused.')
        for number, attempt in enumerate(item['attempts'], 1):
            require(isinstance(attempt, dict) and attempt.get('number') == number
                    and attempt.get('status') in ('running', 'interrupted', 'cancelled', 'passed', 'failed'),
                    'INVALID_CHECKPOINT', 'Invalid attempt history.')
            if attempt['status'] in ('passed', 'failed'):
                require(attempt.get('files') == result_files(attempt_path(output, index, number)),
                        'OUTPUT_CHANGED', 'Completed report or catalog changed; results cannot be reused.')
        if item['status'] in ('passed', 'failed'):
            require(item['attempts'] and item['attempts'][-1]['status'] == item['status'],
                    'INVALID_CHECKPOINT', 'Completed item lacks a matching attempt.')
            if item['status'] == 'passed':
                require(set(item['attempts'][-1]['files']) == RESULT_FILES,
                        'INVALID_CHECKPOINT', 'Passed item lacks its report or catalog.')
    return plan, state


def worker_command(model, path, timeout):
    return [sys.executable, str(Path(__file__).absolute()), '_worker', '--source', model['source'],
            '--sha256', model['sha256'], '--output', str(path), '--timeout-seconds', str(timeout)]


def stop_worker(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
    process.wait(timeout=3)
    process.stdin.close()


def process_one(model, path, timeout, lock_fd, stop):
    process = subprocess.Popen(worker_command(model, path, timeout), stdin=subprocess.PIPE,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, pass_fds=(lock_fd,))
    deadline = time.monotonic() + timeout
    reason = None
    try:
        while process.poll() is None:
            if stop():
                reason = 'CANCELLED'
                break
            if time.monotonic() >= deadline:
                reason = 'WORKER_TIMEOUT'
                break
            time.sleep(.05)
    finally:
        stop_worker(process)
    if reason == 'CANCELLED':
        return {'status': 'cancelled', 'errorCode': reason}
    files = result_files(path) if path.exists() else {}
    try:
        report = read_json(path / 'report.json', MAX_RESULT_BYTES) if 'report.json' in files else {}
    except ProbeError:
        # A killed/timed-out writer may leave a partial JSON file; retain it as a failed attempt.
        report = {}
    if not isinstance(report, dict):
        report = {}
    valid = (isinstance(report, dict) and report.get('status') in ('passed', 'failed')
             and isinstance(report.get('releaseReadiness'), dict) and report['releaseReadiness'].get('eligible') is False)
    if valid and report['status'] == 'passed':
        valid = (set(files) == RESULT_FILES and isinstance(report.get('source'), dict)
                 and isinstance(report.get('catalog'), dict) and report['source'].get('sha256') == model['sha256']
                 and report['catalog'].get('sha256') == files['components.json']['sha256'])
    passed = valid and report['status'] == 'passed' and process.returncode == 0 and reason is None
    error = None if passed else ('WORKER_TIMEOUT' if reason or process.returncode == 124 else
                                report.get('error', {}).get('code', 'WORKER_FAILED') if valid else 'WORKER_FAILED')
    return {'status': 'passed' if passed else 'failed', 'files': files, 'errorCode': error}


def run_batch(output, *, manifest=None, timeout=120, stop=lambda: False):
    output = safe_path(output)
    if manifest is not None:
        plan = load_plan(safe_path(manifest), timeout, stop)
        output.mkdir(mode=0o700, parents=True, exist_ok=False)
        atomic_json(output / 'plan.json', plan)
        state = {'schemaVersion': 1, 'verificationScope': 'local_batch_only', 'releaseEligible': False,
                 'createdAt': datetime.now(timezone.utc).isoformat(), 'status': 'running', 'processors': processors(),
                 'planSha256': fingerprint(output / 'plan.json', MAX_JSON_BYTES)['sha256'],
                 'items': [{'id': model['id'], 'status': 'pending', 'attempts': []} for model in plan['models']]}
        save(output, state)
    with batch_lock(output) as lock_fd:
        marker = output / 'cancel.request'
        if marker.exists() or marker.is_symlink():
            fingerprint(marker, 0)
            marker.unlink()
        cancelled = lambda: stop() or marker.exists() or marker.is_symlink()
        plan, state = load_checkpoint(output, cancelled)
        for item in state['items']:
            if item['status'] == 'running':
                require(item['attempts'] and item['attempts'][-1]['status'] == 'running',
                        'INVALID_CHECKPOINT', 'Running item lacks its attempt.')
                item['attempts'][-1]['status'] = 'interrupted'
                item['status'] = 'pending'
        state['status'] = 'running'
        save(output, state)
        emit(state, 'batch_started')
        for index, (model, item) in enumerate(zip(plan['models'], state['items'])):
            if cancelled():
                break
            if item['status'] in ('passed', 'failed'):
                continue
            require(state['processors'] == processors(), 'PROCESSOR_CHANGED', 'Processor files changed during this batch.')
            number = len(item['attempts']) + 1
            path = attempt_path(output, index, number)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            require(not path.exists(), 'OUTPUT_CHANGED', 'Attempt directory already exists; never overwrite it.')
            attempt = {'number': number, 'status': 'running'}
            item['attempts'].append(attempt)
            item['status'] = 'running'
            save(output, state)
            emit(state, 'item_started', item)
            result = process_one(model, path, plan['timeoutSeconds'], lock_fd, cancelled)
            require(fingerprint(Path(model['source']), MAX_BYTES)
                    == {key: model[key] for key in ('sha256', 'bytes')}, 'INPUT_CHANGED', 'Input changed during processing.')
            attempt.update(result)
            item['status'] = 'pending' if result['status'] == 'cancelled' else result['status']
            save(output, state)
            emit(state, 'item_finished', item)
            if result['status'] == 'cancelled':
                break
        state['status'] = ('cancelled' if cancelled() or state['counts']['pending'] else
                           'failed' if state['counts']['failed'] else 'passed')
        save(output, state)
        emit(state, 'batch_finished')
        return state


def cancel_batch(output):
    output = safe_path(output)
    state = read_json(output / 'checkpoint.json', MAX_RESULT_BYTES)
    require(isinstance(state, dict) and state.get('status') in ('running', 'cancelled', 'passed', 'failed'),
            'INVALID_CHECKPOINT', 'Invalid batch checkpoint.')
    if state['status'] not in ('passed', 'failed'):
        marker = safe_path(output / 'cancel.request')
        try:
            fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            os.fsync(fd)
            os.close(fd)
        except FileExistsError:
            fingerprint(marker, 0)
    return {'status': state['status'], 'cancellationRequested': state['status'] not in ('passed', 'failed')}


def worker(source, output, sha256, timeout):
    def watchdog():
        ready, _, _ = select.select([sys.stdin.buffer], [], [], timeout)
        # The parent holds stdin open. EOF also terminates a worker after SIGKILL of its owner.
        os._exit(125 if ready else 124)
    threading.Thread(target=watchdog, daemon=True).start()
    os.umask(0o077)
    report = run_probe(source, output, source_sha256=sha256)
    return 0 if report['status'] == 'passed' else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    start = commands.add_parser('start', help='Freeze and inspect a new local source manifest.')
    start.add_argument('--manifest', type=Path, required=True)
    start.add_argument('--timeout-seconds', type=int, default=120)
    for name in ('resume', 'cancel'):
        commands.add_parser(name)
    internal = commands.add_parser('_worker', help=argparse.SUPPRESS)
    internal.add_argument('--source', type=Path, required=True)
    internal.add_argument('--sha256', required=True)
    internal.add_argument('--timeout-seconds', type=int, required=True)
    for command in commands.choices.values():
        command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == '_worker':
        return worker(args.source, args.output, args.sha256, args.timeout_seconds)
    cancelled = threading.Event()
    old_handlers = {sig: signal.signal(sig, lambda *_: cancelled.set()) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        if args.command == 'cancel':
            print(json.dumps(cancel_batch(args.output)))
            return 0
        state = run_batch(args.output, manifest=args.manifest if args.command == 'start' else None,
                          timeout=args.timeout_seconds if args.command == 'start' else 120, stop=cancelled.is_set)
        return 0 if state['status'] == 'passed' else 130 if state['status'] == 'cancelled' else 1
    except (BatchError, ProbeError, OSError, TypeError, KeyError, ValueError) as error:
        print(json.dumps({'status': 'failed', 'errorCode': getattr(error, 'code', 'INVALID_INPUT'),
                          'releaseEligible': False}), file=sys.stderr)
        return 130 if getattr(error, 'code', None) == 'CANCELLED' else 1
    finally:
        for sig, handler in old_handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
