# MetaWorld MT50 direct-control protocol

MT50 comprises 50 manipulation task families. The
[native evaluation procedure](https://metaworld.farama.org/evaluation/evaluation/)
specifies 50 goal configurations per task, one episode per configuration and
success when the native success flag is reached at any step. The service's
`max` mode follows its goal schedule and success rule, with one stabilization
control before the agent's controls (below); `fast` and `example` are smaller
selections.

The service evaluates MT50 tasks with native 500-control episodes:
one stabilization control followed by at most 499 agent-selected controls.
Evaluation mode, seed and image orientation are fixed before execution. Record
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
files before the first environment is constructed. They run once per service
process and are recorded in every episode's provenance. Renderer and driver requirements are
documented in [environment setup](environment/README.md).

The server also explicitly pins `packaging==26.2`, an import-time dependency of
Gymnasium's optional MuJoCo renderer. Environment setup verifies the native
import path as well as package metadata; neither check constructs an episode.

MT50 contains **50 task families**. [task_catalog.json](bench_server/protocol/task_catalog.json)
defines their native order, names and language instructions. It also supplies
easy/medium/hard/very_hard group labels (28/11/6/5), which are an integration
taxonomy rather than a native difficulty standard.

### Current service selection

`evaluation_mode` selects the schedule. In `fast`, trial `k` of every task uses
seed launch seed + `k`. In `max`, every episode uses the fixed goal-pool seed
4042, which must also be the launch seed.

| Mode | Selection | Episodes | Cap |
| --- | --- | ---: | --- |
| `fast` (default) | All 50 tasks × 5 trials, catalog order | 250 | 499 controls |
| `max` | All 50 tasks × 50 native MT50 goals, goals 0–49 once each | 2500 | 499 controls |
| `example` | First `fast` episode: `assembly-v3`, trial 0 | 1 | 499 controls |

Both multi-episode schedules are task-major: all trials or goals of catalog task
0, then task 1, and so on. `fast` episode IDs are `<task>-seed<seed>-episode<k>`;
`max` episode IDs are `<task>-seed4042-goal<GG>` with `GG` from 00 to 49. The
protocol identity is
`metaworld-3.1.1/mt50-native500/rgb480-corner2[-rot180]/<mode>/v1`. The example
launch uses seed 4042. Fix the mode and seed before observing outcomes; retain
unsuccessful attempts and errors.

The native constructor `metaworld.MT50(seed=seed)` generates a pool of **50
goal/reset configurations per task family** (`_N_GOALS = 50`, each verified
unique by the constructor). The pool is pure task data: each entry carries one
frozen goal/initial-state vector for its class.

- `fast` does not iterate this pool. Each trial gets a freshly constructed,
  never-reset native environment and evaluates its first native reset, whose
  goal the native wrapper draws from its own pool. The interface does not expose
  a goal index, and distinct seeds do not guarantee visibly different scenes.
- `max` builds one pool with `metaworld.MT50(seed=4042)` and evaluates every
  entry exactly once. Episode metadata records `goal_pool_seed`, `goal_index`
  (position within the task's 50 goals) and `mt50_train_task_index`
  (`native_id × 50 + goal_index` in `pool.train_tasks`). The goal index is a
  pool position, not a visible layout label.

Each episode still constructs its own native environment rather than carrying
one vector environment through a multi-episode aggregate.

The documented procedure selects goals with `iterate_goal_position()`, which the
pinned 3.1.1 wheel does not provide. Its shipped `metaworld.evaluation.evaluation`
(`num_episodes=50`) instead runs the `gym.make_vec("Meta-World/MT50")` vector,
whose `RandomTaskSelectWrapper` draws a goal uniformly *with replacement* from
the same 50-goal pool at every reset. That helper has the same 50 × 50 episode
count, but some goals may repeat while others are skipped. `max` follows the
documented one-episode-per-goal procedure using only native pool data and native
`set_task`; it does not reproduce that helper's draw sequence.

## Reset and setup

Adapter construction, schedule inspection, `describe` and `open` create no
native environment. One claimed `reset` performs:

1. Verify source/dependency pins (first reset of the service process only).
2. Build the native task pool `metaworld.MT50(seed=seed)` (first reset per
   seed only). This native constructor instantiates all 50 classes and performs
   its own goal-generation resets under its own seeded NumPy stream, then
   restores global NumPy. The pool is pure task data, reused for later tasks
   with the same seed. These internal resets are setup, not model actions.
3. Seed NumPy with the recorded seed and construct only the selected class with
   native `metaworld._init_each_env`, using exactly the arguments that
   `gym.make_vec("Meta-World/MT50", vector_strategy="sync", seed=seed,
   render_mode="rgb_array", camera_name="corner2", width=480, height=480)`
   passes for that sub-environment. Sub-environments share no state or RNG, so
   the other 49 are not built. Check action bounds, native timestep, frame
   skip, action scaling and native horizon.
4. Select the goal, then call the native wrapper's `reset(seed=seed)`.
   - `fast`/`example`: native `RandomTaskSelectWrapper` selects its goal before
     forwarding the reset.
   - `max`: the adapter takes goal `goal_index` from the task's 50 pool
     entries (filtered by class, as `make_vec` passes them), calls the native
     `toggle_sample_tasks_on_reset(False)` on that wrapper and the native
     `set_task(goal)` on the base environment, then resets. After reset it
     checks that the base environment still holds that goal's frozen vector
     and logs the vector's SHA-256 evaluator-side.

   The underlying `SawyerXYZEnv.reset` documents that the seed argument is
   ignored, while construction already called the native `seed()` method.
   Preserve that ordering, rather than reseeding or sampling a goal with custom
   code. No environment under the pinned `envs/` package draws random numbers
   at reset, so a pinned goal fully determines the native reset state
   (source inspection only, not a replay check).
5. Execute exactly one native zero action `[0,0,0,0]` for stabilization, as in
   the retained evaluator. It consumes one of the native 500 steps. Then deliver
   the first public image at model control step 0, with 499 controls remaining.

Neither selected wrapper nor unwrapped base exposes `iterate_goal_position` in this pin;
the adapter records `goal_iteration_method: null`. An unexpected callable is
version drift and fails visibly, rather than changing goal selection. In `max`,
a missing or duplicated `RandomTaskSelectWrapper`, a non-contiguous goal pool or
a goal not retained through reset is also version drift. Native
setup errors are not swallowed. Success/termination during stabilization is an
initialization error, not a model success.

The adapter owns and closes its selected native environment. An uncertain/failed control or render poisons further actions.
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

Essential results retain the seed/task schedule (and, in `max`, the goal-pool
seed and goal index), benchmark/protocol and method
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
