"""``paperus-ml``: run the service (``--host 0.0.0.0`` in containers)."""

import argparse
import logging

import uvicorn


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="paperus-ml")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3003)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(
        "paperus_ml.main:create_app", factory=True, host=args.host, port=args.port
    )
