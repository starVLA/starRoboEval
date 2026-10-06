"""An explicit placeholder, never a runnable named-model integration."""


def create_policy(**parameters):
    from benchkit.model_profiles import UnconfiguredModelProfile

    raise UnconfiguredModelProfile("Opus has no verified provider/model ID or implemented adapter")
