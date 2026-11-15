"""Reusable agent-side decision loop with explicit execution receipts.

This trusted driver is not the model actor: it retains the administrative
benchmark client and passes only declared observations/counters to Policy.
Recording is shared tooling under benchkit/; the manifest records the Git
revision and dirty flag, while native task/control/score semantics stay on
the benchmark server.

How one run moves through this file:

    EvaluationRunner.run        check the protocol, write manifest.json, play each episode
      _EpisodeRun.run           one episode, in this order:
        _open_session           claim the case and reset it -> first observation
        _start_policy           give the policy the public episode context
        _decision_loop          until a stop or a limit:
          _call_policy            policy.act(observation) -> PolicyDecision
          _validated_chunk        check the decision's action vectors
          _execute                step the controls, then tell the policy what ran
        _collect_metrics        native success from the benchmark
        _close                  artifacts, policy.end_episode, session.close (always)
        _write_result           result.json; run() also appends it to episodes.jsonl
      summary.json, status.json after the last episode

Files of one run, under output_dir/run_id/:

    manifest.json, status.json, episodes.jsonl, summary.json
    episodes/<episode id>/      events.jsonl, agent_interactions.jsonl, result.json,
                                artifacts/ (benchmark side), policy_artifacts/ (policy side)
"""

from __future__ import annotations

import math
import re
import secrets
import tempfile
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

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
    EpisodeUsage,
    ExecutionFeedback,
    JsonValue,
    PolicyDecision,
    PolicyEpisodeSpec,
    Transition,
    Usage,
    ensure_jsonable,
    episode_step_limit,
)
from benchkit.errors import (
    ActionRejected, CompatibilityError, EvaluationError, InfrastructureError,
    PolicyCallError, PolicyError, ProtocolError,
)
from benchkit.interfaces import BenchmarkAdapter, EpisodeSession, Policy
from benchkit.reports.run_summary import summarize_run
from benchkit.driver.recording import (
    InteractionRecorder, RecordingOptions, public_error_record,
)
from benchkit.driver.methods import (
    USAGE_ACCOUNTING_VERSION, method_from_policy, normalize_method,
    normalize_component_usage, sum_component_usage,
)
from benchkit.validation import validate_action_vector

SCHEMA_VERSION = "starvla-rsi.eval/v1"
INSTRUCTION_CHANGE_HANDLING = "replan-after-ack/v1"


@dataclass(frozen=True)
class RunRequest:
    """Resolved runner settings for one benchmark-policy cell."""

    output_dir: Path  # the run directory is created under it
    seed: int = 0  # passed to benchmark.episodes(); the service maps it to its schedule
    episode_limit: int | None = None  # how many scheduled episodes to run; None: all
    max_steps: int = 500  # controls per episode
    max_policy_calls: int | None = None  # policy calls per episode, rejected ones included
    replan_interval: int | None = None  # most controls executed from one decision; None: the whole chunk
    run_id: str | None = None  # run directory name; generated when None
    fail_fast: bool = False  # stop after the first episode that ends in an error
    repository: Path | None = None  # its git revision and dirty flag go into the manifest
    invalid_action_handling: str = "terminate"  # "feedback" returns invalid actions to the policy
    recording: RecordingOptions = RecordingOptions()  # what is kept; never changes inputs or scoring
    method: Mapping[str, JsonValue] | None = None  # declared method; None derives it from the policy

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
        if self.run_id is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.run_id):
            raise ValueError("run_id may contain only letters, digits, dot, underscore, and dash")


class EvaluationRunner:
    """Run policy/benchmark pairs and emit schema-versioned artifacts."""

    # Reading step 3 of 6: one run. Checks the protocol, writes the manifest, then
    # plays each episode through _EpisodeRun.run below.
    def run(self, benchmark: BenchmarkAdapter, policy: Policy, request: RunRequest) -> Path:
        """Check that runner, benchmark and policy agree on the protocol, write the
        manifest, then run the episodes in order. Returns the run directory."""
        # 1. Runner, benchmark and policy must agree before anything is written.
        # Feedback mode needs a policy that can hear rejections and a benchmark that allows them.
        if request.invalid_action_handling == "feedback" and not callable(
            getattr(policy, "observe_rejection", None)
        ):
            raise CompatibilityError("action rejection feedback requires policy.observe_rejection")
        if request.invalid_action_handling == "feedback" and getattr(
            benchmark, "action_rejection_feedback", True
        ) is not True:
            raise CompatibilityError("feedback mode returns invalid actions to the policy; "
                                     "this benchmark track does not admit action rejection feedback")
        required_prefix = getattr(benchmark, "required_replan_interval", None)  # set when the service fixes it
        if required_prefix is not None:
            if type(required_prefix) is not int or required_prefix <= 0:
                raise ProtocolError("benchmark required_replan_interval must be a positive integer")
            if type(request.replan_interval) is not int or request.replan_interval != required_prefix:
                raise ProtocolError("runner replan_interval does not satisfy the benchmark observation interface")
        # The method record: the --method-file declaration, else derived from the policy.
        method = (method_from_policy(policy.descriptor) if request.method is None
                  else normalize_method(request.method))
        # The policy checks the benchmark's cameras, state and action spec.
        errors = list(policy.compatibility_errors(benchmark.observation_spec, benchmark.action_spec))
        if errors:
            raise CompatibilityError("; ".join(errors))

        # 2. The episode list comes from the service; ids must stay unique as directory names.
        episodes = list(benchmark.episodes(request.seed, request.episode_limit))  # the service's fixed schedule
        if not episodes:
            raise ProtocolError("benchmark selected zero episodes")
        episode_ids = [episode.id for episode in episodes]
        if len(episode_ids) != len(set(episode_ids)):
            raise ProtocolError("benchmark episode ids must be unique")
        episode_paths = [self._safe_component(episode_id) for episode_id in episode_ids]  # directory names
        if len(episode_paths) != len(set(episode_paths)):
            raise ProtocolError("benchmark episode ids collide after artifact path normalization")

        # 3. Create the run directory and write the manifest.
        run_id = request.run_id or self._new_run_id(benchmark.descriptor.name, policy.descriptor.name)
        run_dir = request.output_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=False)  # a new directory; earlier runs are never overwritten

        try:  # a failure here is recorded in initialization_error.json
            # status.json: initializing -> running -> completed / completed_with_errors
            atomic_write_json(run_dir / "status.json", {"status": "initializing", "updated_at": utc_now()})
            manifest: dict[str, JsonValue] = {
                "schema_version": SCHEMA_VERSION,
                "run_id": run_id,
                "created_at": utc_now(),
                "benchmark": benchmark.descriptor.to_dict(),
                "policy": policy.descriptor.to_dict(),
                "method": method,
                "method_origin": ("participant_declaration" if request.method is not None
                                  else "policy_descriptor_projection"),
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
                    "fail_fast": request.fail_fast,
                    "execution_feedback_version": "starvla-rsi.execution-feedback/v1",
                    "instruction_change_handling": INSTRUCTION_CHANGE_HANDLING,
                    **({"control_acknowledgement_version": "starvla-rsi.control-acknowledgement/v1",
                        "control_feedback_schema": benchmark.observation_spec.control_feedback_schema}
                       if benchmark.observation_spec.control_feedback_schema is not None else {}),
                    "invalid_action_handling": request.invalid_action_handling,
                    "usage_accounting_version": USAGE_ACCOUNTING_VERSION,
                },
                "runtime": runtime_provenance(request.repository),  # host, Python, git revision and dirty flag
            }
            if request.invalid_action_handling == "feedback":
                manifest["protocol"]["action_rejection_feedback_version"] = (
                    "starvla-rsi.action-rejection-feedback/v1"
                )
            if required_prefix is not None:
                manifest["protocol"]["required_replan_interval"] = required_prefix
            # Record the used horizon and call cap against the service's advertised ones.
            service_cap = getattr(benchmark, "environment_step_cap", None)
            service_cap = service_cap if type(service_cap) is int else None
            manifest["protocol"]["service_environment_step_cap"] = service_cap
            manifest["protocol"]["max_steps_overridden"] = request.max_steps != service_cap
            service_calls = getattr(benchmark, "max_policy_calls", None)
            service_calls = service_calls if type(service_calls) is int else None
            manifest["protocol"]["service_max_policy_calls"] = service_calls
            manifest["protocol"]["max_policy_calls_overridden"] = request.max_policy_calls != service_calls
            # A remote service contributes its describe response (no endpoint or token).
            service_provenance = getattr(benchmark, "execution_provenance", None)
            if callable(service_provenance):
                provenance = ensure_jsonable(service_provenance(), "benchmark service provenance")
                if not isinstance(provenance, dict):
                    raise ProtocolError("benchmark service provenance must be a JSON object")
                manifest["benchmark_service"] = provenance
            atomic_write_json(run_dir / "manifest.json", manifest, overwrite=False)
            atomic_write_json(run_dir / "status.json", {"status": "running", "updated_at": utc_now()})
        except Exception as exc:  # leave a record of why setup failed, then re-raise
            failure = {
                "schema_version": SCHEMA_VERSION, "run_id": run_id,
                "phase": "initialization", "timestamp": utc_now(),
                "error": {"type": type(exc).__name__, "category": _error_category(exc),
                          "message": str(exc), "traceback": traceback.format_exc()},
            }
            atomic_write_json(run_dir / "initialization_error.json", failure, overwrite=False)
            atomic_write_json(run_dir / "status.json", {
                "status": "initialization_failed", "updated_at": utc_now(),
                "episodes_written": 0, "error_path": "initialization_error.json",
            })
            raise

        # 4. Play the episodes in order.
        results: list[dict[str, JsonValue]] = []
        for episode_index, episode in enumerate(episodes):
            # The policy sees episode-000000, ... instead of the benchmark's episode id.
            result = self._run_episode(
                benchmark, policy, episode, request, run_dir, f"episode-{episode_index:06d}", method
            )
            results.append(result)
            append_jsonl(run_dir / "episodes.jsonl", result)  # each result is kept as soon as it exists
            if request.fail_fast and result["status"] == "error":
                break

        # 5. Summarize the episodes and set the final status.
        summary = self._summarize(run_id, benchmark.descriptor.name, policy.descriptor.name, results)
        component_usage = {model["id"]: Usage().to_dict() for model in method["models"]}  # summed over episodes
        for result in results:
            component_usage = sum_component_usage(component_usage, result["component_usage"], method)
        summary["component_usage"] = component_usage
        atomic_write_json(run_dir / "summary.json", summary)
        # A completed episode may still be unsuccessful; only errors make this completed_with_errors.
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
        """Create episodes/<episode id>/ and play the episode there; returns its result."""
        episode_dir = run_dir / "episodes" / self._safe_component(episode.id)
        episode_dir.mkdir(parents=True, exist_ok=False)
        return _EpisodeRun(benchmark, policy, episode, request, episode_dir, policy_episode_id, method).run()

    @staticmethod
    def _summarize(
        run_id: str,
        benchmark_name: str,
        policy_name: str,
        results: list[dict[str, JsonValue]],
    ) -> dict[str, JsonValue]:
        return summarize_run(run_id, benchmark_name, policy_name, results)

    @staticmethod
    def _safe_component(value: str) -> str:
        """Make an id usable as a file name: other characters become "_"."""
        normalized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._")
        return normalized or "episode"

    @classmethod
    def _new_run_id(cls, benchmark: str, policy: str) -> str:
        """<benchmark>-<policy>-<UTC time>-<random hex>."""
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


class _EpisodeRun:
    """One episode: open the session, start the policy, run the decision loop,
    read the metrics, then collect artifacts, end the policy and close the session.

    Counters, usage and the error record live on the instance, so the failure
    handler and the closing phase see exactly what the loop had reached.
    """

    def __init__(self, benchmark: BenchmarkAdapter, policy: Policy, episode: EpisodeSpec,
                 request: RunRequest, episode_dir: Path, policy_episode_id: str, method: dict) -> None:
        self.benchmark = benchmark  # benchmark side: specs, the session, native success
        self.policy = policy  # the method under evaluation; it sees only public observations and counters
        self.episode = episode  # native task and seed; the policy gets a PolicyEpisodeSpec instead
        self.request = request  # limits, rejection handling and recording for this run
        self.method = method  # the declared method; its models name the component_usage entries
        self.episode_dir = episode_dir  # episodes/<episode id>/ of this run
        self.policy_episode_id = policy_episode_id  # the episode id the policy sees, not the benchmark's
        self.events_path = episode_dir / "events.jsonl"  # runner ledger: calls, chunks, steps, rejections, errors
        # Writes both JSONL files, applying the recording options, and collects warnings.
        self.recorder = InteractionRecorder(episode_dir / "agent_interactions.jsonl", request.recording)
        self.feedback_schema = benchmark.observation_spec.control_feedback_schema  # None: no control ACKs
        # Run max_steps, or this episode's smaller native cap from the service schedule.
        self.max_steps = episode_step_limit(request.max_steps, episode.metadata)
        self.component_usage = {model["id"]: Usage().to_dict() for model in method["models"]}  # usage per model

        # Episode state, filled in as the episode runs.
        # The scratch dirs take exports that must not be kept; _close removes them.
        self.policy_scratch: tempfile.TemporaryDirectory | None = None
        self.session_scratch: tempfile.TemporaryDirectory | None = None
        self.discard_session_artifacts = False  # True when session artifacts went to scratch
        self.started_at = time.monotonic()  # for duration_s
        self.session: EpisodeSession | None = None  # set by _open_session
        self.observation = None  # latest public observation: from reset, then from each step
        self.policy_started = False  # closing calls end_episode only once this is set
        self.decision_instruction: str | None = None  # the instruction the current decision was made for

        # Accounting: written into result.json.
        self.usage = Usage()  # summed over policy calls
        self.reconciliation: dict[str, JsonValue] | None = None  # set when the policy reports its own total
        self.usage_pending_since: float | None = None  # set while a call's usage is not yet accounted
        self.policy_call_failure: PolicyCallError | None = None  # the current call's own failure, if any
        self.terminal_rejection_phase: str | None = None  # where a rejection ended the episode
        self.policy_calls = 0  # every policy.act call
        self.action_decisions = 0  # decisions with at least one executed control
        self.rejected_actions = 0  # invalid actions, caught by the runner or by the service
        self.env_steps = 0  # controls executed in the environment
        self.reward_sum = 0.0  # native reward, recorded but never shown to the policy

        # Outcome.
        self.termination_reason = "unknown"  # e.g. runner:step_limit, policy:task_complete, error:policy
        self.metrics: dict[str, JsonValue] = {}  # session.metrics(), with a boolean "success"
        self.artifacts: dict[str, JsonValue] = {}  # session artifact paths kept in the result
        self.status = "error"  # becomes "completed" only when the episode runs through its metrics
        self.error: dict[str, JsonValue] | None = None  # record of the exception that ended the episode

    # Reading step 4 of 6: one episode. Each policy call in _call_policy goes to
    # policy.act, e.g. CodexNativePolicy in AgentPolicies/gpt6_astra/codex_native.py.
    def run(self) -> dict[str, JsonValue]:
        self._event("episode_start", episode=self.episode.to_dict())
        try:
            self._open_session()  # claim and reset; sets the first observation
            self._start_policy()  # policy.start_episode with the public context
            self._decision_loop()  # call, validate, execute, until a stop or a limit
            self._collect_metrics()  # native success
            self.status = "completed"  # reached only when nothing above raised
        except Exception as exc:  # artifact boundary: preserve typed and third-party failures
            self._record_failure(exc)
        finally:
            self._close()  # always runs: artifacts, end_episode, session.close
        return self._write_result()  # result.json

    def _event(self, event: str, **fields: JsonValue) -> None:
        self.recorder.event(self.events_path, {"event": event, "timestamp": utc_now(), **fields})

    # Starting the episode

    def _open_session(self) -> None:
        """Open the benchmark session, bind its artifact directory and reset it."""
        recording = self.request.recording
        self.session = session = self.benchmark.open_episode(self.episode)  # for a remote service: claims the case
        configure_recording = getattr(session, "configure_recording", None)  # optional: session applies retention
        if callable(configure_recording):
            configure_recording(recording)
        bind_artifact_dir = getattr(session, "bind_artifact_dir", None)  # optional: where the session writes media
        if bind_artifact_dir is not None:
            if not callable(bind_artifact_dir):
                raise ProtocolError("session.bind_artifact_dir must be callable")
            artifact_dir = self.episode_dir / "artifacts"
            # A session that cannot take the retention options writes to scratch when
            # unknown artifacts are not retained; scratch artifacts are not recorded.
            if not recording.retain_unknown_artifacts and not callable(configure_recording):
                self.session_scratch = tempfile.TemporaryDirectory(prefix="rsi-session-recording-")
                artifact_dir = Path(self.session_scratch.name) / "artifacts"
                self.discard_session_artifacts = True
            elif not recording.retain_all and not callable(configure_recording):
                self.recorder.warn("session_media_retention_unsupported_preserved_artifacts")
            artifact_dir.mkdir(exist_ok=False)
            bind_artifact_dir(artifact_dir)
        self.observation = session.reset()  # the first public observation
        if self.observation.control_feedback is not None:
            raise ProtocolError("reset cannot carry a control acknowledgement")
        self._event("observation", observation=self.observation.log_view())  # metadata only, no image arrays

    def _start_policy(self) -> None:
        """Bind the policy's recording and artifact directory, then start its episode."""
        policy, request = self.policy, self.request
        benchmark = self.benchmark
        # All the policy learns about the episode: public identity, specs and limits.
        context = EpisodeContext(
            benchmark=benchmark.descriptor,
            episode=PolicyEpisodeSpec(
                id=self.policy_episode_id,
                task=self.episode.task,
                instruction=self.observation.instruction,  # from the reset observation
            ),
            observation_spec=benchmark.observation_spec,
            action_spec=benchmark.action_spec,
            max_steps=self.max_steps,
            max_policy_calls=request.max_policy_calls,
            replan_interval=request.replan_interval,
            invalid_action_handling=request.invalid_action_handling,
        )
        # Model-owned diagnostics/workspace exports; no SIM client or
        # evaluator-private artifact directory is passed to the actor.
        configure_recording = getattr(policy, "configure_recording", None)
        if callable(configure_recording):
            configure_recording(request.recording)
        bind_recorder = getattr(policy, "bind_interaction_recorder", None)  # writes to agent_interactions.jsonl
        if callable(bind_recorder):
            bind_recorder(self.recorder)
        bind_artifact_dir = getattr(policy, "bind_artifact_dir", None)  # optional: where the policy exports files
        if bind_artifact_dir is not None:
            if not callable(bind_artifact_dir):
                raise ProtocolError("policy.bind_artifact_dir must be callable")
            destination = self.episode_dir / "policy_artifacts"

            def configurable() -> bool:  # the policy applies the retention options itself
                return callable(configure_recording) and getattr(policy, "recording_configurable", False) is True

            if not request.recording.retain_unknown_artifacts and not configurable():
                # Unknown policy exports cannot be classified by filenames.
                # Keep required runtime files available, but do not retain
                # an opaque bundle containing disabled categories.
                self.policy_scratch = tempfile.TemporaryDirectory(prefix="rsi-policy-recording-")
                destination = Path(self.policy_scratch.name) / "policy_artifacts"
            elif not request.recording.retain_all and not configurable():
                self.recorder.warn("policy_media_retention_unsupported_preserved_artifacts")
            bind_artifact_dir(destination)
        self.policy_started = True  # set first, so end_episode also runs when start_episode fails
        policy.start_episode(context)  # CodexNativePolicy sets up its workspace here

    # The decision loop

    def _decision_loop(self) -> None:
        """Call the policy and execute its chunks until a stop, a limit or the episode's end.

        Each round is one policy call. A stop decision ends the loop; a rejected
        reply or chunk goes back to the policy and the loop calls again; otherwise
        _execute runs the chunk and may end the episode.
        """
        request = self.request
        while self.env_steps < self.max_steps:  # each round: one policy call, then its chunk
            if request.max_policy_calls is not None and self.policy_calls >= request.max_policy_calls:
                self.termination_reason = "runner:policy_call_limit"
                break
            decision = self._call_policy()
            if decision is None:
                continue  # rejected and returned to the policy as feedback
            if decision.stop:
                self.termination_reason = f"policy:{decision.stop_reason}"
                break
            chunk = self._validated_chunk(decision)
            if chunk is None:
                continue  # rejected and returned to the policy as feedback
            self._execute(chunk)
            if self.termination_reason != "unknown":  # _execute ended the episode
                break
        if self.termination_reason == "unknown":  # the while condition ended it: all steps used
            self.termination_reason = "runner:step_limit"

    def _call_policy(self) -> PolicyDecision | None:
        """Make one policy call and account its usage.

        Returns None when the call's action was rejected and returned to the
        policy as feedback.
        """
        self.policy_calls += 1  # every call counts, also one whose reply is rejected
        self._event("policy_call_start", policy_call=self.policy_calls)
        self.usage_pending_since = time.monotonic()  # if the call fails unaccounted, the elapsed time is charged
        self.policy_call_failure = None
        self.decision_instruction = self.observation.instruction  # _execute stops the chunk if an ACK changes it
        try:
            decision = self.policy.act(self.observation)  # the model decides here
        except PolicyCallError as exc:
            self.policy_call_failure = exc  # lets _record_failure keep the usage this call reported
            if isinstance(exc, ActionRejected):
                self.rejected_actions += 1
                if self.request.invalid_action_handling == "feedback":  # count the call, tell the policy, call again
                    self._accumulate_component_usage(exc.metadata)
                    self.usage = self.usage + exc.usage
                    self.usage_pending_since = None  # accounted
                    self._feed_back_rejection(exc, phase="policy_act", executed_steps=0,
                                              control_acks=() if self.feedback_schema is not None else None,
                                              additional_usage=exc.usage, usage_recorded_in="action_rejected")
                    self.policy_call_failure = None  # handled; not an episode failure
                    return None
                self.terminal_rejection_phase = "policy_act"  # terminate mode: the rejection ends the episode
            raise
        except (TypeError, ValueError) as exc:  # e.g. an invalid PolicyDecision or ActionChunk
            raise PolicyError(f"policy failed to produce a valid decision: {exc}") from exc
        if not isinstance(decision, PolicyDecision):
            raise PolicyError(f"policy returned {type(decision).__name__}, expected PolicyDecision")
        # Build the event first; then account the call with nothing
        # that can fail between adding its usage and clearing pending.
        decision_event: dict[str, JsonValue] = {
            "event": "policy_decision",
            "timestamp": utc_now(),
            "policy_call": self.policy_calls,
            "note": decision.note,
            "metadata": ensure_jsonable(decision.metadata),
            "usage": decision.usage.to_dict(),
            "stop": decision.stop,
            "stop_reason": decision.stop_reason,
            "chunk_length": 0 if decision.action is None else len(decision.action.steps),
        }
        self._accumulate_component_usage(decision.metadata)
        self.usage = self.usage + decision.usage
        self.usage_pending_since = None
        self.recorder.event(self.events_path, decision_event)
        return decision

    def _validated_chunk(self, decision: PolicyDecision) -> tuple[tuple[float, ...], ...] | None:
        """Check that a non-stop decision carries a chunk, then validate every
        vector of the chunk against the action spec.

        Returns None when the chunk was rejected and returned to the policy as
        feedback.
        """
        if decision.action is None:
            raise PolicyError("non-stop decision omitted an action chunk")
        action_spec = self.benchmark.action_spec
        if self.request.invalid_action_handling == "feedback":  # a bad vector goes back to the policy
            try:
                # Validate the WHOLE proposed chunk, including any
                # unplayed suffix, before issuing its first control.
                return tuple(validate_action_vector(action_spec, raw_action)
                             for raw_action in decision.action.steps)
            except ActionRejected as exc:
                self.rejected_actions += 1
                self._feed_back_rejection(exc, phase="action_spec", executed_steps=0,
                                          control_acks=() if self.feedback_schema is not None else None,
                                          additional_usage=Usage(), usage_recorded_in="policy_decision")
                return None
        try:  # terminate mode: a bad vector is a policy error
            return tuple(action_spec.validate(raw_action) for raw_action in decision.action.steps)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PolicyError(f"policy action violates the benchmark contract: {exc}") from exc

    def _execute(self, chunk: tuple[tuple[float, ...], ...]) -> None:
        """Send the chunk's allowed prefix one control at a time. The chunk also ends
        early when the episode ends (setting termination_reason) or the public
        instruction changes. The policy then gets the executed prefix as
        ExecutionFeedback, or as ActionRejectionFeedback when the session rejected
        a control."""
        request = self.request
        control_acks = [] if self.feedback_schema is not None else None  # one public ACK per executed control
        # At most replan_interval controls, and never past max_steps.
        steps_to_play = len(chunk)
        if request.replan_interval is not None:
            steps_to_play = min(steps_to_play, request.replan_interval)
        steps_to_play = min(steps_to_play, self.max_steps - self.env_steps)
        # Log the whole chunk, then play its prefix one control at a time.
        self._event("action_chunk", policy_call=self.policy_calls, actions=ensure_jsonable(chunk),
                    maximum_executed_prefix=steps_to_play)
        executed_steps = 0  # controls of this chunk that ran
        rejected_control = None  # set when the service rejects a control
        for chunk_index, action in enumerate(chunk[:steps_to_play]):
            try:
                transition = self.session.step(action)  # one control in the environment
            except ActionRejected as exc:
                if request.invalid_action_handling != "feedback":  # terminate mode: the rejection ends the episode
                    self.rejected_actions += 1
                    self.terminal_rejection_phase = "session_step"
                    raise
                if exc.usage != Usage():  # the policy call's usage was already counted
                    raise ProtocolError("session action rejection cannot report policy usage") from None
                self.rejected_actions += 1
                rejected_control = exc  # fed back below with the prefix that already ran
                break
            if not isinstance(transition, Transition):
                raise ProtocolError(f"episode returned {type(transition).__name__}, expected Transition")
            self.env_steps += 1
            executed_steps += 1
            if chunk_index == 0:  # a decision counts once its first control has executed
                self.action_decisions += 1
            self.reward_sum += transition.reward
            self.observation = observation = transition.observation  # the next call sees this one
            self._event("environment_step", policy_call=self.policy_calls, chunk_index=chunk_index,
                        environment_step=self.env_steps, action=action, reward=transition.reward,
                        terminated=transition.terminated, truncated=transition.truncated,
                        info=ensure_jsonable(transition.info), observation=observation.log_view())
            # Copy only the benchmark-declared public channel. Private
            # reward, terminal flags and Transition.info never cross.
            payload = observation.control_feedback
            if self.feedback_schema is not None:
                if (not isinstance(payload, Mapping) or payload.get("schema") != self.feedback_schema
                        or observation.step != self.env_steps):
                    raise ProtocolError("missing or uncorrelated public control acknowledgement")
                control_acks.append(ControlAcknowledgement(self.env_steps, observation.step, payload))
            elif payload is not None:
                raise ProtocolError("undeclared public control acknowledgement")
            # Stop conditions, in this order; otherwise the next control runs.
            if transition.terminated:  # the benchmark ended the task
                self.termination_reason = "environment:terminated"
                break
            if transition.truncated:  # the benchmark's own time limit
                self.termination_reason = "environment:truncated"
                break
            if self.env_steps >= self.max_steps:
                self.termination_reason = "runner:step_limit"
                break
            if observation.instruction != self.decision_instruction:
                # The next instruction is already public in this ACK.
                # Discard the unexecuted suffix and let the method decide
                # again; never inspect reward, native info or private
                # subtask state to select this boundary.
                break
        acks = tuple(control_acks) if control_acks is not None else None
        if rejected_control is not None:
            # A typed service rejection confirms that THIS vector did
            # not execute. Retain the last ACK observation and all
            # earlier prefix controls; never reset, replay or invent a
            # zero-control outcome for a partly executed decision.
            self._feed_back_rejection(rejected_control, phase="session_step", executed_steps=executed_steps,
                                      control_acks=acks, additional_usage=Usage(),
                                      usage_recorded_in="policy_decision")
            return
        # Tell the policy what actually ran: counters and the public ACKs.
        observe_execution = getattr(self.policy, "observe_execution", None)
        if observe_execution is not None:
            if not callable(observe_execution):
                raise PolicyError("policy.observe_execution must be callable")
            observe_execution(ExecutionFeedback(
                policy_calls=self.policy_calls,
                action_decisions=self.action_decisions,
                environment_steps=self.env_steps,
                executed_steps=executed_steps,
                control_acks=acks,
            ))

    def _feed_back_rejection(self, rejection: ActionRejected, *, phase: str, executed_steps: int,
                             control_acks: tuple[ControlAcknowledgement, ...] | None,
                             additional_usage: Usage, usage_recorded_in: str) -> None:
        """Log the rejection and pass its public issue and counters to the policy."""
        feedback = ActionRejectionFeedback(issue=rejection.issue,
            policy_calls=self.policy_calls, action_decisions=self.action_decisions,
            environment_steps=self.env_steps, executed_steps=executed_steps,
            rejected_actions=self.rejected_actions, control_acks=control_acks)
        self._event("action_rejected", policy_call=self.policy_calls, phase=phase, feedback=feedback.to_dict(),
                    usage=additional_usage.to_dict(), usage_recorded_in=usage_recorded_in,
                    metadata=rejection.metadata)
        # No receipts, raw exceptions, reward/terminal flags or native metadata
        # cross this hook. Hook errors are terminal; no inner model retry.
        self.policy.observe_rejection(feedback)

    def _accumulate_component_usage(self, metadata: Mapping[str, JsonValue]) -> None:
        """Add one call's per-model usage, as the policy reported it in metadata."""
        try:
            reported = normalize_component_usage(metadata.get("component_usage"), self.method)
        except (TypeError, ValueError, OverflowError, RecursionError):
            self.recorder.warn("invalid_component_usage_unavailable")
            reported = normalize_component_usage(None, self.method)
        self.component_usage = sum_component_usage(self.component_usage, reported, self.method)

    def _collect_metrics(self) -> None:
        """Read the benchmark's episode metrics; they must report success as a bool."""
        metrics = ensure_jsonable(self.session.metrics(), "episode metrics")  # native success comes from here
        if not isinstance(metrics, dict):
            raise ProtocolError("episode metrics must be a JSON object")
        if not isinstance(metrics.get("success"), bool):
            raise ProtocolError("episode metrics must contain boolean 'success'")
        self.metrics = metrics

    def _record_failure(self, exc: Exception) -> None:
        """Record the exception that ended the episode, with the usage of a call it interrupted."""
        failure = self.policy_call_failure
        # A call that failed with its own PolicyCallError reported its usage; any
        # other failure during a call leaves only the elapsed time known.
        reported_call_failure = self.usage_pending_since is not None and exc is failure
        if self.usage_pending_since is not None:
            failed_usage = (failure.usage if reported_call_failure else
                            Usage.unavailable(latency_s=time.monotonic() - self.usage_pending_since))
            self.usage = self.usage + failed_usage
            self._accumulate_component_usage(failure.metadata if reported_call_failure else {})
        error: dict[str, JsonValue] = {
            "type": type(exc).__name__,
            "category": _error_category(exc),
            "message": str(exc),
        }
        if isinstance(exc, ActionRejected):
            error["issue"] = exc.issue.to_dict()
            if self.terminal_rejection_phase is not None:
                error["action_rejection_phase"] = self.terminal_rejection_phase
        if self.usage_pending_since is not None:
            error.update(policy_call=self.policy_calls, usage=failed_usage.to_dict())
        if not isinstance(exc, PolicyCallError):
            error["traceback"] = traceback.format_exc()
        if reported_call_failure:
            # Never fabricate a normal decision to retain a failed call's
            # receipt. Chained provider exceptions may contain private data.
            error["metadata"] = failure.metadata
        self.error = error
        self.termination_reason = f"error:{error['category']}"
        self._event("error", error=error)

    # Closing the episode

    def _close(self) -> None:
        """Collect session artifacts, end the policy, reconcile its usage, then
        close the session and remove scratch directories.

        Artifact errors and failures of end_episode or session.close attach to an
        existing error, or become the episode error when there is none; usage and
        scratch failures are warnings."""
        cleanup_errors: list[str] = []
        if self.session is not None:
            self._collect_artifacts()
        if self.policy_started:
            try:
                self.policy.end_episode()
            except Exception as exc:  # cleanup must be visible without hiding the primary result
                cleanup_errors.append(f"policy.end_episode: {type(exc).__name__}: {exc}")
            self._reconcile_policy_usage()  # after end_episode, when the policy's own total is final
        self._remove_scratch(self.policy_scratch, "policy_scratch_cleanup_failed")
        if self.session is not None:
            try:
                self.session.close()
            except Exception as exc:
                cleanup_errors.append(f"session.close: {type(exc).__name__}: {exc}")
        self._remove_scratch(self.session_scratch, "session_scratch_cleanup_failed")
        if cleanup_errors:
            if self.error is None:
                self.status = "error"
                self.termination_reason = "error:infrastructure"
                self.error = {
                    "type": "CleanupError",
                    "category": "infrastructure",
                    "message": "; ".join(cleanup_errors),
                }
            else:
                self.error["cleanup_errors"] = cleanup_errors

    def _collect_artifacts(self) -> None:
        """Keep the session's artifact paths; a failure becomes, or joins, the episode error."""
        try:
            artifacts = ensure_jsonable(self.session.artifacts(), "episode artifacts")
            if not isinstance(artifacts, dict) or any(not isinstance(value, str) for value in artifacts.values()):
                raise ProtocolError("episode artifacts must map names to string paths")
            self.artifacts = {} if self.discard_session_artifacts else artifacts
        except Exception as exc:
            artifact_error = {
                "type": type(exc).__name__,
                "category": _error_category(exc),
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
            if self.error is None:
                self.error = artifact_error
                self.status = "error"
                self.termination_reason = f"error:{artifact_error['category']}"
            else:
                self.error["artifact_error"] = artifact_error
            self._event("artifact_error", error=artifact_error)

    def _reconcile_policy_usage(self) -> None:
        # Read once after end_episode, when the policy has settled its
        # own accounting. A broken report, including a raising lookup,
        # never changes the outcome; it counts as unknown with a warning.
        reported = None
        try:
            usage_report = getattr(self.policy, "episode_usage", None)
            if usage_report is not None:
                reported = usage_report()
                if not isinstance(reported, EpisodeUsage):
                    raise TypeError("episode_usage must return EpisodeUsage")
        except Exception:
            self.recorder.warn("episode_usage_unavailable")
            reported = EpisodeUsage(total=Usage.unavailable(), complete=False)
        if reported is not None:
            self.usage, self.reconciliation = _reconcile_usage(self.usage, reported)
            self._event("usage_reconciliation", **self.reconciliation)

    def _remove_scratch(self, scratch: tempfile.TemporaryDirectory | None, warning: str) -> None:
        if scratch is not None:
            try:
                scratch.cleanup()
            except Exception:
                self.recorder.warn(warning)

    def _write_result(self) -> dict[str, JsonValue]:
        """Write result.json; run() appends the same record to episodes.jsonl."""
        request, reconciliation = self.request, self.reconciliation
        result: dict[str, JsonValue] = {
            "schema_version": SCHEMA_VERSION,
            "episode": self.episode.to_dict(),
            "status": self.status,  # "completed" or "error"; success is a separate field
            "success": self.metrics.get("success") if self.status == "completed" else None,  # unknown, not failed
            "termination_reason": self.termination_reason,
            "environment_steps": self.env_steps,
            "policy_calls": self.policy_calls,
            "action_decisions": self.action_decisions,
            "rejected_actions": self.rejected_actions,
            "reward_sum": self.reward_sum,
            "duration_s": time.monotonic() - self.started_at,
            "usage": self.usage.to_dict(),
            "component_usage": self.component_usage,
            # Null when the policy reports no episode usage of its own.
            "usage_reported_complete": None if reconciliation is None else reconciliation["reported_complete"],
            "usage_inconsistent_fields": None if reconciliation is None else reconciliation["inconsistent_fields"],
            "metrics": self.metrics,
            "artifacts": self.artifacts,
            "error": public_error_record(self.error, request.recording),  # metadata dropped unless model_io
            "recording": {**request.recording.to_dict(),
                          "agent_events_written": self.recorder.events_written,
                          "warnings": list(self.recorder.warnings)},
        }
        result_path = self.episode_dir / "result.json"
        atomic_write_json(result_path, result)
        self._event("episode_end", result=result)
        # A failed episode_end write adds a warning; keep result.json in step with it.
        if result["recording"]["warnings"] != self.recorder.warnings:
            result["recording"]["warnings"] = list(self.recorder.warnings)
            atomic_write_json(result_path, result)
        return result


def _reconcile_usage(measured: Usage, reported: EpisodeUsage) -> tuple[Usage, dict[str, JsonValue]]:
    """Combine the per-call sum S with the policy's own total T, field by field.

    Unknown T keeps S; unknown S takes T; T >= S takes T. T below S
    contradicts the measured calls, so that field becomes unknown and is
    listed instead of being clamped to either side.
    """
    final, adjustment, inconsistent = {}, {}, []
    for key, summed in measured.__dict__.items():
        total = getattr(reported.total, key)
        if total is None or summed is None:
            final[key] = summed if total is None else total
            adjustment[key] = None
        elif total < summed and not (key in ("estimated_cost_usd", "latency_s") and
                                     math.isclose(total, summed, rel_tol=1e-12, abs_tol=1e-9)):
            final[key] = adjustment[key] = None
            inconsistent.append(key)
        else:
            final[key], adjustment[key] = total, total - summed
    usage = Usage(**final)
    return usage, {"policy_call_sum": measured.to_dict(), "reported_total": reported.total.to_dict(),
                   "reported_complete": reported.complete, "adjustment": ensure_jsonable(adjustment),
                   "inconsistent_fields": inconsistent, "usage": usage.to_dict()}


def _error_category(error: Exception) -> str:
    """Unknown exceptions count as infrastructure, never as policy failures."""
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
