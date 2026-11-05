"""Command line: ``paperus serve``, ``worker``, ``migrate``, ``user create``,
``backup create|list|restore``, ``import``."""

import argparse
import getpass
import logging
import sys
from pathlib import Path

import uvicorn
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from paperus.access import Access, Forbidden, NotVisible
from paperus.auth import create_user
from paperus.backup import (
    BackupError,
    check_restore,
    create_backup,
    list_backups,
    restore_backup,
)
from paperus.config import Settings
from paperus.db import make_engine, make_sessionmaker
from paperus.importing.run import run_import
from paperus.jobs import make_job_app, queue_text_extraction, run_worker
from paperus.migrate import migrate
from paperus.models import Group, Import, ImportStatus, User
from paperus.storage import make_blob_store


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="paperus")
    commands = parser.add_subparsers(dest="command", required=True)

    serve = commands.add_parser("serve", help="run the API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")

    commands.add_parser("worker", help="run background jobs (text extraction, …)")
    commands.add_parser("migrate", help="bring the database schema up to date")

    user = commands.add_parser("user", help="manage users")
    user_commands = user.add_subparsers(dest="user_command", required=True)
    user_create = user_commands.add_parser("create", help="create a user")
    user_create.add_argument("username")
    user_create.add_argument("--admin", action="store_true")
    user_create.add_argument(
        "--password-stdin",
        action="store_true",
        help="read the password from standard input (for scripts)",
    )

    backup = commands.add_parser("backup", help="back up and restore")
    backup_commands = backup.add_subparsers(dest="backup_command", required=True)
    backup_create = backup_commands.add_parser("create", help="write a backup now")
    backup_create.add_argument(
        "--no-files", action="store_true", help="only the database, not the files"
    )
    backup_commands.add_parser("list", help="list backups, newest first")
    backup_restore = backup_commands.add_parser(
        "restore", help="restore a backup into the database (and missing files)"
    )
    backup_restore.add_argument("name", help="the backup's name, see `backup list`")
    backup_restore.add_argument(
        "--replace",
        action="store_true",
        help="drop everything in the database first (it must be empty otherwise)",
    )

    import_ = commands.add_parser(
        "import",
        help="import a BibTeX, RIS or CSL-JSON export (zip, folder or file)",
    )
    import_.add_argument("path", help="the export: a zip, a folder or the file")
    import_.add_argument("--user", required=True, help="who imports (username)")
    import_.add_argument(
        "--group",
        help="give everything new to this group (default: the user's default owner)",
    )

    args = parser.parse_args(argv)

    if args.command == "serve":
        uvicorn.run(
            "paperus.app:create_app",
            factory=True,
            host=args.host,
            port=args.port,
            reload=args.reload,
            proxy_headers=True,
            forwarded_allow_ips=Settings().trusted_proxies,
            # Don't wait forever for open connections (e.g. an AI assistant's
            # MCP stream) when stopping or reloading.
            timeout_graceful_shutdown=5,
        )
    elif args.command == "worker":
        logging.basicConfig(level=logging.INFO)
        run_worker(Settings())
    elif args.command == "migrate":
        logging.basicConfig(level=logging.INFO)
        migrate(Settings())
    elif args.command == "backup":
        logging.basicConfig(level=logging.INFO)
        sys.exit(backup_command(args))
    elif args.command == "import":
        logging.basicConfig(level=logging.WARNING)
        sys.exit(import_command(args.path, args.user, args.group))
    elif args.command == "user" and args.user_command == "create":
        sys.exit(
            create_user_command(
                args.username, is_admin=args.admin, from_stdin=args.password_stdin
            )
        )


def create_user_command(
    username: str, *, is_admin: bool, from_stdin: bool = False
) -> int:
    if from_stdin:
        password = sys.stdin.readline().rstrip("\n")
    else:
        password = getpass.getpass("Password: ")
        if password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.", file=sys.stderr)
            return 1
    if not password:
        print("Password must not be empty.", file=sys.stderr)
        return 1
    engine = make_engine(Settings().database_url)
    try:
        with make_sessionmaker(engine)() as db:
            create_user(db, username, password, is_admin=is_admin)
            db.commit()
    except IntegrityError:
        print(f"User {username!r} already exists.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    print(f"Created user {username!r}.")
    return 0


def backup_command(args: argparse.Namespace) -> int:
    settings = Settings()
    root = settings.backup_path
    engine = make_engine(settings.database_url)
    try:
        if args.backup_command == "create":
            manifest = create_backup(
                engine, make_blob_store(settings), root, with_files=not args.no_files
            )
            print(f"Wrote backup {manifest.name} to {root}.")
        elif args.backup_command == "list":
            for manifest in list_backups(root):
                files = f", {manifest.files} files" if manifest.with_files else ""
                items = (
                    manifest.tables["items"].rows if "items" in manifest.tables else 0
                )
                print(
                    f"{manifest.name}  paperus {manifest.paperus_version}, "
                    f"{items} items{files}"
                )
        elif args.backup_command == "restore":
            blobs = make_blob_store(settings)
            check = check_restore(blobs, root, args.name)
            print(
                f"Files: {check.needed} needed, {check.in_storage} already in "
                f"the storage, {check.from_backup} from the backup, "
                f"{check.missing} missing."
            )
            if check.extra:
                print(
                    f"{check.extra} files in the storage are not in the backup; "
                    "they stay."
                )
            if check.missing:
                print(f"{check.affected_count} papers would lack a file, e.g.:")
                for title in check.affected[:5]:
                    print(f"  {title}")
                if input("Restore anyway? Type yes: ").strip().lower() != "yes":
                    print("Nothing changed.")
                    return 1
            if args.replace:
                answer = input(
                    "This drops everything in the database first. Type yes: "
                )
                if answer.strip().lower() != "yes":
                    print("Nothing changed.")
                    return 1
            restore_backup(
                settings,
                engine,
                make_blob_store(settings),
                root,
                args.name,
                replace=args.replace,
            )
            print(f"Restored {args.name}. Start paperus again.")
    except BackupError as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


def import_command(path_text: str, username: str, group: str | None) -> int:
    """Import on the server, for libraries too large to upload."""
    path = Path(path_text)
    if not path.exists():
        print(f"{path} does not exist.", file=sys.stderr)
        return 1
    settings = Settings()
    engine = make_engine(settings.database_url)
    jobs = make_job_app(settings)
    try:
        with make_sessionmaker(engine)() as db, jobs.open():
            user = db.scalar(select(User).where(User.username == username))
            if user is None:
                print(f"No user {username!r}.", file=sys.stderr)
                return 1
            access = Access.of(db, user)
            owner = access.target_library(None)
            if group is not None:
                found = db.scalar(select(Group).where(Group.name == group))
                if found is None or found.id not in access.group_libraries:
                    print(f"{username} is in no group {group!r}.", file=sys.stderr)
                    return 1
                owner = access.group_libraries[found.id]
            record = Import(
                user_id=user.id,
                library_id=owner,
                filename=path.name,
                status=ImportStatus.WAITING,
            )
            db.add(record)
            db.commit()
            record_id = record.id
            run_import(
                db,
                make_blob_store(settings),
                record,
                path=path,
                max_file_bytes=settings.max_upload_bytes,
                file_added=lambda file_id: queue_text_extraction(jobs, file_id),
            )
            done = db.get(Import, record_id)
            if done is None or done.status != ImportStatus.DONE:
                print(done.error if done else "The import failed.", file=sys.stderr)
                return 1
            report = done.report or {}
            print(
                f"{report.get('papers', 0)} papers: {report.get('added', 0)} added, "
                f"{report.get('found', 0)} already there; {report.get('files', 0)} "
                f"files, {report.get('notes', 0)} notes, "
                f"{report.get('collections', 0)} new collections."
            )
            for missing in report.get("missing_files", []):
                print(f"Missing file: {missing}")
            for problem in report.get("problems", []):
                print(f"Problem: {problem}")
    except (Forbidden, NotVisible) as error:
        print(error, file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0
