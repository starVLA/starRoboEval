# LIBERO-Plus direct-control protocol

Status: implemented lazy adapter and standalone SIM server; native full parity
and model capability scores are not established by installation or CPU tests.
Benchmark ID: `libero_plus`. Native source pin:
[`4976dc30028e805ff8094b55501d532c48fec182`](https://github.com/sylvestf/LIBERO-plus/tree/4976dc30028e805ff8094b55501d532c48fec182).

## Task universe and selection

The pinned native task map and one-based classification IDs contain **10,030
variants in four suites**. RSI uses the native zero-based task indices with
`task_order_index=0`. The unrelated 90-task `libero_90` suite is excluded.

| Native perturbation category | Spatial | Object | Goal | LIBERO-10 |
| --- | ---: | ---: | ---: | ---: |
| Background Textures | 258 | 248 | 281 | 289 |
| Camera Viewpoints | 376 | 396 | 408 | 419 |
| Language Instructions | 390 | 354 | 410 | 383 |
| Light Conditions | 292 | 297 | 279 | 274 |
| Objects Layout | 385 | 403 | 425 | 312 |
| Robot Initial States | 350 | 398 | 409 | 393 |
| Sensor Noise | 351 | 422 | 379 | 449 |
| Total | 2,402 | 2,518 | 2,591 | 2,519 |

The four [frozen catalogs](bench_server/protocol/catalogs/) record every native name, category,
difficulty level, public/native instruction, backing BDDL SHA-256 and resolved
initial-state file SHA-256. `environment/freeze_catalog.py` reproduces this data
read-only from the pinned upstream checkout without importing a simulator.
No licensed training dataset or model weights are needed for evaluation.

`evaluation_mode: fast` selects an explicit increasing, unique `task_ids` list,
one predeclared seed, released state index **0**, and **one attempt per selected
variant**. Failures and environment errors remain in the selected denominator;
neither the client nor the adapter retries a failed task/reset. Upstream's own
reset wrapper may retry internal placement randomization before returning one
reset; that is retained native initialization, not a success-seeking model retry.
The upstream README instructs changing original LIBERO's 50 trials to **one
trial per LIBERO-Plus variant**. A `full` preset is deliberately rejected until
the complete native matrix, seed/aggregation convention and runtime are verified.
Selecting many task IDs is not proof of full benchmark parity.

## Native variation and reset semantics

The service passes the exact **virtual** native BDDL filename to
`OffScreenRenderEnv`. It must not substitute the backing filename when starting
the environment: `_view_..._initstate_...` names cause the native wrapper to
change camera orientation/distance, endpoint angles, Panda initialization and,
when present, sensor-noise parameters. The wrapper resolves the actual BDDL by
removing the view suffix. No variation is recreated by a model or harness helper.

The native reset loader resolves filenames in this precedence order:

1. Language suffix: underlying pre-language reset file.
2. View suffix: underlying pre-view reset file.
3. Table/table-background suffix removal; light suffix selects its base reset.
4. Layout `_add_`/`_level` variants: `init_files/libero_newobj/<suite>/...`, with
   the native loader's one-row reshape retained.

RSI checks these exact files against the catalog before native `torch.load`.
It seeds NumPy and the native environment, invokes native reset and state 0,
then performs the retained evaluator's **10 fixed settle controls**
`[0,0,0,0,0,0,-1]`. They are initialization, not model decisions, and are recorded
separately. A native success during settling is an initialization error, not a
model success. No task-solving action is supplied by the adapter.

## Public observation and direct action interface

- Public task label: `<suite>/task-<ordinal>`, never a variant filename.
- Language: the backing BDDL's `:language` field, with native BDDL tokenization
  (lowercase and whitespace normalization). Rewritten language variants keep
  their rewritten BDDL instruction.
- Two 256×256 RGB uint8 views: `agentview`, `robot0_eye_in_hand`.
- Fixed retained orientation: independent contiguous copies of
  `native_rgb[::-1, ::-1]`. No resize, crop, recoloring or reversal of native
  sensor-noise perturbations.
- No joint/EEF/object poses, success, reward, seed, view angles, robot-init index,
  calibration, segmentation or simulator metadata is delivered to the policy.

**Language track distinction:** upstream's non-language `task.language` is
generated from the full variant filename and includes numeric view/init-state
suffixes. Passing it through would disclose evaluator-private parameters. RSI
uses the actual BDDL instruction instead; the original native string remains in
private catalog/provenance for identity checks. This explicit direct-control
track must not be reported as byte-identical legacy model-prompt parity.

Each native control is a normalized 7D OSC_POSE vector in `[-1,1]` at **20 Hz**:
world-frame translation deltas (component 1 → 0.05 m), world axis-angle rotation
deltas (component 1 → 0.5 rad), and gripper `-1` open / `+1` close / `0` retain
the native gripper target. The native controller is checked before reset. No
VLA proposal, IK task planner, grasp service or fallback policy is allowed.

`Policy.act` runs only through the shared observation-to-decision interface. The
evaluator privately owns the service token/client. A model gets no direct reset,
step, scorer or artifact-read endpoint. Idle service time causes no controls.

## Budgets, scoring and reporting

The retained StarVLA evaluator references 220/280/300/520 policy controls for
spatial/object/goal/LIBERO-10, excluding the 10 settle controls. These are named
reference horizons, not an inferred universal engine limit. Optional
`budget_mode: decisions` declares `max_policy_calls × replan_interval` as an
explicit alternative control cap and changes protocol identity. The neutral
runner separately enforces call/chunk limits. Calls, executed action decisions,
native controls and settle controls are distinct counters. Ordinary give-up
preferences belong to the policy profile, never this benchmark.

`BDDLBaseDomain.step` assigns `done = _check_success()` natively. RSI uses that
returned value once; it never polls the success predicate again or scores from
model text. Native success terminates; exhausting the predeclared control cap
without success truncates. A renderer/load/protocol error is an infrastructure
error, not evidence that the policy cannot perform the task.

The server and evaluator retain source captures, schedule, original failures,
native versions, reset/BDDL hashes, action records, PNG frame hashes and separate
camera-named videos. Selected mesh/texture references from constructed native
XML have bounded hash receipts; unresolved relative references are explicit.
These receipts do **not** attest the complete asset archive or loaded GPU memory.
The 60 declared native source files are hash-checked before reset. Dependency
versions and the controller configuration are recorded/checked, not a byte-level
attestation of all third-party package source or loaded memory. Use a stable
native checkout and inspect renderer diagnostics before capability work.
The native import inventory rejects extra Python/extension/bytecode files and
source-directory symlinks before import. Asset, BDDL and reset trees are data
scopes verified separately, not a recursive import inventory of unused code.
The actual ImageMagick library version, quantum depth and HDRI/features are
recorded separately from Python Wand. Do not aggregate sensor-noise results
across different backends; this initial integration does not claim a universal
ImageMagick binary pin or complete full-suite parity.

`native_events.jsonl` records evaluator-private initialization and control
start/end receipts. Metrics distinguish declared settling, actually completed
settle controls, policy-control attempts/completions and uncertain native calls.
A missing completion receipt is not silently counted as a completed control.
Native or observation errors poison the session; artifact finalization rejects
further controls and close failures remain visible on repeated cleanup calls.

Results, indices and video exports belong under
`AgentPolicies/<profile>/results/libero_plus/`, not in this benchmark directory.
Historical anonymous attempts cannot be relabeled as verified named-model scores.
The standalone server is supported; remote frozen campaign/full scheduling is
not yet integrated. See the [shared service protocol](../SERVER_PROTOCOL.md).
