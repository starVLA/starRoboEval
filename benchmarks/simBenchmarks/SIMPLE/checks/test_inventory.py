"""Dependency-free checks for the explicit released-task scope and frozen pins."""
import ast
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from benchmarks.simBenchmarks.SIMPLE.bench_server.adapter import (
    ACTION_NAMES, FULL_TASKS, HORIZONS, INVENTORY_PATH, INVENTORY_SHA256,
    SEED, TASKS, TASK_CONFIGS, SimpleHumanoidBenchmarkAdapter, task_config,
)
from benchkit.errors import CompatibilityError


class ReleasedInventoryTests(unittest.TestCase):
    def test_actual_worker_constructor_branch_preserves_task_inventory_binding(self):
        # Execute the real bounded constructor/identity-check branch with fake
        # modules. No native initialization or reset occurs. A SimLoopConfig is
        # deliberately not a mapping: shadowing task config with it must fail.
        worker = Path(__file__).parents[1] / "environment/native_worker.py"
        tree = ast.parse(worker.read_text())
        reset = next(n for cls in tree.body if isinstance(cls, ast.ClassDef)
                     for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "reset")
        start = next(i for i, n in enumerate(reset.body) if isinstance(n, ast.Assign)
                     and any(isinstance(t, ast.Name) and t.id == "kwargs" for t in n.targets))
        end = next(i for i, n in enumerate(reset.body[start:], start) if isinstance(n, ast.If)
                   and ast.unparse(n.test) == "self.backend == 'amo'")
        branch = compile(ast.Module(body=reset.body[start:end], type_ignores=[]), str(worker), "exec")
        fake_loop = SimpleNamespace(load_wbc_yaml=lambda: {})
        fake_tyro = SimpleNamespace(cli=lambda *a, **kw: fake_loop,
                                   conf=SimpleNamespace(ConsolidateSubcommandArgs=object()))
        fake_configs = SimpleNamespace(SimLoopConfig=object())
        for task, inventory_config in TASK_CONFIGS.items():
            with self.subTest(task=task):
                module, name = inventory_config["env_entry_point"].split(":")
                raw = type(name, (), {"__module__": module})()
                raw.task = SimpleNamespace(uid=inventory_config["task_uid"],
                    robot_cfg={"uid": inventory_config["robot_uid"]},
                    metadata={"max_episode_steps": inventory_config["reference_native_horizon"]})
                made = []
                def fake_make(env_id, **kwargs):
                    made.append((env_id, kwargs))
                    return SimpleNamespace(unwrapped=raw)
                original_config = dict(inventory_config)
                state = {"self": SimpleNamespace(backend=inventory_config["backend"],
                    task_id=task, horizon=inventory_config["reference_native_horizon"]),
                    "config": original_config, "gym": SimpleNamespace(make=fake_make)}
                with patch.dict(sys.modules, {"tyro": fake_tyro,
                    "gear_sonic.utils.mujoco_sim.configs": fake_configs}):
                    exec(branch, state)
                self.assertIs(state["config"], original_config)
                self.assertEqual(state["config"]["instruction"], inventory_config["instruction"])
                self.assertEqual(len(made), 1)
                self.assertEqual(made[0][0], "simple/" + task)
                self.assertEqual(made[0][1]["render_hz"], 50)
                if inventory_config["backend"] == "sonic":
                    self.assertIs(state["sim_loop_config"], fake_loop)
                    self.assertEqual(made[0][1]["sonic_config"], {"ENV_NAME": "simple"})
                else:
                    self.assertNotIn("sonic_config", made[0][1])

    def test_all_twelve_exact_native_identities_and_horizons(self):
        expected = {
            "G1WholebodyBendPickMP-v0": ("amo", 400),
            "G1WholebodyCloseDoorTeleop-v0": ("sonic", 1000),
            "G1WholebodyHandoverTeleop-v0": ("sonic", 800),
            "G1WholebodyLocomotionPickBetweenTablesTeleop-v0": ("sonic", 1200),
            "G1WholebodyOpenFaucetTeleop-v0": ("sonic", 1000),
            "G1WholebodyOpenOvenTeleop-v0": ("sonic", 1000),
            "G1WholebodyOpenTrashCanTeleop-v0": ("sonic", 800),
            "G1WholebodyPickAndPlaceAndHugContainerTeleop-v0": ("sonic", 1000),
            "G1WholebodyPushOfficeChairTeleop-v0": ("sonic", 800),
            "G1WholebodyTabletopGraspMP-v0": ("amo", 800),
            "G1WholebodyXMoveBendPickTeleop-v0": ("sonic", 800),
            "G1WholebodyXMovePickTeleop-v0": ("sonic", 800),
        }
        self.assertEqual(FULL_TASKS, tuple(expected))
        for task, (backend, horizon) in expected.items():
            with self.subTest(task=task):
                config = task_config(task, "released-12")
                adapter = SimpleHumanoidBenchmarkAdapter(task_names=[task], task_scope="released-12")
                episode, = adapter.episodes()
                self.assertEqual((adapter.backend, adapter.native_horizon), (backend, horizon))
                self.assertEqual(HORIZONS[task], config["native_metadata"]["max_episode_steps"])
                self.assertEqual(config["native_source"], f"src/simple/tasks/{config['task_uid']}.py")
                self.assertEqual(config["robot_uid"], "g1_wholebody" if backend == "amo" else "g1_sonic")
                self.assertEqual(config["env_entry_point"], "simple.envs.loco_manipulation:LocoManipulationEnv"
                    if backend == "amo" else "simple.envs.sonic_loco_manip:SonicLocoManipEnv")
                self.assertEqual(adapter.environment_step_cap, 1000)
                self.assertEqual((adapter.max_policy_calls, adapter.replan_interval), (200, 5))
                self.assertEqual(adapter.observation_spec.state_names, ACTION_NAMES[:31])
                self.assertEqual(adapter.action_spec.names[34], "turning_flag" if backend == "amo" else "turning_gate")
                self.assertEqual(adapter.descriptor.protocol_version,
                    f"simple/released-12/{backend}/rgb-qpos31/decision-200-prefix-5/v2")
                self.assertEqual((episode.id, episode.seed), (f"{task}/dr0/ep0", SEED))
                self.assertEqual(episode.instruction, config["instruction"].strip())
                self.assertEqual(episode.metadata["task_inventory_sha256"], INVENTORY_SHA256)
                self.assertEqual((config["dr_level"], config["episode_index"], config["released_episode_count"]), (0, 0, 10))
                # Retry ownership belongs to campaign history, not this reusable adapter.
                adapter.open_episode(episode).close()

    def test_legacy_defaults_and_pilot_episode_metadata_are_unchanged(self):
        self.assertEqual(TASKS, ("G1WholebodyBendPickMP-v0", "G1WholebodyOpenFaucetTeleop-v0"))
        self.assertEqual(SimpleHumanoidBenchmarkAdapter().task_names, (TASKS[0],))
        for task, backend, instruction in zip(TASKS, ("amo", "sonic"),
            ("bend to pick up the cracker box", "move forward to the faucet and open it")):
            adapter = SimpleHumanoidBenchmarkAdapter(task_names=(task,))
            protocol = f"simple/{backend}/rgb-qpos31/decision-200-prefix-5/v2"
            episode, = adapter.episodes()
            self.assertEqual(adapter.descriptor.protocol_version, protocol)
            self.assertEqual(episode.instruction, instruction)
            self.assertEqual(episode.metadata, {"dr_level": 0, "episode_index": 0,
                "reference_native_horizon": HORIZONS[task], "environment_step_cap": 1000,
                "budget_mode": "decisions", "track": protocol})

    def test_invalid_scope_unknown_task_and_unfrozen_tracks_rejected(self):
        for args in ({"task_scope": "all"}, {"task_scope": None}, {"task_scope": True},
            {"task_names": ["unknown"], "task_scope": "released-12"},
            {"task_names": [FULL_TASKS[-1]]}, {"task_names": FULL_TASKS, "task_scope": "released-12"},
            {"task_scope": "released-12", "proprioception": False},
            {"task_scope": "released-12", "budget_mode": "horizon"}):
            with self.subTest(args=args), self.assertRaises(ValueError):
                SimpleHumanoidBenchmarkAdapter(**args)
        with patch.dict(TASK_CONFIGS[FULL_TASKS[-1]], backend="unsupported", backend_gate="native backend gate"):
            with self.assertRaises(CompatibilityError):
                SimpleHumanoidBenchmarkAdapter(task_names=[FULL_TASKS[-1]], task_scope="released-12")
            self.assertEqual(len(FULL_TASKS), 12)

    def test_inventory_and_all_reset_hashes_are_pinned(self):
        pins = json.loads((Path(__file__).parents[1] / "environment/upstream.json").read_text())
        self.assertEqual(INVENTORY_SHA256, pins["released_task_inventory_sha256"])
        self.assertEqual(INVENTORY_SHA256, hashlib.sha256(INVENTORY_PATH.read_bytes()).hexdigest())
        self.assertEqual(set(pins["reset_metadata_sha256"]), set(FULL_TASKS))
        for task, config in TASK_CONFIGS.items():
            self.assertEqual(pins["reset_metadata_sha256"][task], config["reset_metadata_sha256"])
            for name in ("native_source_sha256", "reset_metadata_sha256", "environment_config_sha256"):
                self.assertEqual(len(bytes.fromhex(config[name])), 32)
        # Native source horizons remain authoritative when released metadata omits them.
        for task in ("G1WholebodyPickAndPlaceAndHugContainerTeleop-v0", "G1WholebodyXMoveBendPickTeleop-v0"):
            self.assertNotIn("max_episode_steps", TASK_CONFIGS[task]["released_metadata"])
        tabletop = TASK_CONFIGS["G1WholebodyTabletopGraspMP-v0"]
        self.assertEqual((tabletop["native_metadata"]["render_hz"], tabletop["released_metadata"]["render_hz"]), (30, 50))

    def test_no_native_import_or_scoring_in_inventory_or_worker_audit(self):
        subprocess.run([sys.executable, "-c", "import sys; import benchmarks.simBenchmarks.SIMPLE.bench_server.adapter; "
            "assert not any(x in sys.modules for x in ('numpy','torch','simple','mujoco','isaacsim'))"], check=True)
        for path in (Path(__file__).with_name("verify_inventory.py"),
            Path(__file__).parents[1] / "environment/native_worker.py"):
            tree = ast.parse(path.read_text())
            calls = [n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
            self.assertNotIn("compute_reward", calls)
            self.assertNotIn("check_success", calls)


if __name__ == "__main__":
    unittest.main()
