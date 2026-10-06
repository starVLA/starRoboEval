> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/Robocasa_365/reports/2026-09-07-task-coverage.md` at source revision `29cb55d`;
> original SHA256: `9ac8074dd48e74fcd74f916e6cc2ae897608ac990eaacc5ff63bd193fd6313f8`. Only documentation links were rebased.

# RoboCasa target50 one-attempt coverage — in progress

Scope: native TARGET_TASKS in order,18 atomic_seen +16 composite_seen +16
composite_unseen =50 distinct tasks, one fixed reset each, seed20260907.
The benchmark name does not mean365 attempts in this campaign. Frozen manifest:
`runs/robocasa365-target50-coverage-20260907-001`, prepared from clean commit
50031b43f7b712fd224785f0d36c9c7285e283da, SHA256
`3071dbc826b220387f9fdaeeb08e3edda30a418519984ae7a4822fd49d1e6fd5`.

Latest full-ledger checkpoint019, collected at
`2026-09-07T16:39:16.030272+00:00` (September8 Asia/Shanghai), retains21/50
terminal (2 native true,19 native false),0 active,29 unattempted and0
invalid/error rows. Cases017 GetToastedBread and018 KettleBoiling both closed
native false without episode errors and passed independent review, at480/97
and146/32 controls/decisions respectively. **RoboCasa365 is now user-paused;
do not launch case019 or retry a closed task.** Earlier launch/snapshot sections
below are historical. Checkpoint019 is a report number, not a new attempt.

Snapshot: `runs/robocasa365-ledger-checkpoint-20260908-019/coverage.json`, SHA256
`aa5df1102c253959525926f03c870951ca96d37e1077d3b4a3e0ad1c9ed84473`;
CSV SHA256 `e26496dbc553807a7a99a44c0d5d21a74512157abbcae971e5090fa4bc0d56bc`.
All50 identities and both carry-forward records were checked with the unchanged
accepted reporter/frozen helpers. Only selection indices19/20 changed from
checkpoint018. See the complete [task checklist](../TASK_CHECKLIST.md),
[case017 review](../../../../../project_readmes/reviews/2026-09-08-casa017-closed-review.md)
and [case018 review](../../../../../project_readmes/reviews/2026-09-08-casa018-closed-review.md).

Two atomic_seen tasks retain their original pilots as sole attempts:

| Original task | Native target ordinal | Native success | Controls / decisions | First success |
| --- | ---: | --- | --- | --- |
| OpenDrawer |6 | false |328 /67 | null |
| NavigateKitchen |4 | true |125 /25 |125 /25 |

Their original protocols, results, reset/source/artifact hashes and videos stay
unchanged; see the [paired review](../../../../../project_readmes/reviews/2026-09-07-robocasa365-closed-pilot-review.md).
The continuation excludes both native identities and executes only48 new cases.
Case000, CloseBlenderLid, closed once on eval_ning GPU3 with a fresh opaque
policy actor: native false,180 controls/37 decisions, first success null,
`policy:give_up`, no interface errors. All180 native flags are false. The36
five-control responses were followed by one stop decision. Native H900 and
cap1000 are unreached. At that closure, coverage retained3 closed tasks (one
original success,two failures) and47 unattempted; the full scope remains50.

The progress report, record audit and video archive completed. Root's separate
closed-only checks with the existing PNG/video helpers verified543 native PNGs,
111 exact public-image matches and three181-frame256×256 videos, no flat frames;
maximum same-frame codec MAE is3.158/255. Public fields, prompt/specs/budgets,
scheduled input and accepted-response bindings matched. Root's initial/final
left-camera image inspections found visible colored scene/robot/task geometry;
these qualitative checks do not replace native scoring. The
[independent closed review](../../../../../project_readmes/reviews/2026-09-07-robocasa-target50-first-closed-review.md)
verified all37 responses with the frozen parser,180 native action pairs, all
images/video timestamps, initial XML/raw-array hashes and a rebuilt245-file
used-asset closure (95,538,571 bytes). No blocking inconsistency was found in
this one-task scope. The failure remains unchanged; this is not full native
target50 validation. Case001's subsequent sole attempt is recorded below.
Original case000 video hashes:

- left: `9e6ad40ca37fb601a1bce82ef6f1e5e6217781fb56c386d45d21d8abb69a12c4`
- right: `364a5e8da84db707fea1e5fb91274eb6ccfcaff3ce02e416491502af4f39f926`
- wrist: `08eb03ad385a18638eb637f7eec79bfa3bd1ef726d74428199e909cf8f2fac63`

Case001's initial launch was rejected before claim/reset: an extra generated
`record_progress.cpython-311.pyc` violated the frozen supplemental inventory.
No expected source file changed. The cache was retained outside the frozen tree
in `runs/casa-frozen-cache-quarantine-20260907.3iNYLH/`; frozen/carry-forward
verification then passed and case001 was confirmed unclaimed before launch.
This did not retry an episode, relax verification or alter native results.
All subsequent inspection commands must disable bytecode writing as launches do.

Case001, CloseFridge, closed false at245 controls/50 decisions, first success
null, `policy:give_up` and no interface errors. All245 native signals are false;
49 five-control responses precede the stop. H900 and cap1000 are unreached.
Record audit, progress and original video export completed. The independently
reviewed [artifact CLI extension](../../../../../project_readmes/reviews/2026-09-07-robocasa-artifact-tool-review.md)
then verified245 native control pairs,738 PNGs,150 public-image matches and
three246-frame20Hz videos with exact presentation timestamps and no flat frames.
This is retained artifact consistency, not a separate new native source/reset/
asset/response-parser review. Original failure and video hashes remain:

- left: `5278bc5e59abc96872c0725f180ca175167d3fd701bb45b339cd63540b6f7dba`
- right: `475e7ccb5e64daf9002ae9f6bc444665b0e535316ed2dde7ba3e678f447843f5`
- wrist: `2ab500c8927ad459dfa768c3f28acb39d0a3e2e16b3aaa527f01651d9a672717`

Case002, CloseToasterOvenDoor, closed false at198 controls/41 decisions,
first success null, `policy:give_up`, no interface error. Native H450 and
cap1000 are unreached. Record/progress/export and the accepted artifact CLI
passed:198 native control pairs,597 PNGs,123 public images and three199-frame
20Hz videos, all presentation timestamps checked and no flat frames. This
is artifact consistency, not a new independent native asset/reset review.
Original archived video hashes:

- left: `12f738560d0420149a2848cd4049d99474d5a50797b43613c4f55dfc34091dd9`
- right: `8c511aab365bca014771341544568d2b8c88ac864acf5c134f9a8917815870f8`
- wrist: `273b552fe5cabb4396c1e2904aaf719bb9c13a79b42609e4bcf73878c739378a`

Case003, CoffeeSetupMug, closed false at176 controls/37 decisions,
`policy:give_up`, first success null and no native/interface error. H600 and
cap1000 are unreached. Progress, original video export and record audit finished.
Root's production offline-tool deployment overlapped the first full artifact
check, which correctly rejected its own changing source hash; that postchain
exit1 is separate from native coordinator return0. No original artifact report
was written by the rejected check. Keep the operator incident receipt at
`runs/casa003-tool-cutover-recovery-20260907.cnMPVE/incident.json`.

The fixed accepted225b tool then checked this same closed run into new
`case-003/mailbox_artifact_audit_after_tool_cutover.json`:176 native pairs,
531 PNGs,111 public images and three177-frame20Hz videos, no flat frames.
The [independent cutover review](../../../../../project_readmes/reviews/2026-09-07-casa003-offline-cutover-review.md)
verified that recovery and the unchanged original records/archive. No native
retry, rescore or error reclassification occurred. Original video hashes:

- left: `7b9de844467d402ecab3b74fd9c40e162ec93090fb12f4b3dda27c3657bd936a`
- right: `cac66e8fb5382f71d5c477c8a34f5fb235fa7ecfa6f09eb6ddea8a34568b87fe`
- wrist: `fe69c4d0cb49be1ed1b521eb42706c072285c67dea2e71d9f4e555667a65d89d`

Case004, OpenCabinet, closed false at90 controls/19 decisions,
`policy:give_up`, first success null and no interface error. Its18 five-control
responses preceded a zero-control stop. Native H1050 and cap1000 are unreached;
the development cap remains a shortened reference track, despite early stop.
All four pinned postprocessors completed cleanly:90 native pairs,273 PNGs,
57 public-image matches and three91-frame20Hz videos, no flat frames. These
artifact checks do not constitute a new independent native source/asset review.
Original video hashes:

- left: `1fa9ded160f524c9c633fabd29f716d890d13637a8900ea672b0cceaf85d8b49`
- right: `290207abfca4129f24b11be37403a8f9a9616f61de56e1633da65abfa86a7b07`
- wrist: `30f63e46f1d29f33c49479648f674550768dace959c35c4df7f4cd47cd47db43`

Case005, OpenStandMixerHead, closed false at149 controls/32 decisions,
`policy:give_up`, first success null and no interface error. Native H450 and
cap1000 are unreached. All four pinned postprocessors completed with exit0:
149 native control pairs,450 PNGs,96 public-image matches and three150-frame
20Hz videos, no flat frames. Retained-artifact consistency is not a new
independent native source/reset/asset review. Original video hashes:

- left: `5964b1132bdfdcc0e29f1a8e63efa8e1cbe3a0d7fd45a73b394758f260b164fa`
- right: `69dfd901826c82167f9d6aefa7a1b6f5b3d91abc4e671f28380df3209681ed7b`
- wrist: `7fde238616481521b8a4aa12e6694553771f83d5fce7a42ffeeab1e994eafe0c`

Case006, PickPlaceCounterToCabinet, closed false at210 controls/43 decisions,
`policy:give_up`, first success null and no interface error. Native H750 and
cap1000 are unreached. All four pinned postprocessors completed with exit0:
210 native pairs,633 PNGs,129 public images and three211-frame20Hz videos,
no flat frames. This is artifact consistency, not a new native asset review.
Original video hashes:

- left: `2e4bfa5e6bf50d73d40ef67dad79e089cc0b402349c916ebbce168a199bdb2ba`
- right: `a993137157d5fc49e9e1fde2077b2e38d602f460c39e527f3f4e36f7b226f558`
- wrist: `48093411a7b1c5ec30fc761a7ef4bdb60aabef81547aa4df10a5fafaf97b9989`

Case007, PickPlaceCounterToStove, reached first/final native success at398
controls/81 decisions, ending by native termination with no interface error.
Native H600 and cap1000 remain unreached. All four pinned postprocessors
completed with exit0:398 native pairs,1197 PNGs,243 public images and three
399-frame20Hz videos, no flat frames. This is retained-artifact consistency,
not a fresh independent native source/asset review. Original video hashes:

- left: `8efccd3302289cdc4592790044d73b408097cb2f847520e3c8cce029758c51fe`
- right: `782161b7462026c954362b7ecf8975976fc2aaf60ab45bc8e20172a33a1c15de`
- wrist: `d1d2c252485021988793c25007fbb378d19d6365df506b1d554818eba2b2a005`

Case008 PickPlaceDrawerToCounter closed native false at171 controls/37
decisions, policy give-up, first successnull and no interface error. Native
H750 and cap1000 remain unreached. All four pinned postprocessors passed:
171 native pairs,516 PNGs,111 public images and three172-frame20Hz videos,
no flat frames. This is retained-artifact consistency, not a fresh independent
native source/asset review. Original video hashes:

- left: `79fd425bbceee6b3eb31e734d13b6dd12fd2f865ce0fdacebc4a30493cf8e732`
- right: `817aa5a70009ba2ee1b26f4e1b4a2dd3d84609567eef1a0648d25a6f86c80eea`
- wrist: `3bec0f922514fc3a9c95f963ee76bb38d17dfbb5525a75a20f8f6f7183cf70e4`

Case009 PickPlaceSinkToCounter closed native false at266 controls/55
decisions, policy give-up, first successnull and no interface error. H900 and
cap1000 remain unreached. All four pinned postprocessors passed:266 native
pairs,801 PNGs,165 public images and three267-frame20Hz videos, no flat
frames. This verifies retained-artifact consistency, not a fresh independent
native task/source/asset review. Original video hashes:

- left: `9f2d4918fb39679b7ac7388add71ee7e8db427856b91ededd5ff5d718f7d8adb`
- right: `70a5e370848ae3b00d08b180a2de0c23d7634c62dc4882f966f2287458cb9324`
- wrist: `7f3268158f0d5fc19296a38c0a7d44d0199715e0a72373336c6e4db4ad87f762`

Case010 PickPlaceToasterToCounter closed native false at189 controls/40
decisions, policy give-up, first successnull and no interface error. H600 and
cap1000 remain unreached. All four pinned postprocessors passed:189 native
pairs,570 PNGs,120 public images and three190-frame20Hz videos, no flat
frames. This verifies retained-artifact consistency, not a fresh independent
native task/source/asset review. Original video hashes:

- left: `8454594dae7c5665df86e81e96f3fd8d81162eaed5aabccb41a191f596177826`
- right: `9a20ddff2d45ada46cd8091a4dda41774cf0e6662dbf37e531b527e4506a43f4`
- wrist: `6163d275cfecd931852116621ee8f546eff6e30baa99a491407dc3e44a0fbcc3`

Current snapshot013 retains13 closed tasks (two native successes,eleven
failures), two active and35 unattempted; zero invalid ledger rows. Case011
SlideDishwasherRack runs on eval_ning GPU3 and case012 TurnOffStove on eval
GPU3, each with a fresh isolated actor ACK before its sole claim/launch. Native
reference H450/H750 differ from cap1000. Static eval preflight confirmed idle
compute contexts and the same pinned RoboCasa/RoboSuite revisions and Python
SHA as eval_ning. Frozen coordinator/coverage-helper inspection confirmed
case-local writes and child process groups, exclusive claims, and read-only
carry-forward validation. The two jobs do not share an actor, mailbox or output
directory. This is scheduling isolation, not a new native asset/node parity
certification. Earlier
actor-creation requests reached the conversation thread limit before creation
or claim. A fresh actor subsequently ACKed before its sole frozen launch on
eval_ning GPU3, with the same pinned four-tool postchain. Case010 native H600 and
cap1000 remain distinct. No reset/retry or task replacement occurred; only
unclaimed identities continue.

After that snapshot, case011 SlideDishwasherRack closed native false at230
controls/47 decisions, first successnull, policy give-up and no interface error.
All four pinned postprocessors passed:230 native pairs,693 PNGs,141 public
images and three231-frame20Hz videos, no flat frames. Retained-artifact
consistency is not fresh native task/source/asset review. Original video hashes:

- left: `ffb0404f1bba12615ef099eb42358cf26eca6e32c818c2d278164e825f9c4247`
- right: `e302f785f143fbbe41faa993cbe0411cc544c913593a6b0aad72548f973710ff`
- wrist: `ede53e0fdb7f1ef5668c02f0d61e20a03725a7f726b72a51f0d96ea9fcb23583`

This raises terminal coverage to14/50 (2 true/12 false). Case013
TurnOnElectricKettle then launched once on idle eval_ning GPU3 after fresh
actor ACK, in parallel with case012 on eval GPU3. Its native H450 differs
from cap1000. Earlier reviewed snapshots remain dated evidence, not live status.

Case012 TurnOffStove closed native false at318 controls/66 decisions;
case013 TurnOnElectricKettle closed native false at33 controls/8 decisions.
Both stopped by policy give-up, with null first success and no interface error.
Native reference horizons750/450 and the1000-control cap were unreached.
All four fixed-tool postprocessors passed. Case012 has318 native pairs,
957 native PNGs,198 public-image matches and three319-frame20Hz videos;
case013 has33 pairs,102 PNGs,24 public-image matches and three34-frame20Hz
videos. Full-video checks found no flat frames. These are retained-artifact
consistency checks, not new independent native source/reset/asset reviews.
The six archived original videos were freshly rehashed against those reports:

| Case | Camera | Original/archive SHA256 |
| --- | --- | --- |
| 012 | left | `437f0ce90a0ec53e8301b7878471a2c8bdabd7ffda7373cf9e824880bca2df5e` |
| 012 | right | `2772b603eda03ea6ac3c136c583ea25de346a9b14e2171e8c105ed7ec158b26f` |
| 012 | wrist | `4fa39ba8975624066ea2465f22a9a611bd8beb05d57a597c52704bfdfba1d4ae` |
| 013 | left | `de8a48291540b818b942aeb62148d9dd2e7b101cf98eda1c7452f33dd595ad81` |
| 013 | right | `6e542f592e2658788dab1482feee96561c455f4c7ab8fa031035e9315951ab55` |
| 013 | wrist | `845a209fda013a8f157f45849d1d3bbd45d92032371e92e7b7c03043491fe4c0` |

Full-ledger snapshot015 now retains16 terminal tasks (2 native true/14 false),
one claimed without terminal outcome and33 unattempted, with zero invalid rows.
SHA256 `fa87187d096ac9db2abbfc0dbc82b3c3d775c6939d0b76ecd0da254a769ebdfd`.
The [task checklist](../TASK_CHECKLIST.md) is updated to that dated snapshot.
Case014 TurnOnMicrowave is independently confirmed live by its original
process handle on eval_ning GPU3; an active ledger label alone is not liveness
evidence. No subsequent task is claimed by this documentation update.

Case014 TurnOnMicrowave subsequently closed native false at267 controls/56
decisions, first successnull, policy give-up and no interface error. All four
pinned postprocessors passed, checking267 native pairs,804 PNGs,168 public-image
matches and three268-frame20Hz videos with no flat frames. Archive video hashes
were freshly verified: left`abbab0670ae806f5bb28e58df4ce1080621a1bf5fb818a16238653b6aaac7802`,
right`2b211b42416d5077430179813164e0b4369c176d0100da98df706e43769f9ca4`,
wrist`7341a6ad83e96de5ffb639bf64ddc99bb8d2a4c45924197ba264606f26b3a226`.
These are retained-artifact checks, not a new independent native source review.

Snapshot016 now retains17/50 terminal (2 true/15 false),2 claimed and31
unattempted, with zero invalid rows; SHA256
`1a032eded5506f91813683fa0c1f805229152f8703138c685f9a1ccffa594cb8`.
Case015 TurnOnSinkFaucet runs on eval GPU3 and case016 DeliverStraw on
eval_ning GPU3, each after fresh isolated actor ACK and idle-node checks.
Both original process handles are live. DeliverStraw is the first composite_seen
entry: its native referenceH2550 exceeds the frozen1000-control cap, so this
remains the explicitly shortened development track. Case015 referenceH600
also remains distinct from the same cap. No task replacement or retry occurred.

Cases015 and016 have subsequently closed once, both native false, first success
null, policy give-up and no interface error: TurnOnSinkFaucet366 controls/75
decisions, DeliverStraw205/42. All four fixed postprocessors passed for each.
Case015 has366 native pairs,1101 native PNGs,225 public-image matches and three
367-frame20Hz videos; case016 has205 pairs,618 PNGs,126 public-image matches
and three206-frame20Hz videos. All presentation timestamps were checked and no
flat frames found. The archive bytes were freshly matched to retained hashes:

| Case | Camera | Original/archive SHA256 |
| --- | --- | --- |
| 015 | left | `b2939f1436266e2b2358912af21c307b2b4346bec9d5165d808be3ebce12bf7a` |
| 015 | right | `ccd7ed5dc1b2046939eaee53930a18d37d9507ae6c342dcfe65e614c01bf22f3` |
| 015 | wrist | `4b8c13ab097b91625cd504ecd6ac65755e2b73b904c020a592b7bb06152192d0` |
| 016 | left | `cace4efaf306159644dd295ec74dbec65279484f54122aa0a672e7df54ab51b4` |
| 016 | right | `1e32adc69ca4b4dc6341d01f17e7aee918d841ef3bb45d65a2fe1d9aba881e06` |
| 016 | wrist | `b20103be15c836d950736931f6e69c3fa6d872939d9967926588508ce726fc0a` |

Snapshot017 validates19/50 terminal (2 true/17 false),0 claimed,31 unattempted
and0 invalid rows; SHA256
`a1159e986288d48caaf1f53c19680b79c1e9047ef54e7c6e625883a01a53b636`.
All18 atomic_seen attempts are closed; DeliverStraw is the first closed
composite_seen entry. At checkpoint017 the remaining31 tasks stayed in scope
while launches were held for the user's Dojo-first priority. Generic artifact checks do not certify
native source/reset/asset or official-horizon parity. The separate
[first-composite closed review](../../../../../project_readmes/reviews/2026-09-07-casa-first-composite-closed-review.md)
accepts the retained DeliverStraw failed development attempt: all42 original
responses pass the exact trusted parser and typed binding,48 recorded source
hashes and319 retained asset rows match. It does not rebuild the asset closure,
execute the native scorer or establish historical runtime/provider parity.
The native success predicate combines contact and planar/gripper distances;
it is not an independent geometric proof of straw insertion. Policy give-up
at205 controls precedes both caps, so the shortened horizon is not the observed
stop cause and a longer-budget success cannot be inferred. No retry occurred.

## Checkpoint018: resumed target50 queue

After the accepted closed Dojo round2 pair, only the next two previously
unclaimed identities resumed: case017 GetToastedBread on eval (coordinator
launch handle14934), and case018 KettleBoiling on eval_ning (handle40208).
The coordinator reported fresh isolated actor ACKs before both launches;
the ledger does not independently attest process liveness or actor isolation.
No prior closed task was retried and the frozen task selection/budgets are
unchanged. Dojo's unsuccessful native outcomes remain separate from this queue.

New non-overwriting snapshot:
`runs/robocasa365-ledger-checkpoint-20260907-018/coverage.json`, SHA256
`d5101b4ca86b273eaf095e1ea24d78584e130152ad55002f5642be2c3aa1feb7`;
`tasks.csv` SHA256
`d9d95974a971de0d273ccc6f243a28df42961791310f8f16e6ab8a4966155a53`.
It contains all50 rows in frozen order:18 atomic_seen closed (2 true/16 false),
16 composite_seen (1 closed false,2 claimed,13 unattempted), and16
composite_unseen unattempted. Totals remain19 terminal,2 true/17 false,
2 claimed,29 unattempted,0 invalid rows and0 infrastructure/policy errors.

The accepted external full-ledger reporter ran from this campaign's exact
frozen cwd/PYTHONPATH with bytecode writing disabled. Campaign digest,
frozen package/supplemental sources and all1499 carry-forward bound files
were revalidated by the accepted guards. Their canonical file-map SHA remains
`64470af2a6a2a1959cd14bfe405812325fc95d9d3acf06d989f47e8e768b38a2`.
Reporter/reader/helper hashes match checkpoint017, including reporter
`45d51b0ee3869bda2553a8f85e37eaa95fab472890ee635181d1f41f2695d63e`,
frozen coordinator `13ee85c6537ded9dc158741129aa67829096e042eef9861a30ddaec77f79bbc4`
and continuation helper `ca4722b627f9dbe79b43f7a90d2bf2fe4d900822de83e3ec551501a5ce7acb00`.
Independent row comparison with017 found only selection indices19/20 changed
from unattempted to claimed; all other row values, pilot source identities,
protocols, counts, successes and nulls remain unchanged.

An additional Python audit hook prohibited file opens inside both active cases
and all policy mailboxes, and prohibited native simulator/controller imports;
the snapshot completed with those guards intact. Directory/outcome existence
checks determine claimed state, not active episode/event/observation reads.
The two active rows retain null controls, decisions, final success and first
success. This non-atomic dated snapshot is not a live scheduler, new native
validation or model leaderboard, and cannot authorize duplicate claims.

## Continuing evaluation constraints

The explicit target50 development protocol permits at most200 decisions,
at most5 native controls per response and a separate1000-control safety cap.
Native reference horizons span450–4350;33 exceed this cap. This is not native
horizon parity or the full variant product. See the [evaluation protocol](../../../../../examples/simBenchmarks/Robocasa_365/EVALUATION_PROTOCOL.md)
for the target groups, inventory hashes, RGB/action interface and budget details.
All stops count as decisions without controls. Retain actual controls/decisions,
first native success, final native score, stop cause, errors and original videos.

The [carry-forward review](../../../../../project_readmes/reviews/2026-09-07-campaign-carry-forward-review.md)
accepts corrected offline exclusion/integrity guards, not48 executed tasks.
The coordinator and helpers run from this campaign's frozen cwd/PYTHONPATH;
carried evidence is revalidated before every new claim. Only policy-shaped
public observations/actions reach actors; no native handles, GT, scoring or
reset metadata. Provider/model identity and usage remain unknown, and isolation
is procedural rather than an OS-enforced sandbox.

The full ledger denominator is50, but coordinator execution counts describe48.
Full-ledger score aggregation is not implemented; do not call48 the benchmark
size or merge original pilot protocols into a homogeneous new formal score.
Continue only unclaimed identities and preserve failed/error claims without retry.

Archive closed original videos under
`../rollouts/2026-09-07-target50-caseNNN/`; all generated artifacts remain
Git-ignored. Record audit, full video/transport checks and independent native
review remain distinct from native capability success and from this launch log.
