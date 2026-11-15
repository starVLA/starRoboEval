# Reports

These tools read closed runs and never change a score or move raw evidence.
None of them makes a Python `Policy` mandatory or attests native or provider
execution.

- `basic_result.py`: the ordinary closed-result view; it needs no events, media
  or source snapshots.
- `interaction_history.py`: a trajectory timeline from the ledger that every
  recording mode writes.
- `run_summary.py`: outcome summaries of recorded runs.
- `episode_viewer.py`: a read-only local review page for selected closed episodes.
- `export_videos.py`: copies videos out of a closed run and keeps the originals.
- `panel_sr.py`: panel SR comparison. It keeps policy failures, infrastructure
  errors and missing closed results apart. It does not select or retry cases,
  and it does not read missing evidence as no attempt.
- `publication.py`: the named-model publication described below.
- `viewer_assets/`: static page assets for the episode viewer.

See [recording and results](../../docs/recording.md) for the record layout.

## Publication

`benchkit.reports.publication` turns closed named-model results
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
dirty flag; the rest of the policy parameters are published only as a digest.
The cases of a remote run must share benchmark, policy, method, protocol and
client source. A paired server record binds outcomes and videos; a remote run,
or a single run without its `server/` pair, is bound to the client-held SIM
receipts only, and server-only videos are listed as hash references. Only a
complete panel without infrastructure errors is accepted. Usage totals are
published with `usage_incomplete_episodes`, and each episode keeps
`usage_reported_complete` and `usage_inconsistent_fields`, so totals are not
read as final while a policy's own usage report was incomplete or inconsistent.
`--reference SUCCESSES/EPISODES` adds an operator-declared comparison.
All checks run before any file is written. Re-publishing identical content is a no-op. A publication that
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
