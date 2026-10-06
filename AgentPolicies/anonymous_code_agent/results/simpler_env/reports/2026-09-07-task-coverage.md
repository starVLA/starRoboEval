> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/SimplerEnv/reports/2026-09-07-task-coverage.md` at source revision `29cb55d`;
> original SHA256: `d27df6e19784c3a27d40f36c1373e223685d1d96eb0927c3bb7312ca31195f6d`. Only documentation links were rebased.

# SimplerEnv one-attempt task coverage — attempts closed, review in progress

Campaign `runs/simpler-task-coverage-20260907-001` froze all 15 canonical tasks,
one prepackaged reset per task and seed 20260907 before any attempt. This is
task coverage, not the complete robot/scene/appearance/reset variation matrix.
It is separate from the historical first-two extended-horizon development pass.

Protocol: `simpler-prepackaged-development/rgb/decision-200-prefix-5/v1`.
Each task permits 200 decisions, at most five native controls per response and
a 1000-control safety cap, retaining its registration horizon separately.
Native final success is authoritative; transient success and policy stops do
not independently award success. Actors receive current RGB/language only.
Model/provider/usage remain unknown; this is not a named GPT or official score.
Cases000–002 also received benchmark/case identifiers through orchestration
labels, outside the public payload. Opaque actor naming starts at case003;
no earlier attempt is retrospectively blinded or retried. See the
[operator-context disclosure](../../../../../examples/simBenchmarks/TASK_COVERAGE.md#known-operator-context-limitation-and-prospective-cutover).

## Closed entries at this checkpoint

| Case | Canonical task | Native final success | Controls | Decisions | First native success |
| --- | --- | --- | ---: | ---: | --- |
| 000 | google_robot_pick_horizontal_coke_can | true | 78 | 25 | control 64 / decision 21 |
| 001 | google_robot_pick_vertical_coke_can | true | 937 | 200 | control 91 / decision 31 |
| 002 | google_robot_pick_standing_coke_can | true | 138 | 46 | control 130 / decision 44 |
| 003 | google_robot_move_near_v0 | true | 194 | 59 | control 41 / decision 17 |
| 004 | google_robot_open_top_drawer | false; rendering issue | 1 | 2 | null |
| 005 | google_robot_open_middle_drawer | false; rendering issue | 1 | 2 | null |
| 006 | google_robot_open_bottom_drawer | false | 130 | 35 | null |
| 007 | google_robot_close_top_drawer | true | 195 | 53 | control 96 / decision 27 |
| 008 | google_robot_close_middle_drawer | null; policy error | 23 | 12 | null |
| 009 | google_robot_close_bottom_drawer | true | 329 | 77 | control 186 / decision 47 |
| 010 | google_robot_place_apple_in_closed_top_drawer | false | 238 | 72 | null |
| 011 | widowx_spoon_on_towel | true | 206 | 52 | control 134 / decision 37 |
| 012 | widowx_carrot_on_plate | true | 242 | 60 | control 170 / decision 44 |
| 013 | widowx_stack_cube | null; operator-induced schema error | 0 | 1 | null |
| 014 | widowx_put_eggplant_in_basket | true | 49 | 22 | control 45 / decision 21 |

Case 000 executed 24 action chunks and then an explicit stop. The recorded
termination reason is exactly `policy:give_up`; this label is not rewritten
as environment termination, and does not turn the native success into failure
or award it. The adapter retains the last native step's boolean success.
Steps 1–63 were false and steps 64–78 were true: 15 consecutive successful
controls at the end, native reward sum 15. No error, retry or additional scoring
query occurred. The actor was not given native success or intermediate feedback.

The native registration horizon is 80. This attempt stopped at 78, before
either H80 or the development cap1000, so both horizon checkpoint fields remain
null. Continued success at those horizons was not tested. Do not present this
early-stop development result as fixed-horizon leaderboard parity. Native
control frequency is 3 Hz (simulation 513 Hz); 78 controls advance 26 seconds
of simulation. Mailbox latency was 648.03 seconds, not provider inference time.

Root's closed-record audit verified the copied source, 25 scheduled decisions,
accepted embedded responses, executed prefixes, counters and result/summary
agreement. Separate artifact checks rehashed all 79 native PNGs and matched
all 25 public images pixel-for-pixel with their scheduled native frames. Public
state was null; payload specifications, prompt hash and native instruction
matched the declared interface. The complete video independently decoded to
79 nonblank 640×512 frames: reset plus every controlled step.

Original source:
`case-000/run/episodes/google_robot_pick_horizontal_coke_can-000000/`.
The hash-checked archive is
`../rollouts/2026-09-07-task-coverage-case000/`, with video SHA256
`980cd7f5800be5258cc463f705ad8298ea53862ff1cf4b9b6301aec5dd9069c5`.
`case-000/progress.json` derives first-success timing from the original events;
`case-000/record_audit.json` records offline consistency and its limitations.
Original results are unchanged; generated videos/reports are ignored by Git.

Case 001 exhausted its 200-decision budget after 937 actual controls, with
`runner:policy_call_limit`, no policy stop, interface error or retry. Its first
native success occurred at control 91 / decision 31. Controls 1–90 were false;
91–937 were true, giving 847 consecutive successful controls and native reward
sum 847. This does **not** mean that success required 937 controls or 200 calls.
The actor received no native flag or post-success instruction from the evaluator.

The H80 checkpoint is false; the H1000 checkpoint is null because that cap was
not reached. Final success belongs to this predeclared decision-primary track,
not to an original 80-step evaluation. Neither the first-success diagnostic nor
a retrospective shorter cutoff can replace the declared final-success metric.
At 3 Hz the controlled simulation lasted 312.33 seconds; recorded mailbox
latency was 2399.57 seconds, not verified provider inference accounting.

Generic record and full mailbox-artifact checks passed: all 938 native PNGs,
200 exact scheduled public-image matches, prompt/specification/budgets/responses,
and all 938 nonflat 640×512 video frames. Maximum lossy-codec pixel MAE versus
the corresponding native PNG is 1.585/255, a diagnostic rather than a score.
Original evidence is under
`case-001/run/episodes/google_robot_pick_vertical_coke_can-000000/`; new
progress/record/artifact reports are outside that closed run. Video copies and
the source/result-bearing index are under
`../rollouts/2026-09-07-task-coverage-case001/`, video SHA256
`9e8bd466267686d06cee955b39778961140ecb9eb7337b46eb1aea913cf16cf2`.
The [independent review](../../../../../project_readmes/reviews/2026-09-07-coverage-artifact-tool-review.md)
verified this case directly, including all accepted responses and separately
sampled PNG/video linkage. It found a termination-label checker blind spot and
verified the offline-only repair; original records and reports remain unchanged.
Native accumulated success, first-success timing and decision-cap termination
are kept distinct. The review retains all provider/isolation/parity limitations.

Case 002 stopped with exactly `policy:give_up` after 138 controls / 46 decisions:
45 action chunks and one explicit stop. Native final success was true; the
first success was control 130 / decision 44. Controls 1–129 were false and
130–138 were true, giving nine successful controls at the end. H80 is false
and H1000 remains null. No error, retry or additional scorer query occurred.
At 3 Hz this is 46 seconds of controlled simulation; mailbox latency was
1915.97 seconds, not verified provider inference time. Neither the voluntary
stop label nor the first-success diagnostic replaces native final scoring.

The tightened record and full mailbox-artifact audits passed: 139 native PNGs,
46 exact scheduled public-image matches and all 139 nonflat 640×512 video
frames. Maximum codec pixel MAE was 1.579/255, reported only as a diagnostic.
Original evidence is under
`case-002/run/episodes/google_robot_pick_standing_coke_can-000000/`;
progress and audit reports remain outside the closed run. Copies are under
`../rollouts/2026-09-07-task-coverage-case002/`, video SHA256
`cb814aeb6c820e11d73e2ad1740748a63caf03d1fee04f653c5c6bc4a7925f5c`.

Case 003 stopped with `policy:give_up` after 194 controls / 59 decisions, with
native final success and no error or retry. It executed 58 action chunks and
one stop. First native success was control 41 / decision 17, but success was
not continuous afterward: true intervals were 41–49, 62–94, 111 alone, and
164–194. There were 74 successful controls in total and 31 consecutively at the
end. H80 is true; H1000 is null. First success, an intermediate horizon
checkpoint and declared final success are distinct fields, not interchangeable
stopping rules. At 3 Hz this is 64.67 controlled simulation seconds; measured
mailbox latency was 2271.25 seconds, not provider inference accounting.

The tightened record and full artifact audits passed: all 195 native PNGs,
59 exact public-image matches and the entire 195-frame, nonflat 640×512 video.
Maximum codec pixel MAE was 1.654/255. This is the prospective opaque actor-name
cutover, not proof of OS isolation or total provider/context accounting.
Original evidence remains under
`case-003/run/episodes/google_robot_move_near_v0-000000/`, with derived reports
outside the closed run. Copies and source-bearing index are under
`../rollouts/2026-09-07-task-coverage-case003/`, video SHA256
`6e7be47423c51a69a0a6a5f31381e8efc15034ce61b729ae4d430205f21aeff0`.

Cases004 and005 each executed one native control, then stopped at decision2
with `policy:give_up`. Final native success is false, first success remains
null, and there was no runner/interface exception or retry. Their reference
horizon113 and cap1000 were not reached. Mailbox latency was 75.66 seconds and
68.62 seconds respectively. These observations must **not** be interpreted as
clean measurements of drawer-manipulation capability: the rendered cabinet
and visible robot are black silhouettes against the photographic background.

Both logs contain OptiX internal/invalid-value errors and repeated denoising
failures. The pinned drawer setup selects ray tracing with denoising, unlike
the prior can/move-near IBL cases. Separate infrastructure diagnostics002/003
isolated missing driver denoiser data: native-on with authentic matching weights
restores the foreground without changing geometry, masks or native settings.
The data is exposed only in a private read-only mount namespace; global driver
files and existing attempts remain untouched. See [RENDERING.md](../../../../../examples/simBenchmarks/SimplerEnv/RENDERING.md).
No active policy received private diagnostic feedback. Case005
had already started before the closed case004 image was inspected; all further
unclaimed SimplerEnv launches were held for this rendering investigation.

The ordinary audits still pass: each case has two native PNGs, two exact public
image matches and a complete two-frame nonflat video. A textured background can
make whole-frame nonflatness pass while the task foreground is unusable. Record
consistency/pixel transport therefore does not attest rendering quality.
Retain both original native failures, action/stop records and diagnostic caveat;
do not retry them, rewrite their results or silently remove them from coverage.
Archives are `../rollouts/2026-09-07-task-coverage-case004/` and
`../rollouts/2026-09-07-task-coverage-case005/`:

- case004 video: `63a82eb71b2279c590d1d9efb5d0f4305c8dfde6a62425b12e64f97e7e880633`
- case005 video: `51711f9d23b6d501c79d5e4028a1ed8781fb0d192efb56a9a4a1c534ed1d3095`

Case006 is the first capability attempt through the accepted data-restoration
namespace, with native denoising and the frozen source/task/budget unchanged.
It ended with `policy:give_up` after 130 controls / 35 decisions:34 action chunks
and one stop. Every native success flag was false; first success remains null.
There was no error or retry. Reference113 was exceeded under the predeclared
decision-primary cap1000. Controlled simulation was 43.33 seconds at 3 Hz;
mailbox latency was 1830.61 seconds, not provider inference accounting.

Complete record/artifact checks passed:131 native PNGs,35 exact public-image
matches and the full131-frame 640×512 video, with no flat frames and maximum
codec MAE1.575/255. Root separately inspected closed reset/final PNGs:the cabinet
and robot have visible native colors, unlike cases004/005. The closed console
contains no OptiX/denoising error. The launch result records returncode0 and
unchanged restoration dependencies after exit. This bounded inspection does
not certify all pixels, native parity or task success. The actor received none
of the private diagnostic findings. Original failure and copied archive under
`../rollouts/2026-09-07-task-coverage-case006/` remain intact, video SHA256
`e6fba351025cc8a0bcc4b32bdfe4e878ca9c91dbdc69b126298bd09779ec1a1d`.

Case007 closed once with native final success after 195 controls / 53 decisions,
ending with `policy:give_up`: 52 action chunks and one explicit stop. First native
success occurred at control 96 / decision 27. Controls 1–95 were false and
96–195 true, giving 100 successful controls at the end. H113 is true and H1000
remains null. No error, retry, extra scoring query or private feedback occurred.
The first-success count is not the final control count; neither the stop label
nor the intermediate H113 flag replaces declared final scoring. Controlled
simulation was 65 seconds at 3 Hz; mailbox latency was 1618.23 seconds.

Record and full artifact checks passed: 196 native PNGs, 53 exact public-image
matches and the full 196-frame 640×512 video, with no flat frames and maximum
codec MAE 1.559/255. Root inspected closed reset/final images with colored native
foreground and found no OptiX/denoising error in the closed console. The external
restoration result records returncode 0 and unchanged dependencies after exit.
The original result and archive under
`../rollouts/2026-09-07-task-coverage-case007/` remain intact, video SHA256
`f890025beac9d9fbd549b1033d8f1f96a74977b8d8aca23325072334ec2fb409`.
Rendering inspection remains bounded, not exhaustive image/native parity.

The [independent restored-capability review](../../../../../project_readmes/reviews/2026-09-07-simpler-restored-capability-review.md)
directly verified cases006/007: 327 native PNGs, 88 public observations/responses,
both complete videos, all 86 action prefixes, source/policy bindings and both
case-specific restoration receipts. Fresh record/progress/artifact reports
exactly reproduce the originals. The sampled colored foreground and timing
support this bounded repair check, not every later trajectory or native parity.

Case008 ended with `error:policy` on decision 12: a submitted action had six
values where the public action specification required seven. The response
contained two vectors of lengths [7, 6]; even its valid first vector was not
executed because the whole response is validated before execution. Eleven previously
accepted chunks executed 23 controls; no part of the rejected response executed.
All 23 logged native flags were false, but final `success` is **null**, not a
manufactured native false result. First success remains null and the error
attempt stays in the denominator. There was no repair request, response retry,
task reset or additional scoring query. The permanent claim is retained.

The generic closed-record audit passes its error-consistency checks, including
12 started versus 11 returned decisions and all 23 copied source files. Progress
and the hash-checked 24-frame video archive are retained under
`../rollouts/2026-09-07-task-coverage-case008/`. Root inspected closed reset/final
PNGs with colored foreground; the console has no OptiX/denoising error and the
cutover result confirms unchanged dependencies with returncode 1. The standard
full mailbox-artifact checker does not support error runs: this case does not
receive a fabricated full-artifact pass. The
[independent policy-error review](../../../../../project_readmes/reviews/2026-09-07-simpler-policy-error-review.md)
verified all 24 native PNGs, 12 public observations/images, 11 raw/accepted
response pairs, the rejected raw response and the entire 24-frame video through
a separately scoped error-specific inspection. Record/progress recomputations
exactly match the originals. It confirms a genuine malformed response and
whole-chunk rejection, not a demonstrated harness rejection bug.
The retained video SHA256 is
`258b24d5aa455afa98b17c904b4f27516d9210947aaad735ac14a12a11fc31d8`.

Case009 closed with native final success after 329 controls / 77 decisions:
76 action chunks and one explicit `policy:give_up` stop. First success appeared
at control 186 / decision 47. Native true intervals were 186–275 and 281–329,
with five intervening false controls: 139 successful controls in total and 49
consecutively at the end. H113 is false and H1000 remains null. The first-success
diagnostic, intermediate checkpoint and declared final flag remain distinct.
No error, retry or extra scorer query occurred. Controlled simulation was
109.67 seconds at 3 Hz; recorded mailbox latency was 2188.17 seconds, not
verified provider inference accounting.

Record and full artifact audits passed: 330 native PNGs, 77 exact public-image
matches and the complete 330-frame 640×512 video, with no flat frames and maximum
codec MAE 1.513/255. Root inspected the closed reset/final PNGs with colored
cabinet and robot foreground; the console contains no OptiX/denoising error.
The external cutover result confirms returncode 0 and unchanged dependencies.
These bounded checks do not certify exhaustive native parity. The original
result and hash-checked archive under
`../rollouts/2026-09-07-task-coverage-case009/` retain video SHA256
`1aca8b231e24f7fcd3d1a0e7872ba5314361f3a0e607977d4800d902dda5b535`.

Case010's apple-in-drawer task ended with `policy:give_up` after 238 controls /
72 decisions: 71 action chunks and one stop. All 238 native success flags were
false; first success remains null. H200 is false and H1000 remains null. This
task's pinned registration horizon is 200, not the simpler drawer tasks' 113;
the common D200/prefix5/cap1000 development budget did not change. No error,
retry or extra scoring query occurred. Controlled simulation was 79.33 seconds
at 3 Hz; mailbox latency was 2201.33 seconds, not provider inference accounting.

Record and full artifact checks passed: 239 native PNGs, 72 exact public-image
matches and the entire 239-frame 640×512 video, with no flat frames and maximum
codec MAE 1.495/255. Root inspected closed reset/final PNGs showing colored
cabinet, apple and robot foreground; the console contains no OptiX/denoising
error. The external restoration result confirms returncode 0 and unchanged
dependencies. This is bounded rendering evidence, not visual rescoring or
exhaustive native parity. The original failure and archive under
`../rollouts/2026-09-07-task-coverage-case010/` retain video SHA256
`105d7a0c2702af1a8c6ab62ca61e56f2ae26e477ced793afe33a72a336753d6f`.

All 11 Google-robot entries now retain their one attempt: six native successes,
four native failures (including the two rendering-defect cases), and one
null-score policy error. This mixed development evidence is not a formal model
score and does not erase the rendering/operator-context limitations.

Case011's WidowX spoon-on-towel attempt ended with native final success after
206 controls / 52 decisions: 51 action chunks and an explicit `policy:give_up`
stop. First native success was control 134 / decision 37. Controls 1–133 were
false and 134–206 true, giving 73 successful controls at the end. H60 is false
and H1000 remains null. The successful expanded-budget result is not an
original 60-control success, nor a replacement for the separately preserved
historical first-pass failure. No error, retry or extra scorer query occurred.
WidowX runs at 5 Hz: controlled simulation was 41.2 seconds; mailbox latency
was 1969.89 seconds, not verified provider inference accounting.

Record and full artifact audits passed: 207 native PNGs, 52 exact public-image
matches and the complete 207-frame 640×480 third-view video, with no flat frames
and maximum codec MAE 1.492/255. Root inspected closed reset/final PNGs showing
visible spoon/towel geometry and colors; the console contains no OptiX/denoising
error. The external launcher result records returncode 0 and unchanged
dependencies. Native final metrics include both `src_on_target=true` and
`is_src_obj_grasped=true`; this grasp telemetry is historically OR-latched,
not proof of a current final-step grasp. Native placement success has no
additional release predicate; the harness adds none and does not visually
rescore. Bounded image checks are not native parity proof.
The original result and archive under
`../rollouts/2026-09-07-task-coverage-case011/` retain video SHA256
`c623f085b6c7dfddcd3d6675e98c7e2bf1e53ccf456c730a7f45de0d6aa7bb9e`.

Case012's carrot-on-plate attempt closed with native final success after
242 controls / 60 decisions, including the final `policy:give_up` stop.
First success was control 170 / decision 44; 22 controls logged true in total,
with 13 true controls at the end. H60 is false and cap1000 was not reached.
No error, retry or extra scoring query occurred. At 5 Hz, controlled simulation
was 48.4 seconds; mailbox latency was 2583.89 seconds, not provider accounting.
Record/artifact checks passed: 243 native PNGs, 60 exact public-image matches
and a complete 243-frame 640×480 video, with no flat frames and maximum codec
MAE 1.472/255. Root inspected colored reset/final carrot/plate imagery; no
console OptiX/denoising error appeared and external restoration dependencies
remained unchanged. This is bounded image verification, not visual rescoring.
Archive `../rollouts/2026-09-07-task-coverage-case012/` retains video SHA256
`33662e08124022fbb058db78220ed0f03e3df1dee83dd0401c85a3eaeb08df70`.

Case013 preserves an operator-induced transport/schema error: one decision
started, none accepted, zero native controls, empty metrics and null success.
Root supplied an incorrect out-of-band `notes` example (and an unused incorrect
`reason` stop example); the frozen public prompt correctly names `note` and
`stop_reason`. The sole response used `notes`, rejected before action execution.
The original category stays `error:policy`, but this is not a pure model
capability failure. No repair, retry, deletion or score rewrite is permitted.
An [independent closed-error review](../../../../../project_readmes/reviews/2026-09-07-simpler-operator-schema-error-review.md)
verified frozen source/prompt/endpoint, absent accepted/control events, exact
initial-PNG binding and one 640×480 video frame at 5 fps. The generic record
audit passes; the full artifact checker explicitly does not support error runs.
The exported initial-frame video (not a trajectory) retains SHA256
`510b76589cb76d0912132ddde5867816ac5b366ddb5e12129a4655e038d7708b`
under `../rollouts/2026-09-07-task-coverage-case013/`.

New canonical actor instructions omit optional commentary keys and use the
correct minimal action/stop schemas. Four tests passed against the actual frozen
parser, independently rechecked. Root sent the exact host/mailbox-substituted
template to fresh case014; its SHA256 is
`887e4a6f8398c131bdbb226f076c6a4b18364ba23b98a0991a84c90a6c1c3349`.
This prospective correction changes no frozen runtime, public prompt or prior
score, and does not establish homogeneous actor context.

Case014 put the eggplant in the basket: native final success after49 controls /
22 decisions, first success at45/21 and five true native controls at the end.
The final decision is `policy:give_up`; no error or retry occurred. Controlled
simulation was9.8 seconds at5Hz and mailbox latency480.15 seconds. H120 and
cap1000 are unreached, so neither fixed-horizon checkpoint is a measured score.
Record/fullartifact checks passed:50 native PNGs,22 exact public-image matches
and50 complete 640×480 video frames, no flat frames, maximum codec MAE1.742/255.
Root inspected closed reset/final PNGs; external driver data remained unchanged.
The archive `../rollouts/2026-09-07-task-coverage-case014/` retains video SHA256
`a53f48301971b83ad52ab53f92dbc1dfc067623cce285bb8124dcc36f085a8e9`.
The corrected operator wire example produced accepted decisions in this sole
attempt; that does not retroactively repair case013 or attest provider usage.

All15 preselected tasks now retain one terminal attempt:13 completed episodes
(nine native true, four native false) and two null-score policy-category errors.
No active or unattempted entries remain. This closes attempt coverage, not
uniform native parity, valid capability measurements for the defective cases,
or a formal provider/model score. The
[independent WidowX closed review](../../../../../project_readmes/reviews/2026-09-07-simpler-widow-closed-review.md)
accepted cases011/012/014 within its stated bounds: nine fresh offline audits,
500 fully decoded frames and134 exact public-image matches. It confirms the
native placement scorer and historical grasp-telemetry distinction, not
provider attestation or uniform native-horizon parity.
The repair's frozen external plan and
per-case launch/result receipts are under
`runs/simpler-rendering-cutover-20260907-001/`, outside the original campaign.
Continue only unclaimed
cases, retain failures/errors, and use campaign `summarize` for live coverage.
Broader native parity, OS isolation, trusted provider metering and independent
review of the expanded closed coverage remain separate work.
