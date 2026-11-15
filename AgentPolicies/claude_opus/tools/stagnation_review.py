"""Policy-only repeated-command evidence. No SIM, score, action or stop API.

Exact constant-command repetition is a reason to review, not proof of a stall:
velocity commands may keep moving and declared state may contain command values.
No mixed-unit robot-state tolerance, image stability or task predicate is inferred.
"""
import math
from collections import deque


class RepeatedCommandReview:
    """Counts consecutive decisions whose executed controls were all one identical command.

    messages_native.py calls acknowledge() after each ACK that executed controls, and puts feedback()
    into every new packet as policy_review. It holds one episode's count and is rebuilt for each episode.
    """

    def __init__(self, enabled=True, window=4):
        if type(enabled) is not bool:
            raise ValueError("stagnation_review must be a boolean")
        if type(window) is not int or not 2 <= window <= 32:
            raise ValueError("stagnation_window must be an integer in [2,32]")
        self.enabled, self.window = enabled, window
        self.command = None  # the command being repeated, as a tuple; None before any or after a mixed prefix
        self.repeated_decisions = 0  # consecutive decisions that executed only this command
        self.controls = 0  # controls executed across those decisions
        self.before_states = deque(maxlen=window)  # packet state each of the last `window` decisions saw

    def acknowledge(self, executed_actions, before_state):
        """Count only a nonempty confirmed prefix; zero execution has no effect."""
        if not self.enabled or not executed_actions:
            return
        command = tuple(executed_actions[0])
        if any(tuple(row) != command for row in executed_actions):  # mixed commands: clear the count
            self.command = None
            self.repeated_decisions = self.controls = 0
            self.before_states.clear()
            return
        if command != self.command:  # a different constant command starts a new count
            self.command = command
            self.repeated_decisions = self.controls = 0
            self.before_states.clear()
        self.repeated_decisions += 1
        self.controls += len(executed_actions)
        self.before_states.append(None if before_state is None else tuple(before_state))

    def feedback(self, current_state, names):
        result = {"schema_version": "starvla-rsi.policy-repeated-command-review/v1",
            "enabled": self.enabled, "window_decisions": self.window,
            "repeat_interval_decisions": self.window,
            "repeated_executed_decisions": self.repeated_decisions,
            "repeated_controls": self.controls,
            # Due at window, 2*window, ... repeats, not on every repeat past the window.
            "review_due": self.enabled and self.repeated_decisions >= self.window
                          and self.repeated_decisions % self.window == 0,
            "authority": "policy_advisory_not_native_progress_or_success",
            "basis": "exact_identical_constant_commands_in_acknowledged_prefixes",
            "limitations": "Repeated commands may produce useful motion. State may be commanded, not measured. "
                           "No task progress, image stability or success is inferred."}
        if not self.enabled or self.repeated_decisions < self.window:
            return result  # counters only
        before = self.before_states[0]  # state before the first decision of the latest window
        result["public_state_change"] = {
            "available": before is not None and current_state is not None,
            "scope": "latest_window_start_to_current_observation; channel-native units; no common tolerance"}
        if before is not None and current_state is not None:
            if len(before) != len(current_state) or len(before) != len(names):
                raise ValueError("public state schema changed during repeated-command review")
            # delta is None when the difference overflows to infinity.
            result["public_state_change"]["channels"] = [
                {"name": name, "before": a, "after": b,
                 "delta": b - a if math.isfinite(b - a) else None}
                for name, a, b in zip(names, before, current_state)]
        if result["review_due"]:  # the reminder text is added only when a review is due
            result["request"] = (
                "If you judge the task complete and your method enables a completion operation, "
                "you may declare completion now without another review or action. Otherwise: "
                "Recheck the task's observable requirements against current public evidence before choosing again. "
                "Stable images or unchanged objects do not prove completion. Distinguish observed facts, "
                "uncertain conditions and your next check in the brief reason. Inspect available views/crops; "
                "choose a new viewpoint or revise the plan only when justified. If holding is necessary, "
                "state the observable reason and a finite waiting budget, then reassess. "
                "Do not wait indefinitely for termination. No hidden score or reset is authorized; "
                "this reminder forces neither motion nor stopping.")
        return result
