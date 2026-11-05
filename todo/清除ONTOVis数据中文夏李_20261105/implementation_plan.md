# 清除 ONTOVis 数据中文“夏李” 实施方案

## 1. 背景与目标

用户在工作台“场景与可视化”中发现，虽然风机已命名为“本源1号风机”、“本源4号风机”等，但在“场景内容”面板顶部的公开地形与公开影像名称中仍带有“夏李”：
- `夏李 · Copernicus GLO-30 DSM (公开概览)`
- `夏李 · Sentinel-2 2026-10-13 (20米公开概览)`

用户明确指示：
“ONTOVis数据中文“夏李”也要去掉，无需审核直接实施”

目标是彻底清洗 ONTOVis 生产与备用数据库（`library.sqlite3`）中的“夏李”字样，确保工作台、视口面板、资源列表与天气点位等所有 ONTOVis 自有数据中均不再出现“夏李”。

---

## 2. 数据库清洗范围与详细方案

清洗对象为生产库 `/data/ontovis/private/workbench-pg-v1/workbench-library/library.sqlite3` 以及备用库 `/data/ontovis/private/workbench-library/library.sqlite3`。

### 2.1 地形资源（`terrain_versions` 与 `terrain_jobs`）
- `name`: `夏李 · Copernicus GLO-30 DSM（公开概览）` -> `Copernicus GLO-30 DSM（公开概览）`
- `metadata` / `payload`: JSON 字段 `displayName` 相应更新为 `Copernicus GLO-30 DSM（公开概览）`

### 2.2 影像资源（`imagery_versions` 与 `imagery_requests`）
- `name`: `夏李 · Sentinel-2 2026-10-13（20米公开概览）` -> `Sentinel-2 2026-10-13（20米公开概览）`
- `metadata` / `payload`: JSON 字段 `displayName` 相应更新为 `Sentinel-2 2026-10-13（20米公开概览）`

### 2.3 场景与快照（`scenes` 与 `scene_revisions`）
- 场景名称：
  - `夏李7号 · 既有模型场景` -> `本源7号 · 既有模型场景`
  - `夏李7号 · 旧上传版本场景` -> `本源7号 · 旧上传版本场景`
- 快照 JSON 数据清洗：
  - `平顶山夏李风电场` -> `平顶山本源风电场`
  - `夏李 · 公开影像概览（非工程定位）` -> `公开影像概览（非工程定位）`
  - `夏李{N}号风机` -> `本源{N}号风机`
  - `夏李风机（已布置12台）` -> `本源风机（已布置12台）`
  - `夏李7号机组（演示）` -> `7号机组（演示）`

### 2.4 设备与天气配置（`equipment_configuration_revisions` 与 `weather_config_revisions`）
- 设备配置 `displayName`: `平顶山夏李 · TU-3000 3.0MW · 夏李项目配置` -> `平顶山 · TU-3000 3.0MW · 本源项目配置`
- 天气点位 `label`: `夏李 · 公开参考中心（非实测）` -> `公开参考中心（非实测）`

---

## 3. 验证与交付

1. 执行数据库清洗脚本并在执行前后备份 `library.sqlite3`；
2. 验证清洗后数据库中所有表的 `夏李` 模糊匹配结果为 0；
3. 调用线上接口与刷新界面，核验“场景内容”面板中地形与影像名称显示为：
   - `Copernicus GLO-30 DSM (公开概览)`
   - `Sentinel-2 2026-10-13 (20米公开概览)`
4. 归档 `walkthrough.md` 并向用户汇报。
