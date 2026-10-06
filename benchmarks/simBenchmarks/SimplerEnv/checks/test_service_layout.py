"""Service layout and protocol-data checks without native simulators."""

import json
from importlib.resources import files
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchmarks.simBenchmarks.SimplerEnv.bench_server import adapter
from benchmarks.simBenchmarks.SimplerEnv import server


class ServiceLayoutChecks(unittest.TestCase):
    def test_server_example_selects_agent_method_with_native_can_horizon(self):
        parameters = json.loads((Path(server.__file__).parent / "server.example.json").read_text())
        benchmark = server.make_simpler_env(parameters)
        self.assertEqual(parameters["interaction_mode"], "agent_method")
        self.assertIs(parameters["action_rejection_feedback"], True)
        self.assertEqual(benchmark.budget_mode, "horizon")
        self.assertEqual((benchmark.native_horizon, benchmark.evaluation_horizon), (80, 80))
        self.assertIsNone(benchmark.max_policy_calls)
        self.assertIsNone(benchmark.replan_interval)

    def test_interaction_mode_is_opt_in_and_preserves_native_conditions(self):
        for budget, suffix in (({}, ""), ({"budget_mode": "decisions", "max_policy_calls": 200,
                                           "replan_interval": 5}, "/decision-200-prefix-5"),
                               ({"horizon_multiplier": 2}, "/extended-2x")):
            for proprioception in (False, True):
                for feedback in (False, True):
                    arguments = {**budget, "proprioception": proprioception,
                                 "action_rejection_feedback": feedback}
                    with self.subTest(arguments=arguments):
                        historical = server.make_simpler_env(arguments)
                        explicit_old = server.make_simpler_env({**arguments, "interaction_mode": "single_response"})
                        method = server.make_simpler_env({**arguments, "interaction_mode": "agent_method"})
                        expected = ("simpler-prepackaged-development/"
                                    + ("rgb-qpos" if proprioception else "rgb") + suffix
                                    + ("/action-feedback" if feedback else "") + "/v1")
                        self.assertEqual(historical.descriptor.protocol_version, expected)
                        self.assertEqual(explicit_old.descriptor, historical.descriptor)
                        self.assertEqual(historical.budget_metadata(), explicit_old.budget_metadata())
                        self.assertEqual(method.descriptor.protocol_version, expected[:-3] + "/agent-method/v1")
                        self.assertEqual(method.action_spec, historical.action_spec)
                        self.assertEqual(method.observation_spec, historical.observation_spec)
                        self.assertEqual(method.budget_metadata(),
                                         {**historical.budget_metadata(), "interaction_mode": "agent_method"})
                        old_episode, = historical.episodes(seed=41, limit=1)
                        new_episode, = method.episodes(seed=41, limit=1)
                        self.assertEqual(new_episode.to_dict(), {
                            **old_episode.to_dict(),
                            "metadata": {**old_episode.metadata, "interaction_mode": "agent_method"},
                        })

    def test_invalid_interaction_modes_are_rejected_before_native_open(self):
        for value in (None, True, 0, [], {}, "", "agent-method", "unknown"):
            with self.subTest(value=value), patch.object(adapter.SimplerEnvBenchmarkAdapter, "open_episode") as opened:
                with self.assertRaisesRegex(ValueError, "interaction_mode"):
                    server.make_simpler_env({"interaction_mode": value})
                opened.assert_not_called()

    def test_service_description_retains_selected_mode_without_claiming(self):
        from benchkit.sim_server.server import BenchmarkService

        parameters = {"interaction_mode": "agent_method", "action_rejection_feedback": True}
        benchmark = server.make_simpler_env(parameters)
        with tempfile.TemporaryDirectory() as temporary, patch.object(benchmark, "open_episode") as opened:
            service = BenchmarkService(benchmark, root=Path(temporary) / "server", seed=41,
                                       limit=1, parameters=parameters)
            description = service.dispatch("describe", {})
            self.assertEqual(description["parameters"], parameters)
            self.assertEqual(description["episodes"][0]["metadata"]["interaction_mode"], "agent_method")
            self.assertEqual(description["budget"]["environment_step_cap"], 60)
            self.assertFalse(service.claims)
            opened.assert_not_called()

    def test_native_provenance_binds_mode_before_native_construction(self):
        class ConstructionReached(Exception):
            pass

        construction_arguments = []

        def make(env_id, **kwargs):
            construction_arguments.append((env_id, kwargs))
            raise ConstructionReached

        for mode in ("single_response", "agent_method"):
            benchmark = server.make_simpler_env({"interaction_mode": mode})
            session = benchmark.open_episode(benchmark.episodes(41)[0])
            modules = {
                "gymnasium": SimpleNamespace(spec=lambda _: SimpleNamespace(max_episode_steps=60), make=make),
                "mani_skill2_real2sim": SimpleNamespace(__file__="/fixture/native/mani_skill2_real2sim/__init__.py"),
                "simpler_env": SimpleNamespace(__file__="/fixture/simpler/simpler_env/__init__.py",
                    ENVIRONMENT_MAP={benchmark.task: ("fixture-id", {})}),
            }
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                session.bind_artifact_dir(Path(temporary))
                with patch.dict("sys.modules", modules), patch.object(adapter, "_revision", return_value={}):
                    with self.assertRaises(ConstructionReached):
                        session.reset()
                provenance = json.loads((Path(temporary) / "native_provenance.json").read_text())
                self.assertEqual(provenance["interaction_mode"], mode)
                self.assertEqual(provenance["track"], benchmark.descriptor.protocol_version)
                self.assertEqual(provenance["native_horizon"], 60)
                self.assertEqual(session.metrics()["interaction_mode"], mode)
        self.assertEqual(len(construction_arguments), 2)
        self.assertEqual(construction_arguments[0], construction_arguments[1])

    def test_action_feedback_is_opt_in_and_has_a_distinct_protocol(self):
        for budget in ({}, {"budget_mode": "decisions", "max_policy_calls": 200,
                           "replan_interval": 5}, {"horizon_multiplier": 2}):
            for proprioception in (False, True):
                arguments = {**budget, "proprioception": proprioception}
                with self.subTest(arguments=arguments):
                    historical = server.make_simpler_env(arguments)
                    explicit_off = server.make_simpler_env({**arguments, "action_rejection_feedback": False})
                    feedback = server.make_simpler_env({**arguments, "action_rejection_feedback": True})
                    self.assertFalse(historical.action_rejection_feedback)
                    self.assertTrue(feedback.action_rejection_feedback)
                    self.assertEqual(historical.descriptor.protocol_version, explicit_off.descriptor.protocol_version)
                    self.assertEqual(feedback.descriptor.protocol_version,
                                     historical.descriptor.protocol_version[:-3] + "/action-feedback/v1")
                    self.assertEqual(historical.budget_metadata(), feedback.budget_metadata())
                    self.assertEqual(historical.action_spec, feedback.action_spec)
                    self.assertEqual(historical.observation_spec, feedback.observation_spec)
        for invalid in (None, 0, 1, "true", [], {}):
            with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                server.make_simpler_env({"action_rejection_feedback": invalid})

    def test_canonical_entrypoint_has_no_compatibility_files(self):
        directory = Path(__file__).resolve().parents[1]
        self.assertFalse((directory / "adapter.py").exists())
        self.assertFalse((directory / "evaluation/plan.py").exists())
        self.assertTrue((directory / "bench_server/protocol/plan.py").is_file())
        self.assertIs(server.make_simpler_env, adapter.make_simpler_env)

    def test_catalog_matches_pinned_runtime_inventory_in_order(self):
        catalog = json.loads(files(
            "benchmarks.simBenchmarks.SimplerEnv.bench_server.protocol"
        ).joinpath("task_catalog.json").read_text())
        self.assertEqual(len(catalog), 15)
        self.assertEqual(
            [(row["id"], row["native_horizon"]) for row in catalog],
            list(adapter.TASK_HORIZONS.items()),
        )

    def test_server_factory_preserves_action_and_observation_tracks(self):
        for task, camera, joints, hz in (
            ("widowx_spoon_on_towel", "3rd_view_camera", 8, 5.0),
            ("google_robot_pick_horizontal_coke_can", "overhead_camera", 11, 3.0),
        ):
            for proprioception in (False, True):
                with self.subTest(task=task, proprioception=proprioception):
                    benchmark = server.make_simpler_env({
                        "task": task, "proprioception": proprioception,
                    })
                    self.assertEqual(benchmark.action_spec.size, 7)
                    self.assertEqual(benchmark.action_spec.mode, "ee_delta_pose")
                    self.assertEqual(benchmark.action_spec.control_hz, hz)
                    self.assertEqual(benchmark.observation_spec.cameras, (camera,))
                    self.assertEqual(len(benchmark.observation_spec.state_names),
                                     joints if proprioception else 0)
                    episode, = benchmark.episodes(seed=41, limit=1)
                    self.assertEqual(episode.seed, 41)
                    self.assertEqual(episode.task, task)


if __name__ == "__main__":
    unittest.main()
