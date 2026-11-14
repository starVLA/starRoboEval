# MetaWorld MT50 direct-control protocol

MT50 comprises 50 manipulation task families. The
[native evaluation procedure](https://metaworld.farama.org/evaluation/evaluation/)
specifies 50 goal configurations per task, one episode per configuration and
success when the native success flag is reached at any step. The current
service's reset selection is narrower, as described below.

The service evaluates selected MT50 tasks with native 500-control episodes:
one stabilization control followed by at most 499 agent-selected controls.
Task selection, seed and image orientation are fixed before execution. Record
the protocol identity returned by the service with those conditions. See the
[SIM server protocol](../SERVER_PROTOCOL.md) for the agent/environment boundary.

## Native identity and task selection

The native implementation is the public `metaworld==3.1.1` distribution, with
MuJoCo 3.3.0, Gymnasium 1.3.0 and NumPy 1.24.4. The checked-in
[package pin](environment/package_pin.json) records SHA-256 and size for all
440 shipped package files (325 bundled assets), checked against installed wheel
RECORD entries and actual bytes. Its canonical file-inventory SHA-256 is
`768366070ab463f23539105601f530461ffb0523946f889749295a0a2c367454`.
This is a distribution-content pin rather than a Git revision. Runtime checks
reject different package bytes, versions, import shadowing or unexpected native
files before constructing an environment. Renderer and driver requirements are
documented in [environment setup](environment/README.md).

The server also explicitly pins `packaging==26.2`, an import-time dependency of
Gymnasium's optional MuJoCo renderer. Environment setup verifies the native
import path as well as package metadata; neither check constructs an episode.

MT50 contains **50 task families**. [task_catalog.json](bench_server/protocol/task_catalog.json)
defines their native order, names and language instructions. It also supplies
easy/medium/hard/very_hard group labels (28/11/6/5), which are an integration
taxonomy rather than a native difficulty standard.

### Current service selection

Select a unique list of canonical catalog `task_names`; other spellings are
rejected. The service schedules one episode per selected task, in declared
order, with an explicit seed. The example chooses `reach-v3` and seed 4042. Fix the task/seed selection
before observing outcomes; retain unsuccessful attempts and errors.

The native constructor generates a pool of **50 goal/reset configurations per
task family**. The current service does not iterate this pool. Each selected
task constructs a fresh seeded
MT50 and evaluates the first native reset for that environment. This independent
fresh-task construction differs from carrying one vector environment through a
multi-episode aggregate. The interface does not expose a layout/reset index.
The seed controls native randomization and is not a one-to-one layout label;
different seeds do not guarantee visibly different scenes. Additional
task/seed samples require their own predeclared service schedules.

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
   the retained evaluator. It consumes one of the native 500 steps. Then deliver
   the first public image at model control step 0, with 499 controls remaining.

Neither selected wrapper nor unwrapped base exposes `iterate_goal_position` in this pin;
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

| `image_orientation` | Public pixels |
| --- | --- |
| `rot180` (default) | Native RGB rotated exactly 180 degrees |
| `native` | Native RGB without any additional transform |

The pinned native `corner2` camera produces an upside-down view in the inspected
headless render. Gymnasium already performs its own documented vertical
framebuffer correction; the additional deterministic 180-degree rotation is a
benchmark-owned camera-view convention, not a renderer patch. It reverses both
image axes, preserves every pixel and channel, and is applied identically to
policy observations, recorded PNGs and videos. Provenance records the selected
orientation and exact transform. Compare only matching observation conditions.
Images are copied to detach native backing buffers; a malformed image is an
error rather than permission to guess a transform or render another frame.

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
| Maximum model-selected controls | 499, the native horizon minus stabilization |
| Setup control | 1 no-op, recorded separately and counted inside the native horizon |
| Maximum raw controls in this track | 500, excluding native constructor/reset internals |

The first native end, explicit policy stop, error or exhausted limit ends the
attempt. The native budget comes from `SawyerXYZEnv.max_path_length = 500` in
the pinned MetaWorld 3.1.1 package; its `step` returns truncation at that count
and rejects another action until reset. The server does not modify this value.
The stabilization action is a native step, not a free extra model control.

The service publishes `environment_step_cap=499` in `describe`, plus
`native_horizon=500` and `settle_steps=1` in episode metadata. A client using
model-control counters must declare 499, not 500. A call allowance does not
multiply or extend that cap. Policies choose how many controls to submit per
decision; no inference frequency or five-step grouping is required by this
benchmark. Invalid submissions consume calls but no execution steps.

`info["success"] == 1` returned by the native step is authoritative. The
retained evaluator ends at the first success; this adapter maps it to termination
without calling an additional task predicate. Native termination/truncation is
also retained. After one setup plus 499 unsuccessful model controls the native
horizon is exhausted; the adapter also enforces that same remaining-control
boundary and rejects later actions without another native call. It does not
infer completion from pixels, language or a generic stop response. Native
reward is recorded evaluator-side, but is never given to the policy.

Record policy calls, executed action decisions, controls, setup controls and
derived policy physics ticks separately. A stop response uses one policy call
but no native control. Interrupted native calls may have uncertain execution;
native action-start/end records are evidence, not permission to retry.

## Reporting

Essential results retain the seed/task schedule, benchmark/protocol and method
configuration, action/observation contracts, budgets, native outcome/error and
separate counters. Recorded source/runtime identities describe the conditions;
usage/provider identity remains unknown if not recorded.

Give task and seed coverage, selected/completed/error counts and the denominator
of every success rate. Native reward is separate from success. Optional
interactions and media follow [recording](../../../docs/recording.md). Recorded
video uses 80 fps and starts after stabilization; it represents control timing,
not model deliberation wall time.

Results belong under `AgentPolicies/<profile>/results/metaworld/`. For comparison
with another evaluator, match task/reset sampling, camera orientation, control
budget and aggregation. Do not mix different budgets or observation conditions
into one success rate.
