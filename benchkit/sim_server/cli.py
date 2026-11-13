"""Select a benchmark-owned service without importing native runtimes or models."""
from __future__ import annotations

import argparse
from importlib import import_module


# These are executable service entrypoints, not the in-process adapter
# registry. Keep task selection, native semantics and launch options in benchmarks.
SERVICE_MODULES = {
    "behavior": "benchmarks.simBenchmarks.Behavior.server",
    "calvin": "benchmarks.simBenchmarks.calvin.server",
    "domino": "benchmarks.simBenchmarks.DOMINO.server",
    "libero": "benchmarks.simBenchmarks.LIBERO.server",
    "libero_plus": "benchmarks.simBenchmarks.LIBERO-plus.server",
    "metaworld": "benchmarks.simBenchmarks.MetaWorld.server",
    "robocasa365": "benchmarks.simBenchmarks.Robocasa_365.server",
    "robocasa_tabletop": "benchmarks.simBenchmarks.Robocasa_tabletop.server",
    "robodojo": "benchmarks.simBenchmarks.RoboDojo.server",
    "robotwin": "benchmarks.simBenchmarks.Robotwin.server",
    "simple_humanoid": "benchmarks.simBenchmarks.SIMPLE.server",
    "simpler_env": "benchmarks.simBenchmarks.SimplerEnv.server",
    "vla_arena": "benchmarks.simBenchmarks.VLA-Arena.server",
    "vln_ce": "benchmarks.simBenchmarks.VLN-CE.server",
}


class _SingleBenchmark(argparse.Action):
    def __call__(self, parser, namespace, value, option_string=None):
        if getattr(namespace, self.dest, None) is not None:
            raise argparse.ArgumentError(self, "specify --benchmark exactly once")
        setattr(namespace, self.dest, value)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="rsi-bench", allow_abbrev=False,
        description="List or launch a benchmark service for your agent's trusted driver.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", allow_abbrev=False, help="list implemented development services")
    serve = commands.add_parser(
        "serve", add_help=False, allow_abbrev=False, help="launch one benchmark-owned service",
        description="Select a service and pass its launch arguments unchanged.",
        epilog="Use serve --benchmark ID --help for the selected service's launch arguments. "
               "Native environments and assets must be prepared separately.")
    serve.add_argument("--benchmark", choices=tuple(SERVICE_MODULES),
                       action=_SingleBenchmark, help="exact service ID (required except for generic help)")
    commands.add_parser("gateway", add_help=False, allow_abbrev=False,
                        help="bench host: serve catalog cases as per-case services (see gateway --help)")
    commands.add_parser("remote-run", add_help=False, allow_abbrev=False,
                        help="agent host: run catalog cases through a forwarded gateway (see remote-run --help)")
    args, remaining = parser.parse_known_args(argv)
    if args.command in ("gateway", "remote-run"):
        module = "gateway" if args.command == "gateway" else "remote_run"
        return import_module("benchkit.sim_server." + module).main(remaining)
    if args.command == "list":
        if remaining:
            parser.error("unrecognized arguments: " + " ".join(remaining))
        print("Development services; listing does not verify native readiness or full-suite support.")
        print("Documentation paths are repository-relative; installed wheels may omit these documents.")
        for identity, module in SERVICE_MODULES.items():
            guide = module.rsplit(".", 1)[0].replace(".", "/") + "/README.md"
            print(f"{identity}\t{guide}")
        return 0

    # parse_known_args preserves benchmark-owned arguments. Do not let an
    # abbreviated selector accidentally reach a different service's parser.
    for value in remaining:
        option = value.split("=", 1)[0]
        if option.startswith("--") and option != "--" and "--benchmark".startswith(option):
            serve.error("use the exact --benchmark selector; abbreviations are not supported")
    if args.benchmark is None:
        if remaining and all(value in {"-h", "--help"} for value in remaining):
            serve.print_help()
            return 0
        serve.error("the following argument is required: --benchmark")
    # Selected help follows the same path: the existing launcher prints its
    # actual options before token validation, construction or output creation.
    return import_module(SERVICE_MODULES[args.benchmark]).main(remaining)


if __name__ == "__main__":
    raise SystemExit(main())
