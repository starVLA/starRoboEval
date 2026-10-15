# RoboCasa365

## Directory responsibilities

```text
Robocasa_365/
├── server.py, server.example.json   # public launcher and operator configuration
├── bench_server/
│   ├── adapter.py                  # public observations/actions and native scorer
│   └── protocol/
│       ├── plan.py                 # predeclared fast selection
│       ├── robocasa365_target50.json # supported target tasks and reference horizons
│       └── task_inventory.json      # upstream task-count evidence
└── environment/                    # native readiness, runtime pins and helpers
```

Protocol catalogs are benchmark definitions, not datasets or deployment settings.
Source/asset locations and GPU selection remain operator configuration.
There is no root adapter alias or separate `evaluation/` package; current callers
use `bench_server.adapter` and `bench_server.protocol.plan`. The public server
module name is unchanged. This directory migration changes no native controls,
observations, scoring, budgets, selected cases or historical evidence.
Model behavior and results belong under `AgentPolicies/<agent>/`; shared
communication belongs in `benchkit/sim_server/`. Structure and offline checks
do not establish native service readiness or native-full evaluation support.

This benchmark can run as an independent SIM service via [server.py](server.py).
Start from [server.example.json](server.example.json), adjust deployment paths/GPU
before launch, and follow the [shared server workflow](../SERVER_PROTOCOL.md).
The server owns native reset/control/scoring; the evaluator uses the client, and
the model receives only permitted observations. Existing in-process commands
below remain available for historical compatibility. Native service-mode
validation is separate from adapter availability.

The pinned runtime has a reproduced [native render-context lifecycle defect](environment/RENDERING.md).
The explicit `render_track="egl-owner-restore-v1"` compatibility track repairs
owning-context cleanup and checks render/readback failures without changing
native pixels, controls or scoring. The service example selects the additional
`egl-owner-material-clamp-v1` track: it also bounds invalid native scene shininess
during drawing and restores it afterward. **This v3 track can change pixels and
is not native-pixel-equivalent.** Its task definitions and controls are unchanged.
The adapter's historical `native-v1` default is retained, not endorsed as healthy.
Validate the repaired track on a fresh single-thread Linux/EGL deployment before
another capability evaluation; transport integrity alone is insufficient.
Historical results remain unchanged, and diagnostics do not authorize retries.

The `robocasa365` adapter evaluates PandaOmron kitchen mobile manipulation using native RoboCasa success definitions. It is distinct from the GR1 [RoboCasa Tabletop](../Robocasa_tabletop/README.md) integration.

The upstream implementation contains 365 tasks. The implemented task scopes are a two-task fast preset and the 50-task target set: **18 atomic seen + 16 composite seen + 16 composite unseen**. Enumerating those 50 tasks once is fast coverage, not 365-task coverage or native full evaluation. See [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) and [the target inventory](bench_server/protocol/robocasa365_target50.json).

## Prepare the environment

Use a dedicated environment with these native pins:

| Component | Required version / revision |
| --- | --- |
| [RoboCasa](https://github.com/robocasa/robocasa) | 1.0.1; `b4684e6ee37d377cc392e98302a6b916d588b415` |
| Robosuite | 1.5.2; `85abee228d1c43ab1939bce33028099945d453b4` |
| MuJoCo | 3.3.1 |
| NumPy | 2.2.5 |

Install the pinned upstream sources and their environment dependencies, provision the required kitchen/object assets under their licenses, then install RSI with `python -m pip install --no-deps -e .` from its checkout. H.264 recording requires PyAV and a working graphics/EGL runtime. No training dataset or VLA checkpoint is needed for this sensor-policy adapter.

The repository does not yet provide a complete portable native/asset installer. Source verification requires each imported native package to come from its own clean Git root at the exact revision; an enclosing unrelated repository is insufficient. Confirm import paths and source identities before evaluating rather than relaxing checks for newer packages.

## Check the environment

Select an available GPU and a new output directory:

```sh
python -B -m benchmarks.simBenchmarks.Robocasa_365.environment.diagnose \
  --output /path/to/new-robocasa-diagnostic \
  --task OpenDrawer --seed 20260907 --gpu 0 --render-track egl-owner-material-clamp-v1
```

The native diagnostic performs reset, one neutral action, rendering and artifact recording with zero policy decisions. Check all three cameras and complete PNG/video decoding. A separate fixed, nonadaptive controller-direction diagnostic is available:

```sh
python -B -m benchmarks.simBenchmarks.Robocasa_365.environment.adapter_diagnose \
  --output /path/to/new-robocasa-direction-check --gpu 0 --render-track egl-owner-material-clamp-v1
```

These are infrastructure checks, not task-solving models or capability scores.
Start with the three [geometry-only lifecycle checks](environment/RENDERING.md#geometry-only-validation)
before constructing a benchmark environment. Set `MUJOCO_GL=egl` and
`PYOPENGL_PLATFORM=egl` explicitly for SIM service launches. The repair does not
support sharing native rendering across threads or switching tracks in-process.

## Inspect closed RGB evidence

The offline RGB diagnostic reads an existing episode artifact directory containing
`frames.jsonl` and its three-camera PNGs. It requires NumPy and Pillow, but does
not start a simulator, render extra images or contact a model:

```sh
python -B -m benchmarks.simBenchmarks.Robocasa_365.environment.audit_rgb \
  /path/to/closed-episode-artifacts \
  --output /path/to/model-results/diagnostics/new-rgb-audit.json
```

Choose a new output outside the original artifacts; preserve previous audit
outputs as well as evaluation records. The diagnostic checks hashes, single-frame
RGB PNG integrity and complete three-camera coverage. A clean SIM-server receipt
also binds coverage to its reset-plus-control count; absent, legacy or faulted
receipts leave episode completeness explicitly unknown. Output identifies the
auditor source bytes, dependency versions, receipt/manifest hashes and thresholds.

Warnings flag sustained camera similarity or alternating vertical orientation
using configurable pixel-difference thresholds. They are not a renderer diagnosis,
a success judgment or image repair. No warnings does not prove correct rendering.
For temporal warnings, `first_step` is the destination of the first qualifying
frame comparison; its source frame is `first_step - 1`. Keep anomalous attempts
in their original denominator and report qualifications separately; this check
neither changes scores nor authorizes a retry.

## Evaluate one task

After connecting a [mailbox actor](../../../AgentPolicies/anonymous_code_agent/README.md):

```sh
python -m benchkit run \
  --benchmark robocasa365 --model-profile anonymous_code_agent \
  --benchmark-args '{"task_ids":[0],"render_gpu_device_id":0,"render_track":"egl-owner-material-clamp-v1","budget_mode":"decisions","max_policy_calls":200,"replan_interval":5}' \
  --policy-args '{"directory":"/path/to/opaque-mailbox"}' \
  --seed 20260907 --episodes 1 --budget-mode decisions \
  --max-policy-calls 200 --replan-interval 5 --max-steps 1000
```

In the default scope, task 0 is OpenDrawer and task 1 is NavigateKitchen. With `task_scope="target50"`, indices instead follow the native target-set ordering: NavigateKitchen is 4 and OpenDrawer is 6. Never reinterpret an index without its scope.

The [campaign plan](bench_server/protocol/plan.py) selects the default pair or all 50 with explicit `target50`; see [campaign usage](../../../docs/evaluation.md). Preserve one outcome per preselected task, including errors and failures, without automatic retry. The anonymous transport does not prove model/provider identity. Model code and results belong under [AgentPolicies](../../../AgentPolicies/README.md). Native-aligned full mode remains unimplemented.
