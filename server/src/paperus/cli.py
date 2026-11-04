"""Command line interface: ``paperus serve``."""

import argparse

import uvicorn


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="paperus")
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "serve":
        uvicorn.run(
            "paperus.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
