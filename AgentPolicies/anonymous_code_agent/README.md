# Anonymous code agent

This selectable profile uses the existing one-observation mailbox transport.
The provider and model identity remain unknown; it is not a named-model score.
`policy.py` owns the factory, `config.json` the transport configuration, and
`prompt.txt` the generic profile instruction. `dependencies.json` declares the
complete, small source allowlist. `mailbox.py` implements this profile's transport;
reusable opt-in policy rules live in `../policy_support/`, not the benchmark.

Prepare a new campaign with `python -m benchkit.campaigns prepare
--model-profile anonymous_code_agent` plus the benchmark, prompt, mailbox and
output arguments. Put new output under
`results/<benchmark>/raw/<task-described-new-run>/campaign` (Git-ignored).
An explicitly selected positive
`--policy-min-action-decisions-before-give-up` for `python -m benchkit run`, or
the campaign's policy parameters, adds a prospective **policy-owned** stopping
preference; `config.json` defaults to zero. This does not change native benchmark
rules, task coverage, or the evaluation plan's fast/full mode. Existing frozen campaigns and historical attempts
retain their original identities and bytes.

New profile campaigns use campaign/v3 and a separate `model_source/v2` bundle;
standalone CLI profile runs also capture that bundle before reset. The index
binds exact factory, config, profile, prompt and dependency bytes. Campaigns
also verify the copied factory inside their frozen package. Results and
neighboring files are never included in the source allowlist.
The compatibility CLI spelling `--policy mailbox` resolves to this same profile
and captures the same model bundle. It cannot override unknown provider/model
identity with an arbitrary display label. `--policy scripted` and `constant`
remain explicitly diagnostic policies, not scored named-model integrations.

The standalone preparation utility
`python -m AgentPolicies.anonymous_code_agent.tools.new_mailbox --root <stable-root>`
chooses an unused opaque endpoint; it does not launch an actor or environment.
It is shipped as a model-owned tool, not included in the `Policy.act` runtime
source allowlist. Campaign preparation already allocates endpoints and records
their values. The three reference texts in `prompts/` are source-bound but are
used only when explicitly selected into the effective prompt.

## Policy persistence and wire v3

The optional `minimum-action-decisions/v2` preference is frozen in
`PolicyDescriptor.parameters.policy_stop_rule`, alongside the effective prompt.
It is enforced here by the policy, never by `RunRequest`, the shared runner or a
benchmark adapter. With a preference of 50, ordinary give-up can first occur on
call 51 after 50 non-stop decisions actually executed at least one control each.
Native end, errors and evaluation limits may end earlier; an explicit safety
stop with a nonempty note remains possible. No rule permits a retry.

The runner's optional `ExecutionFeedback` contains only completed call/action/
control counts. The policy must not equate submitted chunks or physics ticks
with executed action decisions. Mailbox v3 publishes `control_feedback` and
`policy_constraints` separately from evaluation `budgets`. A premature stop is
retained in the original turn's `accepted_response.json`, then recorded as a
policy error without a second request or invented action. Old v2 records remain
unchanged and are audited under their original schema.

Dependency-light policy checks:

```bash
python -m unittest discover -s AgentPolicies/anonymous_code_agent/checks -v
```
