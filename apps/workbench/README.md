# ONTOVis 只读设备与模型工作台

承接MagicPath工作台修订`463670158779645952`及用户离线色板：48px顶栏、42px工具栏、32px对象行，正文13px/说明11px，三栏独立滚动，原Logo透明底。账户菜单提供语言、深浅/系统主题、账户信息和退出；偏好之外的工程数据不落浏览器本地存储。

`Workbench.tsx`复用当前本人会话；`ObjectsPanel.tsx`分列设备树和完整项目对象目录，使用OntoBase搜索及每页50项服务端游标，不把型号定义挂到风机。`SourceEvidence.tsx`支持设备对象的固定型号来源和未安装对象自身图纸；内容变化需重选，旧区域未绑定文件版本时整页显示。

`ModelViewport.tsx`登录后按需加载Three与已授权私有GLB，限制像素比、按需绘制。三柜采用实际OntoBase UID及固定对象修订，CT/CN1显示柜体示意，CN为候选构件；子对象保持自身身份和图纸，仅沿完整物理祖先链定位所属柜体。未知、变化或断链不猜精确坐标。退出、失效或对象切换清理临时图纸URL、模型、高亮及迟到响应。没有通用上传/转码、正式绑定写入或工程发布。

`theme.css`是用户色板和密度变量；`design.css`提供共享控件，`compact.css`承接当前MagicPath布局。Radix Dialog/Tabs/Dropdown处理弹窗、页签及账户菜单。实际模型、UID映射和图纸不进入构建包；空间连续导航Demo继续只作本机参考。

Node 22：

```sh
npm ci --prefix apps/workbench
npm --prefix apps/workbench run check
npm --prefix apps/workbench run dev
```

检查包含严格类型、15项请求时序/定位/语言测试与构建。产物在`output/compact-workbench-20261021/workbench-dist/`，不进入Git。临时预览4180代理固定本机18084，使用结束后关闭，保留参考Demo8766。

API服务通过`--project-code`、`--installation-context-id`及可选`--model-root`固定部署来源。模型目录仅包含`model.json`及`model.glb`，校验指纹、自包含资源、三柜实际身份/修订；生产模板使用服务器私有目录。浏览器不能提交文件路径或上游URL。配置/限额和服务范围见[切片契约](../../docs/plans/紧凑工作台与模型接入切片.md)。
