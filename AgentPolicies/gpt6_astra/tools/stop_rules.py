"""Opt-in policy persistence rules; never a benchmark rule or success oracle.

The v1 spelling is retained only to identify historical, frozen evaluator-owned
records. New policies use v2 with explicit policy ownership. The runner receives
no minimum and never substitutes actions or retries a refused stop.
"""

from __future__ import annotations

from dataclasses import replace

from benchkit.contracts import EpisodeContext, ExecutionFeedback, PolicyDecision
from benchkit.errors import PolicyError

STOP_CONSTRAINT_VERSION = "minimum-action-decisions/v2"


def validate_minimum(value: int) -> int:
    if type(value) is not int or value < 0:
        raise ValueError("min_action_decisions_before_give_up must be a nonnegative integer")
    return value


def stop_constraint(minimum: int) -> dict:
    """Serializable policy configuration, including the unrestricted choice."""
    validate_minimum(minimum)
    return {
        "stop_constraint_version": STOP_CONSTRAINT_VERSION,
        "min_action_decisions_before_give_up": minimum,
        "early_policy_stop_exception": "safety_stop_with_nonempty_note",
        "scope": "policy",
    }


def validate_policy_stop(decision: PolicyDecision, completed: int, minimum: int) -> None:
    """Reject early voluntary stops without retrying or inventing a control.

    A safety stop never awards success. Native termination, errors and exhausted
    limits are handled by the runner independently and need not reach the floor.
    """
    validate_minimum(minimum)
    if not decision.stop or minimum == 0:
        return
    if decision.stop_reason == "safety_stop":
        if not isinstance(decision.note, str) or not decision.note.strip():
            raise PolicyError("safety_stop requires a nonempty safety explanation in note")
        return
    if completed < minimum:
        raise PolicyError(
            f"voluntary stop before {minimum} executed action decisions: only {completed} completed"
        )


def stop_constraint_prompt(minimum: int) -> str:
    validate_minimum(minimum)
    if not minimum:
        return ""
    return (
        f"Voluntary-stop rule ({STOP_CONSTRAINT_VERSION}): complete at least {minimum} "
        "non-stop action decisions before submitting any voluntary stop, including give_up. "
        "Each counted decision must execute at least one permitted native control. "
        "The subsequent stop response is an additional decision. Do not submit repeated "
        "stops or request extra observations. An early voluntary stop is a recorded policy "
        "error, not a request to retry. Native termination, success, exhausted limits and "
        "errors may end the episode earlier. If continued motion is unsafe, you may submit "
        "stop_reason=safety_stop with a nonempty safety explanation in note at any time; "
        "that does not award task success. This is this policy's persistence setting, "
        "not a benchmark requirement. Public control_feedback reports the actually "
        "executed action-decision count, and policy_constraints reports whether this "
        "policy permits voluntary stopping."
    )


def with_stop_rule_prompt(prompt: str, minimum: int) -> str:
    """Append the frozen policy instruction exactly once, not during rollout."""
    if not isinstance(prompt, str):
        raise ValueError("policy prompt must be a string")
    suffix = stop_constraint_prompt(minimum)
    if not suffix or prompt.endswith(suffix):
        return prompt
    return prompt + ("\n\n" if prompt else "") + suffix


def legacy_stop_constraint(minimum: int) -> dict:
    """Historical v1 metadata for read-only verification, not new execution."""
    validate_minimum(minimum)
    return {} if minimum == 0 else {
        "stop_constraint_version": "minimum-action-decisions/v1",
        "min_action_decisions_before_give_up": minimum,
        "early_policy_stop_exception": "safety_stop_with_nonempty_note",
    }


def legacy_stop_constraint_prompt(minimum: int) -> str:
    """The exact historical v1 prompt bytes for frozen-campaign verification."""
    validate_minimum(minimum)
    if not minimum:
        return ""
    return (
        f"Voluntary-stop rule (minimum-action-decisions/v1): complete at least {minimum} "
        "non-stop action decisions before submitting any voluntary stop, including give_up. "
        "Each counted decision must execute at least one permitted native control. "
        "The subsequent stop response is an additional decision. Do not submit repeated "
        "stops or request extra observations. An early voluntary stop is a recorded policy "
        "error, not a request to retry. Native termination, success, exhausted limits and "
        "errors may end the episode earlier. If continued motion is unsafe, you may submit "
        "stop_reason=safety_stop with a nonempty safety explanation in note at any time; "
        "that does not award task success. The public budgets report the completed action "
        "decision count and whether voluntary stopping is allowed."
    )


class VoluntaryStopRule:
    """A policy-local state machine driven only by confirmed execution counts."""

    def __init__(self, minimum: int = 0):
        self.minimum = validate_minimum(minimum)
        self.feedback: ExecutionFeedback | None = None

    @property
    def parameters(self) -> dict:
        return stop_constraint(self.minimum)

    @property
    def completed(self) -> int:
        return 0 if self.feedback is None else self.feedback.action_decisions

    def start_episode(self, context: EpisodeContext) -> None:
        # Hard limits are evaluator-owned and may end before this preference.
        # An unreachable preference is not grounds to change the benchmark.
        self.feedback = None

    def observe_execution(self, feedback: ExecutionFeedback) -> None:
        if not isinstance(feedback, ExecutionFeedback):
            raise PolicyError("policy stop rule requires typed execution feedback")
        prior = self.feedback
        if feedback.action_decisions != self.completed + 1:
            raise PolicyError("policy execution feedback action counter is not consecutive")
        prior_steps = 0 if prior is None else prior.environment_steps
        if feedback.environment_steps != prior_steps + feedback.executed_steps:
            raise PolicyError("policy execution feedback control counter is inconsistent")
        if prior is not None and feedback.policy_calls <= prior.policy_calls:
            raise PolicyError("policy execution feedback call counter is not increasing")
        self.feedback = feedback

    def validate(self, decision: PolicyDecision) -> None:
        validate_policy_stop(decision, self.completed, self.minimum)

    def public_view(self) -> dict:
        return {**self.parameters,
                "voluntary_stop_allowed": self.completed >= self.minimum}

    def feedback_view(self) -> dict:
        return (self.feedback.to_dict() if self.feedback is not None else {
            "policy_calls": 0, "action_decisions": 0, "environment_steps": 0, "executed_steps": 0,
        })


class MinimumActionDecisionsPolicy:
    """Explicit optional decorator for policies that choose a persistence floor.

    Native success and hard limits remain entirely outside this wrapper. A
    refused stop raises a policy error on the original call: no synthetic action,
    extra observation, or automatic retry. Model factories should opt in and
    freeze this file, the chosen parameter, and any actor-facing prompt.
    """

    def __init__(self, policy, minimum: int):
        self.policy = policy
        self.rule = VoluntaryStopRule(minimum)
        self.descriptor = replace(policy.descriptor, parameters={
            **policy.descriptor.parameters, "policy_stop_rule": self.rule.parameters,
        })

    def compatibility_errors(self, observation_spec, action_spec):
        return self.policy.compatibility_errors(observation_spec, action_spec)

    def start_episode(self, context: EpisodeContext) -> None:
        self.rule.start_episode(context)
        self.policy.start_episode(context)

    def act(self, observation):
        decision = self.policy.act(observation)
        if not isinstance(decision, PolicyDecision):
            raise PolicyError("wrapped policy did not return PolicyDecision")
        self.rule.validate(decision)
        return decision

    def observe_execution(self, feedback: ExecutionFeedback) -> None:
        self.rule.observe_execution(feedback)
        callback = getattr(self.policy, "observe_execution", None)
        if callback is not None:
            if not callable(callback):
                raise PolicyError("wrapped policy.observe_execution must be callable")
            callback(feedback)

    def end_episode(self) -> None:
        self.policy.end_episode()
