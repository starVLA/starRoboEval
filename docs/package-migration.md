# Package layout migration

The current source uses these top-level packages:

| Previous source namespace | Current namespace | Responsibility |
| --- | --- | --- |
| `examples/` | `benchmarks/` | Benchmark protocols, native environments, servers and hardware references |
| `harness/` | `benchkit/` | Shared transport, case scheduling, records, reports and internal audits |
| `AgentPolicies/` | Unchanged | Agent methods, trusted decision loops and model-owned results |

Update imports, deployment scripts and module invocations for **new runs**:

```sh
python -m benchkit.sim_server.cli list
python -m benchmarks.simBenchmarks.RoboDojo.server --help
python -m benchkit.campaigns --help
```

The installed commands `rsi-bench` and `starvla-eval` keep their names. Reinstall
the package after updating the checkout (`pip install -e .` for development).
There are no forwarding packages at the old import paths. Benchmark identifiers,
wire protocols, native action semantics, scoring and execution budgets do not
change. Central fixed-plan scheduling remains available in `benchkit/campaigns/`.

## Existing results and frozen deployments

Do not rewrite closed results, pinned upstream inventories or frozen source
directories to make old paths look current. Their paths, hashes and configuration
describe the code that actually ran. Existing deployments continue to use their
own frozen packages; deploy a new snapshot for a new run.

New `campaign/v3` manifests declare `runtime_namespace: benchkit`, checked
against their captured source inventory. Unmarked historical v3 campaigns keep
their `harness` runtime; v1/v2 keep `starVLA.evaluation`. This selects each
campaign's own frozen implementation, not a forwarding module in today's tree.

Persisted `harness_source` record keys/directories and the
`starvla-rsi.harness-source/*` schema identifiers remain unchanged. They identify
an evidence format, not a current Python import. Historical reports can still
mention `examples/`, `harness/` or `starVLA/`; these are not live compatibility
entrypoints. Native dependency inventories may also contain an upstream package's
own `examples/` directory, which must not be renamed.

For repository documentation relocation indexes, compose their recorded
`current_path` with the root mapping above when browsing today's source tree.
This does not rewrite the original index or reinterpret paths inside a frozen run.

Existing deployments may still contain ignored historical local files at old
paths. Prefer organizing retained evidence under the current results namespace
with byte-checked relocation and an explicit path/hash receipt, rather than
keeping old-root aliases. Source moves do not authorize deleting those records
or restarting evaluations.

## GPT validation client consolidation

`AgentPolicies/gpt6_astra/` now has one active client, `codex_native`
(`codex-native/v2`), preserving the former Direct v3 prompt, configuration values
and execution behavior. `run.py` and `codex_native.py` live at the profile root. `configs/` holds the single
`codex_native_config.json`, `codex_native_prompt.txt`, `profile.json`,
`configuration.schema.json` and `dependencies.json`; conversation, public-observation
and transport helpers live under `tools/`. The old `methods/`, `prompts/` and
`transports/` layers are removed; `configs/` no longer contains alternate method presets.
There is no old-module forwarding code or alternate active method selection.

New commands can omit `--control-method`; the only accepted explicit value is
`codex-native/v2`. This is distinct from the former bounded CLI Native v1 method.
Current setup is documented in [client README](../AgentPolicies/gpt6_astra/README.md).
Use its service driver for new runs. The retained local `campaigns prepare` path
rejects `codex-native/v2` before creating outputs because it does not satisfy the
method's horizon/feedback contract; frozen historical campaigns stay unchanged.
Current usage is collected in the profile README; development notes are kept
locally. Old guides remain available from Git history or their frozen source
packages.

New model-source captures use `starvla-rsi.model-source/v7`. Historical v1–v6
inventories, results and experiment snapshots retain their original bytes,
method names and validation rules. Old methods remain recoverable from Git and
frozen run packages; a historical Direct result does not become a Native v2
score. This cleanup does not change native benchmark protocols or start a run.

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
