# 本机开发与核验工具

## 风场目录采集

在ONTOVis根目录执行：

```bash
python3 -m unittest discover -s tests -v
python3 tools/wind_catalog.py --output output/wind-catalog-20261027/batch-01
```

只从固定官方EMODnet WFS与REPD发布页读取。新输出目录不能已存在；成功产生`manifest.json`、`catalog.sqlite`、`observations.jsonl`与`raw/`；失败非零退出并标记failed，不替换旧数据。输出受`.gitignore`排除。

详见[采集设计](../docs/design/风场数据库与数据采集设计.md)。当前未实现GEM文件导入、跨源去重、REPD坐标转换、生产服务和调度。来源观测不等于唯一风场，不修改OntoBase工程数据。

## PREP-02 模型只读核验

`model_probe.py`用于开发计划的模型属性/坐标/映射准备；只读本机输入，不上传文件、不请求外部URI、不改写源模型。仅使用Python标准库。

在仓库根目录运行定向测试和现有样本检查，`--output`必须是尚不存在的新目录：

```bash
python3 -m unittest discover -s tests -p 'test_model_probe.py' -v
python3 tools/model_probe.py \
  --source output/xiali-spatial-demo-20261020/assets/models/tu3000-geared-original.glb \
  --derived output/xiali-spatial-demo-20261020/assets/models/tu3000-geared-merged.glb \
  --mapping output/xiali-spatial-demo-20261020/sources/models-tu3000-geared-merged-mapping.json \
  --output output/development-start-20261021/model-audit-final
```

可用`--source-sha256`、`--derived-sha256`传入已有参考指纹；不相符会失败。输出`report.json`和版本内节点目录`components.json`；全量映射比对通过时另产出`mapping-checked.json`，同时固定源/派生SHA256。已有旧sidecar只绑定源指纹的事实保留在报告中，不修改原sidecar。

Q-09增补的报告为schemaVersion 2，目录保留每个节点的原始`sourceExtras`及是否存在该字段，区分身份缺失、残缺、格式错误和重复。目录实际字节的SHA256写入报告。来源属性保持原始JSON类型，不读取属性内的URI；其中身份仍是未核实声明。详见[属性与身份切片](../docs/plans/模型属性与源身份核验切片.md)。

两版来源文件可用`--previous-source`及可选`--previous-source-sha256`比较；后者不能单独使用。当前版仍由`--source`及`--source-sha256`指定。技术检查通过时另输出`identity-candidates.json`，固定双方SHA256，精确比较`sourceModelKey/sourceElementId/placementId`原值；双方唯一且在默认场景的声明才列为待审阅候选，重复、非活动、仅前版/仅当前版和无完整声明分别保留。`propertiesChanged`提示原始extras差异，布尔与数字不会混同。

名称、旧ObjectID及节点索引不补作源身份；大小写和空白不自动规范化。缺身份时零候选是有效的检查结果。候选不确认几何对应或工程绑定，`sourceIdentityVerified`、`geometryCorrespondenceVerified`及`bindingMigrationApproved`保持false。现有完整/外观表示的比较只证明声明可用性，不充当真实连续版本验收。

核验范围：GLB2结构、嵌入资源、有限数值、节点父变换、实际顶点包络、源/派生全量三角形位置与版本内属性对应。所有`componentKey`都包含制品指纹和节点索引，只在该制品版本内有效；旧`sourceObjectId`、名称或未经核实的`extras.ontoVis`声明不会升级成工程身份或已验证跨版ID。模型父子只用于计算几何变换，不是设备安装树。

当前仅支持选定默认场景的静态未压缩TRIANGLES、float POSITION与常规索引。稀疏/矩阵accessor、蒙皮、形变、必需扩展/压缩解码、节点扩展及data URI明确拒绝；这是本工具范围，不能据此把所有这些合法glTF特性判成坏模型。工具不代替[Khronos glTF规范与完整校验](https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html)、材质/法线/UV或浏览器拾取验证。200MB仅为本机读取预算，不是已冻结的生产上传/内存/CPU限额。

可另传`--control-points <本机JSON>`检查源模型的局部参考点。JSON需含`modelSha256`、`units:"m"`、非空`basis`、正有限`toleranceMetres`和至少三个`points`；前三个参考点需非共线，每项含唯一`id`、`nodeIndex`、`primitiveIndex`（默认0）、`vertexIndex`、`expected:[x,y,z]`。参考点需指向同一源制品；缺输入为`not_provided`，偏差超限则失败、退出码1。合成点只验证算法，真实点的来源权威、现场变换与用途容差仍需审核。

成功退出码0只表示本工具范围内技术检查通过；结构/映射/控制点错误退出码1并保存failed报告，绝不覆盖已有输出。所有结果的`releaseReadiness.eligible`和`G2Passed`仍为false：工程UID/物理链、现场控制点、许可及评审不由该工具确认。实际结果与下一步见[开发执行记录](../docs/plans/开发执行记录.md)。

## 本机批量模型核验与恢复

[model_probe_batch.py](model_probe_batch.py)逐文件调用上述源模型核验，提供私有检查点、JSON行进度、取消和中断恢复。输入清单必须预先给出每份文件的SHA；格式和预算见[批量切片](../docs/plans/模型批量核验与中断恢复切片.md)。仅使用标准库和POSIX文件锁，不连接服务器或改写工程数据。

```bash
python3 -m unittest discover -s tests -p 'test_model_probe_batch.py' -v
python3 tools/model_probe_batch.py start \
  --manifest output/q09-batch-processing-20261025/_work/models.json \
  --output output/q09-batch-processing-20261025/run-new
python3 tools/model_probe_batch.py cancel \
  --output output/q09-batch-processing-20261025/run-new
python3 tools/model_probe_batch.py resume \
  --output output/q09-batch-processing-20261025/run-new
```

start须用新目录；cancel在另一终端执行，也可向主进程发SIGINT/SIGTERM。resume先核对全部源输入、处理器和已完成输出SHA，再复用完成项；中断项保留原目录、用新尝试重跑，失败项保留并继续其他文件。计划、输入或已完成报告变化时拒绝复用，需选择清单另开新批次。退出码0/1/130分别为全通过、失败/输入错误、取消。批次通过仍为本机技术结果，工程发布资格始终false；在线处理、产品报告和工程换版另验。

## 三柜与无几何子设备的合同验证

[location_contract.py](location_contract.py)把[OV-C05逻辑契约](../docs/contracts/三柜绑定与子设备定位契约.md#5-定位算法与响应)变成离线可执行样例；使用Python标准库，不连接OntoBase、不创建HTTP服务、不写工程事实或绑定。它是当前提案的参考求值器，后续生产实现仍需在已冻结的服务边界内实现和验证。

```bash
python3 -m unittest discover -s tests -p 'test_location_contract.py' -v
python3 tools/location_contract.py \
  --fixtures tests/fixtures/location_contract.json \
  --output output/contract-verification-20261021/run-01
```

上述输出目录已存在；复跑时换用新的目录后缀。32个[维护夹具](../tests/fixtures/location_contract.json)全部使用`fixture-*`工程引用。`request`是拟议OV-C05逻辑载荷；`facts`是可信提供方的合成答复和已发布场景替身，**不能成为客户端请求的权限、父链或发布依据**。夹具包的`baseRequest/baseFacts/baseExpected`与每例同名字段仅作同级浅覆盖；对象和数组整项替换，不做隐式深合并。工具导出的`report.json`展开每例完整请求、`recordedAuthority`、期望和实际响应，避免只看差异误解输入。

43项定向测试验证：三柜直接定位及组成构件；子设备身份与祖先几何分列；当前授权拒绝与隐藏路径；合并/退役、实例/版本冲突；完整确认父链、半开有效期、历史缺失不回退；多表示选择、已审核主表示和`contextEpoch`回传。最近已绑定祖先失效或歧义时不会跳到更远机组。深度32只是本机验证预算，生产限额仍属R-08。固定历史树即使在直接定位时也核对存在性；等价UTC写法按同一时刻比较。

缺字段/非法夹具明确失败；成功只表示32例与预期逐字段一致。退出码0为全例匹配，1为输入、输出或断言失败；新目录保存报告，已有目录拒绝覆盖。报告始终标记`verificationScope=offline_contract_only`、`realIntegrationPassed=false`和`G1/G2/G3Passed=false`。它没有实现当前用户认证、权限存储、分页游标、写入幂等/事务、证据读取、实时一致性重试或浏览器丢弃旧响应；S-01–16真实业务验收不由这些样例代签。

## 7号安装对象的本机只读预览

[installation_preview.py](installation_preview.py)将已有本机三维Demo接到OntoBase的演示安装API，Python标准库实现。它只服务已审阅清单中的机组、三柜和一个子对象；本机操作者正常登录，令牌只在进程内存，结束即丢弃。浏览器没有OntoBase令牌、写入代理或自报权限/父链入口，不保存密码。

```bash
python3 -m unittest discover -s tests -p 'test_installation_preview.py' -v
python3 tools/installation_preview.py \
  --manifest output/installation-preview-20261021/session-manifest.json \
  --demo-root output/xiali-spatial-demo-20261020 \
  --ssh-target root@192.168.2.153 --port 8766
```

需要已获授权的SSH和应用用户；密码通过终端隐藏输入，勿写进命令、文件或聊天。当前测试会话的凭据已由用户提供，不再索取。命令绑定`127.0.0.1:8766`，通过SSH回环端口访问后端；不是公网多用户登录方案，不能直接改绑公网地址。清单和模型不进入Git；没有清单/本机模型时明确失败，不伪造演示输入。

清单schemaVersion=1，固定projectCode、installationContextId、unitLabel=7、rootEntityUid、childEntityUid、源/派生模型SHA256及CT/CN1/CN的独立UID/geometryQuality。启动校验实际模型文件双指纹，CN只能source_candidate、CT/CN1只能proxy_schematic；清单只是本机绑定草稿，不产生正式发布。

GET `/api/demo/context`和GET `/api/demo/locate`为仅有的工程读取入口，Host/Origin限制为当前回环服务，响应no-store。每次从后端核实当前成员/身份、同安装范围和完整assumed父链，树修订不一致最多重读一次。合并/跨机位/断链不复用旧几何，子对象仍为分析对象，CN只为空间宿主，柜内坐标未知。所有成功响应明确`previewOnly=true`、`bindingStatus=demonstration_draft`、`engineeringUseAllowed=false`。

14项测试覆盖真实本机HTTP入口、方法/来源限制、清单指纹、跨范围/未知身份、权限拒绝、合并不自动改绑、完整父链及有界重读。测试全为合成数据，不依赖服务器或现有演示清单。实际API/三维与浏览器故障验证分列在[本机交付说明](../output/installation-preview-20261021/README.md)，不等于G3正式工程验收。

## 历史演示资源打包（仅归档参考）

[package_spatial_demo.py](package_spatial_demo.py)针对夏李技术演示导出固定资源清单。用户最新要求Demo仅作本机交互参考，不发布到vis.ontobase.ai；下列打包能力保留归档，不作为当前发布任务。原模型、工程清单、原始附件/商业参考影像、日志与中间文件不进入公开包；声明需有非敏感授权依据，不自动推断素材开放许可。2026-10-21用户已确认现有TU-3000公网用途授权，保留模型，书面依据待补充。

```bash
python3 -m unittest discover -s tests -p 'test_package_spatial_demo.py' -v
python3 tools/package_spatial_demo.py \
  --source output/xiali-spatial-demo-20261020 \
  --output output/public-spatial-demo-20261021/bundle-01 \
  --model-authorization-basis '用户于2026-10-21确认本模型公网使用与再分发授权；依据文件待补充。'
```

上述目录已存在，复跑必须换新目录。工具拒绝覆盖，拒绝缺文件/符号链接和本机路径，输出逐文件SHA/字节数的release.json、公开来源与模型声明。9项合成测试通过；实际服务器包/公网浏览器检查另见[部署记录](../docs/plans/公网演示部署记录.md)。包不含工程身份或登录凭据，工程读取明确未连接；它不是完整产品或用户会话实现。

## 历史逐用户会话包（仅参考）

`package_spatial_demo.py --with-user-sessions`将维护中的apps/web会话与工程页覆盖入固定空间资源包，新增session.js/session.css；私有身份清单不导出。打包本身不证明后端已连接，实际部署见[部署记录](../docs/plans/公网演示部署记录.md)，服务与检查见[应用说明](../apps/README.md)。当前机位数量按源GeoJSON元数据生成公开说明，保留原编号；不修改机位坐标。

## 私有库与固定模型的离线备份/恢复

[model_store_backup.py](model_store_backup.py)只复制当前成对的 `workbench-library`（完整 SQLite、模型、地形与临时文件）和 `workbench-model`（固定配置/GLB及其他常规文件），不管理服务、迁移数据或切换运行目录。它不同于只清孤儿的 `model_store_recovery.py`。

操作者须先停止所有写者，并另存 unit/MainPID/cgroup/端口等停服证据。`--service-stopped` 仅为明确声明，工具不冒充检测任意写者。仅支持当前 rollback-journal SQLite；WAL/SHM/journal、symlink（含父路径）、hardlink、特殊文件、已有/重叠目标全部拒绝，不自动修库、清理或覆盖。所有路径须为无链接的绝对路径；以下是停服并获操作授权后才执行的示例，本节不表示已经备份运行站。

```bash
python3 tools/model_store_backup.py snapshot \
  --library-root /data/ontovis/private/workbench-library \
  --model-root /data/ontovis/private/workbench-model \
  --destination /data/ontovis/output/q06-scene-acceptance-20261023/backup-B0 \
  --service-stopped

# 手工填入 snapshot 回执中的完整 manifestSha256，不从待核验包自行推导期望值。
ONTOVIS_BACKUP_MANIFEST_SHA256='填入回执中的64位小写SHA256'
python3 tools/model_store_backup.py verify \
  --backup-root /data/ontovis/output/q06-scene-acceptance-20261023/backup-B0 \
  --expected-manifest-sha256 "$ONTOVIS_BACKUP_MANIFEST_SHA256"
python3 tools/model_store_backup.py restore-new \
  --backup-root /data/ontovis/output/q06-scene-acceptance-20261023/backup-B0 \
  --expected-manifest-sha256 "$ONTOVIS_BACKUP_MANIFEST_SHA256" \
  --destination /data/ontovis/output/q06-scene-acceptance-20261023/restore-R0 \
  --service-stopped
```

目标必须每次换新目录。工具以0700/0600创建私有副本，核对复制前后完整目录清单/文件身份/SHA、SQLite `integrity_check`/外键、所有表及完整 schema 摘要，并按数据库记录核对注册 GLB、固定模型 scope/SHA和地形版本全部制品/报告；不调用会清临时文件或改任务状态的应用构造器。整库字节和全表摘要保留场景头/历史、registry、幂等结果、全部审计和 catalog 签名密钥；回执只输出计数/摘要及 registry 状态，不输出私密行值或密钥。

失败返回非零并保留私有未完成目标，不自动删数据。出现 `manifest.partial`、缺少 `manifest.json`、seal失败的双链接或任何清单差异均不可使用，`verify` 会拒绝；不能仅凭清单文件名存在认定成功。中断后保留证据，重试使用新目录。外部期望 SHA 必须来自独立保存的成功回执。

恢复只生成新目录，不启用服务、不覆写原根。切换后须由操作者比较当前库与恢复回执中的 registry/全表摘要，保持同一 active gate 和全部新数据；不得以切换前旧备份倒回库或让不识别 gate 的旧后端启动。失败回退优先保留兼容后端、只退兼容前端；无法保持旧写关闭则停服维护。真实停服、恢复演练、旧写拒绝与部署回退另行验收，不由本工具的合成测试代替。

## 项目登记 PostgreSQL 迁移候选

`python -m tools.project_registry_postgres --help` 提供 export/stage/verify 三个固定操作，完整字段、预算及错误见[迁移准备契约](../docs/contracts/项目登记PostgreSQL迁移准备契约.md)。export先验证现有整组备份和外部manifest SHA，再只读导出当前三表登记；固定包只含原UUID、范围、状态和时间文本，不包含文件原件、会话或凭据。

stage/verify使用外部package SHA、原request-id及私有`ONTOVIS_REGISTRY_STAGE_DSN`；目标须为独立ontovis/ontovis_*数据库。事务导入保留源记录，重复请求返回同一回执，冲突/未知目标不覆盖；verify实际只读。连接异常仅输出固定错误码，DSN不放入命令参数或日志。

此工具只产生`staged_metadata_only`候选，不切换服务、复制资源或变更工程权威；当前仍单进程SQLite。24项合成/真实PG测试及既有1空间/247文件B1登记只读暂存通过，来源备份保持，实际消费者/全库文件迁移/恢复和多进程运行另做后续验收。现行[切片](../docs/plans/存储与服务运行准备切片.md)保留后续顺序。
