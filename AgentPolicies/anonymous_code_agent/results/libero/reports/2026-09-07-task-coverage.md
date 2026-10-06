> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/LIBERO/reports/2026-09-07-task-coverage.md` at source revision `29cb55d`;
> original SHA256: `299ab79e1fdfe205ee9f7459444f602227da3aa22017c7607786d72b132e3ac6`. Only documentation links were rebased.

# LIBERO one-attempt task coverage — paused by user

Pause checkpoint:38/130 closed (25 true,13 false),92 unattempted. Case037
finished before pausing; do not launch038 until user resume. The complete
[task checklist](../TASK_CHECKLIST.md) records every selected identity and count.

Campaign: `runs/libero-task-coverage-20260907-001`, frozen before any attempt,
with 130 suite-task entries: Spatial 10, Object 10, Goal 10, LIBERO-90 90 and
LIBERO-10 10. Each selects released initial-state index 0, task order 0 and
seed 20260907. This is not all 6500 initial-state variants or an official score.
The former two-task/40-decision development pass remains a separate experiment.

Each new task permits 200 decisions, prefix at most five and 1000 controlled
steps, keeping its suite's retained reference horizon separate. Ten native
settling actions are initialization, not policy controls or decisions. A fresh
actor receives only its opaque public mailbox; provider/model/usage remain
unknown, and filesystem isolation is procedural rather than OS-enforced.
Cases000–007 also received benchmark/case identifiers through orchestration
labels, outside the public payload. Opaque actor naming starts at case008;
existing attempts are not retrospectively blinded or retried. See the
[operator-context disclosure](../../../../../examples/simBenchmarks/TASK_COVERAGE.md#known-operator-context-limitation-and-prospective-cutover).

## Closed entries at this checkpoint

| Case | Suite / task | Native success | Controls | Decisions | First success |
| --- | --- | --- | ---: | ---: | --- |
| 000 | Spatial / 0 | true | 130 | 26 | control 130 / decision 26 |
| 001 | Spatial / 1 | true | 160 | 33 | control 160 / decision 33 |
| 002 | Spatial / 2 | true | 187 | 38 | control 187 / decision 38 |
| 003 | Spatial / 3 | true | 183 | 37 | control 183 / decision 37 |
| 004 | Spatial / 4 | false | 389 | 82 | null |
| 005 | Spatial / 5 | true | 84 | 18 | control 84 / decision 18 |
| 006 | Spatial / 6 | false | 213 | 44 | null |
| 007 | Spatial / 7 | true | 392 | 79 | control 392 / decision 79 |
| 008 | Spatial / 8 | true | 247 | 52 | control 247 / decision 52 |
| 009 | Spatial / 9 | true | 196 | 41 | control 196 / decision 41 |
| 010 | Object / 0 | false | 224 | 48 | null |
| 011 | Object / 1 | true | 228 | 47 | control 228 / decision 47 |
| 012 | Object / 2 | true | 362 | 74 | control 362 / decision 74 |
| 013 | Object / 3 | true | 197 | 41 | control 197 / decision 41 |
| 014 | Object / 4 | true | 167 | 35 | control 167 / decision 35 |
| 015 | Object / 5 | true | 85 | 18 | control 85 / decision 18 |
| 016 | Object / 6 | true | 113 | 24 | control 113 / decision 24 |
| 017 | Object / 7 | true | 117 | 24 | control 117 / decision 24 |
| 018 | Object / 8 | true | 103 | 22 | control 103 / decision 22 |
| 019 | Object / 9 | false | 103 | 22 | null |
| 020 | Goal / 0 | true | 83 | 17 | control 83 / decision 17 |
| 021 | Goal / 1 | true | 112 | 25 | control 112 / decision 25 |
| 022 | Goal / 2 | false | 436 | 89 | null |
| 023 | Goal / 3 | false | 436 | 89 | null |
| 024 | Goal / 4 | true | 179 | 37 | control 179 / decision 37 |
| 025 | Goal / 5 | false | 370 | 75 | null |
| 026 | Goal / 6 | true | 76 | 16 | control 76 / decision 16 |
| 027 | Goal / 7 | true | 105 | 22 | control 105 / decision 22 |
| 028 | Goal / 8 | true | 198 | 40 | control 198 / decision 40 |
| 029 | Goal / 9 | false | 220 | 45 | null |
| 030 | LIBERO-90 / 0 | false | 196 | 41 | null |
| 031 | LIBERO-90 / 1 | false | 237 | 51 | null |

Case 000's language is “pick up the black bowl between the plate and the ramekin
and place it on the plate.” It completed once, with no error, stop or retry.
All 26 five-action prefixes executed. Controls 1–129 logged native false and
130 logged true, ending with `environment:terminated`. Reference horizon is
220, separate from the 1000-control development cap. Controlled simulation
was 6.5 seconds at 20 Hz; measured mailbox latency was 784.13 seconds, not
provider inference accounting.

Root's offline record audit verified the copied source and all decision/action/
control/result accounting. The separate artifact audit rehashed all 262 native
PNGs and matched all 52 public images pixel-for-pixel with their scheduled
native frames. Public state was null and JSON contained only the declared
interface. Two videos independently decoded to 131 nonblank 256×256 frames
each. First-success progress comes from existing native flags, not a new query.

Copies and source-bearing indexes are under
`../rollouts/2026-09-07-task-coverage-case000/`; original evidence remains in
`case-000/run/episodes/libero_spatial-task00-init00/`. Video hashes:

- agentview: `b64e8cb5a011599221008dca6e3063d35b492f498a523995f6e743cc770a9383`
- wrist: `426e295a7b37640d690ef6c36217036326d26679e51720b8d8a5dd78357a502b`

Case 001's language is “pick up the black bowl next to the ramekin and place it
on the plate.” It completed once with native success at control 160 / decision
33, without error, policy stop or retry. Actual action prefixes have variable
length; the decision count is not control count divided by five. Reference
horizon remains 220, separate from the 1000-control development cap. Controlled
simulation was 8 seconds at 20 Hz; mailbox latency was 1117.22 seconds.

Root's closed-record audit passed. The separate artifact audit checked all 322
native PNG hashes, 66 exact scheduled public-image matches and the public
prompt/specification/response boundary. Both videos fully decoded to 161
nonblank 256×256 frames. Copies are under
`../rollouts/2026-09-07-task-coverage-case001/`; first-success progress was
derived only from existing native flags. Video hashes:

- agentview: `af62a5ef96ab04190b4be73662c3185117293e795f10adfff73eb3bab4d79052`
- wrist: `88f97862d535b9d4e9af0ea2559071957870de59957990e9cb4b90ab05647236`

Case 002's language is “pick up the black bowl from table center and place it on
the plate.” It completed once with native success at control 187 / decision 38,
without error, policy stop or retry. The first 186 native flags were false.
Its variable-length chunks and native termination leave 9.35 seconds of
controlled simulation at 20 Hz; mailbox latency is 1073.33 seconds. Reference
horizon is 220 and the predeclared development cap remains 1000 controls.

Both generic record and full mailbox-artifact audits passed. The latter verifies
376 native PNGs, all 76 public pixel matches, prompt/specification/budget/response
agreement, and two fully decoded 188-frame 256×256 videos with no flat frames.
Maximum lossy-codec pixel MAE is 2.35/255 (agentview) and 3.16/255 (wrist), reported
as diagnostics, not scoring. Root separately rehashed the pinned task BDDL,
released 50-state file and selected state-0 array bytes for cases 001 and 002.
No simulator reset/step or additional scoring query occurred during this audit.
Case 002's original progress, record and artifact audit files remain private;
copies are under `../rollouts/2026-09-07-task-coverage-case002/`. Video hashes:

- agentview: `84d3dcf7c205a249bd9742d8c5f2aa7158ae6618a12dbb34e22d0f1d42d6b2c6`
- wrist: `c765fa40d352a83abde2a113f4016836045e325f15b9b6a1fd3a2ccc3570ea8b`

Case 003's language is “pick up the black bowl on the cookie box and place it on
the plate.” Its single attempt succeeded first at control 183 / decision 37,
ending on native termination with no error, stop or retry. All earlier native
flags were false. Controlled simulation was 9.15 seconds at 20 Hz; mailbox
latency was 1208.24 seconds. Reference horizon remains 220, distinct from cap1000.

Record and mailbox-artifact audits verified 368 native PNGs, 74 public pixel
matches and both fully decoded 184-frame videos, without flat frames. Maximum
codec pixel MAE was 2.33/255 and 3.26/255. Root separately checked pinned BDDL,
released-state file and selected state-0 bytes offline. The case's original
records/progress/audits and archive under
`../rollouts/2026-09-07-task-coverage-case003/` remain intact. Video hashes:

- agentview: `18f3c0d4ac6695af0066b808fccc63b4b044f74b4ecb753f6d47cc314ecc64c1`
- wrist: `3a7a4f671cec049e13640eb825667efe2f6b3ad9a35c916c78a3581bf0d26406`

Case 004's language is “pick up the black bowl in the top drawer of the wooden
cabinet and place it on the plate.” Its single attempt failed after 389 controls
and 82 decisions: 81 action chunks followed by `policy:give_up`. All 389 native
flags were false, and first-success fields remain null. It did not exhaust the
200-decision cap; voluntary stop remains a valid preserved failure. There was
no interface error or retry. It crossed the 220-step reference horizon under
the original 1000-control decision-primary cap. Controlled simulation lasted
19.45 seconds, while recorded mailbox latency was 2461.53 seconds.

The tightened record audit and full artifact audit passed, including 780 native
PNGs, 164 public-image matches and two complete 390-frame videos with no flat
frames. Maximum codec pixel MAE was 2.38/255 and 3.96/255. Copies are under
`../rollouts/2026-09-07-task-coverage-case004/`, retaining native failure:

- agentview: `2440dd6d5eaa7baaa9bab32c00e4564d3493eda2b56444f016b3c7d6d3ad31d7`
- wrist: `a107d612808057a5f66e057f7078869abee0b569b0bafae20ead5ee8ee70b2c9`

Case 005's language is “pick up the black bowl on the ramekin and place it on
the plate.” It succeeded first at control 84 / decision 18 and ended with
`environment:terminated`, without error, policy stop or retry. All earlier
native flags were false. Controlled simulation lasted 4.2 seconds at 20 Hz;
mailbox latency was 506.39 seconds. Reference horizon remains 220.

The tightened record and full artifact audits verified 170 native PNGs, 36
public-image matches and both full 85-frame videos, with no flat frames and
maximum codec MAE 2.30/255 and 3.17/255. Root checked BDDL, released-state files
and selected state-0 bytes offline for both cases 004 and 005. Source originals
remain unchanged; case005 copies are under
`../rollouts/2026-09-07-task-coverage-case005/`. Video hashes:

- agentview: `8064d93bf443c8f3969f83c78649314d02e24aa4df04cf8d50076b72728042df`
- wrist: `7978c456cc82391b432ff0a9a6fc818cd9f4d8244f4d2a7402f91ddcd815fdee`

Case 006's language is “pick up the black bowl next to the cookie box and place
it on the plate.” Its sole attempt failed after 213 controls / 44 decisions:
43 action chunks and one explicit `policy:give_up`. All native flags were false,
first-success fields remain null, and there was no error or retry. The 220-step
reference horizon was not reached; the frozen decision-primary budget was not
exhausted. Controlled simulation was 10.65 seconds at 20 Hz; mailbox latency
was 1328.05 seconds, not provider inference accounting.

The tightened record and complete artifact audits passed, including 428 native
PNGs, 88 exact public-image matches and both 214-frame 256×256 videos, with no
flat frames. Maximum codec pixel MAE was 2.40/255 and 3.35/255. Failure videos
and source-bearing indexes are retained under
`../rollouts/2026-09-07-task-coverage-case006/`. Video hashes:

- agentview: `564cfe21b77bde688f310836dc656087f8e679b2fb853e5e670152c56a213a58`
- wrist: `117002e00d2e5bc2f224b1dfe68d2a915ac806c6f206d71c3f92dc6abb750cbd`

Case 007's language is “pick up the black bowl on the stove and place it on the
plate.” It succeeded first at control392 / decision79, ending with native
termination and no error, policy stop or retry. All earlier native flags were
false. The success is beyond reference220 under the frozen decision-primary
cap1000, not an H220 success. Controlled simulation was 19.6 seconds at 20 Hz;
mailbox latency was 3400.08 seconds, not provider inference time.

Record and full artifact audits passed: 786 native PNGs, 158 exact public-image
matches and both complete 393-frame 256×256 videos, with no flat frames.
Maximum codec pixel MAE was 2.32/255 and 3.13/255. Original results and
`../rollouts/2026-09-07-task-coverage-case007/` archives are retained:

- agentview: `63e08ec4e2c4a7889e48134f1d8f88688b192cc991d543026eafa10abe574f00`
- wrist: `3cdb0cb8574ea7891e72d3d0e8a1995f45cd97e16948d2c125f252d73151e346`

Case 008's language is “pick up the black bowl next to the plate and place it on
the plate.” Its sole attempt succeeded first at control247 / decision52 and
ended with `environment:terminated`, without policy stop, error or retry. All
prior native flags were false. It succeeded after the retained reference220
horizon under the original decision-primary cap1000; it is not a reference220
success. Controlled simulation was 12.35 seconds at 20 Hz; mailbox latency
was 1557.18 seconds, not provider inference accounting.

The tightened record and full artifact audits passed: 496 native PNGs, 104
exact public-image matches and both fully decoded 248-frame 256×256 videos,
with no flat frames and maximum codec MAE 2.30/255 and 2.93/255. This is LIBERO's
prospective opaque actor-name cutover; it does not attest OS/provider isolation.
Native evidence and source-bearing copies under
`../rollouts/2026-09-07-task-coverage-case008/` remain intact. Video hashes:

- agentview: `3a90c4ac353a3a972cd82b5401408908217f12809eed0a8bdbd37024e2e3a4b3`
- wrist: `2ad434e0b319c9a113635966f15a3b40f9b39d5c8ed8527470ad21b353fc2632`

Case 009's language is “pick up the black bowl on the wooden cabinet and place
it on the plate.” Native success first appeared at control 196 / decision 41,
ending with `environment:terminated` and no error, stop or retry. All preceding
flags were false; this success was within reference 220 and the unchanged
decision-primary cap 1000. Controlled simulation was 9.8 seconds at 20 Hz;
mailbox latency was 1817.35 seconds, not provider inference accounting.
The last response proposed five controls, but native termination occurred after
its first executed control; the remaining four were never applied. Decisions
therefore cannot be converted to actual controls by multiplying by five.

Closed record and full artifact audits passed: 394 native PNG hashes, 82 exact
public-image matches, and two fully decoded 197-frame 256×256 videos with no
flat frames. Maximum codec pixel MAE was 2.20/255 and 4.31/255. Originals and
copies under `../rollouts/2026-09-07-task-coverage-case009/` are retained:

- agentview: `a15bbeca86859538ce778c68aa760f02bb09d746ff6913f57f1a5f30b4456d73`
- wrist: `faba59c4a31f52c4f4fc781077c51b10b4498c3a1ec5ba9dd2a5cbaa286152cc`

Within these ten fixed-state Spatial attempts, six first successes occurred at
or before control 220; two further first successes occurred at 247 and 392.
The recorded flags therefore distinguish success within the reference control
budget from later success under the frozen extended budget. This is not a new
paired budget experiment or a general estimate of how extra decisions help.
Neither failure exhausted 200 decisions: both preserve the actor's voluntary stop.

Case010's language is “pick up the alphabet soup and place it in the basket.”
Its single attempt ended with `policy:give_up` after 224 controls / 48 decisions:
47 action chunks and the explicit stop. All native flags were false, with no
first success, error or retry. It stopped before Object's reference horizon280
and the frozen decision/control caps. Controlled simulation was 11.2 seconds;
mailbox latency was 1610.43 seconds, not provider inference accounting.

Complete record/artifact checks passed: 450 native PNGs, 96 exact public-image
matches and two fully decoded 225-frame 256×256 videos, without flat frames.
Maximum codec pixel MAE was 2.30/255 and 3.11/255. Original failure and copies
under `../rollouts/2026-09-07-task-coverage-case010/` are retained:

- agentview: `cabb2137f3fa39b168e94ed58e1b3fbe46af09f33037f45a79722bd37f2f2b4c`
- wrist: `3e96e62dab262dfe57853a5777b4aba080571953bd41ad8545f01204072a30d5`

Case011's language is “pick up the cream cheese and place it in the basket.”
Its sole attempt succeeded first at control 228 / decision 47 and ended with
native termination, without stop, error or retry. All earlier flags were false.
This is within Object's retained reference280, separate from cap1000. Controlled
simulation was 11.4 seconds at 20 Hz; mailbox latency was 2079.81 seconds, not
provider inference accounting.

Record and full artifact audits passed: 458 native PNGs, 94 exact public-image
matches and both fully decoded 229-frame 256×256 videos with no flat frames.
Maximum codec pixel MAE was 2.28/255 and 3.18/255. Originals and copies under
`../rollouts/2026-09-07-task-coverage-case011/` are retained:

- agentview: `1cad66852f76fde2a523fc3fc3d592e00777d72adb7d578b35bce41195ec40eb`
- wrist: `e76c05cbcdf94bfa69013bbde048d39e424df5bb20ef860b9c8726afb2e8449a`

The [independent Spatial/Object review](../../../../../project_readmes/reviews/2026-09-07-libero-spatial-object-closed-review.md)
directly verified cases009/010: task ordering, BDDL and released-state hashes,
844 native PNGs,178 public images,89 responses, four complete videos and exact
action-prefix/termination accounting. Two tampered-label probes were rejected.
A final image near the basket did not override Object case010's all-false native
predicate. Its bounded acceptance does not independently certify case011 or
other unreviewed trajectories.

Case013's language is “pick up the bbq sauce and place it in the basket.”
Its sole attempt succeeded first at control197 / decision41, with all preceding
native flags false and `environment:terminated`. No error, stop or retry occurred.
Reference280 was not exceeded. Controlled simulation was9.85 seconds at20 Hz;
mailbox latency1292.41 seconds is not verified provider inference accounting.
Record and full artifact checks passed:396 native PNGs,82 exact public-image
matches and two198-frame 256×256 videos, with no flat frames and maximum codec
MAE2.20/255 and2.87/255. Copies under
`../rollouts/2026-09-07-task-coverage-case013/` retain these hashes:

- agentview: `2b6837eb363fffaaa84e670bd5963505fc76e2a7c600689cf3b4d2d9861d5e50`
- wrist: `fd0d792628c7e8de1153409c5b15f1b4c8a42cad2fbcaaf2bc07fa09da1e69a7`

Case012's language is “pick up the salad dressing and place it in the basket.”
It closed after case013 because independent workers ran in parallel; neither
actor received information about the other attempt. Native success first
appeared at control362 / decision74, with all preceding flags false and native
termination. There was no error, stop or retry. This first success is beyond
Object's reference280 but within the predeclared D200/cap1000 track; it is not
a reference-budget success or a new paired-budget experiment. Controlled
simulation was18.1 seconds; mailbox latency was2239.89 seconds.

Record and full artifact audits passed:726 native PNGs,148 public-image matches
and two363-frame 256×256 videos with no flat frames and maximum codec MAE2.34/255
and2.96/255. Originals and copies under
`../rollouts/2026-09-07-task-coverage-case012/` preserve these hashes:

- agentview: `310520a5b289b64b09189a80c16f67965668902e64744d66626467721a406826`
- wrist: `42beb91cfefa6138c360f9d45d61e85de303fec35bc4e0503269e996d75e641c`

Cases014/015 respectively picked up ketchup and tomato sauce and placed the
named object in the basket. Their first native successes were control 167 /
decision 35 and control 85 / decision 18, both within reference 280. Each ended
on native termination with all earlier flags false, no stop, error or retry.
At 20 Hz their controlled simulation durations were 8.35 and 4.25 seconds;
mailbox latency was 749.39 and 556.78 seconds, not provider inference accounting.

Both record and full artifact audits passed. Case014 has 336 native PNGs,
70 exact public-image matches and two 168-frame videos; case015 has 172 native
PNGs, 36 public matches and two 86-frame videos. All video frames are 256×256
and nonflat. Maximum codec MAE is 2.25/2.87 for case014 and 2.27/2.91 for case015
(agentview/wrist, 0–255 units), a diagnostic rather than a score. Originals and
copies under `../rollouts/2026-09-07-task-coverage-case014/` and
`../rollouts/2026-09-07-task-coverage-case015/` preserve these hashes:

- case014 agentview: `0a664ed5b4f8134ddc5756c7b17395264adbbc479730061a6a76c1219a94aa30`
- case014 wrist: `1c2806da7269ed814a0495dea5ef3394f5d8cef5ca3ee064f0474ec075af45cd`
- case015 agentview: `e91544df1df0662c53d476efd4c0b3787e9ec5089ecc25e39331ab640a3ad23d`
- case015 wrist: `dbe520be5b783b074a3481237029fe068459e0d745c872c2fadce4ed3c2af806`

Case016 picked up the butter and placed it in the basket. Its first native
success was control 113 / decision 24, within reference 280, and ended the
episode with native termination. All earlier flags were false; no error, stop
or retry occurred. Controlled simulation was 5.65 seconds at 20 Hz; mailbox
latency was 741.46 seconds, not verified provider inference accounting.

Record and full artifact audits passed: 228 native PNGs, 48 exact public-image
matches and two 114-frame 256×256 videos with no flat frames. Maximum codec MAE
was 2.29/255 and 3.18/255. Copies and source-bearing indexes under
`../rollouts/2026-09-07-task-coverage-case016/` preserve these video hashes:

- agentview: `e99c2c30e5bfa95510229acd5d16e426d9e89033306eb088e0833662add14cf2`
- wrist: `7bb5458cf0f6b8e30dd9253f3b90436cd35ddae9567a8174ae74affc0bf41b21`

Case017 picked up the milk and placed it in the basket. Its first native success
was control 117 / decision 24, within reference 280, followed by native
termination. All earlier flags were false; no error, stop or retry occurred.
Controlled simulation was 5.85 seconds at 20 Hz; recorded mailbox latency was
1748.43 seconds, not verified provider inference accounting. Record and full
artifact checks passed: 236 native PNGs, 48 public-image matches and two
118-frame 256×256 videos, with no flat frames and maximum codec MAE 2.29/3.13.
Copies under `../rollouts/2026-09-07-task-coverage-case017/` retain these hashes:

- agentview: `8fdbebe8db13b9c08292c93069bad89f70dddcc9a4254f4e97f0f3ae975b24e5`
- wrist: `15f8305dfc7e48f93c532ae2d43d9f6e9bb9dd20bacc6b3d6b5bfdd7bc92de62`

Case018 picked up the chocolate pudding and placed it in the basket. Native
success first appeared at control 103 / decision 22, within reference 280;
all preceding flags were false and native termination ended the sole attempt.
No error, stop or retry occurred. Controlled simulation was 5.15 seconds;
recorded mailbox latency was 687.65 seconds, not provider inference accounting.
Record and full artifact checks passed: 208 native PNGs, 44 public-image matches
and two 104-frame 256×256 videos, with no flat frames and maximum codec MAE
2.31/3.30. Copies under `../rollouts/2026-09-07-task-coverage-case018/` retain:

- agentview: `0664eab10ebc6a214c184074a5bed59ba735548e47c1f0168b7807acdcfaca49`
- wrist: `255e4e03ece6a10d5929cc9bb5681607d1874fa171eebc284a6cb24472a31ef5`

Case019's orange-juice task ended with `policy:give_up` after 103 controls /
22 decisions: 21 accepted chunks and one stop. All native flags were false,
first success remains null, and there was no error or retry. It stopped before
reference 280 and the D200/cap1000 limits. Controlled simulation was 5.15 seconds;
mailbox latency was 681.01 seconds, not provider inference accounting. Record
and full artifact audits passed: 208 native PNGs, 44 public-image matches and
two 104-frame 256×256 videos, with no flat frames and maximum codec MAE 2.22/3.05.
Copies under `../rollouts/2026-09-07-task-coverage-case019/` retain the failure:

- agentview: `93e82d51a9f26f63c2793479c9abe316f3434a70589aca480c9a11eda02fbae9`
- wrist: `d4f80cd4a56e8bab56d833bb7729a2c5f8367d8acdd031ff2447992480498629`

The ten Object entries are now each closed once: eight native successes and
two preserved failures, without interface errors. Seven first successes were
within reference 280; one was later at control 362 under the existing expanded
budget. The two failures were voluntary stops before reference 280. These
one-state development observations are not a general model success-rate estimate
or a paired budget experiment. Spatial likewise retains eight successes and
two failures across its ten closed entries; neither suite was retried.

Case020 opened the middle cabinet drawer. Its first native success was control
83 / decision 17; all earlier flags were false and native termination ended the
attempt. Goal's reference horizon is 300, separate from the unchanged D200 /
prefix5 / cap1000 track. No error, stop or retry occurred. Controlled simulation
was 4.15 seconds at 20 Hz; mailbox latency was 515.84 seconds. Record and full
artifact audits passed: 168 native PNGs, 34 public-image matches and two
84-frame 256×256 videos with no flat frames and maximum codec MAE 2.37/3.42.
Copies under `../rollouts/2026-09-07-task-coverage-case020/` retain:

- agentview: `c9dfa003055ec04ab7c80931e036adac6874624a272ba0dd5f5848ac38e25a13`
- wrist: `dc67fc6b8e4c6cc8a3c70e6c1fdac00bffaeed9d0aa29db68a5bd22f70de0354`

Case021 placed the bowl on the stove. First native success appeared at control
112 / decision 25, within reference 300, and native termination ended the sole
attempt. All earlier flags were false; no error, stop or retry occurred.
Controlled simulation was 5.6 seconds at 20 Hz; mailbox latency was 720.20 seconds,
not verified provider inference accounting. Record and full artifact audits
passed: 226 native PNGs, 50 public-image matches and two 113-frame 256×256 videos,
with no flat frames and maximum codec MAE 2.16/3.54. Copies under
`../rollouts/2026-09-07-task-coverage-case021/` retain:

- agentview: `cc65b0ca1d767f5afa6844b751ce740eca1f1ec3254bbd3674adb9234c13a585`
- wrist: `f022f2058585a0df922d778c1ecd902ad0cd68c4c7b31594d14238b018244dc5`

The [independent Goal review](../../../../../project_readmes/reviews/2026-09-07-libero-goal-closed-review.md)
accepted closed cases020/021 within scope: all 42 accepted responses, 195
executed controls, 394 native PNGs, 84 public images and four complete videos,
plus native task/state/source and separate frozen-policy bindings. It confirms
case020's final five-action response executed only three actions before native
termination; proposed actions are not counted as executed controls. Four
in-memory action/termination tampering probes were rejected. No blocking finding
was identified; the review does not certify later cases or formal native parity.

Case022's wine-bottle task ended with `policy:give_up` after 436 controls /
89 decisions: 88 action chunks and one stop. All native success flags were
false, first success remains null, and no error or retry occurred. Reference
300 was exceeded under the unchanged D200/prefix5/cap1000 development track;
this does not redefine the reference horizon. Controlled simulation was
21.8 seconds at 20 Hz; mailbox latency was 2468.95 seconds, not provider inference
accounting. Record and full artifact audits passed: 874 native PNGs, 178 public-
image matches and two 437-frame 256×256 videos, with no flat frames and maximum
codec MAE 2.15/3.64. Copies under
`../rollouts/2026-09-07-task-coverage-case022/` preserve the native failure:

- agentview: `a047b676161d2753465bf2375701082e8490f1a7ea38a5344bd8193315ce97d0`
- wrist: `199978b3436f9dff4f436112d9d6bb9b427c7a8e3770f9b8e71e2bde7b0b2033`

Case023's top-drawer-and-bowl task also ended with `policy:give_up` after
436 controls / 89 decisions: 88 action chunks and one stop. These are its own
records, not a repeated case022 attempt. All native flags were false, first
success remains null, and no error or retry occurred. Reference 300 and the
predeclared development cap remain separate. Controlled simulation was
21.8 seconds; mailbox latency was 2873.21 seconds, not provider inference
accounting. Record and full artifact checks passed: 874 native PNGs, 178 exact
public-image matches and two 437-frame 256×256 videos, with no flat frames and
maximum codec MAE 2.37/3.53. Copies under
`../rollouts/2026-09-07-task-coverage-case023/` preserve the native failure:

- agentview: `194d346dd0d9de186f7e74b8209240b753a4a3b6ffea5f40c2f1024c61ff91bb`
- wrist: `3489652c373c8a77e98680123bbab33392d14f207183c2e7a0f9bf13d517032b`

Case024 placed the bowl on top of the cabinet. Native success first appeared
at control 179 / decision 37, within reference 300, and native termination
ended the sole attempt. Every earlier flag was false; no error, stop or retry
occurred. Controlled simulation was 8.95 seconds at 20 Hz; mailbox latency was
1082.26 seconds, not provider inference accounting. Record and full artifact
audits passed: 360 native PNGs, 74 public-image matches and two 180-frame 256×256
videos, with no flat frames and maximum codec MAE 2.08/3.17. Copies under
`../rollouts/2026-09-07-task-coverage-case024/` retain:

- agentview: `b95201bafc9e3b9b3ef87aa020e8989dbb07848bc419008d1a6542c4e0b0a7d4`
- wrist: `056cb10cfbc85b6aef4ffa07188eb5be5eb03306d55992ab3019f92cec88a41f`

Case026 placed the cream cheese in the bowl. Native success first appeared at
control 76 / decision 16, within reference 300; all earlier flags were false
and native termination ended the attempt. No error, stop or retry occurred.
Controlled simulation was 3.8 seconds at 20 Hz; mailbox latency was 558.15 seconds,
not provider inference accounting. Record and full artifact checks passed:
154 native PNGs, 32 public-image matches and two 77-frame 256×256 videos, with
no flat frames and maximum codec MAE 2.16/2.82. Copies under
`../rollouts/2026-09-07-task-coverage-case026/` retain:

- agentview: `3edc1ebd4bd01f1a91d6deea7e771b38a3b55cfa5f8bcd980544c95211141d23`
- wrist: `df653ee56b1957bd3714ee14b2ac4aa0237dd357a0abff90ad7d8d50b271fe26`

Case025, "push the plate to the front of the stove", closed with native success
false, 370 controls / 75 decisions, and
`policy:give_up`. First success is null.
Reference horizon remains 300; no error or retry occurred. Record and full
artifact checks passed: 742 native PNGs, 150 public-image matches and two
371-frame 256×256 videos with no flat frames. The closed archive is
`../rollouts/2026-09-07-task-coverage-case025/`. Video hashes:

- agentview: `77157f506639d3671266317daa6c1d1b431346e86c4a1758b3afcc3b9e7a37dc`
- wrist: `8f72eaad32f2f2554f6bf20a2e284f6d73c7d65e45aab6706f373e4c48d0f588`

Case027, "turn on the stove", closed with native success
true, 105 controls / 22 decisions, and
`environment:terminated`. First success is control 105 / decision 22.
Reference horizon remains 300; no error or retry occurred. Record and full
artifact checks passed: 212 native PNGs, 44 public-image matches and two
106-frame 256×256 videos with no flat frames. The closed archive is
`../rollouts/2026-09-07-task-coverage-case027/`. Video hashes:

- agentview: `c104c67fb07050e9d82af95957a7c8d4a14d64ef3d8200f3c7d51a87ddcf0ac3`
- wrist: `69dd0ef391fc329a494f71e45412490d76d48f76cb10d4697970a849015f642a`

Case028, "put the bowl on the plate", closed with native success
true, 198 controls / 40 decisions, and
`environment:terminated`. First success is control 198 / decision 40.
Reference horizon remains 300; no error or retry occurred. Record and full
artifact checks passed: 398 native PNGs, 80 public-image matches and two
199-frame 256×256 videos with no flat frames. The closed archive is
`../rollouts/2026-09-07-task-coverage-case028/`. Video hashes:

- agentview: `84f1e57e5814b59738375e6156525a3227f54ef5a2d33a072cd427720781c520`
- wrist: `ee81b0b3f3bbca622d393ac1f629c216612e349205634d13aafa7fb36814a089`

Case029, "put the wine bottle on the rack", closed with native success
false, 220 controls / 45 decisions, and
`policy:give_up`. First success is null.
Reference horizon remains 300; no error or retry occurred. Record and full
artifact checks passed: 442 native PNGs, 90 public-image matches and two
221-frame 256×256 videos with no flat frames. The closed archive is
`../rollouts/2026-09-07-task-coverage-case029/`. Video hashes:

- agentview: `d1e0854cda897fb59d87f884f67b6f819375fb41e342e1123a43dc25c697c830`
- wrist: `e8efdc68c0469382f8eb9df09dc14ecf2791aa47fca66dccf88b39199f007644`

Case030, "close the top drawer of the cabinet", closed with native false
after196 controls/41 decisions, including the final `policy:give_up` stop.
First success is null; all196 native step flags are false. Reference400 and
cap1000 remain unreached. Forty accepted action chunks preceded the stop;
no interface error or retry occurred. Record/full artifact checks passed:
394 native PNGs,82 exact public-image matches and two197-frame256×256 videos,
with no flat frames. The archive retains original video hashes:

- agentview: `239734865dab68c04389050bf0ddc7489701a8906b30ceebeb421fb3017ed47a`
- wrist: `5fcb6f9f63287b93a00a07d6312e3ea29c442f0c2b18d95e64ee4afd2bdced64`

Case030 is the first LIBERO use of the prospective canonical operator template
`POLICY_ACTOR_INSTRUCTIONS.txt`; the frozen public prompt and native package
are unchanged. This operator-cohort distinction does not relabel old attempts.

Case031, "close the top drawer of the cabinet and put the black bowl on top
of it", closed false at237 controls/51 decisions, including `policy:give_up`.
All237 native flags are false and first success remains null; reference400 and
cap1000 are unreached. No error or retry occurred. Record and full artifact
audits passed:476 native PNGs,102 exact public-image matches and two238-frame
256×256 videos, no flat frames. Archive hashes:

- agentview: `2cfaaa27f3ee4a8b2c9fac4150093f12e67a6d5132dcf3f6f7f2f0462e076022`
- wrist: `39b96a0ac6eb1c93e86518e7b9167c3d3f99fa4eb636d09ad4a74fd0de431f62`

Case032, "put the black bowl in the top drawer of the cabinet", closed false
at286 controls/59 decisions, including `policy:give_up`. All286 native flags
are false; first success is null and reference400/cap1000 remain unreached.
No interface error or retry occurred. Record/full artifact checks passed:
574 native PNGs,118 exact public-image matches and two287-frame256×256 videos,
no flat frames. Archive hashes:

- agentview: `3abb84789f66174ee72aa7ec1e637657a54ed2655bc13706d520631f3e4c2ff0`
- wrist: `9e58161ecfb1f9f2c3bee4f065cf72f68c5f696021411a7e6e366143c43d865a`

Case033, "put the butter at the back in the top drawer of the cabinet and close
it", reached first/final native success at control157/decision34 and stopped
with `environment:terminated`. Native reference400 and cap1000 are unreached;
only the final logged signal is true. No error or retry occurred. Record/full
artifact checks passed using the original auditor:316 native PNGs,68 public
image matches and two158-frame256x256 videos, no flat frames. Archive hashes:

- agentview: `453daa43c82f0c406373c73bb32c50874d1b0cdc82e34dd2723af45e56853c75`
- wrist: `c1c4966c48ab0fcb6c3c7cd481173325fc72a9c0ba5c66933e31e1d7aa5cd532`

Case034, LIBERO-90 task4, reached first/final native success at control381/
decision78 and stopped with `environment:terminated`. Only the final native
flag is true; H400 and cap1000 are unreached. Record/progress/export and the
accepted artifact CLI passed:764 native PNGs,156 public images and two382-frame
videos, no flat frames. No error or retry occurred. Original archive hashes:

- agentview: `b4d4cd95e17eb72ab3b57a723de3f38a646a7a537835c20fc49049a4cfd9a3d6`
- wrist: `1eb5a0a5bc4c943639906e3022f9eb2352840bef81585ec9e3cea3606a1cc1ca`

Case035, LIBERO-90 task5, closed false at263 controls/55 decisions,
`policy:give_up`, first success null. H400 and cap1000 are unreached.
Record/progress/export and accepted225b artifact checks passed:528 PNGs,
110 public images and two264-frame videos, no flat frames. Archive hashes:

- agentview: `dd708380364921119d2c70ab9b5684487a6013a59a75f384b21897f73be66ef3`
- wrist: `5e570fcc8d70ff39936fa48aaa83cecaf8ebbd9d0b585fd1ea9dd7650d9945d2`

Case036, LIBERO-90 task6, closed false at332 controls/69 decisions,
`policy:give_up`, first success null and no interface error. H400 and cap1000
are unreached. All four pinned postprocessors completed with exit0:666 native
PNGs,138 public images and two333-frame videos, no flat frames. Archive hashes:

- agentview: `955206a1470db1bfcd73d5ec2404b97702c4a360ac3917136a41434ae1caa810`
- wrist: `758e8363efc3db6c4966212469eb50a0c9e308cb41d1a4e94d9060f1cb15bdf0`

Case037, LIBERO-90 task7, reached first/final native success at control76/
decision16. All four pinned postprocessors completed with exit0:154 native PNGs,
32 public images and two77-frame videos, no flat frames. Original video hashes:

- agentview: `11a8e7b029b83a527b5133dc2540b19a8ef2e663518dabc15037170092371d21`
- wrist: `b1d75289333289619766fc4f56723aaa99e07421728367fc3d8c4b5f6c7dd8de`

Thirty-eight closed cases (25 native successes and thirteen failures) are not130-task
completion. Spatial, Object and Goal each retain all ten attempts; LIBERO is
paused aftercase037 and92 entries remain unattempted at this checkpoint. Its offline
postprocessors are pinned separately from the mutable development checkout;
the native frozen campaign remains unchanged. The
[independent artifact-tool review](../../../../../project_readmes/reviews/2026-09-07-coverage-artifact-tool-review.md)
verified case002 directly, identified and verified a fix for an offline
termination-label checker gap, and found no remaining blocker in its bounded
scope. It does not independently certify every other case or complete coverage.
Use the campaign `summarize` command for current coverage; preserve every
failure, error and unresolved attempt. Independent review of later closed
coverage and all remaining planned attempts are still outstanding.
