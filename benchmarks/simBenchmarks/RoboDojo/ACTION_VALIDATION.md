# Action validation and rejection feedback

Validation is not task scoring. Native RoboDojo still decides success. Input
checks use only submitted values and public contract constants, never object
truth, hidden predicates or hypothetical simulator outcomes.

## Requirement ownership

| Requirement | Owner/source | Configurable? |
| --- | --- | --- |
| EEF16: two `[x,y,z,qw,qx,qy,qz,opening]` targets, finite numbers, unit wxyz quaternions, opening `[0,1]` | Benchmark [Direct v2 EEF interface](environment/REFERENCE_EEF.md); norm tolerance `1e-4` | Mandatory, versioned input validity |
| Fixed IK and per-control numerical bounds | Benchmark robot-only low-level conversion | Another declared benchmark track is required to change it |
| Optional motion-size guards, binary-gripper preferences, action grouping | Selected agent method | Method-owned; not server action validity |
| Response JSON fields, repeated-target count, memory/note lengths, safety-stop representation | Selected model's output/memory protocol | Declared in model configuration, not native scoring |

An agent may declare its own optional guards while respecting mandatory
benchmark action validity. The service does not impose a model's per-decision
motion limit or number of controls per decision. It accepts continuous opening
commands; binary opening is a method preference. Numerical execution provenance
is pinned in [the runtime binding](environment/REFERENCE_EEF.md); it does not
require participants to adopt the reference repository's agent implementation.

The accepted submitted quaternion is retained unchanged in action records;
conversion to a rotation uses SciPy's quaternion interpretation, as upstream
does. This is not repair of a target rejected by its declared tolerance.
The fixed DLS clips in float64 and casts the resulting command to float32,
exactly as the reference does, without an inward one-ULP adjustment or a
revalidation of converted joint targets. Native soft-limit intersection and
per-control DLS bounds still apply before that documented numerical cast.

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
acknowledged valid prefix remains real execution. An invalid output is not an
executed control; an agent may retain the rejection in its own memory.

Lost acknowledgements, native exceptions, corrupt responses, authentication
failures and uncertain execution still fault the stream. Native end, valid
safety stops and public resource limits remain terminal. The service never
repairs, clips, normalizes or substitutes a target, calls a model, or supplies
task-solving feedback. Public rejection data excludes raw provider/native error
text, arbitrary JSON keys, credentials and hidden state.

## Client behavior and budgets

A client may act on deterministic rejection feedback or end its attempt;
declare the handling before execution and retain every rejection. Optional
agent guards cannot disable mandatory server validity. See the
[agent-method contract](../POLICY_PROTOCOL.md) for ownership and the selected
method's guide for configuration flags and defaults.

The optional reference feedback loop requires a finite policy-call cap because
invalid outputs do not advance simulation. That is a driver constraint, not a
model-call allowance assigned by RoboDojo. Disclose the selected cap and count
correction calls and available usage. The native 1100-control horizon remains
separate. No automatic replay, extra observation or reset is granted.

Benchmark protocol and agent method versions are independent. Retain the
conditions of each attempt and do not overwrite failures after a correction.
CPU fixtures validate interface/accounting mechanics, not native capability or SR.
