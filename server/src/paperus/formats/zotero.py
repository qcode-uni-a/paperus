"""Zotero RDF, as Zotero's own "Export Library…" writes it with "Export
Notes" and "Export Files" ticked.

Laid out like Zotero's export (RDF/XML with its namespaces, details
nested in each item): an item per paper (``bib:Article``, ``bib:Book``,
… with ``z:itemType``), journal or book details on a ``dcterms:isPartOf``
container, creators in ``rdf:Seq`` lists of ``foaf:Person``, tags as
``dc:subject`` and the papers' own keywords as Zotero's automatic tags
(``z:AutomaticTag``), notes as ``bib:Memo`` (HTML) linked by
``dcterms:isReferencedBy``, notes without a paper as ``bib:Memo`` items,
files as ``z:Attachment`` linked by ``link:link`` with the path as
Zotero writes it (``<rdf:resource rdf:resource="files/…"/>``, relative
to the .rdf), and collections as ``z:Collection`` holding subcollections
and items through ``dcterms:hasPart``. The citation key, the arXiv ID,
a PubMed ID and, for item types without a DOI field, the DOI go into
Extra (``dc:description``) as ``Name: value`` lines, as Zotero and Better
BibTeX read them.

Written by hand rather than with rdflib: Zotero's file path element is
not valid RDF/XML (rdflib refuses to write it), and Zotero's layout is
kept as it is. Only the structure is taken from Zotero's translator (AGPL),
not its code.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from itertools import count
from urllib.parse import quote
from xml.sax.saxutils import escape

from paperus import citations
from paperus.formats.common import (
    Written,
    all_collections,
    arxiv_id,
    children,
    family,
    first,
    given,
    identifier,
    iso_date,
    raw_date,
)
from paperus.formats.markdown import to_html
from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedFile, ExportedPaper
from paperus.importing import zotero as reader

README = """\
Zotero
======

paperus.rdf is a Zotero RDF file: your papers with their details, tags,
keywords (as automatic tags), notes, files and collections.

1. Unpack the whole archive into one folder and keep paperus.rdf and the
   files folder side by side: the files are found relative to the .rdf.
2. In Zotero 7: File → Import…, choose "A file (BibTeX, RIS, Zotero RDF,
   etc.)", then paperus.rdf.
3. Leave "Place imported collections and items into new collection" on to
   keep them apart from your library at first, and choose "Copy files to
   the Zotero storage folder" so Zotero keeps its own copies.
"""

_NAMESPACES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "z": str(reader.Z),
    "dcterms": str(reader.DCTERMS),
    "bib": str(reader.BIB),
    "foaf": str(reader.FOAF),
    "link": str(reader.LINK),
    "dc": str(reader.DC),
    "prism": str(reader.PRISM),
    "vcard": str(reader.VCARD),
}
# CSL type → Zotero item type: the importer's table the other way round
# (where two Zotero types give one CSL type, the first).
_ITEM_TYPES = {csl: kind for kind, csl in reversed(reader.TYPES.items())}
# Zotero item type → its element and its container's, as in Zotero's export.
_ELEMENTS: dict[str, tuple[str, str | None]] = {
    "book": ("bib:Book", None),
    "bookSection": ("bib:BookSection", "bib:Book"),
    "journalArticle": ("bib:Article", "bib:Journal"),
    "magazineArticle": ("bib:Article", "bib:Periodical"),
    "newspaperArticle": ("bib:Article", "bib:Newspaper"),
    "thesis": ("bib:Thesis", None),
    "letter": ("bib:Letter", None),
    "manuscript": ("bib:Manuscript", None),
    "interview": ("bib:Interview", None),
    "film": ("bib:MotionPicture", None),
    "artwork": ("bib:Illustration", None),
    "webpage": ("bib:Document", "z:Website"),
    "report": ("bib:Report", None),
    "bill": ("bib:Legislation", None),
    "case": ("bib:Document", "bib:CourtReporter"),
    "hearing": ("bib:Report", None),
    "patent": ("bib:Patent", None),
    "statute": ("bib:Legislation", None),
    "map": ("bib:Image", None),
    "blogPost": ("bib:Document", "z:Blog"),
    "forumPost": ("bib:Document", "z:Forum"),
    "audioRecording": ("bib:Recording", None),
    "presentation": ("bib:ConferenceProceedings", None),
    "radioBroadcast": ("bib:Recording", None),
    "computerProgram": ("bib:Data", None),
    "encyclopediaArticle": ("rdf:Description", "bib:Book"),
    "dictionaryEntry": ("rdf:Description", "bib:Book"),
    "conferencePaper": ("rdf:Description", "bib:Journal"),
}
# Item types with a DOI field; others keep it in Extra, as Zotero does.
_WITH_DOI = {"journalArticle", "conferencePaper", "preprint", "dataset", "standard"}
# CSL name variables Zotero has no own property for (z:castMembers, …).
_OTHER_ROLES = {
    "cast-member",
    "chair",
    "compiler",
    "composer",
    "curator",
    "executive-producer",
    "guest",
    "host",
    "illustrator",
    "narrator",
    "organizer",
    "original-author",
    "performer",
    "producer",
    "script-writer",
    "series-creator",
}


def _role_property(role: str) -> str | None:
    """Zotero's creator property for a CSL role (``bib:authors``,
    ``z:castMembers``); None for other fields."""
    for predicate, known in reader.ROLES.items():
        if known == role:
            prefix = "bib" if predicate.startswith(str(reader.BIB)) else "z"
            return f"{prefix}:{predicate.rsplit('/', 1)[-1].rsplit('#', 1)[-1]}"
    if role in _OTHER_ROLES:
        head, *rest = role.split("-")
        return "z:" + head + "".join(word.capitalize() for word in rest) + "s"
    return None


@dataclass
class _El:
    """An XML element: text or children."""

    tag: str
    text: str | None = None
    attributes: dict[str, str] = field(default_factory=dict)
    children: list["_El"] = field(default_factory=list)

    def add(self, tag: str, text: object = None, **attributes: str) -> "_El":
        element = _El(tag, None if text is None else str(text), attributes)
        self.children.append(element)
        return element

    def text_of(self, tag: str, value: object) -> None:
        """A child with text, if there is any."""
        text = first(value)
        if text:
            self.add(tag, text)

    def lines(self, depth: int) -> list[str]:
        attributes = "".join(
            f' {name}="{_xml(value, attribute=True)}"'
            for name, value in self.attributes.items()
        )
        head = "    " * depth + f"<{self.tag}{attributes}"
        if self.text is not None:
            return [f"{head}>{_xml(self.text)}</{self.tag}>"]
        if not self.children:
            return [f"{head}/>"]
        inner = [line for child in self.children for line in child.lines(depth + 1)]
        return [f"{head}>", *inner, "    " * depth + f"</{self.tag}>"]


def write(export: Export) -> Written:
    items: list[_El] = []
    ids: dict[int, str] = {}  # id() of a paper or note → its resource
    counter = count(1)

    def next_id() -> str:
        return f"#item_{next(counter)}"

    for paper in export.papers:
        ids[id(paper)] = next_id()
        items.extend(_paper(paper, ids[id(paper)], next_id))
    for note in export.notes:
        ids[id(note)] = next_id()
        memo = _El("bib:Memo", attributes={"rdf:about": ids[id(note)]})
        memo.add("z:itemType", "note")
        memo.add("rdf:value", _note_html(note.text))
        items.append(memo)
    items.extend(_collections(export, ids))
    namespaces = "".join(f'\n xmlns:{p}="{uri}"' for p, uri in _NAMESPACES.items())
    lines = [line for item in items for line in item.lines(1)]
    text = "\n".join([f"<rdf:RDF{namespaces}>", *lines, "</rdf:RDF>"]) + "\n"
    return Written(
        content=text.encode(),
        filename="paperus.rdf",
        media_type="application/rdf+xml",
        readme=README,
    )


def _paper(paper: ExportedPaper, about: str, next_id: Callable[[], str]) -> list[_El]:
    csl = citations.tidy(paper.csl)
    kind = _ITEM_TYPES.get(str(csl.get("type") or ""), "document")
    element, container_tag = _ELEMENTS.get(kind, ("rdf:Description", None))
    item = _El(element, attributes={"rdf:about": about})
    item.add("z:itemType", kind)

    publisher = first(csl.get("publisher"))
    if kind == "preprint" and not publisher and container_tag is None:
        publisher = first(csl.get("container-title"))  # the repository
    place = first(csl.get("publisher-place"))
    if publisher or place:
        organization = item.add("dc:publisher").add("foaf:Organization")
        if place:
            address = organization.add("vcard:adr").add("vcard:Address")
            address.add("vcard:locality", place)
        organization.text_of("foaf:name", publisher)

    section = first(csl.get("section"))
    if section:
        item.add("dcterms:isPartOf").add("bib:Part").add("dc:title", section)
    # Journal details on the container, as Zotero has them; without one
    # (books, reports, …) on the item.
    holder = item
    if container_tag:
        holder = item.add("dcterms:isPartOf").add(container_tag)
        holder.text_of("dc:title", csl.get("container-title"))
        holder.text_of("dcterms:alternative", csl.get("container-title-short"))
        holder.text_of("prism:volume", csl.get("volume"))
        holder.text_of("prism:number", csl.get("issue") or csl.get("number"))
    series, number = first(csl.get("collection-title")), csl.get("collection-number")
    if series or first(number):
        part = holder.add("dcterms:isPartOf").add("bib:Series")
        part.text_of("dc:title", series)
        part.text_of("dc:identifier", number)
    event = first(csl.get("event-title") or csl.get("event"))
    if event:
        item.add("bib:presentedAt").add("bib:Conference").add("dc:title", event)

    for role, people in csl.items():
        creators = _role_property(role)
        if creators and isinstance(people, list) and people:
            sequence = item.add(creators).add("rdf:Seq")
            for name in people:
                person = sequence.add("rdf:li").add("foaf:Person")
                person.add("foaf:surname", family(name) or name.get("literal") or "")
                if given(name) and name.get("family"):
                    suffix = f", {name['suffix']}" if name.get("suffix") else ""
                    person.add("foaf:givenName", given(name) + suffix)

    extra_items: list[_El] = []
    for text in paper.notes:
        note = next_id()
        item.add("dcterms:isReferencedBy", **{"rdf:resource": note})
        memo = _El("bib:Memo", attributes={"rdf:about": note})
        memo.add("rdf:value", _note_html(text))
        extra_items.append(memo)
    for file in paper.files:
        attachment = next_id()
        item.add("link:link", **{"rdf:resource": attachment})
        extra_items.append(_attachment(file, attachment))
    for tag in dict.fromkeys(paper.tags):
        item.add("dc:subject", tag)
    for keyword in dict.fromkeys(paper.keywords):
        tag = item.add("dc:subject").add("z:AutomaticTag")
        tag.add("rdf:value", keyword)

    item.text_of("dc:title", csl.get("title") or "(untitled)")
    doi = identifier(paper, Scheme.DOI)
    for name, value in (
        ("DOI", doi if kind in _WITH_DOI else None),
        ("ISBN", identifier(paper, Scheme.ISBN)),
        ("ISSN", first(csl.get("ISSN"))),
    ):
        if value:
            holder.add("dc:identifier", f"{name} {value}")
    if not container_tag:
        item.text_of("prism:volume", csl.get("volume"))
        item.text_of("prism:number", csl.get("number") or csl.get("issue"))
    item.text_of("dcterms:abstract", csl.get("abstract"))
    item.text_of("dc:date", iso_date(csl.get("issued")) or raw_date(csl.get("issued")))
    for tag, name in (
        ("prism:edition", "edition"),
        ("dc:type", "genre"),
        ("z:language", "language"),
        ("z:shortTitle", "title-short"),
        ("z:archive", "archive"),
        ("dc:coverage", "archive_location"),
        ("z:numPages", "number-of-pages"),
    ):
        item.text_of(tag, csl.get(name))
    arxiv = arxiv_id(paper)
    if kind == "preprint" and arxiv:
        item.add("z:archiveID", f"arXiv:{arxiv}")
    url = first(csl.get("URL"))
    if url:
        item.add("dc:identifier").add("dcterms:URI").add("rdf:value", url)
    item.text_of("dcterms:dateSubmitted", iso_date(csl.get("accessed")))
    item.text_of("bib:pages", csl.get("page"))
    extra = [
        first(csl.get("note")),
        _line("Citation Key", citations.own_key(csl)),
        _line("arXiv", arxiv),
        _line("DOI", doi if kind not in _WITH_DOI else None),
        _line("PMID", identifier(paper, Scheme.PMID)),
    ]
    item.text_of("dc:description", "\n".join(line for line in extra if line))
    return [item, *extra_items]


def _line(name: str, value: str | None) -> str | None:
    return f"{name}: {value}" if value else None


def _attachment(file: ExportedFile, about: str) -> _El:
    attachment = _El("z:Attachment", attributes={"rdf:about": about})
    attachment.add("z:itemType", "attachment")
    # Zotero's own (invalid) way of writing the path, which it reads back.
    path = quote(file.path, safe="/")
    if file.path.startswith("/"):
        path = "file://" + path
    attachment.add("rdf:resource", **{"rdf:resource": path})
    attachment.add("dc:title", file.description or file.path.rsplit("/", 1)[-1])
    attachment.text_of("link:type", file.media_type)
    return attachment


def _collections(export: Export, ids: dict[int, str]) -> list[_El]:
    paths = all_collections(export)
    tree = children(paths)
    names = {path: f"#collection_{n}" for n, path in enumerate(paths, 1)}
    members: dict[tuple[str, ...], list[str]] = {}
    for item in [*export.papers, *export.notes]:
        for path in dict.fromkeys(item.collections):
            members.setdefault(path, []).append(ids[id(item)])
    elements: list[_El] = []

    def add(path: tuple[str, ...]) -> None:
        collection = _El("z:Collection", attributes={"rdf:about": names[path]})
        collection.add("dc:title", path[-1])
        for child in tree.get(path, []):
            collection.add("dcterms:hasPart", **{"rdf:resource": names[child]})
        for member in members.get(path, []):
            collection.add("dcterms:hasPart", **{"rdf:resource": member})
        elements.append(collection)
        for child in tree.get(path, []):
            add(child)

    for top in tree.get((), []):
        add(top)
    return elements


def _note_html(markdown: str) -> str:
    return f'<div data-schema-version="9">{to_html(markdown)}</div>'


def _xml(text: str, *, attribute: bool = False) -> str:
    """Escaped for XML, without the characters XML 1.0 cannot hold."""
    text = "".join(
        char
        for char in text
        if char in "\t\n\r"
        or ("\x20" <= char <= "퟿")
        or ("" <= char <= "�")
        or char >= "\U00010000"
    )
    return escape(text, {'"': "&quot;"} if attribute else {})
