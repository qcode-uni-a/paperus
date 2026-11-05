"""Search evaluation: questions with the paper each should find."""

import json
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.access import Access
from paperus.cli import main
from paperus.config import Settings
from paperus.embedding import embed_file
from paperus.evaluate import Question, Scores, evaluate, load_questions, rank, report
from paperus.models import User
from paperus.processing import process_file
from paperus.storage import BlobStore
from tests.conftest import FakeML

MODEL = "bge-m3"


def paper(
    client: TestClient, db: Session, blobs: BlobStore, ml: FakeML, text: bytes
) -> uuid.UUID:
    item = client.post("/api/items", json={"metadata": {"title": "Paper"}}).json()
    file = client.post(
        f"/api/items/{item['id']}/files",
        files={"upload": ("text.md", text, "text/markdown")},
    ).json()
    process_file(db, blobs, uuid.UUID(file["id"]))
    embed_file(db, ml.client(), MODEL, uuid.UUID(file["id"]))
    return uuid.UUID(item["id"])


def test_scores() -> None:
    scores = Scores()
    for found in (1, 3, None, 10):
        scores.add(found)
    assert scores.hit(1) == 0.25
    assert scores.hit(5) == 0.5
    assert scores.mrr == pytest.approx((1 + 1 / 3 + 1 / 10) / 4)


def test_rank_counts_other_right_papers() -> None:
    a, b, c = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    assert rank([a, b, c], {c}) == 3
    assert rank([a, b, c], {c, b}) == 2
    assert rank([a] * 10 + [c], {c}) is None


def test_evaluate_per_mode(
    logged_in: TestClient,
    db: Session,
    blobs: BlobStore,
    fake_ml: FakeML,
    settings: Settings,
) -> None:
    rain = paper(logged_in, db, blobs, fake_ml, b"Rainfall gauges were read weekly.")
    gaps = paper(logged_in, db, blobs, fake_ml, b"Missing days were interpolated.")
    questions = [
        Question("rainfall gauges", rain, kind="keyword"),
        Question("gaps", gaps, kind="meaning"),
    ]
    user = db.scalars(select(User).where(User.username == "ada")).one()
    results = evaluate(db, Access.of(db, user), fake_ml.client(), settings, questions)
    by_mode = {r.mode: r for r in results}
    assert by_mode["keyword"].all.ranks == [1, None]
    assert by_mode["meaning"].all.ranks[1] == 1
    assert by_mode["hybrid"].all.ranks == [1, 1]
    assert by_mode["hybrid"].by_kind["meaning"].ranks == [1]
    text = report(results, questions)
    assert "keyword    all          2   0.50   0.50   0.50" in text
    assert text.splitlines()[-1].endswith("  gaps")

    # Without the ML service, the report says hybrid used keywords only.
    fake_ml.down = True
    [hybrid] = evaluate(
        db, Access.of(db, user), fake_ml.client(), settings, questions, ("hybrid",)
    )
    assert hybrid.used == {"keyword"}
    assert "(used keyword)" in report([hybrid])


def test_questions_file_and_command(
    logged_in: TestClient,
    db: Session,
    database_url: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    item = logged_in.post("/api/items", json={"metadata": {"title": "X"}}).json()
    other = str(uuid.uuid4())
    path = tmp_path / "questions.json"
    path.write_text(
        json.dumps(
            [{"q": "rain", "item_id": item["id"], "accept": [other], "kind": "vague"}]
        )
    )
    [question] = load_questions(path)
    assert question.right == {uuid.UUID(item["id"]), uuid.UUID(other)}
    assert question.kind == "vague"

    monkeypatch.setenv("PAPERUS_DATABASE_URL", database_url)
    # No ML service here: meaning finds nothing, the others fall back.
    monkeypatch.setenv("PAPERUS_ML_URLS", "[]")
    with pytest.raises(SystemExit) as exit:
        main(["evaluate", str(path), "--user", "ada", "--each"])
    assert exit.value.code == 0
    out = capsys.readouterr().out
    assert "hit@1" in out
    assert out.rstrip().endswith("  rain")
    with pytest.raises(SystemExit) as exit:
        main(["evaluate", str(path), "--user", "nobody"])
    assert exit.value.code == 1
