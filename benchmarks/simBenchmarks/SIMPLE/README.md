# SIMPLE humanoid evaluation

This integration follows the [RoboDojo-derived service conventions](../SERVICE_CONVENTIONS.md).
Its native humanoid controllers, 36-value commands and task scoring remain distinct.

The current **v2** interface removes RSI's additional joint-target range
rejection. It forwards finite physical targets through the original controller
without clipping; native physics and controller limits remain unchanged.
Optional model target guards belong in `AgentPolicies/`, not the SIM service.
Frozen v1 records retain their old protocol and outcomes; see the
[action contract](EVALUATION_PROTOCOL.md#physical-36-dimensional-action).

This benchmark can run as an independent SIM service via [server.py](server.py).
Start from [server.example.json](server.example.json), adjust deployment paths/GPU
before launch, and follow the [shared server workflow](../SERVER_PROTOCOL.md).
The server owns native reset/control/scoring; the evaluator uses the client, and
the model receives only permitted observations. Native service-mode validation
is separate from adapter availability.

The server excludes its episode-local `cache/` from artifact transfer. The
adapter assigns this directory to native runtime caches (including Omniverse
texture caches and Torch extension builds); it is not rollout evidence. The
exclusion is recorded in session receipts and the captured launcher. Native originals are
retained, while observations, videos, logs, metrics and provenance remain
exported. This affects new launches only: existing frozen runs keep their
original inventories and cached files, without retroactive pruning.

[SIMPLE](https://github.com/physical-superintelligence-lab/SIMPLE) is the whole-body humanoid benchmark from Physical Superintelligence Lab, not SimplerEnv or HumanoidBench. The `simple_humanoid` adapter connects a sensor-driven policy to G1's native AMO/SONIC whole-body controllers.

The released inventory has 12 tasks. The default campaign selects BendPickMP and OpenFaucetTeleop; explicit `task_scope="released-12"` selects all 12 once each. These are fast task selections, not the native domain-randomization/episode schedule. See [task scope](bench_server/protocol/RELEASED_TASK_SCOPE.md) and [EVALUATION_PROTOCOL.md](EVALUATION_PROTOCOL.md).

## Directory responsibilities

```text
SIMPLE/
├── server.py                         # stable public service entrypoint
├── server.example.json               # operator paths and selected task
├── bench_server/
│   ├── adapter.py                    # public contract, reset mapping and scoring
│   ├── native_worker_client.py       # private RPC and child-process lifecycle
│   ├── source_inventory.py           # explicit service source capture inputs
│   └── protocol/
│       ├── plan.py                   # benchmark-owned task selection
│       ├── POLICY_GUIDE.md            # declared public sensor/action interface
│       ├── RELEASED_TASK_SCOPE.md     # released task/reset scope and timing
│       └── simple_released_tasks.json # pinned task/backend/reset inventory
└── environment/                      # native worker, runtime pins, diagnostics
```

The catalog is protocol data consumed by the service; native assets stay outside
the package at configured deployment paths. `bench_server/adapter.py` delivers
only the declared RGB/joint observations and translates public actions into the
private worker protocol. `native_worker_client.py` launches and closes the pinned
worker without defining tasks or model behavior. `server.main(argv=None)` uses
the service-owned source inventory independently of campaign task selection.
Model decisions and results stay in `AgentPolicies/<profile>/`.
The catalog bytes, task/reset identities and protocol IDs are preserved when
changing this directory layout.
The [public interface guide](bench_server/protocol/POLICY_GUIDE.md) is reusable
benchmark context. Historical reports, checklists and evidence caveats live in
the [anonymous code-agent results](../../../AgentPolicies/anonymous_code_agent/results/simple_humanoid/README.md).
The canonical adapter lives in `bench_server/adapter.py`; task selection lives
beside the protocol in `bench_server/protocol/plan.py`.

## Prepare the environment

The source pin is `5e3d6f84e85343e34e9bca8d157f0d7813231185`, with Python 3.10, Isaac Sim 4.5 and MuJoCo 3.3.6. Native AMO/SONIC controllers and fixed locomotion weights are environment dependencies, not the high-level policy being evaluated.

Provision the upstream runtime, controller weights, robot assets, released evaluation metadata and referenced HSSD scenes under their respective licenses. [environment/upstream.json](environment/upstream.json) records source, compatibility-patch, controller and asset-manifest requirements. [simple_released_tasks.json](bench_server/protocol/simple_released_tasks.json) binds task/backends and released resets.

A portable all-assets installer is not yet available. Installing RSI alone is insufficient. Adapter path defaults remain site-specific: explicitly pass `simple_root` and `eval_root` for a compatible local materialization. The worker uses `<simple_root>/.venv/bin/python`. Do not bypass source/asset checks to use a different release.

Run one task/backend per adapter. Check GPU capacity before initialization: controller contexts may appear on other visible GPUs, so choosing a renderer index is not complete isolation.

## Check the integration

[environment/diagnose.py](environment/diagnose.py) performs reset, stabilization, rendering and one measured hold with zero policy calls. Its CLI currently uses site-specific adapter path defaults and the two default task identities; a relocated deployment must use explicit adapter paths in evaluator-owned diagnostic setup. Diagnostic measurements are not a policy feature or capability score.

## Evaluate one selected task

Configure the paths and one task in a local copy of `server.example.json`.
Set the evaluator-only token following the [shared server workflow](../SERVER_PROTOCOL.md),
then launch the stable entrypoint with a fresh result directory:

```sh
python -B -m benchmarks.simBenchmarks.SIMPLE.server \
  --parameters /absolute/simple-server.json \
  --seed 20260907 --episodes 1 --port 8765 \
  --output-dir /absolute/model-results/simple_humanoid/new-run/server
```

The server starts without resetting the simulator. A trusted model-owned driver
connects to the declared schedule and performs the single reset/attempt. Its
policy receives the permitted observation/action interface, without the service
credential or private score/reset metadata. Keep client records beside server
records in the selected model's results namespace. Native full-mode support is
not implied by this service entrypoint.

For the model-owned native-vector driver, follow
[client README](../../../AgentPolicies/gpt6_astra/README.md).
See the [evaluation workflow](../../../docs/evaluation.md) for source capture
and closed-record reporting.

The [selection plan](bench_server/protocol/plan.py) freezes preselected tasks; its launcher also requires deployment-compatible runtime paths. Retain each task's single outcome, including failures and environment errors. Full native episode/DR coverage and a portable asset bootstrap remain unsupported.
