"""arXiv's versions of a preprint (v1, v2, …) as versions of the paper: a
PDF named with its arXiv version, as arXiv gives it ("2401.12345v3.pdf"),
goes to the paper's preprint labelled "v3", made if there is none (the
preprint without a label takes it, if it has no PDF of another version
yet). The newest is cited unless a published version is there
(``library.preferred_of``). A hook on the session, so every way a file
arrives counts (uploads, the browser extension, open-access copies,
imports)."""

import re

from sqlalchemy import event
from sqlalchemy.orm import Session, UOWTransaction

from paperus import library
from paperus.identifiers import Scheme
from paperus.models import File, FileRole, Item, Version, VersionKind

PDF = "application/pdf"


def label_of(filename: str, item: Item) -> str | None:
    """ "v3" for a file named after one of the paper's arXiv IDs with a
    version ("2401.12345v3.pdf", "hep-th_9901001v2.pdf"), else None."""
    stem = re.sub(r"\.pdf$", "", filename.strip().lower())
    for version in item.versions:
        for identifier in version.identifiers:
            if identifier.scheme != Scheme.ARXIV:
                continue
            number = re.escape(identifier.value.split("/")[-1])
            match = re.search(rf"(?:^|[^0-9.]){number}v(\d+)$", stem)
            if match:
                return f"v{int(match.group(1))}"
    return None


def _has_other_pdf(version: Version, file: File) -> bool:
    return any(
        f is not file
        and f.deleted_at is None
        and f.media_type == PDF
        and f.role == FileRole.MAIN
        for f in version.files
    )


def place(db: Session, file: File) -> None:
    """A new PDF of one of arXiv's versions: to the paper's version of it."""
    version = file.version
    if version is None or file.media_type != PDF or file.role != FileRole.MAIN:
        return
    item = version.item
    label = label_of(file.filename, item)
    if item is None or label is None:
        return
    # arXiv's: the preprints, and the version with its ID (whatever kind).
    preprints = [
        v
        for v in item.versions
        if v.kind == VersionKind.PREPRINT
        or any(i.scheme == Scheme.ARXIV for i in v.identifiers)
    ]
    target = next((v for v in preprints if v.label == label), None)
    if target is None:
        # The preprint without arXiv's version yet, if it has no PDF of
        # another one: it is this one.
        bare = next(
            (
                v
                for v in preprints
                if not library.arxiv_number(v.label) and not _has_other_pdf(v, file)
            ),
            None,
        )
        if bare is not None:
            bare.label = label
            target = bare
    if target is None:
        # Another of arXiv's versions: a preprint of its own, with the
        # details of the preprint there is (arXiv's ID stays with that one).
        like = max(preprints, key=lambda v: library.arxiv_number(v.label), default=None)
        target = Version(
            kind=VersionKind.PREPRINT,
            label=label,
            csl=dict(like.csl) if like else dict(version.csl),
            metadata_source=(like or version).metadata_source,
            created_by=file.uploaded_by,
        )
        item.versions.append(target)
        db.add(target)
    if target is not version:
        file.version = target
        db.add(file)
    library.refresh_item(item)


@event.listens_for(Session, "before_flush")
def _place_new_files(db: Session, flush: UOWTransaction, instances: object) -> None:
    for obj in list(db.new):
        if isinstance(obj, File):
            place(db, obj)
