# Three selected SIM-server development cases

Each task was explicitly selected because a historical attempt had recorded native
success. Each received exactly one new Codex-controlled attempt; historical action
trajectories and scorer feedback were not supplied to the live actors. There was
no automatic retry or replacement. These are integration cases, not representative
sampling, native full evaluation or a verified named-model score.

| Benchmark / selected task | Policy calls | Action decisions | Controls | Native result / qualification |
| --- | ---: | ---: | ---: | --- |
| [SimplerEnv: horizontal-can pickup](simpler_env/reports/2026-09-15-SIM-SERVER-CODEX-CASE.md) | 49 | 48 | 109 | False; ordinary policy stop |
| [SIMPLE: open faucet](simple_humanoid/reports/2026-09-15-SIM-SERVER-CODEX-CASE.md) | 30 | 29 | 145 | False; ordinary policy stop |
| [RoboCasa365: NavigateKitchen](robocasa365/reports/2026-09-15-SIM-SERVER-CODEX-CASE.md) | 10 | 9 | 41 | False; safety stop with native RGB anomaly |

All first-native-success fields remain null. One final stop call in each episode
does not execute an action, and an action decision can contain several controls;
the counters therefore intentionally differ. The predeclared limit was 200 policy
calls, prefix length up to 5, and 1000 controls. Ordinary give-up minimum was 0,
a policy setting rather than a benchmark rule. No extra persistence constraint
was introduced midway through a task.

## Architecture exercised

- `examples/simBenchmarks/<benchmark>/server.py`: independently launched native
  environment, task schedule, physical control and native scoring.
- `harness/sim_server/`: evaluator-private client, strict transport and lifecycle;
  shared runner retains decisions, controls, scores, provenance and artifacts.
- `starVLA/anonymous_code_agent/`: model policy, declared prompt/configuration,
  mailbox actors and results. The actor sees declared RGB/language/proprioception
  only, never SIM credentials, native scorer metadata or reset-state files.

The generic server has no task-solving or hybrid-policy RPC. Policies ran in fresh
contexts using only their opaque mailbox. This operational restriction is not a
claim of OS-enforced sandboxing or independently attested provider identity.
No model API was configured. Model/provider snapshots and token/cost accounting
remain unknown, so these attempts must not be relabeled GPT6Astra or Opus.

## Evidence and remaining limits

Execution used immutable source commit
`c2a54f323ebb2b7bafacd6dab8ca27dc7208a52d`. All 558 tracked snapshot files and the
three startup source captures (72/75/72 files) matched that commit both before
and after the attempts. This checks source bytes, not loaded memory or asset parity.
All three generic closed-record audits passed and server/evaluator processes exited
0 without recorded native/cleanup errors. Original records are retained; six
exact-byte videos are indexed under the three model result directories.

The RoboCasa observation anomaly is present in native artifacts before transport.
It is not a clean model capability failure or a fully validated native path.
Its original false result remains visible, qualified separately; do not silently
exclude it from the selected cases or summarize this table as a clean aggregate
model success rate. Diagnosis requires a separately authorized native investigation.

The implementation/review/regression loop added conservative offline RGB checks
and identified SIMPLE cache-transfer overhead. Neither finding was used to repair
or replay a scored attempt. Follow-up changes apply to future invocations only.
CPU verification passed all 825 tests across ten groups on the follow-up snapshot,
then the final cache launcher passed the 26-test SIMPLE and 206-test harness
groups. Two additional exclusion semantics tests passed with the 17-test server
suite. This covers 829 distinct tests, with zero skips; these synthetic tests do
not launch native capability evaluations.
The HTTP service interface does not yet integrate frozen campaign prepare/run-case
or native-full sampling. Existing compatibility commands and old records retain
their original semantics; service entrypoint availability alone is not parity.
