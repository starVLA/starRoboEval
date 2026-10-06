# Unitree G1 whole-body evaluation integration

Future hardware benchmark entrypoint. The retained SONIC/GR00T-WBC bridge,
controller and sensor-schema notes are references; there is no unified runnable
RSI real-robot adapter or certified whole-body safety/score parity here.

| Reference | What to retain | What it does not establish |
| --- | --- | --- |
| [SDK/controller notes](sdk_tools/README.md) | Controller dependencies, observation/action and safety review questions | Current hardware readiness or permission to actuate |
| [Deployment bridge](step3_deployment/README.md) | Historical server/client grouping, normalization and mock/replay route | A model-agnostic `BenchmarkAdapter` or a working RSI checkpoint server |
| [Interface reference](INTERFACE_REFERENCE.md) | Historical sensor/action dimensions and operator safety gates | A verified physical action contract or an active training requirement |

Training-oriented demonstration collection, dataset conversion and step2
training instructions are removed from the active tree and remain recoverable
from Git history. The existing deployment directory name is retained so its
launch paths do not change; it does not require completing training steps here.

A future benchmark owns declared sensors, native controller commands, hardware
interlocks, tasks and objective outcomes. Model serving, motion generation,
model-specific auxiliary IK and voluntary stopping belong to `AgentPolicies/<profile>/`.
Public controller capabilities and latencies must be frozen as part of the track.
Require explicit hardware/operator authority and mock/replay acceptance before
real execution. This reorganization does not launch a model server or robot.
