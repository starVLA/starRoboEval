# RoboChallenge Table30v2 evaluation integration

This is a retained hardware-evaluation interface reference, not yet a unified
RSI `BenchmarkAdapter`. No actual RoboChallenge robot task is launched here.

- [Original interface and mock-test notes](eval_files/README.md).
- [Checkpoint policy bridge](eval_files/model2robochallenge_interface.py) documents
  native server image/state/action schemas, but directly loads an old StarVLA
  checkpoint and performs its normalization. It is model-side reference code,
  not an interchangeable native benchmark adapter.
- [Mock/self-test material](eval_files/local_self_test.py) is retained for future
  extraction and review; old model/deployment dependencies are not restored.
- Retired data download/conversion, registry and training recipes remain in Git
  history and the local ignored `barks/` archive.

Future integration must separate model calls and normalization into a policy
profile, and pin native server I/O, task episodes, objective success, robot
ownership/operator authorization, emergency stops and timeouts in the benchmark.
Mock tests do not certify physical safety. Results will belong to the selected
model's `AgentPolicies/<profile>/results/<benchmark>/` namespace.
