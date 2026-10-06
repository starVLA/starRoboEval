# MetaWorld MT50 direct-control protocol

Status: **development adapter; native parity and full schedules remain pending**.
Default protocol ID:
`metaworld-mt50-3.1.1/rgb480-corner2-rot180/control400/fast-v2`.
The explicit `image_orientation="native"` compatibility track retains
`metaworld-mt50-3.1.1/rgb480-corner2/control400/fast-v1`.
The server is an independent process; its credentials and native handles are
evaluator-private. See the [SIM server protocol](../SERVER_PROTOCOL.md).

## Native identity and task selection

The native implementation is the public `metaworld==3.1.1` distribution, with
MuJoCo 3.3.0, Gymnasium 1.3.0 and NumPy 1.24.4. The checked-in
[package pin](environment/package_pin.json) records SHA-256 and size for all
440 shipped package files (325 bundled assets), checked against installed wheel
RECORD entries and actual bytes. Its canonical file-inventory SHA-256 is
`768366070ab463f23539105601f530461ffb0523946f889749295a0a2c367454`.
This is a distribution-content pin, **not an inferred Git commit**. Runtime
verification rejects different package bytes, versions, import shadowing or
unexpected native files before constructing an environment. The pin does not
attest GPU drivers, loaded memory or the full transitive dependency graph.

The server also explicitly pins `packaging==26.2`, an import-time dependency of
Gymnasium's optional MuJoCo renderer. Environment setup verifies the native
import path as well as package metadata; neither check constructs an episode.

MT50 contains **50 task families**. [task_catalog.json](bench_server/protocol/task_catalog.json) freezes
their native order and names. The retained StarVLA evaluator supplies language
instructions and four difficulty labels: easy 28, medium 11, hard 6 and very_hard
5. Those labels are a retained integration taxonomy, not a native MetaWorld
difficulty standard. Native version 3.1.1 renamed five old labels:

| Archived alias | Canonical native name |
| --- | --- |
| `nut-assembly-v3` | `assembly-v3` |
| `nut-disassemble-v3` | `disassemble-v3` |
| `door-v3` | `door-open-v3` |
| `peg-insertion-side-v3` | `peg-insert-side-v3` |
| `sweep-into-goal-v3` | `sweep-into-v3` |

The selector accepts these aliases, normalizes them before scheduling and
rejects duplicates. Every recorded task uses its canonical name. A fast schedule
contains exactly one episode per explicitly selected task, in the declared
order, with an explicit seed. The example chooses `reach-v3` and seed 4042.
No task is substituted or retried after an outcome. A new server output directory
is not permission to repeat a task.

The native constructor generates a pool of **50 goal/reset configurations per
task family**. These are internal randomized native tasks, not 50 scored attempts
or a declared full schedule. Each selected fast task constructs a fresh seeded
MT50 and evaluates the first native reset for that environment. This independent
fresh-task construction differs from carrying one vector environment through a
multi-episode aggregate; do not claim full native equivalence.

`full` is rejected. The historical StarVLA example used 10 episodes per task,
seed 4042 and 400 controls. That historical 500-episode matrix and its macro mean
over four bucket success rates are not implemented or validated as a full
protocol here. No generic harness aggregate replaces that legacy weighting.

## Reset and setup

Adapter construction, schedule inspection, `describe` and `open` create no
native environment. One claimed `reset` performs:

1. Verify source/dependency pins and seed NumPy with the recorded seed.
2. Call native `gym.make_vec("Meta-World/MT50", vector_strategy="sync", seed=seed,
   render_mode="rgb_array", camera_name="corner2", width=480, height=480)`.
   This native constructor internally instantiates environments and performs its
   own goal-generation resets. They are setup, not model actions; native internal
   setup physics is not counted as agent interaction.
3. Select the canonical task index. Check action bounds, native timestep,
   frame skip, action scaling and native horizon.
4. Call the selected native wrapper's `reset(seed=seed)`. Native
   `RandomTaskSelectWrapper` selects its goal before forwarding the reset; the
   underlying `SawyerXYZEnv.reset` documents that the seed argument is ignored,
   while construction already called the native `seed()` method. Preserve that
   ordering, rather than reseeding or sampling a goal with custom code.
5. Execute exactly one native zero action `[0,0,0,0]` for stabilization, as in
   the retained evaluator. Then deliver the first public image at control step 0.

The archived evaluator optionally calls `iterate_goal_position` before reset.
Neither selected wrapper nor unwrapped base exposes that method in this pin;
the adapter records `goal_iteration_method: null`. An unexpected callable is
version drift and fails visibly, rather than changing goal selection. Native
setup errors are not swallowed. Success/termination during stabilization is an
initialization error, not a model success.

The adapter owns and closes all 50 native vector environments, not only the
selected camera. An uncertain/failed control or render poisons further actions.
Cleanup failures remain visible and prevent a clean-close claim.

## Public observation

Each decision receives the task instruction and current `corner2` frame:
480×480 RGB `uint8`, no crop, resize, overlay or depth. The orientation is fixed
before a schedule starts and is part of the protocol identity:

| `image_orientation` | Public full-frame pixels | Protocol suffix |
| --- | --- | --- |
| `rot180` (default) | Native RGB rotated exactly 180 degrees | `corner2-rot180/control400/fast-v2` |
| `native` | Native RGB without any additional transform | `corner2/control400/fast-v1` |

The pinned native `corner2` camera produces an upside-down view in the inspected
headless render. Gymnasium already performs its own documented vertical
framebuffer correction; the additional deterministic 180-degree rotation is a
benchmark-owned camera-view convention, not a renderer patch. It reverses both
image axes, preserves every pixel and channel, and is applied identically to
policy observations, recorded PNGs and videos. Provenance records the selected
orientation and exact transform. Existing native-orientation evidence is not
rewritten or relabelled; compare only matching observation tracks.

The archived VLA bridge also rotated 180 degrees, then center-cropped to
two-thirds and resized to 224×224, with a comment requiring training-pipeline
matching. This protocol reuses only the deterministic full-frame orientation
convention, not that model-specific crop/resize chain. Images are copied to
detach native backing buffers. A malformed image is an error, not permission
to guess a transform or render another frame.

Native state includes privileged object and goal positions. The adapter drops
it entirely: no 39-D state, proprioception, oracle success, reward, object/target
pose, native info dictionary, task sampling state or camera calibration reaches
the policy. Policies may retain previously delivered images/actions, but cannot
query the simulator or request extra images between scheduled decisions.

## Direct native actions

The model returns `[delta_x, delta_y, delta_z, gripper_effort]`, four finite real
numbers each in `[-1,1]`. Booleans, wrong sizes, non-finite or out-of-range values
are rejected before native execution; no clipping, gripper binarization or
fallback action is added by the adapter.

Native `set_xyz_action` moves the mocap target by `0.01 × [dx,dy,dz]` metres in
world XYZ, clipping the target to the native task's workspace. The native mocap
quaternion is fixed to `[1,0,1,0]`; there is no model rotation command. The final
scalar supplies native paired actuator controls `[g,-g]`: positive closes,
negative opens. This is a native low-level controller, not task planning or a
learned action proposal. One selected action calls native `step` exactly once:
five physics ticks of 0.0025 seconds, hence 80 control Hz.

## Limits and native scoring

| Quantity | Protocol |
| --- | --- |
| Underlying native horizon | 500 native controls, unchanged |
| Maximum model-selected controls | 400 |
| Setup control | 1 no-op, recorded separately |
| Maximum raw controls in this track | 401, excluding native constructor/reset internals |
| Example runner mode | `horizon` |
| Example maximum policy calls | 200, including stop/error calls |
| Example maximum executed chunk prefix | 5 explicit controls per decision |

The first native end, explicit policy stop, error or exhausted limit ends the
attempt. A 200-call cap is not a requirement to make 200 decisions or grant 1000
controls. Extending the native/adapter horizon needs a separate protocol; the
current selector does not support a decision-primary 1000-control track.

`info["success"] == 1` returned by the native step is authoritative. The
retained evaluator ends at the first success; this adapter maps it to termination
without calling an additional task predicate. Native termination/truncation is
also retained. At 400 unsuccessful model controls the adapter truncates. It does
not infer completion from pixels, language or a generic stop response. Native
reward is recorded evaluator-side, but is never given to the policy.

Record policy calls, executed action decisions, controls, setup controls and
derived policy physics ticks separately. A stop response uses one policy call
but no native control. Interrupted native calls may have uncertain execution;
native action-start/end records are evidence, not permission to retry.

## Evidence and acceptance

Store source and runtime pin receipts, seed/task schedule, the exact action and
observation contracts, native outcome/error, native action events, every reset/
control image, PNG hashes and a camera-labelled decodable MP4. Frames are
recorded after stabilization and after every successful native control. Video
uses 80 fps to preserve native control timing; model deliberation wall time is
not simulator time. Usage/provider identity remains unknown if not recorded.

Results belong under `AgentPolicies/<profile>/results/metaworld/`. Do not write case
diaries or model strategy constraints into this benchmark's protocol. Shared
record audits are not proof of native execution, source-memory attestation,
native full scores or model identity.

The dependency-light checks use fake native environments only. Before capability
scoring, independently review and validate native reset/render/action/video via
the adapter/server. Native parity still requires fixed-policy checks spanning
each retained difficulty bucket and comparison to the pinned evaluator; no
completed parity claim is implied by this development entrypoint.
