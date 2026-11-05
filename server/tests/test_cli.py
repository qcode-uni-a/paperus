import io

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.auth import verify_password
from paperus.cli import main
from paperus.models import User


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
