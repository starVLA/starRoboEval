# LIBERO: GPT6Astra agent-method samples

## 2026-10-04: one closed Spatial task-0 sample

The preselected black-bowl-on-plate sample completed with native failure:
**0 successes / 1 selected case**, 0 errors, 54 policy calls, 53 executed action
decisions and 215 controls. The final call requested `give_up` and executed no
action. No action was rejected and there was no automatic retry.

- Task/reset: `libero_spatial/task-0`, initial state 0, seed `20260907`.
- Protocol: `libero-task-coverage/libero_spatial/rgb/v1`; task horizon 220.
  Ten native settling controls are initialization and are
  separate from the 215 model-controlled steps.
- Method: `codex-native/v1`, requested `gpt-6-astra` with `xhigh` reasoning;
  method-owned policy-call cap 220 and chunk/replan setting 5, not universal
  server limits.
- [JSON result](reports/2026-10-04-libero_spatial-task0-black-bowl-on-plate-post-convergence-once-independent-audit/result.json)
  and [HTML result](reports/2026-10-04-libero_spatial-task0-black-bowl-on-plate-post-convergence-once-independent-audit/index.html).
- Optional raw-export videos: [agent view](raw/2026-10-04-libero_spatial-task0-black-bowl-on-plate-post-convergence-once/client/episodes/libero_spatial-task00-init00/artifacts/sim_server_files/agentview.mp4)
  and [wrist view](raw/2026-10-04-libero_spatial-task0-black-bowl-on-plate-post-convergence-once/client/episodes/libero_spatial-task00-init00/artifacts/sim_server_files/robot0_eye_in_hand.mp4).
  These files are Git-ignored and not bundled in this source checkout.

The CLI model/provider identity is requested, not independently attested.
Provider-internal requests/retries and cost are unknown; available tokens are
CLI-reported. This single sample is not benchmark-wide or native-full coverage.
Readiness diagnostics are not scored model cases. [The index](index.json)
retains historical attempts separately: the 2026-09-20 decision-budget protocol
below is different and its outcomes must not be pooled with this horizon track.

## 2026-09-20: preserved historical development-track attempts

The authorized launch-corrected Spatial task 0 sample closed normally with
**native failure after 122 policy calls, 121 executed action decisions and 425
controls**. The last call requested `give_up` and executed no action. There were
zero rejected actions and no interface/infrastructure error in that run. Its
public stop note reports difficulty aligning the gripper with the target bowl;
that is the policy's explanation, not an independent diagnosis.

The earlier launch attempt remains a separate infrastructure-error record:
the operator omitted the pinned LIBERO checkout from `PYTHONPATH`, so native
source validation failed before environment construction, with zero policy
calls and zero controls. The corrected run was explicitly authorized as a new
attempt; it was not an automatic retry or a replacement of the error record.

| Recorded run | Native outcome | Policy calls | Executed decisions | Controls |
| --- | --- | ---: | ---: | ---: |
| Original launch | Infrastructure error; success unknown | 0 | 0 | 0 |
| Authorized launch-corrected sample | Failure, `policy:give_up` | 122 | 121 | 425 |

These are two preserved attempt records for one selected task/reset, only one
of which reached model-controlled execution. They are not a two-case benchmark
score, benchmark-wide success rate, or native-full evaluation.

### Conditions

- Task: `libero_spatial/task-0`, pick up the black bowl between the plate and
  ramekin and place it on the plate; native task order 0, initial state 0,
  seed `20260907`.
- Protocol: `libero-task-coverage/libero_spatial/rgb/decision-200-prefix-5/v1`.
- Observation: `agentview` and `robot0_eye_in_hand` RGB, 256×256 with the retained
  orientation transform; no proprioception or object truth.
- Action: seven normalized world-frame OSC pose deltas/gripper commands, 20 Hz.
- Budget: 200 policy calls, at most five controls per returned action prefix,
  1000-control cap. This differs from the retained Spatial reference horizon
  of 220 controls. Ten fixed settling controls are separate initialization.
- Method: `codex-native/v1`, one `codex-exec/v1` invocation per policy call,
  current RGB plus the last eight acknowledged chunks. Ordinary give-up was
  permitted by this model's configuration; no benchmark persistence floor.

Success comes only from the pinned native `BDDLBaseDomain.step` success flag.
All 425 executed controls reported false; the native return was 0. A policy
stop or visual impression does not award success. No extra scorer queries were
used. The requested CLI identity `gpt-6-astra`/OpenAI is recorded, but backend
identity, internal request/retry counts, cost and OS isolation are not attested.

### Reports and videos

- [Result index, including both attempts](index.json)
- [Corrected sample report](reports/2026-09-20-libero_spatial-task0-init0-black-bowl-on-plate-bench-server-native-v1-sample-launch-env-fixed/result.json)
- [Original launch-error report](reports/2026-09-20-libero_spatial-task0-init0-black-bowl-on-plate-bench-server-native-v1-sample/result.json)
- [Closed-record audit summary](reports/2026-09-20-libero_spatial-task0-init0-black-bowl-on-plate-bench-server-native-v1-sample-launch-env-fixed/record-audit.json)
- [Video inventory and hashes](reports/2026-09-20-libero_spatial-task0-init0-black-bowl-on-plate-bench-server-native-v1-sample-launch-env-fixed/media.json)
- Videos: [agent view](media/2026-09-20-libero_spatial-task0-init0-black-bowl-on-plate-bench-server-native-v1-sample-launch-env-fixed/agentview.mp4),
  [wrist view](media/2026-09-20-libero_spatial-task0-init0-black-bowl-on-plate-bench-server-native-v1-sample-launch-env-fixed/robot0_eye_in_hand.mp4).

Both videos fully decode to 426 RGB frames at 256×256 and 20 Hz, with increasing
timestamps: one initial frame plus 425 post-control frames. Server originals,
local downloaded files, exported client files and presentation copies have
matching hashes. Both views were delivered to the model. The original failed
launch produced no video. Decoding is not independent proof of task success.

Both closed-record audits passed, checking 131 runtime-source files, 29 model
files and their respective call/control ledgers. This establishes record
consistency, not native parity or execution/provider attestation. Public reports
exclude deployment paths and private tracebacks; hash-linked raw evidence stays
unchanged. Evidence paths are relative to this result directory and list local
or exported-client alternatives. Videos are Git-ignored presentation copies.

See the [benchmark protocol](../../../../examples/simBenchmarks/LIBERO/EVALUATION_PROTOCOL.md)
and [result organization](../README.md).
