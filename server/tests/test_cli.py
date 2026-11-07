import io
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import make_url, select
from sqlalchemy.orm import Session
from uvicorn.importer import import_from_string

from paperus import __version__
from paperus.app import create_app
from paperus.auth import verify_password
from paperus.backup import list_backups
from paperus.cli import main
from paperus.config import Settings
from paperus.models import User
from tests.conftest import _recreate_database
from tests.pdfs import make_pdf
from tests.people import Person, group


def run(argv: list[str], monkeypatch: pytest.MonkeyPatch, database_url: str) -> int:
    monkeypatch.setenv("PAPERUS_DATABASE_URL", database_url)
    try:
        main(argv)
    except SystemExit as exit:
        return int(exit.code or 0)
    return 0


def test_migrate_is_repeatable(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    assert run(["migrate"], monkeypatch, database_url) == 0


def test_create_user_from_stdin(
    monkeypatch: pytest.MonkeyPatch, database_url: str, db: Session
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("s3cret pass\n"))
    assert (
        run(
            ["user", "create", "root", "--admin", "--password-stdin"],
            monkeypatch,
            database_url,
        )
        == 0
    )
    user = db.scalars(select(User).where(User.username == "root")).one()
    assert user.is_admin
    assert verify_password(user.password_hash, "s3cret pass")

    monkeypatch.setattr("sys.stdin", io.StringIO("again\n"))
    assert (
        run(["user", "create", "root", "--password-stdin"], monkeypatch, database_url)
        == 1
    )


def test_empty_password_is_refused(
    monkeypatch: pytest.MonkeyPatch, database_url: str, db: Session
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    assert (
        run(["user", "create", "nobody", "--password-stdin"], monkeypatch, database_url)
        == 1
    )


def test_serve_runs_the_app_behind_proxies(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    started: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "paperus.cli.uvicorn.run",
        lambda app, **options: started.append((app, options)),
    )
    monkeypatch.setenv("PAPERUS_TRUSTED_PROXIES", "10.1.2.3")
    assert run(["serve", "--port", "8123", "--reload"], monkeypatch, database_url) == 0
    [(app, options)] = started
    assert import_from_string(app) is create_app
    assert options["factory"] and options["proxy_headers"]
    assert (options["host"], options["port"], options["reload"]) == (
        "127.0.0.1",
        8123,
        True,
    )
    assert options["forwarded_allow_ips"] == "10.1.2.3"


def test_worker_gets_the_settings(
    monkeypatch: pytest.MonkeyPatch, database_url: str
) -> None:
    given: list[Settings] = []
    monkeypatch.setattr("paperus.cli.run_worker", given.append)
    assert run(["worker"], monkeypatch, database_url) == 0
    assert [s.database_url for s in given] == [database_url]


def test_create_user_asks_twice(
    monkeypatch: pytest.MonkeyPatch, database_url: str, db: Session
) -> None:
    answers = iter(["one", "other", "s3cret", "s3cret"])
    monkeypatch.setattr("getpass.getpass", lambda prompt: next(answers))
    assert run(["user", "create", "ada"], monkeypatch, database_url) == 1
    assert db.scalar(select(User).where(User.username == "ada")) is None
    assert run(["user", "create", "ada"], monkeypatch, database_url) == 0
    user = db.scalars(select(User).where(User.username == "ada")).one()
    assert not user.is_admin
    assert verify_password(user.password_hash, "s3cret")


@pytest.fixture
def restore_url(database_url: str) -> str:
    """An empty database to restore into (this run's own)."""
    url = make_url(database_url)
    url = url.set(database=f"{url.database}_restore")
    rendered = url.render_as_string(hide_password=False)
    _recreate_database(rendered)
    return rendered


def test_backup_list_and_restore(
    client: TestClient,
    db: Session,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    restore_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    ada = Person(client, db, "ada")
    item = ada.add("Kept safe")
    pdf = make_pdf([["Rain gauges"]])
    ada.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("paper.pdf", pdf, "application/pdf")},
    )
    backups = tmp_path / "backups"
    monkeypatch.setenv("PAPERUS_STORAGE_PATH", str(settings.storage_path))
    monkeypatch.setenv("PAPERUS_BACKUP_PATH", str(backups))

    into = database_url

    def backup(*argv: str, answers: str = "") -> tuple[int, str]:
        monkeypatch.setattr("sys.stdin", io.StringIO(answers))
        code = run(["backup", *argv], monkeypatch, into)
        out, err = capsys.readouterr()
        return code, out + err

    code, out = backup("create")
    assert code == 0 and out.startswith("Wrote backup ")
    full = list_backups(backups)[0].name
    (backups / full).rename(backups / "2000-01-01T00-00-00Z")
    assert backup("create", "--no-files")[0] == 0
    only_db = list_backups(backups)[0].name
    code, out = backup("list")
    assert out.splitlines() == [
        f"{only_db}  paperus {__version__}, 1 items",
        f"2000-01-01T00-00-00Z  paperus {__version__}, 1 items, 1 files",
    ]

    # Into an empty database and storage: without the files the paper would
    # lack its PDF, so it asks first.
    monkeypatch.setenv("PAPERUS_STORAGE_PATH", str(tmp_path / "new-storage"))
    into = restore_url
    code, out = backup("restore", only_db, answers="no\n")
    assert code == 1
    assert "1 needed, 0 already in the storage, 0 from the backup, 1 missing" in out
    assert "1 papers would lack a file, e.g.:\n  Kept safe\n" in out
    assert out.endswith("Nothing changed.\n")
    code, out = backup("restore", only_db, answers="yes\n")
    assert code == 0 and out.endswith(f"Restored {only_db}. Start paperus again.\n")

    # Not over a database in use, unless asked to replace it (and confirmed).
    code, out = backup("restore", "2000-01-01T00-00-00Z")
    assert code == 1 and "not empty" in out
    monkeypatch.setenv("PAPERUS_STORAGE_PATH", str(settings.storage_path))
    later = ada.add("Later")
    ada.post(
        f"/api/items/{later['id']}/files",
        files={"upload": ("later.pdf", make_pdf([["Later"]]), "application/pdf")},
    )
    code, out = backup("restore", only_db, "--replace", answers="nope\n")
    assert code == 1
    assert "1 files in the storage are not in the backup; they stay." in out
    assert out.endswith("Nothing changed.\n")
    monkeypatch.setenv("PAPERUS_STORAGE_PATH", str(tmp_path / "new-storage"))
    code, out = backup("restore", "2000-01-01T00-00-00Z", "--replace", answers="yes")
    assert code == 0
    assert "0 missing" in out
    assert len(list((tmp_path / "new-storage").rglob("*"))) > 0

    code, out = backup("restore", "1999-01-01T00-00-00Z")
    assert code == 1 and "no backup '1999-01-01T00-00-00Z'" in out


def test_import_refusals(
    client: TestClient,
    db: Session,
    settings: Settings,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    database_url: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    chair = group(root, "Chair", ada)
    export = tmp_path / "library.bib"
    export.write_text(
        "@article{a, title={Rain gauges}, file={:gauges.pdf:PDF}}\n"
        "@article{a, title={Wind vanes}}\n"
    )
    monkeypatch.setenv("PAPERUS_STORAGE_PATH", str(settings.storage_path))

    def run_import(path: Path, *options: str) -> tuple[int, str]:
        code = run(["import", str(path), *options], monkeypatch, database_url)
        out, err = capsys.readouterr()
        return code, out + err

    assert run_import(tmp_path / "gone.bib", "--user", "ada") == (
        1,
        f"{tmp_path / 'gone.bib'} does not exist.\n",
    )
    assert run_import(export, "--user", "nobody") == (1, "No user 'nobody'.\n")
    assert run_import(export, "--user", "ada", "--group", "Chairs") == (
        1,
        "ada is in no group 'Chairs'.\n",
    )
    # Into a group of theirs; what was missing or odd is listed.
    code, out = run_import(export, "--user", "ada", "--group", "Chair")
    assert code == 0 and out.startswith("2 papers: 2 added, 0 already there")
    assert "Missing file: gauges.pdf\n" in out
    assert "Problem: The key a appears more than once" in out
    papers = ada.get("/api/items").json()
    assert {p["library_id"] for p in papers} == {chair["library_id"]}

    (tmp_path / "notes.txt").write_text("not an export")
    code, out = run_import(tmp_path / "notes.txt", "--user", "ada")
    assert code == 1 and out.strip()
    assert ada.titles() == ["Rain gauges", "Wind vanes"]


def test_openapi_script_prints_the_schema(
    settings: Settings, database_url: str
) -> None:
    printed = subprocess.run(
        [sys.executable, "-m", "paperus.openapi"],
        capture_output=True,
        check=True,
        env={**os.environ, "PAPERUS_DATABASE_URL": database_url},
    ).stdout
    assert json.loads(printed) == create_app(settings).openapi()
