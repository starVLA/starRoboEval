# Franka evaluation integration

This is the future single-/dual-arm hardware evaluation entrypoint, not a model
training recipe. No unified hardware benchmark adapter or task score is certified.

- Retained client references: [single arm](eval_files/inference_single_example.py)
  and [dual arm](eval_files/inference_dual_example.py).
- The client/server scripts are historical StarVLA checkpoint integrations;
  their model normalization and inference loop are not the neutral `Policy` contract.
- Dataset conversion and training recipes are removed from the active tree;
  their original documentation remains recoverable from Git history.

For evaluation records, preserve camera identities/order, timestamped images,
measured robot state, issued actions, task language and episode boundaries.
The old dataset convention does not establish action units or frames: derive
those from the selected hardware controller before declaring an interface.

A future adapter must separately pin hardware, cameras/state, action frames/units,
task success, emergency stops and operator supervision. Move model calls and
method-specific planning to `AgentPolicies/<profile>/`; leave declared robot I/O and
safety at the hardware boundary. Validate mocks/replay before any authorized
physical motion. This cleanup does not start a robot or enable the old server.
