"""Fixtures for the static ownership guard; no native imports or scored episodes."""

from pathlib import Path
import tempfile
import unittest

from benchkit.checks.check_boundaries import BENCHMARKS, MIGRATED_BENCHMARKS, NESTED_ADAPTERS, SERVER_ONLY_BENCHMARKS, check


class BoundaryChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.write("benchkit/contracts.py", "from dataclasses import dataclass\n")
        self.write("AgentPolicies/example/policy.py", "from benchkit.contracts import Example\n")
        for benchmark in BENCHMARKS:
            base = f"benchmarks/simBenchmarks/{benchmark}"
            adapter_path = "bench_server/adapter.py" if benchmark in MIGRATED_BENCHMARKS else "adapter.py"
            plan_path = "bench_server/protocol/plan.py" if benchmark in MIGRATED_BENCHMARKS else "evaluation/plan.py"
            for name in (adapter_path, "server.py", plan_path, "EVALUATION_PROTOCOL.md"):
                self.write(f"{base}/{name}", "")
        for benchmark in SERVER_ONLY_BENCHMARKS:
            base = f"benchmarks/simBenchmarks/{benchmark}"
            adapter_path = "bench_server/adapter.py"
            for name in (adapter_path, "server.py", "EVALUATION_PROTOCOL.md"):
                self.write(f"{base}/{name}", "")

    def write(self, relative, content):
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def violations(self):
        return check(self.root)[0]

    def test_clean_fixture(self):
        self.assertEqual(self.violations(), [])

    def test_old_policy_root_and_imports_are_not_compatibility_entrypoints(self):
        self.write("starVLA/__init__.py", "")
        self.assertTrue(any("starVLA: removed namespace" in item for item in self.violations()))
        (self.root / "starVLA/__init__.py").unlink()
        self.write("AgentPolicies/example/policy.py", "from starVLA.policy_support import runner\n")
        self.assertTrue(any("removed starVLA namespace" in item for item in self.violations()))

    def test_removed_benchmark_entrypoints_must_not_be_reintroduced(self):
        for benchmark in NESTED_ADAPTERS:
            for path in ("adapter.py", "evaluation/__init__.py", "evaluation/plan.py"):
                relative = f"benchmarks/simBenchmarks/{benchmark}/{path}"
                with self.subTest(path=relative):
                    self.write(relative, "")
                    self.assertTrue(any(relative in row and "removed compatibility" in row
                                        for row in self.violations()))
                    (self.root / relative).unlink()

    def test_standalone_service_needs_no_unimplemented_campaign_plan(self):
        self.assertFalse((self.root / "benchmarks/simBenchmarks/MetaWorld/evaluation/plan.py").exists())
        self.assertEqual(self.violations(), [])
        (self.root / "benchmarks/simBenchmarks/MetaWorld/server.py").unlink()
        self.assertTrue(any("MetaWorld/server.py: missing" in item for item in self.violations()))

    def test_metaworld_is_native_not_a_policy_dependency(self):
        self.write("AgentPolicies/example/policy.py", "def act():\n    import metaworld\n")
        self.assertTrue(any("native simulator" in item for item in self.violations()))

    def test_nested_benchmark_packages_cannot_import_participant(self):
        for package in ("bench_server", "bench_server/protocol"):
            relative = f"benchmarks/simBenchmarks/RoboDojo/{package}/helper.py"
            with self.subTest(package=package):
                self.write(relative, "import AgentPolicies.example.policy\n")
                self.assertTrue(any(relative in item and "model implementation" in item
                                    for item in self.violations()))
                self.write(relative, "")

    def test_robodojo_requires_its_nested_adapter(self):
        (self.root / "benchmarks/simBenchmarks/RoboDojo/bench_server/adapter.py").unlink()
        self.assertTrue(any("RoboDojo/bench_server/adapter.py: missing" in item
                            for item in self.violations()))

    def test_standalone_environment_helper_cannot_import_participant(self):
        self.write("benchmarks/simBenchmarks/MetaWorld/environment/runtime.py", "import AgentPolicies.example.policy\n")
        self.assertTrue(any("model implementation" in item for item in self.violations()))

    def test_existing_service_renderer_helper_cannot_import_participant(self):
        self.write("benchmarks/simBenchmarks/Robocasa_365/environment/render_lifecycle.py", "import AgentPolicies.example.policy\n")
        self.assertTrue(any("render_lifecycle.py" in item and "model implementation" in item
                            for item in self.violations()))

    def test_standalone_root_helper_cannot_import_participant(self):
        self.write("benchmarks/simBenchmarks/LIBERO-plus/bench_server/protocol/catalog.py", "import AgentPolicies.example.policy\n")
        self.assertTrue(any("LIBERO-plus/bench_server/protocol/catalog.py" in item and "model implementation" in item
                            for item in self.violations()))

    def test_model_cannot_import_sim_server_client(self):
        self.write("AgentPolicies/example/policy.py", "from benchkit.sim_server.client import SimServerBenchmarkAdapter\n")
        self.assertTrue(any("evaluator execution" in item for item in self.violations()))

    def test_removed_shared_service_import_is_rejected(self):
        self.write("benchkit/registry.py", "from benchmarks.simBenchmarks.service.client import SimServerBenchmarkAdapter\n")
        self.assertTrue(any("removed shared service namespace" in item for item in self.violations()))

    def test_shared_transport_must_not_be_duplicated_under_examples(self):
        self.write("benchmarks/simBenchmarks/service/server.py", "")
        self.assertTrue(any("shared transport belongs in benchkit/sim_server" in item for item in self.violations()))

    def test_only_declared_trusted_driver_may_import_service_client_not_native_adapter(self):
        self.write("AgentPolicies/gpt6_astra/run.py", "from benchkit.sim_server.client import SimServerBenchmarkAdapter\n")
        self.assertEqual(self.violations(), [])
        self.write("AgentPolicies/gpt6_astra/run.py", "from benchmarks.simBenchmarks.RoboDojo.bench_server.adapter import make_robodojo\n")
        self.assertTrue(any("native simulator" in item for item in self.violations()))

    def test_shared_service_cannot_depend_on_model_code(self):
        self.write("benchkit/sim_server/server.py", "import AgentPolicies.example.policy\n")
        self.assertTrue(any("extension imports" in item for item in self.violations()))

    def test_benchmark_server_is_required(self):
        (self.root / "benchmarks/simBenchmarks/SIMPLE/server.py").unlink()
        self.assertTrue(any("server.py: missing benchmark-owned" in item for item in self.violations()))

    def test_transport_numpy_is_lazy_only(self):
        self.write("benchkit/sim_server/wire.py", "def decode():\n    import numpy\n")
        self.assertEqual(self.violations(), [])
        self.write("benchkit/sim_server/wire.py", "import numpy\n")
        self.assertTrue(any("provider dependency" in item for item in self.violations()))

    def test_diagnostics_belong_to_harness_not_model_namespace(self):
        self.write("benchkit/diagnostics/constant.py", "from benchkit.contracts import PolicyDecision\n")
        self.assertEqual(self.violations(), [])
        self.write("AgentPolicies/diagnostics/constant.py", "")
        self.assertTrue(any("AgentPolicies/diagnostics" in item for item in self.violations()))

    def test_fixed_rgb_diagnostic_allows_only_lazy_image_decoder(self):
        relative = "benchkit/diagnostics/simpler_mailbox.py"
        self.write(relative, "def main():\n    from PIL import Image\n")
        self.assertEqual(self.violations(), [])
        for content in ("from PIL import Image\n", "def main():\n    import openai\n",
                        "def main():\n    import mujoco\n"):
            with self.subTest(content=content):
                self.write(relative, content)
                self.assertTrue(any("provider dependency" in item for item in self.violations()))

    def test_removed_namespace_rejected(self):
        self.write("AgentPolicies/example/policy.py", "from AgentPolicies.evaluation.contracts import Example\n")
        self.assertTrue(any("removed evaluator namespace" in item for item in self.violations()))

    def test_removed_diagnostic_import_rejected_without_old_directory(self):
        self.write("benchkit/registry.py", "from AgentPolicies.diagnostics.constant import ConstantPolicy\n")
        self.assertTrue(any("removed diagnostic namespace" in item for item in self.violations()))

    def test_model_cannot_import_native_simulator(self):
        self.write("AgentPolicies/example/policy.py", "def act():\n    import mujoco\n")
        self.assertTrue(any("native simulator" in item for item in self.violations()))

    def test_model_can_use_its_own_model_runtime(self):
        self.write("AgentPolicies/example/policy.py", "import torch\n")
        self.assertEqual(self.violations(), [])

    def test_benchmark_cannot_import_model(self):
        self.write("benchmarks/simBenchmarks/LIBERO/bench_server/adapter.py", "import AgentPolicies.example.policy\n")
        self.assertTrue(any("model implementation" in item for item in self.violations()))

    def test_harness_cannot_import_sdk(self):
        self.write("benchkit/contracts.py", "import openai\n")
        self.assertTrue(any("provider dependency" in item for item in self.violations()))

    def test_registration_does_not_grant_model_benchmark_construction(self):
        self.write("AgentPolicies/example/policy.py", "from benchkit.registry import register_policy\n")
        self.assertEqual(self.violations(), [])
        self.write("AgentPolicies/example/policy.py", "from benchkit.registry import create_benchmark\n")
        self.assertTrue(any("benchmark construction" in item for item in self.violations()))

    def test_frozen_result_source_is_not_inspected(self):
        self.write("AgentPolicies/example/results/task/raw/frozen/AgentPolicies/evaluation/runner.py", "import mujoco\n")
        self.assertEqual(self.violations(), [])

    def test_diagnostic_output_trees_are_not_active_source(self):
        before = check(self.root)
        for name in ("artifacts", "results", "rollouts"):
            self.write(f"benchkit/diagnostics/{name}/run/frozen/native.py", "not valid python !")
            self.write(f"benchkit/diagnostics/{name}/run/observation_payload.json", '{"private": true}')
        self.assertEqual(check(self.root), before)

    def test_lazy_media_dependency_is_explicitly_bounded(self):
        self.write("benchkit/audits/mailbox_artifacts.py", "def inspect():\n    import numpy\n")
        self.assertEqual(self.violations(), [])
        self.write("benchkit/audits/mailbox_artifacts.py", "import numpy\n")
        self.assertTrue(any("provider dependency" in item for item in self.violations()))

    def test_old_empty_directory_is_not_active_source(self):
        (self.root / "AgentPolicies/evaluation").mkdir()
        self.assertEqual(self.violations(), [])
        self.write("AgentPolicies/evaluation/__init__.py", "")
        self.assertTrue(any("outside AgentPolicies" in item for item in self.violations()))

    def test_missing_benchmark_plan_is_visible(self):
        (self.root / "benchmarks/simBenchmarks/LIBERO/bench_server/protocol/plan.py").unlink()
        self.assertTrue(any("missing benchmark-owned component" in item for item in self.violations()))


if __name__ == "__main__":
    unittest.main()
