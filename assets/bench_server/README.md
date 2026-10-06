# Bench Server 架构图解

[打开介绍网页](index.html) · [benchmark 接入指南](../../docs/benchmark-server-guide.md)

面向 agentic policy 的具身 Benchmark 服务化：让评测更严谨、更可复现、更易规模化。
页面先介绍开放 agent 方法评测、统一 benchmark 入口与能力边界，再以 RoboDojo **服务协议 Direct v2** 展开实例。启动示例使用 **agent 方法 codex-direct/v3**；两者不是同一个版本号。方法可组合多个通用模型、规划、记忆与工具；固定 prompt 单模型仍可作为对照。当前按 benchmark／protocol／方法配置分别比较，尚不提供跨 benchmark 总榜。

交互历史可选、默认启用，不是参评或发布门槛；基础结果不要求事件日志或源码审计。RoboDojo 是已接入服务之一，不是整个框架；不同机器人保留原生观测、动作与评分。

两个核心目标是隔离仿真神谕信息，以及围绕机器人能力设计 sim/real 接口。协议允许的机器人 state 可以公开，但测量值、命令值和仿真物体真值不能混淆。sim/real 共用原则不代表动作维度相同，也不代表统一硬件服务已实现。

## 查看方式

`index.html` 是自包含页面，没有外部脚本、字体或图片依赖。可以直接在浏览器打开，也可以在 VS Code 以仓库根目录为工作区预览 HTML。查看本页面不需要模型 API、评测 token 或启动仿真。

如需通过 HTTP 预览，在仓库根目录运行：

```sh
python3 -m http.server 18765 --bind 127.0.0.1
```

然后打开：

```text
http://127.0.0.1:18765/assets/bench_server/
```

若在远程主机启动静态服务器，先转发该端口到本地。上述命令自身不设置密码；平台代理的登录要求与 benchmark 服务认证是两回事。

## 内容与边界

- `benchmarks/simBenchmarks/<benchmark>/`：环境、协议、adapter/server 和原生评分。
- `AgentPolicies/<agent>/`：方法的模型组合、决策、prompt、工具、配置与结果；按服务协议接入，Python SDK 可选。
- `benchkit/sim_server/`：公共通信和会话库；`benchkit/campaigns/` 保留固定案例调度，当前运行冻结的本地 adapter，不是远程多服务调度器。benchkit 另提供记录、审计与报告，不新增决策服务。
- `rsi-bench list / serve --benchmark <id>`：统一选择并委托现有服务，不改变原生契约。
- `benchkit/reports/interaction_history.py`：闭合 client-run 的交互 HTML / JSON；不复制媒体、不补造缺失输出。内容指纹留作内部支撑，用户主视图是交互与结果。
- `benchkit/reports/basic_result.py`：无需交互日志的基础结果，保留选定分母、成败、错误和已知用量。
- [方法声明](../../docs/agent-methods.md)、[可选记录](../../docs/recording.md)、[跨语言结果格式](../../docs/result-format.md)：公开接入与保存约定；客户端保存开关不控制原生服务录像。
- 开发态服务实现、原生短交互、模型单例和 full 评测是不同证据层级；当前范围见[支持矩阵](../../benchmarks/simBenchmarks/SERVICE_SUPPORT.md)。

本目录是可随仓库发布的自包含介绍材料。规范性定义仍以 [通用线协议](../../benchmarks/simBenchmarks/SERVER_PROTOCOL.md)、[服务约定](../../benchmarks/simBenchmarks/SERVICE_CONVENTIONS.md) 和各 benchmark 的评测协议为准。

新评测默认只在持久化的 `server/episodes/<session>/` 长期保留视频，client 保存引用而不下载第二份。正常关闭后，确认视频非空、哈希稳定且数量不低于声明相机数，再清理临时图片；这不是视频解码或逐相机内容完整性验证。条件不满足则保留图片并记录原因。server 可用 `--retain-frame-images` 额外保留图片，client 可用 `--copy-server-media` 复制所选媒体；历史记录不回溯清理。

一次决策可以对应多个控制步。动作块长度、重复次数和何时再次推理由 agent 方法决定；服务保留原生控制、终止和执行预算，不设通用的“每次决策五步”。

内容更新：2026-10-06。目录更名见 [迁移说明](../../docs/package-migration.md)；新增 benchmark 的具体实施步骤见 [docs/benchmark-server-guide.md](../../docs/benchmark-server-guide.md)。
