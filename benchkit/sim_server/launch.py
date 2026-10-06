"""Shared launch mechanics; benchmark-owned entrypoints supply native factories."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal

from benchkit.sim_server.server import BenchmarkService, make_http_server
from benchkit.sim_server.wire import loads


def main(factory, *, excluded_artifact_directories=(), supplemental_sources=(),
         require_complete_schedule=False, argv=None) -> int:
    parser = argparse.ArgumentParser(description="Serve one predeclared SIM schedule to a trusted evaluator")
    parser.add_argument("--parameters", type=Path, help="native adapter JSON object; paths resolve on server")
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument("--episodes", type=int)
    parser.add_argument("--output-dir", type=Path, required=True, help="fresh model-owned result staging directory")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token-env", default="RSI_SIM_SERVER_TOKEN", help="evaluator-only bearer token variable")
    parser.add_argument("--retain-frame-images", action=argparse.BooleanOptionalAction, default=False,
                        help="keep closed native frame images in addition to server videos; default off")
    args = parser.parse_args(argv)
    if require_complete_schedule and args.episodes is not None:
        parser.error("this benchmark requires its complete named panel; omit --episodes")
    token = os.environ.get(args.token_env, "")
    # Validate credentials before any native factory construction or storage.
    import re
    if re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token) is None:
        parser.error("set a 32..256 character URL-safe token in the selected environment variable")
    parameters = loads(args.parameters.read_bytes()) if args.parameters else {}
    adapter = factory(parameters)
    service = BenchmarkService(adapter, root=args.output_dir, seed=args.seed, limit=args.episodes,
                               parameters=parameters, capture_source=True,
                               supplemental_sources=supplemental_sources,
                               excluded_artifact_directories=excluded_artifact_directories,
                               retain_frame_images=args.retain_frame_images)
    httpd = make_http_server(service, token=token, port=args.port)
    print(json.dumps({"status": "listening", "endpoint": f"http://127.0.0.1:{httpd.server_port}",
                      "server_id": service.description["server_id"],
                      "episodes": len(service.episodes), "native_resets": 0}), flush=True)

    def stop(_signal, _frame):
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        # Native calls run serially on this same thread, not a background ticking
        # render loop. Idle wall time does not consume simulator control steps.
        httpd.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGTERM, previous)
        httpd.server_close()
        service.close()
    return 0
