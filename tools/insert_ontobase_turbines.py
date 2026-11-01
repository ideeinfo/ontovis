import uuid
import json
import subprocess

turbines = [
    ('vestas-v105-3450', 'Vestas V105-3.45MW 风机工程定义', 'Vestas', 'vestas-v105-3450'),
    ('ge-3-2-103-corriemoillie', 'GE 3.2-103 风机工程定义', 'GE Renewable Energy', 'ge-3-2-103-corriemoillie'),
    ('nordex-n80-2500', 'Nordex N80-2500 风机工程定义', 'Nordex', 'nordex-n80-2500'),
    ('siemens-swt-2-3-82-crystal-rig', 'Siemens SWT 2.3-82 风机工程定义', 'Siemens', 'siemens-swt-2-3-82-crystal-rig'),
    ('ge-haliade-x-14mw', 'GE Haliade-X 14MW 风机工程定义', 'GE Renewable Energy', 'ge-haliade-x-14mw'),
    ('siemens-sg-8-0-167', 'Siemens Gamesa SG 8.0-167 风机工程定义', 'Siemens Gamesa', 'siemens-sg-8-0-167'),
    ('siemens-swt-2-3-93', 'Siemens SWT 2.3-93 风机工程定义', 'Siemens', 'siemens-swt-2-3-93'),
    ('myse-18-5-260', '明阳智能 MySE 18.5-260 风机工程定义', '明阳智能', 'myse-18-5-260'),
    ('mhi-vestas-v164-8-0', 'MHI Vestas V164-8.0MW 风机工程定义', 'MHI Vestas', 'mhi-vestas-v164-8-0'),
    ('siemens-swt-3-6-107', 'Siemens SWT 3.6-107 风机工程定义', 'Siemens', 'siemens-swt-3-6-107'),
    ('enercon-e-82-e2', 'Enercon E-82 E2 风机工程定义', 'Enercon', 'enercon-e-82-e2'),
    ('senvion-mm82', 'Senvion MM82 风机工程定义', 'Senvion', 'senvion-mm82'),
    ('nordex-n163-6x', 'Nordex N163/6.X 风机工程定义', 'Nordex', 'nordex-n163-6x'),
    ('siemens-sg-11-0-200-dd', 'Siemens Gamesa SG 11.0-200 DD 风机工程定义', 'Siemens Gamesa', 'siemens-sg-11-0-200-dd'),
    ('tu-22k', 'TU-22K 风机工程定义', 'ONTOVis Reference', 'tu-22k'),
    ('vestas-v182-7-2mw', 'Vestas V182-7.2MW 风机工程定义', 'Vestas', 'vestas-v182-7-2mw'),
    ('vestas-v80-2-0mw', 'Vestas V80-2.0MW 风机工程定义', 'Vestas', 'vestas-v80-2-0mw'),
    ('vestas-v90-3-0mw', 'Vestas V90-3.0MW 风机工程定义', 'Vestas', 'vestas-v90-3-0mw'),
    ('vestas-v136-4-5', 'Vestas V136-4.5MW 风机工程定义', 'Vestas', 'vestas-v136-4-5'),
]

sql_statements = []
for code, name, mfr, norm in turbines:
    u = 'entity:' + str(uuid.uuid5(uuid.NAMESPACE_DNS, 'turbine.demo-pds.' + code))
    props = json.dumps({
        'model_code': code,
        'manufacturer': mfr,
        'definition_basis': 'user_declared',
        'definition_key': code + '-shared-equipment',
        'creation_basis': f'{mfr} {code} 风机工程定义，用于项目风电场景三维数字孪生与构件装配。'
    }, ensure_ascii=False).replace("'", "''")
    escaped_name = name.replace("'", "''")
    sql = f"""
    INSERT INTO asset.entities (
        entity_uid, project_code, entity_type, display_name, normalized_local_id,
        review_status, properties, object_scope, entity_revision, entity_incarnation
    ) VALUES (
        '{u}', 'Demo-PDS', 'turbine', '{escaped_name}', '{norm}',
        'reviewed', '{props}'::jsonb, 'definition', 1, gen_random_uuid()
    ) ON CONFLICT (entity_uid) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        properties = EXCLUDED.properties,
        updated_at = now();
    """
    sql_statements.append(sql)

full_sql = 'BEGIN;\n' + '\n'.join(sql_statements) + '\nCOMMIT;'
cmd = ['docker', 'exec', '-i', 'ontobase-postgres', 'psql', '-U', 'ontobase', '-d', 'ontobase']
res = subprocess.run(cmd, input=full_sql.encode('utf-8'), capture_output=True)
print('STDOUT:', res.stdout.decode('utf-8'))
if res.stderr:
    print('STDERR:', res.stderr.decode('utf-8'))
