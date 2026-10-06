# SIMPLE: GPT6Astra profile samples

The selected TabletopGraspMP case completed with native success after **5 policy
calls, 5 executed action decisions and 21 controls**, with zero rejected actions
and no recorded interface/infrastructure error. This is one fixed sample, not a
SIMPLE benchmark-wide success rate or native-full evaluation.

The requested CLI model was `gpt-6-astra`, using the `codex-native/v1` method and
`codex-exec/v1` transport. That requested identity is not independent backend
model/provider attestation. CLI-reported tokens are retained in the report;
provider-internal request counts, retries and cost remain unknown.

## Conditions and outcome

| Field | Recorded value |
| --- | --- |
| Task | `G1WholebodyTabletopGraspMP-v0` |
| Reset | Released DR0 episode 0, seed `20260907` |
| Protocol | `simple/released-12/amo/rgb-qpos31/decision-200-prefix-5/v1` |
| Model observation | Head-left RGB, 640×360, plus 31 measured robot joint encoders |
| Model action | 36 physical joint/navigation targets, native fixed AMO controller |
| Budget | 200 policy calls; up to 5 controls per decision; 1000-control cap |
| Native reference horizon | 800 controls; this decision-budget track differs from native timing |
| Initialization | 60 standing controls, recorded separately from policy controls |
| Attempt count | One; no automatic retry |
| Outcome | Native success, `environment:terminated` |
| First success | Call 5, control 21; previous 20 native flags were false |
| Native reward at first success | `0.9080922860569909` |

Success comes from the pinned task's height-only predicate:
`clip((target_height - baseline_height) / 0.02, 0, 1) >= 0.9`, nominally a 1.8 cm
height gain. It does not require secure contact or a sustained grasp. The baseline
is established during native warmup; retained records do not attribute all height
change exclusively to policy. No extra scorer queries were used. Native logs
retain inherited startup/rendering warnings; this result does not certify a
warning-free installation or complete asset parity.

## Reports and videos

- [Sample result and evidence hashes](reports/2026-09-20-G1WholebodyTabletopGraspMP-v0-tabletop-grasp-bench-server-native-v1-sample/result.json)
- [Episode outcome](reports/2026-09-20-G1WholebodyTabletopGraspMP-v0-tabletop-grasp-bench-server-native-v1-sample/episodes.json)
- [Sanitized record-audit summary](reports/2026-09-20-G1WholebodyTabletopGraspMP-v0-tabletop-grasp-bench-server-native-v1-sample/record-audit.json)
- [Video inventory and hashes](reports/2026-09-20-G1WholebodyTabletopGraspMP-v0-tabletop-grasp-bench-server-native-v1-sample/media.json)
- Videos: [head left](media/2026-09-20-G1WholebodyTabletopGraspMP-v0-tabletop-grasp-bench-server-native-v1-sample/head_stereo_left.mp4), [head right](media/2026-09-20-G1WholebodyTabletopGraspMP-v0-tabletop-grasp-bench-server-native-v1-sample/head_stereo_right.mp4), [front left](media/2026-09-20-G1WholebodyTabletopGraspMP-v0-tabletop-grasp-bench-server-native-v1-sample/front_stereo_left.mp4), [front right](media/2026-09-20-G1WholebodyTabletopGraspMP-v0-tabletop-grasp-bench-server-native-v1-sample/front_stereo_right.mp4).

All four videos decode to 22 frames at 640×360 and 50 Hz with increasing
timestamps. Server originals, downloaded client files, exported client files
and presentation copies have matching hashes. Only head-left images were
delivered to the policy; the other views are evaluator evidence. Decoding and
hash checks do not replace the native success predicate.

The closed-record audit verified 131 runtime-source files, 29 model-source files
and the recorded call/control counts. This establishes record consistency, not
execution, OS isolation, model identity or complete native parity attestation.

`reports/` and [index.json](index.json) are portable public summaries; `media/`
contains Git-ignored byte-checked presentation copies. Raw evidence is retained
unchanged. Each evidence `paths` array names alternative local or exported-client
locations relative to this result directory, with one common byte count and
SHA-256. Those raw files can contain private deployment provenance and are not
included in the public JSON. Release media separately using the inventory.

See the [benchmark protocol](../../../../examples/simBenchmarks/SIMPLE/EVALUATION_PROTOCOL.md)
and [result layout](../README.md).
