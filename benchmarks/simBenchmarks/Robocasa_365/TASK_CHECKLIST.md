# RoboCasa365 task selection reference

The [upstream inventory](bench_server/protocol/task_inventory.json) records
365 implemented tasks (65 atomic and 300 composite), separately from the
317 entries with dataset metadata. It is a source inventory, not an evaluation
completion checklist.

The [target50 catalog](bench_server/protocol/robocasa365_target50.json) defines
the service's expanded task ordering and native-reference horizons:

| Split | Tasks |
| --- | ---: |
| Atomic seen | 18 |
| Composite seen | 16 |
| Composite unseen | 16 |
| Total | 50 |

`fast` and `max` use all 50 tasks with launch seed 20260907. `fast` runs
attempts 1–5 on one seeded scenario per task and `example` runs task 0 once.
`max` matches the reference's 50 scenarios per target task with seeds
20260907 + 0..49, a deterministic stand-in for upstream's unseeded draws.
One `fast` attempt pass over task IDs therefore has a different denominator.

Before evaluation, fix the evaluation mode, seed, rendering track and
budget. Record completed, failed, errored and unattempted cases with the
participant's results rather than editing this task catalog. See the
[evaluation protocol](EVALUATION_PROTOCOL.md) and
[service guide](README.md#start-the-benchmark-service).
