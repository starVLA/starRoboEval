"""Native-free checks for the single public RoboDojo server."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from benchmarks.simBenchmarks.RoboDojo.bench_server import adapter as adapter_module
from benchmarks.simBenchmarks.RoboDojo import server
from benchmarks.simBenchmarks.RoboDojo.bench_server.protocol.robot_feedback import SCHEMA
from benchmarks.simBenchmarks.RoboDojo.bench_server.protocol.task_catalog import load_catalog


DIRECTORY = Path(__file__).resolve().parents[1]
SEED = 20260907


def example():
    return json.loads((DIRECTORY / "server.example.json").read_text())


class RoboDojoServerChecks(unittest.TestCase):
    def build(self, values=None):
        with patch.object(adapter_module, "load_runtime", return_value={"python": "/native/bin/python"}):
            return server.make_robodojo(example() if values is None else values)

    def test_example_is_the_single_catalog_task_and_protocol(self):
        value = self.build()
        catalog = load_catalog()
        episodes = value.episodes(SEED)
        self.assertEqual(value.descriptor.name, "robodojo")
        self.assertEqual(value.descriptor.protocol_version, catalog["interface_protocol"])
        self.assertEqual([episode.task for episode in episodes], ["classify_objects"] * 5)
        self.assertEqual([episode.metadata["layout_id"] for episode in episodes], list(range(5)))
        self.assertEqual(value.native_horizon, 1100)
        self.assertEqual(value.environment_step_cap, 1100)
        self.assertIsNone(value.max_policy_calls)
        self.assertIsNone(value.replan_interval)
        self.assertEqual(value.robot_feedback, SCHEMA)
        self.assertEqual(value.observation_spec.control_feedback_schema, SCHEMA)
        self.assertEqual(value.action_spec.size, 16)

    def test_factory_rejects_protocol_selectors_unknown_tasks_and_bad_panels(self):
        for update in ({"protocol_track": "reference-eef-v2"}, {"robot_feedback": SCHEMA},
                       {"task_id": "arrange_largest_number"}, {"layout_ids": [0, 1]},
                       {"panel": "unknown"}, {"policy": "hidden-policy"}):
            with self.subTest(update=update), self.assertRaises((TypeError, ValueError)):
                self.build({**example(), **update})

    def test_entrypoint_captures_only_final_runtime_sources(self):
        self.assertEqual(server.SUPPLEMENTAL_FILES, (
            "benchmarks/simBenchmarks/RoboDojo/__init__.py",
            "benchmarks/simBenchmarks/RoboDojo/server.py",
            "benchmarks/simBenchmarks/RoboDojo/bench_server/__init__.py",
            "benchmarks/simBenchmarks/RoboDojo/bench_server/adapter.py",
            "benchmarks/simBenchmarks/RoboDojo/bench_server/native_worker_client.py",
            "benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/__init__.py",
            "benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/robot_feedback.py",
            "benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/task_catalog.json",
            "benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/task_catalog.py",
            "benchmarks/simBenchmarks/RoboDojo/environment/__init__.py",
            "benchmarks/simBenchmarks/RoboDojo/environment/asset_reference.py",
            "benchmarks/simBenchmarks/RoboDojo/environment/eef_kinematics.py",
            "benchmarks/simBenchmarks/RoboDojo/environment/reference_eef_runtime.py",
            "benchmarks/simBenchmarks/RoboDojo/environment/reference_eef_snapshot.json",
            "benchmarks/simBenchmarks/RoboDojo/environment/worker_runtime.py",
            "benchmarks/simBenchmarks/RoboDojo/environment/native_eef_worker.py",
        ))
        with patch.object(server, "launch", return_value=0) as launch:
            self.assertEqual(server.main(["--help"]), 0)
        launch.assert_called_once_with(server.make_robodojo, excluded_artifact_directories=("cache",),
                                       require_complete_schedule=True,
                                       supplemental_sources=server.SUPPLEMENTAL_FILES, argv=["--help"])

    def test_launcher_describes_final_service_without_opening_native_worker(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "server"
            http = Mock(server_port=8767)
            seen = []

            def connect(service, **kwargs):
                seen.append(service.dispatch("describe", {}))
                return http

            with (patch.dict(os.environ, {"RSI_SIM_SERVER_TOKEN": "s" * 48}),
                  patch.object(adapter_module, "load_runtime", return_value={"python": "/native/bin/python"}),
                  patch("benchkit.sim_server.launch.make_http_server", side_effect=connect),
                  patch.object(adapter_module.DirectEEFBenchmarkAdapter, "open_episode",
                               side_effect=AssertionError("native open")),
                  redirect_stdout(io.StringIO()) as stdout):
                result = server.main(["--parameters", str(DIRECTORY / "server.example.json"),
                                      "--seed", str(SEED),
                                      "--output-dir", str(output), "--port", "8767"])
            self.assertEqual(result, 0)
            self.assertEqual(json.loads(stdout.getvalue())["native_resets"], 0)
            description = seen[0]
            self.assertEqual(description["descriptor"]["protocol_version"], load_catalog()["interface_protocol"])
            self.assertEqual(description["episodes"][0]["task"], "classify_objects")
            self.assertEqual(len(description["episodes"]), 5)
            self.assertEqual(description["budget"]["environment_step_cap"], 1100)
            self.assertIsNone(description["budget"]["max_policy_calls"])
            self.assertEqual(len(description["source"]["supplemental_files"]), len(server.SUPPLEMENTAL_FILES))
            for item in description["source"]["supplemental_files"]:
                relative = item["path"]
                expected = (DIRECTORY.parents[2] / relative).read_bytes()
                self.assertEqual(item["sha256"], hashlib.sha256(expected).hexdigest())
                self.assertEqual((output / "service_source" / relative).read_bytes(), expected)

    def test_import_does_not_load_native_worker_or_model(self):
        code = ("import json,sys; import benchmarks.simBenchmarks.RoboDojo.server; "
                "blocked=('isaacsim','isaaclab','omni','torch','AgentPolicies',"
                "'benchmarks.simBenchmarks.RoboDojo.environment.worker_runtime',"
                "'benchmarks.simBenchmarks.RoboDojo.environment.native_eef_worker'); "
                "print(json.dumps([name for name in blocked if any(k==name or k.startswith(name+'.') for k in sys.modules)]))")
        result = subprocess.run([sys.executable, "-B", "-c", code], cwd=DIRECTORY.parents[2],
                                text=True, capture_output=True, check=True)
        self.assertEqual(json.loads(result.stdout), [])


if __name__ == "__main__":
    unittest.main()
