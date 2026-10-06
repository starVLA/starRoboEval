# Policy development boundary

Build general-purpose embodied agent methods here. Start with a top-down design
of capabilities, observations, planning, execution feedback and recovery before
changing prompts or running tasks. Do not encode a benchmark/task name, layout,
object coordinate, prerecorded trajectory or private score as a strategy.

`benchmarks/simBenchmarks/` is **read-only for policy work**. You may inspect its
public contracts and source to understand the interface. Do not edit, patch,
delete, generate files in, or change permissions under that tree to improve a
policy result. Do not modify a benchmark server, task, horizon, scorer, controller
or asset through another path either. An integration defect is reported
separately; policy work does not grant benchmark modification authority.

Development-time source inspection is not permission to expose arbitrary
benchmark files to the model during an episode. The live actor receives only
declared public observations, action/state semantics and execution feedback.
Never expose private layouts/seeds, object truth, scoring implementations/data,
native handles, simulator evaluation tools, administrative client or credentials.
Read-only filesystem access alone does not prevent oracle leakage.

The model owns plans, same-episode factual memory, action choice, repetitions,
replan timing and optional motion preferences. Use the public benchmark server
for all robot execution. No task-solving fallback, VLA proposals or simulated
lookahead. Acknowledgment confirms executed controls, not object manipulation
success. Success is reported only from the benchmark's native result.

Keep prior versioned methods/results intact while introducing a new method.
Never patch an active frozen run. New validation attempts must be preselected,
separately named and retained on failure. No automatic task retry or uncertain
action replay. Keep all policy implementation, prompt, configuration and results
in this model namespace; shared record/source tooling is not a policy planner.

Use independent review and offline regressions before an authorized live sample.
Never push Git commits. Local commits use JinhuiYE <jinhuiyes@gmail.com>.
