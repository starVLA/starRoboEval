# VLN-CE evaluation protocol

RSI status: **`protocol_draft`**. The specification below is a proposed
adapter contract, not evidence of an installed runtime or completed attempt.
Pinned upstream sources and environment/asset requirements are in [PREFLIGHT.md](PREFLIGHT.md).

## Identity and episode selection

- Draft protocol family: `vlnce-r2r-v1-3/rgb/native-horizon500/draft-v1`.
- Evaluator: [StarVLA-VLN-CE-Evaluation at
  `2e56d1c026b2945b90b4ff339bdec2cb1e42b800`](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/tree/2e56d1c026b2945b90b4ff339bdec2cb1e42b800).
- Native task: `VLN-v0`; dataset registration: `VLN-CE-v1`; released data:
  `R2R_VLNCE_v1-3`, split `val_unseen`. These version names are different fields.
- Reset seed: an explicit manifest field, applied before native reset.

Select episode IDs from the complete split before filtering by asset availability
or inspecting outcomes. Freeze IDs, scene IDs, instructions, seed, dataset
checksum and order before any attempt. Do not invent IDs while assets are missing. A missing
selected scene blocks that attempt; it does not authorize a substitute episode.

One navigation episode pairs an instruction with a native start state, scene and
goal. `trajectory_id` identifies a route and `scene_id` identifies a building;
neither should be counted as a distinct manipulation task. Different instructions
can describe the same route. Native reset/scoring fields remain evaluator-private.

Neither fast nor full is currently executable through a unified adapter.

| Mode | Required selection |
| --- | --- |
| `fast` | A preselected episode subset, one attempt per selected episode, with an explicit denominator |
| `full` | Every episode in the selected native dataset/split/role/language configuration, with its native evaluation settings |

Full R2R `val_unseen` coverage means all 1,839 released episodes, not one episode
per each of its 11 scenes. R2R, RxR, language, guide/follower roles and challenge
configurations are separate variants. Neither mode permits success-based retries,
easy-route selection or replacement of failed attempts. A subset result cannot
establish a full VLN-CE score. Repeated native evaluation cells must be declared
before execution rather than added after failure.

## Policy observation boundary

The proposed RGB track delivers the instruction and current forward-facing
`rgb` image at each decision: `512x512`, RGB `uint8`, 90-degree horizontal field
of view, without policy-specific crop or resize. The policy may retain its own
previously delivered observations and actions; episode state resets between
attempts. No extra camera query or simulator access is permitted between calls.

The native configuration also generates depth, but this track exposes only
RGB and language. Remove `SHORTEST_PATH_SENSOR` and
`VLN_ORACLE_PROGRESS_SENSOR` from the task sensor configuration, leaving the
instruction sensor. Use an explicit observation allowlist: do not forward native
observation dictionaries or `info` wholesale. No depth, GPS, compass, global
pose, goal coordinates, shortest paths, navigation graph, maps, oracle progress,
distance, reward, success or other scoring metadata reaches the policy. The
runner supplies an opaque episode label rather than the native episode ID.

The legacy QwenVL trainer samples up to eight RGB frames from native-step
history. That wrapper is not the current-image contract above; preserving it
requires a separately frozen history variant, including sampling and timing.
Video or metric overlays are evaluator artifacts, never policy images.

## Native navigation actions

Use the pinned R2R configuration's `v0` action space, `ALLOW_SLIDING=true` and
the following native action IDs:

| ID | Native action | Effect per executed action |
| ---: | --- | --- |
| 0 | `STOP` | Call the native task's stop action; counts as one action |
| 1 | `MOVE_FORWARD` | Request a 0.25-metre forward step; collision may limit movement |
| 2 | `TURN_LEFT` | Turn left by 15 degrees |
| 3 | `TURN_RIGHT` | Turn right by 15 degrees |

The proposed shared `ActionSpec` has mode `habitat_discrete_navigation_v0`,
size `1`, name `action_id` and bounds `[0, 3]`. The adapter must additionally
reject fractional IDs; numeric bounds alone do not validate a discrete enum.
Do not use a seven-dimensional arm action, velocity command, waypoint planner,
teleport or shortest-path follower. Do not invent a control frequency for these
native task actions.

One `Policy.act` call produces one decision containing one to five explicit
native actions. One `EpisodeSession.step` executes exactly one of them. Do not
silently repeat short chunks, round malformed output, default invalid text to
forward, or carry queued actions into another episode. The runner records the
executed prefix and stops playing it when the native episode ends.

Navigation STOP is an action chunk containing `(0,)`, not
`PolicyDecision.stop=True`. Generic policy stop aborts the runner loop without
calling `env.step(0)`; it cannot substitute for the native stop required by the
scorer. Report generic stop separately as a policy abort.

## Budgets and native termination

A proposed fast R2R configuration uses these matching adapter/runner settings;
this table is a draft, not an implemented runner preset:

| Setting | Value |
| --- | ---: |
| `budget_mode` | `horizon` |
| Native `ENVIRONMENT.MAX_EPISODE_STEPS` | 500 |
| Runner `max_steps` | 500 |
| `max_policy_calls` | 200 |
| `replan_interval` | 5 |

The first exhausted limit ends the attempt. Thus 500 native actions can end an
attempt before 200 decisions; 200 short-chunk decisions can end it before 500
actions. Count STOP and failed/scheduled policy calls, and record actual calls,
native actions, executed chunk lengths and the exact termination reason. These
are fast evaluation limits, not a validated native full scoring configuration.

Do not relabel this track as decision-primary. A future 200-decision,
five-action-prefix track with a 1000-action native cap changes the native
500-action horizon; it needs its own protocol/configuration and must be reported
as an extended development variant. It is not an official VLN-CE score, and
existing attempts must not be retroactively relabeled.

Native success is authoritative: Habitat requires an executed STOP and a final
geodesic distance strictly below 3 metres. Merely entering that radius does not
terminate the native task or establish success. `oracle_success` records whether
the trajectory ever entered the radius; it is a separate metric. Map native
STOP to `terminated`, native horizon exhaustion to `truncated`, and retain the
specific reason. Runner budget exhaustion must not execute an unrequested STOP
to turn an unfinished trajectory into a success.

Use native `get_metrics()` for `success`, `distance_to_goal`, `spl`, `ndtw`,
`path_length`, `oracle_success`, `steps_taken` and the pinned R2R `oracle_spl`.
Normalize native success to the required boolean without recomputing it. GT
paths needed by nDTW belong exclusively to the evaluator. Non-finite metrics
or missing scoring assets are visible errors, not silently discarded failures.

## Required artifacts and adapter acceptance

Retain the manifest, exact selected episodes, seed, split, role/language where
applicable, runtime/build revisions, configuration and asset checksums. Log each
policy call, action chunk, executed action, termination reason, native metrics,
provider transcript and available token/cost/latency usage. Unavailable usage
is unknown, not zero. Preserve the original result of every attempt and keep
infrastructure errors distinct from completed policy failures.

Record reset and native-step RGB frames into a decodable video under the
runner-owned episode artifact directory. Native poses, paths and scoring records
may be retained for evaluator auditing but must be isolated from policy access;
a file mailbox by itself is not a sandbox.

Before model evaluation, verify reset/render/action semantics,
integer/observation boundaries, STOP versus timeout handling and video output.
For a fixed episode and recorded action sequence, compare native direct
execution with the unified session: every executed action, final trajectory,
termination and native metric must agree. This is evaluator validation, not a
policy success-seeking retry. Review retained evaluation artifacts independently
before declaring the adapter ready. Neither a reachable model server nor documentation
alone passes this gate.
