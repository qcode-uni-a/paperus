"""Command line interface: ``paperus serve``, ``worker``, ``user create``."""

import argparse
import getpass
import logging
import sys

import uvicorn
from sqlalchemy.exc import IntegrityError

from paperus.auth import create_user
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.jobs import run_worker


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="paperus")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    commands.add_parser("worker", help="run background jobs (text extraction, …)")

    user = commands.add_parser("user", help="manage users")
    user_commands = user.add_subparsers(dest="user_command", required=True)
    user_create = user_commands.add_parser("create", help="create a user")
    user_create.add_argument("username")
    user_create.add_argument("--admin", action="store_true")

    args = parser.parse_args(argv)

    if args.command == "serve":
        uvicorn.run(
            "paperus.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
    elif args.command == "worker":
        logging.basicConfig(level=logging.INFO)
        run_worker(Settings())
    elif args.command == "user" and args.user_command == "create":
        sys.exit(create_user_command(args.username, is_admin=args.admin))


def create_user_command(username: str, *, is_admin: bool) -> int:
    password = getpass.getpass("Password: ")
    if password != getpass.getpass("Repeat password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1
    if not password:
        print("Password must not be empty.", file=sys.stderr)
        return 1
    sessions = make_sessionmaker(make_engine(Settings().database_url))
    with sessions() as db:
        try:
            create_user(db, username, password, is_admin=is_admin)
            db.commit()
        except IntegrityError:
            print(f"User {username!r} already exists.", file=sys.stderr)
            return 1
    print(f"Created user {username!r}.")
    return 0
