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

Select `task_scope="target50"` with an explicit increasing, unique `task_ids`
subset of 0–49. The smaller `pilot` scope uses different local indices:
0=OpenDrawer and 1=NavigateKitchen. Each service-selected task currently uses
one sample at seed 20260907, without a selectable layout/style or seed panel.
The reference has 50 scenarios per target task; that repeated-scenario sampler
is not implemented. A single pass over task IDs has a different denominator.

Before evaluation, fix the selected tasks, scope, seed, rendering track and
budget. Record completed, failed, errored and unattempted cases with the
participant's results rather than editing this task catalog. See the
[evaluation protocol](EVALUATION_PROTOCOL.md) and
[service guide](README.md#start-the-benchmark-service).
