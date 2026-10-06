# Real-robot evaluation surface

This directory is retained for future real-robot evaluation. It is **not** a
training workflow and does not currently provide a unified runnable
`BenchmarkAdapter` / `EpisodeSession` for hardware. Existing clients, model
bridges and deployment notes are references, not permission to actuate a robot
or proof of safety/score parity.

| Entry | Useful retained material | Migration boundary |
| --- | --- | --- |
| [Franka](Franka/README.md) | Single-/dual-arm image/state/action client examples | Old checkpoint/WebSocket normalization and inference loops require separation from a future hardware adapter |
| [Unitree G1 WholeBody](UnitreeG1_WholeBody/README.md) | SDK/SONIC controller notes, deployment bridge and mock/replay guidance | Preserve controller/safety references; old StarVLA model serving and training are not active evaluation |
| [RoboChallenge Table30v2](RoboChallenge_table30v2/eval_files/README.md) | Server I/O contract, robot schemas and mock/self-test references | Existing class loads a StarVLA checkpoint directly; it is not a neutral hardware benchmark adapter |
| [Realman](Realman/README.md) | Previously documented observation/action schema | Training recipes are historical reference; native evaluation/safety integration remains pending |

The removed EgoVLA model bridge remains recoverable from Git history; it is not
an active hardware benchmark entrypoint. G1 hardware references remain under
Unitree G1 WholeBody above.

Model-specific serving, normalization, planning and auxiliary IK belong to the
model/method in `AgentPolicies/`. Native sensor collection, declared action dispatch,
hardware stop/interlock handling, tasks and objective evaluation rules belong to
the robot's eventual benchmark adapter here. Never move a model's extra perception
or controller capability into the hardware interface without declaring that track.

Before any physical evaluation, explicitly establish hardware ownership and
operator authorization, local emergency-stop/guardrail procedures, calibrated
action units/frames and rate limits, sensor whitelist, timeout handling, task
success rules and artifact capture. Validate mock/replay first; simulator checks
do not certify hardware safety. This repository reorganization launches no robot.

Training recipes, demonstration-collection workflows and dataset-conversion
guides are removed from the active tree; Git history retains their originals.
Useful sensor/action context and safety gates remain in the hardware guides.
Evaluation tests, mocks and deployment code are retained; this cleanup does not
convert historical checkpoint integrations into neutral hardware servers. New reports and
videos belong to the evaluated model's `results/<robot-benchmark>/` namespace;
never overwrite old evidence to fit a new directory layout.
