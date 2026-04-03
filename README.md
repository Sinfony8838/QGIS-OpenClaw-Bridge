# GeoBot

GeoBot 是一个面向地理教学与 GIS 实践的智能辅助教学项目。  
它的目标不是把 QGIS 包装成一个单纯的“控制台”，而是把**教学设计、地图制作、课堂展示和教学产物生成**串成一个完整工作流。

当前版本采用本地桌面执行架构：

- 教师在 `GeoBot Desktop` 中输入教学需求
- `GeoBot Runtime` 负责项目、任务、产物和本地桥接
- `QGIS Plugin` 负责专业制图与空间分析执行
- 过渡阶段通过隐藏的 OpenClaw 工作流完成教学编排
- 长期将迁移到专用内核 `GISclaw`

## 项目定位

GeoBot v1 的核心交付不是“单张地图”，而是：

- 教学设计 / 教案
- QGIS 制作的专题地图
- 课堂展示材料
- 后续可扩展的 PPT / 教学包

QGIS 是 GeoBot 的一个重点能力，但不是全部。  
项目真正要解决的是：**如何把教学意图转成可执行的教学流程和专业 GIS 演示**。

## 当前能力

目前仓库已经包含：

- 本地 QGIS 插件与 socket 桥接
- GeoBot 本地运行时
- Electron 桌面端壳层
- 面向 QGIS 的 `qgis-solver` 工具包
- 教学地图模板与查询能力
- 面向教学工作流的阶段化任务模型

已支持的重点地图能力包括：

- 分级设色
- 热力图 / 密度图
- 流向图
- 胡焕庸线生成与对比
- 标签、图例、属性查询
- 地形剖面和简化地形表达

## 仓库结构

```text
geoai_agent_plugin/   QGIS 插件，负责本地 GIS 执行
geobot_runtime/       本地运行时，负责任务、产物、桥接与 API
geobot_desktop/       Electron 桌面端
qgis-solver/          QGIS 工具层与客户端封装
scripts/              安装与启动脚本
tests/                单元测试
```

## 当前架构

```text
GeoBot Desktop
  -> GeoBot Runtime
  -> Hidden teaching workflow engine (transition stage)
  -> qgis-solver
  -> QGIS plugin socket
  -> QGIS
  -> Exported teaching artifacts
```

当前过渡版本默认仍通过本地 OpenClaw 工作流运行教学编排，但桌面前台不会暴露 `agent / skill / session / subagent` 等内部概念。  
后续计划用 `GISclaw` 替换这一层，而不改变桌面端和 QGIS 桥接层。

## 本仓库包含什么

本仓库包含：

- GeoBot 本地产品壳
- QGIS 插件代码
- 本地运行时代码
- QGIS 工具层
- 测试与启动脚本

本仓库**不包含**：

- QGIS 安装本体
- 用户本地 `.openclaw` 工作区中的私有配置
- 模型 API Key 或个人凭证
- 教师私有数据与教学资源

## 快速开始

### 1. 环境要求

- Windows
- QGIS 3.16+
- Python 3.7+
- Node.js

### 2. 安装或更新 QGIS 插件

```powershell
.\scripts\install_geobot_plugin.ps1 -Force
```

### 3. 启动 Runtime

```powershell
.\scripts\run_geobot_runtime.ps1
```

默认监听：

```text
http://127.0.0.1:18999
```

### 4. 启动 Desktop

首次需要安装前端依赖：

```powershell
cd .\geobot_desktop
npm install
cd ..
.\scripts\run_geobot_desktop.ps1
```

### 5. 过渡版额外要求

如果你要使用当前的“聊天驱动教学工作流”，还需要：

- 本机已有可运行的 OpenClaw
- 本机已有可用的 `qgis-solver`
- QGIS 已启动并加载 `geoai_agent_plugin`

## 运行时接口

`geobot_runtime` 默认提供本地 HTTP 接口：

- `GET /health`
- `GET /templates`
- `POST /projects`
- `GET /projects/{project_id}`
- `POST /chat`
- `POST /templates/{template_id}`
- `GET /jobs/{job_id}`
- `GET /jobs/{job_id}/stream`
- `GET /artifacts/{artifact_id}`
- `GET /outputs`
- `POST /qgis/focus`

## 开发状态

当前仓库更接近 **GeoBot v1 原型 / 过渡版**，已经能跑通：

- 教学需求输入
- 本地工作流任务调度
- QGIS 地图制作
- 查询型任务结果回收
- 桌面端状态与产物展示

仍在持续完善：

- `teacher_flow` 的正式产品化输出契约
- PPT 生成链路
- 更多教学模板
- Windows 安装器
- 用 `GISclaw` 替换过渡期 OpenClaw 编排层

## 测试

```powershell
python -m unittest `
  tests.unit.test_service_utils `
  tests.unit.test_session_utils `
  tests.unit.test_geobot_runtime_config `
  tests.unit.test_geobot_runtime_store `
  tests.unit.test_geobot_templates `
  tests.unit.test_openclaw_engine `
  tests.unit.test_qgis_client
```

## 路线图

短期目标：

- 稳定教学工作流
- 完善地图、教案、PPT 三类产物
- 继续隐藏底层编排引擎

长期目标：

- 建立云端知识库和模型网关
- 把 OpenClaw 过渡为 `GISclaw`
- 将 GeoBot 做成可交付给教师的正式桌面产品

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).
