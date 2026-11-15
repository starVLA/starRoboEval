# Policy development boundary

This profile holds the Native Claude Opus Policy, the baseline for what the model
does before anything is tailored to a benchmark. Its prompt and checked-in
configuration are frozen before each reported run and shared by every benchmark.
Do not tune them on evaluation failures. A method that adds a harness, tools,
demonstrations, a changed prompt or a self-improvement loop is a different
method: give it its own profile or method ID so that it is reported as its own
entry next to the baseline. Never encode a benchmark/task name, layout, object
coordinate, prerecorded trajectory or private score as a strategy.

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

Never patch an active run. New evaluation runs must be preselected,
separately named and retained on failure. No automatic task retry or uncertain
action replay. Keep this policy's implementation, prompt, configuration and
results in this profile; shared record/source tooling is not a policy planner.
