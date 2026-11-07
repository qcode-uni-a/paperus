"""The worker's jobs, run as ``paperus worker`` runs them (against
Procrastinate's in-memory stand-in), with the fake ML service and web."""

import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import Engine, func, select, update
from sqlalchemy.orm import Session

from paperus import integrity, jobs, ml, readable, system
from paperus.backup import list_backups
from paperus.config import Settings
from paperus.db import make_sessionmaker
from paperus.jobs import WorkerContext, tasks
from paperus.models import (
    Embedding,
    File,
    Import,
    ImportStatus,
    Item,
    OcrStatus,
    TextStatus,
)
from paperus.storage import BlobStore
from paperus.system import BackupConfig, load_config, save_backup_config, save_config
from tests.conftest import FakeDOIRegistry, FakeML
from tests.pdfs import make_pdf
from tests.people import Person

TYPED = "A typed first page about rain gauges, long enough to count as text."
HALF_SCANNED = make_pdf([[TYPED], []])
ARXIV = "2504.12221"
JOURNAL_DOI = "10.1088/2058-9565/ae0a7d"
PREPRINT = make_pdf([["Phonon-coupled hole-spin qubits, the preprint"]])
JOURNAL = make_pdf([["Phonon-coupled hole-spin qubits, as published"]])


class FakeWeb:
    """doi.org, arXiv (its API and its PDFs), OpenAlex and a journal."""

    def __init__(self, registry: FakeDOIRegistry) -> None:
        self.registry = registry
        self.published: dict[str, str] = {}
        """arXiv ID → the journal DOI arXiv knows."""
        self.open_journal: set[str] = set()
        """DOIs whose journal PDF OpenAlex lists as open."""

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        host = request.url.host
        if host == "doi.org":
            return self.registry(request)
        if host == "export.arxiv.org":
            entries = "".join(
                f"<entry><id>http://arxiv.org/abs/{paper}v1</id>"
                f"<arxiv:doi>{doi}</arxiv:doi></entry>"
                for paper, doi in self.published.items()
            )
            return httpx2.Response(200, text=f"<feed>{entries}</feed>")
        if host == "arxiv.org":
            return httpx2.Response(200, content=PREPRINT)
        if host == "api.openalex.org":
            doi = request.url.path.removeprefix("/works/doi:")
            open_copy = {
                "is_oa": True,
                "version": "publishedVersion",
                "pdf_url": "https://journal.example.org/paper.pdf",
            }
            locations = [open_copy] if doi in self.open_journal else []
            return httpx2.Response(200, json={"locations": locations})
        if host == "journal.example.org":
            return httpx2.Response(200, content=JOURNAL)
        return httpx2.Response(404)


@pytest.fixture
def web(doi_registry: FakeDOIRegistry) -> FakeWeb:
    return FakeWeb(doi_registry)


@pytest.fixture
def job_app(monkeypatch: pytest.MonkeyPatch) -> App:
    """Jobs recorded in memory, with the tasks a worker can run under the
    names they are queued by. (Each app that adds the blueprint's shared
    tasks prefixes their names again, so the conftest's app runs none.)
    No periodic tasks: only the jobs a test queues run."""
    app = App(connector=InMemoryConnector())
    for task in set(tasks.tasks.values()):
        name = f"paperus:{task.name.rsplit(':', 1)[-1]}"
        monkeypatch.setattr(task, "name", name)
        monkeypatch.setattr(task, "blueprint", app)
        app.tasks[name] = task
    return app


@pytest.fixture
def worker(
    engine: Engine,
    settings: Settings,
    blobs: BlobStore,
    fake_ml: FakeML,
    web: FakeWeb,
    job_app: App,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> App:
    """The worker's context; the job app to run the queued jobs with."""
    monkeypatch.setattr(settings, "copy_path", tmp_path / "copy")
    context = WorkerContext(
        engine=engine,
        sessions=make_sessionmaker(engine),
        blobs=blobs,
        http=httpx2.Client(transport=httpx2.MockTransport(web)),
        ml=fake_ml.client(),
        settings=settings,
    )
    monkeypatch.setattr(jobs, "_context", context)
    # The fake ML service changes between jobs: always asked anew.
    monkeypatch.setattr(ml, "VECTORS_TTL", 0)
    return job_app


def run_jobs(app: App) -> Counter[str]:
    """Run the queued jobs until none are left (retries wait), as
    ``paperus worker`` does; how many of each task ran, with how they ended
    (and forget them, for the next round)."""
    app.run_worker(wait=False, install_signal_handlers=False, listen_notify=False)
    assert isinstance(app.connector, InMemoryConnector)
    ran = Counter(
        f"{job['task_name'].removeprefix('paperus:')} {job['status']}"
        for job in app.connector.jobs.values()
    )
    app.connector.jobs.clear()
    return ran


def defer(app: App, task: str, **arguments: Any) -> None:  # noqa: ANN401
    app.configure_task(f"paperus:{task}").defer(**arguments)


def configure(db: Session, settings: Settings, **changes: Any) -> None:  # noqa: ANN401
    config = load_config(db, settings)
    for name, value in changes.items():
        setattr(config, name, value)
    save_config(db, config)
    db.commit()


def upload(person: Person, content: bytes, name: str = "paper.pdf") -> uuid.UUID:
    item = person.add("Upload")
    file: dict[str, Any] = person.post(
        f"/api/items/{item['id']}/files",
        files={"upload": (name, content, "application/pdf")},
    ).json()
    return uuid.UUID(file["id"])


def file_status(db: Session, file_id: uuid.UUID) -> tuple[str, str | None]:
    db.expire_all()
    file = db.get(File, file_id)
    assert file is not None
    return file.text_status, file.ocr_status


def embedded(db: Session, model: str = "bge-m3") -> int:
    return (
        db.scalar(
            select(func.count()).select_from(Embedding).where(Embedding.model == model)
        )
        or 0
    )


def test_without_a_context() -> None:
    with pytest.raises(RuntimeError, match="paperus worker"):
        jobs.embed(str(uuid.uuid4()))


def test_an_upload_is_read_scanned_and_embedded(
    client: TestClient, db: Session, worker: App, fake_ml: FakeML
) -> None:
    ada = Person(client, db, "ada")
    file_id = upload(ada, HALF_SCANNED)
    ada.note("A note on drizzle")
    assert run_jobs(worker) == {
        # Read twice: the typed page first, then with the scan's text.
        "extract_text succeeded": 2,
        "ocr_file succeeded": 1,
        "embed_file succeeded": 2,
        "embed_note succeeded": 1,
    }
    assert file_status(db, file_id) == (TextStatus.DONE, OcrStatus.DONE)
    assert len(fake_ml.read) == 1
    found = ada.get("/api/search", params={"q": "typewriter", "mode": "meaning"})
    first = found.json()[0]
    assert (first["page"], first["snippet"]) == (2, f"{FakeML.SCANNED} 1")
    # The typed page, the scanned one and the note.
    assert embedded(db) == 3


def test_ocr_switched_off_and_on(
    client: TestClient, db: Session, worker: App, fake_ml: FakeML
) -> None:
    root = Person(client, db, "root", admin=True)
    config = root.get("/api/admin/config").json()
    root.put("/api/admin/config", {**config, "ocr": False})
    file_id = upload(Person(client, db, "ada"), HALF_SCANNED)
    assert run_jobs(worker) == {
        "extract_text succeeded": 1,
        "embed_file succeeded": 1,
    }
    assert file_status(db, file_id) == (TextStatus.DONE, OcrStatus.SKIPPED)
    # The sweep, by hand, does nothing while OCR is off.
    root.post("/api/admin/jobs/ocr")
    assert run_jobs(worker) == {"queue_pending_ocr succeeded": 1}

    # Switched on: the waiting scans are read.
    root.put("/api/admin/config", {**config, "ocr": True})
    assert run_jobs(worker) == {
        "queue_pending_ocr succeeded": 1,
        "ocr_file succeeded": 1,
        "extract_text succeeded": 1,
        "embed_file succeeded": 1,
    }
    assert file_status(db, file_id) == (TextStatus.DONE, OcrStatus.DONE)

    # A job queued before OCR was switched off reads nothing.
    db.execute(update(File).values(ocr_status=OcrStatus.PENDING))
    db.commit()
    root.put("/api/admin/config", {**config, "ocr": False})
    jobs.queue_ocr(worker, file_id)
    assert run_jobs(worker) == {"ocr_file succeeded": 1}
    assert len(fake_ml.read) == 1


def test_missing_embeddings_and_another_model_file(
    client: TestClient, db: Session, worker: App, fake_ml: FakeML
) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    upload(ada, make_pdf([[TYPED]]))
    ada.note("A note on drizzle")
    fake_ml.down = True
    ran = run_jobs(worker)
    # Waiting for the ML service, to be retried later.
    assert ran["extract_text succeeded"] == 1
    assert ran["embed_file todo"] == ran["embed_note todo"] == 1
    assert embedded(db) == 0
    root.post("/api/admin/jobs/embeddings")
    assert run_jobs(worker) == {"queue_missing_embeddings succeeded": 1}

    fake_ml.down = False
    root.post("/api/admin/jobs/embeddings")
    assert run_jobs(worker) == {
        "queue_missing_embeddings succeeded": 1,
        "embed_file succeeded": 1,
        "embed_note succeeded": 1,
    }
    assert embedded(db) == 2

    # The ML service now runs another file of the model (a GPU's): its
    # vectors differ, so everything is embedded again.
    fake_ml.variant = "fp16"
    root.post("/api/admin/jobs/embeddings")
    run_jobs(worker)
    assert embedded(db, "bge-m3@fp16") == 2
    assert system.vectors_in_use(db, "bge-m3") == "bge-m3@fp16"
    root.post("/api/admin/jobs/embeddings")
    assert run_jobs(worker) == {"queue_missing_embeddings succeeded": 1}


def test_every_file_read_again(client: TestClient, db: Session, worker: App) -> None:
    root = Person(client, db, "root", admin=True)
    file_id = upload(Person(client, db, "ada"), make_pdf([[TYPED]]))
    run_jobs(worker)
    root.post("/api/admin/jobs/text-all")
    assert run_jobs(worker) == {
        "queue_pending_files succeeded": 1,
        "extract_text succeeded": 1,
        "embed_file succeeded": 1,
    }
    assert file_status(db, file_id) == (TextStatus.DONE, None)


def test_open_access_copies_and_published_versions(
    client: TestClient,
    db: Session,
    worker: App,
    settings: Settings,
    doi_registry: FakeDOIRegistry,
    web: FakeWeb,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(jobs, "OPEN_ACCESS_WAIT", timedelta(0))
    doi_registry.records[f"10.48550/arxiv.{ARXIV}"] = {
        "type": "article",
        "title": "Phonon-coupled hole-spin qubits in germanium",
    }
    doi_registry.records[JOURNAL_DOI] = {
        "type": "article-journal",
        "title": "Phonon-coupled hole-spin qubits in germanium",
        "container-title": "Quantum Science and Technology",
    }
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    paper = ada.post("/api/items", json={"doi": f"10.48550/arXiv.{ARXIV}"}).json()

    # Off by default: no copies by themselves; preprints are checked.
    defer(worker, "queue_open_access_sweep", timestamp=0)
    root.post("/api/admin/jobs/published")
    assert run_jobs(worker) == {
        "queue_open_access_sweep succeeded": 1,
        "find_published_versions succeeded": 1,
    }

    # Switched on: the arXiv PDF is added and read.
    configure(db, settings, open_access_auto=True)
    defer(worker, "queue_open_access_sweep", timestamp=0)
    assert run_jobs(worker) == {
        "queue_open_access_sweep succeeded": 1,
        "fetch_open_access succeeded": 1,
        "extract_text succeeded": 1,
        "embed_file succeeded": 1,
    }
    [preprint] = ada.get(f"/api/items/{paper['id']}").json()["versions"]
    assert len(preprint["files"]) == 1
    # Once it has its file, a repeated job does nothing.
    jobs.queue_open_access(worker, uuid.UUID(paper["id"]), None)
    jobs.queue_open_access(worker, uuid.uuid4(), None)
    assert run_jobs(worker) == {"fetch_open_access succeeded": 2}

    # Published in a journal, openly: its version comes with its PDF.
    web.published[ARXIV] = JOURNAL_DOI
    web.open_journal.add(JOURNAL_DOI)
    db.execute(update(Item).values(published_checked_at=None))
    db.commit()
    jobs.queue_published_check(worker)
    assert run_jobs(worker) == {
        "find_published_versions succeeded": 1,
        "fetch_open_access succeeded": 1,
        "extract_text succeeded": 1,
        "embed_file succeeded": 1,
    }
    detail = ada.get(f"/api/items/{paper['id']}").json()
    journal = next(v for v in detail["versions"] if v["kind"] == "published")
    assert len(journal["files"]) == 1

    configure(db, settings, find_published=False)
    jobs.queue_published_check(worker)
    assert run_jobs(worker) == {"find_published_versions succeeded": 1}


def at(hour: int) -> int:
    """A time at ten to the end of the hour (UTC), as a job's timestamp."""
    return int(datetime(2026, 11, 8, hour, 50, tzinfo=UTC).timestamp())


def test_maintenance_jobs(
    client: TestClient, db: Session, worker: App, settings: Settings
) -> None:
    root = Person(client, db, "root", admin=True)
    ada = Person(client, db, "ada")
    upload(ada, make_pdf([[TYPED]]))
    gone = ada.add("Gone")
    ada.delete(f"/api/items/{gone['id']}")
    db.execute(
        update(Item)
        .where(Item.deleted_at.is_not(None))
        .values(deleted_at=datetime.now(UTC) - timedelta(days=40))
    )
    db.commit()
    for job in ("trash", "integrity", "copy", "tidy"):
        root.post(f"/api/admin/jobs/{job}")
    ran = run_jobs(worker)
    assert ran["empty_trash succeeded"] == ran["check_integrity succeeded"] == 1
    assert ran["readable_copy succeeded"] == ran["tidy succeeded"] == 1
    # The trash is only emptied with a number of days set; no copy unless on.
    assert db.scalar(select(func.count()).select_from(Item)) == 2
    assert not settings.copy_path.exists()
    assert integrity.last_report(db) is not None

    configure(db, settings, trash_days=30, copy_enabled=True, night_hour=3)
    root.post("/api/admin/jobs/trash")
    root.post("/api/admin/jobs/copy")
    run_jobs(worker)
    db.expire_all()
    assert db.scalar(select(func.count()).select_from(Item)) == 1
    assert readable.last_report(db) is not None
    copied = list(settings.copy_path.rglob("*.pdf"))
    assert len(copied) == 1

    # At the night hour only, by the clock.
    copied[0].unlink()
    defer(worker, "nightly_readable_copy", timestamp=at(2))
    run_jobs(worker)
    assert not any(settings.copy_path.rglob("*.pdf"))
    defer(worker, "nightly_readable_copy", timestamp=at(3))
    assert run_jobs(worker) == {"nightly_readable_copy succeeded": 1}
    assert any(settings.copy_path.rglob("*.pdf"))

    root.post("/api/admin/jobs/copy-remove")
    run_jobs(worker)
    assert not any(settings.copy_path.rglob("*.pdf"))


def test_backups(
    client: TestClient, db: Session, worker: App, settings: Settings
) -> None:
    root = Person(client, db, "root", admin=True)
    upload(Person(client, db, "ada"), make_pdf([[TYPED]]))
    run_jobs(worker)
    assert root.post("/api/admin/backups", {"with_files": True}).is_success
    assert run_jobs(worker) == {"backup succeeded": 1}
    [backup] = list_backups(settings.backup_path)
    assert backup.with_files and backup.files == 1

    def scheduled_now() -> None:
        hour = datetime.now(UTC).hour
        config = BackupConfig(schedule="daily", hour=hour, with_files=False, keep=1)
        save_backup_config(db, config)
        db.commit()
        defer(worker, "scheduled_backup", timestamp=0)

    # On its schedule: not again within the day.
    scheduled_now()
    assert run_jobs(worker) == {"scheduled_backup succeeded": 1}
    (settings.backup_path / backup.name).rename(
        settings.backup_path / "2000-01-01T00-00-00Z"
    )
    manifest = settings.backup_path / "2000-01-01T00-00-00Z" / "manifest.json"
    manifest.write_text(
        manifest.read_text().replace(backup.created_at, "2000-01-01T00:00:00+00:00")
    )
    scheduled_now()
    assert run_jobs(worker) == {
        "scheduled_backup succeeded": 1,
        "backup succeeded": 1,
    }
    # One kept: the new one, without files.
    [newer] = list_backups(settings.backup_path)
    assert not newer.with_files and newer.name != "2000-01-01T00-00-00Z"


def test_imports(
    client: TestClient,
    db: Session,
    worker: App,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ada = Person(client, db, "ada")
    bib = b"@article{a, title={Radar gaps over the Alps}, year={2020}}\n"
    started = client.post(
        "/api/imports",
        headers=ada.headers,
        files={"upload": ("library.bib", bib, "text/plain")},
    ).json()
    assert run_jobs(worker) == {"import_library succeeded": 1}
    done = ada.get(f"/api/imports/{started['id']}").json()
    assert (done["status"], done["format"]) == ("done", "bibtex")
    assert ada.titles() == ["Radar gaps over the Alps"]

    # Done already, gone or without its upload: nothing to do.
    jobs.queue_import(worker, uuid.UUID(started["id"]), uuid.uuid4())
    jobs.queue_import(worker, uuid.uuid4(), uuid.uuid4())
    db.execute(update(Import).values(status=ImportStatus.WAITING, blob_sha256=None))
    db.commit()
    jobs.queue_import(worker, uuid.UUID(started["id"]), uuid.uuid4())
    assert run_jobs(worker) == {"import_library succeeded": 3}
    assert ada.titles() == ["Radar gaps over the Alps"]

    monkeypatch.setattr(settings, "max_import_bytes", len(bib) - 1)
    too_large = client.post(
        "/api/imports",
        headers=ada.headers,
        files={"upload": ("library.bib", bib, "text/plain")},
    )
    assert too_large.status_code == 413


def test_ml_settings_are_sent(
    db: Session, worker: App, fake_ml: FakeML, settings: Settings
) -> None:
    configure(db, settings, ml_threads=4, rerank="on")
    defer(worker, "configure_ml", timestamp=0)
    assert run_jobs(worker) == {"configure_ml succeeded": 1}
    assert fake_ml.config == {"threads": 4, "keep": ["bge-m3", "bge-reranker-v2-m3"]}

    # "auto": the reranker only with a GPU.
    configure(db, settings, rerank="auto")
    jobs.queue_ml_configuration(worker)
    run_jobs(worker)
    assert fake_ml.config["keep"] == ["bge-m3"]
    fake_ml.device = "cuda"
    jobs.queue_ml_configuration(worker)
    run_jobs(worker)
    assert fake_ml.config["keep"] == ["bge-m3", "bge-reranker-v2-m3"]

    # The ML service down: tried again in a minute.
    fake_ml.down = True
    jobs.queue_ml_configuration(worker)
    assert run_jobs(worker) == {"configure_ml succeeded": 1}


def test_starting_the_worker(
    settings: Settings, db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``paperus worker`` sets up its context and runs one worker per
    queue, as many jobs at once as the settings say."""
    configure(db, settings, jobs_text=3)
    monkeypatch.setattr(jobs, "_context", None)
    seen: list[dict[str, int]] = []

    async def run_workers(app: App, limits: Any) -> None:  # noqa: ANN401
        seen.append(limits())

    monkeypatch.setattr(jobs, "run_workers", run_workers)
    jobs.run_worker(settings)
    assert seen == [{"text": 3, "ml": 1, "ocr": 1, "import": 1, "backup": 1}]
    context = jobs._worker_context()
    assert context.settings is settings
    context.http.close()
    context.engine.dispose()


def test_jobs_of_a_stopped_worker_run_again(
    client: TestClient, db: Session, worker: App
) -> None:
    root = Person(client, db, "root", admin=True)
    file_id = upload(Person(client, db, "ada"), make_pdf([[TYPED]]))
    # Its worker was killed in the middle of reading the file.
    assert isinstance(worker.connector, InMemoryConnector)
    [job] = worker.connector.jobs.values()
    job.update(status="doing", worker_id=1)
    root.post("/api/admin/jobs/tidy")
    assert run_jobs(worker) == {
        "tidy succeeded": 1,
        "extract_text succeeded": 1,
        "embed_file succeeded": 1,
    }
    assert file_status(db, file_id) == (TextStatus.DONE, None)


def test_the_ml_service_switches_files_meanwhile(
    client: TestClient,
    db: Session,
    worker: App,
    fake_ml: FakeML,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Vectors are stored under the name the service sends with them, even
    if it ran another file of the model when asked before."""
    monkeypatch.setattr(ml, "VECTORS_TTL", 60)
    assert jobs._worker_context().ml.vectors_name("bge-m3") == "bge-m3"
    fake_ml.variant = "fp16"
    upload(Person(client, db, "ada"), make_pdf([[TYPED]]))
    run_jobs(worker)
    assert (embedded(db), embedded(db, "bge-m3@fp16")) == (0, 1)
