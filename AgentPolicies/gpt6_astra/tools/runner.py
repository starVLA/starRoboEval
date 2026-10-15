"""Reusable agent-side decision loop with explicit execution receipts.

This trusted driver is not the model actor: it retains the administrative
benchmark client and passes only declared observations/counters to Policy.
Recording and source capture are shared tooling under benchkit/;
native task/control/score semantics stay on the benchmark server.
"""

from __future__ import annotations

import re
import secrets
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from benchkit.artifacts import (
    append_jsonl,
    atomic_write_json,
    runtime_provenance,
    utc_now,
)
from benchkit.contracts import (
    ActionRejectionFeedback,
    ControlAcknowledgement,
    EpisodeContext,
    EpisodeSpec,
    ExecutionFeedback,
    JsonValue,
    PolicyDecision,
    PolicyEpisodeSpec,
    Transition,
    Usage,
    ensure_jsonable,
)
from benchkit.errors import (
    ActionRejected, CompatibilityError, EvaluationError, InfrastructureError,
    PolicyCallError, PolicyError, ProtocolError,
)
from benchkit.interfaces import BenchmarkAdapter, EpisodeSession, Policy
from benchkit.source_snapshot import capture_harness_source
from benchkit.reports.run_summary import summarize_run
from benchkit.recording import (
    InteractionRecorder, RecordingOptions, public_error_record,
)
from benchkit.methods import (
    USAGE_ACCOUNTING_VERSION, method_from_policy, normalize_method,
    normalize_component_usage, sum_component_usage,
)
from benchkit.validation import validate_action_vector

SCHEMA_VERSION = "starvla-rsi.eval/v1"


@dataclass(frozen=True)
class RunRequest:
    """Resolved runner settings for one benchmark-policy cell."""

    output_dir: Path
    seed: int = 0
    episode_limit: int | None = None
    max_steps: int = 500
    max_policy_calls: int | None = None
    replan_interval: int | None = None
    run_id: str | None = None
    fail_fast: bool = False
    repository: Path | None = None
    budget_mode: str = "horizon"
    invalid_action_handling: str = "terminate"
    recording: RecordingOptions = RecordingOptions()
    method: Mapping[str, JsonValue] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "output_dir", Path(self.output_dir))
        if not isinstance(self.recording, RecordingOptions):
            raise TypeError("recording must be RecordingOptions")
        if self.invalid_action_handling not in ("terminate", "feedback"):
            raise ValueError("invalid_action_handling must be terminate or feedback")
        if self.invalid_action_handling == "feedback" and (
            type(self.max_policy_calls) is not int or self.max_policy_calls <= 0
        ):
            raise ValueError("action rejection feedback requires a finite positive integer policy-call cap")
        if self.episode_limit is not None and self.episode_limit <= 0:
            raise ValueError("episode_limit must be positive")
        if self.max_steps <= 0:
            raise ValueError("max_steps must be positive")
        if self.max_policy_calls is not None and self.max_policy_calls <= 0:
            raise ValueError("max_policy_calls must be positive")
        if self.replan_interval is not None and self.replan_interval <= 0:
            raise ValueError("replan_interval must be positive")
        if self.budget_mode not in ("horizon", "decisions"):
            raise ValueError("budget_mode must be horizon or decisions")
        if self.budget_mode == "decisions":
            if any(type(value) is not int or value <= 0 for value in
                   (self.max_policy_calls, self.replan_interval, self.max_steps)):
                raise ValueError("decision budget requires positive integer calls, prefix and step cap")
            if self.max_steps != self.max_policy_calls * self.replan_interval:
                raise ValueError("decision-mode max_steps must equal max_policy_calls * replan_interval")
        if self.run_id is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.run_id):
            raise ValueError("run_id may contain only letters, digits, dot, underscore, and dash")


class EvaluationRunner:
    """Run policy/benchmark pairs and emit schema-versioned artifacts."""

    def run(self, benchmark: BenchmarkAdapter, policy: Policy, request: RunRequest) -> Path:
        if request.invalid_action_handling == "feedback" and not callable(
            getattr(policy, "observe_rejection", None)
        ):
            raise CompatibilityError("action rejection feedback requires policy.observe_rejection")
        adapter_mode = getattr(benchmark, "budget_mode", "horizon")
        if adapter_mode != request.budget_mode:
            raise ProtocolError("runner and benchmark budget_mode must match")
        required_prefix = getattr(benchmark, "required_replan_interval", None)
        if required_prefix is not None:
            if type(required_prefix) is not int or required_prefix <= 0:
                raise ProtocolError("benchmark required_replan_interval must be a positive integer")
            if type(request.replan_interval) is not int or request.replan_interval != required_prefix:
                raise ProtocolError("runner replan_interval does not satisfy the benchmark observation interface")
        if request.budget_mode == "decisions":
            for name, expected in (("max_policy_calls", request.max_policy_calls),
                                   ("replan_interval", request.replan_interval),
                                   ("environment_step_cap", request.max_steps)):
                if getattr(benchmark, name, None) != expected:
                    raise ProtocolError(f"runner and benchmark decision budget differ: {name}")
        method = (method_from_policy(policy.descriptor) if request.method is None
                  else normalize_method(request.method))
        errors = list(policy.compatibility_errors(benchmark.observation_spec, benchmark.action_spec))
        if errors:
            raise CompatibilityError("; ".join(errors))

        episodes = list(benchmark.episodes(request.seed, request.episode_limit))
        if not episodes:
            raise ProtocolError("benchmark selected zero episodes")
        episode_ids = [episode.id for episode in episodes]
        if len(episode_ids) != len(set(episode_ids)):
            raise ProtocolError("benchmark episode ids must be unique")
        episode_paths = [self._safe_component(episode_id) for episode_id in episode_ids]
        if len(episode_paths) != len(set(episode_paths)):
            raise ProtocolError("benchmark episode ids collide after artifact path normalization")

        run_id = request.run_id or self._new_run_id(benchmark.descriptor.name, policy.descriptor.name)
        run_dir = request.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)

        try:
            atomic_write_json(run_dir / "status.json", {"status": "initializing", "updated_at": utc_now()})
            source_snapshot = capture_harness_source(run_dir)
            model_snapshot = None
            if "model_profile" in policy.descriptor.parameters:
                from benchkit.model_profiles import capture_policy_source

                model_snapshot = capture_policy_source(run_dir, policy)
            manifest: dict[str, JsonValue] = {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "created_at": utc_now(),
                "benchmark": benchmark.descriptor.to_dict(),
                "policy": policy.descriptor.to_dict(),
                "method": method,
                "method_origin": ("participant_declaration" if request.method is not None
                                  else "legacy_policy_projection"),
                "recording": request.recording.to_dict(),
                "observation_spec": benchmark.observation_spec.to_dict(),
                "action_spec": benchmark.action_spec.to_dict(),
                "protocol": {
                    "seed": request.seed,
                    "episode_limit": request.episode_limit,
                    "episode_ids": episode_ids,
                    "max_steps": request.max_steps,
                    "max_policy_calls": request.max_policy_calls,
                    "replan_interval": request.replan_interval,
                    "budget_mode": request.budget_mode,
                    "primary_budget": "policy_decisions" if request.budget_mode == "decisions" else "first_exhausted_limit",
                    "fail_fast": request.fail_fast,
                    "execution_feedback_version": "starvla-rsi.execution-feedback/v1",
                    **({"control_acknowledgement_version": "starvla-rsi.control-acknowledgement/v1",
                        "control_feedback_schema": benchmark.observation_spec.control_feedback_schema}
                       if benchmark.observation_spec.control_feedback_schema is not None else {}),
                    "invalid_action_handling": request.invalid_action_handling,
                    "usage_accounting_version": USAGE_ACCOUNTING_VERSION,
                },
                "harness_source": source_snapshot,
                "runtime": runtime_provenance(
                    request.repository, evaluation_root=Path(source_snapshot["source_root"]),
                ),
            }
            if model_snapshot is not None:
                manifest["model_source"] = model_snapshot
            if request.invalid_action_handling == "feedback":
                manifest["protocol"]["action_rejection_feedback_version"] = (
                    "starvla-rsi.action-rejection-feedback/v1"
                )
            if required_prefix is not None:
                manifest["protocol"]["required_replan_interval"] = required_prefix
            service_provenance = getattr(benchmark, "execution_provenance", None)
            if callable(service_provenance):
                provenance = ensure_jsonable(service_provenance(), "benchmark service provenance")
                if not isinstance(provenance, dict):
                    raise ProtocolError("benchmark service provenance must be a JSON object")
                manifest["benchmark_service"] = provenance
            atomic_write_json(run_dir / "manifest.json", manifest, overwrite=False)
            atomic_write_json(run_dir / "status.json", {"status": "running", "updated_at": utc_now()})
        except Exception as exc:
            failure = {
                "schema_version": SCHEMA_VERSION, "run_id": run_id,
                "phase": "initialization", "timestamp": utc_now(),
                "error": {"type": type(exc).__name__, "category": self._error_category(exc),
                          "message": str(exc), "traceback": traceback.format_exc()},
            }
            atomic_write_json(run_dir / "initialization_error.json", failure, overwrite=False)
            atomic_write_json(run_dir / "status.json", {
                "status": "initialization_failed", "updated_at": utc_now(),
                "episodes_written": 0, "error_path": "initialization_error.json",
            })
            raise

        results: list[dict[str, JsonValue]] = []
        for episode_index, episode in enumerate(episodes):
            result = self._run_episode(
                benchmark, policy, episode, request, run_dir, f"episode-{episode_index:06d}", method
            )
            results.append(result)
            append_jsonl(run_dir / "episodes.jsonl", result)
            if request.fail_fast and result["status"] == "error":
                break

        summary = self._summarize(run_id, benchmark.descriptor.name, policy.descriptor.name, results)
        component_usage = {model["id"]: Usage().to_dict() for model in method["models"]}
        for result in results:
            component_usage = sum_component_usage(component_usage, result["component_usage"], method)
        summary["component_usage"] = component_usage
        atomic_write_json(run_dir / "summary.json", summary)
        final_status = "completed" if all(result["status"] == "completed" for result in results) else "completed_with_errors"
        atomic_write_json(
            run_dir / "status.json",
            {"status": final_status, "updated_at": utc_now(), "episodes_written": len(results)},
        )
        return run_dir

    def _run_episode(
        self,
        benchmark: BenchmarkAdapter,
        policy: Policy,
        episode: EpisodeSpec,
        request: RunRequest,
        run_dir: Path,
        policy_episode_id: str,
        method: dict,
    ) -> dict[str, JsonValue]:
        episode_dir = run_dir / "episodes" / self._safe_component(episode.id)
        episode_dir.mkdir(parents=True, exist_ok=False)
        events_path = episode_dir / "events.jsonl"
        recorder = InteractionRecorder(episode_dir / "agent_interactions.jsonl", request.recording)
        component_usage = {model["id"]: Usage().to_dict() for model in method["models"]}

        def accumulate_component_usage(metadata):
            nonlocal component_usage
            try:
                reported = normalize_component_usage(metadata.get("component_usage"), method)
            except (TypeError, ValueError, OverflowError, RecursionError):
                recorder.warn("invalid_component_usage_unavailable")
                reported = normalize_component_usage(None, method)
            component_usage = sum_component_usage(component_usage, reported, method)

        policy_scratch = None
        session_scratch = None
        discard_session_artifacts = False
        started_at = time.monotonic()
        session: EpisodeSession | None = None
        policy_started = False
        usage = Usage()
        usage_pending_since: float | None = None
        policy_call_failure: PolicyCallError | None = None
        terminal_rejection_phase: str | None = None
        policy_calls = 0
        action_decisions = 0
        rejected_actions = 0
        env_steps = 0
        reward_sum = 0.0
        termination_reason = "unknown"
        metrics: dict[str, JsonValue] = {}
        artifacts: dict[str, JsonValue] = {}
        status = "error"
        error: dict[str, JsonValue] | None = None
        feedback_schema = benchmark.observation_spec.control_feedback_schema

        recorder.event(
            events_path,
            {"event": "episode_start", "timestamp": utc_now(), "episode": episode.to_dict()},
        )
        try:
            session = benchmark.open_episode(episode)
            configure_session_recording = getattr(session, "configure_recording", None)
            if callable(configure_session_recording):
                configure_session_recording(request.recording)
            bind_artifact_dir = getattr(session, "bind_artifact_dir", None)
            if bind_artifact_dir is not None:
                if not callable(bind_artifact_dir):
                    raise ProtocolError("session.bind_artifact_dir must be callable")
                artifact_dir = episode_dir / "artifacts"
                if (not request.recording.retain_unknown_artifacts
                        and not callable(configure_session_recording)):
                    session_scratch = tempfile.TemporaryDirectory(prefix="rsi-session-recording-")
                    artifact_dir = Path(session_scratch.name) / "artifacts"
                    discard_session_artifacts = True
                elif not request.recording.retain_all and not callable(configure_session_recording):
                    recorder.warn("session_media_retention_unsupported_preserved_artifacts")
                artifact_dir.mkdir(exist_ok=False)
                bind_artifact_dir(artifact_dir)
            observation = session.reset()
            if observation.control_feedback is not None:
                raise ProtocolError("reset cannot carry a control acknowledgement")
            recorder.event(
                events_path,
                {"event": "observation", "timestamp": utc_now(), "observation": observation.log_view()},
            )
            context = EpisodeContext(
                benchmark=benchmark.descriptor,
                episode=PolicyEpisodeSpec(
                    id=policy_episode_id,
                    task=episode.task,
                    instruction=observation.instruction,
                ),
                observation_spec=benchmark.observation_spec,
                action_spec=benchmark.action_spec,
                max_steps=request.max_steps,
                max_policy_calls=request.max_policy_calls,
                replan_interval=request.replan_interval,
                budget_mode=request.budget_mode,
                invalid_action_handling=request.invalid_action_handling,
            )
            # Model-owned diagnostics/workspace exports; no SIM client or
            # evaluator-private artifact directory is passed to the actor.
            configure_policy_recording = getattr(policy, "configure_recording", None)
            if callable(configure_policy_recording):
                configure_policy_recording(request.recording)
            bind_recorder = getattr(policy, "bind_interaction_recorder", None)
            if callable(bind_recorder):
                bind_recorder(recorder)
            bind_policy_artifacts = getattr(policy, "bind_artifact_dir", None)
            if bind_policy_artifacts is not None:
                if not callable(bind_policy_artifacts):
                    raise ProtocolError("policy.bind_artifact_dir must be callable")
                artifact_destination = episode_dir / "policy_artifacts"
                if not request.recording.retain_unknown_artifacts and not (
                    callable(configure_policy_recording)
                    and getattr(policy, "recording_configurable", False) is True
                ):
                    # Unknown policy exports cannot be classified by filenames.
                    # Keep required runtime files available, but do not retain
                    # an opaque bundle containing disabled categories.
                    policy_scratch = tempfile.TemporaryDirectory(prefix="rsi-policy-recording-")
                    artifact_destination = Path(policy_scratch.name) / "policy_artifacts"
                elif not request.recording.retain_all and not (
                    callable(configure_policy_recording)
                    and getattr(policy, "recording_configurable", False) is True
                ):
                    recorder.warn("policy_media_retention_unsupported_preserved_artifacts")
                bind_policy_artifacts(artifact_destination)
            policy_started = True
            policy.start_episode(context)

            while env_steps < request.max_steps:
                if (
                    request.max_policy_calls is not None
                    and policy_calls >= request.max_policy_calls
                ):
                    termination_reason = "runner:policy_call_limit"
                    break
                policy_calls += 1
                control_acks = [] if feedback_schema is not None else None
                recorder.event(
                    events_path,
                    {"event": "policy_call_start", "timestamp": utc_now(), "policy_call": policy_calls},
                )
                usage_pending_since = time.monotonic()
                policy_call_failure = None
                try:
                    decision = policy.act(observation)
                except PolicyCallError as exc:
                    policy_call_failure = exc
                    if isinstance(exc, ActionRejected):
                        rejected_actions += 1
                        if request.invalid_action_handling == "feedback":
                            accumulate_component_usage(exc.metadata)
                            usage = usage + exc.usage
                            usage_pending_since = None
                            self._rejection_feedback(policy, events_path, exc, recorder=recorder,
                                phase="policy_act", policy_calls=policy_calls,
                                action_decisions=action_decisions, environment_steps=env_steps,
                                executed_steps=0, rejected_actions=rejected_actions,
                                control_acks=() if control_acks is not None else None,
                                additional_usage=exc.usage, usage_recorded_in="action_rejected")
                            policy_call_failure = None
                            continue
                        terminal_rejection_phase = "policy_act"
                    raise
                except (TypeError, ValueError) as exc:
                    raise PolicyError(f"policy failed to produce a valid decision: {exc}") from exc
                if not isinstance(decision, PolicyDecision):
                    raise PolicyError(f"policy returned {type(decision).__name__}, expected PolicyDecision")
                usage = usage + decision.usage
                accumulate_component_usage(decision.metadata)
                usage_pending_since = None
                decision_event: dict[str, JsonValue] = {
                    "event": "policy_decision",
                    "timestamp": utc_now(),
                    "policy_call": policy_calls,
                    "note": decision.note,
                    "metadata": ensure_jsonable(decision.metadata),
                    "usage": decision.usage.to_dict(),
                    "stop": decision.stop,
                    "stop_reason": decision.stop_reason,
                    "chunk_length": 0 if decision.action is None else len(decision.action.steps),
                }
                recorder.event(events_path, decision_event)
                if decision.stop:
                    termination_reason = f"policy:{decision.stop_reason}"
                    break
                if decision.action is None:
                    raise PolicyError("non-stop decision omitted an action chunk")

                if request.invalid_action_handling == "feedback":
                    try:
                        # Validate the WHOLE proposed chunk, including any
                        # unplayed suffix, before issuing its first control.
                        chunk = tuple(validate_action_vector(benchmark.action_spec, raw_action)
                                      for raw_action in decision.action.steps)
                    except ActionRejected as exc:
                        rejected_actions += 1
                        self._rejection_feedback(policy, events_path, exc, recorder=recorder,
                            phase="action_spec", policy_calls=policy_calls,
                            action_decisions=action_decisions, environment_steps=env_steps,
                            executed_steps=0, rejected_actions=rejected_actions,
                            control_acks=() if control_acks is not None else None,
                            additional_usage=Usage(), usage_recorded_in="policy_decision")
                        continue
                else:
                    try:
                        chunk = tuple(
                            benchmark.action_spec.validate(raw_action)
                            for raw_action in decision.action.steps
                        )
                    except (TypeError, ValueError, OverflowError) as exc:
                        raise PolicyError(f"policy action violates the benchmark contract: {exc}") from exc
                steps_to_play = len(chunk)
                if request.replan_interval is not None:
                    steps_to_play = min(steps_to_play, request.replan_interval)
                steps_to_play = min(steps_to_play, request.max_steps - env_steps)
                recorder.event(
                    events_path,
                    {
                        "event": "action_chunk",
                        "timestamp": utc_now(),
                        "policy_call": policy_calls,
                        "actions": ensure_jsonable(chunk),
                        "maximum_executed_prefix": steps_to_play,
                    },
                )
                executed_steps = 0
                rejected_control = None
                for chunk_index, action in enumerate(chunk[:steps_to_play]):
                    try:
                        transition = session.step(action)
                    except ActionRejected as exc:
                        if request.invalid_action_handling != "feedback":
                            rejected_actions += 1
                            terminal_rejection_phase = "session_step"
                            raise
                        if exc.usage != Usage():
                            raise ProtocolError("session action rejection cannot report policy usage") from None
                        rejected_actions += 1
                        rejected_control = exc
                        break
                    if not isinstance(transition, Transition):
                        raise ProtocolError(
                            f"episode returned {type(transition).__name__}, expected Transition"
                        )
                    env_steps += 1
                    executed_steps += 1
                    if chunk_index == 0:
                        action_decisions += 1
                    reward_sum += transition.reward
                    observation = transition.observation
                    recorder.event(
                        events_path,
                        {
                            "event": "environment_step",
                            "timestamp": utc_now(),
                            "policy_call": policy_calls,
                            "chunk_index": chunk_index,
                            "environment_step": env_steps,
                            "action": action,
                            "reward": transition.reward,
                            "terminated": transition.terminated,
                            "truncated": transition.truncated,
                            "info": ensure_jsonable(transition.info),
                            "observation": observation.log_view(),
                        },
                    )
                    # Copy only the benchmark-declared public channel. Private
                    # reward, terminal flags and Transition.info never cross.
                    payload = observation.control_feedback
                    if feedback_schema is not None:
                        if (not isinstance(payload, Mapping) or payload.get("schema") != feedback_schema
                                or observation.step != env_steps):
                            raise ProtocolError("missing or uncorrelated public control acknowledgement")
                        control_acks.append(ControlAcknowledgement(env_steps, observation.step, payload))
                    elif payload is not None:
                        raise ProtocolError("undeclared public control acknowledgement")
                    if transition.terminated:
                        termination_reason = "environment:terminated"
                        break
                    if (request.budget_mode == "decisions"
                            and env_steps >= request.max_steps
                            and policy_calls >= request.max_policy_calls):
                        termination_reason = "runner:policy_call_limit"
                        break
                    if transition.truncated:
                        termination_reason = "environment:truncated"
                        break
                    if env_steps >= request.max_steps:
                        termination_reason = "runner:step_limit"
                        break
                if rejected_control is not None:
                    # A typed service rejection confirms that THIS vector did
                    # not execute. Retain the last ACK observation and all
                    # earlier prefix controls; never reset, replay or invent a
                    # zero-control outcome for a partly executed decision.
                    self._rejection_feedback(policy, events_path, rejected_control, recorder=recorder,
                        phase="session_step", policy_calls=policy_calls,
                        action_decisions=action_decisions, environment_steps=env_steps,
                        executed_steps=executed_steps, rejected_actions=rejected_actions,
                        control_acks=tuple(control_acks) if control_acks is not None else None,
                        additional_usage=Usage(), usage_recorded_in="policy_decision")
                    continue
                observe_execution = getattr(policy, "observe_execution", None)
                if observe_execution is not None:
                    if not callable(observe_execution):
                        raise PolicyError("policy.observe_execution must be callable")
                    observe_execution(ExecutionFeedback(
                        policy_calls=policy_calls,
                        action_decisions=action_decisions,
                        environment_steps=env_steps,
                        executed_steps=executed_steps,
                        control_acks=tuple(control_acks) if control_acks is not None else None,
                    ))
                if termination_reason != "unknown":
                    break

            if termination_reason == "unknown":
                termination_reason = "runner:step_limit"

            normalized_metrics = ensure_jsonable(session.metrics(), "episode metrics")
            if not isinstance(normalized_metrics, dict):
                raise ProtocolError("episode metrics must be a JSON object")
            if not isinstance(normalized_metrics.get("success"), bool):
                raise ProtocolError("episode metrics must contain boolean 'success'")
            metrics = normalized_metrics
            status = "completed"
        except Exception as exc:  # artifact boundary: preserve typed and third-party failures
            reported_call_failure = usage_pending_since is not None and exc is policy_call_failure
            if usage_pending_since is not None:
                failed_usage = (policy_call_failure.usage if reported_call_failure else
                                Usage.unavailable(latency_s=time.monotonic() - usage_pending_since))
                usage = usage + failed_usage
                accumulate_component_usage(policy_call_failure.metadata if reported_call_failure else {})
            error = {
                "type": type(exc).__name__,
                "category": self._error_category(exc),
                "message": str(exc),
            }
            if isinstance(exc, ActionRejected):
                error["issue"] = exc.issue.to_dict()
                if terminal_rejection_phase is not None:
                    error["action_rejection_phase"] = terminal_rejection_phase
            if request.invalid_action_handling == "feedback" and usage_pending_since is not None:
                error.update(policy_call=policy_calls, usage=failed_usage.to_dict())
            if not isinstance(exc, PolicyCallError):
                error["traceback"] = traceback.format_exc()
            if reported_call_failure:
                # Never fabricate a normal decision to retain a failed call's
                # receipt. Chained provider exceptions may contain private data.
                error.update(policy_call=policy_calls, usage=policy_call_failure.usage.to_dict(),
                             metadata=policy_call_failure.metadata)
            termination_reason = f"error:{error['category']}"
            recorder.event(
                events_path,
                {"event": "error", "timestamp": utc_now(), "error": error},
            )
        finally:
            cleanup_errors: list[str] = []
            if session is not None:
                try:
                    normalized_artifacts = ensure_jsonable(session.artifacts(), "episode artifacts")
                    if not isinstance(normalized_artifacts, dict) or any(
                        not isinstance(value, str) for value in normalized_artifacts.values()
                    ):
                        raise ProtocolError("episode artifacts must map names to string paths")
                    artifacts = {} if discard_session_artifacts else normalized_artifacts
                except Exception as exc:
                    artifact_error = {
                        "type": type(exc).__name__,
                        "category": self._error_category(exc),
                        "message": str(exc),
                        "traceback": traceback.format_exc(),
                    }
                    if error is None:
                        error = artifact_error
                        status = "error"
                        termination_reason = f"error:{error['category']}"
                    else:
                        error["artifact_error"] = artifact_error
                    recorder.event(
                        events_path,
                        {"event": "artifact_error", "timestamp": utc_now(), "error": artifact_error},
                    )
            if policy_started:
                try:
                    policy.end_episode()
                except Exception as exc:  # cleanup must be visible without hiding the primary result
                    cleanup_errors.append(f"policy.end_episode: {type(exc).__name__}: {exc}")
            if policy_scratch is not None:
                try:
                    policy_scratch.cleanup()
                except Exception:
                    recorder.warn("policy_scratch_cleanup_failed")
            if session is not None:
                try:
                    session.close()
                except Exception as exc:
                    cleanup_errors.append(f"session.close: {type(exc).__name__}: {exc}")
            if session_scratch is not None:
                try:
                    session_scratch.cleanup()
                except Exception:
                    recorder.warn("session_scratch_cleanup_failed")
            if cleanup_errors:
                if error is None:
                    status = "error"
                    termination_reason = "error:infrastructure"
                    error = {
                        "type": "CleanupError",
                        "category": "infrastructure",
                        "message": "; ".join(cleanup_errors),
                    }
                else:
                    error["cleanup_errors"] = cleanup_errors

        result: dict[str, JsonValue] = {
            "schema_version": SCHEMA_VERSION,
            "episode": episode.to_dict(),
            "status": status,
            "success": metrics.get("success") if status == "completed" else None,
            "termination_reason": termination_reason,
            "environment_steps": env_steps,
            "policy_calls": policy_calls,
            "action_decisions": action_decisions,
            "rejected_actions": rejected_actions,
            "reward_sum": reward_sum,
            "duration_s": time.monotonic() - started_at,
            "usage": usage.to_dict(),
            "component_usage": component_usage,
            "metrics": metrics,
            "artifacts": artifacts,
            "error": public_error_record(error, request.recording),
            "recording": {**request.recording.to_dict(),
                          "agent_events_written": recorder.events_written,
                          "warnings": list(recorder.warnings)},
        }
        atomic_write_json(episode_dir / "result.json", result)
        recorder.event(
            events_path,
            {"event": "episode_end", "timestamp": utc_now(), "result": result},
        )
        if result["recording"]["warnings"] != recorder.warnings:
            result["recording"]["warnings"] = list(recorder.warnings)
            atomic_write_json(episode_dir / "result.json", result)
        return result

    @staticmethod
    def _rejection_feedback(policy: Policy, events_path: Path, rejection: ActionRejected, *,
                            recorder: InteractionRecorder,
                            phase: str, policy_calls: int, action_decisions: int,
                            environment_steps: int, executed_steps: int,
                            rejected_actions: int, additional_usage: Usage,
                            usage_recorded_in: str,
                            control_acks: tuple[ControlAcknowledgement, ...] | None = None) -> None:
        feedback = ActionRejectionFeedback(issue=rejection.issue,
            policy_calls=policy_calls, action_decisions=action_decisions,
            environment_steps=environment_steps, executed_steps=executed_steps,
            rejected_actions=rejected_actions, control_acks=control_acks)
        recorder.event(events_path, {"event": "action_rejected", "timestamp": utc_now(),
            "policy_call": policy_calls, "phase": phase, "feedback": feedback.to_dict(),
            "usage": additional_usage.to_dict(), "usage_recorded_in": usage_recorded_in,
            "metadata": rejection.metadata})
        # No receipts, raw exceptions, reward/terminal flags or native metadata
        # cross this hook. Hook errors are terminal; no inner model retry.
        policy.observe_rejection(feedback)

    @staticmethod
    def _summarize(
        run_id: str,
        benchmark_name: str,
        policy_name: str,
        results: list[dict[str, JsonValue]],
    ) -> dict[str, JsonValue]:
        return summarize_run(run_id, benchmark_name, policy_name, results)

    @staticmethod
    def _error_category(error: Exception) -> str:
        if isinstance(error, PolicyCallError):
            return error.category
        if isinstance(error, PolicyError):
            return "policy"
        if isinstance(error, ProtocolError):
            return "protocol"
        if isinstance(error, InfrastructureError):
            return "infrastructure"
        if isinstance(error, EvaluationError):
            return "evaluation"
        return "infrastructure"

    @staticmethod
    def _safe_component(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
        return normalized or "episode"

    @classmethod
    def _new_run_id(cls, benchmark: str, policy: str) -> str:
        from datetime import datetime, timezone

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return "-".join(
            (
                cls._safe_component(benchmark),
                cls._safe_component(policy),
                timestamp,
                secrets.token_hex(3),
            )
        )
