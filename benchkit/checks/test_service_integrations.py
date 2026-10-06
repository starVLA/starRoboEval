"""Shared registration/capture checks; these never create a native simulator."""
from pathlib import Path
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from benchkit.registry import create_benchmark
from benchkit.sim_server.server import BenchmarkService
from benchkit.source_snapshot import capture_harness_source, repository_source_files, MAX_FILES


class StandaloneServices(unittest.TestCase):
    def test_packaging_data_keys_are_valid_module_names_including_hyphenated_services(self):
        configuration = (Path(__file__).resolve().parents[2] / "pyproject.toml").read_text()
        block = configuration.split("[tool.setuptools.package-data]", 1)[1].split("\n[", 1)[0]
        keys = re.findall(r'^"([^"\n]+)"\s*=', block, flags=re.MULTILINE)
        self.assertIn("benchmarks.simBenchmarks", keys)
        for key in keys:
            self.assertTrue(key == "*" or all(part.isidentifier() for part in key.split(".")), key)
        for path in ("LIBERO-plus/environment/native_source_manifest.json", "LIBERO-plus/bench_server/protocol/catalogs/*.json",
                     "VLA-Arena/bench_server/protocol/task_catalog.json", "VLA-Arena/environment/native_source_pin.json",
                     "VLA-Arena/environment/robosuite_pin.json"):
            self.assertIn('"' + path + '"', block)

    def test_source_capture_excludes_private_diagnostic_outputs_before_recursion(self):
        source = Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory() as directory:
            root, output = Path(directory) / "repository", Path(directory) / "run"
            output.mkdir()
            for path, _ in repository_source_files(source, MAX_FILES):
                target = root / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            for name in ("artifacts", "results", "rollouts", "_local"):
                generated = root / "benchkit/diagnostics" / name / "old-run"
                generated.mkdir(parents=True)
                (generated / "observation_payload.json").write_text('{"private_observation": true}')
                (generated / "frozen_runtime.py").write_text("import private_simulator\n")
                (generated / "outside").symlink_to(Path(directory) / "not-source", target_is_directory=True)
            with patch("benchkit.source_snapshot.installed_source_root", return_value=root / "benchkit"):
                capture_harness_source(output)
            index = json.loads((output / "harness_source/index.json").read_text())
            names = {row["path"] for row in index["files"]}
            self.assertTrue(any(name.startswith("benchkit/diagnostics/") for name in names))
            self.assertFalse(any(set(Path(name).parts) & {"artifacts", "results", "rollouts", "_local"} for name in names))

    def test_registry_and_schedule_do_not_import_native_or_model_packages(self):
        code = """
import sys
from benchkit.registry import create_benchmark, registered
assert {'metaworld', 'libero_plus', 'robotwin', 'domino', 'behavior', 'vla_arena', 'calvin'} <= set(registered()['benchmarks'])
create_benchmark('metaworld', {'task_names': ['reach-v3']}).episodes(4042)
create_benchmark('libero_plus', {'upstream': '/unused/native'}).episodes(7)
create_benchmark('robotwin', {'source_root': '/unused/native',
                            'deployment_manifest_sha256': '0' * 64}).episodes(7)
create_benchmark('robotwin', {'source_root': '/unused/native',
                            'deployment_manifest_sha256': '0' * 64,
                            'renderer_runtime': 'oidn_2_3_3_cuda_v1'}).episodes(7)
create_benchmark('domino', {'source_root': '/unused/native',
                          'deployment_manifest_sha256': '0' * 64,
                          'episode_manifest': '/unused/private/fixed.pkl',
                          'episode_manifest_sha256': '1' * 64}).episodes(7)
create_benchmark('behavior', {'deployment_manifest': '/unused/private/deployment.json',
                            'deployment_manifest_sha256': '0' * 64,
                            'worker_python': '/unused/python'}).episodes(7)
create_benchmark('vla_arena', {'native_root': '/unused/native'}).episodes(7)
create_benchmark('calvin', {'source_root': '/unused/native',
                          'dataset_root': '/unused/assets'}).episodes(7)
create_benchmark('robocasa365', {'render_track': 'egl-owner-restore-v1'}).episodes(20260907, 1)
create_benchmark('robocasa365', {'render_track': 'egl-owner-material-clamp-v1'}).episodes(20260907, 1)
assert not ({'metaworld', 'mujoco', 'gymnasium', 'torch', 'numpy', 'robosuite',
             'libero', 'sapien', 'mplib', 'curobo', 'openai', 'anthropic',
             'vla_arena', 'calvin_env', 'pybullet', 'calvin_agent', 'omnigibson', 'gello'} & set(sys.modules))
"""
        subprocess.run([sys.executable, '-B', '-c', code], check=True)

    def test_standalone_services_are_not_fabricated_full_campaigns(self):
        from benchkit.campaigns.benchmark_plans import get_plan
        for name in ('metaworld', 'libero_plus', 'robotwin', 'domino', 'behavior', 'vla_arena', 'calvin'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                get_plan(name)

    def test_source_capture_includes_native_service_helpers_not_model_results(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            capture_harness_source(Path(directory))
            index = json.loads((Path(directory) / 'harness_source/index.json').read_text())
            names = {row['path'] for row in index['files']}
        required = {
            'Robocasa_365/environment/render_lifecycle.py',
            'MetaWorld/bench_server/adapter.py', 'MetaWorld/server.py', 'MetaWorld/bench_server/protocol/task_catalog.json',
            'MetaWorld/environment/runtime.py', 'MetaWorld/environment/package_pin.json',
            'LIBERO-plus/bench_server/adapter.py', 'LIBERO-plus/server.py', 'LIBERO-plus/bench_server/protocol/catalog.py',
            'LIBERO-plus/environment/native_source_manifest.json',
            *('LIBERO-plus/bench_server/protocol/catalogs/' + name + '.json' for name in
              ('libero_spatial', 'libero_object', 'libero_goal', 'libero_10')),
            'Robotwin/bench_server/adapter.py', 'Robotwin/server.py', 'Robotwin/environment/runtime.py',
            'Robotwin/environment/deployment.py', 'Robotwin/environment/native_snapshot.json',
            'Robotwin/environment/runtime_snapshot.json',
            'Robotwin/environment/oidn_compat.py', 'Robotwin/environment/oidn_2_3_3_snapshot.json',
            'DOMINO/__init__.py', 'DOMINO/server.py', 'DOMINO/bench_server/__init__.py',
            'DOMINO/bench_server/adapter.py', 'DOMINO/bench_server/protocol/__init__.py',
            'DOMINO/environment/__init__.py', 'DOMINO/environment/runtime.py',
            'DOMINO/environment/deployment.py', 'DOMINO/environment/native_outcome.py',
            'Behavior/__init__.py', 'Behavior/server.py', 'Behavior/bench_server/__init__.py',
            'Behavior/bench_server/adapter.py', 'Behavior/bench_server/native_worker_client.py',
            'Behavior/bench_server/protocol/__init__.py', 'Behavior/environment/__init__.py',
            'Behavior/environment/deployment.py', 'Behavior/environment/native_bridge.py',
            'Behavior/environment/native_worker.py',
            'VLA-Arena/bench_server/adapter.py', 'VLA-Arena/server.py', 'VLA-Arena/bench_server/protocol/task_catalog.json',
            'VLA-Arena/environment/native_source_pin.json', 'VLA-Arena/environment/runtime.py',
            'VLA-Arena/environment/configure.py', 'VLA-Arena/environment/robosuite_pin.json',
            'calvin/bench_server/adapter.py', 'calvin/server.py', 'calvin/environment/runtime.py',
            'calvin/bench_server/protocol/frozen_sequence.json', 'calvin/environment/runtime_snapshot.json',
            'calvin/environment/requirements-rgb-setup.txt',
        }
        self.assertTrue({'benchmarks/simBenchmarks/' + name for name in required} <= names)
        self.assertEqual({name for name in names if name.startswith('AgentPolicies/')},
                         {'AgentPolicies/policy_support/runner.py', 'AgentPolicies/gpt6_astra/run.py'})
        self.assertFalse(any('/checks/' in name or '/legacy/' in name
                             or '/results/' in name for name in names))

    def test_metaworld_service_description_and_claim_are_lazy(self):
        adapter = create_benchmark('metaworld', {'task_names': ['reach-v3']})
        with tempfile.TemporaryDirectory() as directory:
            service = BenchmarkService(adapter, root=Path(directory) / 'server', seed=4042)
            description = service.dispatch('describe', {})
            self.assertEqual(description['observation_spec']['modalities'], ['language', 'rgb'])
            self.assertEqual(description['action_spec']['size'], 4)
            sid = service.dispatch('open', {'episode_id': service.episodes[0].id})['session_id']
            native = service.sessions[sid]['native']
            self.assertIsNone(native.env)
            self.assertFalse(native.reset_attempted)
            service.close()

    def test_plus_service_hides_native_variant_from_public_task_label(self):
        adapter = create_benchmark('libero_plus', {'upstream': '/unused/native'})
        with tempfile.TemporaryDirectory() as directory:
            service = BenchmarkService(adapter, root=Path(directory) / 'server', seed=7)
            episode = service.episodes[0]
            self.assertEqual(episode.task, 'libero_spatial/task-0')
            self.assertNotEqual(episode.task, episode.metadata['native_name'])
            description = service.dispatch('describe', {})
            self.assertEqual(description['observation_spec']['state_names'], [])
            self.assertEqual(description['budget']['environment_step_cap'], 220)
            sid = service.dispatch('open', {'episode_id': episode.id})['session_id']
            self.assertIsNone(service.sessions[sid]['native'].env)
            service.close()

    def test_robotwin_service_contract_does_not_expose_a_planner(self):
        adapter = create_benchmark('robotwin', {'source_root': '/unused/native',
                                              'deployment_manifest_sha256': '0' * 64})
        with tempfile.TemporaryDirectory() as directory:
            service = BenchmarkService(adapter, root=Path(directory) / 'server', seed=7)
            description = service.dispatch('describe', {})
            self.assertEqual(description['action_spec']['mode'], 'robotwin_aloha_absolute_joint_targets')
            self.assertEqual(description['action_spec']['size'], 14)
            self.assertIsNone(description['action_spec']['control_hz'])
            self.assertEqual(description['observation_spec']['state_names'], [
                *(f'measured_fl_joint{i}_rad' for i in range(1, 7)), 'commanded_left_gripper_01',
                *(f'measured_fr_joint{i}_rad' for i in range(1, 7)), 'commanded_right_gripper_01',
            ])
            self.assertEqual(description['observation_spec']['modalities'],
                             ['language', 'rgb', 'joint_position', 'gripper_command'])
            self.assertFalse(description['observation_spec']['privileged'])
            self.assertEqual(description['descriptor']['protocol_version'],
                             'robotwin-local-content/clean-fixed-seed/qpos14-rgb320-state14/fast-v3')
            sid = service.dispatch('open', {'episode_id': service.episodes[0].id})['session_id']
            self.assertIsNone(service.sessions[sid]['native'].env)
            self.assertFalse(service.sessions[sid]['native'].reset_attempted)
            service.close()

    def test_robotwin_declared_state_roundtrips_into_native_model_request_without_inference(self):
        try:
            import numpy as np
            from PIL import Image
        except ImportError:
            self.skipTest('optional NumPy/Pillow required for public image encoding')
        from benchkit.contracts import EpisodeContext, PolicyEpisodeSpec
        from benchkit.model_profiles import create_policy
        from benchkit.sim_server.wire import encode_observation, decode_observation, WireError
        from benchmarks.simBenchmarks.Robotwin.bench_server.adapter import policy_observation

        benchmark = create_benchmark('robotwin', {'source_root': '/unused/native',
                                                'deployment_manifest_sha256': '0' * 64})
        state = (0.1, -0.2, 0.3, -0.4, 0.5, -0.6, 0.25,
                 -0.7, 0.8, -0.9, 1.0, -1.1, 1.2, 0.75)
        raw = {'observation': {camera: {'rgb': np.full((240, 320, 3), index, dtype=np.uint8),
                                       'intrinsics': 'private-camera-calibration-marker'}
                               for index, camera in enumerate(benchmark.observation_spec.cameras)},
               'joint_action': {'vector': [42.0] * 14}, 'endpose': 'private-endpose-marker',
               'object_pose': 'private-object-marker', 'success': True, 'seed': 123}
        original = policy_observation(raw, 0, 'generic instruction', state)
        encoded = encode_observation(original, benchmark.observation_spec)
        observed = decode_observation(encoded, benchmark.observation_spec)
        self.assertEqual(tuple(observed.state), state)
        self.assertEqual(observed.metadata, {})
        for camera in benchmark.observation_spec.cameras:
            self.assertTrue(np.array_equal(observed.images[camera], original.images[camera]))
        for invalid in (None, list(state[:-1]), [True] + list(state[1:]),
                        [float('nan')] + list(state[1:])):
            with self.subTest(invalid=invalid), self.assertRaises(WireError):
                decode_observation({**encoded, 'state': invalid}, benchmark.observation_spec)

        policy = create_policy('gpt6_astra', control_method='codex-native/v1')
        policy.start_episode(EpisodeContext(
            benchmark=benchmark.descriptor,
            episode=PolicyEpisodeSpec('opaque', 'private-task-label', 'generic instruction'),
            observation_spec=benchmark.observation_spec, action_spec=benchmark.action_spec,
            max_steps=400, max_policy_calls=400, replan_interval=5))
        try:
            with patch('AgentPolicies.gpt6_astra.transports.codex_cli.send',
                       side_effect=AssertionError('no backend call allowed')) as send:
                public, images = policy._request(observed)
                send.assert_not_called()
            self.assertEqual(public['state'], list(state))
            self.assertEqual(public['state_names'], list(benchmark.observation_spec.state_names))
            self.assertEqual(public['action_spec']['size'], 14)
            from PIL import Image
            import io
            self.assertEqual(len(images), len(benchmark.observation_spec.cameras))
            for camera, payload in zip(benchmark.observation_spec.cameras, images):
                with Image.open(io.BytesIO(payload)) as decoded:
                    self.assertTrue(np.array_equal(np.asarray(decoded), observed.images[camera]))
            for marker in ('private-camera-calibration-marker', 'private-endpose-marker',
                           'private-object-marker', 'private-task-label', 'joint_action'):
                self.assertNotIn(marker, json.dumps(public))
        finally:
            policy.end_episode()

    def test_domino_service_is_lazy_and_declares_commanded_not_measured_state(self):
        adapter = create_benchmark('domino', {
            'source_root': '/unused/native', 'deployment_manifest_sha256': '0' * 64,
            'episode_manifest': '/unused/private/fixed.pkl', 'episode_manifest_sha256': '1' * 64})
        with tempfile.TemporaryDirectory() as directory:
            service = BenchmarkService(adapter, root=Path(directory) / 'server', seed=7)
            description = service.dispatch('describe', {})
            self.assertEqual(description['action_spec']['size'], 14)
            self.assertIsNone(description['action_spec']['control_hz'])
            self.assertEqual(description['budget']['environment_step_cap'], 400)
            self.assertEqual(description['budget']['required_replan_interval'], 1)
            self.assertTrue(all(name.startswith('commanded_target_')
                                for name in description['observation_spec']['state_names']))
            self.assertEqual(len(description['observation_spec']['state_names']), 14)
            sid = service.dispatch('open', {'episode_id': service.episodes[0].id})['session_id']
            native = service.sessions[sid]['native']
            self.assertIsNone(native.env)
            self.assertFalse(native.reset_attempted)
            service.close()

    def test_behavior_description_is_lazy_and_keeps_native_task_budget(self):
        adapter = create_benchmark('behavior', {
            'deployment_manifest': '/unused/private/deployment.json',
            'deployment_manifest_sha256': '0' * 64, 'worker_python': '/unused/python'})
        with tempfile.TemporaryDirectory() as directory:
            service = BenchmarkService(adapter, root=Path(directory) / 'server', seed=7)
            description = service.dispatch('describe', {})
            self.assertEqual(description['action_spec']['size'], 23)
            self.assertEqual(description['action_spec']['control_hz'], 30.0)
            self.assertEqual(len(description['observation_spec']['state_names']), 61)
            self.assertEqual(description['observation_spec']['cameras'],
                             ['head', 'left_wrist', 'right_wrist'])
            self.assertEqual(description['budget']['environment_step_cap'], 3224)
            self.assertEqual(description['budget']['required_replan_interval'], 1)
            self.assertIsNone(description['budget']['max_policy_calls'])
            self.assertEqual(len(service.episodes), 1)
            self.assertEqual(service.episodes[0].task, 'turning_on_radio')
            service.close()

    def test_vla_arena_service_projects_rgb_and_physical_actions_only(self):
        adapter = create_benchmark('vla_arena', {'native_root': '/unused/native'})
        with tempfile.TemporaryDirectory() as directory:
            service = BenchmarkService(adapter, root=Path(directory) / 'server', seed=7)
            description = service.dispatch('describe', {})
            self.assertEqual(description['action_spec']['size'], 7)
            self.assertEqual(description['observation_spec']['state_names'], [])
            self.assertEqual(description['observation_spec']['cameras'], ['agentview', 'robot0_eye_in_hand'])
            sid = service.dispatch('open', {'episode_id': service.episodes[0].id})['session_id']
            self.assertIsNone(service.sessions[sid]['native'].env)
            service.close()

    def test_calvin_service_declares_observation_prefix_not_a_model_call_quota(self):
        adapter = create_benchmark('calvin', {'source_root': '/unused/native', 'dataset_root': '/unused/assets'})
        with tempfile.TemporaryDirectory() as directory:
            service = BenchmarkService(adapter, root=Path(directory) / 'server', seed=7)
            description = service.dispatch('describe', {})
            self.assertEqual(description['budget']['required_replan_interval'], 1)
            self.assertIsNone(description['budget']['max_policy_calls'])
            self.assertEqual(description['action_spec']['size'], 7)
            self.assertEqual(description['observation_spec']['state_names'], [])
            sid = service.dispatch('open', {'episode_id': service.episodes[0].id})['session_id']
            self.assertIsNone(service.sessions[sid]['native'].native)
            service.close()


if __name__ == '__main__':
    unittest.main()
