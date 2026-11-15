# SimplerEnv

SimplerEnv evaluates robot manipulation in simulation using environments designed
to match real robot tasks and visual conditions. This integration supports Google
Robot and WidowX tasks through a benchmark-owned service: task selection,
observations, native actions, execution budgets and scoring are independent of
the participating agent method.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): task selection, budgets and native scoring.
- [Tasks and variants](bench_server/protocol/TASKS.md): aliases, canonical tasks and reference evaluation matrices.
- [Public interface](bench_server/protocol/INTERFACE.md): sensor channels and action semantics.
- [Rendering checks](environment/RENDERING.md): graphics readiness and device selection.

## Benchmark tasks and variation design

The [upstream task overview](https://github.com/allenai/SimplerEnv/blob/c701ea271b16b80616d6fed9713c4a50a0adea3b/README.md#current-environments)
lists 10 task categories: six Google Robot categories (can picking, random-object
picking, move-near, drawer opening, drawer closing and drawer placement) and four
WidowX tasks (spoon on towel, carrot on plate, cube stacking and eggplant in
basket). Its registry provides 25 aliases; orientations, drawer levels and alias
names are not 25 independent task families.

The benchmark uses two evaluation designs. **Visual Matching** aligns simulated
scenes with real task images. **Variant Aggregation** evaluates across changed
visual conditions. The pinned reproduction scripts define nine task families
(random-object picking is an additional environment): VM expands to 864 Google
Robot and 96 WidowX episodes; Google VA expands to 1,992 episodes. These are
separate reference matrices, with different condition sets and denominators.
The [task and variation guide](bench_server/protocol/TASKS.md) details layouts,
object orientations, robot poses and appearance changes for each family.

## Select tasks through this service

The current catalog exposes 15 canonical subtasks, expanding can orientations
and drawer levels:

| Task group | Canonical subtasks | Native control horizon |
| --- | ---: | ---: |
| Google Robot: pick horizontal, vertical or standing can | 3 | 80 |
| Google Robot: move near (`v0`) | 1 | 80 |
| Google Robot: open or close top, middle or bottom drawer | 6 | 113 |
| Google Robot: put apple in initially closed top drawer | 1 | 200 |
| WidowX: spoon on towel, carrot on plate, stack cubes | 3 | 60 |
| WidowX: eggplant in basket | 1 | 120 |

A service selects one `task`; `evaluation_mode` then fixes its episodes.
In `fast` and `example`, episode `i` uses reset seed `--seed + i`; changing the
seed samples the native prepackaged reset and does not guarantee a distinct layout.

| `evaluation_mode` | Selection | Episodes | Step cap |
| --- | --- | ---: | --- |
| `fast` (default) | Selected task, seeds `--seed + 0..4` | 5 | Native task horizon |
| `max` | Selected task's pinned-script matrix chosen by `reference_matrix` | 24–600 per task | Native task horizon |
| `example` | First `fast` episode (seed `--seed`) | 1 | Native task horizon |

`max` runs one reference matrix per service run, as upstream runs one script.
Select it with `reference_matrix`: `visual_matching` (default) or
`variant_aggregation`, which exists for Google Robot tasks only; the parameter
is rejected in `fast` and `example`. Episodes per task:

| Task | `visual_matching` | `variant_aggregation` |
| --- | ---: | ---: |
| Each pick can orientation (3 tasks) | 100 | 275 |
| Move near `v0` | 240 | 600 |
| Each open/close drawer (6 tasks) | 36 | 63 |
| Apple in closed top drawer | 108 | 189 |
| Each WidowX task (4 tasks) | 24 | — |
| **All 15 tasks, as separate runs** | **960** | **1,992** |

`max` builds each episode with the script's explicit environment kwargs and
seedless reset options, so `--seed` does not change its scenes. Report VM and
VA separately, never pooled. Drawer/apple `max` uses the native ray-tracing
shader, which is unverified on the current runtime. See the
[protocol](EVALUATION_PROTOCOL.md#reference-matrices-max) for details.

`--episodes N` runs the first N episodes of the selected mode. Protocol IDs
name the selection and mode, e.g. `simpler-env-c701ea2/prepackaged-seeded/rgb/fast/v1`,
`simpler-env-c701ea2/reference-visual-matching/rgb/max/v1` or
`simpler-env-c701ea2/reference-variant-aggregation/rgb/max/v1`.

## Observations, actions and scoring

| Contract | Google Robot | WidowX |
| --- | --- | --- |
| RGB camera | `overhead_camera`, 512 × 640 | `3rd_view_camera`, 480 × 640 |
| Native control frequency | 3 Hz | 5 Hz |
| Arm target | Measured-pose delta, base-aligned (`ee_align`) | Accumulated target delta, base-aligned (`ee_align2`) |
| Gripper | Positive closes; negative opens; zero holds | +1 open; −1 closed; zero intermediate |

The default observation is current native RGB and language. An explicitly
selected RGB+joint-position track adds 11 Google Robot or 8 WidowX encoders;
see the [joint order and units](bench_server/protocol/INTERFACE.md#joint-position-order).
Object poses, depth, segmentation, reset metadata and native scores are not
public observations.

Each control is seven finite values:
`[dx_m, dy_m, dz_m, rx_rad, ry_rad, rz_rad, gripper]`. Rotation is an axis-angle
vector, not Euler angles. Both deltas use robot-base axes, not rotating tool
axes; [the interface](bench_server/protocol/INTERFACE.md#actions) explains
WidowX's retained-target rotation pivot and the bounds. Native low-level control
performs the command without task planning.

Success is the **last executed native step's** `info["success"]`. Intermediate
success does not terminate this benchmark and is not substituted for the final
score. Preserve call, action-decision and control counts separately.

`horizon_multiplier=1` retains the native horizons above. Explicit 2× horizons
are a separate track with a distinct protocol identity. Action
grouping and inference timing belong to the agent driver; they do not extend
the native budget. See [the protocol](EVALUATION_PROTOCOL.md) for exact conditions.

## Install the environment

Use a Linux NVIDIA node with a separate Python 3.10 environment. From the
repository root, replace the source path with an owned installation directory:

```bash
conda env create -f benchmarks/simBenchmarks/SimplerEnv/environment/environment.yml
conda activate starvla-rsi-simpler

export SIMPLERENV_ROOT=/absolute/path/to/native/SimplerEnv
git clone --recurse-submodules https://github.com/allenai/SimplerEnv.git "$SIMPLERENV_ROOT"
git -C "$SIMPLERENV_ROOT" checkout c701ea271b16b80616d6fed9713c4a50a0adea3b
git -C "$SIMPLERENV_ROOT" submodule update --init --recursive

python -m pip install \
  -c benchmarks/simBenchmarks/SimplerEnv/environment/constraints.txt \
  -e "$SIMPLERENV_ROOT/ManiSkill2_real2sim" -e "$SIMPLERENV_ROOT" -e .
```

The ManiSkill2_real2sim submodule pin is
`ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682`. The adapter verifies both revisions
and tracked modifications before reset. Use the assets shipped with that
recursive checkout. Model weights and training datasets are not required.

The native renderer needs graphics libraries and a working NVIDIA Vulkan ICD,
in addition to CUDA. Prefer the system ICD; the provided
[descriptor](environment/nvidia_icd.json) can register an already-installed
graphics library in containers that lack the descriptor. Run the separate
readiness diagnostic using the native environment:

```bash
python benchmarks/simBenchmarks/SimplerEnv/environment/verify_environment.py
```

This performs reset/render and constant-action checks, not agent evaluation.
Inspect the robot and objects, as a photographic background can hide a black
foreground. Validate both IBL and drawer-task RT rendering. On multi-GPU nodes,
first follow the [renderer-only device check](environment/RENDERING.md#first-verify-the-actual-gpu-without-starting-a-task):
CUDA visibility alone does not prove Vulkan device selection.

## Start the benchmark service

Copy [server.example.json](server.example.json) to an operator-owned file and
choose the task, GPU, observation track, budget and, for `max`, the
`reference_matrix` before starting. The example
selects the horizontal-can task's native 80-control horizon, one seeded reset,
explicit `interaction_mode: "agent_method"` and `action_rejection_feedback: true`.
The alternative `single_response` and fail-fast tracks retain separate declared
conditions; omitted parameters do not inherit the example's values.

Set a strong `RSI_SIM_SERVER_TOKEN` privately for the server and trusted driver.
From the prepared native environment, use a new output directory:

```bash
python -B -m benchmarks.simBenchmarks.SimplerEnv.server \
  --parameters /absolute/path/to/simpler-server.json \
  --seed 0 --episodes 1 --port 8765 \
  --output-dir /absolute/path/to/results/simpler_env/your-run/server
```

The service binds loopback and fixes its schedule without resetting a task.
Use authenticated SSH forwarding for a driver on another node. A compatible
driver connects through the [shared wire protocol](../SERVER_PROTOCOL.md);
[agent integration](../../../docs/agent-methods.md) describes the separate
participant side. No provider, prompt, agent library or action chunk size is
selected by this launch command.

## Directory responsibilities and results

`server.py` is the public launcher; `bench_server/adapter.py` defines the public
contract and native bridge. `bench_server/protocol/` contains task definitions,
selection and interface documents. `environment/` holds source pins and readiness
tools. Deployment paths and credentials belong to operator configuration.

Keep method implementations under `AgentPolicies/<agent>/` and generated reports
and evidence under `AgentPolicies/<agent>/results/simpler_env/`. Reports identify the selected
task/reset denominator, protocol, native outcome, counters and typed errors.
Optional interaction histories and videos follow the shared
[recording policy](../../../docs/recording.md); native videos remain on the
server by default. See [evaluation and reporting](../../../docs/evaluation.md)
for connecting a method and inspecting closed results.
