# GR1 Tabletop environment setup

This directory supplies environment requirements, source manifests and evaluator-owned diagnostics. It does not implement a model policy or publish capability results. Read the [benchmark protocol](../EVALUATION_PROTOCOL.md) before running a task.

## Required sources and runtime

Use a dedicated Python 3.10 environment; the pinned runtime was materialized with Python 3.10.21. Set `PYTHONHASHSEED=0` before every evaluator Python process starts.

| Dependency | Source identity |
| --- | --- |
| [RoboCasa GR1 Tabletop](https://github.com/robocasa/robocasa-gr1-tabletop-tasks) | `4840e671596f93ca03651524b9f72ffb1aadfeff` |
| Robosuite | `51cc01785bab80ffeed20da15e67d7dd4140e76a` |

[runtime-requirements.txt](runtime-requirements.txt) is the environment-only dependency set, including MuJoCo 3.2.6 and NumPy 1.26.4; [runtime-lock.txt](runtime-lock.txt) records the materialized runtime. From the RSI repository root:

```sh
python -m pip install -r benchmarks/simBenchmarks/Robocasa_tabletop/environment/runtime-requirements.txt
python -m pip install --no-deps -e .
```

These commands do **not** acquire the native repositories or assets. Provision the pinned sources first and preserve their verified non-asset code bytes and actual import paths. Robosuite also supports the exact archive described by [robosuite-source-manifest.json](robosuite-source-manifest.json); an arbitrary unversioned source tree is not equivalent.

## Assets and portability limits

Provision the native fixture/texture/scene assets and the `objaverse`, `sketchfab` and `lightwheel` object libraries under their licenses. The adapter's [contract](../bench_server/protocol/robocasa_tabletop_contract.json) requires the matching object inventory: 42,994 regular files totaling 6,843,155,836 bytes in the provisioned snapshot.

That inventory describes a reproducible snapshot, not certification of the complete official asset release. The native constructor may warn about an absent category such as `sketchfab/book` and skip a distractor configuration. Retain the warning; do not add/remove categories to conceal it. Every referenced asset in the executed scene must still pass content/dependency checks.

There is not yet a portable all-assets bootstrap/manifest-generation workflow for arbitrary installations. Merely downloading a newer upstream release or copying a subset of objects is insufficient. Adapter defaults also retain site-specific source/inventory locations; relocated deployments must pass `casa_source`, `suite_source` and `object_inventory` explicitly. The supplied inventory and asset root must satisfy the exact pinned contract.

At reset the adapter checks the object inventory's full names/sizes and hashes the used-scene object content against the inventory. It does not rehash every unused object on every reset. Keep this distinction when reporting asset evidence.

## Native environment diagnostic

Select an idle GPU and a new output directory. This parameterized tool accepts relocated source/inventory paths:

```sh
PYTHONHASHSEED=0 python \
  benchmarks/simBenchmarks/Robocasa_tabletop/environment/verify_environment.py \
  --casa-source /path/to/robocasa-gr1 \
  --suite-source /path/to/robosuite-gr1 \
  --object-inventory /path/to/object-inventory.json \
  --gpu 0 --seed 20260907 \
  --output-dir /path/to/new-tabletop-diagnostic
```

It verifies sources/assets, constructs the selected native environment, resets, renders and executes an evaluator-owned measured hold. Its policy-call count is zero. Retain the diagnostic status/errors, compiled control and encoder contract, initial-state hash, delivered images and completely decodable video. A native reset or hold is not a capability attempt or a task success claim.

[verify_adapter.py](verify_adapter.py) separately checks the RSI adapter's reset/render/hold path for supported task indices 0, 1, 2 and 19. Its current CLI uses site-specific adapter source/inventory defaults; unlike the command above it does not expose relocation flags. Use it only with a compatible configured layout, or invoke the adapter with explicit paths in evaluator-owned diagnostic setup.

## Evaluation gate

Before model evaluation, require source/asset identity, compiled joint/actuator parity, ordinary encoder identity, observation allowlisting, per-control native scoring and complete video decoding. Record rather than hide environment errors and native warnings. Diagnostics and CPU checks do not establish native-full schedule parity or all-task readiness.

Model execution must go through the [shared runner and benchmark adapter](../README.md), never diagnostic native-state access. Policy prompts, persistence preferences and capability results belong under [AgentPolicies](../../../../AgentPolicies/README.md).
