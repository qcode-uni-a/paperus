"""How well search finds papers: questions, each with the paper it should
find, run in every search mode; scored by hit@1, hit@5 and MRR@10 (one
over the rank of the first right paper among the top ten, averaged).

The questions file is JSON: a list of ``{"q": "…", "item_id": "…"}``,
optionally with ``"accept"`` (other papers that count as right) and
``"kind"`` (a label to break the scores down by, e.g. "vague")."""

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import get_args

from sqlalchemy.orm import Session

from paperus.access import Access
from paperus.api.search import Mode, run_search
from paperus.config import Settings
from paperus.ml import MLClient

TOP = 10


@dataclass
class Question:
    q: str
    item_id: uuid.UUID
    accept: set[uuid.UUID] = field(default_factory=set)
    kind: str = ""

    @property
    def right(self) -> set[uuid.UUID]:
        return {self.item_id, *self.accept}


@dataclass
class Scores:
    ranks: list[int | None] = field(default_factory=list)
    """Per question: the first right paper's rank (1 = top), None if not in
    the top ten."""

    def add(self, rank: int | None) -> None:
        self.ranks.append(rank)

    def hit(self, k: int) -> float:
        return sum(1 for r in self.ranks if r is not None and r <= k) / max(
            len(self.ranks), 1
        )

    @property
    def mrr(self) -> float:
        return sum(1 / r for r in self.ranks if r is not None) / max(len(self.ranks), 1)


@dataclass
class ModeResult:
    mode: Mode
    used: set[Mode] = field(default_factory=set)
    """The modes search actually used (hybrid falls back to keywords without
    the ML service)."""
    all: Scores = field(default_factory=Scores)
    by_kind: dict[str, Scores] = field(default_factory=dict)


def load_questions(path: Path) -> list[Question]:
    return [
        Question(
            q=entry["q"],
            item_id=uuid.UUID(entry["item_id"]),
            accept={uuid.UUID(other) for other in entry.get("accept", [])},
            kind=entry.get("kind", ""),
        )
        for entry in json.loads(path.read_text())
    ]


def rank(papers: list[uuid.UUID], right: set[uuid.UUID]) -> int | None:
    for position, paper in enumerate(papers[:TOP], start=1):
        if paper in right:
            return position
    return None


def evaluate(
    db: Session,
    access: Access,
    ml: MLClient,
    settings: Settings,
    questions: list[Question],
    modes: tuple[Mode, ...] = get_args(Mode),
    rerank: bool | None = None,
) -> list[ModeResult]:
    """``rerank``: on or off whatever the administration's setting."""
    results = []
    for mode in modes:
        result = ModeResult(mode)
        for question in questions:
            used, passages = run_search(
                db,
                access,
                ml,
                settings,
                question.q,
                mode=mode,
                per_item=1,
                limit=TOP,
                rerank=rerank,
            )
            result.used.add(used)
            papers = [p.item_id for p in passages if p.item_id is not None]
            found = rank(papers, question.right)
            result.all.add(found)
            result.by_kind.setdefault(question.kind, Scores()).add(found)
        results.append(result)
    return results


def report(results: list[ModeResult], questions: list[Question] | None = None) -> str:
    """Scores per mode (and kind); with the questions, also each question's
    rank per mode ("-": not in the top ten)."""
    lines = [f"{'mode':<10} {'kind':<10} {'n':>3} {'hit@1':>6} {'hit@5':>6} {'MRR':>6}"]
    for result in results:
        note = (
            ""
            if result.used == {result.mode}
            else f"  (used {', '.join(sorted(result.used))})"
        )
        kinds = sorted((k, s) for k, s in result.by_kind.items() if k)
        rows = [("all", result.all), *kinds]
        for kind, scores in rows:
            lines.append(
                f"{result.mode:<10} {kind:<10} {len(scores.ranks):>3} "
                f"{scores.hit(1):>6.2f} {scores.hit(5):>6.2f} {scores.mrr:>6.2f}"
                + (note if kind == "all" else "")
            )
    if questions:
        lines.append("")
        lines.append(" ".join(f"{r.mode[:7]:>7}" for r in results) + "  question")
        for n, question in enumerate(questions):
            ranks = [r.all.ranks[n] for r in results]
            lines.append(
                " ".join(f"{rank if rank else '-':>7}" for rank in ranks)
                + f"  {question.q}"
            )
    return "\n".join(lines)
