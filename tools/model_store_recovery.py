"""Offline maintenance for orphan files in one private ONTOVis ModelLibrary.

Stop the owning service before apply. Preview uses SQLite read-only and never
initializes a ModelLibrary. Filesystem deletion is deliberately not described
as atomic: after interruption or partial failure, generate a new preview.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from uuid import UUID


VERSION_COLUMNS=('id','request_id','actor','name','source_note','sha256','bytes',
                 'created_at','revision','components','report')
VERSION_TYPES=('TEXT','TEXT','TEXT','TEXT','TEXT','TEXT','INTEGER','TEXT','INTEGER','TEXT','TEXT')
TEMPORARY_NAME=re.compile(r'(?:upload-|project-upload-|project-calibration-)[A-Za-z0-9_-]{1,128}\.glb\Z|scene-geometry-[A-Za-z0-9_-]{1,128}\.json\Z')
BUSY_TIMEOUT_MS=250


class RecoveryError(ValueError):
    def __init__(self,code,message,*,removed=()):
        super().__init__(message)
        self.code=code;self.removed=list(removed)

    def public(self):
        return {'code':self.code,'message':str(self),'removedCandidates':self.removed,
                'repreviewRequired':True,'deletionIsAtomic':False}


def _require(condition,code,message):
    if not condition:raise RecoveryError(code,message)


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode()


def _sha(value):
    return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None


def _uuid(value):
    try:return isinstance(value,str) and str(UUID(value))==value
    except (ValueError,TypeError,AttributeError):return False


def _root(value):
    try:root=Path(value)
    except (TypeError,ValueError):raise RecoveryError('INVALID_STORE','An absolute private ModelLibrary root is required.') from None
    _require(root.is_absolute() and '..' not in root.parts,'INVALID_STORE','An absolute private ModelLibrary root is required.')
    try:
        for path in (root,root/'files',root/'temporary'):
            info=path.lstat()
            _require(stat.S_ISDIR(info.st_mode) and not path.is_symlink(),'UNSAFE_STORE','The private store directories must be real directories.')
        database=root/'library.sqlite3';info=database.lstat()
        _require(stat.S_ISREG(info.st_mode) and not database.is_symlink(),'UNSAFE_STORE','The private database must be a regular file.')
        for suffix in ('-journal','-wal','-shm'):
            sidecar=Path(str(database)+suffix)
            _require(not sidecar.is_symlink(),'UNSAFE_STORE','Database sidecars must not be symlinks.')
        with database.open('rb') as file:header=file.read(100)
        _require(len(header)==100 and header[:16]==b'SQLite format 3\x00','INVALID_STORE','The private database header is invalid.')
        _require(header[18:20]==b'\x01\x01' and not Path(str(database)+'-wal').exists() and not Path(str(database)+'-shm').exists(),
                 'STORE_FORMAT_UNSUPPORTED','Only the existing rollback-journal ModelLibrary format is supported; checkpoint WAL separately while offline.')
    except OSError:raise RecoveryError('UNSAFE_STORE','The private store cannot be inspected safely.') from None
    return root


def _connect(root,readonly):
    db=None
    try:
        db=sqlite3.connect((root/'library.sqlite3').as_uri()+('?mode=ro' if readonly else '?mode=rw'),
                           uri=True,timeout=BUSY_TIMEOUT_MS/1000)
        db.execute('pragma busy_timeout='+str(BUSY_TIMEOUT_MS))
        if readonly:db.execute('pragma query_only=on')
        return db
    except sqlite3.Error as error:
        if db is not None:db.close()
        raise _database_error(error) from None


def _database_error(error):
    busy=getattr(error,'sqlite_errorcode',0)&255 in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED)
    return RecoveryError('STORE_BUSY' if busy else 'INVALID_STORE',
                         'The store is busy; stop the owning service and preview again.' if busy else
                         'The fixed ModelLibrary database could not be read; no cleanup was started.')


def _table(db,name,names,types):
    row=db.execute('select type,sql from sqlite_master where name=?',(name,)).fetchone()
    _require(row is not None and row[0]=='table' and isinstance(row[1],str) and row[1].lstrip().lower().startswith('create table'),
             'INVALID_STORE','The fixed ModelLibrary table is missing or unsupported.')
    columns=db.execute('pragma table_xinfo('+name+')').fetchall()
    _require(tuple(item[1] for item in columns)==names and tuple(item[2].upper() for item in columns)==types
             and all(item[6]==0 for item in columns) and columns[0][5]==1,
             'INVALID_STORE','The fixed ModelLibrary table schema differs from the supported store.')


def _fingerprint(path):
    try:
        before=path.lstat()
        _require(stat.S_ISREG(before.st_mode),'UNSAFE_STORE','An eligible model or temporary path is not a regular file.')
        descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(descriptor,'rb') as file:
            opened=os.fstat(file.fileno())
            _require((before.st_dev,before.st_ino)==(opened.st_dev,opened.st_ino) and stat.S_ISREG(opened.st_mode),
                     'STORE_CHANGED','A candidate changed during inspection; preview again.')
            digest=hashlib.sha256();size=0
            for chunk in iter(lambda:file.read(65536),b''):digest.update(chunk);size+=len(chunk)
            after=os.fstat(file.fileno())
        current=path.lstat()
        _require((opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns)==
                 (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) and
                 (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)==
                 (current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns) and size==opened.st_size,
                 'STORE_CHANGED','A file changed during inspection; preview again.')
        return {'bytes':size,'sha256':digest.hexdigest()}
    except RecoveryError:raise
    except OSError:raise RecoveryError('STORE_CHANGED','A file could not be safely inspected; preview again.') from None


def _report(root,db):
    _root(root)
    _table(db,'library',('id','revision','project_code','context_id'),('INTEGER','INTEGER','TEXT','TEXT'))
    _table(db,'versions',VERSION_COLUMNS,VERSION_TYPES)
    scopes=db.execute('select id,revision,project_code,context_id from library').fetchall()
    _require(len(scopes)==1 and scopes[0][0]==1 and type(scopes[0][1]) is int and scopes[0][1]>=0
             and isinstance(scopes[0][2],str) and scopes[0][2] and _uuid(scopes[0][3]),
             'INVALID_STORE','The private library identity is invalid.')
    _require(db.execute('pragma foreign_key_check').fetchone() is None,
             'INVALID_STORE','The private store contains unresolved resource references; no cleanup is allowed.')
    registered=[];identifiers=set()
    for identifier,size,digest in db.execute('select id,bytes,sha256 from versions order by id'):
        _require(_uuid(identifier) and type(size) is int and size>=0 and _sha(digest),
                 'INVALID_STORE','A registered model identity is invalid.')
        try:actual=_fingerprint(root/'files'/(identifier+'.glb'))
        except RecoveryError:raise RecoveryError('REGISTERED_MODEL_CHANGED','A registered GLB is missing, unsafe or changed; no cleanup is allowed.') from None
        _require(actual=={'bytes':size,'sha256':digest},'REGISTERED_MODEL_CHANGED','A registered GLB hash or byte count changed; no cleanup is allowed.')
        registered.append({'versionId':identifier,**actual});identifiers.add(identifier)
    candidates=[];preserved=[]
    for directory in ('files','temporary'):
        for path in sorted((root/directory).iterdir(),key=lambda item:item.name):
            name=path.name
            if directory=='files' and name.endswith('.glb') and _uuid(name[:-4]):
                if name[:-4] in identifiers:continue
                eligible=True
            else:eligible=directory=='temporary' and TEMPORARY_NAME.fullmatch(name) is not None
            if not eligible:
                preserved.append({'directory':directory,'name':name,'reason':'unknown_name'})
            elif path.is_symlink():
                raise RecoveryError('UNSAFE_STORE','An eligible orphan path is a symlink; no cleanup is allowed.')
            elif not path.is_file():
                preserved.append({'directory':directory,'name':name,'reason':'not_regular_file'})
            else:candidates.append({'directory':directory,'name':name,**_fingerprint(path)})
    report={'schemaVersion':1,'kind':'ontovis-offline-model-store-recovery','root':str(root),
        'scope':{'projectCode':scopes[0][2],'contextId':scopes[0][3],'libraryRevision':scopes[0][1]},
        'registered':{'count':len(registered),'totalBytes':sum(item['bytes'] for item in registered),
                      'fixedManifestSha256':hashlib.sha256(_canonical(registered)).hexdigest()},
        'candidates':candidates,'candidateCount':len(candidates),
        'candidateBytes':sum(item['bytes'] for item in candidates),'preserved':preserved,
        'businessDataChanged':False,'requiresOfflineServiceStopped':True,'deletionIsAtomic':False}
    report['reportSha256']=hashlib.sha256(_canonical(report)).hexdigest()
    return report


def preview(root):
    """Read only. In particular, do not invoke ModelLibrary.__init__."""
    root=_root(root);db=_connect(root,True)
    try:
        db.execute('begin')
        return _report(root,db)
    except sqlite3.Error as error:raise _database_error(error) from None
    except OSError:raise RecoveryError('STORE_CHANGED','The store changed during inspection; preview again.') from None
    finally:db.close()


def apply(root,expected_report_sha256,*,service_stopped=False):
    """Delete only a freshly reviewed candidate set while holding a DB write lock.

    BEGIN IMMEDIATE prevents a new version registration during cleanup. It
    cannot lock filesystem writers, so service_stopped is a required operator
    declaration. A filesystem failure can leave a subset deleted.
    """
    _require(service_stopped is True,'OFFLINE_REQUIRED','Stop the owning ONTOVis service and explicitly declare it stopped before applying cleanup.')
    _require(_sha(expected_report_sha256),'INVALID_REQUEST','The exact preview report SHA256 is required.')
    root=_root(root);db=_connect(root,False);removed=[]
    try:
        db.execute('begin immediate')
        report=_report(root,db)
        _require(report['reportSha256']==expected_report_sha256,'REPORT_CHANGED','The preview changed; no cleanup was started. Generate and review a new preview.')
        for item in report['candidates']:
            _require(_fingerprint(root/item['directory']/item['name'])=={'bytes':item['bytes'],'sha256':item['sha256']},
                     'REPORT_CHANGED','A candidate changed after the preview; no cleanup was started.')
        _root(root)
        for item in report['candidates']:
            os.unlink(root/item['directory']/item['name'])
            removed.append({'directory':item['directory'],'name':item['name']})
        for name in sorted({item['directory'] for item in removed}):
            descriptor=os.open(root/name,os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
        return {'state':'applied','reportSha256':expected_report_sha256,'registered':report['registered'],
                'removedCandidates':removed,'removedCount':len(removed),'removedBytes':report['candidateBytes'],
                'businessDataChanged':False,'deletionIsAtomic':False,'repreviewRequired':False}
    except sqlite3.Error as error:raise _database_error(error) from None
    except OSError:raise RecoveryError('RECOVERY_PARTIAL_FAILURE',
        'Filesystem cleanup did not finish. Deletions are not atomic; stop writers and generate a new preview before retrying.',removed=removed) from None
    finally:db.close()


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    read=commands.add_parser('preview');read.add_argument('--root',required=True,type=Path)
    write=commands.add_parser('apply');write.add_argument('--root',required=True,type=Path)
    write.add_argument('--expected-report-sha256',required=True)
    write.add_argument('--service-stopped',required=True,action='store_true')
    args=parser.parse_args(argv)
    try:
        result=preview(args.root) if args.command=='preview' else apply(args.root,args.expected_report_sha256,service_stopped=args.service_stopped)
        print(_canonical(result).decode());return 0
    except RecoveryError as error:print(_canonical(error.public()).decode());return 2


if __name__=='__main__':raise SystemExit(main())
