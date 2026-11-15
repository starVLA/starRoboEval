# 将一个 benchmark 接入 Bench Server

这份指南面向新增或整理仿真 benchmark 的贡献者。目标不是把原生 Python API 原样暴露给模型，而是建立可复现、可审计的机器人交互边界：模型根据声明的观测生成动作，服务执行动作并保留原生评分。

先看[架构图解](../assets/bench_server/index.html)，再按本文实施。线协议以 [SERVER_PROTOCOL.md](../benchmarks/simBenchmarks/SERVER_PROTOCOL.md) 为准，目录与验收要求以 [SERVICE_CONVENTIONS.md](../benchmarks/simBenchmarks/SERVICE_CONVENTIONS.md) 为准。本文不另建一套协议。

## 1. 先明确边界

服务化有两个目的：隔离仿真神谕信息；让策略面向机器人能力，而不是依赖 simulator 内部特权。

评测对象是完整 agent 方法，可组合多个通用模型、规划、记忆与工具。
直接控制限制环境权限和执行接口，不限制内部思考方式；按服务协议接入，
Python Policy／SDK 是可选便利。沿用原生执行预算，推理开销单独披露。
详见 [方法接入](agent-methods.md)。

- 可以公开协议声明的 RGB、机器人自身关节、末端位姿及其他允许的传感器观测。说明数据是测量值、估计值，还是上一条命令；不能把夹爪目标当成实测开度。
- 不向模型公开物体真值、隐藏 reset 配置、奖励、成功谓词、私有日志或原生环境句柄。评分由原生评测端产生，不由模型看视频自评。
- 固定的机器人运动学、IK 和原生控制器可以执行动作；服务不得根据物体真值选抓点、规划任务或插入另一个策略代替模型。
- 复用 RoboDojo 的组织方式，不照搬它的 EEF 动作。SIMPLE 是人形机器人；各 benchmark 保留自己的关节、末端、导航或其他原生动作语义。

sim/real 共用的是接口设计原则，不是统一动作维度或现成的硬件后端。需要逐项对齐传感器来源、单位、坐标系、控制周期、观测新鲜度和执行反馈。仿真等待推理时可以暂停推进，真机不能暂停物理世界；硬件看门狗、失联保持、急停、复位授权与评分必须另行实现和验证。当前仓库没有真机后端。

## 2. 按职责放置文件

```text
benchmarks/simBenchmarks/<Benchmark>/
├── README.md                       # 安装、启动与当前支持范围
├── EVALUATION_PROTOCOL.md          # 任务、观测、动作、计数、评分
├── server.py                      # benchmark 自有启动入口；供统一选择器委托，import 无副作用
├── server.example.json            # 部署参数，不放密钥或个人路径
├── bench_server/
│   ├── adapter.py                 # 公开契约与原生执行的衔接
│   ├── protocol/                  # 需要时放任务 catalog、计划与校验
│   └── native_worker_client.py    # 需要独立原生进程时使用
└── environment/                   # 原生运行、安装、版本与资产检查

AgentPolicies/<agent>/             # 模型调用、prompt、记忆、决策循环
└── results/<benchmark>/           # 该模型的报告与证据索引

benchkit/sim_server/                # 共享传输、会话、序列与 artifact 机制
benchkit/                           # 公共契约、记录、服务源码快照、审计和报告
```

`bench_server/protocol/task_catalog.json` 这类文件是评测协议数据，不是训练数据，也不是资产安装配置。任务不需要各复制一个 server；同一接口的新任务扩展 catalog 和原生绑定即可。并非每个 benchmark 都必须有相同文件名或独立 worker，避免添加空层和兼容转发壳。

模型侧的 trusted driver 持有服务凭据，负责把模型动作提交给服务、保存结果；模型 Actor 只接收公开观测和反馈。`benchkit/sim_server` 是两端复用的通信库，不是第三个决策服务。本版没有中央 campaign 调度。不能再复制一份通信实现到 `benchmarks/simBenchmarks/service/`。

当前源码根目录是 `benchmarks/`、`AgentPolicies/`、`benchkit/`，不保留旧入口兼容壳。
旧部署仍可能看见被 Git 忽略的缓存、视频或历史索引；这不代表旧源码入口仍然有效，
也不应直接删除这些文件。参见[目录迁移说明](package-migration.md)。

## 3. 先核实原生协议，再写 adapter

从上游实际 evaluator、环境实现和固定配置取得定义，不凭任务名称猜默认值。在 `EVALUATION_PROTOCOL.md` 中记录下表，并链接对应源码版本或资产 manifest。

| 要核实的内容 | 必须写清楚 |
| --- | --- |
| 版本与环境 | 原生仓库 revision、Python/SDK、资产版本、许可、GPU 与渲染要求。资产和解释器路径由操作者配置，不硬编码某位用户的目录。 |
| 任务与计划 | task ID、任务数、变体/layout、每例 seed/初始化、尝试次数、顺序，以及当前实现的子集。 |
| 观测 | 相机名称、顺序、尺寸、颜色和时间语义；机器人 state 的每个字段及来源；公开白名单和私有字段。 |
| 动作 | 维度、字段顺序、单位、坐标系、绝对/增量、四元数顺序、夹爪语义、原生有效域及控制器。 |
| 控制与终止 | 一次控制对应几个 physics ticks、控制频率、horizon 的实际单位、何时检查边界、原生成功/失败/截断条件。 |
| 评分 | 原生 success 与部分分数的来源和更新时机，是否存在有副作用的评分调用，以及最终结果怎样保存。 |

`fast` 是预先声明的小计划，每个选定 case 只尝试一次；保留失败，不按结果补抽。`max` 必须覆盖已核实的原生任务/变体/episode 矩阵。没有验证完整矩阵时，明确写“不支持 max”，不能只提高 horizon 就称为 max。

增加观测、改变动作含义或控制时序，需要明确的新协议身份、实现与验证。端口、GPU、资产路径等部署参数可以配置；一个 JSON selector 本身不能创造新协议。

版本应分开记录：公共通信是 `starvla-rsi.sim-server/v1`；RoboDojo 当前机器人协议是
`robodojo-ee67a14/classify-objects-fixed-layouts/rgb-proprio28-eef16/<mode>/v1`（fast/example），
`max` 为 `robodojo-ee67a14/classify-objects-reset-stable-layouts/rgb-proprio28-eef16/max/v1`；模型侧当前方法是
`gpt6-astra-codex-native`。它们分别描述通信、机器人能力和 agent 方法，并不需要同步升版。
能接入同一服务不等于复现旧方法的成功率；也不要将 Dojo 的 EEF16 接口套用到 SIMPLE 等其他机器人。

绝对关节目标接口还应检查机器人自身状态是否足够明确。原生观测里的某个
`joint_action` 字段若是驱动目标，不能把它当成实测编码器，也不能因此认定
没有可用的机器人状态；继续查证原生机器人是否另有实测关节接口。一个 state
向量可以同时含实测关节角和上次夹爪命令，但字段名、来源及单位必须分别说明。
有意采用 RGB-only 也应明确声明其限制；补充机器人状态需升级协议，不能回写旧轮次。

## 4. 实现原生桥接与公共入口

实现 [BenchmarkAdapter 和 EpisodeSession](../benchkit/interfaces.py)，参考 [RoboDojo adapter](../benchmarks/simBenchmarks/RoboDojo/bench_server/adapter.py)，但保留本 benchmark 的原生语义。

| 接口 | 责任 |
| --- | --- |
| `descriptor` / `observation_spec` / `action_spec` | 声明版本、能力与动作/观测规格。 |
| `episodes(seed, limit)` | 返回确定的 `EpisodeSpec` 计划；不 reset、不推进环境。 |
| `open_episode(episode)` | 绑定已声明的 case，构造 session；不能接受模型提供的隐藏 reset 参数。 |
| `reset()` | 初始化一次，输出公开 `Observation`；私有元数据留在评测端。 |
| `step(action)` | 执行一条协议动作，返回公开观测与终止状态；不要把原生 `info` 字典整体透传。 |
| `metrics()` / `artifacts()` / `close()` | 提供私有原生结果与证据并释放资源；读取评分不能额外推进任务或重复触发有副作用的 scorer。 |

需要独立 Python/SDK 时，将执行放进 `environment/` 下的私有 worker，由 `bench_server` 连接。它不是第二个公开策略接口。import、factory 构造、服务启动和 `describe` 均不得触发原生 reset、控制或模型调用。

根目录 `server.py` 提供 `main(argv=None)` 和惰性的 adapter factory，调用现有的 [shared launcher](../benchkit/sim_server/launch.py)。工厂校验参数白名单，不静默接受拼错的字段。完整命名 panel 使用 `require_complete_schedule=True`，防止 `--episodes` 截断计划。仓库内的协议文件、worker 和版本定义通过源码清单及 `supplemental_sources` 纳入冻结；部署时的原生运行/资产 manifest 另存为评测端私有来源证据。只能排除声明过的运行缓存，不能排除动作、评分或视频证据。

将实际采用的预算公开到 `describe`：原生执行 horizon `environment_step_cap`；benchmark 规则限定模型调用次数时公布 `max_policy_calls`。driver 可以覆盖二者，manifest 记录服务值与是否覆盖。重规划间隔和每次执行几步属于策略，服务不替策略公布 `replan_interval`，也不把调用次数或前缀与执行上限耦合；只有观测接口确实强制控制前缀时才声明 `required_replan_interval`。注明哪些是 benchmark 限定，哪些允许 driver 配置；不能已在内部实施控制上限，对外却只留下未解释的空值。

### 动作约束放在哪一端

服务验证协议本身：字段、类型、维度、有限值、单位四元数等确有要求的格式，以及原生接口的合法域。不要额外发明关节 soft limit、裁剪、5 cm 步长或“至少 50 次才能放弃”等策略偏好；这些可选约束归 `AgentPolicies/<agent>`。保持原生控制器自身行为，真实硬件的安全控制也不能被策略绕过。

在支持动作拒绝反馈的协议中，纯校验失败应在任何执行与 sequence 消耗之前拒绝，返回 `invalid_action` 和 `executed=false`。下一次计数的决策调用可以根据同一份已确认观测修正动作，不能通过被拒绝的动作免费获得新观测。当前参考 driver 为此配置有限决策调用保护上限；它不是全仓库统一的模型推理预算。若执行可能已经发生，或发生模型服务/CLI/原生运行错误，不能伪装成一次安全的动作拒绝。

## 5. 复用一次性会话和可靠计数

共享传输采用带认证的 JSON RPC，wire ID 为 `starvla-rsi.sim-server/v1`。公开给模型的是观测/动作契约；完整管理 RPC 只交给 trusted driver。

```text
describe → open（认领固定 case）→ reset（一次，sequence=0）
         → step（严格递增的 sequence）… → finish → read_artifact
```

- 在原生创建/初始化前先认领 case；初始化失败也留下已认领的错误记录，不能自动重新入队。
- 每个服务实例同时只有一个 active episode。并行评测使用独立实例、输出目录与资源分配，不共享可变环境。
- 网络超时或 ACK 丢失不代表动作未执行。不能盲目重放 `step` 或 `reset`；执行结果不确定时停止并保留证据。
- `metrics` 属于评测端；`finish` 闭合后固定文件清单，按相对路径、普通文件和 SHA-256 校验证据传输。
- 当前服务仅支持绑定 `127.0.0.1` / loopback。密钥只交给服务和 driver，跨节点使用受控转发。进程分离不等于 OS sandbox；不受信任 Actor 还需要文件、凭据和进程权限隔离。

独立记录决策调用数、可测的模型推理请求与组件用量、已执行动作决策数、客户端 ACK 控制数、原生执行控制数与 physics ticks。一次决策可以使用多个模型、发出多条控制，但没有全仓库通用的“五步一次决策”。被拒绝、stop-only 和异常调用也要按实际记录计入调用统计，不能和已执行决策混为一谈。

动作 chunk 长度、同一目标重复几次、何时重新思考由 policy 和 trusted driver 选择。
共享 `step` 请求只接受一条动作，不接收“替模型重复 N 次”的指令；每条控制都有自己的
sequence 和 ACK。原生物理子步、固定插值、终止与总执行预算仍归 benchmark。
已有 `required_replan_interval` 约定应显式迁移，不能在整理目录时改变。

特别测试 horizon 的最后一步：原生动作可能执行后，终止判定或回传才报错。此时原生计数与 ACK 计数可以不同；不能把已执行控制抹成 0，也不能将基础设施错误写成“正常达到 horizon”。无法确认的量标为未知，不补造计数。

## 6. 注册、打包与启动

接入不止新增一个 `server.py`。按本 benchmark 的实际情况核对：

- 在 [统一服务选择器](../benchkit/sim_server/cli.py) 的显式表中登记 canonical ID、module 和仓库文档路径；不把未实现项或硬件占位列为可启动服务。只惰性委托已有 `server.main(argv)`，不能绕过它重新建 factory。
- 服务通过自身的 `SUPPLEMENTAL_FILES` 声明完整 adapter、协议与 worker 文件；共享服务源码采用 [source snapshot](../benchkit/source_snapshot.py) 的独立 service 范围，不依赖其他 benchmark 或模型文件。
- [pyproject.toml](../pyproject.toml) 纳入所需 Python 包及 JSON 等协议数据；从安装后的包运行，不只在源码目录里碰巧成功。
- 为本次接入准备可复核的轻量契约验证，覆盖服务约定、公开输入与执行生命周期；按实际运行记录结果。公开最小检查为 `make check` 与 `make smoke`；契约测试是本地工作检查，与生成产物一样不进入公开源码。
- 更新本 benchmark 的 README、评测协议、部署参数示例和 [SERVICE_SUPPORT.md](../benchmarks/simBenchmarks/SERVICE_SUPPORT.md)；明确实现范围、已验证层级和未解决问题。

先按该 benchmark 的 `environment/` 说明安装环境。数据许可需单独满足；服务可 import 不等于资产、渲染或原生初始化已就绪。检查正确的 Python、依赖路径、GPU/渲染设备和真实画面，避免把黑帧当作正常观测。

以现有 RoboDojo 为例，在仓库根目录或已安装环境中启动（先完成其 [环境准备](../benchmarks/simBenchmarks/RoboDojo/README.md)）：

```sh
# 通过安全的环境注入方式设置 RSI_SIM_SERVER_TOKEN；勿把真实密钥写入配置或 Git。
# /absolute/... 是占位路径，需替换为本次部署配置和全新的输出目录。
rsi-bench serve --benchmark robodojo \
  --parameters /absolute/robodojo-server.json \
  --seed 20260907 --port 8765 \
  --output-dir /absolute/new-run/server
```

token 要求 32–256 个 URL-safe 字符。先验证启动和 `describe` 无原生副作用，再使用模型目录下的 driver 连接服务；不要绕过 server 直接操作仿真做“等价测试”。具体 runner 参数见 [运行指南](evaluation.md) 和对应模型的说明，不复制 RoboDojo 的任务、预算或控制频率到其他 benchmark。

## 7. 按证据层级验收

采用“实现 → 独立审核 → 回归验证 → 修正”的循环。审核者检查观测白名单、隐藏 scorer、动作语义和计数，不仅检查目录是否整齐。每一层分别报告，上一层通过不能代替下一层。

| 层级 | 最低检查 | 不代表什么 |
| --- | --- | --- |
| 离线契约与回归 | import 无副作用；参数与 schema；计划确定性；重复 claim/sequence；动作拒绝不执行；评分不泄露；close、故障、计数和 artifact 校验。 | 不代表 simulator、资产或模型能运行。 |
| 原生短交互 | 经授权新开独立诊断 run，不调用模型或任务求解策略；通过 server 真实 reset、至少 1–2 次控制、检查 RGB/state、关闭并保留原生日志及媒体。 | 不代表任务成功或完整评测通过。 |
| 模型单例 | 预声明 task/case/seed、协议和预算，通过同一 server 完成一次尝试；保留成功、任务失败或基础设施错误。 | 不代表全 benchmark 的 SR。 |
| 原生完整矩阵 | 核实任务、变体、种子、horizon、控制器、观测及评分条件，与原生 full schedule 对齐。 | 条件不同的结果不能直接声称复现参考 SR。 |

运行公开的 catalog 检查与自检：

```sh
make check smoke PYTHON=python3
```

使用 Python 3.10 及以上；两者都不启动原生模拟器或调用模型，也不代表任何 benchmark
已完成原生验收。契约测试只构造合成环境、临时文件及假的服务/策略，作为本地工作检查保留，
不进入公开源码；新集成根据实际接口准备，并在稳定源码快照上执行。按实际执行过的检查报告结果，
不能将脚本清理、目录存在或历史通过记录当作当前验收通过。

清理与接入改动只做连接层验证：运行 `make check` 与 `make smoke`，再连接运行中的服务，确认 describe、claim、reset、step 可用；不为此运行完整评测。

不要因测试失败静默重跑正式 case。先保存闭合错误和原因，修复后在获准的新轮次中使用新 run ID；旧结果不覆盖。短交互测试也不能混入正式 SR 分母。

模型首轮主动放弃、0 个控制步，可能是一份有效的失败记录，但没有验证模型的
机器人动作链路。应核查实际发送的图像/state/动作契约、模型原始停止输出和
停止解析分支，区分能力不足、策略选择与观测接口缺失；不能仅凭“进程正常退出”
就称模型控制验收通过，也不要强制输出盲目动作来凑验收步数。

## 8. 发布前检查

- 公共主线是选择 benchmark → agent 接入 → 查看交互和结果。`rsi-bench list` 列服务，`rsi-bench serve --benchmark <id> --help` 显示对应启动参数；源码运行可用 `python -m benchkit`。不是新增中央决策层，也不统一不同机器人的动作空间。
- 交互记录可选、默认启用，不是参评或发布门槛；[basic_result](../benchkit/reports/basic_result.py) 无事件／源码快照也能导出结果。客户端关闭保存不等于原生 server 停止录像；参见 [记录能力](recording.md)。
- 当前默认长期视觉产物是 server 保存的原生视频，client 保存清单与位置引用，不自动下载第二份。帧图像在运行中仍可供模型使用；服务闭合并通过视频文件完整性与数量检查后才移除可清理帧，缺失视频时保留帧，清理失败时保留剩余帧并记录已移除项。服务 `--retain-frame-images` 和客户端 `--copy-server-media` 是分别配置的显式选项。
- 公共文档不依赖 `project_readmes/`、个人绝对路径、SSH 别名或未说明的手工补丁。
- 源码、环境清单、协议和任务计划可追溯；模型身份与实际可核验的调用证据分开，未知项不补造。
- 发布报告位于 `AgentPolicies/<agent>/results/<benchmark>/`，优先展示任务、策略调用输入、已记录输出、动作与反馈、计数、终止和结果。闭合 client-run 可用 [interaction_history](../benchkit/reports/interaction_history.py) 导出自包含 HTML/JSON；首版不复制媒体或补造原始会话，详见 [运行指南](evaluation.md#inspect-and-report)。
- 服务端源码快照、运行记录的 git revision/dirty 标记与闭合记录一致性审计作为内部支撑保留，不是用户看交互的前置手工流程。上游 Git revision、环境/控制器与资产来源等有用复现信息可公开，但只采用已记录且明确允许的字段。原始视频、日志和缓存按规则忽略或持久化，不递归发布私有 metadata/info。
- 密钥只留在操作者的安全凭据存储与受信任进程中；不得写入 Git、源码快照、模型输入或 artifact 清单。
- 任务/布局、调用次数、控制步、终止原因、原生 success 与部分分数分别可查。`40/100` 原生部分分数不是 `40%` 成功率；报告计划、尝试、完成和错误数量，不藏失败样本。
- 将本次验收的具体协议、范围、结果和剩余阻塞写清楚。“14 个开发态服务入口”不等于“14 个 benchmark 已完整验证”，最新范围查 [支持矩阵](../benchmarks/simBenchmarks/SERVICE_SUPPORT.md)。

新增模型通常只改 `AgentPolicies/`；新增任务通常扩展 benchmark 的协议数据和原生绑定；新增动作/观测语义要改协议；新增通用报告才进入 `benchkit/`。保持这些边界，才能继续扩展 benchmark，而不为每个模型复制一套仿真代码。
