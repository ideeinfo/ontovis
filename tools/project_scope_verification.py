"""Read-only proof that adding project ownership retained all original business rows."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3


def verify_legacy_scope_upgrade(original_library, current_library):
    def connect(root):
        db = sqlite3.connect((Path(root) / 'library.sqlite3').as_uri() + '?mode=ro', uri=True)
        db.execute('pragma query_only=on')
        return db

    def columns(db, table):
        return [row[1] for row in db.execute('pragma table_info("' + table.replace('"', '""') + '")')]

    def rows(db, table, names):
        quoted = ','.join('"' + name.replace('"', '""') + '"' for name in names)
        values = db.execute('select ' + quoted + ' from "' + table.replace('"', '""') + '"')
        return sorted(json.dumps([(type(v).__name__, v.hex() if isinstance(v, bytes) else v) for v in row],
                                 ensure_ascii=False, separators=(',', ':')) for row in values)

    with closing(connect(original_library)) as before, closing(connect(current_library)) as after:
        for db in (before, after):
            if db.execute('pragma quick_check').fetchall() != [('ok',)] or db.execute('pragma foreign_key_check').fetchone():
                raise ValueError('INVALID_PROJECT_STORE')
        old = {row[0] for row in before.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
        new = {row[0] for row in after.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")}
        if new - old - {'workspace_scope'} or old - new:
            raise ValueError('UNEXPECTED_SCHEMA_CHANGE')
        counts = {}
        for table in old:
            names = columns(before, table)
            actual = columns(after, table)
            if actual != names and not (table == 'scenes' and actual == names + ['workspace_id']):
                raise ValueError('ORIGINAL_COLUMNS_CHANGED')
            initial, current = rows(before, table, names), rows(after, table, names)
            if initial != current:
                raise ValueError('ORIGINAL_BUSINESS_ROWS_CHANGED_' + table)
            counts[table] = len(initial)
        scope = after.execute('select workspace_id,ontobase_connection_id,project_code from workspace_scope where id=1').fetchone()
        if not scope or after.execute('select 1 from scenes where workspace_id is null or workspace_id!=? or project_code!=? limit 1',
                                      (scope[0], scope[2])).fetchone():
            raise ValueError('SCENE_SCOPE_MISMATCH')
        return {'originalTablesPreserved': len(old), 'originalTableCounts': counts,
                'scopeTableAdded': 'workspace_scope' not in old, 'originalBusinessRowsPreserved': True,
                'retainedSceneRevisions': counts['scene_revisions'], 'sceneCount': counts['scenes'],
                'retainedInstanceIds': counts['scene_instance_ids']}
