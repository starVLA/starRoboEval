"""Dependency-light protocol checks, never a native replay or model score."""
from __future__ import annotations

from contextlib import ExitStack
from dataclasses import replace
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from benchkit.contracts import Observation
from benchkit.errors import CompatibilityError, ProtocolError

adapter = importlib.import_module("benchmarks.simBenchmarks.LIBERO-plus.bench_server.adapter")
catalog = importlib.import_module("benchmarks.simBenchmarks.LIBERO-plus.bench_server.protocol.catalog")
configure = importlib.import_module("benchmarks.simBenchmarks.LIBERO-plus.environment.configure")
readiness = importlib.import_module("benchmarks.simBenchmarks.LIBERO-plus.environment.verify_environment")


def make(**kwargs):
    return adapter.LiberoPlusBenchmarkAdapter(upstream="/nonexistent/owned/LIBERO-plus", **kwargs)


class CatalogChecks(unittest.TestCase):
    def test_exact_four_suite_universe_and_counts(self):
        self.assertEqual(catalog.COUNTS, {"libero_spatial": 2402, "libero_object": 2518,
                                         "libero_goal": 2591, "libero_10": 2519})
        all_ids = []
        for suite, count in catalog.COUNTS.items():
            data = catalog.task_catalog(suite)
            self.assertEqual(len(data["tasks"]), count)
            self.assertEqual(sum(data["category_counts"].values()), count)
            self.assertEqual(len(data["category_counts"]), 7)
            all_ids += [(suite, row["native_id"]) for row in data["tasks"]]
        self.assertEqual(len(all_ids), 10030)
        self.assertEqual(len(set(all_ids)), 10030)

    def test_each_runtime_catalog_fits_source_capture_bound(self):
        directory = Path(catalog.__file__).with_name("catalogs")
        for suite in catalog.COUNTS:
            self.assertLess((directory / (suite + ".json")).stat().st_size, 2 * 1024**2)

    def test_excludes_native_90_and_unknown_suites(self):
        for suite in ("libero_90", "LIBERO_SPATIAL", "libero_plus", "../libero_spatial"):
            with self.subTest(suite=suite), self.assertRaises(ValueError):
                catalog.task_catalog(suite)

    def test_all_variants_resolve_exact_frozen_initial_files(self):
        for suite in catalog.COUNTS:
            for row in catalog.task_catalog(suite)["tasks"]:
                files = catalog.native_files(suite, row["native_name"])
                self.assertEqual(files["initial_file"], row["initial_file"])
                self.assertEqual(files["virtual_bddl"], f"{suite}/{row['native_name']}.bddl")

    def test_view_virtual_bddl_is_not_its_backing_file(self):
        row = catalog.task_catalog("libero_spatial")["tasks"][608]
        files = catalog.native_files("libero_spatial", row["native_name"])
        self.assertIn("_view_0_0_100_2_352_initstate_0", files["virtual_bddl"])
        self.assertNotIn("_view_", files["bddl"])
        self.assertNotIn("_view_", files["initial_file"])

    def test_language_reset_precedes_view_and_keeps_rewritten_bddl(self):
        row = catalog.task_catalog("libero_spatial")["tasks"][984]
        files = catalog.native_files("libero_spatial", row["native_name"])
        self.assertIn("_language_1.bddl", files["bddl"])
        self.assertNotIn("_language_", files["initial_file"])
        self.assertEqual(row["instruction"], row["native_instruction"])

    def test_table_tb_light_and_layout_branches(self):
        for name, initial in (
            ("move_table_12", "libero_goal/move.pruned_init"),
            ("move_tb_12", "libero_goal/move.pruned_init"),
            ("move_light_12", "libero_goal/move.pruned_init"),
            ("move_add_12", "libero_newobj/libero_goal/move_add_12.pruned_init"),
            ("move_level1", "libero_newobj/libero_goal/move_level1.pruned_init"),
        ):
            with self.subTest(name=name):
                self.assertEqual(catalog.native_files("libero_goal", name)["initial_file"], initial)

    def test_no_invented_reset_fallback_or_unsafe_paths(self):
        for name in ("plain_task", "../move_table_1", "/absolute_table_1", "move table 1"):
            with self.subTest(name=name), self.assertRaises((ValueError, CompatibilityError)):
                catalog.native_files("libero_spatial", name)

    def test_public_instruction_contains_no_filename_parameter_tail(self):
        for suite in catalog.COUNTS:
            for row in catalog.task_catalog(suite)["tasks"]:
                self.assertNotIn(" initstate ", row["instruction"])
                self.assertNotIn("_initstate_", row["instruction"])
                self.assertNotIn("_view_", row["instruction"])
        row = catalog.task_catalog("libero_spatial")["tasks"][608]
        self.assertIn("initstate", row["native_instruction"])
        self.assertNotEqual(row["instruction"], row["native_instruction"])

    def test_source_inventory_has_core_semantics_and_unique_safe_paths(self):
        data = json.loads((Path(adapter.__file__).parents[1] / "environment" / "native_source_manifest.json").read_text())
        paths = [row["path"] for row in data["files"]]
        self.assertEqual(len(paths), len(set(paths)))
        for suffix in ("benchmark/__init__.py", "benchmark/task_classification.json", "envs/env_wrapper.py",
                       "envs/bddl_base_domain.py", "envs/robots/new_init.py", "envs/arenas/table_arena.py"):
            self.assertIn("libero/libero/" + suffix, paths)
        self.assertTrue(all(path.startswith("libero/libero/") and ".." not in Path(path).parts for path in paths))


class AdapterChecks(unittest.TestCase):
    def test_selection_and_import_are_lazy(self):
        code = """import importlib, sys
m = importlib.import_module('benchmarks.simBenchmarks.LIBERO-plus.bench_server.adapter')
a = m.LiberoPlusBenchmarkAdapter(upstream='/missing/native')
assert len(a.episodes(7)) == 1
assert not any(x in sys.modules for x in ('numpy', 'libero', 'robosuite', 'mujoco', 'torch'))
"""
        subprocess.run([sys.executable, "-B", "-c", code], check=True, timeout=30,
                       cwd=Path(__file__).resolve().parents[4])

    def test_fast_selection_one_attempt_state_zero_and_safe_public_task(self):
        benchmark = make(task_ids=[258, 608, 984])
        episodes = benchmark.episodes(7)
        self.assertEqual([episode.task for episode in episodes],
                         ["libero_spatial/task-258", "libero_spatial/task-608", "libero_spatial/task-984"])
        for episode in episodes:
            self.assertEqual(episode.metadata["attempt"], 1)
            self.assertEqual(episode.metadata["initial_state_index"], 0)
            self.assertEqual(episode.metadata["evaluation_mode"], "fast")
            self.assertNotIn("initstate", episode.instruction)
            self.assertNotIn("_view_", episode.task)
        self.assertEqual(len(benchmark.episodes(7, limit=1)), 1)

    def test_invalid_selections_rejected(self):
        for ids in ([], [True], [1, 0], [0, 0], [-1], [2402], "0", {0}):
            with self.subTest(ids=ids), self.assertRaises(ValueError):
                make(task_ids=ids)
        for mode in ("full", "pilot", None):
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                make(evaluation_mode=mode)

    def test_invalid_seed_limit_and_gpu_rejected(self):
        benchmark = make()
        for seed in (-1, 2**32, True, 7.0, "7"):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                benchmark.episodes(seed)
        for limit in (0, 2, True, -1, 1.0):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                benchmark.episodes(7, limit=limit)
        for gpu in (-1, True, "0"):
            with self.assertRaises(ValueError):
                make(render_gpu_device_id=gpu)

    def test_unknown_parameters_and_relative_upstream_rejected(self):
        with self.assertRaises(ValueError):
            adapter.make_libero_plus({"upstream": "/native", "proprioception": True})
        for path in ("relative", "", None):
            with self.assertRaises(ValueError):
                adapter.LiberoPlusBenchmarkAdapter(upstream=path)

    def test_reference_horizons_and_extended_decision_budget_distinct(self):
        for suite, horizon in catalog.HORIZONS.items():
            baseline = make(suite=suite)
            self.assertEqual(baseline.environment_step_cap, horizon)
            extended = make(suite=suite, budget_mode="decisions", max_policy_calls=200, replan_interval=5)
            self.assertEqual(extended.environment_step_cap, 1000)
            self.assertEqual(extended.native_engine_horizon, 1010)
            self.assertEqual(extended.budget_metadata()["native_horizon"], horizon)
            self.assertNotEqual(baseline.descriptor.protocol_version, extended.descriptor.protocol_version)

    def test_invalid_budget_combinations_rejected(self):
        for kwargs in ({"budget_mode": "full"}, {"max_policy_calls": 200},
                       {"budget_mode": "decisions", "max_policy_calls": True, "replan_interval": 5},
                       {"budget_mode": "decisions", "max_policy_calls": 0, "replan_interval": 5},
                       {"budget_mode": "decisions", "max_policy_calls": 200},
                       {"budget_mode": "decisions", "max_policy_calls": 10000, "replan_interval": 5}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                make(**kwargs)

    def test_repeated_or_forged_episode_rejected(self):
        benchmark = make()
        episode = benchmark.episodes(7)[0]
        with self.assertRaises(ProtocolError):
            benchmark.open_episode(replace(episode, instruction="different"))
        benchmark.open_episode(episode)
        with self.assertRaises(ProtocolError):
            benchmark.open_episode(episode)

    def test_failed_reset_is_claimed_and_not_retried(self):
        benchmark = make()
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        with patch.object(adapter, "prepare_native_import", side_effect=CompatibilityError("missing native")) as prepare:
            with self.assertRaises(CompatibilityError):
                session.reset()
            with self.assertRaises(ProtocolError):
                session.reset()
            self.assertEqual(prepare.call_count, 1)
        with self.assertRaises(ProtocolError):
            session.step((0,) * 7)
        self.assertEqual(session.metrics()["settle_steps"], 0)
        self.assertEqual(session.metrics()["settle_control_attempts"], 0)
        self.assertTrue(session.finished)

    def test_partial_settle_failure_records_completed_and_uncertain_controls(self):
        benchmark = make()
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        calls = []

        def native_step(action):
            calls.append(action)
            if len(calls) == 4:
                raise RuntimeError("native control may have advanced")
            return {}, 0, False, {}

        session.env = SimpleNamespace(step=native_step)

        def reset_fixture():
            for _ in range(10):
                session._native_control([0.0] * 6 + [-1.0], settle=True)

        with tempfile.TemporaryDirectory() as directory:
            session.bind_artifact_dir(Path(directory))
            with patch.object(session, "_reset_once", side_effect=reset_fixture), self.assertRaises(RuntimeError):
                session.reset()
            events = [json.loads(line) for line in (Path(directory) / "native_events.jsonl").read_text().splitlines()]
        self.assertEqual(sum(row["event"] == "native_control_start" for row in events), 4)
        self.assertEqual(sum(row["event"] == "native_control_end" for row in events), 3)
        self.assertEqual({row["phase"] for row in events}, {"settle"})
        self.assertEqual(session.metrics()["settle_steps"], 3)
        self.assertEqual(session.metrics()["settle_control_attempts"], 4)
        self.assertEqual(session.metrics()["uncertain_native_controls"], 1)
        self.assertEqual(session.metrics()["native_steps"], 0)
        self.assertTrue(session.finished)
        with self.assertRaises(ProtocolError):
            session.reset()

    def test_native_step_error_poisoned_without_replay(self):
        benchmark = make()
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        session.initialized = True
        calls = []

        def native_step(action):
            calls.append(action)
            raise RuntimeError("native uncertain")

        session.env = SimpleNamespace(step=native_step)
        with self.assertRaises(RuntimeError):
            session.step((0,) * 7)
        with self.assertRaises(ProtocolError):
            session.step((0,) * 7)
        self.assertEqual(len(calls), 1)
        self.assertEqual(session.metrics()["native_steps"], 0)
        self.assertEqual(session.metrics()["native_control_attempts"], 1)
        self.assertEqual(session.metrics()["uncertain_native_controls"], 1)

    def test_render_error_preserves_executed_count_but_prevents_more_controls(self):
        benchmark = make()
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        session.initialized = True
        session.env = SimpleNamespace(step=lambda action: ({}, 0, False, {}))
        with patch.object(session, "_observe", side_effect=ProtocolError("bad RGB")), self.assertRaises(ProtocolError):
            session.step((0,) * 7)
        self.assertEqual(session.metrics()["native_steps"], 1)
        self.assertEqual(session.metrics()["native_control_attempts"], 1)
        self.assertEqual(session.metrics()["uncertain_native_controls"], 0)
        with self.assertRaises(ProtocolError):
            session.step((0,) * 7)

    def test_artifact_finalization_blocks_reset_and_step(self):
        benchmark = make()
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        self.assertEqual(session.artifacts(), {})
        with self.assertRaises(ProtocolError):
            session.reset()
        session.env = SimpleNamespace(step=lambda _: self.fail("must not step after finalization"))
        session.initialized = True
        with self.assertRaises(ProtocolError):
            session.step((0,) * 7)
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ProtocolError):
            session.bind_artifact_dir(Path(directory))

    def test_native_close_error_is_sticky_and_not_retried(self):
        benchmark = make()
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        calls = []
        original = RuntimeError("close uncertain")

        def native_close():
            calls.append(1)
            raise original

        session.env = SimpleNamespace(close=native_close)
        for _ in range(2):
            with self.assertRaises(RuntimeError) as caught:
                session.close()
            self.assertIs(caught.exception, original)
        self.assertEqual(calls, [1])

    def test_scoring_uses_step_done_and_drops_private_info(self):
        benchmark = make()
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        session.initialized = True
        native = SimpleNamespace(step=lambda action: ({"object_pose": "private"}, 1, True, {"secret": 42}))
        session.env = native
        with patch.object(adapter, "policy_observation", return_value=Observation(step=1, instruction="move")):
            transition = session.step((0,) * 7)
        self.assertTrue(transition.terminated)
        self.assertFalse(transition.truncated)
        self.assertEqual(transition.info, {"native_success": True, "native_steps": 1})
        self.assertEqual(transition.observation.metadata, {})
        with self.assertRaises(ProtocolError):
            session.step((0,) * 7)

    def test_cap_truncates_without_native_success(self):
        benchmark = make()
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        session.initialized = True
        session.env = SimpleNamespace(step=lambda action: ({}, 0, False, {}))
        session.step_count = benchmark.environment_step_cap - 1
        with patch.object(adapter, "policy_observation", return_value=Observation(step=220, instruction="move")):
            result = session.step((0,) * 7)
        self.assertTrue(result.truncated)
        self.assertFalse(result.terminated)
        self.assertFalse(session.metrics()["success"])

    def test_seven_normalized_actions_no_native_call_for_invalid_action(self):
        benchmark = make()
        self.assertEqual(benchmark.action_spec.validate((0,) * 7), (0.0,) * 7)
        self.assertEqual(benchmark.observation_spec.state_names, ())
        self.assertFalse(benchmark.observation_spec.privileged)
        for values in ((0,) * 6, (2,) * 7, (True,) * 7, (float("nan"),) * 7):
            with self.assertRaises((TypeError, ValueError)):
                benchmark.action_spec.validate(values)

    def test_writer_failure_still_closes_native_once(self):
        benchmark = make()
        session = benchmark.open_episode(benchmark.episodes(7)[0])
        calls = []
        session.env = SimpleNamespace(close=lambda: calls.append("native-close"))
        session.writers = {"agentview": SimpleNamespace(close=lambda: (_ for _ in ()).throw(OSError("disk")))}
        with self.assertRaises(OSError):
            session.close()
        with self.assertRaises(OSError):
            session.close()
        self.assertEqual(calls, ["native-close"])
        self.assertIsNone(session.env)


class EvidenceChecks(unittest.TestCase):
    def test_readiness_checks_data_without_constructing_native_environment(self):
        row = catalog.task_catalog("libero_spatial")["tasks"][0]
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            root = Path(directory)
            for name in ("articulated_objects", "new_objects", "scenes", "stable_hope_objects",
                         "stable_scanned_objects", "textures", "turbosquid_objects"):
                (root / "libero/libero/assets" / name).mkdir(parents=True)
            stack.enter_context(patch.object(adapter, "verify_native_source", return_value={"files": [0] * 60,
                "manifest_sha256": "a" * 64}))
            stack.enter_context(patch.object(catalog, "task_catalog", return_value={"tasks": [row]}))
            stack.enter_context(patch.object(catalog, "file_sha256", side_effect=lambda path:
                row["initial_file_sha256"] if str(path).endswith("pruned_init") else row["bddl_sha256"]))
            result = readiness.verify_inputs(root, ["libero_spatial"])
            self.assertEqual(result["catalog_variants_checked"], 1)
            self.assertEqual(result["unique_bddl_reset_files_checked"], 2)
            self.assertEqual(result["native_environments_constructed"], 0)
            self.assertEqual(result["native_controls"], 0)
            for suites in ([], ["libero_90"], ["libero_spatial", "libero_spatial"]):
                with self.assertRaises(ValueError):
                    readiness.verify_inputs(root, suites)

    def test_readiness_fails_on_catalog_input_mismatch(self):
        row = catalog.task_catalog("libero_spatial")["tasks"][0]
        with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
            stack.enter_context(patch.object(adapter, "verify_native_source", return_value={"files": []}))
            stack.enter_context(patch.object(catalog, "task_catalog", return_value={"tasks": [row]}))
            stack.enter_context(patch.object(catalog, "file_sha256", return_value="b" * 64))
            with self.assertRaises(ValueError):
                readiness.verify_inputs(Path(directory), ["libero_spatial"])

    def test_bounded_hash_and_missing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bytes"
            path.write_bytes(b"abc")
            self.assertEqual(catalog.file_sha256(path), hashlib.sha256(b"abc").hexdigest())
            with self.assertRaises(CompatibilityError):
                catalog.file_sha256(path, max_bytes=2)

    def test_config_is_explicit_external_and_idempotent_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "upstream"
            for suffix in ("assets", "bddl_files", "init_files"):
                (root / "libero/libero" / suffix).mkdir(parents=True)
            target = Path(directory) / "config"
            self.assertEqual(configure.configure(root, target), target.resolve())
            original = (target / "config.yaml").read_bytes()
            configure.configure(root, target)
            self.assertEqual((target / "config.yaml").read_bytes(), original)
            with self.assertRaises(ValueError):
                configure.configure(root, root / "config")
            (target / "config.yaml").write_text("different")
            with self.assertRaises(ValueError):
                configure.configure(root, target)

    def test_config_does_not_import_native_or_accept_missing_asset_tree(self):
        with tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
            configure.configure(Path(directory) / "missing", Path(directory) / "config")

    def test_selected_asset_receipt_is_bounded_and_labels_roots(self):
        with tempfile.TemporaryDirectory() as directory:
            root, suite_root = Path(directory) / "native", Path(directory) / "suite"
            path = root / "libero/libero/assets/test.bin"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"texture")
            native = SimpleNamespace(model=SimpleNamespace(get_xml=lambda: f'<mujoco><asset><texture file="{path}"/></asset></mujoco>'))
            receipt = adapter.selected_asset_receipt(native, root, suite_root)
            self.assertEqual(receipt["files"][0]["path"], "libero_plus_assets/test.bin")
            self.assertEqual(receipt["files"][0]["sha256"], hashlib.sha256(b"texture").hexdigest())
            self.assertEqual(receipt["unresolved_relative_references"], [])

    def test_selected_assets_outside_roots_rejected_unresolved_relative_explicit(self):
        native = SimpleNamespace(model=SimpleNamespace(get_xml=lambda: '<mujoco><asset><texture file="/etc/passwd"/></asset></mujoco>'))
        with self.assertRaises(CompatibilityError):
            adapter.selected_asset_receipt(native, Path("/native"), Path("/suite"))
        native.model.get_xml = lambda: '<mujoco><asset><texture file="relative.png"/></asset></mujoco>'
        receipt = adapter.selected_asset_receipt(native, Path("/native"), Path("/suite"))
        self.assertEqual(receipt["files"], [])
        self.assertEqual(receipt["unresolved_relative_references"], [{"tag": "texture", "file": "relative.png"}])


class ArrayChecks(unittest.TestCase):
    def setUp(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("NumPy optional CPU observation checks")
        self.np = np

    def test_exact_two_camera_orientation_independent_copy_allowlist(self):
        first = self.np.zeros((256, 256, 3), dtype=self.np.uint8)
        second = self.np.full((256, 256, 3), 20, dtype=self.np.uint8)
        first[0, 0] = [255, 4, 8]
        raw = {"agentview_image": first, "robot0_eye_in_hand_image": second,
               "robot0_eef_pos": [1, 2, 3], "robot0_joint_pos": [0] * 7, "success": True}
        observation = adapter.policy_observation(raw, 0, "move")
        self.assertEqual(tuple(observation.images), adapter.CAMERAS)
        self.assertTrue(self.np.array_equal(observation.images["agentview"][-1, -1], [255, 4, 8]))
        self.assertTrue(observation.images["agentview"].flags.c_contiguous)
        self.assertFalse(self.np.shares_memory(first, observation.images["agentview"]))
        self.assertIsNone(observation.state)
        self.assertEqual(observation.metadata, {})
        adapter.policy_observation(raw, 1, "move")
        self.assertTrue(self.np.array_equal(first[0, 0], [255, 4, 8]))

    def test_wrong_shape_dtype_or_missing_camera_rejected(self):
        good = self.np.zeros((256, 256, 3), dtype=self.np.uint8)
        for bad in (self.np.zeros((128, 128, 3), dtype=self.np.uint8), good.astype(float), None):
            with self.assertRaises(ProtocolError):
                adapter.policy_observation({"agentview_image": good, "robot0_eye_in_hand_image": bad}, 0, "move")

    def test_native_reset_retains_virtual_view_name_and_ten_settle_controls(self):
        benchmark = make(task_ids=[608])
        episode = benchmark.episodes(7)[0]
        session = benchmark.open_episode(episode)
        row = benchmark.catalog["tasks"][608]
        np = self.np
        actions, constructors = [], []
        raw = {camera + "_image": np.zeros((256, 256, 3), dtype=np.uint8) for camera in adapter.CAMERAS}
        task = SimpleNamespace(name=row["native_name"], language=row["native_instruction"],
            problem_folder=benchmark.suite, bddl_file=row["native_name"] + ".bddl",
            init_states_file=row["native_name"] + ".pruned_init")
        suite = SimpleNamespace(n_tasks=2402, get_task=lambda _: task,
                                get_task_init_states=lambda _: np.zeros((50, 10)))
        lib = ModuleType("libero.libero")
        lib.benchmark = SimpleNamespace(get_benchmark_dict=lambda: {"libero_spatial": lambda **kwargs: suite})
        envs = ModuleType("libero.libero.envs")
        robosuite = ModuleType("robosuite")
        robosuite.__file__ = "/pinned/robosuite/__init__.py"
        robosuite.load_controller_config = lambda **_: {"input_min": -1, "input_max": 1,
            "output_max": [0.05, 0.05, 0.05, 0.5, 0.5, 0.5],
            "output_min": [-0.05, -0.05, -0.05, -0.5, -0.5, -0.5], "control_delta": True}

        class Native:
            def __init__(self, **kwargs):
                constructors.append(kwargs)
                self.env = SimpleNamespace(action_spec=(np.full(7, -1.0), np.full(7, 1.0)))
            def seed(self, seed):
                self.seed_value = seed
            def reset(self):
                return raw
            def set_init_state(self, state):
                return raw
            def step(self, action):
                actions.append(action)
                return raw, 0, False, {}
            def close(self):
                pass

        envs.OffScreenRenderEnv = Native
        with ExitStack() as stack:
            stack.enter_context(patch.dict(sys.modules, {"libero": ModuleType("libero"), "libero.libero": lib,
                                                         "libero.libero.envs": envs, "robosuite": robosuite}))
            stack.enter_context(patch.object(adapter, "prepare_native_import", return_value={}))
            stack.enter_context(patch.object(adapter, "selected_asset_receipt", return_value={}))
            stack.enter_context(patch.object(adapter, "image_magick_receipt", return_value={}))
            stack.enter_context(patch.object(adapter.importlib.metadata, "version", return_value="fixture"))
            stack.enter_context(patch.object(adapter, "file_sha256", side_effect=lambda path: row["initial_file_sha256"]
                if str(path).endswith("pruned_init") else row["bddl_sha256"]))
            observation = session.reset()
        self.assertIn("_view_0_0_100_2_352_initstate_0.bddl", constructors[0]["bddl_file_name"])
        self.assertEqual(constructors[0]["camera_heights"], 256)
        self.assertEqual(constructors[0]["camera_names"], list(adapter.CAMERAS))
        self.assertEqual(actions, [[0.0] * 6 + [-1.0]] * 10)
        self.assertEqual(observation.step, 0)
        self.assertEqual(session.metrics()["native_steps"], 0)
        self.assertTrue(session.initialized)
        with self.assertRaises(ProtocolError):
            session.reset()


if __name__ == "__main__":
    unittest.main()
