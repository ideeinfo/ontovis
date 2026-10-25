# 项目登记 PostgreSQL 迁移准备契约

2026-10-25，Q-13 的固定迁移候选。工具为 [project_registry_postgres.py](../../tools/project_registry_postgres.py)，承接[存储与运行切片](../plans/存储与服务运行准备切片.md)。本切片仅验证已有项目登记的迁移，尚未让ProjectSessions改读PostgreSQL，也未完成全库/文件、会话、任务和多HTTP实例运行。

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
