# Shared communication and evaluation tools

`benchkit/` provides shared SIM communication, central case scheduling, data/result
formats, recording, source snapshots, audits and reports. Its libraries and
commands are not a mandatory per-action control process. Agent-side decision loops live under `AgentPolicies/policy_support/`;
[`sim_server/`](sim_server/README.md) implements transport, serialization and session
lifecycle used by benchmark-owned servers and trusted drivers. Native tasks/scorers and model
decisions do not belong here.

- `contracts.py` / `interfaces.py`: public observation, action and lifecycle types.
- `methods.py`: protocol-first method composition and per-component usage declarations.
- `recording.py`: default-on optional interaction/client retention preferences and SDK sink.
- `registry.py`: explicit lazy extension registration; no eager native SDK imports.
- `sim_server/`: the only shared SIM communication implementation; not a compatibility alias.
- `campaigns/`: retained central task coordination: fixed-plan preparation,
  permanent case claims, explicit launches and progress. It currently executes
  frozen local adapters, not remote service campaigns; it is not an agent
  decision loop, automatic retry engine or distributed resource scheduler.
- `catalog/`: packaged benchmark declarations and their loader/validator.
- `cli.py`: shared catalog/diagnostic commands; participant entrypoints can use
  the service protocol directly.
- `model_profiles.py`: configuration/factory validation and bounded model-source capture;
  actual factories remain under `AgentPolicies/<profile>/`.
- `source_snapshot.py`: bounded output-tool, benchmark-service and explicitly
  declared trusted-driver source capture. An inventory's storage path does not
  change the ownership of the captured code.
- `diagnostics/`: shared synthetic and fixed-action infrastructure fixtures, captured with the
  harness source; these are not participant models or task-solving baselines.
- `audits/`: offline record validation, not native replay or provider attestation.
- `reports/`: shared run summaries, campaign coverage, historical result indices,
  fixed-plan SR comparison and named-model
  publication. The panel report
  preserves policy failures, infrastructure errors and missing closed results;
  it does not select or retry cases or infer that missing evidence means no attempt.
- `checks/` / `artifact_checks/`: lightweight regression and ownership checks.

Native adapters and selection plans live under
[`benchmarks/simBenchmarks`](../benchmarks/simBenchmarks/README.md). Policies, shared
policy support and results live under [`AgentPolicies`](../AgentPolicies/README.md).

```sh
python -m benchkit catalog --check
python -m benchkit list
python -m benchkit.campaigns --help
python -m benchkit.checks.check_boundaries
```

From a repository checkout, run the CPU-only regression groups with a Python
environment that already provides NumPy, Pillow and PyAV:

```sh
python -B -m benchkit.checks.run_regressions --jobs 3 --output /absolute/new/cpu-check-report
```

This retains per-group logs and a JSON summary without starting a native
simulator, a model or a hardware session. Keep the source tree unchanged while
the checks run: source-freezing fixtures intentionally reject concurrent edits.
Checks are not packaged in the distribution wheel. `make check` parses active
source and checks ownership/catalog layout without traversing frozen results.

The console entrypoint remains `starvla-eval`. Campaign commands use
`python -m benchkit.campaigns`; history adoption uses
`python -m benchkit.reports.result_index`. Removed flat modules and the
`benchkit.runner` bridge have no compatibility shims. All live decision-loop
callers import `AgentPolicies.policy_support.runner` directly. Old frozen
campaigns retain their original package names, bytes and verification rules;
never rewrite a frozen package just to update an import path. This directory
migration does not start evaluations or complete native full presets.

Closed coverage reports bind the run's declared policy identity, model profile,
prompt and stop settings to its campaign; mismatches remain invalid evidence in
the denominator. This checks record consistency, not provider attestation.
The participant-coverage reporter rejects declared infrastructure-diagnostic
campaigns; their raw native outcomes remain available through diagnostic indices.
`reports/result_index.py` is specifically for adopting closed anonymous historical runs,
not a general named-model importer. It rejects explicit non-anonymous profiles
even when their provider/model fields are null, and marks fixed-action
infrastructure diagnostics separately with archived media. Original native
outcomes and source records are never rewritten by either reporting tool.

For ordinary closed results use `benchkit.reports.basic_result`; it does not
require events, media or source snapshots. Optional `interaction_history` needs
sufficient event evidence. See [recording/results](../docs/recording.md). Neither
report makes Python Policy mandatory or attests native/provider execution.

The specialized `benchkit.reports.publication` turns one already-closed, complete named-model
panel into a compact public view. It checks the raw summary, status, manifest,
panel and episode counts, records hashes of those inputs, exports selected media
with descriptive names, and writes only under the model's
`results/<benchmark>/` directory. It never moves raw evidence or changes a score.

```sh
python -B -m benchkit.reports.publication \
  --raw-run AgentPolicies/gpt6_astra/results/robodojo/raw/accepted-run \
  --results-root AgentPolicies/gpt6_astra/results/robodojo \
  --task-description classify_objects=category-sorting
```
