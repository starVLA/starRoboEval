# RoboDojo Direct v2 evaluation protocol

## Protocol identity

- Benchmark: `robodojo`
- Public protocol: `robodojo-direct-v2-rgb-proprio28-eef16-robot-feedback-v1`
- Task: `classify_objects`
- Embodiment: two fixed-base ARX X5 arms
- Native task instruction: sort objects by category into three baskets
- Public instruction also requires both arms to return to their starting
  end-effector poses
- Campaign seed: 20260907
- Native evaluation/simulator seed: 0
- Panels: `fast` is layouts 0–4; `full` is layouts 0–49, in order
- Attempts: exactly one per selected layout; no automatic retry or replacement
- Native horizon: 1100 acknowledged controls per layout

The five-layout `fast` panel is the reference-comparison/development mode. The
50-layout `full` panel matches the upstream configured episode count for this
task. Neither is the complete multi-task RoboDojo benchmark. A run must select
one named panel before outcomes; arbitrary layout subsets are not a score.

The machine-readable definition is [bench_server/protocol/task_catalog.json](bench_server/protocol/task_catalog.json),
validated by [bench_server/protocol/task_catalog.py](bench_server/protocol/task_catalog.py). It is benchmark
protocol data, including the binding to the pinned layout inventory. It contains
no native assets or operator deployment paths. [server.py](server.py) loads the
[service adapter](bench_server/adapter.py), which applies this definition through
the private runtime under `environment/`. Directory reorganization does not create
a new protocol or alter the meaning of frozen historical results.

## Public observation

At reset and after each acknowledged control the model receives:

- task language;
- original 640×480 `uint8` RGB for `cam_head`, `cam_left_wrist` and
  `cam_right_wrist`;
- 28 robot values: six measured joints and one last commanded gripper opening
  per arm, followed by each measured link6 world pose as `x,y,z,qw,qx,qy,qz`.

After a control, the observation additionally contains the closed
`robodojo.robot-control-feedback/v1` acknowledgement: executed joint command,
post-control public robot state, and robot-only DLS/FK diagnostics. Reset has no
acknowledgement.

The model never receives object poses/identities, layout or reset metadata,
camera calibration, contacts, depth, reward, native success, process score,
scorer state, simulator handles, worker logs or private errors.

## Public action

One action is 16 finite values:

```text
[left_x, left_y, left_z, left_qw, left_qx, left_qy, left_qz, left_opening,
 right_x, right_y, right_z, right_qw, right_qx, right_qy, right_qz, right_opening]
```

Poses are absolute measured link6 targets in the declared world frame.
Quaternions are absolute unit `wxyz` values with tolerance `1e-4`; openings are
continuous `[0,1]`. The benchmark performs a fixed robot-only numerical DLS
conversion, applies native soft-limit/measured-joint bounds and sends exactly
one native joint control. It does not plan around objects, choose targets, run a
support policy or roll out hypothetical actions.

Model-side step size, rotation size, chunk length and ordinary give-up rules are
policy configuration, not benchmark validity. Benchmark validity is limited to
the declared vector shape, finite values, quaternion norm and opening range.
Confirmed invalid actions execute zero controls and return structured feedback;
they remain recorded. The client may correct them on a later decision.

## Counting and termination

Count policy calls, action decisions, rejected actions, acknowledged controls
and physics ticks separately. One acknowledged control runs ten native physics
ticks at 0.004 seconds. A model may propose a bounded chunk, but the service
still executes and acknowledges controls one at a time.

Terminate on native success/end, native horizon, explicit model stop, or a
terminal infrastructure/policy error. The 1100-control horizon is a benchmark
limit; model-call limits are model/evaluation configuration and must be reported
separately. Waiting for a model advances no physics. An uncertain native action
is never silently replayed.

## Scoring

Success is the pinned native result `end_flag[0] and success[0]`. Native reward
and cached process score are recorded without an extra stateful scorer call.
Partial process score is not task success. Report success count over the full
selected named-panel denominator (5 for `fast`, 50 for `full`), plus native
scores and all infrastructure or policy errors. Do not remove failures or
replace layouts.

## Isolation and evidence

The model communicates only through the authenticated loopback SIM service.
The server owns the native environment, schedule and score; the model owns its
decision loop. The shared harness may coordinate output and publish a closed
report, but it cannot expose server-private fields or generate actions.

Essential results retain the selected schedule and protocol/method configuration,
native outcome, executed counters and separate infrastructure/policy errors.
Detailed interaction/media retention is optional, default enabled. It does not
alter the sensors, controller, horizon, scoring or attempts specified above.

The existing **full-evidence audit path** additionally uses:

- immutable schedule and protocol/source declarations;
- client receipt and server claim/session record;
- submitted/rejected actions and public observations;
- native events, final result and cleanup receipts;
- head, left-wrist and right-wrist video;
- model transcript/usage when available;
- separate infrastructure and policy errors.

Published results belong under
`AgentPolicies/<model-profile>/results/robodojo/`. Raw evidence may live in durable
artifact storage or local ignored `barks/`. The full-evidence publisher binds
its selected raw evidence by hash; the generic basic-result publisher does not
require those optional logs, videos or a source audit. Current native workers
still capture their own media independently of client retention settings. See
[recording scope](../../../docs/recording.md). Never rewrite a closed failure
to make a report publishable.
