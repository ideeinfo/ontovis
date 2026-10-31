"""Local POSIX directory locks for the SQLite service and offline snapshots."""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import stat


class StorageInUse(RuntimeError):
    def __init__(self):
        super().__init__('STORAGE_IN_USE')


@contextmanager
def storage_lease(roots, *, shared=False, create=False):
    """Hold directory inodes, without adding mutable files to backup manifests.

    All cooperating service processes take exclusive locks before initialization.
    Offline snapshots take shared locks for the entire capture/copy operation.
    This is a local advisory lock, not distributed storage or an online backup.
    """
    paths = sorted({Path(root).absolute() for root in roots})
    if not paths:
        raise ValueError('At least one private storage directory is required')
    # Shared ancestor locks stop a differently configured service from opening
    # a project library nested beneath an exclusively held registry root.
    intents = {parent: True for path in paths for parent in path.parents}
    intents.update({path: shared for path in paths})
    descriptors = []
    try:
        for path in sorted(intents, key=lambda value: (len(value.parts), str(value))):
            if path.is_symlink():
                raise ValueError('Private storage must not contain symlinks')
            if create:
                path.mkdir(mode=0o700, exist_ok=True)
            descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
            descriptors.append(descriptor)
            before, opened = path.lstat(), os.fstat(descriptor)
            if (not stat.S_ISDIR(opened.st_mode)
                    or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
                raise ValueError('Private storage directory changed')
            try:
                fcntl.flock(descriptor, (fcntl.LOCK_SH if intents[path] else fcntl.LOCK_EX) | fcntl.LOCK_NB)
            except BlockingIOError:
                raise StorageInUse() from None
        yield tuple(paths)
    finally:
        for descriptor in reversed(descriptors):
            # Closing also releases a lock after exceptions; no stale PID file.
            os.close(descriptor)
