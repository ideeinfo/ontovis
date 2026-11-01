#!/usr/bin/env python3
"""Migrate project_model_assets table to add definition_entity_uid, model_code, and representation_type."""
import sqlite3
import sys
from pathlib import Path

MAPPINGS = {
    'E-82 E2 · 外观版': ('entity:dcd29706-c4ec-5710-886a-426a8b2407c3', 'enercon-e-82-e2', 'appearance'),
    'E-82 E2 · 完整版': ('entity:dcd29706-c4ec-5710-886a-426a8b2407c3', 'enercon-e-82-e2', 'detailed'),
    'MM82 · 外观版': ('entity:c488d4d1-cbe1-5995-8ef5-d156681b4b36', 'senvion-mm82', 'appearance'),
    'MM82 · 完整版': ('entity:c488d4d1-cbe1-5995-8ef5-d156681b4b36', 'senvion-mm82', 'detailed'),
    'MySE 18.5-260 · 外观版': ('entity:e0522383-1a80-5490-b254-933ef05b11d6', 'myse-18-5-260', 'appearance'),
    'MySE 18.5-260 · 完整版': ('entity:e0522383-1a80-5490-b254-933ef05b11d6', 'myse-18-5-260', 'detailed'),
    'N163/6.X · 外观版': ('entity:8e7d720e-f828-57c1-9764-1b8a5e981c3c', 'nordex-n163-6x', 'appearance'),
    'N163/6.X · 完整版': ('entity:8e7d720e-f828-57c1-9764-1b8a5e981c3c', 'nordex-n163-6x', 'detailed'),
    'SG 11.0-200 DD · 外观版': ('entity:350c6655-8220-578b-a22e-8252ec082291', 'siemens-sg-11-0-200-dd', 'appearance'),
    'SG 11.0-200 DD · 完整版': ('entity:350c6655-8220-578b-a22e-8252ec082291', 'siemens-sg-11-0-200-dd', 'detailed'),
    'TU-22K · 外观版': ('entity:fd1b8791-1a34-5e37-8ef4-512e466b10f0', 'tu-22k', 'appearance'),
    'TU-22K · 完整版': ('entity:fd1b8791-1a34-5e37-8ef4-512e466b10f0', 'tu-22k', 'detailed'),
    'TU-3000': ('entity:e0280f96-13cc-47b9-ae1e-4aaa2614a730', 'tu-3000', 'detailed'),
    'TU-3000 · 外观版': ('entity:e0280f96-13cc-47b9-ae1e-4aaa2614a730', 'tu-3000', 'appearance'),
    'V182-7.2 MW · 外观版': ('entity:d052dcdc-27b2-51d5-a000-c1cec8944aa5', 'vestas-v182-7-2mw', 'appearance'),
    'V182-7.2 MW · 完整版': ('entity:d052dcdc-27b2-51d5-a000-c1cec8944aa5', 'vestas-v182-7-2mw', 'detailed'),
    'V80-2.0 MW · 外观版': ('entity:106c1204-9c77-50da-877d-0a844414d98a', 'vestas-v80-2-0mw', 'appearance'),
    'V80-2.0 MW · 完整版': ('entity:106c1204-9c77-50da-877d-0a844414d98a', 'vestas-v80-2-0mw', 'detailed'),
    'V90-3.0 MW · 外观版': ('entity:048889cd-7d56-56b2-9781-25e37d6ff2ce', 'vestas-v90-3-0mw', 'appearance'),
    'V90-3.0 MW · 完整版': ('entity:048889cd-7d56-56b2-9781-25e37d6ff2ce', 'vestas-v90-3-0mw', 'detailed'),
    'ge-3-2-103-corriemoillie · 外观版': ('entity:b198b4db-4741-52df-bb16-cd46579f615c', 'ge-3-2-103-corriemoillie', 'appearance'),
    'ge-3-2-103-corriemoillie · 完整版': ('entity:b198b4db-4741-52df-bb16-cd46579f615c', 'ge-3-2-103-corriemoillie', 'detailed'),
    'ge-haliade-x-14mw · 外观版': ('entity:26097b0a-0705-5b07-8fa2-e2397f520007', 'ge-haliade-x-14mw', 'appearance'),
    'ge-haliade-x-14mw · 完整版': ('entity:26097b0a-0705-5b07-8fa2-e2397f520007', 'ge-haliade-x-14mw', 'detailed'),
    'mhi-vestas-v164-8-0 · 外观版': ('entity:602a2334-1801-5c1e-8319-75a650682722', 'mhi-vestas-v164-8-0', 'appearance'),
    'mhi-vestas-v164-8-0 · 完整版': ('entity:602a2334-1801-5c1e-8319-75a650682722', 'mhi-vestas-v164-8-0', 'detailed'),
    'nordex-n80-2500 · 外观版': ('entity:acc6ff48-828f-5455-a082-46bc06fd4090', 'nordex-n80-2500', 'appearance'),
    'nordex-n80-2500 · 完整版': ('entity:acc6ff48-828f-5455-a082-46bc06fd4090', 'nordex-n80-2500', 'detailed'),
    'siemens-sg-8-0-167 · 外观版': ('entity:fcab8673-d361-5e64-9c70-c9acb548518f', 'siemens-sg-8-0-167', 'appearance'),
    'siemens-sg-8-0-167 · 完整版': ('entity:fcab8673-d361-5e64-9c70-c9acb548518f', 'siemens-sg-8-0-167', 'detailed'),
    'siemens-swt-2-3-82-crystal-rig · 外观版': ('entity:ae3877aa-7ef9-50de-b555-54356d8aa80b', 'siemens-swt-2-3-82-crystal-rig', 'appearance'),
    'siemens-swt-2-3-82-crystal-rig · 完整版': ('entity:ae3877aa-7ef9-50de-b555-54356d8aa80b', 'siemens-swt-2-3-82-crystal-rig', 'detailed'),
    'siemens-swt-2-3-93 · 外观版': ('entity:f95b67e1-b5d5-59c6-91c8-f80df6c65a65', 'siemens-swt-2-3-93', 'appearance'),
    'siemens-swt-2-3-93 · 完整版': ('entity:f95b67e1-b5d5-59c6-91c8-f80df6c65a65', 'siemens-swt-2-3-93', 'detailed'),
    'siemens-swt-3-6-107 · 外观版': ('entity:221dbbed-8ac0-5fd9-8fee-a5c541b2697e', 'siemens-swt-3-6-107', 'appearance'),
    'siemens-swt-3-6-107 · 完整版': ('entity:221dbbed-8ac0-5fd9-8fee-a5c541b2697e', 'siemens-swt-3-6-107', 'detailed'),
    'vestas-v105-3450 · 外观版': ('entity:ee6b36b1-b7e7-5ba6-a8be-f93a5a68717f', 'vestas-v105-3450', 'appearance'),
    'vestas-v105-3450 · 完整版': ('entity:ee6b36b1-b7e7-5ba6-a8be-f93a5a68717f', 'vestas-v105-3450', 'detailed'),
    'vestas-v136-4-5 · 外观版': ('entity:8d7d8ce0-17ce-5490-bbd7-8660c5f8f2e9', 'vestas-v136-4-5', 'appearance'),
    'vestas-v136-4-5 · 完整版': ('entity:8d7d8ce0-17ce-5490-bbd7-8660c5f8f2e9', 'vestas-v136-4-5', 'detailed'),
}

def migrate(db_path: str):
    con = sqlite3.connect(db_path)
    cur = con.cursor()
    # Check existing columns in project_model_assets
    cols = [r[1] for r in cur.execute("PRAGMA table_info(project_model_assets)").fetchall()]
    print(f"[{db_path}] Current columns: {cols}")
    
    if 'definition_entity_uid' not in cols:
        print(f"[{db_path}] Adding column definition_entity_uid...")
        cur.execute("ALTER TABLE project_model_assets ADD COLUMN definition_entity_uid text")
    if 'model_code' not in cols:
        print(f"[{db_path}] Adding column model_code...")
        cur.execute("ALTER TABLE project_model_assets ADD COLUMN model_code text")
    if 'representation_type' not in cols:
        print(f"[{db_path}] Adding column representation_type text...")
        cur.execute("ALTER TABLE project_model_assets ADD COLUMN representation_type text")

    # Update mapped assets
    updated_count = 0
    for name, (def_uid, code, rep_type) in MAPPINGS.items():
        res = cur.execute("""
            UPDATE project_model_assets
            SET definition_entity_uid = ?, model_code = ?, representation_type = ?
            WHERE name = ?
        """, (def_uid, code, rep_type, name))
        if res.rowcount > 0:
            updated_count += res.rowcount

    con.commit()
    print(f"[{db_path}] Successfully mapped {updated_count} assets to OntoBase turbine definitions!")
    con.close()

if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else '/data/ontovis/private/workbench-pg-v1/workbench-library/library.sqlite3'
    migrate(target)
