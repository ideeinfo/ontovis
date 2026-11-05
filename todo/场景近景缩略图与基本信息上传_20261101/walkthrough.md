# 场景近景缩略图与基本信息上传更新 交付验证

## 1. 任务背景与核心目标
按用户要求：
> “为每个场景生成缩略图，需要近景，看得见风机，用于项目资产页的资产组合列表，如果场景数据结构缺少缩略图，需要补，可以在场景基本信息里上传/更新缩略图”

本次交付达成以下全部目标：
1. **数据模型与接口补齐**：后端 SQLite `SceneLibrary` 新增 `scene_thumbnails` 表，提供 `POST /api/workbench/scenes/thumbnail/upload` 与 `POST /api/workbench/scenes/thumbnail/content` 接口，场景列表及场景打开自动携带 `thumbnail` 元信息。
2. **场景基本信息上传与更新缩略图**：在场景列表与场景编辑器内的「场景基本信息」弹窗中新增 `SceneThumbnailField` 控件，支持近景图片预览、文件选择校验（支持 PNG/JPEG/WebP，单张 ≤ 5 MB）与保存时上传更新。
3. **项目驾驶舱「资产组合」卡片呈现**：在项目驾驶舱「项目资产」页的「资产组合」卡片中通过 `SceneThumbnail` 加载场景近景缩略图，无缩略图或加载异常时平滑回退原有图标。
4. **全量 9 大场景近景缩略图生成与线上写入**：为 `Demo-PDS` 的全部 9 个场景生成看得见风机的近景缩略图，并写入远端线上生产数据库。

---

## 2. 9 大场景近景缩略图合集
9 个场景均采用 `640 × 480` PNG 格式渲染或裁剪，主体风机/地形居中清晰、无任何 UI 遮挡：

![9大场景近景缩略图合集预览](/Users/diwei/.gemini/antigravity/brain/12df916c-7cc1-4971-9bfd-d74a3b191320/thumbnails-grid-preview.png)

1. **平顶山夏李风电场** (`968dfcc9-25ea-4be7-86c1-2b74aead11d0`): 夏李 1 号风机（带 ONTOVis 机舱 Logo）近景特写
2. **海上风电· MySE** (`79f0e852-4dbe-497f-8779-13d5fe494ee4`): MySE 双转子海上风电机组近景特写
3. **Beck Burn** (`93d1013a-fb2a-42c4-80d4-1d47d4c4b894`): Beck Burn 陆上风电机组近景
4. **Corriemoillie** (`875b27e4-e4bd-4cdd-88c2-983a0f3ab64b`): Corriemoillie 陆上风电机组近景
5. **Crystal Rig** (`973cb067-42d4-415c-abf3-5b5262bda339`): Crystal Rig 大规模风机机群近景
6. **Dogger Bank** (`bf4275c5-0b4c-4406-acc8-1c0607557fda`): Dogger Bank 海上风电场单机近景
7. **Hornsea 2** (`017eb11a-9dec-46cb-a3ee-88dfef641e9c`): Hornsea 2 巨型海上风电机组近景
8. **Teesside Offshore** (`424d6396-2a4e-48c5-b823-a465af7ea8cc`): Teesside 近海风电机组近景
9. **鸣沙山** (`6a4ec2e4-88f9-4658-93eb-8c55ced2f7c6`): 鸣沙山高精度三维地形与地表影像近景

---

## 3. 实机界面验证效果

### 3.1 场景基本信息弹窗中的缩略图预览与更新
在场景列表右键菜单或场景工作台打开「场景基本信息」弹窗，左下角展示缩略图预览卡片，右侧配有「更新缩略图」按钮与辅助说明，保存时自动上传替换：

![场景基本信息弹窗缩略图预览与更新控件](/Users/diwei/.gemini/antigravity/brain/12df916c-7cc1-4971-9bfd-d74a3b191320/scene-basic-info-thumbnail.png)

### 3.2 项目资产页「资产组合」列表第 1 页
展示 `Beck Burn`、`Corriemoillie`、`Crystal Rig` 3 个场景的近景风机缩略图：

![项目资产驾驶舱资产组合第 1 页缩略图](/Users/diwei/.gemini/antigravity/brain/12df916c-7cc1-4971-9bfd-d74a3b191320/cockpit-portfolios-page1.png)

### 3.3 项目资产页「资产组合」列表第 2 页
展示 `Dogger Bank`、`Hornsea 2`、`Teesside Offshore` 3 个海上风电场景的近景风机缩略图：

![项目资产驾驶舱资产组合第 2 页缩略图](/Users/diwei/.gemini/antigravity/brain/12df916c-7cc1-4971-9bfd-d74a3b191320/cockpit-portfolios-page2.png)

### 3.4 项目资产页「资产组合」列表第 3 页
展示 `平顶山夏李风电场`、`海上风电· MySE`、`鸣沙山` 3 个场景的近景风机与地形缩略图：

![项目资产驾驶舱资产组合第 3 页缩略图](/Users/diwei/.gemini/antigravity/brain/12df916c-7cc1-4971-9bfd-d74a3b191320/cockpit-portfolios-page3.png)

---

## 4. 自动化测试与质量核验

| 检查项 | 范围 | 结果 |
|---|---|---|
| 后端 SQLite 缩略图存储 | `tests/test_scene_library.py`（单张5MB限制/元数据提取/更新/去重） | 27/27 全部通过 |
| 后端 HTTP API 边界 | `tests/test_scene_http.py`（认证/会话校验/SHA-256防篡改/404/413） | 33/33 全部通过 |
| Nginx 白名单代理 | `tests/test_workbench_deploy.py` | 18/18 全部通过 |
| 前端缩略图 API 与组件 | `apps/workbench/tests/model-thumbnail-api.test.mjs` | 全部通过 |
| 驾驶舱资产组合状态合并 | `apps/workbench/tests/cockpit-state.test.mjs` | 全部通过 |
| TypeScript 类型校验 | `tsc --noEmit` | 0 错误 |
| Vite 生产打包与媒体核验 | `python3 tools/build_workbench.py` | 零错误完成 |
| 远端线上状态 | `/health` 接口状态 OK，Release `0f05c6409024131baa48bab60a5d6a3fe6680a35`，`scene_thumbnails` 9 条记录完整 | 正常运行 |
