# Bench Server 架构图解

[打开介绍网页](index.html) · [benchmark 接入指南](../../docs/benchmark-server-guide.md)

**具身 Benchmark 服务化：让评测更严谨、更可复现、更易规模化。**

**一个入口，选择你的 Benchmark：已集成 13 个仿真 Benchmark，真实机器人接入正在拓展。** 各仿真服务的任务覆盖与原生验收进度见[支持矩阵](../../benchmarks/simBenchmarks/SERVICE_SUPPORT.md)。

Bench Server 将具身评测封装为独立、可调用的服务，明确 Agent 的环境访问权限，将物体真值、私有场景信息和评分逻辑留在评测端，减少利用仿真特权取得成绩的捷径。服务围绕真实机器人的感知与控制能力定义接口，为 Sim / Real 交互对齐、后续真机接入与规模化评测提供基础。

页面按以下顺序介绍服务化的价值：

1. **可信的 agentic 评测：** 明确环境访问权限，减少仿真特权捷径，同时保留允许范围内的自主规划和工具使用。
2. **Sim / Real 交互对齐：** 围绕真实机器人的感知与控制能力封装服务，为后续真机接入建立共同边界。
3. **可复用的评测基础设施：** 统一封装环境、任务执行和评分，保留可核对的配置与结果，降低接入成本，为规模化评测提供基础。

项目介绍聚焦 Bench Server 的设计与实现，现有几个 Agent 方法用于服务验证和接入示例。当前每个服务实例同时运行一个 episode；自动资源分配与远程多服务调度仍待实现。更完整的项目说明见 [Projects_readmes/README.md](../../Projects_readmes/README.md)。

网页的[验证进展](index.html#validation-snapshot)收录了项目维护者提供的 **2026-10-07 人工结果快照**：SimplerEnv 15 任务 × 5 seeds 的 75 个正常结果（20 成功、55 失败；另保留 1 条原始工程错误），以及 13 个 Benchmark 的 Direct v3 单案例验收（11 正常完成，含 6 成功、5 失败；2 工程中断）。完整条件、恢复关联和运行索引见[详细快照](../../Projects_readmes/evaluation-snapshot-2026-10-07.md)。两组范围分开呈现；本次未重新读取 raw 或开展评测，当前源码不包含这批原始运行产物。

后续章节介绍架构、能力边界和生命周期，并以 RoboDojo **服务协议 Direct v2** 展开实例。启动示例使用 **agent 方法 gpt6-astra-codex-native**；两者是分别版本化的服务与方法。当前按 benchmark／protocol／方法配置分别比较，尚不提供跨 benchmark 总榜。

交互历史可选、默认启用，不是参评或发布门槛；基础结果不要求事件日志或源码审计。RoboDojo 是已接入服务之一，不是整个框架；不同机器人保留原生观测、动作与评分。

访问边界需要由观测白名单和部署权限共同落实，服务封装本身不构成完整安全沙箱。协议允许的机器人 state 可以公开，但测量值、命令值和仿真物体真值不能混淆。Sim / Real 对齐首先指交互权限与接口语义；硬件时序、安全、复位和评分仍需独立实现与验证。

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
- `benchkit/sim_server/`：公共通信和会话库。benchkit 另提供记录、审计与报告，不新增决策服务，也不提供中央案例调度。
- `rsi-bench list / serve --benchmark <id>`：统一选择并委托现有服务，不改变原生契约。
- `benchkit/reports/interaction_history.py`：闭合 client-run 的交互 HTML / JSON；不复制媒体、不补造缺失输出。内容指纹留作内部支撑，用户主视图是交互与结果。
- `benchkit/reports/basic_result.py`：无需交互日志的基础结果，保留选定分母、成败、错误和已知用量。
- [方法声明](../../docs/agent-methods.md)、[可选记录](../../docs/recording.md)、[跨语言结果格式](../../docs/result-format.md)：公开接入与保存约定；客户端保存开关不控制原生服务录像。
- 开发态服务实现、原生短交互、模型单例和 max 评测是不同证据层级；当前范围见[支持矩阵](../../benchmarks/simBenchmarks/SERVICE_SUPPORT.md)。

本目录是可随仓库发布的自包含介绍材料。规范性定义仍以 [通用线协议](../../benchmarks/simBenchmarks/SERVER_PROTOCOL.md)、[服务约定](../../benchmarks/simBenchmarks/SERVICE_CONVENTIONS.md) 和各 benchmark 的评测协议为准。

新评测默认只在持久化的 `server/episodes/<session>/` 长期保留视频，client 保存引用而不下载第二份。正常关闭后，确认视频非空、哈希稳定且数量不低于声明相机数，再清理临时图片；这不是视频解码或逐相机内容完整性验证。条件不满足则保留图片并记录原因。server 可用 `--retain-frame-images` 额外保留图片，client 可用 `--copy-server-media` 复制所选媒体；历史记录不回溯清理。

一次决策可以对应多个控制步。动作块长度、重复次数和何时再次推理由 agent 方法决定；服务保留原生控制、终止和执行预算，不设通用的“每次决策五步”。

项目定位文案更新：2026-10-10；原有验证记录的日期与范围保持不变。目录更名见 [迁移说明](../../docs/package-migration.md)；新增 benchmark 的具体实施步骤见 [docs/benchmark-server-guide.md](../../docs/benchmark-server-guide.md)。
