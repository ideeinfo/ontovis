# ONTOVis 设备与模型工作台

承接MagicPath修订463695831967600640，保留原命名管理侧栏、页面入口和树/模型/详情三栏；附件只提供灰绿深浅配色。56px顶栏、64px标题区、32px对象行，13px正文/11px说明；透明原Logo和中英文/主题账户偏好保留。

`Workbench.tsx`复用本人会话，`ObjectsPanel.tsx`分列真实设备树与完整项目目录，服务端每页50项。`SourceEvidence.tsx`按对象自身或固定型号来源打开受保护当前图纸；内容变化拒绝并重选，不借用所属柜资料。

`ModelLibraryPanel.tsx`落实原模型中心、报告/版本页签和四步上传。仅接收20MiB以内的自包含静态GLB；实际校验成功生成私有不可变版本，预览需显式选择，坐标/工程身份继续待核实。来源与授权由上传者声明，不替代许可或工程审核。文件更换清空原声明，失败显示原因。

`BindingEditor.tsx`保存三柜演示关联，后端核验当前项目管理员、三柜真实身份/修订、完整父链和模型修订。CT/CN1的既有示意只用于相同文件指纹；新文件不能继承旧工程关联。`modelLocation.ts`保留子设备身份，通过最近有效柜体定位，旧近层关联失效时不跳远层。

`ModelViewport.tsx`登录后按需加载Three/私有GLB，绑定提取目录的版本内节点，按需绘制并限制像素比。`theme.css`仅定义色板/尺寸，`navigation.css`保留原管理结构；`models.css`补原模型流程控件。Radix负责弹窗、页签和账户菜单。退出/失效清理详情、文件、模型和迟到结果。工程确认/发布、在线CAD转换和空间导航Demo不在部署包中。

Node 22：

```sh
npm ci --prefix apps/workbench
npm --prefix apps/workbench run check
npm --prefix apps/workbench run dev
```

检查包含严格类型、当前前端测试全集和构建，数量以最新执行记录为准。产物在`output/compact-workbench-20261021/workbench-dist/`，不进入Git。临时4180预览代理固定本机18084；本机空间参考Demo的资源独立保留。

带登录视频的发布使用`tools/build_workbench.py`，显式提供`--media-dir`、`--public-dir`及`--check`；它注入视频地址并核对编译引用。单独运行npm构建不能替代这一发布入口。媒体、Logo原件和真实工程资料不随代码新增上传。

静态交付使用`deploy/nginx-workbench.conf`：仅成功的带内容版本文件名的公开`/assets/`与登录`/media/`响应允许长期缓存，HTML、健康、会话、业务API和错误响应仍为no-store。Logo从HTML高优先级预加载，保持原字节；脚本/样式启用传输压缩。发布新目录时保留上一发布目录的带版本公开资源，若同名则必须同字节，避免已打开页面延迟加载旧分块时404；不沿用旧HTML或把业务资料放入静态目录。更新后核对实际缓存/安全响应头、条件读取304及旧分块可达性，见[Q-52记录](../../docs/plans/开发执行记录.md#96-q-52首页静态缓存与logo预加载2026-10-25)。

API以`--project-code`、`--installation-context-id`、`--model-root`和`--library-root`固定部署范围。原模型映射、上传库/SQLite/审计放服务器私有目录，不进入Git或静态发布目录。上传与演示关联不修改OntoBase业务数据。详细服务、资源限制和边界见[上传切片](../../docs/plans/模型上传与演示关联切片.md)。
