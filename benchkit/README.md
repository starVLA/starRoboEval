# Shared communication and evaluation tools

`benchkit/` provides shared SIM communication, data/result formats, recording,
service source snapshots, audits and reports. Its libraries and
commands are not a mandatory per-action control process. The reusable agent-side
loop is `AgentPolicies/gpt6_astra/tools/runner.py`, also used by the general CLI;
[`sim_server/`](sim_server/README.md) implements transport, serialization and session
lifecycle used by benchmark-owned servers and trusted drivers. Native tasks/scorers and model
decisions do not belong here.

- `contracts.py` / `interfaces.py`: public observation, action and lifecycle types.
- `methods.py`: protocol-first method composition and per-component usage declarations.
- `recording.py`: default-on optional interaction/client retention preferences and SDK sink.
- `registry.py`: the shared diagnostic policies selectable with `--policy`.
- `sim_server/`: the only shared SIM communication implementation; not a compatibility alias.
- `catalog/`: packaged benchmark declarations and their loader/validator.
- `cli.py`: shared catalog/diagnostic commands. `run` takes its benchmark only
  from a running service (`--sim-server`); `smoke` starts the synthetic service
  and runs through it; `probe` checks one service's connect-level readiness. Participant entrypoints can use the service protocol directly.
- `model_profiles.py`: reads self-describing `configs/profile.json` files and
  validates configuration/factories; actual factories remain under
  `AgentPolicies/<profile>/`.
- `source_snapshot.py`: bounded service source capture, limited to
  `SERVICE_SOURCE_FILES` plus benchmark-declared supplemental files.
- `diagnostics/`: shared synthetic and fixed-action infrastructure fixtures;
  these are not participant models or task-solving baselines.
- `audits/`: offline record-consistency validation (`closed_run.py`), not source
  verification, native replay or provider attestation.
- `reports/`: shared run summaries, panel SR comparison, interaction views and
  named-model publication. The panel report
  preserves policy failures, infrastructure errors and missing closed results;
  it does not select or retry cases or infer that missing evidence means no attempt.

Native adapters and selection plans live under
[`benchmarks/simBenchmarks`](../benchmarks/simBenchmarks/README.md). Policies, shared
policy support and results live under [`AgentPolicies`](../AgentPolicies/README.md).

```sh
python -m benchkit catalog --check
python -m benchkit list
```

`list` shows the diagnostic policies; `rsi-bench list` and `catalog` show the
benchmarks. Test and check files stay local and untracked. `make check`
validates current catalog data, and `make smoke` runs the dependency-free
self-check through the synthetic service. Neither
replaces native simulator, model or hardware validation.

The console entrypoint remains `starvla-eval`. Removed flat modules and the
`benchkit.runner` bridge have no compatibility shims. All live decision-loop
callers import `AgentPolicies.gpt6_astra.tools.runner` directly. Old records
remain data with their original bytes; live code does not read their source
bundles. This directory migration does not start evaluations or complete native
max presets.

For ordinary closed results use `benchkit.reports.basic_result`; it does not
require events, media or source snapshots. `interaction_history` reads the
trajectory ledger that every recording mode writes. See [recording/results](../docs/recording.md). Neither
report makes Python Policy mandatory or attests native/provider execution.

The specialized `benchkit.reports.publication` turns closed named-model results
into a compact public view under the model's `results/<benchmark>/` directory.
`--raw-run` is either one closed client run (optionally a `client/` + `server/`
pair) or a `remote-run` output directory. For a remote run, the planned cases
in its `plan.json` are the denominator. A case's outcome is its first attempt:
the oldest lease whose client run closed a row that is not an infrastructure
error, with or without a completion record (a policy error exits nonzero).
Later attempts are listed but not used; leases whose client crashed, never
started or closed only infrastructure errors are not attempts. Cases without an
attempt count as missing results. A single run's denominator is its `manifest.protocol.episode_ids`.
Each client run is audited, its summary checked against its rows, and every
input file hashed. The manifests must carry the profile ID (equal to the result
namespace), a 64-hex `preset_sha256`, and a 40-hex client git revision with its
dirty flag; the rest of the policy parameters is published only as a digest.
The cases of a remote run must share benchmark, policy, method, protocol and
client source. A paired server record binds outcomes and videos; a remote run,
or a single run without its `server/` pair, is bound to the client-held SIM
receipts only, and server-only videos are listed as hash references. Only a
complete panel without infrastructure errors is accepted. Usage totals are
published with `usage_incomplete_episodes`, and each episode keeps
`usage_reported_complete` and `usage_inconsistent_fields`, so totals are not
read as final while a policy's own usage report was incomplete or inconsistent.
`--reference SUCCESSES/EPISODES` adds an operator-declared comparison.
All checks run before any file is written; it never moves raw evidence or
changes a score. Re-publishing identical content is a no-op. A publication that
is not accepted is replaced in full (report and media directory) when the new
one comes from the same source: the same raw directory name and the same planned
profile, panel and cases, such as a remote run that has closed more cases since.
An accepted publication is never replaced.

```sh
python -B -m benchkit.reports.publication \
  --raw-run records/ \
  --results-root AgentPolicies/gpt6_astra/results/<benchmark> \
  --task-description <task>=<short-english-description>
```
