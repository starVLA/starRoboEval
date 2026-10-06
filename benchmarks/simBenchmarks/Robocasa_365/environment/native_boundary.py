"""Legacy diagnostic constructor; the canonical boundary is this benchmark's adapter."""

from benchmarks.simBenchmarks.Robocasa_365.bench_server.adapter import (  # noqa: F401
    ACTION_SPEC, CAMERAS, NATIVE_HORIZONS, NEUTRAL_ACTION, OBSERVATION_SPEC,
    PILOT_SEED, PILOT_TASKS, ROBOCASA_REVISION, ROBOSUITE_REVISION,
    RoboCasa365BenchmarkAdapter, RoboCasa365Episode,
    action_dictionary, policy_observation, verify_sources,
)


class NativeBoundary(RoboCasa365Episode):
    """Legacy diagnostic construction; caller must bind a private artifact directory."""

    def __init__(self, task, seed, gpu, *, render_track="native-v1"):
        benchmark = RoboCasa365BenchmarkAdapter(task_ids=[PILOT_TASKS.index(task)],
                                               render_gpu_device_id=gpu, render_track=render_track)
        super().__init__(benchmark, benchmark.episodes(seed)[0])
