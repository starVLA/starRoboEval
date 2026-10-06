"""Dependency-light checks for the external-policy boundary and replay handling.

Run from the repository root:
python3 -m unittest discover -s benchmarks/simBenchmarks/SimplerEnv/checks -p test_mailbox.py -v
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from typing import Any, Callable

from benchkit.artifacts import atomic_write_json
from benchkit.contracts import (
    ActionSpec,
    BenchmarkDescriptor,
    EpisodeContext,
    Observation,
    ObservationSpec,
    PolicyEpisodeSpec,
)
from benchkit.errors import PolicyError, ProtocolError
from AgentPolicies.anonymous_code_agent.mailbox import MailboxPolicy, make_mailbox_policy, new_mailbox_directory


def context(*, privileged: bool = False, cameras: tuple[str, ...] = ()) -> EpisodeContext:
    return EpisodeContext(
        benchmark=BenchmarkDescriptor("fixture", "1", "fixture/v1", "fixture-source"),
        episode=PolicyEpisodeSpec("opaque-episode", "fixture", "Move the robot."),
        observation_spec=ObservationSpec(
            cameras=cameras, state_names=("joint_position",), privileged=privileged
        ),
        action_spec=ActionSpec("delta", 7, low=(-1.0,) * 7, high=(1.0,) * 7),
        max_steps=10,
        max_policy_calls=3,
        replan_interval=1,
    )


def action_response(request_id: str) -> dict[str, Any]:
    return {"request_id": request_id, "actions": [[0.0] * 7], "usage": {"calls": 1}}


class MailboxChecks(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.policy = MailboxPolicy(self.root / "mailbox", timeout_s=2)
        self.policy.start_episode(context())
        self.observation = Observation(
            step=0, instruction="Move the robot.", state=(0.25,),
            metadata={"seed": 876, "success": True, "object_pose": [1, 2, 3]},
        )

    def exchange(
        self,
        response: Callable[[str], Any] = action_response,
        *,
        observation: Observation | None = None,
        writer: Callable[[Path, Any], None] = atomic_write_json,
    ) -> Any:
        """Fake client reads only the exported pointer and publishes one reply."""
        failures: list[BaseException] = []

        def client() -> None:
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    pointer = json.loads((self.policy.directory / "ready.json").read_text())
                    if pointer["status"] == "pending":
                        self.assertFalse(Path(pointer["observation_path"]).is_absolute())
                        self.assertFalse(Path(pointer["response_path"]).is_absolute())
                        self.assertNotIn(str(self.policy.directory), json.dumps(pointer))
                        writer(self.policy.directory / pointer["response_path"], response(pointer["request_id"]))
                        return
                    time.sleep(0.005)
                raise AssertionError("client never received a pending observation")
            except BaseException as exc:
                failures.append(exc)

        thread = threading.Thread(target=client, daemon=True)
        thread.start()
        try:
            return self.policy.act(observation or self.observation)
        finally:
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
            if failures:
                raise failures[0]

    def test_only_declared_channels_are_exported(self) -> None:
        decision = self.exchange()
        self.assertEqual(decision.action.steps, ((0.0,) * 7,))
        self.assertEqual(decision.usage.calls, 1)
        self.assertIsNone(decision.usage.input_tokens)
        self.assertIsNone(decision.usage.estimated_cost_usd)
        self.assertGreater(decision.usage.latency_s, 0)
        path = Path(decision.metadata["observation_path"])
        exported = json.loads(path.read_text())
        self.assertEqual(exported["state"], [0.25])
        self.assertEqual(exported["instruction"], "Move the robot.")
        self.assertEqual(exported["action_spec"]["size"], 7)
        self.assertEqual(exported["budgets"]["max_policy_calls"], 3)
        self.assertEqual(exported["history"], "current_observation_only")
        for forbidden in ("seed", "success", "object_pose", "opaque-episode", "fixture-source"):
            self.assertNotIn(forbidden, path.read_text())
        self.assertEqual(
            json.loads(Path(decision.metadata["response_path"]).read_text()),
            decision.metadata["structured_response"],
        )
        self.assertTrue(path.is_absolute())
        self.assertEqual(json.loads((self.policy.directory / "ready.json").read_text())["status"], "consumed")

    def test_unavailable_code_agent_usage_remains_null_and_unverified(self) -> None:
        decision = self.exchange(lambda request_id: {
            "request_id": request_id, "actions": [[0.0] * 7], "usage": None,
        })
        self.assertIsNone(decision.usage.calls)
        self.assertIsNone(decision.usage.input_tokens)
        self.assertIsNone(decision.usage.output_tokens)
        self.assertIsNone(decision.usage.cached_input_tokens)
        self.assertIsNone(decision.usage.estimated_cost_usd)
        self.assertGreater(decision.usage.latency_s, 0)
        self.assertEqual(decision.metadata["usage_source"], "unavailable")
        self.assertIs(decision.metadata["provider_call_limit_verified"], False)
        self.assertEqual(self.policy.descriptor.parameters["evaluation_status"], "experimental")
        self.assertIs(self.policy.descriptor.parameters["provider_call_limit_verified"], False)
        response = json.loads(Path(decision.metadata["response_path"]).read_text())
        self.assertIsNone(response["usage"])

    def test_individual_usage_fields_can_be_unknown(self) -> None:
        decision = self.exchange(lambda request_id: {
            "request_id": request_id, "actions": [[0.0] * 7],
            "usage": {"calls": None, "input_tokens": 12, "output_tokens": None},
        })
        self.assertIsNone(decision.usage.calls)
        self.assertEqual(decision.usage.input_tokens, 12)
        self.assertIsNone(decision.usage.output_tokens)

    def test_stop_is_structured_and_success_free(self) -> None:
        decision = self.exchange(lambda request_id: {
            "request_id": request_id, "stop": True, "stop_reason": "give_up",
            "usage": {"calls": 1, "input_tokens": 12}, "note": "Unable to reach the target.",
        })
        self.assertTrue(decision.stop)
        self.assertIsNone(decision.action)
        self.assertEqual(decision.stop_reason, "give_up")
        self.assertNotIn("success", decision.metadata)

    def test_rgb_export_preserves_the_exact_current_frame(self) -> None:
        try:
            import numpy as np
            from PIL import Image
        except ImportError:
            self.skipTest("optional RGB check requires numpy and Pillow")
        self.policy.end_episode()
        self.policy.start_episode(context(cameras=("robot_camera",)))
        frame = np.array([[[255, 0, 0], [0, 255, 0]]], dtype=np.uint8)
        decision = self.exchange(observation=Observation(
            step=0, instruction="Move.", state=(0.25,), images={"robot_camera": frame}
        ))
        exported = json.loads(Path(decision.metadata["observation_path"]).read_text())
        frame_spec = exported["images"]["robot_camera"]
        self.assertEqual(frame_spec["color_space"], "RGB")
        self.assertEqual((frame_spec["width"], frame_spec["height"]), (2, 1))
        self.assertFalse(Path(frame_spec["path"]).is_absolute())
        with Image.open(self.policy.directory / frame_spec["path"]) as image:
            self.assertEqual(list(image.getdata()), [(255, 0, 0), (0, 255, 0)])

    def test_public_paths_do_not_serialize_private_directory_identifiers(self) -> None:
        self.policy.end_episode()
        self.policy = MailboxPolicy(self.root / "private-seed-20260907-task-42", timeout_s=2)
        self.policy.start_episode(context())
        decision = self.exchange()
        payload = Path(decision.metadata["observation_path"]).read_text()
        for hidden in (str(self.root), "20260907", "private-seed", "task-42"):
            self.assertNotIn(hidden, payload)
        self.assertEqual(json.loads(payload)["schema_version"], "starvla-rsi.mailbox/v3")
        # Private decision artifacts may retain absolute paths for audit. They
        # are never serialized into the public observation or pointer.
        self.assertTrue(Path(decision.metadata["observation_path"]).is_absolute())

    def test_new_endpoints_are_random_and_not_created_or_reused(self) -> None:
        first = new_mailbox_directory(self.root / "policy_io")
        second = new_mailbox_directory(self.root / "policy_io")
        self.assertNotEqual(first, second)
        self.assertRegex(first.name, r"^mbx-[0-9a-f]{32}$")
        self.assertFalse(first.exists())
        with self.assertRaises(ValueError):
            new_mailbox_directory(Path("relative-root"))

    def test_request_ids_advance_and_old_observation_cannot_be_retried(self) -> None:
        first = self.exchange()
        with self.assertRaisesRegex(PolicyError, "same observation step"):
            self.policy.act(self.observation)
        second = self.exchange(observation=Observation(step=1, instruction="Move.", state=(0.5,)))
        self.assertNotEqual(first.metadata["request_id"], second.metadata["request_id"])
        self.policy.end_episode()
        self.policy.start_episode(context())
        third = self.exchange()
        self.assertNotEqual(first.metadata["request_id"], third.metadata["request_id"])

    def test_mismatched_response_is_not_retried(self) -> None:
        with self.assertRaisesRegex(PolicyError, "request_id"):
            self.exchange(lambda _: action_response("old-request"))
        with self.assertRaisesRegex(PolicyError, "failed decision"):
            self.policy.act(Observation(step=1, instruction="Move.", state=(0.25,)))

    def test_multiple_provider_calls_are_rejected(self) -> None:
        def invalid(request_id: str) -> dict[str, Any]:
            result = action_response(request_id)
            result["usage"]["calls"] = 2
            return result

        with self.assertRaisesRegex(PolicyError, "at most one"):
            self.exchange(invalid)

    def test_invalid_schema_and_types_are_rejected(self) -> None:
        invalid_responses = [
            {"actions": [[0] * 7], "usage": {"calls": True}},
            {"actions": [[0] * 7], "usage": {"calls": 1.0}},
            {"actions": [[0] * 7], "usage": {"calls": 1, "input_tokens": 1.5}},
            {"actions": [[0] * 7], "usage": {"calls": 1, "extra": 7}},
            {"actions": [["0"] * 7], "usage": {"calls": 1}},
            {"actions": [[True] * 7], "usage": {"calls": 1}},
            {"actions": [[2] * 7], "usage": {"calls": 1}},
            {"actions": [[0] * 6], "usage": {"calls": 1}},
            {"actions": [], "usage": {"calls": 1}},
            {"actions": [[0] * 7], "usage": {}},
            {"actions": [[0] * 7], "usage": {"calls": 1}, "success": True},
            {"actions": [[0] * 7], "usage": {"calls": 1}, "reasoning": "private"},
            {"stop": False, "stop_reason": "give_up", "usage": {"calls": 1}},
            {"stop": True, "usage": {"calls": 1}},
            {"stop": True, "stop_reason": "give_up", "actions": [[0] * 7], "usage": {"calls": 1}},
        ]
        # Parsing has no I/O or retries, so invalid responses can be checked on
        # a single fixture while the threaded tests cover publication/lifecycle.
        for invalid in invalid_responses:
            with self.subTest(response=invalid), self.assertRaises(PolicyError):
                self.policy._parse_response(
                    {"request_id": "pending", **invalid}, "pending", 0.1, self.policy.directory
                )

    def test_duplicate_keys_and_non_finite_json_are_rejected(self) -> None:
        for index, raw in enumerate((b'{"request_id":"one","request_id":"two"}', b'{"a":NaN}')):
            path = self.root / f"invalid-{index}.json"
            path.write_bytes(raw)
            with self.assertRaises(PolicyError):
                self.policy._read_response(path)

    def test_response_size_limit(self) -> None:
        self.policy.max_response_bytes = 32
        with self.assertRaisesRegex(PolicyError, "max_response_bytes"):
            self.exchange()

    def test_timeout_is_terminal_for_the_decision(self) -> None:
        self.policy.timeout_s = 0.03
        with self.assertRaisesRegex(PolicyError, "timed out"):
            self.policy.act(self.observation)
        pointer = json.loads((self.policy.directory / "ready.json").read_text())
        self.assertEqual(pointer["status"], "failed")
        with self.assertRaises(PolicyError):
            self.policy.act(Observation(step=1, instruction="Move.", state=(0.25,)))

    def test_existing_directory_and_unknown_parameters_are_rejected(self) -> None:
        with self.assertRaises(FileExistsError):
            MailboxPolicy(self.policy.directory)
        with self.assertRaisesRegex(ValueError, "unknown"):
            make_mailbox_policy({"directory": str(self.root / "new"), "provider_retries": 3})
        with self.assertRaisesRegex(ValueError, "absolute"):
            MailboxPolicy("relative/path")

    def test_privileged_or_undeclared_observations_are_rejected(self) -> None:
        self.policy.end_episode()
        with self.assertRaisesRegex(ProtocolError, "non-privileged"):
            self.policy.start_episode(context(privileged=True))
        self.policy.start_episode(context())
        with self.assertRaisesRegex(ProtocolError, "camera"):
            self.policy.act(Observation(step=0, instruction="Move.", state=(0,), images={"oracle": object()}))

    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlink_response_is_rejected(self) -> None:
        def symlink_writer(path: Path, payload: Any) -> None:
            target = self.root / "outside-response.json"
            atomic_write_json(target, payload)
            path.symlink_to(target)

        with self.assertRaises(PolicyError):
            self.exchange(writer=symlink_writer)


if __name__ == "__main__":
    unittest.main()
