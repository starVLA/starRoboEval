# GPT6Astra on RoboDojo

This directory contains publishable GPT6Astra results for RoboDojo. Benchmark
definitions, native scoring and the SIM service remain under
`examples/simBenchmarks/RoboDojo/`; model decisions and results live here.

## Latest accepted panel

- Task: `classify_objects` — category sorting.
- Schedule: standard layouts 0–4, one attempt per layout, no automatic retry.
- Interface: `codex-direct/v2` over the benchmark SIM service, with public RGB,
  measured robot state and robot execution feedback.
- Limit: 1100 native controls per layout.
- Outcome: **3/5 native successes (60%)**, two native failures, zero
  infrastructure errors.
- Successful layouts: 0, 1 and 2. Failed layouts: 3 and 4.
- This is a fixed five-layout comparison panel, not RoboDojo native full
  evaluation. The external 5/5 reference is declared for comparison; equivalent
  conditions and statistical equivalence are not established.

The machine-readable entrypoint is [`index.json`](index.json). Its accepted run
links to `reports/<run-id>/result.json`, the five per-layout records and a
hash-bound media manifest. Videos are generated under `media/<run-id>/` and are
not stored in Git.

Raw client/server evidence is immutable and retained in the local `barks/`
archive after publication. The public report records SHA-256 and byte counts for
the raw summary, manifest, status, panel and episode ledger so archived evidence
can be matched without exposing server-private files.

## 2026-10-04 cohort: one closed layout-0 development sample

The client record closed at 2026-10-04 18:20:28 UTC. The original client copy on
the evaluation node was byte-verified, all three videos were fully decoded, and
the run's native, server and actor process cleanup was checked.
This sample does not replace or update the accepted five-layout panel above.

The preselected `classify_objects` layout 0 reached native success on control
758: **1 success / 1 client-selected case**, with native benchmark and process
scores both **100/100**. The record contains **154 policy calls, 152 executed
action decisions, 758 acknowledged controls, 2 rejected actions and 0 terminal
errors**. Termination was `environment:terminated`, not a budget cutoff or an
operator-selected stop. No automatic case retry occurred. This reports native
scorer success, not independent visual certification of every instruction clause
or a claim that both arms returned home.

- Protocol: `robodojo-direct-v2-rgb-proprio28-eef16-robot-feedback-v1`;
  native evaluator seed 0, layout 0; the client seed is `20260907`.
- The server retained the complete fast schedule, layouts 0–4. This development
  client selected only layout 0; the other **4 layouts were not attempted**.
  The selected-case result is not a five-layout panel success rate, a native-full
  result, or a score to combine with the 09-20 panel.
- Method: `codex-direct/v2`, requested `gpt-6-astra` with `xhigh` reasoning,
  persistent same-episode context and declared action-rejection feedback.
  Requested provider/model identity is not independently attested. Policy calls
  are not known provider-request counts; provider-internal retries and cost
  remain unknown.
- Budgets: 1100 native controls, a separate method-owned 1100-call cap and
  method-owned maximum chunk/replan length 5. The server does not impose that
  method's chunk choice as a universal policy limit.
- Timing: **842 initialization physics ticks** are separate from **7580
  policy-control physics ticks**. Controls use the declared 25 Hz target rate
  over native 250 Hz physics; neither count is model wall-clock inference time.
- Execution source: frozen `1afb5d7`; native source identity `ee67a146` is
  recorded in the JSON report. Nine original material dependencies were supplied
  from verified offline copies without changing the original USD files. A known
  stand-texture warning remains; complete asset closure and official native
  pixel parity are not established. Native scoring rules were not changed.

Non-terminal diagnostics are retained separately from episode failures. The
Codex transport cleanup receipt records `group_kill_failed`, but also verifies
the owned process group gone and the child reaped, with no final cleanup errors.
The failed signal's errno was not recorded, so its cause is unknown. This is
separate from the native worker, which exited with code 0 without TERM or KILL.

[JSON result](reports/2026-10-04-classify_objects-object-sorting-layout0-post-convergence-once/result.json)
and [HTML result](reports/2026-10-04-classify_objects-object-sorting-layout0-post-convergence-once/index.html)
are prepared from the closed client records. The basic report checks recorded
outcomes and counters; it does not attest source/runtime parity, provider identity,
media integrity or process cleanup. This is the original Direct-v2 cohort run,
not the separate `codex-planned/v1` policy-development experiment.

Optional central-gallery videos: [head camera](../media/2026-10-04-service-validation/robodojo/2026-10-04-classify_objects-object-sorting-layout0-post-convergence-once/cam_head.mp4),
[left wrist](../media/2026-10-04-service-validation/robodojo/2026-10-04-classify_objects-object-sorting-layout0-post-convergence-once/cam_left_wrist.mp4)
and [right wrist](../media/2026-10-04-service-validation/robodojo/2026-10-04-classify_objects-object-sorting-layout0-post-convergence-once/cam_right_wrist.mp4).
These are optional, Git-ignored viewing copies; raw evidence remains unchanged.
Each video has 759 frames at 25 fps: the initial observation and one frame per
executed control, not the elapsed model-inference or artifact-transfer time.

## 2026-10-05: separate Planned-v1 layout-0 experiment

The client record for
`2026-10-05-classify_objects-object-sorting-layout0-planned-v1-once` closed at
2026-10-04 20:09:26 UTC. This additional policy-development experiment does not
replace the Direct sample or enter the original seven-service primary cohort.
The accepted 09-20 five-layout panel remains unchanged.

The selected case ended with **native failure**, benchmark and process scores
both **40/100**: **237 policy calls, 236 executed action decisions, 1053
acknowledged controls, 0 rejected actions and 0 terminal errors**. Call 237
explicitly requested `safety_stop` with no actions, leaving **47 controls** unused.
Termination was `policy:safety_stop`, not a budget cutoff or infrastructure
error. Its safety rationale is a model-authored judgment, not independent proof
of collision, physical necessity to stop or satisfaction of all task conditions.
No automatic retry occurred.

- Method: `codex-planned/v1`, frozen source `33b4edb`, requested `gpt-6-astra`
  with `xhigh` reasoning; provider identity and internal request/retry counts
  remain unverified.
- The unchanged `robodojo-direct-v2-rgb-proprio28-eef16-robot-feedback-v1`
  service retained all five fast layouts. Only layout 0 / native seed 0 was
  selected; layouts 1–4 were not attempted. This is not a panel success rate
  or native-full result. The client seed was `20260907`.
- Limits: 1100 native controls, separate method-owned 1100-call cap and
  maximum chunk/replan length 5; the model selected shorter chunks as well.
  The **842 reset physics ticks** are separate from **10530 policy physics ticks**.
- The known stand-texture limitation remains. Native scorer/controller rules
  were unchanged; official pixel parity and full asset closure are not claimed.

This comparison changes more than planning: Planned v1 exposes current declared
state and acknowledged actions/counters without Direct v2's detailed IK feedback;
it uses generic action-vector sequences, omits Direct's optional motion guard,
adds a safety-stop branch, and changes the prompt and memory representation.
The two single-case outcomes cannot establish which difference caused the result,
that planning is generally worse, or that the underlying model regressed.

[JSON result](reports/2026-10-05-classify_objects-object-sorting-layout0-planned-v1-once/result.json)
and [HTML result](reports/2026-10-05-classify_objects-object-sorting-layout0-planned-v1-once/index.html)
preserve the closed outcome. The client/native record and three videos passed
their independent audit; the complete remote copy and outer operator cleanup
are verified. Zero terminal episode errors does not mean no native
warnings: the historical texture/screenshot-directory messages and a nonterminal
Codex `group_kill_failed` cleanup diagnostic are retained.

Optional central-gallery videos:
[head camera](../media/2026-10-04-service-validation/robodojo/2026-10-05-classify_objects-object-sorting-layout0-planned-v1-once/cam_head.mp4),
[left wrist](../media/2026-10-04-service-validation/robodojo/2026-10-05-classify_objects-object-sorting-layout0-planned-v1-once/cam_left_wrist.mp4)
and [right wrist](../media/2026-10-04-service-validation/robodojo/2026-10-05-classify_objects-object-sorting-layout0-planned-v1-once/cam_right_wrist.mp4).
Each fully decoded video has 1054 frames at 25 fps: one initial frame plus one
per control. These optional Git-ignored copies do not replace raw evidence.
