# RoboChallenge Table30v2 — Evaluation Pipeline

This is a retained checkpoint-integration reference. It requires the original
StarVLA model runtime, not just the current RSI package. The local self-test and
I/O contract remain as integration references; they do not establish a neutral
hardware bench server or authorize production submission.

We follow the upstream
[RoboChallengeInference (cvpr branch)](https://github.com/RoboChallenge/RoboChallengeInference/tree/cvpr)
step-by-step approach: **first self-test offline, then drive the mock server,
then submit to the real platform**.

```text
local_self_test.py        ← step 1: dummy obs, no network
production_demo.py        ← step 3 (TODO): wire to demo.py / job_loop on the real challenge
model2robochallenge_interface.py
                          ← shared `RoboChallengePolicy` (replaces upstream `DummyPolicy`)
```

## I/O contract (with the RC server)

| Direction | Endpoint | Robot=`ur5` |
|---|---|---|
| GET state | `/state.pkl` with `image_type=cam_global,cam_arm` and `action_type=leftjoint` | returns `{images: {cam: PNG}, action: joint(6)+gripper(1) = 7-d, state, pending_actions, timestamp}` |
| POST action | `/action` with `action_type=leftpos` | body `{actions: [[ee_pose(7) + gripper(1)], ...], duration: 0.05}` |

We deliberately use **two different action_types per cycle**: `leftjoint` to
fetch the joint state our model was trained on, `leftpos` to post the 8-d
ee-pose actions our model produces. The mock server treats each request
independently so this is fine.

> Only a checkpoint whose declared input state is ee-pose can use `leftpos`
> for both `state_action_type` and `post_action_type`. Verify that contract;
> changing a selector cannot convert a joint-state checkpoint.

Robot specs (`image_types`, `state_dim`, `action_dim`) live in
`model2robochallenge_interface.py::ROBOT_SPECS` and must match the selected
checkpoint's input/output schema and the platform contract. The original
dataset registry is historical provenance in Git, not an active RSI dependency.

## Step 1 — local self-test (no network)

Loads the checkpoint, runs forward on a synthetic observation, prints the
action chunk + latency. **Run this first** any time you swap the checkpoint or
the framework.

```bash
bash benchmarks/realRobots/RoboChallenge_table30v2/eval_files/run_self_test.sh
# or override the defaults:
CKPT=playground/Checkpoints/.../steps_100_pytorch_model.pt \
ROBOT_TAG=ur5 PROMPT="shred the paper" \
bash benchmarks/realRobots/RoboChallenge_table30v2/eval_files/run_self_test.sh --n_runs 5
```

Expected: prints `(8, 8)` action chunk + ~hundreds-of-ms latency.

## Step 2 — upstream mock-server reference

1. Clone upstream **once** (somewhere outside the starVLA repo so it isn't tracked)::

    ```bash
    mkdir -p ~/playground/Code && cd ~/playground/Code
    git clone -b cvpr https://github.com/RoboChallenge/RoboChallengeInference.git
    cd RoboChallengeInference && pip install -r requirements.txt
    ```

2. **Pick an episode** to replay and edit `mock_server/mock_settings.py`:

    ```python
    ROBOT_TAG = 'ur5'
    RECORD_DATA_DIR = '../20260413/ur5/arrange_fruits'   # or any ur5 task directory
    ```

3. Start the mock server (port 9098):

    ```bash
    cd mock_server && python3 mock_robot_server.py
    ```

The former local mock client and launcher are recoverable from Git history.
The upstream setup above documents the protocol reference; connecting a client
requires a compatible implementation.

## Step 3 — production submission (TODO)

Mirror upstream `demo.py` + `robot/job_worker.py::job_loop`. Replace
`DummyPolicy` with `RoboChallengePolicy(checkpoint, robot_tag=...)`. We have
not implemented or validated this production path. The following is an
integration sketch, not a current submission command:

```python
from benchmarks.realRobots.RoboChallenge_table30v2.eval_files.model2robochallenge_interface import RoboChallengePolicy
policy = RoboChallengePolicy(args.checkpoint, robot_tag="ur5")
gpu_client = GPUClient(policy)
job_loop(client, gpu_client, args.submission_id, [224, 224],
         policy.image_type, policy.state_action_type, duration)
```

Caveat for the real `job_loop`: it uses a single `action_type` for both get/post.
Before production integration, resolve this mismatch using a checkpoint with
matching state/action semantics or a separately reviewed state-fetch bridge.
Do not silently relabel joint measurements as ee-pose. Passing the mock test
does not establish that the production loop supports mixed action types.
