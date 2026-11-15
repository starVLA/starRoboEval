"""The single public RoboDojo Direct-control SIM server."""
from collections.abc import Mapping

from benchmarks.simBenchmarks.RoboDojo.bench_server.adapter import DirectEEFBenchmarkAdapter, selection_protocol
from benchkit.sim_server.launch import main as launch

SUPPLEMENTAL_FILES = (
    "benchmarks/simBenchmarks/RoboDojo/__init__.py",
    "benchmarks/simBenchmarks/RoboDojo/server.py",
    "benchmarks/simBenchmarks/RoboDojo/bench_server/__init__.py",
    "benchmarks/simBenchmarks/RoboDojo/bench_server/adapter.py",
    "benchmarks/simBenchmarks/RoboDojo/bench_server/native_worker_client.py",
    "benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/__init__.py",
    "benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/reset_stability.py",
    "benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/robot_feedback.py",
    "benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/task_catalog.json",
    "benchmarks/simBenchmarks/RoboDojo/bench_server/protocol/task_catalog.py",
    "benchmarks/simBenchmarks/RoboDojo/environment/__init__.py",
    "benchmarks/simBenchmarks/RoboDojo/environment/asset_reference.py",
    "benchmarks/simBenchmarks/RoboDojo/environment/eef_kinematics.py",
    "benchmarks/simBenchmarks/RoboDojo/environment/reference_eef_runtime.py",
    "benchmarks/simBenchmarks/RoboDojo/environment/reference_eef_snapshot.json",
    "benchmarks/simBenchmarks/RoboDojo/environment/worker_runtime.py",
    "benchmarks/simBenchmarks/RoboDojo/environment/native_eef_worker.py",
)
SERVER_PARAMETERS = frozenset({"task_id", "runtime_manifest", "runtime_manifest_sha256",
    "evaluation_mode", "gpu_id", "worker_timeout",
    "stability_manifest", "stability_manifest_sha256"})  # max only


def make_robodojo(parameters: Mapping[str, object]) -> DirectEEFBenchmarkAdapter:
    """Build only the published Direct v2 + robot-feedback protocol.

    Protocol selection is deliberately absent from the server configuration:
    changing sensor/action semantics requires a new benchmark protocol, not a
    runtime selector beside the accepted result.
    """
    values = dict(parameters)
    if "protocol_track" in values or "robot_feedback" in values:
        raise ValueError("RoboDojo server protocol is fixed; remove protocol selectors")
    unknown = set(values) - SERVER_PARAMETERS
    if unknown:
        raise ValueError(f"unknown RoboDojo server parameters: {sorted(unknown)}")
    adapter = DirectEEFBenchmarkAdapter(**values)
    if adapter.descriptor.protocol_version != selection_protocol(adapter.evaluation_mode):
        raise ValueError("RoboDojo adapter and task-catalog interface protocols differ")
    return adapter


def main(argv=None) -> int:
    """Capture the final private worker while excluding only runtime cache."""
    return launch(make_robodojo, excluded_artifact_directories=("cache",), require_complete_schedule=True,
                  supplemental_sources=SUPPLEMENTAL_FILES, argv=argv)


if __name__ == "__main__":
    raise SystemExit(main())
