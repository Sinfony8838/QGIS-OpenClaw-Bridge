from __future__ import annotations

import argparse

from .config import RuntimeConfig
from .runtime import GeoBotRuntime
from .server import run_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the GeoBot local product runtime.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18999)
    parser.add_argument("--qgis-port", type=int, default=5555)
    args = parser.parse_args()

    config = RuntimeConfig(host=args.host, port=args.port, qgis_port=args.qgis_port)
    runtime = GeoBotRuntime(config)
    server = run_server(runtime)
    print(f"GeoBot Runtime listening on http://{config.host}:{config.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
