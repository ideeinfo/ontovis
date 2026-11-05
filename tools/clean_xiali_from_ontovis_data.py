#!/usr/bin/env python3
"""Clean '夏李' from ONTOVis database."""
import os, sys, shutil, sqlite3, re
from datetime import datetime
from pathlib import Path

def clean_text(t: str) -> str:
    if not t:
        return t
    t = t.replace('夏李 · Copernicus GLO-30 DSM', 'Copernicus GLO-30 DSM')
    t = t.replace('夏李 · Sentinel-2', 'Sentinel-2')
    t = t.replace('夏李 · 公开影像概览', '公开影像概览')
    t = t.replace('夏李 · 公开参考中心', '公开参考中心')
    t = t.replace('平顶山夏李风电场', '平顶山风电场')
    t = t.replace('平顶山夏李', '平顶山')
    t = t.replace('夏李项目配置', '本源项目配置')
    t = t.replace('夏李风机', '本源风机')
    t = re.sub(r'夏李(\d+)号', r'本源\1号', t)
    t = t.replace('夏李7号', '本源7号')
    t = t.replace('夏李', '本源')
    return t

def clean_database(db_path: Path):
    if not db_path.exists():
        print(f"File not found: {db_path}")
        return

    # Backup
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    bak_path = db_path.with_name(f"{db_path.name}.bak_{timestamp}")
    shutil.copy2(db_path, bak_path)
    print(f"Backed up {db_path} to {bak_path}")

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [r[0] for r in cur.fetchall()]

    updated_count = 0
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in cur.fetchall()]
        for c in cols:
            try:
                cur.execute(f"SELECT rowid, {c} FROM {t} WHERE {c} LIKE '%夏李%'")
                rows = cur.fetchall()
                if rows:
                    for rowid, val in rows:
                        new_val = clean_text(val)
                        cur.execute(f"UPDATE {t} SET {c}=? WHERE rowid=?", (new_val, rowid))
                        updated_count += 1
                    print(f"Table {t}, column {c}: updated {len(rows)} rows")
            except Exception as e:
                pass

    conn.commit()
    print(f"Total updated fields in {db_path}: {updated_count}")

    # Verify
    remaining = 0
    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = [r[1] for r in cur.fetchall()]
        for c in cols:
            try:
                cur.execute(f"SELECT count(*) FROM {t} WHERE {c} LIKE '%夏李%'")
                cnt = cur.fetchone()[0]
                if cnt > 0:
                    print(f"WARNING: Table {t}, column {c} still has {cnt} rows containing '夏李'")
                    remaining += cnt
            except Exception:
                pass

    conn.close()
    if remaining == 0:
        print(f"SUCCESS: 0 '夏李' remaining in {db_path}!")
    else:
        print(f"FAILED: {remaining} occurrences still remain in {db_path}!")

if __name__ == '__main__':
    targets = [
        Path('/data/ontovis/private/workbench-pg-v1/workbench-library/library.sqlite3'),
        Path('/data/ontovis/private/workbench-library/library.sqlite3')
    ]
    if len(sys.argv) > 1:
        targets = [Path(p) for p in sys.argv[1:]]
    for target in targets:
        clean_database(target)
