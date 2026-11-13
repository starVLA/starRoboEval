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
- `registry.py`: explicit lazy extension registration; no eager native SDK imports.
- `sim_server/`: the only shared SIM communication implementation; not a compatibility alias.
- `catalog/`: packaged benchmark declarations and their loader/validator.
- `cli.py`: shared catalog/diagnostic commands; participant entrypoints can use
  the service protocol directly.
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

The former regression runner, ownership checks and test fixtures are no longer
included in the active source tree; their matching versions remain in Git history.
`make check` validates current catalog data. This check is distinct
from native simulator, model or hardware validation; removing historical fixtures
does not establish that any new implementation has passed them.

The console entrypoint remains `starvla-eval`. Removed flat modules and the
`benchkit.runner` bridge have no compatibility shims. All live decision-loop
callers import `AgentPolicies.gpt6_astra.tools.runner` directly. Old records
remain data with their original bytes; live code does not read their source
bundles. This directory migration does not start evaluations or complete native
full presets.

For ordinary closed results use `benchkit.reports.basic_result`; it does not
require events, media or source snapshots. Optional `interaction_history` needs
sufficient event evidence. See [recording/results](../docs/recording.md). Neither
report makes Python Policy mandatory or attests native/provider execution.

The specialized `benchkit.reports.publication` turns one already-closed, complete named-model
panel into a compact public view. It checks the raw summary, status, manifest,
panel and episode counts, records hashes of those inputs, the profile ID,
effective configuration, preset/prompt digests and the client git revision,
dirty flag and diff digest (a 40-hex revision, boolean dirty flag and 64-hex
`preset_sha256`/`prompt_sha256` are required), exports the episode
videos (checked against, and taken from, the paired server record when one is
declared) under descriptive names that keep the camera, and writes only under the model's
`results/<benchmark>/` directory. It never moves raw evidence or changes a score.

```sh
python -B -m benchkit.reports.publication \
  --raw-run AgentPolicies/gpt6_astra/results/robodojo/raw/accepted-run \
  --results-root AgentPolicies/gpt6_astra/results/robodojo \
  --task-description classify_objects=category-sorting
```
