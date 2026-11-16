# Optional interaction recording and results

Interaction history is useful, but it is not a requirement for participating or
publishing a result. The default retains supported interactions and **native videos
on the server**, without downloading duplicate media to the client. Native capture
is adapter-specific; the shared service does not create a missing camera video.
Standalone frame images are normally temporary, with the fallback exceptions below.
These settings never change the actor's
observations, robot actions, native horizon or score.

## Reference driver settings

Add these options to the selected agentic policy's driver command, for example
`python -m AgentPolicies.gpt6_astra.run ...`:

```sh
--recording-mode standard
# Explicitly download another copy of retained server media:
--recording-mode standard --copy-server-media
# Or essential results, without optional client interaction/media retention:
--recording-mode minimal
# Independent overrides, for example:
--recording-mode standard --no-record-videos --no-record-images
```

| Setting | Retains when supported | Standard / minimal |
| --- | --- | --- |
| `--[no-]record-interactions` | Observation/transition metadata in trajectory events | on / off |
| `--[no-]record-model-io` | Visible model input/output, notes and method records | on / off |
| `--[no-]record-tool-traces` | Allowlisted visible tool events | on / off |
| `--[no-]record-images` | Retained client image artifacts / requested server image copies | off / off |
| `--[no-]record-videos` | Select video downloads when media copying is enabled | on / off |
| `--[no-]copy-server-media` | Download selected media instead of keeping server references | off / off |

Explicit switches override the preset. Resolve them before the run; do not
change them mid-episode. The Python SDK uses `RecordingOptions` and
`RunRequest(recording=...)`. No additional model call is made for recording.
The essential closed-file inventory still identifies server media when client
video copying is disabled; `--no-record-videos` does not delete server videos.

## The trajectory ledger is always written

Every reference-driver mode writes `episodes/<id>/events.jsonl` for the closed-run
audit and event-based reports. Basic result export does not require it. The
ledger holds `episode_start`,
the reset `observation`, `policy_call_start`, `policy_decision` (with usage, stop
and chunk length), `action_chunk` (proposed actions), `environment_step`
(executed action, reward, terminal flags and the public observation),
`action_rejected`, `error`/`artifact_error`, `usage_reconciliation` (when the
policy reports an episode total) and `episode_end`. The switches only strip
payloads:

- without `interactions`, observation `metadata` is dropped and transition
  `info` becomes `{}`; step, instruction, camera names, robot state and the
  public control acknowledgement remain;
- without `model_io`, the decision `note` becomes `""` and decision, rejection
  and error `metadata` is dropped.

Any other event kind is written unchanged.

## One canonical visual record

For new service runs, videos stay under `server/episodes/<session>/`. The client
retains the server identity, session, relative media paths and integrity metadata
in its artifact receipt; a reference is not a downloaded or independently
verified local copy. Keep the server result directory on durable storage. Reports
and exports must not assume a video exists in `client/.../sim_server_files/`.
`benchkit.reports.export_videos` copies local videos and otherwise lists these
server references with `video_status: retained_on_server`. Each episode gets a
`<date>-<task>-<short-instruction>-caseNNN/` directory; `index.json` maps it to
the original episode record. Receipts are parsed before the archive is created.

Native adapters may need PNG files during execution. They remain available until
native finalization and close. The shared service then drops eligible temporary
frame images before publishing its final inventory, and records omitted paths
and hashes in `server_media_retention.json`. Videos, scores, logs and provenance
are not deleted. Frame pruning requires successful native finalization/close,
nonempty videos numbering at least the declared cameras, and stable file hashes.
Missing or zero-byte videos, insufficient camera count, or failed cleanup keep
frames with a recorded reason. A pruning error preserves remaining frames and
records the warning and any completed removals. These file/count checks do not
prove video decoding, camera correspondence or complete frame coverage; inspect
native readiness separately. This is close-time retention, not a promise of zero
temporary image I/O.

To retain frame images explicitly, start the service with `--retain-frame-images`.
If local image copies are also wanted, use client `--record-images
--copy-server-media`. `--copy-server-media` intentionally creates an additional
copy; it does not remove the server original. Model-side public-image history is
also optional to retain; live images remain available to the actor regardless.

Historical runs, existing server inventories and historical media are not
rewritten or cleaned retroactively. The client requires the server's
`server_media_retention.json` receipt in every finalized inventory.

Essential records remain: method/configuration, benchmark/protocol and selected
cases, lifecycle, outcomes, termination/errors, counters and known usage. The
reference runner records the client Git revision, dirty flag and diff digest in
the manifest. The supplied profiles add their profile ID, effective configuration
and preset/prompt digests. Service source snapshots are captured separately by
the benchmark service; client recording presets do not control them. `minimal`
is not a promise of only four files or zero storage. Source snapshots are not
required by the basic result exporter.

## What the switches do not promise

- **Client retention is not native capture.** Servers may generate temporary
  images and videos while running. The client always finalizes once and retains
  the close receipt; its flags do not alter server capture. Service-side frame
  retention is selected separately at launch. New clients reference server media
  by default and download it only on explicit opt-in.
- **Retention is not the live input channel.** RGB and state still reach the
  actor. Direct's public image/history workspace remains available for the whole
  episode, even in minimal mode, and its owned scratch is removed after closure.
  Suppressing files before closure would change the method.
- **Support varies by method.** The optional recorder SDK is not a mandatory
  model proxy. Direct records visible turn inputs, action submissions/tool replies
  and allowlisted completed tool/message events. It excludes reasoning events,
  arbitrary provider envelopes and file diffs; it does not reconstruct a complete
  provider transcript. Other profiles do not automatically gain raw IO capture.
- **Mixed files are conservative.** Native metrics and provenance must not
  disappear merely because images are disabled. Unknown non-media evidence is
  retained conservatively; recognized interaction streams still respect their
  switches. Direct's mixed public JSON export requires interactions and model IO;
  the trajectory ledger itself is always written. Disabling images leaves
  references to unavailable images, not invented retained pixels. Components
  without selective-recording support may retain mixed artifacts and report that
  limitation rather than silently dropping their non-media evidence.
- **The optional recorder is best effort.** Its I/O/serialization failures produce
  fixed warnings rather than changing robot control. This does not relax existing
  core result persistence, private transport diagnostics, artifact integrity or
  service lifecycle checks; failures there remain infrastructure errors.
- **This is not automatic secret removal.** Essential private error diagnostics
  can contain participant text. Visible prompts/tool output can also be sensitive.
  Keep raw records private and review before sharing. Do not submit credentials,
  hidden reasoning or evaluator-private data to the interaction recorder.

## Basic result without event logs

Use the [basic result exporter](result-format.md#export) to produce a standalone
`index.html` and `result.json` from essential closed records. It does not require
events, media or source snapshots. An external driver can write the
[JSON record contract](result-format.md) without importing or subclassing the
reference runner.

The exporter preserves attempted failures/errors and the unattempted selected
suffix. Its denominator is the client-selected schedule; record consistency
does not establish native execution, provider identity or full suite coverage.
See the [evaluation workflow](evaluation.md#inspect-and-report) for reporting
commands and the result contract for required fields and export checks.

The `python -m benchkit.reports.interaction_history` exporter provides a
trajectory timeline from the ledger in every mode; without model IO it shows
decisions without notes or structured output. It currently does not merge
`agent_interactions.jsonl` or copy media. The result publication
(`benchkit.reports.publication`) is described in the
[reports README](../benchkit/reports/README.md).
