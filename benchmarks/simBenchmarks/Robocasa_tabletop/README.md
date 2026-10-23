# RoboCasa GR1 Tabletop

## Directory responsibilities

```text
Robocasa_tabletop/
├── server.py, server.example.json   # public launcher and operator configuration
├── bench_server/
│   ├── adapter.py                  # public observations/actions and native scorer
│   └── protocol/
│       ├── plan.py                 # predeclared fast selection
│       ├── robocasa_tabletop_contract.json # pinned sensor/action/source contract
│       ├── task_catalog.json        # official 24-task order and layout candidates
│       └── POLICY_GUIDE.md           # public robot interface, not a model prompt
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

The `robocasa_tabletop` adapter evaluates GR1 whole-upper-body manipulation using native [RoboCasa GR1 Tabletop](https://github.com/robocasa/robocasa-gr1-tabletop-tasks) tasks and success predicates. This is distinct from PandaOmron RoboCasa365.

The official set contains 24 tasks. `task_scope="tabletop24-seeded-v1"` supports
all 24 through an explicit one-to-five-seed development panel, ordered first by
sample, then by task: cover every task once before moving to the next seed.
Historical fast pairs (indices 0/19 or 1/2) remain unchanged. Five seeds do not
mean five distinct layouts; each task retains its native layout and all 12 style
candidates. Native-aligned full evaluation is not implemented. See
[EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md) for the complete catalog, selection
rules, sensors, physical joint actions and scoring.

## Prepare and verify

Follow [environment/README.md](environment/README.md) for source/runtime/asset requirements and a parameterized native diagnostic. Required source pins are:

- RoboCasa GR1: `4840e671596f93ca03651524b9f72ffb1aadfeff`.
- Robosuite: `51cc01785bab80ffeed20da15e67d7dd4140e76a`.

Launch Python with `PYTHONHASHSEED=0` before process startup. The pinned contract includes the complete provisioned object inventory and compiled controller/encoder identities; arbitrary newer source or asset snapshots are not interchangeable. A portable all-assets bootstrap is not yet available.

## Run as an independent SIM server

[server.py](server.py) owns the native Tabletop adapter. The evaluator connects
through the shared SIM client; the policy receives only the one allowed RGB
view, native language and 29 measured encoders. No server handle, private
metadata, scorer or diagnostic hold is a policy interface.

Copy [server.example.json](server.example.json) to an operator-owned file and
replace all three source/inventory placeholders and the GPU before launch.
These paths must still satisfy the exact source/asset contract; the example
does not provision or certify a fresh installation. It selects task 0
`PnPCupToDrawerClose`, one seeded reset and the explicit `budget_mode: "horizon"`,
`control_step_cap: 1000` development track. This server track limits total
controls, not policy calls or controls per decision. The policy/method owns its
chunk size and any replan/call limits. It is not native-full evaluation.

Follow [SERVER_PROTOCOL.md](../SERVER_PROTOCOL.md) to set the same strong
`RSI_SIM_SERVER_TOKEN` only in server/evaluator process environments and to
forward loopback over SSH when using separate nodes. Start the server from a
stable source snapshot using the pinned native **Python 3.10.21** environment:

```sh
PYTHONHASHSEED=0 python -B -m benchmarks.simBenchmarks.Robocasa_tabletop.server \
  --parameters /absolute/path/to/tabletop-server.json \
  --seed 20260907 --episodes 1 --port 8768 \
  --output-dir AgentPolicies/anonymous_code_agent/results/robocasa_tabletop/raw/PnPCupToDrawerClose-cup-in-drawer/server
```

`PYTHONHASHSEED=0` must be present before the server interpreter starts; changing
it inside Python cannot satisfy the native hash sentinel. The chosen GPU must
be idle at reset. Do not stop another user's process to pass the GPU check.
In a separate evaluator environment with NumPy and an unused opaque
[mailbox actor endpoint](../../../AgentPolicies/anonymous_code_agent/README.md):

```sh
python -B -m benchkit run \
  --benchmark robocasa_tabletop --sim-server http://127.0.0.1:8768 \
  --model-profile anonymous_code_agent \
  --policy-args '{"directory":"/absolute/opaque-mailbox","timeout_s":900,"max_chunk_length":5}' \
  --seed 20260907 --episodes 1 --budget-mode horizon \
  --max-policy-calls 200 --max-steps 1000 \
  --output-dir AgentPolicies/anonymous_code_agent/results/robocasa_tabletop/raw/PnPCupToDrawerClose-cup-in-drawer/evaluator
```

In this example the mailbox method chooses its own five-action maximum and
200-call allowance; neither is a server constraint. Omitting the generic
runner's `--replan-interval` executes the submitted chunk until native end or
the remaining total control limit. A method may instead declare its own prefix.
The service accepts `control_step_cap` integers from 1 to 1000; a smaller cap
has a distinct `control-N/v2` protocol identity. Do not mix that parameter with
the legacy service-side `max_policy_calls` or `replan_interval` parameters.

Do not pass `--benchmark-args` remotely; only the service constructs native
environments. Use new output directories. Service launch/`describe` freezes
the selection without resetting the SIM and is not native readiness evidence.
Source, inventory, renderer, compiled controller and encoder checks remain in
the adapter's one reset. Failure retains the attempt; no automatic retry or
asset substitution is enabled. Keep original service/client records and videos
under the model result namespace and verify source integrity before and after.
The evaluator does not need the native Python version or renderer settings.
Native-free service checks do not establish native service-mode validation,
completed 24-task coverage or object-library completeness. The frozen campaign path
and legacy artifact auditors do not yet support remote service records.

### NVML resource index and EGL renderer index

`render_gpu_device_id` selects the **NVML / nvidia-smi resource index** checked
for other processes before native reset. The optional `egl_device_id` selects
`MUJOCO_EGL_DEVICE_ID` independently; when omitted it defaults to the same
integer, preserving prior configurations. Both must be nonnegative integers.
EGL enumeration can differ from NVML enumeration, so identical numbers do not
prove that the renderer uses the GPU protected by the resource check.

Before claiming a task on a new machine or driver configuration, run a separate
renderer-only preflight and match the actual graphics process GPU by UUID /
PCI address to the intended NVML resource. Supply the verified EGL index in the
operator-owned configuration if the enumerations differ. For example,
`"render_gpu_device_id": 0, "egl_device_id": 1` is valid **only if preflight on
that machine verifies this mapping**; it is not a portable GPU mapping.
The service neither guesses a mapping nor silently falls back to another GPU.
Both configured indices are recorded in native provenance; those indices alone
are not proof of physical-device identity. Do not change them during a run.

## Cover all tasks with five declared seeds

For the new service scope, retain the source/inventory paths and GPU fields from
your operator-owned server JSON, and replace the selection with:

```json
{
  "task_scope": "tabletop24-seeded-v1",
  "episode_seeds": [20261020, 20261021, 20261022, 20261023, 20261024],
  "budget_mode": "horizon",
  "control_step_cap": 1000
}
```

Omitting `task_ids` selects all 24 official tasks. Start the server with
`--seed 20261020 --episodes 120` and a new output directory. Connect the
trusted driver using the same schedule seed and episode count. A predeclared
external queue may instead launch a singleton `task_ids` / `episode_seeds`
selection per service, while preserving the overall sample-major task order.
This is a service scope; the historical in-process campaign plan does not
implement this new selection.

The launch seed must match the first configured episode seed. Each case uses
its own declared seed for native construction and reset. Selecting seeds is not
requesting particular styles, and actual styles can repeat. Retain every outcome;
successful or normally budget-exhausted cases are not repeated to improve scores.
Infrastructure interruption stays a separate error record; any separately
authorized repair attempt uses a new run ID without overwriting the original.

This is the retained **1000-control development track**, not the pinned upstream
README's Isaac-GR00T example with 720 steps and 10 episodes. A method owns its
action chunk and call allowance; the service executes one native control per
step and stops at native success / termination or the selected control cap.
Completed native evaluation must be demonstrated separately for each case.

## In-process compatibility

The adapter default and existing frozen campaigns retain the separately named
`decisions` track, including its 200-call/prefix-5 defaults and D × K total cap.
This legacy example is not the recommended independent-control server track.
After provisioning compatible sources/assets and connecting a [mailbox actor](../../../AgentPolicies/anonymous_code_agent/README.md):

```sh
PYTHONHASHSEED=0 python -m benchkit run \
  --benchmark robocasa_tabletop --model-profile anonymous_code_agent \
  --benchmark-args '{"task_ids":[0],"casa_source":"/path/to/robocasa-gr1","suite_source":"/path/to/robosuite-gr1","object_inventory":"/path/to/object-inventory.json","render_gpu_device_id":0,"budget_mode":"decisions","max_policy_calls":200,"replan_interval":5}' \
  --policy-args '{"directory":"/path/to/opaque-mailbox"}' \
  --seed 20260907 --episodes 1 --budget-mode decisions \
  --max-policy-calls 200 --replan-interval 5 --max-steps 1000
```

Explicit paths avoid the adapter's site-specific defaults; the files must still match the pinned manifest. Use `task_scope="tabletop-next-pair-v1"` with `task_ids=[1]` or `[2]` for the second pair. The [campaign plan](bench_server/protocol/plan.py) supports either pair and requires compatible deployment paths.

Fast mode keeps one outcome for every preselected task, including failure and environment error, without automatic retry. Only the evaluator operates the simulator and reads native scoring state. Model behavior/results belong under [AgentPolicies](../../../AgentPolicies/README.md); anonymous transport is not proof of a named model/provider identity.
