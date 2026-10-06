# Anonymous policy instructions

These are policy-side development instructions, not native benchmark definitions.

- [control_guidance.txt](control_guidance.txt): generic visual-control guidance,
  moved byte-for-byte from the old shared `POLICY_PROMPT.txt`.
- [actor_instructions.txt](actor_instructions.txt): opaque mailbox actor/operator
  instructions, moved byte-for-byte from `POLICY_ACTOR_INSTRUCTIONS.txt`.
- [simpler_development.txt](simpler_development.txt): this policy's historical
  SimplerEnv development guidance, moved byte-for-byte from that benchmark's old
  `prompts/policy.txt`. It is not a benchmark requirement or task solution.

The profile's base prompt remains [`../prompt.txt`](../prompt.txt). A campaign may
explicitly select additional guidance with `--prompt-file`; its exact effective
prompt is frozen. All three reference files are explicitly included in the declared
model-source bundle, but are not automatically appended to an actor's prompt.
Only the effective prompt / `campaign_prompt.txt` hash identifies the actual
text delivered for a run. Old frozen prompts and results remain unchanged.

Benchmark-owned interface guides stay with their benchmark: they describe
allowed observations, action units, fixed native controllers and limits, not
a model-specific grasp plan or task solution. Model-side hints and persistence
rules must not be presented as mandatory benchmark conditions.
