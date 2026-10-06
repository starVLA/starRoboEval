"""Stdlib-only language-contract regression; no native runtime or rescore."""
import unittest

from benchkit.contracts import EpisodeSpec, Observation, PolicyEpisodeSpec


class InstructionContractTests(unittest.TestCase):
    def test_episode_metadata_normalizes_only_outer_whitespace(self):
        raw = " pick up the object and place  on the table. \n"
        episode = EpisodeSpec(id="fixture", task="fixture", seed=0, instruction=raw)
        public_episode = PolicyEpisodeSpec(id="opaque", task="fixture", instruction=raw)
        self.assertEqual(episode.instruction, raw.strip())
        self.assertEqual(public_episode.instruction, raw.strip())
        self.assertIn("place  on", episode.instruction)

    def test_observation_and_log_preserve_exact_native_language(self):
        for raw in (" leading", "trailing ", " internal  spaces ", "\ttext\n"):
            with self.subTest(raw=raw):
                observation = Observation(step=0, instruction=raw)
                self.assertEqual(observation.instruction, raw)
                self.assertEqual(observation.log_view()["instruction"], raw)
                self.assertNotEqual(observation.instruction, raw.strip())

    def test_raw_observation_is_not_episode_metadata(self):
        raw = " pick up the object."
        episode = EpisodeSpec(id="fixture", task="fixture", seed=0, instruction=raw)
        observation = Observation(step=1, instruction=raw)
        self.assertNotEqual(observation.instruction, episode.instruction)
        self.assertEqual(observation.instruction.strip(), episode.instruction)


if __name__ == "__main__":
    unittest.main()
