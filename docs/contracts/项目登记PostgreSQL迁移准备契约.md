# 项目登记 PostgreSQL 迁移准备契约

2026-10-25，Q-13 的登记迁移与运行候选，承接[存储与运行切片](../plans/存储与服务运行准备切片.md)。固定暂存/回装工具为 [project_registry_postgres.py](../../tools/project_registry_postgres.py)，当前实际ProjectSessions的PG登记候选与配对备份入口为 [project_registry_runtime.py](../../tools/project_registry_runtime.py)。业务库/资源文件仍本机SQLite与私有目录，会话、任务和多HTTP实例运行未完成。暂存24项见§4，回装33项见§5；后继运行候选见§6，各轮范围分别记录。

## 1. 来源与固定迁移包

`export` 接受现有整组离线备份、外部固定的manifest SHA256及新输出文件。先调用现有整组verify，核对登记/共享资源/项目库/保留文件组合；再只读registry.sqlite3，固定格式仅接受 registry_meta、project_workspaces、shared_model_store 三表及其当前列集合。

保留原workspace_id、连接/项目范围、storage_key、legacy_context_id、preparing/ready/blocked及阻断原因、原created_at文本；不生成替代工作区ID、不把未完成范围提升为ready、不重新核实工程身份。单例meta/schema/scope版本必须为当前v1，连接范围一致，主身份/项目/存储键唯一，UUID及带时区时间有效。未知源表/列/版本拒绝，不静默丢弃。

迁移包为固定UTF-8 JSON：format=ontovis-project-registry-staging-package-v1、schemaVersion=1、sourceManifestSha256、sourceRegistrySha256和三表registry。至多10,000个工作区且包不超过4MiB，以先达到的限制为准；读取包先检查文件大小再有界读取，重复JSON键/额外协议字段/NaN拒绝。包文件新建0600，不覆盖原文件或写入来源备份目录；拒绝链接/硬链接。

导出回执提供外部固定packageSha256；导入须由操作者持有这份原回执。摘要验证字节一致性，不替代来源/操作者授权或工程事实核实；导入不重新复制/核验所有资源，源整组备份仍是后续完整迁移/恢复依据。包仅含登记字段，不含数据库凭据、会话、模型字节或原文。

## 2. 独立 PostgreSQL 暂存

`stage` 使用固定包、外部packageSha256、原request-id和私有连接。数据库须独立命名为ontovis或ontovis_*；在任何DDL/DML前检查current_database，不向OntoBase业务数据库写表。只使用固定schema `ontovis_registry_stage_v1`，包括三份明确字段表和单例migration_receipt；没有通用SQL转换/插件平台。

整个首次导入在一个事务中完成，事务级advisory lock串行化本profile的并发导入，固定15秒statement/5秒lock预算；数据库约束再次控制连接外键、唯一范围及状态。已有不认识的目标拒绝，不drop/rebuild或覆盖。中途数据库失败回滚本次schema/全部行/回执。

同request-id＋同固定包重放前重新读取三表并核对完整行及摘要，返回同一回执/时间，不更新行或行版本。不同request-id不能接管既有目标；同请求内容改变返回冲突；目标内容变化拒绝且不自动修复。提交结果未知时保留原包、SHA及原请求号，显式重试原请求，不生成新身份重导。

`verify` 使用真实REPEATABLE READ / READ ONLY事务；空目标返回REGISTRY_TARGET_EMPTY且不创建schema。回执固定 `status:staged_metadata_only`、`runtimeActivated:false`、`resourceFilesCopied:false`、`engineeringAuthorityChanged:false`，含源/包/登记摘要、原请求回执ID、时间和三表计数；不输出完整登记行或凭据。

## 3. 操作入口与错误

在仓库根运行 `python -m tools.project_registry_postgres --help` 查看实际参数。export需要backup、manifest-sha256、package；stage/verify需要package、package-sha256、request-id。连接从私有 `ONTOVIS_REGISTRY_STAGE_DSN` 读取，不作为命令参数或普通日志输出；本批实测复用已有安全配置，未要求用户准备环境变量。

来源损坏、格式/范围不符、包变化、目标占用/改变/请求冲突、目标忙或数据库不可达均有固定错误码，CLI退出2。原SQLite异常及连接异常不向普通输出透传；来源/格式拒绝发生在目标连接或写入之前。原整组备份错误码保持可辨识。

## 4. 验证与边界

最终12项包契约本机通过；真实PostgreSQL完整24项包含这12项及12项集成，零失败/跳过。覆盖来源与包保持、错误/未知格式、严格UTF-8与过深JSON拒绝、身份与预算、凭据错误输出、完整元数据、原回执/行版本重放、真实只读事务、空目标无写、两CLI进程并发同请求、竞争请求单一成功、未知目标保持、内容变化拒绝、数据库约束及中途失败后原请求可重试。

首轮12项有1项损坏源透传SQLite异常；已修正为REGISTRY_SOURCE_INVALID并重跑12项通过，首轮日志保留。PostgreSQL测试仅自建/清理随机ontovis_registry_*库，默认应用DSN不可达，不运行OntoBase业务迁移或冻结识别验证。

另对现有最终B1（1空间、247文件）实际只读导出，在新独立PG库暂存、重放和只读核对，原登记三表/UUID/状态逐字段一致。收尾补齐输入拒绝后，24项及该固定B1实测均再次执行，导出包摘要相同；两轮是同一固定样本，不加为2空间/494文件。两份合成集成库/两份登记实测库均删除，完整B1摘要及文件字节/身份/mtime保持。该实测只对应固定B1登记元数据，不是当前权限、资源复制、全库恢复或多进程生产验收。证据见[本机索引](../../output/q13-registry-postgres-20261025/README.md)。

后续接入实际ProjectSessions读取前，仍需迁移/备份/新目录恢复、共享模型和项目文件配对、当前授权、会话/游标密钥、处理名额及任务所有权等完整链路。保留单进程保护，当前线上仍a17f3fa；本批未部署、修改UI或使用浏览器，Q-08原临时页与最终回读保留。

## 5. 固定登记回装与完整新目录恢复

`restore-new` 接受原backup/manifest-sha256、固定package/package-sha256、原request-id、同一私有DSN、全新destination及显式service-stopped。先验证完整备份、包内来源摘要及实际三表逐字段相等；仅声明相同源SHA而登记行不同也拒绝。目标已存在、嵌套来源、链接或未声明目标存储离线均在读取PG前拒绝。离线声明针对该备份/恢复副本，不代表在线测试站已经停服。

以真实REPEATABLE READ / READ ONLY事务核对暂存回执/摘要，取得同一事务中的实际PG行；不重新stage、不更新暂存行或xmin。原UUID、连接/项目范围、storage_key、preparing/ready/blocked与原因、原带时区时间文本均保持。随后使用既有整组restore-new复制配对文件，仅在本次新目录重建SQLite三表登记；不能覆盖既有库或自动接管在线目录。

重建先撤下复制的旧清单，再创建0600登记候选、核对全部行、替换本次新登记；除registry.sqlite3的物理字节及对应清单项外，整组报告必须和原备份相等。来源全文件字节/身份/mtime、包指纹保持后才生成新外部manifest SHA，并再次完整verify。新清单兼容既有project_store_backup.verify/restore-new；新SHA不能冒作原来源或在线B1的SHA。

回执为restored_sqlite_from_staged_metadata，包含原/新登记和清单摘要、包/登记摘要、原stageReceiptId及计数，固定postgresWrites=0、resourceFilesCopied=true、registryRebuiltFromPostgres=true、runtimeActivated=false、engineeringAuthorityChanged=false。失败保留本次部分目录，撤下本次重建的完整清单，不能原地重试/自动删证据；应保留原来源与原请求并换新目录。源/包不匹配、重建失败、恢复不一致分别为REGISTRY_PACKAGE_SOURCE_MISMATCH、REGISTRY_RESTORE_FAILED、REGISTRY_RESTORE_MISMATCH，既有备份错误码保持。

最终本机16项与容器16项包契约通过，均含在真实PG完整33项中；本批新增9项（4包/5PG）包含其中，不与首轮24项或其他环境相加。覆盖真实只读快照、同目标两CLI进程唯一成功、来源声明/实际行不符拒绝、失败目录及换目录重试、未完成状态保持。合成权限测试通过现有ProjectSessions登录、读取原场景/UUID、撤权后拒绝及只读角色写入拒绝，不把旧备份中的权限当当前授权。

同一最终B1的1空间/247文件完成实际CLI回装、整组核对、既有标准restore-new再恢复和原生ProjectWorkspaces登记读取，场景数16；源三表/UUID/范围/状态及其余全部配对文件保持，PG暂存行/xmin不变。此固定样本仅回读登记/范围，不声称对真实源重新核权；当前授权由前述合成反例覆盖。原来源manifest仍b65c1fab6e60c675fc373c127feb95d5234489f1ab2170ab2b7993e7d9d3026e，新私有恢复manifest为d4a7efdda8d2bcb6f15544a6ff30d455f031edb2a14119ba7edb8f5670a17785。三份临时文件副本仍是同一固定样本，不加成多个工程数据样本；两自建PG库、唯一容器候选、三份完整文件副本及登记消费者小副本均已清理，原在线整组及配置保持。

本切片未部署或启动PG运行后端，场景/资源业务DB、文件真值及当前在线服务仍原SQLite。后续实际PG消费者、运行期写入/备份恢复、会话/游标/名额/任务跨进程仍待实施。Q-08原页补验已于[记录§85](../plans/开发执行记录.md#85-q-08原页完整回执与最终重新登录补验2026-10-25)完成，不再保留待导出临时页。完整[本批证据](../../output/q13-registry-recovery-20261025/README.md)仅本机保存。

## 6. 实际会话服务的 PostgreSQL 登记候选

`ProjectSessions`显式选择`registry_backend=postgres`，服务CLI为`--registry-backend postgres`；私有连接仅从`ONTOVIS_REGISTRY_DSN`读取。默认SQLite行为保持，PG故障不回退SQLite。可选驱动固定于[requirements-registry.txt](../../apps/api/requirements-registry.txt)，普通SQLite运行不要求安装该依赖。共享模型范围登记改由两种具体登记实现各自处理，不向业务库引入通用SQL翻译层。

运行schema独立为`ontovis_registry_runtime_v1`，与前述不可变暂存schema分开。原三表/字段保持，额外单例`runtime_binding`记录随机store_id、整组目录身份摘要及原备份SHA。`activate-new`只接受已完整验证的备份、外部manifest-sha256、全新目标目录、无该运行schema的ONTOVis专用库及显式service-stopped。通过原备份工具复制全部文件，再在单事务中创建明确表/外键/唯一范围/状态约束及原登记行；不改原备份或在线目录，不覆盖既有schema，不将业务表写入OntoBase数据库。

新项目根的`registry-postgres.json`只含格式、storeId、connectionId，权限0600，不含DSN。运行候选撤下旧备份清单并移除其SQLite登记文件，其他文件保持；启动先核对PG表列、连接范围、storeId及项目/共享库/旧固定模型目录的绝对路径和设备/inode身份，之后才初始化业务服务。复制目录、错误模型根、错误连接、未知schema、标记缺失/错误及同时存在SQLite登记均拒绝。带PG标记的目录不能通过默认SQLite服务或旧SQLite快照工具打开；标记链接也拒绝。跨机器/目录搬迁必须经完整备份及新登记恢复，不直接复制旧标记启动。

PG所有权与登记读写使用同一连接：全程持有数据库级会话advisory lock；15秒statement/5秒lock预算，连接丢失后拒绝后续请求，不自动重连越过所有权锁。服务启动仍先取得原本机目录独占锁；PG连接也排斥第二服务或离线快照，跨目录副本又须通过目录身份检查。初始化失败和正常close释放PG所有权。使用[PostgreSQL会话锁](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)及[psycopg显式事务](https://www.psycopg.org/psycopg3/docs/basic/transactions.html)的实际语义；这仍是单服务、本机业务存储候选，不是跨机器分布式租约或多实例生产能力。

新项目按原当前OntoBase权限和服务写门创建，原连接＋项目唯一键保证登记幂等。初始化仍经过preparing→ready，冲突可记blocked；仅离线迁移能登记legacy根。登记上限10,000与固定恢复profile一致，达到上限后仍能读取/重用已有项目，但拒绝新增。状态更新核对完整原行及`xmin`短期并发令牌，陈旧行/错误范围拒绝；状态无变化不生成新行版本。`xmin`不作为工程或业务修订，恢复后重新建立；原workspace UUID、场景修订、请求摘要、工单修订和文件内容语义保持。当前授权、幂等和业务修订检查继续由现有ProjectSessions及业务服务执行。

`snapshot`需要目标存储离线声明，同时持有本机目录共享锁与PG排他所有权。用真实READ ONLY / REPEATABLE READ事务读取全部登记行；复制配对文件，在新备份中以当前PG行重建标准SQLite登记并移除运行标记。副本的其他文件逐项与源一致，整组业务范围/共享引用仍由原`project_store_backup`检查。再次核对源文件字节/身份/mtime及新的PG快照行/xmin，均保持后才发布新manifest SHA；PG未写入任何行。写清单或最终验证失败时撤下清单，保留部分目录，换新目标重试。

因此该快照可直接使用现有`verify/restore-new`恢复到新SQLite目录，也可用`activate-new`恢复到另一空运行schema及新配对目录。运行期新增项目和状态包含在新备份中，不用迁移前备份覆盖新数据。DDL与文件系统无法组成单一原子事务：中断留下的PG候选必须通过全部启动检查；提交结果不明时保留现场，另用新目标核对恢复，不自动drop、重建或接管既有schema。

本轮验证和最新工单B2副本演练见[本机证据](../../output/q13-registry-runtime-20261025/README.md)。尚未切换vis.ontobase.ai或更改其unit/代理，生产选址、业务SQLite迁移、任务/会话/名额跨进程及容量/高可用继续分列。
