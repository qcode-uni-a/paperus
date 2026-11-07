"""MCP tools for tidying the library, as Manage in the website does:
duplicates, papers without details, unreadable files, missing PDFs, files,
tags, collections and the trash. Groups and their members are not for AI
assistants (tokens never manage people), and the trash is never emptied
here (that cannot be undone)."""

import re
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import CallToolResult, ToolAnnotations
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from paperus import duplicates, library, merge, metadata, missing, open_access
from paperus import organize as organizing
from paperus.access import Access
from paperus.api.files import read_again, replace_with_open_access, unreadable
from paperus.api.items import unsorted_conditions
from paperus.api.manage import manage_counts, progress_of, queue_all_open_access
from paperus.api.manage import next_to_a_pdf as beside_a_pdf
from paperus.identifiers import (
    InvalidIdentifier,
    Scheme,
    implied_by_doi,
    normalize,
)
from paperus.jobs import queue_text_extraction
from paperus.models import (
    Chunk,
    Collection,
    File,
    FileChunk,
    Group,
    Item,
    MetadataSource,
    Tag,
    Version,
)
from paperus.system import load_config, max_upload_bytes
from paperus.tokens import Scope

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)
WRITE = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, open_world_hint=False
)
# Changes that put something in the trash (it can be restored from there).
TRASHES = ToolAnnotations(
    read_only_hint=False, destructive_hint=True, open_world_hint=False
)
# Downloads from arXiv, OpenAlex, Unpaywall and DOI registries.
FETCHES = ToolAnnotations(
    read_only_hint=False, destructive_hint=False, open_world_hint=True
)

Acting = Callable[[Context, Scope], AbstractContextManager[tuple[Session, Access, str]]]
Json = Callable[[dict[str, Any] | list[Any]], CallToolResult]
Brief = Callable[[Item, Access, str], dict[str, Any]]

MAX_LIST = 100
# The scope each tool needs (for my_access).
TOOL_SCOPES = {
    "library_checkup": Scope.PAPERS_READ,
    "list_duplicates": Scope.PAPERS_READ,
    "merge_papers": Scope.PAPERS_WRITE,
    "not_duplicates": Scope.PAPERS_WRITE,
    "list_unsorted": Scope.PAPERS_READ,
    "set_doi": Scope.PAPERS_WRITE,
    "list_unreadable_files": Scope.PAPERS_READ,
    "retry_file": Scope.PAPERS_WRITE,
    "list_missing_pdfs": Scope.PAPERS_READ,
    "download_open_access": Scope.PAPERS_WRITE,
    "mark_file_not_needed": Scope.PAPERS_WRITE,
    "download_all_open_access": Scope.PAPERS_WRITE,
    "open_access_progress": Scope.PAPERS_READ,
    "list_files": Scope.PAPERS_READ,
    "trash_files": Scope.PAPERS_WRITE,
    "restore_files": Scope.PAPERS_WRITE,
    "archive_papers": Scope.PAPERS_WRITE,
    "remove_tags": Scope.TAGS_WRITE,
    "rename_tag": Scope.TAGS_WRITE,
    "create_collection": Scope.COLLECTIONS_WRITE,
    "add_to_collection": Scope.COLLECTIONS_WRITE,
    "remove_from_collection": Scope.COLLECTIONS_WRITE,
    "list_trash": Scope.PAPERS_READ,
    "restore_papers": Scope.PAPERS_WRITE,
}
EXCERPT = 800


def register(
    mcp: MCPServer,
    acting: Acting,
    state: Any,  # noqa: ANN401 (the app's state)
    json: Json,
    brief: Brief,
) -> None:
    """Add the tidying tools to the MCP server."""

    def described(item: Item, access: Access, base: str) -> dict[str, Any]:
        """A paper with what tells duplicates apart."""
        files = [f for v in item.versions for f in v.files if f.deleted_at is None]
        return {
            **brief(item, access, base),
            "identifiers": sorted(
                {f"{i.scheme}:{i.value}" for v in item.versions for i in v.identifiers}
            ),
            "versions": [v.kind for v in item.versions],
            "files": [f.filename for f in files],
        }

    @mcp.tool(annotations=READ)
    def library_checkup(ctx: Context) -> CallToolResult:
        """What needs tidying in the library (as Manage in the website):
        possible duplicates, papers whose details are only guessed from
        their file, files whose text could not be read, papers without a
        PDF or with only their preprint's, saved web pages next to a PDF,
        and the trash; each with the tool to look at it."""
        with acting(ctx, Scope.PAPERS_READ) as (db, access, _):
            counts = manage_counts(db, access)
            trash = db.scalar(
                select(func.count())
                .select_from(Item)
                .where(Item.deleted_at.is_not(None), access.item_filter())
            )
            return json(
                {
                    "possible_duplicates": {
                        "count": counts.duplicates,
                        "tools": "list_duplicates, merge_papers, not_duplicates",
                    },
                    "papers_without_details": {
                        "count": counts.unsorted,
                        "tools": "list_unsorted, set_doi",
                    },
                    "unreadable_files": {
                        "count": counts.unreadable,
                        "tools": "list_unreadable_files, retry_file",
                    },
                    "papers_without_pdf": {
                        "count": counts.missing,
                        "tools": "list_missing_pdfs, download_open_access, "
                        "mark_file_not_needed",
                    },
                    "papers_with_only_their_preprint": {
                        "count": counts.missing_journal,
                        "tools": "list_missing_pdfs(section='journal'), "
                        "download_open_access(journal=true)",
                    },
                    "web_pages_next_to_a_pdf": {
                        "count": counts.snapshots,
                        "tools": "list_files(media_types=['text/html', "
                        "'application/xhtml+xml'], next_to_a_pdf=true), "
                        "trash_files",
                    },
                    "trash": {
                        "count": trash or 0,
                        "tools": "list_trash, restore_papers",
                    },
                }
            )

    # Duplicates

    @mcp.tool(annotations=READ)
    def list_duplicates(ctx: Context, limit: int = 20) -> CallToolResult:
        """Pairs that look like the same paper twice (same DOI or arXiv ID,
        or the same title and first author): which one paperus would keep
        and why, and what tells them apart. Merge with merge_papers, or
        keep both with not_duplicates; ask the person first."""
        with acting(ctx, Scope.PAPERS_READ) as (db, access, base):
            pairs = duplicates.find(db, access, limit=min(limit, MAX_LIST))
            return json(
                [
                    {
                        "keep": described(pair.keep, access, base),
                        "other": described(pair.merge, access, base),
                        "same": list(pair.reasons),
                        "why_keep": pair.why,
                        "can_merge": pair.can_merge,
                    }
                    for pair in pairs
                ]
            )

    @mcp.tool(annotations=TRASHES)
    def merge_papers(keep_id: str, other_id: str, ctx: Context) -> CallToolResult:
        """Merge a duplicate into the paper that stays: the other one's
        versions, files, tags, collections and notes move over (what the
        kept one has already stays once) and the other goes to the trash
        (restore_papers brings it back). Ask the person first, naming both."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, base):
            keep = find_paper(db, access, keep_id)
            other = find_paper(db, access, other_id, write=True)
            try:
                steps = merge.merge_items(db, access, other, keep)
            except merge.CannotMerge as error:
                raise ToolError(str(error)) from error
            db.commit()
            db.refresh(keep)
            return json(
                {
                    "kept": brief(keep, access, base),
                    "done": [
                        f"{s.kind} {s.name}: {s.action}"
                        + (f" ({s.reason})" if s.reason else "")
                        for s in steps
                    ],
                }
            )

    @mcp.tool(annotations=WRITE)
    def not_duplicates(paper_a: str, paper_b: str, ctx: Context) -> CallToolResult:
        """Two papers that only look alike: they are not suggested as
        duplicates again (for everyone who sees both)."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, _):
            a, b = find_paper(db, access, paper_a), find_paper(db, access, paper_b)
            if not (access.can_write_item(a) or access.can_write_item(b)):
                raise ToolError("You may change neither of them.")
            duplicates.dismiss(db, a.id, b.id, access.user.id)
            db.commit()
            return json({"kept_apart": [str(a.id), str(b.id)]})

    # Papers without details

    @mcp.tool(annotations=READ)
    def list_unsorted(ctx: Context, limit: int = 20) -> CallToolResult:
        """Papers whose details are only guessed from their file (no DOI or
        arXiv ID was found in it), with the file's name and the beginning of
        its text, to recognise the paper. Give each its DOI or arXiv ID with
        set_doi (ask the person first)."""
        with acting(ctx, Scope.PAPERS_READ) as (db, access, base):
            items = db.scalars(
                select(Item)
                .where(
                    access.item_filter(),
                    Item.deleted_at.is_(None),
                    Item.archived_at.is_(None),
                    *unsorted_conditions(),
                )
                .order_by(Item.id.desc())
                .limit(min(limit, MAX_LIST))
            ).unique()
            result = []
            for item in items:
                file = _first_pdf(item)
                result.append(
                    {
                        **brief(item, access, base),
                        "file": file.filename if file else None,
                        "beginning": _beginning(db, file) if file else None,
                    }
                )
            return json(result)

    @mcp.tool(annotations=FETCHES)
    def set_doi(paper_id: str, doi: str, ctx: Context) -> CallToolResult:
        """Look up a paper's details by its DOI (or arXiv ID, e.g.
        2401.12345): they become its shown details (as a version of it).
        If another paper has that DOI already, the answer says so: merge
        them instead. Ask the person first."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, base):
            item = find_paper(db, access, paper_id, write=True)
            try:
                value = normalize(Scheme.DOI, _as_doi(doi))
            except InvalidIdentifier as error:
                raise ToolError(str(error)) from error
            identifiers = [(Scheme.DOI, value), *implied_by_doi(value)]
            known = library.find_identifier(db, access.readable, identifiers)
            if known is not None:
                if known.version.item_id == item.id:
                    return json({**brief(item, access, base), "unchanged": True})
                raise ToolError(
                    f"Paper {known.version.item_id} has {value} already: merge "
                    "the two with merge_papers."
                )
            try:
                csl, kind = metadata.lookup_doi(state.http, value)
            except metadata.DOINotFound as error:
                raise ToolError(f"No paper has the DOI {value}.") from error
            except metadata.MetadataUnavailable as error:
                raise ToolError(
                    "The DOI registry did not answer; try later."
                ) from error
            try:
                library.add_version(
                    db,
                    item,
                    kind=kind,
                    label=None,
                    csl=csl,
                    source=MetadataSource.LOOKUP,
                    identifiers=identifiers,
                    created_by=access.user.id,
                )
            except library.IdentifierTaken as error:
                raise ToolError(str(error)) from error
            db.commit()
            db.refresh(item)
            return json(brief(item, access, base))

    # Unreadable files

    @mcp.tool(annotations=READ)
    def list_unreadable_files(ctx: Context) -> CallToolResult:
        """Files whose text could not be read (so search cannot find them),
        with why. retry_file reads one again, or replaces it with a fresh
        open-access copy."""
        with acting(ctx, Scope.PAPERS_READ) as (db, access, base):
            email = load_config(db, state.settings).contact_email
            return json(
                [
                    {
                        "file_id": str(file.id),
                        "filename": file.filename,
                        "error": file.text_error,
                        "paper": brief(item, access, base),
                        "fresh_copy_possible": bool(open_access.sources(item, email)),
                    }
                    for file, item in unreadable(db, access)
                ]
            )

    @mcp.tool(annotations=FETCHES)
    def retry_file(
        file_id: str, ctx: Context, download: bool = False
    ) -> CallToolResult:
        """Read a file's text again (e.g. after an update of paperus); with
        download=true, replace it first with a fresh open-access copy of its
        paper (arXiv, or a copy Unpaywall knows), e.g. for a damaged PDF.
        Ask the person first."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, _):
            file = readable_file(db, access, file_id)
            if file is None:
                raise ToolError("No such file.")
            if not access.can_write_item(file.version.item):
                raise ToolError("You may not change this paper's files.")
            if download:
                try:
                    replace_with_open_access(db, state, file)
                except open_access.NoSource as error:
                    raise ToolError(f"No good copy found: {error}") from error
                return json({"file_id": str(file.id), "replaced": True})
            read_again(db, file)
            queue_text_extraction(state.jobs, file.id)
            return json({"file_id": str(file.id), "reading": True})

    # Missing PDFs

    @mcp.tool(annotations=READ)
    def list_missing_pdfs(
        ctx: Context, section: str = "file", limit: int = 30
    ) -> CallToolResult:
        """Papers without a PDF (section="file"), or published papers with
        only their preprint's PDF (section="journal"), or those marked as
        needing no file (section="not_needed", to undo that); whether an
        open copy may be found, and the last try (when, and why it found
        none). download_open_access gets one, download_all_open_access all
        of a section in the background; mark_file_not_needed takes a paper
        off the list (a web page, a book on the shelf). PDFs behind a
        login: the person can get them with the paperus browser extension
        (Manage → Missing)."""
        hidden = section == "not_needed"
        which = "file" if hidden else _section(section)
        with acting(ctx, Scope.PAPERS_READ) as (db, access, base):
            email = load_config(db, state.settings).contact_email
            conditions = (
                missing.hidden_conditions() if hidden else missing.conditions(which)
            )
            items = db.scalars(
                select(Item)
                .where(access.item_filter(), *conditions)
                .order_by(Item.id.desc())
                .limit(min(limit, MAX_LIST))
            ).unique()
            result = []
            for item in items:
                possible = (
                    missing.journal_doi(item) is not None
                    if which == "journal"
                    else missing.may_have_copy(item, email)
                )
                result.append(
                    {
                        **brief(item, access, base),
                        "doi": missing.journal_doi(item)
                        or next(
                            (
                                i.value
                                for v in item.versions
                                for i in v.identifiers
                                if i.scheme == Scheme.DOI
                            ),
                            None,
                        ),
                        "open_copy_possible": possible,
                        "last_tried": item.open_access_tried_at.isoformat()
                        if item.open_access_tried_at
                        else None,
                        "last_try": missing.plain_reason(item.open_access_error, email),
                    }
                )
            return json(result)

    @mcp.tool(annotations=FETCHES)
    def download_open_access(
        paper_id: str, ctx: Context, journal: bool = False
    ) -> CallToolResult:
        """Get a paper's PDF where it is open: the journal's own copy, else
        its arXiv version (found by the DOI; added as the paper's preprint
        version), else one Unpaywall knows. journal=true: only the journal's
        own copy (for papers with only their preprint's PDF). Ask the person
        first."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, _):
            item = find_paper(db, access, paper_id, write=True)
            add = missing.add_journal_copy if journal else missing.add_open_access
            file = add(
                db,
                state.http,
                state.blobs,
                item,
                contact_email=load_config(db, state.settings).contact_email,
                max_bytes=max_upload_bytes(db, state.settings),
                user_id=access.user.id,
            )
            if file is None:
                raise ToolError(f"No open copy found: {item.open_access_error}")
            queue_text_extraction(state.jobs, file.id)
            return json({"paper_id": str(item.id), "file": file.filename})

    @mcp.tool(annotations=WRITE)
    def mark_file_not_needed(
        paper_ids: list[str], ctx: Context, needed: bool = False
    ) -> CallToolResult:
        """Papers that need no (further) PDF (a web page, a book on the
        shelf, a preprint that is enough): off the missing list; needed=true
        puts them back."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, _):
            changed = []
            for paper_id in paper_ids[:MAX_LIST]:
                item = find_paper(db, access, paper_id, write=True)
                item.file_wanted = needed
                changed.append(str(item.id))
            db.commit()
            return json({"changed": changed, "file_needed": needed})

    @mcp.tool(annotations=FETCHES)
    def download_all_open_access(ctx: Context, section: str = "file") -> CallToolResult:
        """Look for open copies of all papers of a section ("file": without
        a PDF; "journal": with only their preprint's) in the background, as
        Manage → Missing → "Download all" does; papers tried in the last day
        are left out. Returns the papers queued and when; follow with
        open_access_progress. Ask the person first."""
        which = _section(section)
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, _):
            queued, started_at = queue_all_open_access(db, access, state, which)
            return json(
                {
                    "queued": len(queued),
                    "paper_ids": [str(item_id) for item_id in queued],
                    "started_at": started_at.isoformat(),
                }
            )

    @mcp.tool(annotations=READ)
    def open_access_progress(
        paper_ids: list[str], started_at: str, ctx: Context, section: str = "file"
    ) -> CallToolResult:
        """How far download_all_open_access has got: of these papers, how
        many were tried since started_at, how many got their PDF, and why the
        others did not. If none moves for minutes, the server's worker may
        not be running."""
        which = _section(section)
        try:
            since = datetime.fromisoformat(started_at)
        except ValueError as error:
            raise ToolError(
                "started_at as download_all_open_access gave it."
            ) from error
        ids = [parse_id(paper_id) for paper_id in paper_ids[:10_000]]
        with acting(ctx, Scope.PAPERS_READ) as (db, access, _):
            email = load_config(db, state.settings).contact_email
            progress = progress_of(db, access, ids, since, which, email)
            return json(
                {
                    "papers": len(ids),
                    "tried": progress.tried,
                    "found": progress.found,
                    "not_found": [
                        {"paper_id": str(n.item_id), "title": n.title, "why": n.reason}
                        for n in progress.not_found
                    ],
                }
            )

    # Files

    @mcp.tool(annotations=READ)
    def list_files(
        ctx: Context,
        media_types: list[str] | None = None,
        next_to_a_pdf: bool = False,
        in_trash: bool = False,
        limit: int = 30,
    ) -> CallToolResult:
        """Files of the papers the person can see, newest first, with their
        paper and the total count: optionally only some media types
        ("text/html", or "image/" for all images); next_to_a_pdf=true: only
        files that sit next to a PDF of the same version (supplements, but
        also copies such as a saved web page repeating the abstract);
        in_trash=true: files moved to the trash. trash_files and
        restore_files act on them; get_document lists one paper's files."""
        with acting(ctx, Scope.PAPERS_READ) as (db, access, base):
            conditions = [
                File.deleted_at.is_not(None) if in_trash else File.deleted_at.is_(None),
                Item.deleted_at.is_(None),
                access.item_filter(),
            ]
            if media_types:
                conditions.append(
                    or_(
                        *(
                            File.media_type.startswith(kind)
                            if kind.endswith("/")
                            else File.media_type == kind
                            for kind in media_types
                        )
                    )
                )
            if next_to_a_pdf:
                conditions.append(beside_a_pdf())
            query = (
                select(File)
                .join(Version, Version.id == File.version_id)
                .join(Item, Item.id == Version.item_id)
                .where(*conditions)
            )
            count = db.scalar(select(func.count()).select_from(query.subquery()))
            files = db.scalars(
                query.order_by(File.created_at.desc(), File.id).limit(
                    min(limit, MAX_LIST)
                )
            )
            return json(
                {
                    "count": count or 0,
                    "files": [
                        {
                            "file_id": str(file.id),
                            "filename": file.filename,
                            "media_type": file.media_type,
                            "role": file.role,
                            "bytes": file.blob.size,
                            "paper": brief(file.version.item, access, base),
                        }
                        for file in files
                    ],
                }
            )

    def own_files(db: Session, access: Access, file_ids: list[str]) -> list[File]:
        """Files of papers (not in the trash) the person may change."""
        found = []
        for file_id in file_ids[:MAX_LIST]:
            file = db.get(File, parse_id(file_id))
            item = file.version.item if file else None
            if (
                file is None
                or item is None
                or item.deleted_at is not None
                or not access.can_read_item(item)
            ):
                raise ToolError(f"No such file: {file_id}.")
            if not access.can_write_item(item):
                raise ToolError(
                    f"You may not change the files of “{item.title}” (you only "
                    "read it)."
                )
            found.append(file)
        return found

    @mcp.tool(annotations=TRASHES)
    def trash_files(file_ids: list[str], ctx: Context) -> CallToolResult:
        """Move files to the trash (their papers stay; restore_files brings
        them back). Ask the person first, naming the files."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, _):
            files = own_files(db, access, file_ids)
            for file in files:
                library.trash(file, access.user.id)
            db.commit()
            return json({"trashed": [str(file.id) for file in files]})

    @mcp.tool(annotations=WRITE)
    def restore_files(file_ids: list[str], ctx: Context) -> CallToolResult:
        """Bring files back from the trash (list_files(in_trash=true) lists
        them)."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, _):
            files = own_files(db, access, file_ids)
            for file in files:
                library.restore(file)
            db.commit()
            return json({"restored": [str(file.id) for file in files]})

    @mcp.tool(annotations=WRITE)
    def archive_papers(
        paper_ids: list[str], ctx: Context, archived: bool = True
    ) -> CallToolResult:
        """Put papers in the archive: kept, but left out of lists, search
        and Manage (for everyone who sees them); archived=false takes them
        out again. list_documents(archived=true) lists the archive."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, _):
            changed = []
            for paper_id in paper_ids[:MAX_LIST]:
                item = find_paper(db, access, paper_id, write=True)
                if (item.archived_at is not None) != archived:
                    item.archived_at = datetime.now(UTC) if archived else None
                changed.append(str(item.id))
            db.commit()
            return json({"changed": changed, "archived": archived})

    # Tags

    def own_tag(db: Session, access: Access, name: str, group: str | None) -> Tag:
        """The tag of this name the person may change (theirs, or a group's
        they are a member of; ``group`` decides if both have one)."""
        libraries = access.writable
        if group is not None:
            wanted = group_library(db, access, group)
            libraries = [lib for lib in libraries if lib == wanted]
        found = db.scalars(
            select(Tag).where(
                Tag.library_id.in_(libraries),
                func.lower(Tag.name) == organizing.clean_name(name).lower(),
            )
        ).all()
        if not found:
            raise ToolError(f"You have no tag “{name}” you may change.")
        if len(found) > 1:
            raise ToolError(
                f"Several tags are called “{name}”: say which group's (group=…)."
            )
        return found[0]

    @mcp.tool(annotations=WRITE)
    def remove_tags(
        paper_ids: list[str], tags: list[str], ctx: Context
    ) -> CallToolResult:
        """Take tags off papers (the tags stay for other papers). Ask the
        person first."""
        with acting(ctx, Scope.TAGS_WRITE) as (db, access, base):
            names = {organizing.clean_name(t).lower() for t in tags}
            result = []
            for paper_id in paper_ids[:MAX_LIST]:
                item = find_paper(db, access, paper_id)
                for link in list(item.tag_links):
                    if link.tag.name.lower() not in names:
                        continue
                    if not access.can_write(link.tag.library_id):
                        raise ToolError(
                            f"You may not change the tag “{link.tag.name}”."
                        )
                    organizing.untag_item(item, link.tag_id)
                result.append(brief(item, access, base))
            db.commit()
            return json(result)

    @mcp.tool(annotations=WRITE)
    def rename_tag(
        name: str, new_name: str, ctx: Context, group: str | None = None
    ) -> CallToolResult:
        """Rename a tag on all its papers. If a tag of the new name exists
        already (of the same owner), the two become one (e.g. "quantum" into
        "Quantum Physics"). group: whose tag, when several are called
        alike. Ask the person first."""
        with acting(ctx, Scope.TAGS_WRITE) as (db, access, _):
            tag = own_tag(db, access, name, group)
            other = organizing.find_tag(db, tag.library_id, new_name)
            if other is not None and other.id != tag.id:
                papers = organizing.merge_tags(db, tag, other)
                db.commit()
                return json({"merged_into": other.name, "papers_added": papers})
            organizing.rename_tag(db, tag, new_name)
            db.commit()
            return json({"renamed": tag.name})

    # Collections

    def collection(db: Session, access: Access, name_or_id: str) -> Collection:
        try:
            found = db.get(Collection, uuid.UUID(name_or_id))
            matches = [found] if found is not None else []
        except ValueError:
            matches = list(
                db.scalars(
                    select(Collection).where(
                        Collection.library_id.in_(access.readable),
                        func.lower(Collection.name) == name_or_id.strip().lower(),
                    )
                )
            )
        matches = [c for c in matches if access.can_read(c.library_id)]
        if not matches:
            raise ToolError(f"No collection “{name_or_id}” (see list_collections).")
        if len(matches) > 1:
            raise ToolError(
                f"Several collections are called “{name_or_id}”: use its "
                "collection_id from list_collections."
            )
        return matches[0]

    @mcp.tool(annotations=WRITE)
    def create_collection(
        name: str, ctx: Context, inside: str | None = None, group: str | None = None
    ) -> CallToolResult:
        """A new collection: the person's own, a group's (group=its name), or
        inside another one (inside=its name or id). Ask the person first."""
        with acting(ctx, Scope.COLLECTIONS_WRITE) as (db, access, _):
            try:
                clean = organizing.clean_name(name)
            except ValueError as error:
                raise ToolError(str(error)) from error
            parent = collection(db, access, inside) if inside else None
            if parent is not None:
                library_id = parent.library_id
                if parent.rules is not None:
                    raise ToolError("A smart collection holds no other collections.")
            elif group is not None:
                library_id = group_library(db, access, group)
            else:
                library_id = access.own_library
            if not access.can_write(library_id):
                raise ToolError("You may not add collections there.")
            made = Collection(
                library_id=library_id,
                name=clean,
                parent_id=parent.id if parent else None,
                created_by=access.user.id,
                change=0,
            )
            db.add(made)
            db.commit()
            return json({"collection_id": str(made.id), "name": made.name})

    @mcp.tool(annotations=WRITE)
    def add_to_collection(
        paper_ids: list[str], collection_name: str, ctx: Context
    ) -> CallToolResult:
        """Put papers into a collection (its name or collection_id); a
        group's collection takes only the group's papers. Ask the person
        first."""
        with acting(ctx, Scope.COLLECTIONS_WRITE) as (db, access, _):
            target = collection(db, access, collection_name)
            if not access.can_write(target.library_id):
                raise ToolError("You may not change this collection.")
            if target.rules is not None:
                raise ToolError("A smart collection finds its papers by its rules.")
            items = [find_paper(db, access, p) for p in paper_ids[:MAX_LIST]]
            added = organizing.add_to_collection(
                db,
                target,
                [i.id for i in items],
                access.user.id,
                may_hold=lambda item: access.may_hold(target.library_id, item),
            )
            db.commit()
            return json({"collection": target.name, "added": added})

    @mcp.tool(annotations=WRITE)
    def remove_from_collection(
        paper_ids: list[str], collection_name: str, ctx: Context
    ) -> CallToolResult:
        """Take papers out of a collection (they stay in the library). Ask
        the person first."""
        with acting(ctx, Scope.COLLECTIONS_WRITE) as (db, access, _):
            target = collection(db, access, collection_name)
            if not access.can_write(target.library_id):
                raise ToolError("You may not change this collection.")
            removed = 0
            for paper_id in paper_ids[:MAX_LIST]:
                item = find_paper(db, access, paper_id)
                before = len(item.collection_links)
                item.collection_links = [
                    link
                    for link in item.collection_links
                    if link.collection_id != target.id
                ]
                removed += before - len(item.collection_links)
            db.commit()
            return json({"collection": target.name, "removed": removed})

    # Trash

    @mcp.tool(annotations=READ)
    def list_trash(ctx: Context, limit: int = 30) -> CallToolResult:
        """Papers in the trash, most recently trashed first (e.g. merged
        duplicates). They are deleted for good after the trash days set by
        the administrator; restore_papers brings them back."""
        with acting(ctx, Scope.PAPERS_READ) as (db, access, base):
            items = db.scalars(
                select(Item)
                .where(Item.deleted_at.is_not(None), access.item_filter())
                .order_by(Item.deleted_at.desc())
                .limit(min(limit, MAX_LIST))
            ).unique()
            return json(
                [
                    {**brief(item, access, base), "trashed": str(item.deleted_at)}
                    for item in items
                ]
            )

    @mcp.tool(annotations=WRITE)
    def restore_papers(paper_ids: list[str], ctx: Context) -> CallToolResult:
        """Take papers out of the trash. Ask the person first."""
        with acting(ctx, Scope.PAPERS_WRITE) as (db, access, base):
            restored = []
            for paper_id in paper_ids[:MAX_LIST]:
                item = find_paper(db, access, paper_id, write=True, trashed=True)
                library.restore(item)
                restored.append(brief(item, access, base))
            db.commit()
            return json(restored)


# Lookups shared with paperus.mcp_server: a ToolError for what the person
# may not see, as if it did not exist.


def parse_id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as error:
        raise ToolError(f"Not an id: {value!r}.") from error


def find_paper(
    db: Session,
    access: Access,
    paper_id: str,
    *,
    write: bool = False,
    trashed: bool = False,
) -> Item:
    """A paper the person may read (``write``: change), not in the trash
    (``trashed``: also one in the trash)."""
    item = db.get(Item, parse_id(paper_id))
    if (
        item is None
        or not access.can_read_item(item)
        or (item.deleted_at is not None and not trashed)
    ):
        raise ToolError(f"No such paper: {paper_id}.")
    if write and not access.can_write_item(item):
        raise ToolError(f"You may not change “{item.title}” (you only read it).")
    return item


def readable_file(db: Session, access: Access, file_id: str) -> File | None:
    """The file, if neither it nor its paper is in the trash and the person
    may read it."""
    file = db.get(File, parse_id(file_id))
    if file is None or file.deleted_at is not None:
        return None
    item = file.version.item
    return file if item.deleted_at is None and access.can_read_item(item) else None


def group_library(db: Session, access: Access, name: str) -> uuid.UUID:
    """The library of the person's group of this name."""
    for group in db.scalars(
        select(Group).where(Group.id.in_(list(access.group_libraries)))
    ):
        if group.name.casefold() == name.strip().casefold():
            return access.group_libraries[group.id]
    raise ToolError(f"The person is in no group called {name!r}.")


def _section(value: str) -> missing.Section:
    if value not in ("file", "journal"):
        raise ToolError('section is "file" or "journal".')
    return "journal" if value == "journal" else "file"


def _as_doi(text: str) -> str:
    """A DOI, a doi.org link, or an arXiv ID (as its DOI)."""
    value = text.strip()
    arxiv = re.match(r"^(?:arxiv:\s*)?(\d{4}\.\d{4,5})(v\d+)?$", value, re.IGNORECASE)
    return f"10.48550/arXiv.{arxiv[1]}" if arxiv else value


def _first_pdf(item: Item) -> File | None:
    return next(
        (
            f
            for v in item.versions
            for f in v.files
            if f.deleted_at is None and f.media_type == "application/pdf"
        ),
        None,
    )


def _beginning(db: Session, file: File) -> str | None:
    """The first passages of the file's text: title, authors, abstract."""
    texts = db.scalars(
        select(Chunk.text)
        .join(FileChunk, FileChunk.chunk_sha256 == Chunk.sha256)
        .where(FileChunk.file_id == file.id)
        .order_by(FileChunk.position)
        .limit(3)
    ).all()
    text = "\n\n".join(texts)
    return text[:EXCERPT] if text else None
