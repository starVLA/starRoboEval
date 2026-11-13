# Shared infrastructure diagnostics

This package contains harness-owned fixtures, not participant model policies.
`constant.py` returns a supplied fixed action chunk through the same `Policy`
interface used by real methods. It performs no model inference and does not
plan actions from observations. Its descriptor labels every run
`infrastructure_validation_only`.

The CLI name remains `--policy constant`; action validation, chunk length and
execution budgets are unchanged. Using this policy with a native adapter can
move the robot or simulator, so only run it as an explicitly authorized
diagnostic with valid actions and environment safety checks. It is not a task
capability score or a named-model baseline.

Old recorded source inventories remain data with their original bytes; there is
no `AgentPolicies.diagnostics` compatibility shim in the current source.

`robot_state_hold.py` is an explicit one-control SIM-only sensor/target wiring
check. The operator must first confirm that the identically named public sensor
and action fields mean absolute robot targets in the same units and frame. It
echoes that state once through the ordinary authenticated SIM server client,
not through a private simulator handle. The server must declare
`diagnostic=true`, and `--confirm-absolute-state-targets` is mandatory. It does
not infer a task action or guarantee physical holding, and must never be used
on real hardware. Its one fixture decision has zero model requests and is not
a capability score. Keep these artifacts separate from scored model attempts.

Native asset, rendering, reset and control readiness tools belong under the
corresponding benchmark's `benchmarks/.../environment/`. Participant policy
behavior belongs under `AgentPolicies/<profile>/`.

Historical CPU test fixtures for this package are no longer included in the
active source tree and can be recovered from Git history. The diagnostic tools
described here remain available; their presence is not evidence of a passed
native evaluation.
