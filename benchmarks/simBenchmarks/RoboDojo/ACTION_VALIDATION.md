# Action validation and rejection feedback

Validation is not task scoring. Native RoboDojo still decides success. Input
checks use only submitted values and public contract constants, never object
truth, hidden predicates or hypothetical simulator outcomes.

## Requirement ownership

| Requirement | Owner/source | Configurable? |
| --- | --- | --- |
| EEF16: two `[x,y,z,qw,qx,qy,qz,opening]` targets, finite numbers, unit wxyz quaternions, opening `[0,1]` | Benchmark [Direct v2 EEF interface](environment/REFERENCE_EEF.md); norm tolerance `1e-4` | Mandatory, versioned input validity |
| Fixed IK and per-control numerical bounds | Benchmark robot-only low-level conversion | Another declared benchmark track is required to change it |
| Per-decision 5 cm / 0.35 rad, binary opening 0 or 1 | Current model's `AgentPolicies/gpt6_astra/` action guard | Optional, enabled by default |
| Response JSON fields, repeated-target count, memory/note lengths, safety-stop representation | Selected model's output/memory protocol | Declared in model configuration, not native scoring |

The 5 cm / 0.35 rad guard and 1–5 repeated controls were settings of the first
Codex EEF method, not universal RoboDojo limits. Another model may declare its
own preferences while respecting the same mandatory benchmark action contract.
The benchmark accepts continuous opening commands; binary opening is only a
model preference. Direct v2 aligns its target tolerance with GPT-as-Policy
Direct at commit `8f3d362b077d8efb77e2a7274d5b2c20e2243846`.

The accepted submitted quaternion is retained unchanged in action records;
conversion to a rotation uses SciPy's quaternion interpretation, as upstream
does. This is not repair of a target rejected by its declared tolerance.
The v2 fixed DLS clips in float64 and casts the resulting command to float32,
exactly as the reference does. It does not apply v1's extra one-ULP inward
adjustment or revalidate converted joint targets against the old RGB/joint14
decimal bounds. Native soft-limit intersection and per-control DLS bounds
still apply before that documented numerical cast.

## Reject a command without ending the episode

New services advertise `action_rejection: starvla-rsi.action-rejection/v1`.
A deterministic pre-execution rejection returns a closed issue code, declared
field, finite scalar actual/limit, `executed: false`, and the unchanged next
control sequence. The session remains open. No native control, new camera
capture, reward evaluation, reset or automatic replay occurs.

A corrected command can use that same control sequence. The model's driver
returns the issue through the next normal policy call with the last acknowledged
observation. That call and its available usage are counted; an invalid target
adds zero executed action decisions, controls or physics ticks. Any previously
acknowledged valid prefix remains real execution. Invalid output does not become
an executed history entry or a successful memory update.

Lost acknowledgements, native exceptions, corrupt responses, authentication
failures and uncertain execution still fault the stream. Native end, valid
safety stops and public resource limits remain terminal. The service never
repairs, clips, normalizes or substitutes a target, calls a model, or supplies
task-solving feedback. Public rejection data excludes raw provider/native error
text, arbitrary JSON keys, credentials and hidden state.

## Model configuration and budgets

The [Codex v2 client](../../../AgentPolicies/gpt6_astra/README.md) defaults to feedback
handling with enabled extra guards. `--no-action-guard` disables only extra
motion/binary-gripper preferences. Mandatory validity checks remain.
`--invalid-action-handling terminate` explicitly selects terminal rejection.
Choices are frozen before execution and recorded with the method version.

Feedback mode requires a finite policy-call budget, since invalid outputs do
not advance the simulator horizon. The model driver declares this budget with
`--max-policy-calls`; the current RoboDojo service does not assign a model-call
allowance. Rejections consume that same call budget, with no hidden extra
messages. The native 1100-control horizon is a separate benchmark limit.

Frozen `codex-eef/v1` attempts retain their original terminal-error handling.
Keep v2 and repair-round results separate; never replace first-panel failures.
The model-method version `codex-eef/v2` and the fixed benchmark protocol are
independent version namespaces. Bind both sides before any attempt.
CPU fixtures validate interface/accounting mechanics, not native capability or SR.
