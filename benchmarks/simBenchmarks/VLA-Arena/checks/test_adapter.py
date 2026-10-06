"""Contract and fake-native regressions; no simulator construction or controls."""
import importlib
import base64
import json
import os
from dataclasses import replace
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from benchkit.errors import CompatibilityError, ProtocolError

module = importlib.import_module("benchmarks.simBenchmarks.VLA-Arena.bench_server.adapter")
runtime = importlib.import_module("benchmarks.simBenchmarks.VLA-Arena.environment.runtime")
configure = importlib.import_module("benchmarks.simBenchmarks.VLA-Arena.environment.configure")
try:
    import numpy as np
except ImportError:
    np = None


class ContractTests(unittest.TestCase):
    def test_lazy_import_schedule_open(self):
        code = """
import importlib,sys
a=importlib.import_module('benchmarks.simBenchmarks.VLA-Arena.bench_server.adapter').make_vla_arena({'native_root':'/absent'})
a.open_episode(a.episodes(7)[0])
assert not any(n in sys.modules for n in ('vla_arena','robosuite','mujoco','torch','numpy'))
"""
        subprocess.run([sys.executable, "-B", "-c", code], check=True)

    def test_verified_matrix_and_levels(self):
        rows = module.task_catalog()
        self.assertEqual(len(rows), 170)
        self.assertEqual(len({r["suite"] for r in rows}), 11)
        self.assertEqual([sum(r["level"] == i for r in rows) for i in range(3)], [60, 55, 55])
        self.assertTrue(next(r for r in rows if r["key"] == module.DEFAULT_TASK)["has_cost_clause"])

    def test_explicit_fast_schedule_and_claim(self):
        a = module.make_vla_arena({"native_root": "/absent"})
        e = a.episodes(7)[0]
        self.assertEqual(e.metadata["initial_state_index"], 0)
        self.assertEqual(e, a.episodes(7)[0])
        a.open_episode(e)
        for invalid in (e, replace(e, instruction="changed")):
            with self.assertRaises(ProtocolError):
                a.open_episode(invalid)

    def test_selector_rejects_full_higher_levels_unknown_and_duplicates(self):
        higher = next(r["key"] for r in module.task_catalog() if r["level"] == 1)
        for params in ({"evaluation_mode": "full"}, {"task_names": []}, {"task_names": higher},
                       {"task_names": [higher]}, {"task_names": [module.DEFAULT_TASK]*2},
                       {"task_names": [1]}, {"expert": True}):
            with self.subTest(params=params), self.assertRaises(ValueError):
                module.make_vla_arena({"native_root": "/absent", **params})

    def test_seed_and_limit(self):
        a = module.make_vla_arena({"native_root": "/absent"})
        for seed in (-1, 2**32, True, "7", 0.5):
            with self.assertRaises(ValueError):
                a.episodes(seed)
        for limit in (0, -1, False, 0.5):
            with self.assertRaises(ValueError):
                a.episodes(7, limit)

    def test_action_contract(self):
        spec = module.make_vla_arena({"native_root": "/absent"}).action_spec
        self.assertEqual(spec.validate([1, -1, 0, 0.2, -0.3, 0.4, -1]), (1., -1., 0., 0.2, -0.3, 0.4, -1.))
        self.assertEqual(spec.control_hz, 20)
        for action in ([0]*6, [0]*6 + [2], [True]+[0]*6, [float("nan")]+[0]*6,
                       [float("inf")]+[0]*6, ["0"]+[0]*6):
            with self.assertRaises((ValueError, TypeError)):
                spec.validate(action)

    def test_inventory_rejects_symlinks_and_detects_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            file = root / "code.py"
            file.write_text("first")
            first = runtime.inventory(root, root.rglob("*"))
            file.write_text("changed")
            self.assertNotEqual(first, runtime.inventory(root, root.rglob("*")))
            (root / "link").symlink_to(file)
            with self.assertRaises(CompatibilityError):
                runtime.inventory(root, root.rglob("*"))

    def test_inventory_canonical_order_ignores_path_iteration_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "a").mkdir()
            paths = [root / "a/file.py", root / "a.py"]
            for path in paths: path.write_text("code")
            self.assertEqual(runtime.inventory(root, paths), runtime.inventory(root, paths[::-1]))

    def test_native_bytecode_rejected_installed_cache_scope_narrow(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "source.py").write_text("code")
            (root / "__pycache__").mkdir()
            cache = root / "__pycache__/source.cpython-311.pyc"
            cache.write_bytes(b"installation cache")
            with self.assertRaises(CompatibilityError):
                runtime.inventory(root, root.rglob("*"))
            self.assertEqual(runtime.inventory(root, root.rglob("*"), installed_bytecode=True)["files"], 1)
            (root / "shadow.pyc").write_bytes(b"executable shadow")
            with self.assertRaises(CompatibilityError):
                runtime.inventory(root, root.rglob("*"), installed_bytecode=True)

    def test_config_isolated_and_never_overwrites(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("assets", "bddl_files", "init_files"):
                (root / "native/vla_arena/vla_arena" / name).mkdir(parents=True)
            target = root / "private-config"
            config = configure.create_config(root / "native", target)
            self.assertEqual(json.loads(config.read_text())["init_states"],
                             str((root / "native/vla_arena/vla_arena/init_files").resolve()))
            before = config.read_bytes()
            with self.assertRaises(ValueError): configure.create_config(root / "native", target)
            self.assertEqual(config.read_bytes(), before)

    def test_closed_and_finalized_handles_reject_artifact_binding(self):
        adapter = module.make_vla_arena({"native_root": "/absent"})
        session = adapter.open_episode(adapter.episodes(7)[0])
        session.close()
        with self.assertRaises(ProtocolError): session.bind_artifact_dir(Path("must-not-be-created"))
        other = adapter.open_episode(adapter.episodes(8)[0])
        other.artifacts()
        with self.assertRaises(ProtocolError): other.bind_artifact_dir(Path("must-not-be-created"))

    def test_numba_cache_fresh_external_and_process_bound(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(runtime, "_PROCESS_NUMBA_CACHE", None):
            root = Path(directory).resolve()
            native, rs, cache, other = [root / name for name in ("native", "robosuite", "cache", "other")]
            for path in (native, rs, cache, other): path.mkdir()
            with patch.dict(os.environ, {"NUMBA_CACHE_DIR": str(native)}):
                with self.assertRaises(CompatibilityError): runtime.verify_numba_cache(native, rs)
            (cache / "unknown.nbc").write_bytes(b"not generated by this process")
            with patch.dict(os.environ, {"NUMBA_CACHE_DIR": str(cache)}):
                with self.assertRaises(CompatibilityError): runtime.verify_numba_cache(native, rs)
            with patch.dict(os.environ, {"NUMBA_CACHE_DIR": str(other)}):
                self.assertEqual(runtime.verify_numba_cache(native, rs), other)
                (other / "generated.nbc").write_bytes(b"own generated cache")
                self.assertEqual(runtime.verify_numba_cache(native, rs), other)
            with patch.dict(os.environ, {"NUMBA_CACHE_DIR": str(cache)}):
                with self.assertRaises(CompatibilityError): runtime.verify_numba_cache(native, rs)


class FakeEnv:
    def __init__(self):
        arm = SimpleNamespace(name="OSC_POSE", input_type="delta", input_ref_frame="base", impedance_mode="fixed",
                              control_dim=6, output_max=np.array([.05]*3+[.5]*3), output_min=np.array([-.05]*3+[-.5]*3))
        self.env = SimpleNamespace(timestep=0, action_dim=7, action_spec=(np.full(7,-1.),np.full(7,1.)),
                   horizon=1000, ignore_done=False, control_freq=20, model_timestep=.002, control_timestep=.05,
                   robots=[SimpleNamespace(part_controllers={"right":arm})],
                   sim=SimpleNamespace(data=SimpleNamespace(time=0.), model=SimpleNamespace(opt=SimpleNamespace(timestep=.002))))
        self.env.reset = self.inner_reset
        self.actions, self.reset_calls, self.state_calls, self.closes = [], 0, 0, 0
        self.success, self.timeout, self.cost = False, False, .1
        self.fail_reset = self.fail_close = self.bad_frame = False
        self.frame = np.zeros((256,256,3), dtype=np.uint8)
        self.frame[3,7] = [11,47,99]

    def inner_reset(self):
        self.reset_calls += 1
        if self.fail_reset:
            raise RuntimeError("native randomization failed")
        self.env.timestep = 0

    def reset(self):
        raise AssertionError("must not use native wrapper retry loop")

    def set_init_state(self, state):
        self.state_calls += 1
        self.env.sim.data.time = 27.0  # Native init time differs from logical control count.
        return self.raw()

    def raw(self):
        frame = np.zeros((224,224,3), dtype=np.uint8) if self.bad_frame else self.frame
        return {"agentview_image":frame,"robot0_eye_in_hand_image":frame,
                "robot0_eef_pos":[9,9,9],"object-state":[8,8,8],"secret_goal":[7,7,7]}

    def step(self, action):
        self.actions.append(list(action))
        self.env.timestep += 1
        self.env.sim.data.time += .05
        return self.raw(), 0., self.success or self.timeout, {"success":self.success,"timeout":self.timeout,"cost":self.cost}

    def close(self):
        self.closes += 1
        if self.fail_close:
            raise RuntimeError("close failed")


@unittest.skipIf(np is None, "NumPy needed for fake-native/RGB checks")
class NativeTests(unittest.TestCase):
    def setUp(self):
        self.adapter = module.make_vla_arena({"native_root":"/absent"})
        self.session = self.adapter.open_episode(self.adapter.episodes(7)[0])
        self.native = FakeEnv()
        for target, kwargs in [("prepare_runtime", {"return_value":{}}),
                  ("_create_native", {"return_value":(self.native,np.zeros(9),{"available_initial_states":10})})]:
            p = patch.object(module,target,**kwargs)
            p.start()
            self.addCleanup(p.stop)

    def test_reset_and_setup_counts_no_retry(self):
        obs = self.session.reset()
        self.assertEqual(self.native.reset_calls,1)
        self.assertEqual(self.native.state_calls,1)
        self.assertEqual(self.native.actions,[[0.]*6+[-1.]]*10)
        self.assertEqual(obs.step,0)
        self.assertIsNone(obs.state)
        self.assertEqual(obs.metadata,{})
        self.assertEqual(self.session.metrics()["native_steps"],0)
        self.assertEqual(self.session.metrics()["native_steps_including_settle"],10)
        self.assertAlmostEqual(self.session.metrics()["settle_cost_excluded_from_score"],1.)
        self.assertEqual(self.session.metrics()["native_cost"],0)
        with self.assertRaises(ProtocolError): self.session.reset()

    def test_both_cameras_rotated_without_state_or_aliasing(self):
        raw = self.native.raw()
        original = self.native.frame.copy()
        obs = module.policy_observation(raw,4,"task")
        self.assertEqual(set(obs.images),set(module.CAMERAS))
        for frame in obs.images.values():
            np.testing.assert_array_equal(frame,original[::-1,::-1])
            self.assertTrue(frame.flags.c_contiguous)
            self.assertFalse(np.shares_memory(frame,original))
        self.native.frame[:]=0
        self.assertEqual(obs.images["agentview"][-4,-8].tolist(),[11,47,99])
        obs.images["agentview"][:]=0
        self.assertEqual(obs.images["robot0_eye_in_hand"][-4,-8].tolist(),[11,47,99])

    def test_setup_error_not_retried_or_scored(self):
        self.native.fail_reset=True
        with self.assertRaises(RuntimeError): self.session.reset()
        self.assertEqual(self.native.reset_calls,1)
        self.assertEqual(self.native.closes,1)
        self.assertFalse(self.session.metrics()["success"])
        with self.assertRaises(ProtocolError): self.session.reset()

    def test_partial_constructor_is_unknown_cleanup_and_blocks_reuse(self):
        with patch.object(module, "_create_native", side_effect=RuntimeError("constructor failed")):
            with self.assertRaises(RuntimeError): self.session.reset()
        self.assertEqual(self.session.initialization_stage, "construction")
        self.assertIsNone(self.session.env)
        with self.assertRaises(ProtocolError): self.session.close()

    def test_constructor_fault_prevents_next_service_episode(self):
        from benchkit.sim_server.server import BenchmarkService, ServiceError
        other = next(r["key"] for r in module.task_catalog() if r["level"] == 0 and r["key"] != module.DEFAULT_TASK)
        adapter = module.make_vla_arena({"native_root": "/absent", "task_names": [module.DEFAULT_TASK, other]})
        with tempfile.TemporaryDirectory() as directory:
            service = BenchmarkService(adapter, root=Path(directory) / "server", seed=7)
            episodes = adapter.episodes(7)
            sid = service.dispatch("open", {"episode_id": episodes[0].id})["session_id"]
            with patch.object(module, "_create_native", side_effect=RuntimeError("constructor failed")):
                with self.assertRaises(ServiceError): service.dispatch("reset", {"session_id": sid, "sequence": 0})
            final = service.dispatch("finish", {"session_id": sid})
            self.assertEqual(final["cleanup_error"], "native_close_failed")
            self.assertEqual(service.active, sid)
            with self.assertRaises(ServiceError): service.dispatch("open", {"episode_id": episodes[1].id})
            service.close()

    def test_faulted_service_retains_private_metrics_and_native_clock(self):
        from benchkit.sim_server.server import BenchmarkService, ServiceError
        for reset_failure in (True, False):
            with self.subTest(reset_failure=reset_failure), tempfile.TemporaryDirectory() as directory:
                native = FakeEnv()
                native.fail_reset = reset_failure
                adapter = module.make_vla_arena({"native_root": "/absent"})
                service = BenchmarkService(adapter, root=Path(directory) / "server", seed=7)
                sid = service.dispatch("open", {"episode_id": adapter.episodes(7)[0].id})["session_id"]
                with patch.object(module, "_create_native", return_value=(native, np.zeros(9), {})), \
                     patch.object(module.VLAArenaEpisode, "_observe", lambda session, raw:
                                  module.policy_observation(raw, session.controls, session.episode.instruction)):
                    if reset_failure:
                        with self.assertRaises(ServiceError):
                            service.dispatch("reset", {"session_id": sid, "sequence": 0})
                    else:
                        service.dispatch("reset", {"session_id": sid, "sequence": 0})
                        def fail_step(action):
                            native.env.timestep += 1
                            raise RuntimeError("partial native control")
                        native.step = fail_step
                        with self.assertRaises(ServiceError):
                            service.dispatch("step", {"session_id": sid, "sequence": 1, "action": [0.]*7})
                    with self.assertRaises(ServiceError):
                        service.dispatch("metrics", {"session_id": sid})
                    final = service.dispatch("finish", {"session_id": sid})
                    self.assertIn("native_metrics.json", {row["path"] for row in final["files"]})
                    encoded = service.dispatch("read_artifact", {"session_id": sid,
                                               "path": "native_metrics.json", "offset": 0})
                    metrics = json.loads(base64.b64decode(encoded["data"]))
                    self.assertEqual(metrics["started_controls"], 0 if reset_failure else 1)
                    self.assertEqual(metrics["native_steps"], 0)
                    self.assertEqual(metrics["acknowledged_controls"], 0)
                    self.assertEqual(metrics["native_clock_at_cleanup"]["native_timestep"], 0 if reset_failure else 11)
                    self.assertIsNone(metrics["partial_physics_ticks_on_error"])
                    self.assertFalse(metrics["cost_complete"])
                    self.assertEqual(native.closes, 1)
                service.close()

    def test_setup_success_is_environment_error(self):
        self.native.success=True
        with self.assertRaises(ProtocolError): self.session.reset()
        self.assertEqual(self.session.settle_controls,1)
        self.assertEqual(self.session.controls,0)
        self.assertFalse(self.session.metrics()["success"])

    def test_invalid_action_never_native(self):
        self.session.reset()
        with self.assertRaises(ValueError): self.session.step((0,)*6+(2,))
        self.assertEqual(len(self.native.actions),10)

    def test_success_and_safe_success_are_separate(self):
        self.session.reset()
        self.native.success=True
        self.native.cost=11.
        transition=self.session.step((0,)*7)
        self.assertTrue(transition.terminated)
        self.assertFalse(transition.truncated)
        self.assertTrue(self.session.metrics()["native_success"])
        self.assertTrue(self.session.metrics()["success"])
        self.assertFalse(self.session.metrics()["native_evaluator_safety_flag"])
        self.assertFalse(self.session.metrics()["safe_success"])
        with self.assertRaises(ProtocolError): self.session.step((0,)*7)

    def test_native_timeout_is_not_success_and_not_double_final_cost(self):
        self.session.reset()
        self.native.timeout=True
        self.native.cost=10.
        transition=self.session.step((0,)*7)
        self.assertFalse(transition.terminated)
        self.assertTrue(transition.truncated)
        self.assertEqual(self.session.metrics()["native_cost"],10.)
        self.assertEqual(self.session.timeout_final_cost,0.)
        self.assertFalse(self.session.success)

    def test_cap_adds_exactly_one_native_final_cost(self):
        self.session.reset()
        self.native.cost=.2
        calls=[]
        helper=SimpleNamespace(get_timeout_final_cost=lambda env: calls.append(env) or 3.)
        with patch.object(module.importlib,"import_module",return_value=helper):
            for _ in range(300): transition=self.session.step((0,)*7)
        self.assertTrue(transition.truncated)
        self.assertEqual(calls,[self.native])
        self.assertEqual(len(self.native.actions),310)
        self.assertAlmostEqual(self.session.cost,63.)
        self.assertEqual(self.session.timeout_final_cost,3.)
        self.assertTrue(self.session.cost_complete)
        self.assertFalse(self.session.native_timeout)

    def test_early_close_cost_is_partial(self):
        self.session.reset()
        self.session.step((0,)*7)
        self.session.close()
        self.assertFalse(self.session.cost_complete)
        self.assertEqual(self.session.timeout_final_cost,0.)

    def test_non_safety_task_does_not_invent_safe_success(self):
        key = next(r["key"] for r in module.task_catalog() if r["level"] == 0 and not r["safety_suite"])
        adapter = module.make_vla_arena({"native_root": "/absent", "task_names": [key]})
        session = adapter.open_episode(adapter.episodes(7)[0])
        session.reset()
        self.native.success = True
        self.native.cost = 11.
        session.step((0,)*7)
        self.assertTrue(session.metrics()["success"])
        self.assertIsNone(session.metrics()["safe_success"])
        self.assertIsNone(session.metrics()["safety_cost_threshold"])

    def test_malformed_native_score_poisoned(self):
        self.session.reset()
        self.native.cost=float("nan")
        with self.assertRaises(ProtocolError): self.session.step((0,)*7)
        with self.assertRaises(ProtocolError): self.session.step((0,)*7)
        self.assertEqual(len(self.native.actions),11)

    def test_missing_inconsistent_and_invalid_score_fields(self):
        for done,info in [(True,{}),(True,{"success":False,"timeout":False,"cost":0}),
                         (True,{"success":True,"timeout":True,"cost":0}),
                         (False,{"success":False,"timeout":False,"cost":-1}),
                         (True,{"success":"true","timeout":False,"cost":0})]:
            with self.assertRaises(ProtocolError): module.native_outcome(done,info)

    def test_render_shape_error_not_replayed(self):
        self.session.reset()
        self.native.bad_frame=True
        with self.assertRaises(ProtocolError): self.session.step((0,)*7)
        with self.assertRaises(ProtocolError): self.session.step((0,)*7)

    def test_controller_drift_fails_before_explicit_reset(self):
        self.native.env.control_freq=10
        with self.assertRaises(CompatibilityError): self.session.reset()
        self.assertEqual(self.native.reset_calls,0)
        self.assertEqual(self.native.closes,1)

    def test_finalize_prevents_reset_and_controls(self):
        self.assertEqual(self.session.artifacts(),{})
        with self.assertRaises(ProtocolError): self.session.reset()

    def test_close_failure_remains_visible(self):
        self.session.reset()
        self.native.fail_close=True
        with self.assertRaises(ProtocolError): self.session.close()
        with self.assertRaises(ProtocolError): self.session.close()
        self.assertEqual(self.native.closes,1)


if __name__ == "__main__":
    unittest.main()
