# Package layout migration

The current source uses these top-level packages:

| Previous source namespace | Current namespace | Responsibility |
| --- | --- | --- |
| `examples/` | `benchmarks/` | Benchmark protocols, native environments, servers and hardware references |
| `harness/` | `benchkit/` | Shared transport, case leasing, records, reports and record audits |
| `AgentPolicies/` | Unchanged | Agent methods, trusted decision loops and model-owned results |

Update imports, deployment scripts and module invocations for **new runs**:

```sh
python -m benchkit.sim_server.cli list
python -m benchmarks.simBenchmarks.RoboDojo.server --help
```

The installed commands `rsi-bench` and `starvla-eval` keep their names. Reinstall
the package after updating the checkout (`pip install -e .` for development).
There are no forwarding packages at the old import paths. Benchmark identifiers,
wire protocols, native action semantics, scoring and execution budgets do not
change. The `benchkit/campaigns/` fixed-plan scheduler, frozen packages,
per-benchmark `plan.py` files and the `anonymous_code_agent` mailbox and `opus`
profiles are removed without a replacement.

## Existing results and deployments

Do not rewrite closed results, pinned upstream inventories or historical source
directories to make old paths look current. They remain data describing the code
that actually ran; live code does not read their source bundles. Deploy a new
service snapshot for a new run.

New client runs record the git revision, dirty flag and a whole-checkout `diff`
digest in `manifest.runtime.git`, and the profile ID and effective configuration in
`manifest.policy.parameters`. They no longer contain `harness_source/` or
`model_source/`. The service still writes its own `harness_source/` deployment
snapshot with the `starvla-rsi.harness-source/*` schema; that name identifies an
evidence format, not a current Python import. Historical reports can still
mention `examples/`, `harness/` or `starVLA/`; these are not live compatibility
entrypoints. Native dependency inventories may also contain an upstream package's
own `examples/` directory, which must not be renamed.

For repository documentation relocation indexes, compose their recorded
`current_path` with the root mapping above when browsing today's source tree.
This does not rewrite the original index or reinterpret paths inside an old run.

Existing deployments may still contain ignored historical local files at old
paths. Prefer organizing retained evidence under the current results namespace
with byte-checked relocation and an explicit path/hash receipt, rather than
keeping old-root aliases. Source moves do not authorize deleting those records
or restarting evaluations.

## GPT validation client consolidation

`AgentPolicies/gpt6_astra/` now has one active client, `codex_native`
(`codex-native/v2`), consolidating persistent Direct control while retaining the
later optional completion and repeated-command behavior. Both options remain
disabled by default. `run.py` and `codex_native.py` live at the profile root. `configs/` holds the single
`codex_native_config.json`, `codex_native_prompt.txt`, `profile.json`
and `configuration.schema.json`; conversation, public-observation
and transport helpers live under `tools/`. The old `methods/`, `prompts/` and
`transports/` layers are removed; `configs/` no longer contains alternate method presets.
There is no old-module forwarding code or alternate active method selection.

`run.py` has no method selector; it always runs
`codex-native/v2`. This is distinct from the former bounded CLI Native v1 method.
Current setup is documented in [client README](../AgentPolicies/gpt6_astra/README.md).
Use its service driver for new runs.
Current usage is collected in the profile README; development notes are kept
locally. Old guides remain available from Git history.

Model profiles are self-describing `starvla-rsi.model-profile/v2` files at
`AgentPolicies/<id>/configs/profile.json`, naming the factory, config,
configuration schema and prompt. Client runs no longer capture model source.
Historical inventories, results and experiment snapshots remain data with their
original bytes and method names; live auditors do not read them. Old methods
remain recoverable from Git; a historical Direct result does not become a
Native v2 score. This cleanup does not change native benchmark protocols or
start a run.

## Why an old directory may still be visible

Git tracks files, not the existence of a directory. Moving tracked code does not
move ignored `__pycache__/`, local media or historical indexes. An `examples/` or
`harness/` directory on an existing deployment therefore does not establish that
the old Python entrypoint is supported. Inspect without deleting:

```sh
git ls-files -- examples harness
git status --short --ignored -- examples harness
git check-ignore -v -- /path/to/a/specific/local/file
```

Use current packages for new imports and launches. Move retained videos and
indexes only through an explicit evidence-preserving operation: verify the new
copy, retain a relocation receipt, and leave original closed-record contents
unchanged. Keep anonymous evidence anonymous; do not assign it to a named model
without attribution. Disposable caches are distinct from historical evidence
and need their own bounded cleanup. Do not recursively remove an old root just
because the tracked source has moved.
