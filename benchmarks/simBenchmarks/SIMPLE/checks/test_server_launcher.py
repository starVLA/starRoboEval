"""Stdlib-only benchmark launcher checks; never create a native environment."""
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.simBenchmarks.SIMPLE.bench_server import adapter as codec
from benchmarks.simBenchmarks.SIMPLE.bench_server import native_worker_client
from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import make_simple_humanoid
from benchmarks.simBenchmarks.SIMPLE.bench_server.source_inventory import CAMPAIGN_SUPPLEMENTAL_FILES, SUPPLEMENTAL_FILES


SERVER = Path(__file__).resolve().parents[1] / "server.py"


class ServerLauncherTests(unittest.TestCase):
    def test_canonical_entrypoint_has_no_compatibility_files(self):
        from benchmarks.simBenchmarks.SIMPLE import server
        self.assertIs(server.make_simple_humanoid, codec.make_simple_humanoid)
        self.assertFalse((SERVER.parent / "adapter.py").exists())
        self.assertFalse((SERVER.parent / "evaluation/plan.py").exists())
        self.assertTrue((SERVER.parent / "bench_server/protocol/plan.py").is_file())

    def test_nested_adapter_resolves_original_private_worker_before_launch(self):
        # Stop at Popen: this checks the real reset path resolution without a SIM.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / "native/.venv/bin/python"
            python.parent.mkdir(parents=True)
            python.touch()
            adapter = make_simple_humanoid({"simple_root": str(root / "native")})
            session = adapter.open_episode(adapter.episodes()[0])
            session.bind_artifact_dir(root / "artifacts")
            try:
                with patch.object(native_worker_client.subprocess, "Popen", side_effect=RuntimeError("launch stopped")) as launch:
                    with self.assertRaisesRegex(RuntimeError, "launch stopped"):
                        session.reset()
                args, kwargs = launch.call_args
                self.assertEqual(Path(args[0][1]), SERVER.parent / "environment/native_worker.py")
                repository = SERVER.parents[3]
                self.assertEqual(kwargs["env"]["PYTHONPATH"].split(":")[0], str(repository))
            finally:
                if session.log:
                    session.log.close()

    def test_import_does_not_launch(self):
        with patch("benchkit.sim_server.launch.main") as launch:
            runpy.run_path(str(SERVER), run_name="simple_server_import_fixture")
        launch.assert_not_called()

    def test_server_import_does_not_load_plan_models_or_native_runtime(self):
        subprocess.run([sys.executable, "-B", "-c", "import sys; "
            "import benchmarks.simBenchmarks.SIMPLE.server; "
            "assert 'benchmarks.simBenchmarks.SIMPLE.bench_server.protocol.plan' not in sys.modules; "
            "assert not any(n == 'AgentPolicies' or n.startswith('AgentPolicies.') for n in sys.modules); "
            "assert not any(n in sys.modules for n in ('torch', 'simple', 'mujoco', 'isaacsim'))"],
            check=True)

    def test_service_inventory_captures_worker_and_package_sources(self):
        from benchmarks.simBenchmarks.SIMPLE import server
        from benchmarks.simBenchmarks.SIMPLE.bench_server.protocol import plan
        self.assertIs(server.SUPPLEMENTAL_FILES, SUPPLEMENTAL_FILES)
        self.assertIs(plan.SUPPLEMENTAL_FILES, CAMPAIGN_SUPPLEMENTAL_FILES)
        self.assertEqual(CAMPAIGN_SUPPLEMENTAL_FILES, (
            "benchmarks/simBenchmarks/SIMPLE/environment/native_worker.py",
            "benchmarks/simBenchmarks/SIMPLE/environment/upstream.json",
            "benchmarks/simBenchmarks/SIMPLE/bench_server/protocol/POLICY_GUIDE.md",
        ))
        repository = SERVER.parents[3]
        prefix = "benchmarks/simBenchmarks/SIMPLE/"
        required = {prefix + name for name in ("server.py", "bench_server/adapter.py",
            "bench_server/native_worker_client.py", "bench_server/source_inventory.py",
            "environment/native_worker.py", "environment/upstream.json",
            "bench_server/protocol/POLICY_GUIDE.md", "bench_server/protocol/simple_released_tasks.json")}
        self.assertTrue(required <= set(SUPPLEMENTAL_FILES))
        self.assertEqual(len(SUPPLEMENTAL_FILES), len(set(SUPPLEMENTAL_FILES)))
        for source in SUPPLEMENTAL_FILES:
            self.assertTrue((repository / source).is_file(), source)
            self.assertNotIn("/evaluation/", source)

    def test_main_accepts_explicit_argv(self):
        from benchmarks.simBenchmarks.SIMPLE import server
        with patch.object(server, "launch", return_value=19) as launch:
            self.assertEqual(server.main(["--help"]), 19)
        launch.assert_called_once_with(make_simple_humanoid,
            excluded_artifact_directories=("cache",),
            supplemental_sources=SUPPLEMENTAL_FILES, argv=["--help"])

    def test_private_client_roundtrip_finalization_and_close_without_simulator(self):
        client = native_worker_client.NativeWorkerClient(SimpleNamespace(worker_timeout=5), None)
        code = ("import json, sys\n"
                "for line in sys.stdin:\n"
                " request = json.loads(line)\n"
                " result = {'video_head': 'head.mp4'} if request['op'] == 'finalize' else request\n"
                " print(json.dumps({'ok': True, 'result': result}), flush=True)\n"
                " if request['op'] == 'close': break\n")
        client.process = subprocess.Popen([sys.executable, "-B", "-u", "-c", code],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1)
        try:
            request = {"op": "step", "action": [0.0] * 36}
            self.assertEqual(client._rpc(request), request)
            self.assertEqual(client.artifacts(), {"video_head": "head.mp4"})
        finally:
            client.close()
        self.assertEqual(client.process.returncode, 0)
        self.assertTrue(client.process.stdin.closed)
        self.assertTrue(client.process.stdout.closed)

    def test_main_declares_native_factory_sources_and_only_runtime_cache_exclusion(self):
        # A mocked common launcher guarantees no socket, native process or reset.
        with patch("benchkit.sim_server.launch.main", return_value=17) as launch:
            with self.assertRaises(SystemExit) as exit_context:
                runpy.run_path(str(SERVER), run_name="__main__")
        self.assertEqual(exit_context.exception.code, 17)
        launch.assert_called_once_with(
            make_simple_humanoid,
            excluded_artifact_directories=("cache",),
            supplemental_sources=SUPPLEMENTAL_FILES,
            argv=None,
        )


if __name__ == "__main__":
    unittest.main()
