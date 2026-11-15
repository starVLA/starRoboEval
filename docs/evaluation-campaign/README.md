# 跨 Benchmark 评测指南：从单任务验证到每任务五案例

本指南面向接手评测的开发者和希望接入自己 agent 的使用者。目标是：
**通过统一的 Bench Server 通信边界，逐个覆盖具身 benchmark；每个任务尽量预选 5 个案例，各执行一次，成功和失败都保留。**

这是一份运行与交接指南，不是“一条命令已经可以跑完所有官方 benchmark”的承诺。
当前结果见 [2026-10-07 结果快照](../../AgentPolicies/gpt6_astra/results/evaluation-summary-2026-10-07.md)。

## 1. 为什么做这件事

我们希望评测的是完整的 **agent 方法**：模型、prompt、记忆、规划、工具和动作决策如何共同完成任务，
而不只是一个固定 prompt 下的模型名字。固定 prompt 的单模型方法仍可作为对照。

将 benchmark 服务化有两个目的：

- **明确权限和评分边界**：agent 只能使用协议公开的观测和机器人接口；任务、原生控制与评分归 benchmark。
- **面向 SIM 与 real 的共同交互方式**：以机器人实际可提供的传感器和动作能力设计接口，避免策略依赖仿真特权。
  这不表示所有机器人具有相同动作空间，也不表示真实机器人服务已经全部实现。

“直接控制”限制环境访问和执行接口，不限制 agent 内部怎样思考。协议可以公开 RGB、机器人自身关节或末端状态；
不能把物体真值、隐藏评分、任意 reset、模拟器句柄或假想 rollout 交给模型。
不加入 VLA 辅助动作、任务专用兜底策略或自动完成任务的技能服务。

| 目录 | 责任 |
| --- | --- |
| `benchmarks/simBenchmarks/<benchmark>/` | 环境安装、任务目录、协议、服务、原生动作和评分 |
| `AgentPolicies/<profile>/` | agent 方法、prompt、模型配置、决策循环、结果 |
| `benchkit/` | 公共通信、固定计划调度、记录与报告工具，不替模型决策 |

服务化是职责边界，不等于自动获得 OS 级隔离。部署时仍需限制 actor 的文件和进程访问。
管理凭证、私有任务清单和评分记录只给可信驱动，不给模型。

## 2. 运行顺序

沿用项目已确定的主顺序。**先完成当前 benchmark 的安装与代表任务验证，再逐步扩展其任务清单和案例覆盖。**
已有正常完成的案例是证据，不因整理目录或写文档而重新运行。

| 优先级 | Benchmark / 服务 ID | 安装与协议入口 |
| --- | --- | --- |
| 1 | RoboDojo / `robodojo` | [README](../../benchmarks/simBenchmarks/RoboDojo/README.md) |
| 2 | SimplerEnv / `simpler_env` | [README](../../benchmarks/simBenchmarks/SimplerEnv/README.md) |
| 3 | LIBERO / `libero` | [README](../../benchmarks/simBenchmarks/LIBERO/README.md) |
| 4 | RoboCasa365 / `robocasa365` | [README](../../benchmarks/simBenchmarks/Robocasa_365/README.md) |
| 5 | RoboTwin / `robotwin` | [README](../../benchmarks/simBenchmarks/Robotwin/README.md) |
| 6 | RoboCasa Tabletop / `robocasa_tabletop` | [README](../../benchmarks/simBenchmarks/Robocasa_tabletop/README.md) |
| 7 | VLA-Arena / `vla_arena` | [README](../../benchmarks/simBenchmarks/VLA-Arena/README.md) |

后续补充队列建议为 SIMPLE → MetaWorld → LIBERO-Plus → DOMINO → BEHAVIOR → CALVIN；
这部分是交接建议，不覆盖前七项已确定的顺序。SIMPLE 是人形机器人，不能套用机械臂 EEF 接口。
VLN-CE 等待已获授权的导航资产，暂不启动；真实机器人需要另外确认硬件接入和安全授权。

同一时期最多运行 **2 个模型评测任务**，通常每节点/GPU 一个；先检查实际设备、显存和原生进程占用。
不要只依据 SSH 别名或 CUDA 序号判断资源是否独立。优先级指启动顺序，不要求两路同时空闲才能继续。
资源或授权阻塞时记录原因，可以转到下一个已就绪任务，不能让“跳过”变成“已完成”。

## 3. “每任务五案例”到底是什么意思

目标不是“每个 benchmark 只挑五个任务”，也不是“每个任务反复尝试直到成功五次”。

1. 先列出 benchmark 的原生任务全集和**当前服务实际支持的任务子集**。
2. 对每个已支持任务，在运行前固定最多 5 个有依据的案例：layout、初始状态、变体或 seeded reset。
3. 每个选定案例只尝试一次，完整保留成功、正常失败、工程错误和未尝试项。
4. 只有一个已实现任务、缺少初始化状态或资产不足时，明确缺口，不伪造五种布局。
5. 工程修复后的补测另开 run ID，并关联原错误；不能通过换名字隐去旧尝试。

**Seed 不一定等于 layout。** 不同 seed 可能产生相同或近似几何布局；有的 benchmark 要用原生
layout ID 或固定初始状态数组，单纯改 seed 不会换案例。以每个 benchmark 的协议和任务目录为准。
例如 SimplerEnv 当前适配器用 `seed + episode_index` 生成连续 seeded resets；
RoboDojo 的 `classify_objects` 使用任务目录中预定义的五个 fast layouts，不能把前者的 seed 规则照搬过去。

建议将这类实验命名为 `task-panel5`（不足五例时注明实际数量），不要冒充统一的 CLI 模式。
`fast` 是预选的小样本计划；`max` 是该 benchmark 已核实的原生完整矩阵。
**每个任务做五例、甚至覆盖全部任务，也不自动等于官方 max。**

运行前保存案例清单，至少含：benchmark、协议/观测动作 track、task、原生 case/layout/init-state/seed、
预算、方法版本、模型配置、run ID 和资源位置。清单归可信评测端，私有案例信息不进入模型输入。

## 4. 怎样运行

### 4.1 准备环境和固定配置

在仓库根目录安装公共代码并查看入口：

```sh
python -m pip install -e .
python -B -m benchkit list
python -B -m benchkit serve --benchmark simpler_env --help
```

这些命令不安装原生模拟器和资产，也不代替许可确认。随后：

- 阅读所选 benchmark 的 `README.md`、`EVALUATION_PROTOCOL.md` 和任务目录。
- 安装其独立原生环境，运行环境/设备/渲染诊断；检查机器人和前景，不能只看背景是否正常。
- 检查公开观测、动作单位/坐标系、控制频率、评分与预算。不同 benchmark 不强行统一成 EEF。
- 固定 agent 配置和源码；先完成无模型依赖检查。运行期间不修改活动快照。
- 将 server、可信 client 驱动放在可持续托管的进程中，保留日志和退出状态；不要依赖短命 SSH 会话。

当前参考客户端是 [gpt6-astra-codex-native](../../AgentPolicies/gpt6_astra/README.md)，入口为
`python -m AgentPolicies.gpt6_astra.run`。它使用已配置的 Codex 登录；本指南不要求另建 API key。
模型、推理配置和 CLI 路径按 [profile 说明](../../AgentPolicies/gpt6_astra/README.md) 配置并记录。
`--method-file` 是方法声明，不会自动把任意声明值变成实际运行配置；它经规范化后按声明记录，不与策略有效配置比对。
也可以接入自己的可信驱动，不强制继承 Python Policy。

### 4.2 一个可复用的例子：SimplerEnv 单任务五个 seed

下面示例只针对 `google_robot_pick_horizontal_coke_can`，不是其他 benchmark 的通用任务模板。
先按 SimplerEnv 安装指南准备环境。将以下参数保存为自己的 `simpler-server.json`：

```json
{
  "task": "google_robot_pick_horizontal_coke_can",
  "device": "cuda:0",
  "proprioception": false,
  "interaction_mode": "agent_method",
  "action_rejection_feedback": true,
  "horizon_multiplier": 1
}
```

多 GPU 机器先按 [渲染指南](../../benchmarks/simBenchmarks/SimplerEnv/environment/RENDERING.md)
核对实际 Vulkan 设备，再加入匹配的完整 `expected_gpu_uuid`。不要复制别人的 GPU UUID 或私有路径。

两个终端均在所选仓库快照的根目录，分别使用匹配的 server/client Python 环境。
私下给两端设置相同的 `RSI_SIM_SERVER_TOKEN`（至少 32 位随机 URL-safe 字符）；
不要写进配置文件、命令日志、仓库或模型 prompt。下面的 run ID 只是示例，实际须选择未使用的 ID。

终端 A，原生环境中的 server：

```sh
RSI_RUN_ID=google_robot_pick_horizontal_coke_can-horizontal-can-picking-native-v2-panel5-new
RSI_RUN_ROOT="$PWD/AgentPolicies/gpt6_astra/results/simpler_env/raw/$RSI_RUN_ID"

python -B -m benchkit serve --benchmark simpler_env \
  --parameters /absolute/path/to/simpler-server.json \
  --seed 0 --episodes 5 --port 8765 \
  --output-dir "$RSI_RUN_ROOT/server"
```

确认服务就绪后，在终端 B 启动可信 agent 驱动：

```sh
RSI_RUN_ID=google_robot_pick_horizontal_coke_can-horizontal-can-picking-native-v2-panel5-new
RSI_RUN_ROOT="$PWD/AgentPolicies/gpt6_astra/results/simpler_env/raw/$RSI_RUN_ID"

python -B -m AgentPolicies.gpt6_astra.run \
  --sim-server http://127.0.0.1:8765 --benchmark simpler_env \
  --seed 0 --episodes 5 \
  --max-policy-calls 240 \
  --image-max-edge 480 --recording-mode standard \
  --output-dir "$RSI_RUN_ROOT" --run-id client
```

该示例对应 seed 0–4。server/client 数量和 seed 要匹配；服务启动不等于已经完成模型评测。
历史结果仍按当时的 Direct v3 方法标记，不因更新此启动示例而成为 Native v2 的得分。
跨机器时使用受控 SSH 转发，见 [通信协议](../../benchmarks/simBenchmarks/SERVER_PROTOCOL.md)；
两机同名路径不一定共享存储，分别记录真实位置，结束后只收集闭合的 client 记录。

这里的 240 次调用是**该示例的选择**，最多 5 个动作来自方法配置的默认值；两者都不是所有 benchmark 的规定。
一次决策可以输出多个控制动作，由 agent 驱动逐个发送；server 不强制模型每次走五步。
自愿停止（`safety_stop`、`task_complete`）默认开启，是否使用由模型决定；`--no-safety-stop`
只关闭该策略的仿真自愿安全停止，不关闭原生终止、预算或真实硬件保护。
模型调用、已执行动作决策、控制步和物理子步要分别记录。

换 SimplerEnv 任务时，从 [task catalog](../../benchmarks/simBenchmarks/SimplerEnv/bench_server/protocol/task_catalog.json)
取任务 ID 和 horizon，同步修改配置和 run ID：罐抓取/移动 80，抽屉开关 113，
苹果 200，勺子/胡萝卜/堆块 60，茄子 120。不传 `--max-steps` 时取服务公布的 horizon；
显式传入会覆盖它，manifest 同时记录服务 horizon（未公布时为 null）和是否覆盖。共享 server
不检查 client 的取值；调小即偏离原生预算，部分 adapter 仍会按自身 horizon 截断。不要复制旧 fast campaign 的决策预算当作原生 horizon。
换 benchmark 时，重新核实其动作和案例选择接口；不能只替换 `--benchmark`。

### 4.3 扩展到全部任务

按第 2 节优先级逐项推进，每个任务执行以下流程：

1. 确认任务已在服务中实现；未实现项列入适配清单，不从覆盖分母中悄悄删除。
2. 固定最多五个有效案例和预算，验证服务能枚举这些案例，再启动模型。
3. 托管执行一次；记录状态、动作计数和输出位置。并行任务使用独立服务、端口、输出和模型上下文。
4. 评测结束后先收集结果、确认视频/错误记录及进程清理，再释放资源给下一项。
5. 汇总覆盖表后继续；正常失败不为追求分数重跑。

当前没有可直接调度所有远端服务的统一 `--all --panel5` 命令，也没有中央 campaign 调度。
详见 [工作流选择](../evaluation.md#choose-a-workflow)。
2026-10-06 的 75 例使用了单独的运维托管队列；临时运维脚本不是公开、可移植的全 benchmark 启动器。

## 5. 什么算完成，什么可以修复后重测

| 情况 | 处理 |
| --- | --- |
| 原生成功 | 正常完成，保留记录 |
| 达到已声明预算但失败，或原生判失败 | 正常完成，不重新抽样追求成功 |
| 方法明确选择提前停止 | 保留该方法的结果；不能冒充已跑满原生预算 |
| 安装、渲染、进程、模型通信等工程中断 | 单独记 error；定位和修复后，按批准的恢复计划新开 ID，关联旧记录 |
| 动作 ACK 丢失、是否执行不确定 | 不重放动作、不接着猜状态；保留中断证据，单独处理 |
| 缺少授权资产/硬件条件 | 标明 blocked/unattempted，不绕过许可 |

工程恢复不是无限重试：修复不得偷改任务、控制语义、预算或评分；改方法配置需要单列实验。
明确模型传输错误的有界等待/重试，属于策略运行时机制，不是 reset 或重新评测整个案例。
同一固定案例的旧错误和恢复尝试都要可追溯；报告“75 个选定案例 + 1 次工程补测”这样的实际情况，
而不是声称只有 75 次尝试。

## 6. 结果交付

推荐在模型命名空间保存：

```text
AgentPolicies/<profile>/results/<benchmark>/
  raw/<date-task-short-description-method-panel>/
    server/episodes/<session>/...   原生结果、默认唯一长期视频
    client/                        summary、逐例结果、可选交互记录
  reports/<run-id>/                 面向读者的结果视图
```

默认交互记录启用，也可选 minimal；不是发布资格要求。当前默认长期视频留在 server，
client 保存引用，不重复下载。逐帧图片通常是临时数据；视频不完整或关闭失败时可能保留作兜底证据。
不要在 client 尚未拿到必要记录时清理 server，更不要为展示覆盖旧结果。

从已闭合的 client 记录生成只读报告：

```sh
python -B -m benchkit.reports.basic_result \
  --run-dir /absolute/path/to/closed-run/client \
  --output-dir /absolute/path/to/new-report-directory
```

每份报告应列出：原生任务总量/当前已支持范围、选定/已尝试/正常完成/未尝试数量、成功和失败、
工程错误及补测关联、每任务结果、实际控制步和决策数、协议/方法/模型配置、可用推理开销，
以及原生环境、代码版本、资产来源和输出位置。未知模型后端和开销保持 unknown。
内部哈希审计可以保留，但不是对外主功能或发布门槛。

先按 benchmark 和协议分别展示；不要把开发预算、不同观测 track、Direct/Planned 或不同模型混成总榜。
每任务五例仍是小样本，报告成功数和分母，不把一次成功写成已证明 100% 能力。

## 7. 现在已有的证据与下一步

以下是 **截至 2026-10-07 的已核对快照**，不是实时状态。分开列出“每 benchmark 一个任务的验收”
和“SimplerEnv 每任务五案例”，不混合方法、轮次或分母。
这里的结果属于 `AgentPolicies/gpt6_astra` 下的 agent 方法；请求的模型名不等于已独立认证的后端身份。

### 7.1 跨 benchmark：Direct v3 单任务验收结果

2026-10-05 至 2026-10-06 这轮选定了 13 个 benchmark 各一个任务。
**11 个正常完成：6 个成功、5 个失败；另有 2 个最新尝试是工程中断，尚未通过正常完成验收。**
表格沿用前七项主顺序。单案例成功不代表该 benchmark 的整体成功率为 100%。

| Benchmark | 所选任务/案例 | 最新验收结果 | 模型调用／动作决策／控制步 |
| --- | --- | --- | ---: |
| RoboDojo | `classify_objects`，layout 0，物体分类 | **成功**；原生分数 100/100 | 99／99／483 |
| SimplerEnv | 水平罐抓取 | **成功**；原生成功判定为真 | 33／33／80 |
| LIBERO | spatial task 0，黑碗放盘子 | **成功** | 27／27／113 |
| RoboCasa365 | `NavigateKitchen`，厨房导航 | **成功** | 33／33／163 |
| RoboTwin | `lift_pot`，双臂抬锅 | 失败；达到 400 控制预算 | 156／156／400 |
| RoboCasa Tabletop | `PnPCupToDrawerClose`，杯子放抽屉并关闭 | **工程中断**；Codex 调用失败 | 81／80／400 |
| VLA-Arena | Level-0 fork on cabinet，叉子放柜子 | 失败；达到本轮 300 控制预算 | 64／64／300 |
| SIMPLE | `G1WholebodyBendPickMP-v0`，人形机器人弯腰拾取 | 失败；达到 400 控制预算 | 88／88／400 |
| MetaWorld | `reach-v3`，末端到达目标 | **成功** | 25／25／123 |
| LIBERO-Plus | spatial task 0 / table1 | 失败；达到 220 控制预算 | 47／47／220 |
| DOMINO | `click_bell`，seed 100000，移动铃铛任务 | 原生判失败；目标物越界，MS 29.35 | 99／99／99 |
| BEHAVIOR | `turning_on_radio`，public0 / instance301 | **成功**；原生分数 1.0 | 922／922／922 |
| CALVIN | debug sequence 0，旋转蓝色方块 | **工程中断**；修复后仍发生 Codex 调用失败 | 249／248／248 |

计数与结果解释：

- 模型调用、已执行动作决策、控制步不是同一指标。失败调用可能没有动作；一次决策可以执行多个控制。
  例如 Tabletop 第 81 次调用中断，之前有 80 次已执行决策、400 个控制步。
- CALVIN 上一次中断在 32 次调用／31 次决策／31 步；恢复尝试到 249／248／248 后仍中断。
  两次记录都保留，不能算作原生任务失败，也不能称为已完成一次正常评测。
- RoboCasa365、RoboTwin、SIMPLE、Tabletop 列的是按要求关闭策略自愿 safety stop 后的单独实验，
  不是从历史运行中挑选最高分。此前提前停止、初始化失败等记录仍保留。
- VLA-Arena 的 300 步是本轮所选评测预算，不是底层引擎的 1000 步 horizon；Tabletop 是开发预算，
  CALVIN 使用 debug 资产，RoboCasa365 使用已披露的 `egl-owner-material-clamp-v1` 渲染 track。
  因此不能声称全部已对齐官方完整协议。
- DOMINO 的 MS 29.35 是原生 manipulation score，**不是 29.35% 成功率**。
  RoboDojo 的 100/100 同样是该案例的原生分数，不是整个 benchmark 的统计成功率。

### 7.2 SimplerEnv：全部 15 个 canonical 任务，每任务五个 seed

2026-10-06 这轮使用 `codex-direct/v3`，每任务固定 seed 0–4；共 **75 个选定案例全部正常结束**，
**20 成功、55 失败，本轮案例成功比例为 26.7%**。已于当日 23:18（Asia/Shanghai）完成导出和服务清理。

| 机器人 | 任务 | 成功／案例数 | 本轮成功比例 | 每例原生控制预算 |
| --- | --- | ---: | ---: | ---: |
| Google Robot | 水平罐抓取 | 1/5 | 20% | 80 |
| Google Robot | 垂直罐抓取 | 2/5 | 40% | 80 |
| Google Robot | 直立罐抓取 | 2/5 | 40% | 80 |
| Google Robot | 移动到物体附近 | 0/5 | 0% | 80 |
| Google Robot | 打开上层抽屉 | 0/5 | 0% | 113 |
| Google Robot | 打开中层抽屉 | 0/5 | 0% | 113 |
| Google Robot | 打开下层抽屉 | 0/5 | 0% | 113 |
| Google Robot | 关闭上层抽屉 | 1/5 | 20% | 113 |
| Google Robot | 关闭中层抽屉 | 0/5 | 0% | 113 |
| Google Robot | 关闭下层抽屉 | 1/5 | 20% | 113 |
| Google Robot | 苹果放入抽屉 | 1/5 | 20% | 200 |
| WidowX | 勺子放毛巾 | 3/5 | 60% | 60 |
| WidowX | 胡萝卜放盘子 | 4/5 | 80% | 60 |
| WidowX | 方块堆叠 | 3/5 | 60% | 60 |
| WidowX | 茄子放篮子 | 2/5 | 40% | 120 |

这轮的条件是 RGB、原生 horizon、`agent_method`、动作拒绝反馈；请求模型为 `gpt-6-astra` / `xhigh`，
CLI `0.154.0`，每例最多 240 次调用、每次动作 chunk 最多 5，策略 `safety_stop=false`，不跨案例共享记忆。
使用原生末步成功判定，不把最佳中间帧或肉眼看视频的判断替换为结果。

有一项工程恢复需要单独披露：勺子 seed 0 首次在原生 Git 源码检查阶段超时，0 次模型调用、0 控制步。
修复检查等待时间后，另开 run ID 补测，27 次模型调用、60 控制步，成功。
所以原始记录总共是 **76 次尝试：75 条正常结果 + 1 条原始工程错误**；上表包含补测后的固定 seed 0，
并没有为提高成功率重跑其他正常失败。苹果的成功案例是 seed 4，整例 59 次调用、200 控制步，
不能据此推断首次成功恰好发生在第 200 步。

这些是五个 seeded resets 的小样本比例；不保证五种独立几何布局，**不是官方完整 VM/VA 成绩**。
本表也不与 7.1 中那次单独的水平罐抓取成功合并。

### 7.3 Planned 方法和未完成范围

| 项目 | 已有证据 | 尚缺什么 |
| --- | --- | --- |
| Planned 跨 benchmark 批量轮次 | 两条队列在启动前检查处停止，尚无这轮模型结果 | CALVIN 尚未正常完成，前置检查未通过 |
| 历史独立 Planned RoboDojo 样例 | layout 0：237 调用／236 决策／1053 控制；原生 40/100、未成功，策略 safety stop | 不能代替 Planned 批量轮次，也不能推断规划方法整体优劣 |
| CALVIN / Tabletop | 最新尝试均为工程中断；记录已导出、服务已清理 | 定位调用中断并完成一次正常结束的验收 |
| 其他 benchmark 每任务五案例 | 目前主要是 7.1 的选定单任务验证 | 核对原生任务全集、服务支持范围、五案例选择规则和资产 |
| VLN-CE | 仍处于延期范围 | 已授权导航资产及可执行验证条件 |

当前只能说 **SimplerEnv 已完成这份计划定义的“15 任务 × 5 seed”覆盖**，
不能说其他 benchmark 都完成了所有任务五案例。RoboTwin、DOMINO、BEHAVIOR 等仍有服务任务范围限制，
需要先补齐适配，不是换一个任务字符串就能自动跑完整 benchmark。

### 7.4 接手后的执行清单

1. 保留上述已关闭记录，先处理 Tabletop 和 CALVIN 的工程验收缺口；不把中断当作正常失败交付。
2. 按 **RoboDojo → SimplerEnv → LIBERO → RoboCasa365 → RoboTwin → Tabletop → VLA-Arena**
   的主顺序建立新覆盖计划，再进入第 2 节的补充队列；最多并行两个任务。
3. 对已有正常完成的固定案例登记覆盖，不因扩展计划或重新生成报告而自动重跑。
   SimplerEnv 本轮可以直接登记为已完成，除非另行声明新方法或新协议实验。
4. 每个新任务先确认环境与接口，预先固定五案例（不足五例时说明原因），记录每例的结果和实际计数。
5. 单独记录工程恢复及其旧 run ID；发布时按 benchmark / 协议 / 方法区分，不拼成跨 benchmark 总榜。

详细 task ID、原始 run 目录名、源码版本和工程恢复说明见
[结果快照](../../AgentPolicies/gpt6_astra/results/evaluation-summary-2026-10-07.md)。
结果和视频位于 `AgentPolicies/gpt6_astra/results/<benchmark>/raw/<run-id>/`：
`client/` 是闭合客户端结果，`server/episodes/` 是原生记录与默认长期视频。
这些运行产物不随源码 Git 下载；交接时需要另外提供实际 artifact 位置。
