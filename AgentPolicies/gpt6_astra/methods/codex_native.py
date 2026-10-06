"""Native-vector decisions with public ACK memory and bounded CLI recovery.

Not the persistent Dojo Direct method and not a benchmark-specific controller.
Only RGB, declared robot sensors, action semantics and accounting enter requests.
The existing trusted-local CLI transport is not an OS sandbox or request meter.
Transport attempts stay within one policy decision and never replay controls.
"""
from __future__ import annotations

from collections import deque
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

from benchkit.contracts import ActionRejectionFeedback, ExecutionFeedback, Usage
from benchkit.errors import ActionRejected, PolicyCallError, PolicyError
from benchkit.validation import ValidationIssue
from AgentPolicies.gpt6_astra.tools.native_io import NativeActionIO

_ROOT = Path(__file__).absolute().parents[1]


class CodexNativePolicy(NativeActionIO):
    def __init__(self, *, identity, prompt=None, **overrides):
        payload = (_ROOT / "configs/codex_native_config.json").read_bytes()
        config = json.loads(payload)
        from AgentPolicies.gpt6_astra.transports.codex_cli import MODEL, REASONING_EFFORT
        if config["model"] != MODEL or config["reasoning_effort"] != REASONING_EFFORT:
            raise ValueError("native preset differs from pinned CLI transport identity")
        if prompt is None:
            prompt = (_ROOT / "prompts/codex_native_prompt.txt").read_text()
        super().__init__(config=config, identity=identity, prompt=prompt, **overrides)
        if self.config["timeout_s"] > 900 or self.config["max_chunk_length"] > 5:
            raise ValueError("Codex native allows at most 900 seconds and five controls per call")
        self.descriptor = replace(self.descriptor, version="codex-native/v1", parameters={
            **self.descriptor.parameters, "control_method": "codex-native/v1",
            "effective_config": self.config.copy(), "preset_sha256": hashlib.sha256(payload).hexdigest(),
            "model_identity_evidence": "requested CLI model; backend attestation unavailable",
            "tool_isolation": "trusted local CLI with event rejection; not OS isolation",
            "invalid_action_handling": "feedback",
            "automatic_retry": {"scope": "same_policy_decision_before_action_submission",
                                "max_attempts": self.config["max_attempts"],
                                "retry_backoff_s": self.config["retry_backoff_s"]},
        })
        self._clear()

    def _clear(self):
        self.history = deque(maxlen=self.config["history_decisions"])
        self.pending = None
        self.last_feedback = None
        self.last_rejection = None
        self.issued = 0
        self.rejected = 0
        self.awaiting_feedback = False

    def preflight_runtime(self):
        # Shared transport and RGB encoder check; no Dojo compatibility check,
        # simulator reset, credential copy, inference or API fallback.
        from AgentPolicies.gpt6_astra.tools.runtime_preflight import preflight_native_runtime
        preflight_native_runtime()

    def start_episode(self, context):
        super().start_episode(context)
        self._clear()

    def end_episode(self):
        super().end_episode()
        self._clear()

    def _feedback(self, feedback, *, rejected=False):
        prior = self.last_feedback or {"policy_calls": 0, "action_decisions": 0, "environment_steps": 0}
        available = len(self.pending.action.steps) if self.pending is not None else 0
        if (not self.awaiting_feedback or feedback.policy_calls != self.issued
                or feedback.policy_calls <= prior["policy_calls"]
                or feedback.executed_steps > available
                or feedback.environment_steps != prior["environment_steps"] + feedback.executed_steps
                or feedback.action_decisions != prior["action_decisions"] + int(feedback.executed_steps > 0)):
            raise PolicyError("invalid native action execution receipt")
        if feedback.executed_steps:
            self.history.append({"actions": self.pending.action.steps[:feedback.executed_steps],
                                 "note": self.pending.note})
            self.rule.observe_execution(ExecutionFeedback(feedback.policy_calls, feedback.action_decisions,
                                                          feedback.environment_steps, feedback.executed_steps))
        elif not rejected:
            raise PolicyError("zero-control execution is not an action ACK")
        self.last_feedback = {name: getattr(feedback, name) for name in
                              ("policy_calls", "action_decisions", "environment_steps", "executed_steps")}
        self.pending = None
        self.awaiting_feedback = False

    def observe_execution(self, feedback):
        if not isinstance(feedback, ExecutionFeedback):
            raise PolicyError("expected native action ACK")
        self._feedback(feedback)
        self.last_rejection = None

    def observe_rejection(self, feedback):
        if not isinstance(feedback, ActionRejectionFeedback) or feedback.rejected_actions != self.rejected + 1:
            raise PolicyError("expected consecutive native action rejection")
        self._feedback(feedback, rejected=True)
        self.last_rejection = feedback.to_dict()
        self.rejected = feedback.rejected_actions

    def act(self, observation):
        started = time.monotonic()
        try:
            if self.awaiting_feedback:
                raise ValueError("previous action lacks an acknowledgment")
            expected_step = 0 if self.last_feedback is None else self.last_feedback["environment_steps"]
            if type(observation.step) is not int or observation.step != expected_step:
                raise ValueError("observation differs from acknowledged control count")
            public, images = self._request(observation)
            public.update(current_control=observation.step, recent_confirmed_actions=list(self.history),
                          camera_order=list(self.context.observation_spec.cameras),
                          control_feedback=self.last_feedback or public["control_feedback"],
                          last_action_rejection=self.last_rejection)
            prompt = self.prompt + "\n\nPUBLIC_OBSERVATION_JSON\n" + json.dumps(public, allow_nan=False)
        except (TypeError, ValueError, ImportError, OverflowError, RecursionError):
            raise PolicyCallError("could not encode the permitted native observation",
                usage=Usage(calls=0, latency_s=time.monotonic()-started),
                metadata={"provider_request_attempted": False}, category="infrastructure") from None
        from AgentPolicies.gpt6_astra.transports.codex_cli import send
        self.issued += 1
        self.awaiting_feedback = True
        result = send(prompt, images, self._schema(), timeout_s=self.config["timeout_s"],
                      max_response_bytes=self.config["max_response_bytes"], validate_final_json=False,
                      max_attempts=self.config["max_attempts"], retry_backoff_s=self.config["retry_backoff_s"])
        usage = Usage(**result["usage"])
        try:
            decision = self._action_text(result["text"], usage, result["receipt"])
        except ActionRejected as exc:
            raise ActionRejected(exc.issue, usage=usage, metadata={"provider_receipt": result["receipt"]}) from None
        except PolicyError:
            raise PolicyCallError("policy voluntary-stop rule violated", usage=usage,
                                  metadata={"provider_receipt": result["receipt"]}) from None
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise ActionRejected(ValidationIssue("invalid_action", field="response"), usage=usage,
                                 metadata={"provider_receipt": result["receipt"]}) from None
        if decision.stop:
            self.awaiting_feedback = False
        else:
            self.pending = decision
        return decision
