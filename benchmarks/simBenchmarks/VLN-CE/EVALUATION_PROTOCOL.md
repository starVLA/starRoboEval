# VLN-CE evaluation protocol

VLN-CE evaluates natural-language navigation in continuous indoor scenes.
An episode specifies a building, starting pose, route instruction and private
goal. A scene is a building, not an individual task or layout.

## Dataset and selection

The released R2R-VLNCE v1-3 dataset contains train 10,819 episodes / 61 scenes,
val_seen 778 / 53, val_unseen 1,839 / 11 and test 3,408 / 18.
Several instructions may describe one trajectory. Scene counts overlap across
splits; they are not a count of unique buildings when summed.
See the [dataset definition](https://jacobkrantz.github.io/vlnce/data).

This service evaluates a complete `val_seen` or `val_unseen` split, or a
fixed subset of it chosen by `evaluation_mode`:

| `evaluation_mode` | Episodes | Selection | Per-episode cap |
| --- | ---: | --- | ---: |
| `fast` (default) | 373 on `val_unseen` | One ranked instruction per route, ranked routes 1–40 of each scene | 500 actions |
| `max` | 1,839 / 778 | The complete declared split, in dataset order | 500 actions |
| `example` | 1 | The first `fast` episode | 500 actions |

`fast` groups episodes by scene and route, keeps the instruction with the
lowest `sha256("vlnce-panel55-20261028:instruction:<episode_id>")`, ranks each
scene's routes by `sha256("vlnce-panel55-20261028:<scene_id>:<trajectory_id>")`,
keeps ranks 1–40 and orders them rank-major over sorted scene IDs. Dataset path, scene root, split, mode and
reset seed are operator inputs fixed before any claim. The server validates selected scenes
without choosing substitute episodes. Native IDs, starting poses, routes, goals
and scene paths remain evaluator-private; actor episode labels are opaque.
The native episode ID is recorded in each episode's metadata and metrics.

At construction the dataset file must hold exactly the released episode count of
the declared `split` (778 or 1,839); any other count is a configuration error,
not a policy failure. The adapter compares the sha256 of the raw
`<split>.json.gz` (and optional `<split>_gt.json.gz`) bytes with the
`DATASET_SHA256`/`GT_SHA256` pins in `bench_server/adapter.py`. The VLN-CE data
page publishes no checksums, so the pins start unset: until an operator records
them from a verified copy of `R2R_VLNCE_v1-3_preprocessed.zip`, the observed
dataset hash is recorded in the descriptor `source_revision` and marked
`unpinned`. Each split or GT JSON is limited to 64 MiB decompressed in both the
service and the native worker, a memory guard against an oversized gzip file.
The test split needs its separate official scoring process and is not supported.

## Runtime identity

Protocol: `vln-ce-habitat033/r2r-native500/rgb512/{mode}/v1`.

The native worker uses Habitat-Lab and Habitat-Sim reporting version 0.3.3 and
the installed `benchmark/nav/vln_r2r.yaml` configuration. It records package
versions, relevant source fingerprints, resolved configuration and asset/data
identities. The native worker interpreter is configured explicitly and may be
separate from the Python 3.10+ service. No policy implementation is imported
by the server.

This is a declared Habitat 0.3.3 integration of R2R-VLNCE, not a reproduction of
the earlier [Habitat 0.1.7 integration](https://github.com/LiuRicky/StarVLA-VLN-CE-Evaluation/tree/2e56d1c026b2945b90b4ff339bdec2cb1e42b800).
Do not combine results across native runtime or sensor configurations without
identifying those differences. Native Habitat task, action and success code
remain responsible for execution and scoring.

## Observations

Each acknowledged control provides the current forward RGB image, `512×512`
`uint8`, 90° horizontal FOV, and the route instruction. RGB dimensions are
explicitly configured from the installed default of 256×256. No policy-specific
crop or visual overlay is applied by the benchmark service.

The native configuration can render depth but depth is not a policy input.
The only task sensor is the instruction sensor; the adapter projects its text,
not tokens, trajectory identity or the native observation dictionary. It does
not expose GPS, compass, global pose, maps, goal coordinates, shortest paths,
oracle sensors, collision diagnostics, reward or scoring metrics. The method
may retain the observations and actions already delivered in this episode.

## Action and timing

`ActionSpec.mode = habitat_discrete_navigation_v0`, size **1**, name `action_id`.
Each row must contain an integer-valued number from 0 to 3. Fractional values,
non-finite values, wrong dimensions and out-of-range IDs are rejected without
execution. No rounding or invalid-output fallback is used.

| ID | Native action | Requested effect |
| ---: | --- | --- |
| 0 | STOP | End the native task; counts as one control |
| 1 | MOVE_FORWARD | Move forward 0.25 m; collisions can limit displacement |
| 2 | TURN_LEFT | Turn left by 15° |
| 3 | TURN_RIGHT | Turn right by 15° |

Sliding is enabled. The action is not a waypoint or velocity command, and the
service has no route planner or shortest-path follower. There is no declared
wall-clock control frequency for discrete Habitat actions (`control_hz=null`).
Saved video uses 10 FPS for presentation only; it does not change execution.

One sequenced service step executes one native action. The agent chooses chunk
length and when to reason again. Execution stops at native termination or the
500-control horizon; no unexecuted chunk suffix carries into another episode.
An optional inference-call cap is a method setting, not a benchmark budget.

## Termination and score

The native limit is **500 actions**, including STOP. Exhaustion maps to
`truncated`; an explicit native STOP maps to `terminated`. Closing a session,
policy abort or budget exhaustion never inserts STOP automatically.

The service sets the native `Success` measure's threshold to **3 metres**,
the R2R-VLNCE criterion. This explicitly overrides Habitat 0.3.3's generic
0.2-metre default. Habitat itself reports success only when STOP was executed
and final geodesic distance is strictly below the threshold. Entering that
radius during a route does not establish terminal success.

Metrics are taken from native `get_metrics()`:

- `success`: native STOP-aware success, normalized to boolean;
- `distance_to_goal`: final geodesic distance in metres;
- `spl`: native success weighted by path length;
- execution counters and native termination reason.

The wire reward is a neutral 0.0, not a task progress signal. Metrics and
native result metadata remain with the evaluator and are never included in
policy observations. Per-step transition info carries only native success and
the step count; distance and SPL are reported once, in final metrics. Non-finite or missing required metrics are explicit
infrastructure errors. nDTW, oracle success/SPL and path-length reports from
the older extended evaluator are not currently implemented; their absence is
not a zero score. Optional GT files are checked and retained as provenance,
but do not imply that additional metrics were computed.

## Recording and reports

Report the split, `evaluation_mode`, seed, runtime/protocol, success rate
denominator, SPL, final distance, actual decisions/controls and termination.
Keep infrastructure errors distinct from unsuccessful completed routes.
RGB videos contain the same camera observations, without oracle overlays;
standard retention keeps videos on the server and removes temporary frame PNGs
only after successful finalization. See [recording settings](../../../docs/recording.md).
