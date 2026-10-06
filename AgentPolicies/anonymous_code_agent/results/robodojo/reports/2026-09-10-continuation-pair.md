# Hang mugs / sweep blocks — preparation and launch history

Both formal attempts are now closed. See the
[final results and video links](2026-09-11-continuation-results.md).

This is a separately authorized pair, one capability attempt per task, not a
retry of stack_bowls, push_T or pack_objects_into_box. The external code agent's
provider/model identity remains null; this is not a GPT6Astra score.

| Task | Canonical index | Native layouts | Selected layout/seed | Native horizon | Current state |
| --- | ---: | ---: | --- | ---: | --- |
| hang_mugs — mug hanging | 4 | 30 (0–29) | 0 / 0 | 800 | closed, native false, 52 action decisions |
| sweep_blocks — block sweeping | 5 | 55 (0–54) | 0 / 0 | 1000 | closed, native false, 50 action decisions |

The source-reviewed `continuation-pair-v1` scope uses the declared RGB-only
joint14 policy interface. Campaign seed20260907, D200, prefix5 and runner1000
are distinct from native horizons. Freeze the exact campaign before either
claim. Native success/scoring, reset state and controller are not changed.

The `minimum-action-decisions/v1` rule requires50 non-stop action decisions,
each with at least one executed control, before voluntary stop. The stop itself
is an additional call: earliest call51. Native terminal/success, errors, hard
limits and explicit safety stops with a nonempty note can end earlier. Invalid
early stops remain policy errors without retries. Record actual action decisions,
all policy calls, controls and first-native-success evidence, including nulls.

## Prepared evidence

- Source/refactor commit: `6c7f6b6738979620ee627c6441e2c0e68cc75c02`.
- [Native/task/asset preflight](../../../../../project_readmes/reviews/2026-09-10-dojo-new-pair-preflight.md)
  and [independent source review](../../../../../project_readmes/reviews/2026-09-10-dojo-continuation-code-review.md).
- [Dependency-equipped CPU gate](../../../../../project_readmes/reviews/2026-09-10-dojo-continuation-cpu-verification.md):
  483 checks passed, zero skips. This is not native execution.
- Additive asset preparation original handle14776 exited0. It copied only24
  preflight-bound files (108,982,291 bytes) to persistent staging and the existing
  runtime, retaining all8,514 baseline files. New full reference has8,538 files.
  Receipt: `/mnt/workspace/users/jinhuiye/Projects/starVLA-RSI/runs/dojo-continuation-pair-assets-20260910-001/validation.json`.
  Manifest at the same directory: `asset_reference_manifest.json`, SHA256
  `bcee49283722d1b80c0d95a51a44267e0fb9bbc1d76dd52ea0d0e2416e0879dd`.
  Original baseline manifest SHA256 remains
  `826004992bdde89e725f64b02be9dab7d6c1a6389a0d88d273aa063f57f38c84`.
  [Separate applied-byte verification](../../../../../project_readmes/reviews/2026-09-10-dojo-continuation-applied-assets.md)
  passed all8,538 runtime,8,441 reference and24 persistent-copy file checks;
  root read and accepted the bounded report. Native dependency closure
  and renderer acceptance are still unverified; no exceptions were broadened.

## Launch gate

### First infrastructure probes: launcher error retained

The first concurrent no-policy diagnostics used GPU1/hang_mugs and
GPU2/sweep_blocks in `raw/2026-09-10-hang-mugs-and-sweep-blocks/diagnostics/`,
with task-described case000/case001 names. Root omitted the previously accepted
process-only proxy from these two commands. Both reached `native_reset_started`,
then their owned worker PIDs625171/625173 had SYN-SENT connections to S3:443.
Neither reset returned; no policy decision, control, scorer result or video was
produced. Root sent TERM, then KILL only to these verified owned workers after
TERM did not close them. Original parent handles61954/70102 both exited1;
their retained results say passed=false, RPC EOF and worker returncode-9.
These are infrastructure/launcher failures, not model task failures. Nothing
was deleted or relabeled. Both processes selected the same timestamped global
Kit log, so that shared log cannot be attributed to one task independently.

The existing accepted process route remains unchanged:
`proxychains4 -q -f runs/dojo-proxy-cutover-20260907.tWloV1/proxychains.conf`.
Its config/binary/library SHA256 values still equal
`bb2d7ec28c12a960e2d2aca8aee59ad88c30fab4714e4d64fc91f2be79ff5948`,
`5aa40e2b6b4b6ccc0b83e3c7c633ccaa5da7590ae3893d3a906f96cbf2c256c8`,
`31d945cff6691393b54f464ae6ff3744cd395bab938c7f2b57201ddf57c1f0d7`.
SOCKS1080 was already listening; no network service or source/asset changed.
A bounded proxied HEAD to the NVIDIA material host returned200; it used the
unversioned Base URL and is connectivity evidence, not asset-byte acceptance.
New separately retained infrastructure probes use the original process route,
fresh case002/case003 output leaves, and slightly staggered launches to avoid
the observed same-second Kit log collision. They do not claim either capability
case; formal task attempts remain once-only and unstarted pending acceptance.

The user subsequently explicitly authorized concurrent use with existing jobs.
The no-uncontested-GPU scheduling hold below is superseded, not a requirement
for a fully idle node. Root rechecked shared resources: GPUs1/2 each had about
18GiB free and806GiB system RAM was available. Native diagnostic placement is
hang_mugs onGPU1 and sweep_blocks onGPU2, with multi-GPU rendering disabled.
Do not stop or mutate unrelated jobs. Capacity changes/errors remain visible;
this approval does not relax observation, asset, scorer, once-only or stop rules.

All four evaluation nodes currently have unrelated active GPU workloads. The
ready Dojo runtime is on eval. Prior logs bind rendering/physics to GPU5, so
whole-node exclusivity is not a proven requirement; however shared-GPU fit and
peak VRAM for these scenes are unmeasured. No unrelated process has been stopped
or modified. GPU allocation was requested from the user before native launch.

After suitable capacity and applied-byte acceptance: one separately recorded
no-policy reset/render/hold diagnostic per task, independent diagnostic review,
then the frozen model-profile campaign with one fresh opaque policy actor per
case. Keep new raw output under `raw/` in this benchmark result
directory and task-described videos under ignored `media/` directories.
Native diagnostics and the original frozen v2 campaign exist. Both original
opaque actors ACKed, then were interrupted while parked with zero observations
and responses. Neither capability case has been claimed. A new source freeze
will use fresh actors and endpoints; no capability result exists yet.
Other benchmark pauses and the fold-clothes missing-texture hold remain unchanged.

The [campaign/offline source review](../../../../../project_readmes/reviews/2026-09-10-dojo-continuation-campaign-review.md)
is accepted. Campaign SHA256 is
`1095077ec51379f9bd38edb7db4df50b6006877573f6b35b4304fe7be2c99f03`;
the new48-source offline manifest SHA256 is
`8df8bd445e00694b79f8f778ba90c223cdc40c985b3d78ada1a3d8585486ebf2`.
Root separately rehashed all48 files against deployed source and Git689d624,
checked the exact bundle inventory, and reproduced the frozen/model/pair/budget
guards without native imports or claims (original verification98150 exit0).
This is acceptance of the original source/contract, not native acceptance.

### September11: closed probes and prospective cache checkpoint

Both proxied probes exited0 with clean child shutdown, one diagnostic hold,
852 physics ticks (842 reset plus10 hold), and zero model calls. The
[closed diagnostic review](../../../../../project_readmes/reviews/2026-09-10-dojo-continuation-diagnostics-review.md)
accepts sweep's bounded readiness but rejects hang's rendering: two downloaded
PNG payloads have bad checksums and104 texture-upload errors persist. Raw
`passed:true` is retained, not promoted to full readiness or a model score.

The [optional checkpoint design](../../../../../project_readmes/reviews/2026-09-11-dojo-http-cache-checkpoint-design.md)
and [code review](../../../../../project_readmes/reviews/2026-09-11-dojo-http-cache-review.md)
copy only ten exact original HTTP-cache files into each new isolated episode.
No asset URL, native worker, observation/action interface, scorer or task limit
changes. The [dependency-equipped CPU checks](../../../../../project_readmes/reviews/2026-09-11-dojo-http-cache-cpu-verification.md)
passed360 checks with zero skips. Native acceptance is recorded below.

New raw root: `../raw/2026-09-11-hang-mugs-and-sweep-blocks-cache-checkpoint/`.
Its `http-cache-seed.json` is2712 bytes, SHA256
`aff34e2d5ef9ebb8ee331a8a63449e7d5a3c488ba2b7233ac4e92f35eb27e1fb`.
The selected closed pack006 source revalidated ten files/15,892,544 bytes and
all six PNGs decoded. This is checkpoint-byte verification, not proof of
renderer consumption. Preserve the original campaign/bundle and every failed
probe unchanged; prepare a new matching cache-enabled campaign before claims.

### Accepted diagnostics and once-only formal launch

Both cached diagnostics004/005 closed successfully (original handles56901 and
52860, exit0). Root read and accepted the
[independent closed diagnostic review](../../../../../project_readmes/reviews/2026-09-11-dojo-cache-checkpoint-diagnostics-review.md):
each has one hold, zero model calls, unchanged ten-file caches, six decodable
RGB PNGs, three two-frame videos and clean child exit. The former104 texture
upload errors do not recur. Root separately inspected both head-camera images.
These are infrastructure checks, not task scores or extra capability attempts.

The [new preparation](../../../../../project_readmes/reviews/2026-09-11-dojo-cache-checkpoint-preparation.md)
and [independent freeze review](../../../../../project_readmes/reviews/2026-09-11-dojo-cache-freeze-review.md)
are accepted. Source commit is `9ae943df4b330459c94cf7d1f4aeb6018d42901c`;
new campaign SHA256
`fda8e134493ed979f1f48ed5822c0d9381a3ec91dbad3bf62e394c2f847efe9e`,
49-source postprocessor manifest SHA256
`3fdcb0593638c61a73d314bf26269ed2e857458498395441fd76363d2610238e`.
All94 campaign files and49 postprocessor sources matched the verified freeze.

Root then claimed case-000/hang on GPU6 (original handle95528) and
case-001/sweep on GPU7 (49973), using the same accepted process-only proxy and
EULA setting. Each new actor received exactly the canonical instruction template
with only host/opaque endpoint substitution, ACKed before launch and received
only the generic launch notice. No source, diagnostic observation, score or
task-specific hint was supplied. Fresh capacity checks showed about18GiB free
on each chosen GPU; unrelated jobs remain untouched. Both attempts subsequently
closed once:53/51 calls,52/50 action decisions and256/246 controls respectively,
native false and score0/100. Both ordinary give-ups met the floor; neither hit
a cap, errored or timed out. No retry was launched. The linked final report
separates model outcome, record acceptance and shared native-log limitations.
