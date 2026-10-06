# Anonymous code-agent results

Latest: [three selected SIM-server development cases](2026-09-15-sim-server-validation.md),
including counts, native outcomes, evidence qualifications and video indices.

These are historical external code-agent development attempts. The original
records do not establish a verifiable provider/model snapshot, so `model` and
`provider` remain `null`. Moving the records here does not attribute them to
GPT6Astra, Opus, or any other named model, or certify provider-call limits.

The benchmark-owned task catalog and native protocol remain under `examples/`.
Model result reports, task execution checklists, coverage checkpoints and rollout
indexes are maintained here:

The [September10 migration checkpoint](2026-09-10-migration.md) records the
completed organization of38 historical documents,98 closed run indices and204
exact-byte video copies across the six benchmarks below. Follow each benchmark
entrypoint for a human-readable task table and camera-labelled video links.

| Benchmark | Result entrypoint |
| --- | --- |
| LIBERO | [Reports, task checklist and rollouts](libero/README.md) |
| SimplerEnv | [Reports, coverage and rollouts](simpler_env/README.md) |
| SIMPLE | [Reports, task checklist and rollouts](simple_humanoid/README.md) |
| RoboCasa365 | [Reports, task checklist and rollouts](robocasa365/README.md) |
| RoboCasa Tabletop | [Reports, selected-task ledger and rollouts](robocasa_tabletop/README.md) |
| RoboDojo | [Round records and rollouts](robodojo/README.md) |

The [document relocation inventory](document_relocation.json) records each old
path, its original SHA256, its new path and migrated SHA256. Original Markdown
entrypoints are compatibility links. Hash-bound evidence-caveat JSONs are copied
byte-for-byte; their old paths remain compatibility copies for historical tools.
Documentation links were rebased; numerical outcomes, failures and limitations
were preserved. Historical console snippets retain their original context.

Original frozen campaigns under `runs/`, manifests, results, videos, source
snapshots and absolute artifact references have not been moved or rewritten.
Existing export names documented in rollout indexes still resolve against their
original benchmark rollout directories. The new
`<benchmark>/adoptions/2026-09-10-historical/` directories contain the adopted
indices, task tables and ignored media copies; they do not replace the originals.

## Add an explicit closed-run index

Use the dependency-free `harness.result_index` tool after reviewing
the exact source list. It reads terminal `completed`/`completed_with_errors`
runs and rejects active runs, named provider/model records, duplicate selections,
output overlap and existing output directories. The index retains original
policy/protocol identity, all errors, native final success, decisions, controls,
first-success evidence and hashes of the files actually read. It does not launch
evaluation or infer scores from video. Missing first-success evidence stays null.

Create an explicit JSON array, for example:

```json
[
  {
    "run_dir": "/absolute/original/campaign/case-000/run",
    "videos": [
      {
        "episode_id": "the-original-episode-id",
        "artifact": "video_cam_head",
        "camera": "cam_head",
        "description": "bowl-stacking"
      }
    ]
  }
]
```

Omit `videos` for an index without media. Video keys must reference MP4 artifacts
already recorded in the selected episode. Each selected file is copied once and
verified against its original SHA256. Output names include the date, canonical
task identity, an English task description, run/episode identity and camera.
Zero-control, no-policy and errored media are separated under `media/archive/`.
No directory-wide source, asset, image or wire copy is performed.

```sh
PYTHONDONTWRITEBYTECODE=1 python -m harness.result_index \
  --sources /absolute/reviewed-source-list.json \
  --output-dir starVLA/anonymous_code_agent/results/libero/adoptions/new-checkpoint
```

Each invocation requires a new destination. `index.json` is published only after
the selected copies and source stability checks pass. A partial failed output has
no published index and is never reused automatically. This index is a bounded
record of its explicit source list, not full coverage or a homogeneous aggregate
score. Retain the benchmark task checklist and original campaign scope to
interpret unattempted entries, pilot carry-forwards and distinct protocols.

Track the lightweight index, reports, checklists and reference JSON. Generated
`media/`, `raw/`, `campaigns/` and rollout subdirectories remain ignored by Git.
