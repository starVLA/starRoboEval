"""Prove output ignores without depending on an evaluation checkout's Git index.

Only a disposable repository is initialized. No native environment, evaluation,
user index, configured remote or existing output is touched.
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which("git"), "Git is needed to validate ignore syntax")
class RepositoryHygieneTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="rsi-ignore-regression-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        source = Path(__file__).resolve().parents[2] / ".gitignore"
        if not source.is_file():
            self.skipTest("repository ignore declaration is unavailable in this installation")
        shutil.copyfile(source, self.root / ".gitignore")
        # Inherited Git repository/config variables must not redirect this
        # isolated fixture toward the user's working tree or global excludes.
        self.env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        self.git = shutil.which("git")
        self._git("init", "--quiet")

    def _git(self, *arguments, input=None, expected=(0,)):
        result = subprocess.run(
            [self.git, "-C", str(self.root), "-c", "core.excludesFile=" + os.devnull,
             "-c", "init.defaultBranch=ignore-fixture", *arguments],
            input=input, text=True, capture_output=True, env=self.env, timeout=15,
        )
        self.assertIn(result.returncode, expected, result.stderr)
        return result.stdout

    def assert_ignore_set(self, paths, expected):
        ignored = self._git("check-ignore", "--stdin", input="\n".join(paths) + "\n", expected=(0, 1))
        self.assertEqual(set(ignored.splitlines()), set(expected))

    def test_private_workspaces_and_existing_run_outputs_are_ignored(self):
        paths = [
            "project_readmes/framework_design/index.html",
            "barks/archive/previous.bundle",
            "results/old-run/manifest.json",
            "benchkit/_local/checks/summary.json",
            "AgentPolicies/gpt6_astra/_local/debug.json",
            "public/mbx-fixture/request.json",
            "AgentPolicies/gpt6_astra/results/robodojo/raw/run/client/manifest.json",
            "AgentPolicies/gpt6_astra/results/libero/campaigns/run/campaign.json",
            "AgentPolicies/gpt6_astra/results/robodojo/media/run/camera.png",
            "AgentPolicies/my_method/results/my_benchmark/rollouts/run/frame.png",
        ]
        self.assert_ignore_set(paths, paths)

    def test_raw_client_transcripts_and_source_copies_are_scoped_to_results(self):
        runtime_names = ["events.jsonl", "agent_interactions.jsonl",
                         "frames/camera.png", "policy_artifacts/private.json",
                         "sim_server_files/private.json", "harness_source/files/module.py",
                         "model_source/files/prompt.txt"]
        generated = ["AgentPolicies/my_method/results/my_benchmark/run/" + name
                     for name in runtime_names]
        public = ["benchmarks/simBenchmarks/Example/bench_server/protocol/events.jsonl",
                  "benchkit/checks/fixtures/agent_interactions.jsonl",
                  "assets/frames/camera.png"]
        self.assert_ignore_set(generated + public, generated)

    def test_source_checks_protocol_data_and_published_views_remain_visible(self):
        paths = [
            "AgentPolicies/gpt6_astra/run.py",
            "AgentPolicies/gpt6_astra/methods/codex_direct.py",
            "AgentPolicies/gpt6_astra/transports/responses.py",
            "AgentPolicies/gpt6_astra/configs/config.json",
            "AgentPolicies/gpt6_astra/prompts/prompt.txt",
            "AgentPolicies/gpt6_astra/checks/test_policy.py",
            "AgentPolicies/gpt6_astra/results/README.md",
            "AgentPolicies/gpt6_astra/results/robodojo/index.json",
            "AgentPolicies/gpt6_astra/results/robodojo/reports/run/result.json",
            "AgentPolicies/gpt6_astra/results/robodojo/reports/run/episodes.json",
            "AgentPolicies/gpt6_astra/results/robodojo/report/run/index.html",
            "AgentPolicies/gpt6_astra/results/robodojo/interaction/run/history.json",
            "benchkit/reports/basic_result.py",
            "benchkit/checks/test_repository_hygiene.py",
            "benchmarks/simBenchmarks/Example/bench_server/protocol/tasks.json",
            "benchmarks/simBenchmarks/Example/bench_server/protocol/tasks.jsonl",
            "benchmarks/simBenchmarks/Example/rollouts/README.md",
            "assets/bench_server/index.html",
            "assets/architecture.png",
            "docs/assets/architecture.svg",
            "public/example/README.md",
            ".env.example",
        ]
        self.assert_ignore_set(paths, [])

    def test_caches_large_media_and_credentials_are_ignored(self):
        paths = [
            "benchkit/__pycache__/contracts.cpython-310.pyc",
            "AgentPolicies/gpt6_astra/checks/__pycache__/test_policy.pyc",
            ".pytest_cache/README.md", ".coverage", "htmlcov/index.html",
            "benchkit/artifacts/check.json", "benchkit/logs/check.log",
            "AgentPolicies/gpt6_astra/results/robodojo/reports/run/video.mp4",
            "benchmarks/simBenchmarks/Example/rollouts/old-run/frame.png",
            ".env", ".env.private", "private_token", "private_api_key",
        ]
        self.assert_ignore_set(paths, paths)

    def test_ignore_rules_do_not_hide_already_tracked_files(self):
        path = self.root / "benchkit/_local/already-tracked.json"
        path.parent.mkdir(parents=True)
        path.write_text("{}\n", encoding="utf-8")
        relative = path.relative_to(self.root).as_posix()
        self._git("add", "--force", "--", relative)
        self.assert_ignore_set([relative], [])
        matched = self._git("check-ignore", "--no-index", "--", relative)
        self.assertEqual(matched.strip(), relative)


if __name__ == "__main__":
    unittest.main()
