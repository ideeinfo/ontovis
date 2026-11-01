#!/usr/bin/env python3
"""Synchronize the 20 real turbine models into OntoBase equipment specifications, revisions and entities."""
import uuid
import json
import subprocess

REAL_TURBINES = [
    {
        'code': 'enercon-e-82-e2',
        'mfr': 'Enercon',
        'name': 'Enercon E-82 E2 2.0MW 风机',
        'power_kw': 2050,
        'hub_height_m': 78,
        'rotor_diameter_m': 82,
        'kind': 'onshore'
    },
    {
        'code': 'ge-3-2-103-corriemoillie',
        'mfr': 'GE Renewable Energy',
        'name': 'GE 3.2-103 3.2MW 风机',
        'power_kw': 3200,
        'hub_height_m': 85,
        'rotor_diameter_m': 103,
        'kind': 'onshore'
    },
    {
        'code': 'ge-haliade-x-14mw',
        'mfr': 'GE Renewable Energy',
        'name': 'GE Haliade-X 14MW 海上风机',
        'power_kw': 14000,
        'hub_height_m': 150,
        'rotor_diameter_m': 220,
        'kind': 'offshore'
    },
    {
        'code': 'mhi-vestas-v164-8-0',
        'mfr': 'MHI Vestas Offshore Wind',
        'name': 'MHI Vestas V164-8.0MW 海上风机',
        'power_kw': 8000,
        'hub_height_m': 105,
        'rotor_diameter_m': 164,
        'kind': 'offshore'
    },
    {
        'code': 'myse-18-5-260',
        'mfr': '明阳智能',
        'name': '明阳智能 MySE 18.5-260 海上超大型风机',
        'power_kw': 18500,
        'hub_height_m': 160,
        'rotor_diameter_m': 260,
        'kind': 'offshore'
    },
    {
        'code': 'nordex-n163-6x',
        'mfr': 'Nordex',
        'name': 'Nordex N163/6.X 6.0MW 风机',
        'power_kw': 6000,
        'hub_height_m': 118,
        'rotor_diameter_m': 163,
        'kind': 'onshore'
    },
    {
        'code': 'nordex-n80-2500',
        'mfr': 'Nordex',
        'name': 'Nordex N80-2500 2.5MW 风机',
        'power_kw': 2500,
        'hub_height_m': 80,
        'rotor_diameter_m': 80,
        'kind': 'onshore'
    },
    {
        'code': 'senvion-mm82',
        'mfr': 'Senvion',
        'name': 'Senvion MM82 2.05MW 风机',
        'power_kw': 2050,
        'hub_height_m': 80,
        'rotor_diameter_m': 82,
        'kind': 'onshore'
    },
    {
        'code': 'siemens-sg-11-0-200-dd',
        'mfr': 'Siemens Gamesa',
        'name': 'Siemens Gamesa SG 11.0-200 DD 直驱海上风机',
        'power_kw': 11000,
        'hub_height_m': 140,
        'rotor_diameter_m': 200,
        'kind': 'offshore'
    },
    {
        'code': 'siemens-sg-8-0-167',
        'mfr': 'Siemens Gamesa',
        'name': 'Siemens Gamesa SG 8.0-167 DD 海上风机',
        'power_kw': 8000,
        'hub_height_m': 115,
        'rotor_diameter_m': 167,
        'kind': 'offshore'
    },
    {
        'code': 'siemens-swt-2-3-82-crystal-rig',
        'mfr': 'Siemens',
        'name': 'Siemens SWT 2.3-82 2.3MW 风机',
        'power_kw': 2300,
        'hub_height_m': 80,
        'rotor_diameter_m': 82,
        'kind': 'onshore'
    },
    {
        'code': 'siemens-swt-2-3-93',
        'mfr': 'Siemens',
        'name': 'Siemens SWT 2.3-93 2.3MW 风机',
        'power_kw': 2300,
        'hub_height_m': 80,
        'rotor_diameter_m': 93,
        'kind': 'onshore'
    },
    {
        'code': 'siemens-swt-3-6-107',
        'mfr': 'Siemens',
        'name': 'Siemens SWT 3.6-107 3.6MW 风机',
        'power_kw': 3600,
        'hub_height_m': 90,
        'rotor_diameter_m': 107,
        'kind': 'onshore'
    },
    {
        'code': 'tu-22k',
        'mfr': 'ONTOVis Reference',
        'name': 'TU-22K 22MW 概念超大风机',
        'power_kw': 22000,
        'hub_height_m': 170,
        'rotor_diameter_m': 270,
        'kind': 'offshore'
    },
    {
        'code': 'tu-3000',
        'mfr': 'TerraUrsa',
        'name': 'TU-3000 3.0MW 风机工程定义',
        'power_kw': 3000,
        'hub_height_m': 90,
        'rotor_diameter_m': 115,
        'kind': 'onshore'
    },
    {
        'code': 'vestas-v105-3450',
        'mfr': 'Vestas',
        'name': 'Vestas V105-3.45MW 风机',
        'power_kw': 3450,
        'hub_height_m': 84,
        'rotor_diameter_m': 105,
        'kind': 'onshore'
    },
    {
        'code': 'vestas-v136-4-5',
        'mfr': 'Vestas',
        'name': 'Vestas V136-4.5MW 风机',
        'power_kw': 4500,
        'hub_height_m': 112,
        'rotor_diameter_m': 136,
        'kind': 'onshore'
    },
    {
        'code': 'vestas-v182-7-2mw',
        'mfr': 'Vestas',
        'name': 'Vestas V182-7.2MW 海上风机',
        'power_kw': 7200,
        'hub_height_m': 120,
        'rotor_diameter_m': 182,
        'kind': 'offshore'
    },
    {
        'code': 'vestas-v80-2-0mw',
        'mfr': 'Vestas',
        'name': 'Vestas V80-2.0MW 风机',
        'power_kw': 2000,
        'hub_height_m': 67,
        'rotor_diameter_m': 80,
        'kind': 'onshore'
    },
    {
        'code': 'vestas-v90-3-0mw',
        'mfr': 'Vestas',
        'name': 'Vestas V90-3.0MW 风机',
        'power_kw': 3000,
        'hub_height_m': 80,
        'rotor_diameter_m': 90,
        'kind': 'onshore'
    }
]

CLASSIFICATION_REV_ID = 'f2eb359c-e4fa-492f-be32-f3a01c14ada6'
TEMPLATE_REV_ID = '939b1d28-ee75-4fcb-aec4-adde6260865f'
CREATED_BY = '5faeef88-195e-4099-af1b-884ae9fda30a'

sql_parts = ['BEGIN;']

for t in REAL_TURBINES:
    code = t['code']
    mfr = t['mfr']
    name = t['name']
    power = t['power_kw']
    hub = t['hub_height_m']
    rotor = t['rotor_diameter_m']

    # 1. Update asset.entities
    entity_uid = 'entity:' + str(uuid.uuid5(uuid.NAMESPACE_DNS, 'turbine.demo-pds.' + code))
    props = json.dumps({
        'model_code': code,
        'manufacturer': mfr,
        'model_name': name,
        'rated_power_kw': power,
        'hub_height_m': hub,
        'rotor_diameter_m': rotor,
        'kind': t['kind'],
        'definition_basis': 'user_declared',
        'definition_key': f'{code}-shared-equipment',
        'creation_basis': f'{mfr} {code} 风电机组工程定义，支持三维孪生装配、透视与包围盒爆炸。'
    }, ensure_ascii=False).replace("'", "''")

    sql_parts.append(f"""
    INSERT INTO asset.entities (
        entity_uid, project_code, entity_type, display_name, normalized_local_id,
        review_status, properties, object_scope, entity_revision, entity_incarnation
    ) VALUES (
        '{entity_uid}', 'Demo-PDS', 'turbine', '{name.replace("'", "''")}', '{code}',
        'reviewed', '{props}'::jsonb, 'definition', 1, gen_random_uuid()
    ) ON CONFLICT (entity_uid) DO UPDATE SET
        display_name = EXCLUDED.display_name,
        properties = EXCLUDED.properties,
        updated_at = now();
    """)

    # 2. System equipment specification
    spec_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'spec.' + code))
    rev_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'spec.rev.' + code))
    spec_code = code.upper()

    snapshot = json.dumps({
        'productCode': spec_code,
        'manufacturer': mfr,
        'objectKind': 'turbine',
        'displayName': name,
        'ratedPowerKw': power,
        'hubHeightM': hub,
        'rotorDiameterM': rotor,
        'classificationRef': {'code': 'WIND', 'revisionId': CLASSIFICATION_REV_ID},
        'templateRevisionId': TEMPLATE_REV_ID,
        'properties': [
            {'propertyKey': 'ob.wind.rated_power', 'value': power, 'unit': 'kW', 'status': 'known'},
            {'propertyKey': 'ob.wind.rotor_diameter', 'value': rotor, 'unit': 'm', 'status': 'known'},
            {'propertyKey': 'ob.wind.hub_height', 'value': hub, 'unit': 'm', 'status': 'known'},
            {'propertyKey': 'ob.product.manufacturer', 'value': mfr, 'unit': None, 'status': 'known'}
        ]
    }, ensure_ascii=False).replace("'", "''")

    basis = f'风机机型规格主数据：{mfr} {name}，额定功率 {power}kW，叶轮直径 {rotor}m，轮毂高度 {hub}m。'.replace("'", "''")

    sql_parts.append(f"""
    INSERT INTO system.equipment_specifications (id, code, status, row_version, head_revision_id, created_at)
    VALUES ('{spec_id}', '{spec_code}', 'active', 1, '{rev_id}', now())
    ON CONFLICT (id) DO UPDATE SET
        head_revision_id = EXCLUDED.head_revision_id;

    INSERT INTO system.equipment_specification_revisions (
        id, specification_id, revision, classification_revision_id, classification_code,
        template_revision_id, snapshot, basis, created_by, created_at
    ) VALUES (
        '{rev_id}', '{spec_id}', 1, '{CLASSIFICATION_REV_ID}', 'WIND',
        '{TEMPLATE_REV_ID}', '{snapshot}'::jsonb, '{basis}', '{CREATED_BY}', now()
    ) ON CONFLICT (id) DO UPDATE SET
        snapshot = EXCLUDED.snapshot,
        basis = EXCLUDED.basis;
    """)

sql_parts.append('COMMIT;')
full_sql = '\n'.join(sql_parts)

cmd = ['docker', 'exec', '-i', 'ontobase-postgres', 'psql', '-U', 'ontobase', '-d', 'ontobase']
res = subprocess.run(cmd, input=full_sql.encode('utf-8'), capture_output=True)
print('STDOUT:', res.stdout.decode('utf-8'))
if res.stderr:
    print('STDERR:', res.stderr.decode('utf-8'))
