> Historical anonymous code-agent evidence. Model/provider identity remains unverified.
> Original document: `examples/simBenchmarks/LIBERO/reports/2026-09-07-infrastructure-review.md` at source revision `29cb55d`;
> original SHA256: `d4eac0d982c9242338582ae47db3d6c7db0d7e1f8a831d5df43ae4a60d1661d8`. Only documentation links were rebased.

# Independent LIBERO infrastructure review — 2026-09-07

Verdict: **development-ready for the checked task-0 initialization, RGB export,
native action interface, and artifact paths**. This review does not establish
model capability, successful task completion, or full LIBERO evaluation parity.

The reviewed, closed diagnostic directory is
`results/libero-environment-diagnostic-20260907-task0-v4/` on the eval node,
relative to `/mnt/workspace/users/jinhuiye/Projects/starVLA-RSI/`. Review was
read-only. No active model-run artifacts were inspected, no task was rerun, and
no harness or historical result was changed.

**Model not run.** The environment verifier directly opens a native session,
performs initialization and one diagnostic action, then closes it. It does not
instantiate a model or call a policy. Its artifacts must not be counted as a
model trial or used to estimate a model success rate.

## Verified artifacts and source identity

| Camera | PNG frames | Decoded H.264 frames | RGB dimensions | Video rate |
| --- | ---: | ---: | --- | ---: |
| `agentview` | 2 | 2 | 256 × 256 × 3 | 20 frames/s |
| `robot0_eye_in_hand` | 2 | 2 | 256 × 256 × 3 | 20 frames/s |

All four PNG hashes match `frames.jsonl`. Each camera has exactly steps 0 and 1,
with no extra or missing PNG file. Both videos decode fully, with matching
dimensions and frame counts. All PNGs have nonzero spatial variation. Decoding
validates artifact integrity; it does not determine whether the robot completed
the task. Exact observation identity comes from the lossless PNGs, not equality
with the lossy video frames.

The reviewer independently checked the native checkout at
`/mnt/workspace/users/jinhuiye/benchmarks/LIBERO`: its HEAD is
`8f1084e3132a39270c3a13ebe37270a43ece2a01`, with no tracked modifications.
The task-0 BDDL file, released `.pruned_init` file, and selected initial-state
array all match their SHA-256 values in `native_provenance.json`. The released
file contains 50 initial states, and the recorded selection is index 0.

The provenance identifies LIBERO-10, native task order 0, task 0, reset seed
20260907, 10 settling actions, OSC_POSE configuration, and the 520-controlled-step
evaluation cap. Recorded package versions are LIBERO 0.1.0, Robosuite 1.4.0,
MuJoCo 3.2.3, NumPy 1.24.4, CPU Torch 2.5.1, ImageIO 2.37.0 and
ImageIO-FFmpeg 0.6.0.

## Observation boundary and image orientation

Native `BDDLBaseDomain` defaults to `use_object_obs=True`, so object observables
exist internally. The pinned `_setup_observables()` initializes `sensors` and
`names` inside that condition and uses them afterward; disabling the option
would leave those variables undefined. Retaining native construction is
therefore appropriate for this revision.

Internal object allocation does **not** authorize exposing those values to a
policy. The RSI adapter constructs a new `Observation` from an explicit
allowlist: `agentview_image` and `robot0_eye_in_hand_image`, each as a copied
256×256 RGB array. Default `state` is `None` and `metadata` is empty. Object
state, EEF/object poses, reward, native info, seed, reset-state vectors, depth,
segmentation and camera calibration are not forwarded. The optional nine-joint
encoder track has a distinct protocol identity and is outside this diagnostic.

Both cameras use `np.ascontiguousarray(frame[::-1, ::-1]).copy()`: a fixed
180-degree rotation. This matches the retained StarVLA evaluator's transforms
for both images in `eval_files/eval_libero.py`. It does not match the legacy
policy's complete input setting, which also assembled EEF-based state; matching
image orientation alone is not model or evaluation parity.

The reviewer independently ran all eight LIBERO adapter checks in the installed
runtime; all passed. They include injected object-state/EEF/score/reset metadata,
RGB-only filtering, copy isolation, exact two-axis image transformation, frozen
task selection, native-done propagation, and horizon termination. These checks
exercise the data boundary without opening a simulator. The closed diagnostic
does not contain an external policy transcript and does not test hostile client
filesystem/process isolation.

## Initialization, action budgets, and native success

The inspected adapter sets released initial state 0, then performs exactly ten
fixed `[0,0,0,0,0,0,-1]` settling actions. It rejects native success during this
phase. Its first exported frame is controlled-step 0 **after** settling; step 1
is the verifier's one diagnostic action. The settling loop and recorded count
agree with the retained evaluator's `num_steps_wait=10`. There is no per-settling-
step event trace in this diagnostic, so the historical internal step count is
not independently reconstructible from frames alone.

The 520 limit is the retained LIBERO-10 evaluator's controlled-step setting,
not the generic native wrapper horizon: `OffScreenRenderEnv` is constructed with
`horizon=1000`, and RSI enforces 520 controlled steps separately. With the current
first-pass budget of 40 decisions and at most five executed actions per decision,
an unsuccessful model episode can execute **at most 200 controlled steps**,
plus ten evaluator settling actions. Short chunks, early stop, or error reduce
that count. These first-pass results would not be a 520-step evaluation. The
one-action diagnostic does not empirically exercise either cap.

Native action scaling matches recorded OSC_POSE input bounds `[-1,1]`, output
translation scale 0.05 m per component, and rotation scale 0.5 rad per component.
The inspected Panda gripper uses negative commands to open, positive to close,
and zero to preserve its target. RSI rejects invalid actions before stepping.

The pinned `BDDLBaseDomain.step` obtains the native transition, then assigns
`done = self._check_success()`. The task's living-room implementation conjuncts
all BDDL goal predicates. RSI takes that returned `done`, ends on native success,
and does not query an additional predicate or trust model claims. Its `metrics()`
returns cached success. The pinned initial-state loader itself calls a native
success check while regenerating observations; that evaluator-owned initialization
does not expose its outcome to the policy or award a model success.

## Findings and limits

**Medium — diagnostic completion and native outcome are not persisted.** The v4
directory contains provenance, frame records and videos, but no `status.json`,
diagnostic result, step event or stored native `done`. The verifier prints its
diagnostic summary instead of saving it, and that summary omits native outcome.
The files prove that frames were produced through step 1 and videos are decodable;
they do not independently retain successful process exit or task success/failure.
Future diagnostic tooling should persist completion/error status, settling and
controlled-step counts, native transition outcome, and artifact references. No
task score is inferred or retroactively added here.

**Medium — exact historical harness source is not pinned in the diagnostic.**
Native BDDL/reset hashes and upstream revision are useful and were verified, but
there is no harness revision plus source/patch digest. Current source inspection
and boundary checks do not reconstruct every historical implementation detail.
Preserve a committed revision or dirty patch plus digest before future runs.

The older v2 directory remains empty and v3 contains only native provenance;
neither has completed camera artifacts in the reviewed locations. Their precise
errors cannot be recovered from those directories alone. They remain
infrastructure diagnostics, not discarded model attempts.

Not verified here: a real model/provider call, successful task completion, a full
200/520-step rollout, repeated-seed native reset equivalence, adversarial client
isolation, native-policy score parity, other task resets, or a complete 10-task /
50-state benchmark. Findings should inform a future frozen implementation, not
change a model pass already in progress.

## Review fingerprints

| File in v4 directory | SHA-256 |
| --- | --- |
| `native_provenance.json` | `1e60036cf5e9f99e2f9799420da161e61e18570aa3b3c44a8b67a2b09f0c5f35` |
| `frames.jsonl` | `b8695ea2fd36dae0fa711f47b385c7953e0c6a8cb4aea9c085fc6dc92f253a90` |
| `agentview.mp4` | `927ef1e3711ae446cdc88d1568dd8be5ebd2829ca51921baa3b15c8cced4a34d` |
| `robot0_eye_in_hand.mp4` | `46a43469db5efee6f5a9986ecfac21de6fbbfb18be54c95634c235ee570092e4` |
