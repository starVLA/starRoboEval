# Realman evaluation integration

Reserved for a future Realman hardware benchmark adapter. No executable unified
evaluation or safety-certified robot interface is implemented here yet.

The original README records historical RM-75 image/state/action assumptions.
Those training-time assumptions are not a newly verified physical action
contract. The retired ACT/DP recipes and registry remain in Git history and the
local ignored `barks/` archive; they are not active RSI workflows.

Next implementation should pin the actual hardware/sensors, action semantics,
control/safety limits, operator authority, tasks and objective success criteria.
Model implementations and results belong to `AgentPolicies/<profile>/`; native hardware
I/O and evaluation conditions belong here. Begin with mock/replay checks, not
unattended motion. This directory cleanup executes no robot or training recipe.
