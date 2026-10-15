# SimplerEnv

This integration follows the [RoboDojo-derived service conventions](../SERVICE_CONVENTIONS.md).
Its native delta actions, sensor tracks and final-step scoring remain SimplerEnv-specific.

This benchmark can run as an independent SIM service via [server.py](server.py).
Start from [server.example.json](server.example.json), adjust deployment paths/GPU
before launch, and follow the [shared server workflow](../SERVER_PROTOCOL.md).
The server owns native reset/control/scoring; the evaluator uses the client, and
the model receives only permitted observations. Native service-mode validation is separate from adapter availability.

Evaluate a policy through `SimplerEnvBenchmarkAdapter`: the model receives only
declared observations and returns action chunks; the adapter owns the simulator,
controller and native scoring. No model training is required.

- [Evaluation protocol](EVALUATION_PROTOCOL.md): fast/full scope, budgets and scoring.
- [Tasks and variants](bench_server/protocol/TASKS.md): 25 aliases, 15 canonical subtasks and native VM/VA matrices.
- [Policy interface](bench_server/protocol/INTERFACE.md): observations, actions, transport and isolation.
- [Rendering checks](environment/RENDERING.md): preflight and graphics-driver troubleshooting.

The prepackaged fast track is executable. Native full VM/VA evaluation is
documented but is not yet implemented by the unified adapter; fast results must
not be presented as full reference scores.

## Directory responsibilities

```text
SimplerEnv/
├── server.py                  # stable public launch entrypoint
├── server.example.json        # example deployment and selected-track settings
├── bench_server/
│   ├── adapter.py             # native bridge, observation allowlist and scoring
│   └── protocol/              # task catalog, selection plan and interface reference
└── environment/               # upstream pins, installation and rendering checks
```

`bench_server/protocol/` is benchmark definition data, not simulator assets or
server credentials. The catalog's bytes and task order are unchanged by this
layout migration. [plan.py](bench_server/protocol/plan.py) owns task selection.
The canonical adapter lives in `bench_server/adapter.py` and lazily
imports the native simulator on reset, solely inside the service process.
Model prompts, action selection and results stay under `AgentPolicies/<profile>/`;
`benchkit/` supplies shared records, source capture and reports.

## Launch the benchmark service

After verifying the native environment, copy `server.example.json` to your own
configuration and select its task, device, observation track and budgets before
launch. The example selects the horizontal-can task's native 80-control horizon,
`interaction_mode: "agent_method"` and explicit action-rejection feedback. A
method's decision-call cap and action prefix are configured on its driver; they
do not extend the native horizon. The separately labeled decision-budget track
remains available when explicitly selected. Use a fresh output directory:

On multi-GPU hosts, first run the [renderer-only device preflight](environment/RENDERING.md#first-verify-the-actual-gpu-without-starting-a-task).
Keep its exact `device` selector and add `"expected_gpu_uuid": "GPU-..."`
(the complete verified UUID) to the server parameters. This optional deployment
assertion rejects an unexpected physical device before any public observation;
it never silently selects a replacement GPU. CUDA ordinal visibility is not
proof of Vulkan device selection.

```bash
# Activate the native SimplerEnv environment first; set this secret privately.
export RSI_SIM_SERVER_TOKEN='<32-or-more-character-random-URL-safe-secret>'
python -B -m benchmarks.simBenchmarks.SimplerEnv.server \
  --parameters /absolute/path/to/simpler-server.json \
  --seed 0 --episodes 1 --port 8765 \
  --output-dir /absolute/path/to/AgentPolicies/your_agent/results/simpler_env/raw/your-run/server
```

The listener binds loopback. Use the [shared transport](../SERVER_PROTOCOL.md)
for a trusted driver on another machine. Keep its bearer token and administrative
client out of the model actor's workspace. There is no background control tick
while the policy is thinking; lost action acknowledgments are not replayed.
Each predeclared episode is claimed once, including failures.

The service preserves this benchmark's seven-value delta-action interface;
it does **not** expose RoboDojo's absolute dual-arm EEF16 action or robot-feedback
extension. Choose a compatible agent method, not an action-vector conversion
guessed by a server. Explicitly select `interaction_mode: "agent_method"` for
methods that use internal inference or local tools over permitted public data,
including the current Codex CLI method. This adds `/agent-method` before `/v1`
in the selected protocol identity. Omission or `"single_response"` preserves
the historical one-provider-request-per-call track and its existing ID. Neither
the service nor the CLI wrapper verifies hidden provider request counts. The
new mode grants no extra observations, native access, resets or control budget;
see [interaction modes](EVALUATION_PROTOCOL.md#interaction-modes).

The example explicitly selects `"action_rejection_feedback": true`, as required
by the current Codex native-vector driver's default feedback behavior.
This adds `/action-feedback` before the optional `/agent-method` and final `/v1`
suffixes: a rejected action does
not execute, and its bounded validation issue reaches the next counted call
with the last acknowledged observation. The omitted/default `false` setting
preserves historical fail-fast semantics. The selected flag is captured in the
service parameters; see [the protocol](EVALUATION_PROTOCOL.md#optional-rejected-action-feedback).

## Install the evaluation environment

Use a Linux NVIDIA node with a separate Python 3.10 environment. From the
repository root:

```bash
conda env create -f benchmarks/simBenchmarks/SimplerEnv/environment/environment.yml
conda activate starvla-rsi-simpler

export SIMPLERENV_ROOT=/absolute/path/to/benchmarks/SimplerEnv
git clone --recurse-submodules https://github.com/allenai/SimplerEnv.git "$SIMPLERENV_ROOT"
git -C "$SIMPLERENV_ROOT" checkout c701ea271b16b80616d6fed9713c4a50a0adea3b
git -C "$SIMPLERENV_ROOT" submodule update --init --recursive

python -m pip install \
  -c benchmarks/simBenchmarks/SimplerEnv/environment/constraints.txt \
  -e "$SIMPLERENV_ROOT/ManiSkill2_real2sim" -e "$SIMPLERENV_ROOT" -e .
```

The submodule pin is `ef7a4d4fdf4b69f2c2154db5b15b9ac8dfe10682`.
The adapter checks upstream revisions and tracked modifications before reset.
Use the assets shipped with the pinned recursive checkout. Model checkpoints,
training data and a StarVLA model server are not required.

The constraints avoid incompatible NumPy/OpenCV combinations and select an
available Ruckig wheel. If your deployment requires a network proxy, use its
existing configuration; do not put credentials into protocols or model files.

## Validate graphics before evaluating a model

CUDA visibility alone is insufficient: the native renderer also needs graphics
libraries and a working NVIDIA Vulkan ICD. Prefer your system's NVIDIA ICD. If
the graphics library is already installed but the container lacks its ICD
registration, this process-local example uses the provided descriptor:

```bash
export VK_ICD_FILENAMES="$PWD/benchmarks/simBenchmarks/SimplerEnv/environment/nvidia_icd.json"
python benchmarks/simBenchmarks/SimplerEnv/environment/verify_environment.py
```

The verifier performs environment/reset/render and constant-action checks, not a
model evaluation. Use `--help` for task and diagnostic-step options. Check both
IBL and drawer-task RT rendering: a detailed photographic background can hide a
black robot or foreground. [RENDERING.md](environment/RENDERING.md) explains this distinction
and matching driver-data requirements. Simulator-free `catalog` or `list`
commands do not establish graphics readiness.

## Connect an agent

After service readiness, launch a compatible model-owned driver. For the current
Codex native-vector method, follow [client README](../../../AgentPolicies/gpt6_astra/README.md).
Model configuration, prompts, memory and decision loops belong to that profile,
not this benchmark. The service exposes only its declared observation/action
contract, not a task-solving RPC or the simulator handle.

See [the evaluation workflow](../../../docs/evaluation.md) for source capture and
closed-record reporting. Protocol and call-accounting restrictions apply to each
selected method; a method name alone does not establish provider metering or native parity.

## Results and offline review

Outputs belong under `AgentPolicies/<model-profile>/results/simpler_env/`:

- `raw/`: campaigns, manifests, event streams, responses, source snapshots and original media.
- `reports/` and `indices/`: task coverage, typed failures and hash-bound summaries.
- `media/`: presentation copies of closed videos, named with task IDs/descriptions.

Raw/media outputs are ignored by Git. Preserve original closed bytes and every
attempt, including failures. Do not expose closed artifacts to an active policy.

The primary score uses the final executed native step's success, not a video's
appearance, an actor's declaration or the best intermediate frame. Record
policy calls, executed action decisions, control steps and first-success timing
separately. First success is diagnostic, not a replacement score.

`harness_source/` binds shared and benchmark integration bytes;
`model_source/` separately binds declared policy/configuration/prompt bytes.
These are provenance records, not proof of OS isolation, loaded-memory identity,
native asset completeness or trusted provider accounting.

Use the shared [closed-record auditor](../../../benchkit/audits/closed_run.py),
[mailbox artifact auditor](../../../benchkit/audits/mailbox_artifacts.py) and
[progress reporter](../../../benchkit/reports/progress.py) on closed runs only.
Their `--help` commands describe supported inputs and limitations. A passed
record audit does not establish native baseline parity. Changing code or setup
requires a separately declared evaluation configuration, never rewritten results.

Use [the review checklist](../../../benchkit/audits/REVIEW_GUIDE.md) for independent
closed-run review. Shared video export is available as
`python -m benchkit.reports.export_videos --help`; it copies only closed evidence.
Historical anonymous results remain under
[the model result namespace](../../../AgentPolicies/anonymous_code_agent/results/simpler_env/README.md),
not in this benchmark's source directory.
