# RoboDojo: hang mugs / sweep blocks, one attempt each

Both formal attempts completed normally but did not solve their native tasks:
0/2 successes in this selected development pair. No retry, reset-based success
selection or other benchmark resumption was performed. These are anonymous
code-agent results, not verified GPT6Astra/Opus model scores.

| Task | Native success / score | Action decisions | Policy calls | Controls | Stop |
| --- | --- | ---: | ---: | ---: | --- |
| hang_mugs — mug hanging | false / 0/100 | 52 | 53 | 256 | policy:give_up |
| sweep_blocks — block sweeping | false / 0/100 | 50 | 51 | 246 | policy:give_up |

Both met the minimum 50 executed non-stop action decisions before voluntary
give-up. The last call is a stop-only response and executes no control. One
decision can provide up to five independently specified control targets;
decision counts and control steps therefore differ. Neither task reached D200,
runner cap 1000 or native H800/H1000. Both have `error:null`, no timeout, original
coordinator exit 0 and native child exit 0 without TERM/KILL. First native success
step and corresponding decision remain null, not estimated from video.

Wall-clock episode duration was 2987.127s (49.79min) for hang and 2386.477s
(39.77min) for sweep. Controlled simulation time was 10.24s and 9.84s respectively:
25 targets/s, ten physics ticks per target. Each additionally had 842 reset ticks.
One native reward evaluation occurred per control, with no extra scorer calls.
Hang's native process score is 0.0; sweep's is null, not an invented partial score.

## Videos and retained records

[Open all six task-described camera videos](../indices/2026-09-11-hang-mugs-and-sweep-blocks/README.md).
Each MP4 is an exact-byte copy, not a rerender. Hang has 257 frames/camera and
sweep 247, at 640x480/25Hz. Playback omits policy thinking/waiting and intermediate
physics ticks, so its 10.28s/9.88s duration is not wall-clock episode duration.
Root inspected both initial/final head views: arms and objects visibly moved;
visual impressions were not used to override native failure or assign progress.

Raw base beneath this benchmark's results:
`raw/2026-09-11-hang-mugs-and-sweep-blocks-cache-checkpoint/`.
Formal records are `campaign/case-000/run` and `campaign/case-001/run`;
task-described record/artifact/progress reports are in `derived/`. All six
postprocessor invocations passed from the matching frozen 49-source bundle.
Original handles: hang95528, sweep49973; record audits84495/29637;
artifact audits86798/3482; progress invocationsfe0384/4acff3. Video/index
export 75562 exited 0 and copied six preselected videos totaling 4,482,515 bytes.

The [machine-readable index](../indices/2026-09-11-hang-mugs-and-sweep-blocks/index.json)
has SHA256 `907fffe57a20df46b99028c8bd3a06e0b9b63c14e4aa83aad2006b8b30292e45`.
The [explicit source/video selection](2026-09-11-continuation-video-sources.json)
was fixed before either outcome, SHA256
`cca88baaa32e4d23823f12d5ef44c0924849ad1e0faaa40055ae737a245fc141`.
Original frozen packages, failed infrastructure probes and historical results
remain untouched. Raw output and generated media are Git-ignored. Generated
`public/mbx-*/` interface files are also ignored; unrelated public assets are not.

## Protocol and framework conclusions

The [preparation history](2026-09-10-continuation-pair.md) binds source commit
`9ae943df4b330459c94cf7d1f4aeb6018d42901c`, campaign
`fda8e134493ed979f1f48ed5822c0d9381a3ec91dbad3bf62e394c2f847efe9e`,
the original qualified asset reference and exact ten-file HTTP-cache checkpoint.
Both selected layout0/native seed0, ran concurrently on eval L20D GPUs6/7 with
unrelated jobs left intact, and used fresh opaque policy actors. Policy-visible
inputs remained language and three RGB cameras; outputs remained joint14
absolute targets. No diagnostic observation or native score was fed to actors.

The optional isolated cache checkpoint solved the observed corrupt-download
setup issue in the new probes, and retained-byte audits passed for both actual
attempts. It does not establish full URL authentication, renderer consumption,
complete asset closure or historical material parity. Provider/model identity,
provider token accounting and OS-enforced actor isolation remain unverified.

The shared global Kit log has interleaved/overwritten task records and watchdog messages;
it is not a clean per-task error log. This does not erase either completed
native result, but must remain an attribution limitation. Do not turn watchdog
string counts into task failures or silently declare those warnings absent.
The [independent closed-pair review](../../../../../project_readmes/reviews/2026-09-11-dojo-continuation-closed-pair-review.md)
is accepted. It records both observed shared-log digests/counts and the preliminary
overstrict inspector assertion failure; neither is relabelled as a task failure.
Root additionally copied the stable final bytes, without changing the source,
to `derived/shared-kit-2026-09-11-003141-final.log`, SHA256
`9e6014abfdf2db0fe9b7b57b9102660e1f352006b266607ae383f814ae117592`.
This final snapshot contains two watchdog-text occurrences at one timestamp;
it does not reconstruct the earlier overwritten content.
A
[source-backed future log-routing proposal](../../../../../project_readmes/reviews/2026-09-11-dojo-future-kit-log-routing.md)
is recorded without changing this run's worker or launching another attempt.

The action interface is now exercised beyond early give-up, but these two
once-only RGB/joint14 trials do not establish general model capability or an
overall RoboDojo success rate. Any future ordinary proprioception, task-neutral
motion helper or changed horizon must be declared in a new protocol before a
new authorized trial; it must not use hidden simulator state or retrofit these
results. Benchmark environment/protocol guidance stays under `examples/`;
model configuration and result ownership remain under `starVLA/<model>/`.
