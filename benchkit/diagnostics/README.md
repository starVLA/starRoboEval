# Shared infrastructure diagnostics

This package contains harness-owned fixtures, not participant model policies.
`constant.py` returns a supplied fixed action chunk through the same `Policy`
interface used by real methods. It performs no model inference and does not
plan actions from observations. Its descriptor labels every run
`infrastructure_validation_only`.

Select it with `rsi-bench run --sim-server URL --policy constant`; action
validation, chunk length and execution budgets are unchanged. Using this policy with a native adapter can
move the robot or simulator, so only run it as an explicitly authorized
diagnostic with valid actions and environment safety checks. It is not a task
capability score or a named-model baseline.

Old recorded source inventories remain data with their original bytes; there is
no `AgentPolicies.diagnostics` compatibility shim in the current source.

`smoke.py` holds the synthetic reach world that `python -m benchkit.sim_server`
serves and the scripted policy (`--policy scripted`) that `make smoke` runs
against it through that service. `registry.py` maps the `--policy` names to
the fixtures: `constant` to `constant.py` and `scripted` to `smoke.py`.

`robot_state_hold.py` is an explicit one-control SIM-only sensor/target wiring
check. The operator must first confirm that the identically named public sensor
and action fields mean absolute robot targets in the same units and frame. It
echoes that state once through the ordinary authenticated SIM server client,
not through a private simulator handle. The server must declare
`diagnostic=true`, and `--confirm-absolute-state-targets` is mandatory. It does
not infer a task action or guarantee physical holding, and must never be used
on real hardware. Its one fixture decision has zero model requests and is not
a capability score. Keep these artifacts separate from scored model attempts.

`probe.py` backs `python -m benchkit probe`, the shared connect-level readiness
check for every service. It describes the service, claims one episode, resets it
and closes it, then prints a JSON summary of identity, mode, schedule, budgets,
observation shapes and timings. It runs no policy and sends no action, because
the protocol declares no neutral action. Failures report a class, closed code
and phase; the token is never printed. The claim is permanent, so probe a
dedicated launch. See the [readiness probe](../../benchmarks/simBenchmarks/SERVER_PROTOCOL.md#readiness-probe).

Native-only asset and rendering checks that need no service belong under the
corresponding benchmark's `benchmarks/.../environment/`. Participant policy
behavior belongs under `AgentPolicies/<profile>/`.

Checks for this package stay local and untracked. The presence of these
diagnostic tools is not evidence of a passed native evaluation.
