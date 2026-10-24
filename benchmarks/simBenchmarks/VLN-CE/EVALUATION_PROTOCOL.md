# VLN-CE evaluation protocol

VLN-CE measures instruction following and navigation in continuous indoor
scenes, using native route-success and path-efficiency metrics. The specification
below proposes a service interface for the R2R unseen-scene validation split;
the service is not implemented yet.
Pinned upstream sources and environment/asset requirements are in [PREFLIGHT.md](PREFLIGHT.md).

## Identity and episode selection

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

R2R `val_unseen` contains 1,839 released episodes across 11 scenes. R2R, RxR,
language, guide/follower roles and challenge configurations are separate
selection dimensions. Specify episode IDs and repetitions in the evaluation
configuration.

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

The draft specifies current-image delivery, not a model-specific history sampler.
Methods may retain previously delivered inputs within the declared episode
scope; adding server-provided history requires explicit sampling/timing rules.
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

One service `step` would execute exactly one explicit native action. The method
chooses whether to group several actions before another decision. Do not
silently repeat short chunks, round malformed output, default invalid text to
forward, or carry queued actions into another episode. The runner records the
executed prefix and stops playing it when the native episode ends.

Navigation STOP is an action chunk containing `(0,)`, not
`PolicyDecision.stop=True`. Generic policy stop aborts the runner loop without
calling `env.step(0)`; it cannot substitute for the native stop required by the
scorer. Report generic stop separately as a policy abort.

## Budgets and native termination

A proposed R2R configuration uses the following native execution budget;
this table is a draft, not an implemented service preset:

| Setting | Value |
| --- | ---: |
| `budget_mode` | `horizon` |
| Native `ENVIRONMENT.MAX_EPISODE_STEPS` | 500 |
| Service control cap | 500 native actions |

An optional method-call cap and action-grouping policy belong to the agent and
must be disclosed separately; no universal 200-call/five-action setting is part
of this draft. Count STOP as a native action, and record decision calls, controls,
executed chunk lengths and the exact termination reason separately.

An extended control cap would need a separate development protocol; it cannot
be presented as the native 500-action condition or applied retroactively to
existing attempts. An agent's choice of action grouping does not extend the cap.

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

## Result statistics

Report the selected split, scene/episode counts, native metrics and termination
reason. Keep infrastructure errors distinct from completed unsuccessful routes.
Do not equate oracle success with success after a native STOP.

Interaction history and video retention are optional; see
[recording settings](../../../docs/recording.md). The implementation work and
environment checks needed before deployment are listed in [PREFLIGHT.md](PREFLIGHT.md).
