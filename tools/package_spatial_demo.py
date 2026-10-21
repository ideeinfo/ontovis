#!/usr/bin/env python3
"""Package the approved Xiali spatial demo without local engineering records."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import tempfile


FILES = (
    'index.html', 'app.js', 'styles.css', 'authority-preview.js',
    'turbine-objects.js', 'environment.js', 'globe-catalog.js',
    'assets/ONTOVis.png', 'assets/environment/stars.svg',
    'assets/models/tu3000-exterior-lod.glb', 'assets/models/tu3000-geared-merged.glb',
    'assets/textures/grass-diff.jpg', 'assets/textures/grass-nor_gl.jpg',
    'assets/vendor/maplibre-gl.js', 'assets/vendor/maplibre-gl.css',
    'assets/vendor/maplibre-LICENSE.txt', 'assets/vendor/three.module.js',
    'assets/vendor/three.core.js', 'assets/vendor/three-LICENSE.txt',
    'assets/vendor/addons/loaders/GLTFLoader.js',
    'assets/vendor/addons/utils/BufferGeometryUtils.js',
    'assets/vendor/addons/utils/SkeletonUtils.js',
    'data/terrain/grid.json', 'data/turbines.geojson', 'data/turbines.csv',
    'data/turbine-template.json', 'data/interior-tour.json',
    'data/global-wind.geojson', 'data/map/world.geojson', 'data/land.geojson',
    'sources/global-wind-provenance.json', 'sources/basemap-provenance.json',
    'sources/GEM-data-attribution.md', 'sources/terrain-COPDEM-30-license.pdf',
)
PRIVATE_PATH = re.compile(rb'/Users/|/data/ontobase|192\.168\.\d+\.\d+|-----BEGIN [A-Z ]*PRIVATE KEY-----')
PUBLIC_README = '''# ONTOVis 空间导航测试

在同一视口体验全球风电目录、夏李山地风场、机组及内部构件。可调整模拟转速和偏航，连续导览包含六个构件和风场远眺；未连接监测或现场控制。

全球35,089个GEM分期点不是独立风场数。夏李显示1–18及B1共19个图示机位；公开项目18台/48MW与B1的关系待核。机位为图像配准估计，100m范围是演示提示，不能作测量精度。Copernicus GLO-30为真实DSM，EGM2008正高、原始高程1倍；草地为示意材质。

TU-3000为通用教学模型，三柜/安装位置未经现场核实。模型仅按权利人授权用于本测试站点，未声明开放许可；授权状态见[记录](sources/model-authorization.json)。请勿据此推定获得模型再使用许可。

本站只提供空间演示，工程服务未连接；工程身份与资料须经逐用户项目授权，正式工程发布保持阻断。来源见[来源与许可](SOURCES.md)，许可证随包保留；无分析或遥测采集。
'''
SOURCES = '''# 来源与许可

- 全球风电：GEM GWPT 2026年2月官方公开地图，35,089个分期点、28,447个源项目ID。[处理/版本](sources/global-wind-provenance.json)、[署名与许可](sources/GEM-data-attribution.md)。
- 全球概览地图：Natural Earth公共领域数据。[图层来源](sources/basemap-provenance.json)。
- 地形：Copernicus GLO-30 2021公开镜像，DSM，EGM2008正高。produced using Copernicus WorldDEM-30 © DLR e.V. 2010-2014 and © Airbus Defence and Space GmbH 2014-2018 provided under COPERNICUS by the European Union and ESA; all rights reserved. [许可原文](sources/terrain-COPDEM-30-license.pdf)。
- 草地：Poly Haven Leafy Grass，Charlotte Baglioni，CC0。https://polyhaven.com/a/leafy_grass ，https://polyhaven.com/license 。
- 机位：用户正式图的配准估计，[定位与限制](sources/locations-readme.md)；原图和参考影像不随包提供。
- 模型：TerraUrsa TU-3000教学模型，[用途/授权声明](assets/models/README.md)。
- 运行库：MapLibre GL JS BSD-3-Clause、Three.js MIT，许可保留于assets/vendor/。
'''
LOCATION_README = '''# 机位与精度

按用户正式平面图配准，显示1–18和B1共19个图示机位。24个控制点的图像配准RMSE约3.31m、留一RMSE约3.83m；这些不是实测机位误差。源图编号已确认，测量位置/坐标系和现场设备身份未核实。100m圈仅为演示提示。

公开历史项目口径18台/48MW，B1归属待核。模型、工程身份和GEM目录点不自动合并；原始图纸和参考商业影像不在公开包中。
'''
MODEL_README = '''# TU-3000 测试模型

TerraUrsa TU-3000通用教学模型，来源 https://terraursa.com/wind-lab/turbines/tu-3000.html 。保留外观实例与单台近景派生GLB，米制、Y向上；不是夏李实际机型或竣工模型。

2026-10-21用户确认已有本模型公网使用/再分发授权，并选择保留现有模型；授权依据文档待其补充。此为用户授权声明记录，不将素材声明为开源；不包含原始附件或授予访问者再使用权。见[授权记录](../../sources/model-authorization.json)。

CT/CN1为示意代理，CN为controller源候选；构件可视化不确认现场工程身份。机组转速/偏航均为演示参数。
'''


def package(source: Path, output: Path, authorization_basis: str, *, user_sessions: bool = False) -> dict:
    source, output = source.resolve(), output.absolute()
    basis = authorization_basis.strip()
    if not basis or len(basis) > 2000 or PRIVATE_PATH.search(basis.encode()):
        raise ValueError('A non-secret model authorization basis is required')
    if output.exists():
        raise FileExistsError('Refusing to replace an existing package')
    payloads = {}
    for relative in FILES:
        file = source/relative
        if not file.is_file() or file.is_symlink() or not file.resolve().is_relative_to(source):
            raise ValueError('Missing or unsafe approved file: '+relative)
        data = file.read_bytes()
        if PRIVATE_PATH.search(data):
            raise ValueError('Local/private path in approved file: '+relative)
        payloads[relative] = data
    replacements = {
        'index.html': [('本机数据包', '测试数据包')],
        'app.js': [('正在准备本机地形与机组外观', '正在准备地形与机组外观'),
                   ('本机研究预览', '测试演示'), ('地图和文字资源均在本机', '地图和文字资源均随测试包提供')],
        'authority-preview.js': [('本机登录会话尚未启动。此页没有可读取的安装对象。',
                                 '工程服务尚未连接。空间演示可继续使用；工程对象需逐用户授权。')],
    }
    for relative, rows in replacements.items():
        text = payloads[relative].decode()
        for before, after in rows:
            text = text.replace(before, after)
        payloads[relative] = text.encode()
    if user_sessions:
        maintained = Path(__file__).resolve().parents[1]/'apps/web'
        for name in ('authority-preview.js','session.js','session.css'):
            data = (maintained/name).read_bytes()
            if PRIVATE_PATH.search(data): raise ValueError('Private path in session module')
            payloads[name] = data
        payloads['index.html'] = payloads['index.html'].replace(
            b'<link rel="stylesheet" href="./styles.css">',
            b'<link rel="stylesheet" href="./styles.css"><link rel="stylesheet" href="./session.css">')
    template = json.loads(payloads['data/turbine-template.json'])
    template['purpose'] = 'public test visualization only; not engineering binding'
    payloads['data/turbine-template.json'] = (json.dumps(template,ensure_ascii=False,indent=2)+'\n').encode()
    authorization = {
        'model': 'TerraUrsa TU-3000', 'assertedAt': '2026-10-21',
        'basis': basis, 'evidenceStatus': 'user_statement_recorded_reference_pending',
        'scope': 'approved_public_test_demo', 'openLicenseClaimed': False,
        'artifacts': {name:hashlib.sha256(payloads[name]).hexdigest() for name in FILES if name.endswith('.glb')},
    }
    payloads.update({
        'README.md':PUBLIC_README.encode(),
        'SOURCES.md':SOURCES.encode(),
        'sources/locations-readme.md':LOCATION_README.encode(),
        'assets/models/README.md':MODEL_README.encode(),
        'sources/model-authorization.json':(json.dumps(authorization,ensure_ascii=False,indent=2)+'\n').encode(),
        'robots.txt':b'User-agent: *\nDisallow: /\n',
    })
    locations = json.loads(payloads['data/turbines.geojson'])
    metadata = locations.get('metadata', {})
    if 'currentTurbineCount' in metadata:
        count = metadata['currentTurbineCount']
        if type(count) is not int or count != len(locations['features']):
            raise ValueError('Current turbine count does not match runtime data')
        excluded = '、'.join(metadata.get('excludedPlanLabels', []))
        summary = f'当前保留{count}个图示机位；核减编号为{excluded}。原图19个符号和历史18台/48MW口径分别保留，当前容量待核。'
        payloads['README.md'] = payloads['README.md'].replace(
            '夏李显示1–18及B1共19个图示机位；公开项目18台/48MW与B1的关系待核。'.encode(), summary.encode())
        payloads['sources/locations-readme.md'] = payloads['sources/locations-readme.md'].replace(
            '按用户正式平面图配准，显示1–18和B1共19个图示机位。'.encode(), ('按用户正式平面图配准。'+summary).encode()).replace(
            '公开历史项目口径18台/48MW，B1归属待核。'.encode(), '公开历史项目口径18台/48MW不作为当前数量和容量。'.encode())
    if user_sessions:
        payloads['README.md'] = payloads['README.md'].replace(
            '本站只提供空间演示，工程服务未连接；工程身份与资料须经逐用户项目授权，正式工程发布保持阻断。'.encode(),
            '空间演示公开可用。工程对象须本人登录并取得项目权限，首批仅读取7号五个演示安装对象；正式工程发布保持阻断，不开放资料原文或设备控制。'.encode())
    manifest = {'schemaVersion':1,'purpose':'public_spatial_demo', 'engineeringServiceConnected':False,
                'files':{name:{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()} for name,data in sorted(payloads.items())}}
    if user_sessions: manifest['engineeringSessionMode'] = 'per_user'
    manifest['releaseId'] = hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()[:16]
    payloads['release.json'] = (json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    work = output.parent/'_work'
    work.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=work,prefix='package-') as temporary:
        stage = Path(temporary)/'bundle'
        stage.mkdir()
        for relative,data in payloads.items():
            target = stage/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
        if output.exists():
            raise FileExistsError('Refusing to replace an existing package')
        stage.rename(output)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--model-authorization-basis',required=True)
    parser.add_argument('--with-user-sessions',action='store_true')
    args = parser.parse_args()
    try:
        result = package(args.source,args.output,args.model_authorization_basis,user_sessions=args.with_user_sessions)
    except (OSError,ValueError) as error:
        parser.exit(1,str(error)+'\n')
    print(json.dumps({'releaseId':result['releaseId'],'files':len(result['files'])+1,
                      'bytes':sum(row['bytes'] for row in result['files'].values()),
                      'engineeringServiceConnected':False}))


if __name__ == '__main__':
    main()
