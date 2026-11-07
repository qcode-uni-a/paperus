"""Zotero RDF (Zotero's own export, with files and notes) into the common form.

Read as an RDF graph, so it does not depend on how the XML is laid out.
The structure follows Zotero's export: items with ``z:itemType``, journal
details on a ``dcterms:isPartOf`` container, creators in sequences of
``foaf:Person``, tags as ``dc:subject``, child notes (``bib:Memo``) via
``dcterms:isReferencedBy``, files (``z:Attachment`` with ``z:path``) via
``link:link``, and collections (``z:Collection``) with ``dcterms:hasPart``.
Files without a paper (a ``z:Attachment`` nothing links to) become papers
of type "document".
Only the structure is taken from Zotero's translator (AGPL), not its code.
"""

import re
from typing import Any
from urllib.parse import unquote

from markdownify import markdownify
from rdflib import RDF, Graph, Literal, Namespace, URIRef
from rdflib.term import Node

from paperus.importing import Export, ExportedFile, ExportedNote, ExportedPaper
from paperus.importing.common import date_parts, identifiers_of

Z = Namespace("http://www.zotero.org/namespaces/export#")
DC = Namespace("http://purl.org/dc/elements/1.1/")
DCTERMS = Namespace("http://purl.org/dc/terms/")
BIB = Namespace("http://purl.org/net/biblio#")
FOAF = Namespace("http://xmlns.com/foaf/0.1/")
LINK = Namespace("http://purl.org/rss/1.0/modules/link/")
PRISM = Namespace("http://prismstandard.org/namespaces/1.2/basic/")
VCARD = Namespace("http://nwalsh.com/rdf/vCard#")

# Relative references (files/12/x.pdf, #item_3) are resolved against this.
BASE = "http://export.invalid/"

# Zotero item type → CSL type (as Zotero's own CSL mapping does).
_TYPES = {
    "journalArticle": "article-journal",
    "magazineArticle": "article-magazine",
    "newspaperArticle": "article-newspaper",
    "book": "book",
    "bookSection": "chapter",
    "conferencePaper": "paper-conference",
    "thesis": "thesis",
    "report": "report",
    "preprint": "article",
    "manuscript": "manuscript",
    "webpage": "webpage",
    "blogPost": "post-weblog",
    "forumPost": "post",
    "encyclopediaArticle": "entry-encyclopedia",
    "dictionaryEntry": "entry-dictionary",
    "patent": "patent",
    "presentation": "speech",
    "computerProgram": "software",
    "dataset": "dataset",
    "letter": "personal_communication",
    "email": "personal_communication",
    "interview": "interview",
    "film": "motion_picture",
    "videoRecording": "motion_picture",
    "audioRecording": "song",
    "podcast": "song",
    "radioBroadcast": "broadcast",
    "tvBroadcast": "broadcast",
    "artwork": "graphic",
    "map": "map",
    "case": "legal_case",
    "statute": "legislation",
    "bill": "bill",
    "hearing": "hearing",
    "standard": "standard",
    "document": "document",
}
# Creator properties → CSL roles (others, e.g. z:translators, by name).
_ROLES = {
    BIB.authors: "author",
    BIB.editors: "editor",
    BIB.contributors: "contributor",
    Z.translators: "translator",
    Z.seriesEditors: "collection-editor",
    Z.bookAuthors: "container-author",
    Z.directors: "director",
    Z.interviewers: "interviewer",
    Z.recipients: "recipient",
    Z.reviewedAuthors: "reviewed-author",
}


def read(text: str) -> Export:
    export = Export(format="zotero-rdf")
    # Zotero never declares entities; nested ones make the parser take
    # hours on a tiny file ("billion laughs"), so they are refused.
    if re.search(r"<!(DOCTYPE|ENTITY)", text[: text.find("<rdf:RDF") + 1 or None]):
        export.problems.append(
            "The file declares XML entities, which Zotero never does; not read."
        )
        return export
    graph = Graph()
    # Zotero has written file paths as <rdf:resource rdf:resource="files/…"/>,
    # which RDF/XML does not allow as a property; it means z:path.
    text = re.sub(r"<rdf:resource(\s)", r"<z:path\1", text)
    try:
        graph.parse(data=text, format="xml", publicID=BASE)
    except Exception as error:
        export.problems.append(f"The file could not be read as Zotero RDF: {error}")
        return export
    reader = _Reader(graph)
    export.collections, member_of = reader.collections()
    attached = set(graph.objects(None, LINK.link))
    for subject in sorted(set(graph.subjects(Z.itemType, None)), key=str):
        kind = str(graph.value(subject, Z.itemType))
        if kind == "attachment":
            # A file on its own in Zotero (no paper around it): a paper of
            # its own, or it would be lost.
            if subject not in attached and (alone := reader.standalone(subject)):
                alone.collections = member_of.get(subject, [])
                export.papers.append(alone)
            continue
        if kind == "note":
            text_ = reader.note_text(subject)
            if text_:
                export.notes.append(
                    ExportedNote(text=text_, collections=member_of.get(subject, []))
                )
            continue
        try:
            paper = reader.paper(subject, kind)
        except Exception as error:
            export.problems.append(f"An item could not be read: {error}")
            continue
        paper.collections = member_of.get(subject, [])
        export.papers.append(paper)
    return export


class _Reader:
    def __init__(self, graph: Graph) -> None:
        self.g = graph

    def text(self, subject: Node, predicate: URIRef) -> str | None:
        value = self.g.value(subject, predicate)
        if isinstance(value, Literal) and str(value).strip():
            return str(value).strip()
        return None

    # Collections

    def collections(
        self,
    ) -> tuple[list[tuple[str, ...]], dict[Node, list[tuple[str, ...]]]]:
        """Every collection path (parents before children) and, per item,
        the paths of the collections that hold it. Loops are cut."""
        paths: list[tuple[str, ...]] = []
        holding: dict[Node, list[tuple[str, ...]]] = {}

        def visit(collection: Node, above: tuple[str, ...], seen: set[Node]) -> None:
            if collection in seen:
                return
            path = (*above, self.text(collection, DC.title) or "Untitled collection")
            if path not in paths:  # not for a repeated name
                paths.append(path)
            for part in sorted(self.g.objects(collection, DCTERMS.hasPart), key=str):
                if (part, RDF.type, Z.Collection) in self.g:
                    visit(part, path, {*seen, collection})
                else:
                    holding.setdefault(part, []).append(path)

        collections = sorted(self.g.subjects(RDF.type, Z.Collection), key=str)
        inside = {
            part for c in collections for part in self.g.objects(c, DCTERMS.hasPart)
        }
        for top in collections:
            if top not in inside:
                visit(top, (), set())
        return paths, holding

    # Items

    def paper(self, subject: Node, kind: str) -> ExportedPaper:
        g = self.g
        csl: dict[str, Any] = {"type": _TYPES.get(kind, "document")}
        csl["title"] = self.text(subject, DC.title) or "(untitled)"
        for role, people in self._creators(subject):
            csl[role] = [self._name(person) for person in people]

        identifiers: dict[str, str] = {}
        containers = [
            c
            for c in g.objects(subject, DCTERMS.isPartOf)
            if (c, RDF.type, BIB.Series) not in g
        ]
        for node in [subject, *containers]:
            identifiers.update(self._identifiers(node))
        for container in containers:
            if (container, RDF.type, BIB.Part) in g:
                section = self.text(container, DC.title)
                if section:
                    csl["section"] = section
                continue
            title = self.text(container, DC.title)
            if title:
                csl["container-title"] = title
            short = self.text(container, DCTERMS.alternative)
            if short:
                csl["container-title-short"] = short
            for field, predicate in (("volume", PRISM.volume), ("issue", PRISM.number)):
                value = self.text(container, predicate)
                if value:
                    csl[field] = value
        for field, predicate in (("volume", PRISM.volume), ("number", PRISM.number)):
            value = self.text(subject, predicate)
            if value and field not in csl:
                csl[field] = value
        for series in self._all_series(subject, containers):
            title = self.text(series, DC.title)
            if title:
                csl["collection-title"] = title
            number = self.text(series, DC.identifier)
            if number:
                csl["collection-number"] = number

        issued = self._date(self.text(subject, DC.date))
        if issued:
            csl["issued"] = issued
        for field, predicate in (
            ("page", BIB.pages),
            ("abstract", DCTERMS.abstract),
            ("edition", PRISM.edition),
            ("genre", DC.type),
            ("language", Z.language),
            ("title-short", Z.shortTitle),
            ("archive", Z.archive),
            ("archive_location", DC.coverage),
            ("number-of-pages", Z.numPages),
        ):
            value = self.text(subject, predicate)
            if value:
                csl[field] = value
        accessed = self._date(self.text(subject, DCTERMS.dateSubmitted))
        if accessed:
            csl["accessed"] = accessed
        publisher = g.value(subject, DC.publisher)
        if publisher is not None:
            name = self.text(publisher, FOAF.name)
            if name:
                csl["publisher"] = name
            address = g.value(publisher, VCARD.adr)
            place = self.text(address, VCARD.locality) if address else None
            if place:
                csl["publisher-place"] = place
        conference = g.value(subject, BIB.presentedAt)
        if conference is not None:
            event = self.text(conference, DC.title)
            if event:
                csl["event-title"] = event
        url = self._url(subject)
        if url:
            csl["URL"] = url

        extra = self.text(subject, DC.description) or ""
        key = self.text(subject, Z.citationKey) or _extra_field(extra, "Citation Key")
        if key:
            csl["citation-key"] = key
        arxiv = (_extra_field(extra, "arXiv") or "").split(" ")[0] or _arxiv_from(url)
        if "DOI" in identifiers:
            csl["DOI"] = identifiers["DOI"]
        for field in ("ISBN", "ISSN"):
            if field in identifiers:
                csl[field] = identifiers[field]
        found = identifiers_of(
            doi=identifiers.get("DOI") or _extra_field(extra, "DOI"),
            arxiv=arxiv,
            isbn=identifiers.get("ISBN"),
            pmid=_extra_field(extra, "PMID"),
            book=csl["type"] == "book",
        )
        doi = next((v for s, v in found if s.value == "doi"), None)
        if doi:
            csl["DOI"] = doi
        note_lines = [
            line
            for line in extra.splitlines()
            if not re.match(r"\s*(Citation Key|arXiv|DOI|PMID)\s*:", line, re.I)
        ]
        if "\n".join(note_lines).strip():
            csl["note"] = "\n".join(note_lines).strip()

        tags, automatic = self._tags(subject)
        return ExportedPaper(
            csl=csl,
            identifiers=found,
            tags=tags,
            keywords=automatic,
            notes=[
                text
                for note in sorted(g.objects(subject, DCTERMS.isReferencedBy), key=str)
                if (text := self.note_text(note))
            ],
            files=_without_snapshots(
                [
                    file
                    for attachment in sorted(g.objects(subject, LINK.link), key=str)
                    if (file := self._file(attachment)) is not None
                ]
            ),
            source_key=key or csl["title"],
        )

    def standalone(self, subject: Node) -> ExportedPaper | None:
        """A file without a paper (lecture notes, a thesis, scanned notes):
        a document named like the file in Zotero; None for a bare link."""
        file = self._file(subject)
        if file is None:
            return None
        title = self.text(subject, DC.title) or file.path.rsplit("/", 1)[-1]
        title = re.sub(r"\.(pdf|html?|epub|docx?|txt|md)$", "", title, flags=re.I)
        # Downloaded from arXiv (Zotero keeps the address): its arXiv ID, so
        # its details can be looked up and the PDF fetched again.
        url = self._url(subject)
        arxiv = _arxiv_from(url)
        found = identifiers_of(arxiv=arxiv) if arxiv else []
        csl: dict[str, Any] = {"type": "article" if found else "document"}
        csl["title"] = title or "(untitled)"
        if url:
            csl["URL"] = url
        tags, automatic = self._tags(subject)
        return ExportedPaper(
            csl=csl,
            identifiers=found,
            tags=tags,
            keywords=automatic,
            notes=[
                text
                for note in sorted(
                    self.g.objects(subject, DCTERMS.isReferencedBy), key=str
                )
                if (text := self.note_text(note))
            ],
            files=[file],
            source_key=str(subject),
        )

    def _creators(self, subject: Node) -> list[tuple[str, list[Node]]]:
        """(CSL role, people in order) of an item, the usual roles first;
        other roles (``z:castMembers``) by their name (``cast-member``)."""
        found: list[tuple[str, list[Node]]] = []
        for predicate, node in self.g.predicate_objects(subject):
            role = _ROLES.get(predicate)
            name = str(predicate)
            if role is None and name.startswith(str(Z)) and name.endswith("s"):
                role = re.sub(r"(?<!^)([A-Z])", r"-\1", name[len(str(Z)) : -1]).lower()
            people = self._sequence(node) if role else []
            if role and people:
                found.append((role, people))
        order = list(_ROLES.values())
        return sorted(
            found, key=lambda pair: order.index(pair[0]) if pair[0] in order else 99
        )

    def _sequence(self, node: Node) -> list[Node]:
        """Members of an rdf:Seq (rdf:_1, rdf:_2, … or rdf:li) in order."""
        members: list[tuple[int, Node]] = []
        for predicate, member in self.g.predicate_objects(node):
            found = re.fullmatch(re.escape(str(RDF)) + r"_(\d+)", str(predicate))
            if found:
                members.append((int(found.group(1)), member))
        return [m for _, m in sorted(members, key=lambda pair: pair[0])]

    def _name(self, person: Node) -> dict[str, str]:
        family = self.text(person, FOAF.surname) or ""
        given = self.text(person, FOAF.givenName)
        if not given:
            return {"literal": family}
        return {"family": family, "given": given}

    def _identifiers(self, node: Node) -> dict[str, str]:
        found: dict[str, str] = {}
        for value in self.g.objects(node, DC.identifier):
            if not isinstance(value, Literal):
                continue
            match = re.match(r"\s*(DOI|ISBN|ISSN)\s+(.+)", str(value))
            if match:
                found.setdefault(match.group(1), match.group(2).strip())
        return found

    def _all_series(self, subject: Node, containers: list[Node]) -> list[Node]:
        return [
            series
            for node in [subject, *containers]
            for series in self.g.objects(node, DCTERMS.isPartOf)
            if (series, RDF.type, BIB.Series) in self.g
        ]

    def _url(self, subject: Node) -> str | None:
        for value in self.g.objects(subject, DC.identifier):
            if (value, RDF.type, DCTERMS.URI) in self.g:
                url = self.text(value, RDF.value)
                if url:
                    return url
        # Zotero names an item by its URL when it has one.
        about = str(subject)
        if isinstance(subject, URIRef) and about.startswith(("http://", "https://")):
            return None if about.startswith(BASE) else about
        return None

    def _date(self, text: str | None) -> dict[str, Any] | None:
        if not text:
            return None
        parsed = date_parts(text)
        if parsed and "raw" in parsed:
            year = re.search(r"\b(1[5-9]|20)\d{2}\b", text)
            if year:
                return {"date-parts": [[int(year.group())]], "raw": text}
        return parsed

    def _tags(self, subject: Node) -> tuple[list[str], list[str]]:
        """The person's tags, and Zotero's automatic ones (from the paper's
        metadata: arXiv categories, a publisher's subjects)."""
        tags: list[str] = []
        automatic: list[str] = []
        for value in self.g.objects(subject, DC.subject):
            if isinstance(value, Literal):
                tags.append(str(value).strip())
            elif (value, RDF.type, Z.AutomaticTag) in self.g:
                automatic.append(self.text(value, RDF.value) or "")
        return (
            sorted(dict.fromkeys(t for t in tags if t)),
            sorted(dict.fromkeys(t for t in automatic if t)),
        )

    def note_text(self, note: Node) -> str | None:
        html = self.text(note, RDF.value)
        if not html:
            return None
        markdown = markdownify(html, heading_style="ATX", bullets="-").strip()
        return re.sub(r"\n{3,}", "\n\n", markdown) or None

    def _file(self, attachment: Node) -> ExportedFile | None:
        path = self.g.value(attachment, Z.path)
        if path is None:
            return None  # a link to a web page, no file
        text = str(path)
        if text.startswith(BASE):
            text = text[len(BASE) :]
        elif text.startswith("file://"):
            text = text[len("file://") :]
        return ExportedFile(
            path=unquote(text),
            media_type=self.text(attachment, LINK.type),
            description=self.text(attachment, DC.title),
        )


def _without_snapshots(files: list[ExportedFile]) -> list[ExportedFile]:
    """Zotero's saved web pages ("Snapshot") left out next to a PDF: they
    mostly repeat the abstract. Alone, a snapshot is the paper's only text."""
    if any(f.media_type == "application/pdf" for f in files):
        return [
            f
            for f in files
            if f.media_type not in ("text/html", "application/xhtml+xml")
        ]
    return files


def _extra_field(extra: str, name: str) -> str | None:
    """A ``Name: value`` line of Zotero's Extra field."""
    found = re.search(rf"^\s*{re.escape(name)}\s*:\s*(\S.*?)\s*$", extra, re.I | re.M)
    return found.group(1) if found else None


def _arxiv_from(url: str | None) -> str | None:
    found = re.search(r"arxiv\.org/(?:abs|pdf)/([^\s/?#]+?)(?:\.pdf)?$", url or "")
    return found.group(1) if found else None
