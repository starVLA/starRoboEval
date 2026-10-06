> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/SIMPLE/reports/2026-09-07-task-coverage.md` at source revision `29cb55d`;
> original SHA256: `5f5fe968e10e3f7242bfe7dc14859931ee2fb827a1ff1b4231dfdb8121a097e0`. Only documentation links were rebased.

# SIMPLE released12 one-attempt coverage — in progress

Scope: all12 released task identities, DR0 episode0, seed20260907. The frozen
continuation is `runs/simple-released12-coverage-20260907-001`, prepared from
clean commit50031b43f7b712fd224785f0d36c9c7285e283da. Campaign SHA256:
`123c3879c22a95708c76d7e55edadc33beadde3c6243cd23b3fa15181fa94b79`.

The ledger retains two original pilots as their sole attempts:

| Original task | Native success | Controls / decisions | First success |
| --- | --- | --- | --- |
| BendPickMP / AMO | false |295 /60 | null |
| OpenFaucetTeleop / SONIC | true |104 /21 |104 /21 |

Their original campaign, protocols, source/reset/artifact hashes, errors and
videos remain unchanged; see the [paired review](../../../../../project_readmes/reviews/2026-09-07-simple-closed-pilot-review.md).
Only10 new cases are executable. Case000, CloseDoorTeleop, closed once on
node-isolated eval with renderer4 and a fresh opaque policy actor:
native false,335 controls/68 decisions, first success null, `policy:give_up`.
All335 recorded native signals are false. Native reference1000 and cap1000
are unreached. The67 five-control responses were followed by one stop decision.
No interface error or retry occurred. Progress, closed record audit and original
video export completed. The
[independent closed review](../../../../../project_readmes/reviews/2026-09-07-simple-released12-first-closed-review.md)
verified336 native left PNGs,68 public RGB/qpos31 messages,335 private ticks and
two336-frame50fps videos. The private right video has no retained PNG sequence,
so its check is decoding/hash/PTS, not pixel parity. All596 native Python files,
five controller weights,108 used USD layers and eight entrypoints matched.
Startup's271 native stabilization controls remain separate from335 policy
controls. The native stateful door scorer updates its reward/dwell twice per
control; the worker preserves that upstream behavior without extra queries.

Important runtime caveat: the closed native log contains Lula/motion-generation
startup extension errors (`liblula_kinematics.so`, undefined `urdf::parseURDF`),
plus headless warnings. The selected SONIC/ONNX direct path has no inspected
Lula calls and completed the rollout; this is not proof of an error-free Isaac
installation or absence of every indirect effect. Keep the native log and
[external caveat annotation](2026-09-07-evidence-caveats.json); no package repair,
score replacement or retry occurred. Original video SHA256 values:

- left: `98b4a0f4ba0964568e9025f899c614d6f0cc50a76502af9c234e18777481761e`
- right: `b11b3c965347bb12803b523cf4760b0c7a363b29f488e0ebe4505631a9d9ddf3`

Case001, HandoverTeleop, closed false at140 controls/29 decisions, first
success null, `policy:give_up` and no interface errors. All140 native signals
are false;28 five-control responses precede the stop. Warmup270 is separate,
and native reference800/development cap1000 are unreached. Record audit,
progress and original export completed. Root adapted the preceding reviewed
case-specific checker, verifying all141 left PNGs,29 public RGB/qpos31 messages,
140 private ticks,596 native source fingerprints and both141-frame50Hz videos.
This is root verification, not a new independent native task review or generic
SIMPLE CLI support. Right video still lacks corresponding retained PNGs.
Initial/final left images show rendered task/robot geometry; no visual rescore
was performed. The closed worker log retains the same Lula startup errors;
the [new caveat overlay](2026-09-07-evidence-caveats-v2.json) includes cases0/1,
while the prior annotation/snapshot remain unchanged. No package repair/retry.
Root's private report is
`runs/simple-released12-case001-artifact-check-20260907.qkcGxY/native_artifact_audit.json`,
SHA256 `4d5448d4cb1a8c2552148f139757d8efaca44d6ba7b0fca9e1aa10780a13f89d`.
Original video hashes:

- left: `a13b1873183999e4ea6b947706de090676de66abf2128119058f450e7853396e`
- right: `b6e156d423ff14b781e2aa81b5fc03813a5e8bba0a565d48f407de71c9ef7233`

Case002, LocomotionPickBetweenTablesTeleop, closed false at425 controls/86
decisions, first success null, `policy:give_up`, no interface error. Warmup271
remains separate; native H1200 and cap1000 are unreached. The
[independent review](../../../../../project_readmes/reviews/2026-09-07-simple-locomotion-closed-review.md)
verified426 left PNGs,86 exact public RGB/qpos31/language messages,425 native
ticks and both426-frame50Hz videos. An earlier offline checker wrongly compared
raw language to normalized EpisodeSpec metadata: its failed scratch is preserved,
and the corrected source-bound audit passed without editing original records.
The review retains native double reward updates and asymmetric contact-predicate
precedence, Lula errors and an Isaac basket collision warning. The separate
MuJoCo collision path is source-verified, but its OBJ bytes were not retained
in native provenance; full loaded collision completeness is not established.
See the [versioned external caveats](2026-09-07-evidence-caveats-v3.json).
Original video hashes are:

- left: `eabfc16add49a07efaed428540d9c0c0dbe1285a5b5483b8b2a4c284f0e4b2cf`
- right: `d8f0b929075279cfae31634b917bade62cfe085b5376dc1af07e19c62e028f87`

Case003, OpenOvenTeleop, closed false at280 controls/57 decisions, including
the zero-control give-up after56 five-control responses. First success is null,
all280 native flags are false, no interface error occurred and warmup271 is
separate. Both native H1000 and cap1000 are unreached. All four pinned offline
postprocessors completed with exit0:281 left PNGs,57 public RGB/qpos31 messages,
280 private ticks and two281-frame50Hz videos agree, with no flat frames.
Right video has decode/hash/PTS checks only, not retained source-PNG parity.
The accepted generic checker and root's bounded closed-source/log inspection
are not a fresh independent native source/reset/asset review. Retain Lula
startup errors in the [v4 caveat overlay](2026-09-07-evidence-caveats-v4.json).
Accumulated returned reward0.75 is not a success rate and must not be compared
to the native0.5 threshold. The native stateful scorer updates twice per
control; peak/last returned reward is0.27 and all native success flags remain
false. No extra scorer call, repair or retry was made. Original video hashes:

- left: `d5d269339a0ce2cc9a7de03faf665a7ad22b7a194febc2ce3b67c82148f491cb`
- right: `71217b0ea06eb16adaa6a97051a4c1a60542c2297a822068d903e5ff533d4813`

Case004, OpenTrashCanTeleop, reached first/final native success at control223/
decision45, ending with native termination and no interface error. Only the
last native flag is true; native H800 and cap1000 remain unreached. All four
pinned postprocessors completed with exit0:224 left PNGs,45 public RGB/qpos31
messages,223 native ticks and two224-frame50Hz videos, no flat frames. The
private right video has decode/hash/PTS checks, not source-PNG parity. Retain
Lula startup errors in the [v5 caveat overlay](2026-09-07-evidence-caveats-v5.json).
These generic checks do not constitute a fresh independent native task review.
Original video hashes:

- left: `807628eb3de6b6f39b9ee38f79440b821542d1f6073de9d259c1f4381646dcac`
- right: `ea405c7001ed8f65cfabc7f5f306806af7e01051e7e9637315f230548d2bafa6`

Case005, PickAndPlaceAndHugContainerTeleop, ended with an infrastructure error:
SONIC did not stabilize within its native300-call warmup cap. The error was
raised by RSI's existing frozen initialization guard; upstream uses the same
loop but proceeds afterward without this fail-closed check. No policy decision
or policy control was executed; success and first success remain null, not false.
The native post-warmup count is300 and stabilized=false. No velocity trace is
retained to establish why the criterion failed or to attribute it to eval2.
Source-derived warmup physics time is6 seconds (300 steps ×4 ×0.005s), not
measured wall time; the whole episode duration248.075s includes other setup.
Keep Lula startup errors and the basket collision warning in the
[v6 overlay](2026-09-07-evidence-caveats-v6.json). One post-warmup PNG and two
one-frame50Hz videos are retained, not a warmup trajectory or public actor input.
The original shell chain stopped on native exit1. Closed-only progress/export/
record checks subsequently passed without native execution or result edits;
the generic completed-episode mailbox artifact checker does not support this
error. The [independent closed review](../../../../../project_readmes/reviews/2026-09-07-simple-warmup-error-review.md)
verified the source-bound warmup semantics and both one-frame videos, without
establishing cause or node attribution. The mailbox remainedidle because reset failed before Policy.act; a generic
coordinator terminal notice stopped its waiting actor, which submitted0 decisions.
Original videos:

- left: `8b8d5ad12d074d7150ff43e7ff4ceafb37c73f3f92e5ea557749331f7a16df77`
- right: `69c08744784566d4daa1803ef19dfcba2c7979bd228a133a5f1f1a6b8ad6df82`

Case006, PushOfficeChairTeleop, closed false at265 controls/54 decisions,
including one zero-control give-up after53 five-control responses. First
success is null, all265 native flags are false and no interface error occurred.
Warmup271/stabilized=true is separate; native H800 and cap1000 are unreached.
All four pinned postprocessors passed:266 left PNGs,54 public RGB/qpos31
messages,265 native ticks and two266-frame50Hz videos, no flat frames. Right
video has decode/hash/PTS only, not retained source-PNG parity. Preserve Lula
startup errors and render warnings in the [v7 overlay](2026-09-07-evidence-caveats-v7.json).
The selected scene is already hssd:scene3, with no alias rewrite. This is
retained-artifact consistency and bounded root log/provenance inspection, not
a fresh independent native task/source/asset review. Original video hashes:

- left: `97cda5057950dfd050a2d51696ebb9e1cef4a9e5fe5c30e647e93f1dda17ea02`
- right: `62f9ef2fa361a041d1ee06dce5472361831a0c74aca142e72847cf64b8e2e916`

Case007 TabletopGraspMP closed native true at control8/decision2, also the
first success, with environment termination and no interface error. All four
pinned postprocessors passed:9 head-left PNGs,2 public observations,8 native
ticks and four9-frame50Hz videos. Other cameras lack retained PNG parity.
The [independent closed review](../../../../../project_readmes/reviews/2026-09-07-simple-tabletop-grasp-closed-review.md)
confirms the pinned height-only predicate: nominal1.8cm increase, not secure
contact or sustained grasp. Its baseline is initialized during60 native warmup
steps and is not cleared when the wrapper resets step/success. Initial/warmup
score history is not retained; policy-only causal lift is not established.
Both original responses passed the frozen strict CPU parser. Preserve original
true8/2 and startup/collision warnings in the [v8 overlay](2026-09-07-evidence-caveats-v8.json),
without extra scoring, retry or a changed grasp predicate.

Case008 XMoveBendPickTeleop closed false195 controls/40 decisions, first
successnull, policy give-up and no interface error. All four pinned tools
passed:196 head-left PNGs,40 public observations,195 ticks and two196-frame
50Hz videos. Right camera lacks PNG parity. The
[independent review](../../../../../project_readmes/reviews/2026-09-07-simple-xmove-bend-closed-review.md)
verifies all40 original responses against the frozen strict SONIC parser and
the native height-only success predicate (nominal8cm). Warmup271 is separate;
intermediate warmup score history is unavailable. Selected metadata is marked
train, not held-out test. Preserve native false/no error and runtime/source
limitations in the [v9 overlay](2026-09-07-evidence-caveats-v9.json).
Original video hashes:

- left: `c21eddad407c1b2732a3bf1e11c768fcffab38e9d75558adc48162d63ecab286`
- right: `f228e45a38aae217844ae8e13babf719fdcac5af3adf0377d572226a650f3373`

Case009 XMovePickTeleop closed native false at315 controls/64 decisions,
first successnull, policy give-up and no interface error. All four pinned
postprocessors passed:316 head-left PNGs,64 public observations,315 ticks and
two316-frame50Hz videos. Right camera has decode/hash/timestamps only.
The [independent native/source/parser review](../../../../../project_readmes/reviews/2026-09-07-simple-xmove-pick-closed-review.md)
verifies all64 original responses and315 executed actions against the frozen
strict parser/records, all31 encoders and public PNGs, full videos and archive
byte equality. Actual XMovePick success is nominal9cm lift, not XMoveBendPick's
8cm. Saved DR state selects the cracker-box/bend instruction despite class
defaults; preserve that released train/DR0ep0 identity. Warmup271 establishes
the task baseline, with no intermediate score history. Runtime warnings and
nonrecursive asset evidence remain in the [v10 overlay](2026-09-07-evidence-caveats-v10.json),
which preserves all nine prior entries. No secure-grasp, causal or historical
parity inference is supported. Original video hashes:

- left: `74f330921c6a448197d4688c1a88d66f6292912a58a27c2f0cfe9687b21197f8`
- right: `e631f22da63813b04ec0c0aee80685fdcf4e90d4cc1916619630a61cbe6a98c0`

Coverage retains all12 terminal attempts (three native successes,eight failures,
one infrastructure error), with0 active and0 unattempted. Full-ledger
checkpoint011 validates zero invalid rows; all original pilot identities and
the case005 warmup error remain. This closes one-attempt task coverage, not all
variants or a formal provider/model score. No further SIMPLE task is launched.
Each fresh isolated actor ACKed before its sole frozen launch on idle
eval2 GPU4, with the pinned four-tool postchain. Case005 was the
first attempt on dedicated eval2; there is no retry or warmup-cap change.
The node change preserves the shared frozen campaign/source/episode and offline
bundle. Static preflight confirmed the same Python binary SHA256 and driver,
shared environment/assets, and all GPU contexts idle before a fresh actor ACK
and the firstcase005 launch. It is not a native node-parity certification.
No SIMPLE task is retried or canceled. Case003's first actor-creation
requests hit the conversation thread limit before native launch. After old
actors closed, a fresh actor was created successfully and ACKed; node GPU
isolation was checked before the sole native launch. No reviewer context was
reused. After case003 closed, case004 also received a fresh actor, ACK and
node-idle check before its sole launch. Offline postprocessing uses a separately pinned four-tool bundle,
including the independently accepted generic SIMPLE artifact checker. Native
frozen sources and original cases are unchanged. Use the frozen coordinator's `summarize` for execution counts and
the [full-ledger reporter](../../../../../examples/simBenchmarks/TASK_COVERAGE.md#full-continuation-coverage-snapshots)
for the complete12-entry view; do not merge old/new protocols into a score.

New attempts use the explicit released12 protocol, at most200 decisions,
at most5 native controls per accepted response and a separate1000-control cap.
The [inventory and protocol](../../../../../examples/simBenchmarks/SIMPLE/RELEASED_TASK_SCOPE.md) preserve task-specific
native horizons, native AMO/SONIC controllers and fixed reset identities. A stop
counts as a decision but performs no control. Success comes only from the
existing native return; first-success timing is recorded without another scorer.

Actor access is restricted procedurally to the public mailbox's current
RGB/language/qpos31 contract. Coordinator, worker, source and prior evidence
stay evaluator-private. All new actors receive the canonical operator template;
provider/model identity, usage and OS isolation are not independently attested.

The [carry-forward review](../../../../../project_readmes/reviews/2026-09-07-campaign-carry-forward-review.md)
accepts the corrected offline exclusion/integrity guards, not native coverage.
The coordinator and helpers execute from this campaign's frozen cwd/PYTHONPATH.
The complete ledger denominator is12; execution-only counts use10 and must not
be mislabeled as full coverage. Full-ledger score aggregation is not implemented;
old/new protocols remain separate rather than a homogeneous leaderboard score.
The external full-ledger coverage tool is independently reviewed; it does not
apply the separate native-log annotation automatically or certify clean evidence.

Export each closed run's original videos under
`../rollouts/2026-09-07-released12-caseNNN/`, with generated archives ignored by
Git. Preserve failures, errors and permanent claims; no reset/retry for success.
Closed-run record checks, full video/transport checks and independent native
review are separate acceptance steps, not replacements for the original result.
