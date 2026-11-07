"""Writing libraries for Zotero, JabRef and Mendeley: read back with
paperus' own importers, the text checked where the programs need it."""

import re
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from markdownify import markdownify
from rdflib import RDF, Graph

from paperus import formats
from paperus.formats import jabref, ris, zotero
from paperus.formats.common import all_collections, date_parts, raw_date, year
from paperus.formats.markdown import to_html
from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedFile, ExportedNote, ExportedPaper
from paperus.importing import bibtex as bibtex_reader
from paperus.importing import ris as ris_reader
from paperus.importing import zotero as zotero_reader

SAMPLE = Path(__file__).parent / "zotero_sample.rdf"
NOTE = (
    "# Reading notes\n\nThe **gaps** are below the *beam*, see "
    "[the paper](https://example.org/a?b=1&c=2).\n\n- one\n- two\n  - inner"
)
TITLE = (
    "Radar gaps over the Alps: 50% of $\\alpha$-rain & {more} for $5 #1_x <a|b>^c ~d"
)
MANY = [{"family": f"Author{n}", "given": f"Given{n}"} for n in range(1, 31)]


def library() -> Export:
    """Articles, a book, a chapter, a preprint, a bare scan and a thesis,
    with odd characters, tags and keywords, nested collections (a name in
    two branches), notes, files and notes without a paper."""
    article = ExportedPaper(
        csl={
            "type": "article-journal",
            "title": TITLE,
            "author": [
                {"family": "Gogh", "non-dropping-particle": "van", "given": "Vincent"},
                {"family": "Müller", "given": "Jörg"},
                {"literal": "Radar Working Group"},
                {"family": "Lovelace", "given": "Ada", "suffix": "Jr."},
            ],
            "container-title": "Journal of Weather & Climate",
            "container-title-short": "J. Weather",
            "volume": "12",
            "issue": "4",
            "page": "101\u2013120",
            "issued": {"date-parts": [[2024, 3, 2]]},
            "accessed": {"date-parts": [[2026, 1, 5]]},
            "DOI": "10.1234/radar",
            "ISSN": "1234-5678",
            "URL": "https://example.org/radar?a=1&b=2",
            "abstract": "Blind zones hide rainfall.",
            "language": "en",
            "citation-key": "vanGogh2024",
        },
        identifiers=[(Scheme.DOI, "10.1234/radar")],
        tags=["radar", "to read"],
        keywords=["Weather", "Radar"],
        collections=[("Thesis", "Chapter 1"), ("Paper", "Methods")],
        notes=[NOTE, "Second note."],
        files=[
            ExportedFile("files/1/van Gogh: a;b.pdf", "application/pdf", "Full Text"),
            ExportedFile("files/1/snapshot.html", "text/html"),
        ],
    )
    book = ExportedPaper(
        csl={
            "type": "book",
            "title": "Clouds",
            "editor": [{"family": "Babbage", "given": "Charles"}],
            "publisher": "Cloud Press",
            "publisher-place": "Augsburg",
            "ISBN": "978-3-16-148410-0",
            "collection-title": "Weather Studies",
            "collection-number": "7",
            "edition": "2",
            "issued": {"date-parts": [[2020]]},
        },
        identifiers=[(Scheme.ISBN, "9783161484100")],
        collections=[("Thesis",)],
    )
    chapter = ExportedPaper(
        csl={
            "type": "chapter",
            "title": "Engines of the analytical kind",
            "author": [{"family": "Lovelace", "given": "Ada"}],
            "editor": [{"family": "Babbage", "given": "Charles"}],
            "container-title": "Collected Notes",
            "page": "7-9",
            "publisher": "Taylor",
            "issued": {"date-parts": [[1843]]},
        },
        tags=["history"],
    )
    preprint = ExportedPaper(
        csl={
            "type": "article",
            "title": "Diffusion of $\\mathcal{R}$ain",
            "author": MANY,
            "issued": {"date-parts": [[2026, 11]]},
            "DOI": "10.48550/arXiv.2611.00001",
        },
        identifiers=[
            (Scheme.DOI, "10.48550/arxiv.2611.00001"),
            (Scheme.ARXIV, "2611.00001"),
        ],
        keywords=["physics.ao-ph"],
        collections=[("Thesis", "Methods")],
    )
    scan = ExportedPaper(
        csl={"type": "document", "title": "Scan"},
        files=[ExportedFile("files/5/Note 241029.pdf", "application/pdf")],
    )
    thesis = ExportedPaper(
        csl={
            "type": "thesis",
            "genre": "Master's thesis",
            "title": "Hail",
            "author": [{"family": "Lovelace", "given": "Ada"}],
            "publisher": "Universität Augsburg",
            "issued": {"raw": "Spring 1843"},
        },
    )
    return Export(
        format="paperus",
        papers=[article, book, chapter, preprint, scan, thesis],
        notes=[
            ExportedNote("Ideas for the thesis.", [("Thesis",)]),
            ExportedNote("Loose idea."),
        ],
        collections=[
            ("Thesis",),
            ("Thesis", "Chapter 1"),
            ("Thesis", "Methods"),
            ("Paper",),
            ("Paper", "Methods"),
            ("Empty",),
        ],
    )


def by_title(export: Export) -> dict[str, ExportedPaper]:
    return {paper.csl["title"]: paper for paper in export.papers}


def names(csl: dict[str, Any], role: str = "author") -> list[tuple[str, str]]:
    """(family with particle, given) of each person, or (literal, "")."""
    return [
        (
            " ".join(filter(None, [n.get("non-dropping-particle"), n.get("family")]))
            or n.get("literal", ""),
            n.get("given", ""),
        )
        for n in csl.get(role, [])
    ]


def same_details(
    original: ExportedPaper, read: ExportedPaper, fields: list[str]
) -> None:
    for field in fields:
        assert read.csl.get(field) == original.csl.get(field), field
    # (Zotero has no suffix: it stays with the given name.)
    assert [(f, g.removesuffix(", Jr.")) for f, g in names(read.csl)] == names(
        original.csl
    )
    assert set(read.identifiers) == set(original.identifiers)


# The registry


def test_writers_for_each_program() -> None:
    export = library()
    assert set(formats.WRITERS) == {"zotero", "jabref", "mendeley"}
    for name, write in formats.WRITERS.items():
        written = write(export)
        assert isinstance(written, formats.Written)
        assert written.readme.startswith(
            {"zotero": "Zotero", "jabref": "JabRef", "mendeley": "Mendeley"}[name]
        )
        assert written.filename in written.readme
        # The same library gives the same bytes.
        assert write(library()).content == written.content


def test_an_empty_library() -> None:
    export = Export(format="paperus")
    assert jabref.write(export).content == (
        b"@Comment{jabref-meta: databaseType:bibtex;}\n"
    )
    assert ris.write(export).content == b""
    assert zotero_reader.read(zotero.write(export).content.decode()) == Export(
        format="zotero-rdf"
    )
    for write in formats.WRITERS.values():
        assert write(export).warnings == []


# JabRef


def test_jabref_round_trip() -> None:
    export = library()
    written = jabref.write(export)
    back = bibtex_reader.read(written.content.decode())
    assert back.problems == []
    # A name used in two branches gets its parent's name.
    assert back.collections == [
        ("Thesis",),
        ("Thesis", "Chapter 1"),
        ("Thesis", "Methods"),
        ("Paper",),
        ("Paper", "Methods (Paper)"),
        ("Empty",),
    ]
    papers = by_title(back)
    article, book, chapter, preprint, *_ = export.papers

    read = papers[TITLE]
    same_details(
        article,
        read,
        ["type", "container-title", "volume", "issue", "DOI", "ISSN", "URL"],
    )
    assert read.csl["author"][3] == {
        "family": "Lovelace",
        "given": "Ada",
        "suffix": "Jr.",
    }
    assert read.csl["page"] == "101-120"
    assert read.csl["issued"] == {"date-parts": [[2024, 3, 2]]}
    assert read.csl["accessed"] == {"date-parts": [[2026, 1, 5]]}
    assert read.csl["citation-key"] == "vanGogh2024"
    # One kind of keyword: tags first, the paper's own after (once).
    assert (read.tags, read.keywords) == (["radar", "to read", "Weather"], [])
    assert read.collections == [("Thesis", "Chapter 1"), ("Paper", "Methods (Paper)")]
    # The notes, one after the other in Comments, as written (Markdown).
    assert read.notes == [f"{NOTE}\n\nSecond note."]
    assert [asdict(f) for f in read.files] == [
        {
            "path": "files/1/van Gogh: a;b.pdf",
            "media_type": "application/pdf",
            "description": "Full Text",
        },
        {
            "path": "files/1/snapshot.html",
            "media_type": "text/html",
            "description": None,
        },
    ]

    # (Reading keeps the file's order.)
    assert [p.csl["title"] for p in back.papers] == [
        p.csl["title"] for p in export.papers
    ]

    read = papers["Clouds"]
    same_details(book, read, ["type", "publisher", "publisher-place", "edition"])
    assert names(read.csl, "editor") == [("Babbage", "Charles")]
    assert (read.csl["collection-title"], read.csl["number"]) == (
        "Weather Studies",
        "7",
    )
    assert read.collections == [("Thesis",)]

    read = papers["Engines of the analytical kind"]
    same_details(chapter, read, ["type", "container-title", "page", "publisher"])
    assert names(read.csl, "editor") == [("Babbage", "Charles")]

    read = papers["Diffusion of $\\mathcal{R}$ain"]
    same_details(preprint, read, ["type", "issued"])
    assert len(read.csl["author"]) == 30
    assert read.tags == ["physics.ao-ph"]

    read = papers["Scan"]
    assert read.csl["type"] == "document"
    assert [f.path for f in read.files] == ["files/5/Note 241029.pdf"]

    read = papers["Hail"]
    assert (read.csl["type"], read.csl["genre"]) == ("thesis", "Master's thesis")
    assert read.csl["issued"] == {"date-parts": [[1843]]}  # the text is lost

    # Generated keys: AuthorYear, a letter for a repeat.
    assert [p.csl["citation-key"] for p in back.papers] == [
        "vanGogh2024",
        "Babbage2020",
        "Lovelace1843",
        "Author12026",
        "Anon",
        "Lovelace1843a",
    ]
    assert written.warnings == [
        "The collection Paper / Methods is the group 'Methods (Paper)': JabRef "
        "tells groups apart by name and splits names at commas.",
        "JabRef has one kind of keyword: the papers' own keywords (from their "
        "details) are written together with your tags.",
        "2 notes without a paper are not in the file: a .bib holds only papers.",
        "The 2 notes on vanGogh2024 are one after the other in its Comments: "
        "JabRef has one comment per entry.",
    ]


def test_jabref_text() -> None:
    text = jabref.write(library()).content.decode()
    entries = text.split("\n\n@")
    # As JabRef 5 writes it: required fields, optional ones, the rest, each
    # alphabetical; names padded; a month macro; math kept, LaTeX escaped,
    # capitals protected; files with \: and \; escaped.
    assert entries[0].splitlines()[:11] == [
        "@Article{vanGogh2024,",
        "  author   = {van Gogh, Vincent and Müller, Jörg and "
        "{Radar Working Group} and Lovelace, Jr., Ada},",
        "  journal  = {Journal of Weather \\& Climate},",
        "  title    = {Radar gaps over the {Alps}: 50\\% of $\\alpha$-rain \\& "
        "\\{more\\} for \\$5 \\#1\\_x {\\textless}a{\\textbar}b{\\textgreater}"
        "{\\textasciicircum}c {\\textasciitilde}d},",
        "  year     = {2024},",
        "  issn     = {1234-5678},",
        "  month    = mar,",
        "  number   = {4},",
        "  pages    = {101--120},",
        "  volume   = {12},",
        "  abstract = {Blind zones hide rainfall.},",
    ]
    assert (
        "  file     = {Full Text:files/1/van Gogh\\: a\\;b.pdf:PDF;"
        ":files/1/snapshot.html:HTML},\n"
    ) in entries[0]
    assert "  groups   = {Chapter 1, Methods (Paper)},\n" in entries[0]
    assert entries[3].startswith("Misc{Author12026,\n  author        = {Author1, ")
    assert "  archiveprefix = {arXiv},\n" in entries[3]
    assert "  eprint        = {2611.00001},\n" in entries[3]
    assert entries[-2] == "Comment{jabref-meta: databaseType:bibtex;}"
    assert entries[-1] == (
        "Comment{jabref-meta: grouping:\n"
        "0 AllEntriesGroup:;\n"
        "1 StaticGroup:Thesis\\;0\\;1\\;\\;\\;\\;;\n"
        "2 StaticGroup:Chapter 1\\;0\\;1\\;\\;\\;\\;;\n"
        "2 StaticGroup:Methods\\;0\\;1\\;\\;\\;\\;;\n"
        "1 StaticGroup:Paper\\;0\\;1\\;\\;\\;\\;;\n"
        "2 StaticGroup:Methods (Paper)\\;0\\;1\\;\\;\\;\\;;\n"
        "1 StaticGroup:Empty\\;0\\;1\\;\\;\\;\\;;\n"
        "}\n"
    )


def entry(csl: dict[str, Any], **paper: Any) -> str:  # noqa: ANN401
    written = jabref.write(Export("paperus", [ExportedPaper(csl=csl, **paper)]))
    return written.content.decode().split("\n\n@")[0]


def test_jabref_entry_types_and_names() -> None:
    report = entry(
        {
            "type": "report",
            "title": "the report",
            "genre": "Technical note",
            "number": "TR-1",
            "publisher": "Lab",
            "author": [
                {"given": "Plato"},
                {"family": "Rock and Roll", "given": "Band"},
                {"family": "Lovelace", "suffix": "Jr."},
            ],
        }
    )
    assert report == (
        "@TechReport{Plato,\n"
        "  author      = {{Plato} and Rock {and} Roll, Band and Lovelace, Jr.},\n"
        "  institution = {Lab},\n"
        "  title       = {the report},\n"
        "  number      = {TR-1},\n"
        "  type        = {Technical note},\n"
        "}"
    )
    assert entry({"type": "thesis", "title": "T"}).startswith("@PhdThesis{Anon,")
    proceedings = entry(
        {"type": "paper-conference", "title": "P", "container-title": "Proc"}
    )
    assert "  booktitle = {Proc},\n" in proceedings
    assert entry({"type": "patent", "title": "P"}).startswith("@Patent{Anon,")
    # No name or an empty one: "Anonymous".
    assert "author = {{Anonymous}}" in entry({"title": "x", "author": [{}]})


def test_jabref_awkward_text() -> None:
    odd = entry(
        {
            "title": "a { b $x{$ and $y$",
            "URL": "https://example.org/{x",
            "issued": {"date-parts": [["", 2]]},
        },
        tags=["C_x", " "],
        notes=["Half { a brace"],
    )
    # A stray brace becomes \textbraceleft (\{ would unbalance the field);
    # math with a stray brace is text.
    assert (
        "  title    = {a {\\textbraceleft} b \\$x{\\textbraceleft}\\$ and $y$},"
    ) in odd
    assert "  url      = {https://example.org/%7Bx}," in odd
    assert "  comment  = {Half %7B a brace}," in odd
    assert "  keywords = {C\\_x}," in odd
    assert "year" not in odd and "month" not in odd
    # After math, the next word is not the title's first.
    assert "{$x$ Rain}" not in entry({"title": "$x$ Rain"})
    assert "title = {$x$ {Rain}}" in entry({"title": "$x$ Rain"})
    assert bibtex_reader.read(odd).problems == []
    closing = entry({"title": "close } open {"})
    assert "{close {\\textbraceright} open {\\textbraceleft}}" in closing


def test_jabref_keys() -> None:
    def keys(*papers: dict[str, Any]) -> list[str]:
        export = Export("paperus", [ExportedPaper(csl=csl) for csl in papers])
        back = bibtex_reader.read(jabref.write(export).content.decode())
        return [paper.source_key for paper in back.papers]

    ada = {"title": "x", "author": [{"family": "Ångström"}], "issued": {"raw": "1999"}}
    assert keys(*[ada] * 28)[-3:] == [
        "Angstrom1999y",
        "Angstrom1999z",
        "Angstrom1999aa",
    ]
    # A paper's own key wins over a generated one, and repeats get a letter.
    own = {"title": "y", "citation-key": "Angstrom1999"}
    assert keys(ada, own, own) == ["Angstrom1999a", "Angstrom1999", "Angstrom1999b"]
    assert keys({"title": "z", "editor": [{"literal": "Ed. Board"}]}) == ["EdBoard"]


def test_jabref_group_names() -> None:
    export = Export(
        "paperus",
        [ExportedPaper(csl={"title": "x"}, collections=[("a,b",), ("a b",), ("",)])],
        collections=[("Back\\slash",)],
    )
    written = jabref.write(export)
    text = written.content.decode()
    # Separators of the groups field go; repeats get a number; a backslash
    # is escaped twice (in the group, then in the line).
    assert "  groups = {a b, a b 2, Collection}," in text
    assert "1 StaticGroup:Back\\\\\\\\slash\\;0" in text
    assert len(written.warnings) == 3
    back = bibtex_reader.read(text)
    assert back.collections == [("Back\\slash",), ("a b",), ("a b 2",), ("Collection",)]


# Zotero


def test_zotero_round_trip() -> None:
    export = library()
    back = zotero_reader.read(zotero.write(export).content.decode())
    assert back.problems == []
    # Collections, also empty ones and a name in two branches.
    assert back.collections == export.collections
    papers = by_title(back)
    article, book, chapter, preprint, *_ = export.papers

    read = papers[TITLE]
    same_details(
        article,
        read,
        [
            "type",
            "container-title",
            "container-title-short",
            "volume",
            "issue",
            "page",
            "issued",
            "accessed",
            "DOI",
            "ISSN",
            "URL",
            "abstract",
            "language",
            "citation-key",
        ],
    )
    assert read.csl["author"][0] == {"family": "van Gogh", "given": "Vincent"}
    assert read.csl["author"][3] == {"family": "Lovelace", "given": "Ada, Jr."}
    # Tags and the paper's own keywords stay apart (automatic tags).
    assert (read.tags, read.keywords) == (["radar", "to read"], ["Radar", "Weather"])
    assert read.collections == [("Thesis", "Chapter 1"), ("Paper", "Methods")]
    assert read.notes == [NOTE, "Second note."]
    # (The importer leaves a snapshot out next to a PDF.)
    assert [asdict(f) for f in read.files] == [
        {
            "path": "files/1/van Gogh: a;b.pdf",
            "media_type": "application/pdf",
            "description": "Full Text",
        }
    ]

    read = papers["Clouds"]
    same_details(
        book,
        read,
        [
            "type",
            "publisher",
            "publisher-place",
            "ISBN",
            "collection-title",
            "collection-number",
            "edition",
            "issued",
        ],
    )
    assert names(read.csl, "editor") == [("Babbage", "Charles")]
    assert read.collections == [("Thesis",)]

    read = papers["Engines of the analytical kind"]
    same_details(chapter, read, ["type", "container-title", "page", "publisher"])
    assert names(read.csl, "editor") == [("Babbage", "Charles")]
    assert read.tags == ["history"]

    read = papers["Diffusion of $\\mathcal{R}$ain"]
    same_details(preprint, read, ["type", "issued"])
    assert read.csl["DOI"] == "10.48550/arxiv.2611.00001"
    assert read.keywords == ["physics.ao-ph"]
    assert read.collections == [("Thesis", "Methods")]

    read = papers["Scan"]
    assert read.csl == {"type": "document", "title": "Scan"}
    assert [(f.path, f.description) for f in read.files] == [
        ("files/5/Note 241029.pdf", "Note 241029.pdf")
    ]

    read = papers["Hail"]
    assert read.csl["genre"] == "Master's thesis"
    assert read.csl["issued"] == {"date-parts": [[1843]], "raw": "Spring 1843"}

    assert back.notes == export.notes
    # In the file's order (#item_11 after #item_6).
    assert [p.csl["title"] for p in back.papers] == [
        p.csl["title"] for p in export.papers
    ]


def test_zotero_sample_round_trip() -> None:
    """Zotero's own export, read, written and read again, is the same
    (only the keys of files without a paper, made from their address,
    differ)."""
    first = zotero_reader.read(SAMPLE.read_text())
    again = zotero_reader.read(zotero.write(first).content.decode())
    assert [replace(p, source_key="") for p in again.papers] == [
        replace(p, source_key="") for p in first.papers
    ]
    assert (again.notes, again.collections) == (first.notes, first.collections)


def graph(rdf: str) -> Graph:
    """The RDF graph, Zotero's file path element read as the importer does."""
    parsed = Graph()
    parsed.parse(
        data=re.sub(r"<rdf:resource(\s)", r"<z:path\1", rdf),
        format="xml",
        publicID=zotero_reader.BASE,
    )
    return parsed


def test_zotero_rdf_is_like_zoteros() -> None:
    rdf = zotero.write(library()).content.decode()
    ours, theirs = graph(rdf), graph(SAMPLE.read_text())
    # Zotero's namespaces, as Zotero declares them.
    assert rdf.splitlines()[:2] == [
        "<rdf:RDF",
        ' xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"',
    ]
    assert dict(ours.namespaces()).items() >= dict(theirs.namespaces()).items()
    Z, BIB = zotero_reader.Z, zotero_reader.BIB
    assert len(set(ours.subjects(RDF.type, Z.Collection))) == 6
    assert len(set(ours.subjects(RDF.type, Z.Attachment))) == 3
    assert len(set(ours.subjects(RDF.type, BIB.Memo))) == 4

    def used(g: Graph, kind: str) -> set[Any]:
        """The properties of items of a Zotero type, and of their parts."""
        found = set()
        for item in g.subjects(Z.itemType, None):
            if str(g.value(item, Z.itemType)) != kind:
                continue
            for predicate, value in g.predicate_objects(item):
                found.add(predicate)
                found.update(p for p, _ in g.predicate_objects(value))
        # Sequence members, rdf:_1, rdf:_2, …
        return {p for p in found if not re.fullmatch(f"{RDF}_\\d+", str(p))}

    # Nothing Zotero's own export does not write for these types.
    for kind in ("journalArticle", "attachment", "note"):
        assert used(ours, kind) <= used(theirs, kind), kind
    # The file path as Zotero writes it (percent-encoded, relative).
    assert '<rdf:resource rdf:resource="files/1/van%20Gogh%3A%20a%3Bb.pdf"/>' in rdf
    assert "&lt;h1&gt;Reading notes&lt;/h1&gt;" in rdf


def zotero_paper(paper: ExportedPaper) -> tuple[ExportedPaper, str]:
    rdf = zotero.write(Export("paperus", [paper])).content.decode()
    [read] = zotero_reader.read(rdf).papers
    return read, rdf


def test_zotero_fields() -> None:
    read, rdf = zotero_paper(
        ExportedPaper(
            csl={
                "type": "chapter",
                "title": "Section",
                "section": "Part II",
                "collection-title": "Series",
                "collection-number": "3",
                "event-title": "Engine Days",
                "translator": [{"family": "Müller", "given": "Jörg"}],
                "cast-member": [{"literal": "Byron"}],
                "categories": ["not people"],
                "archive": "Archive",
                "note": "Read twice.",
            },
            identifiers=[(Scheme.PMID, "12345")],
        )
    )
    assert read.csl["section"] == "Part II"
    assert (read.csl["collection-title"], read.csl["collection-number"]) == (
        "Series",
        "3",
    )
    assert read.csl["event-title"] == "Engine Days"
    assert read.csl["translator"] == [{"family": "Müller", "given": "Jörg"}]
    assert read.csl["cast-member"] == [{"literal": "Byron"}]
    assert (read.csl["archive"], read.csl["note"]) == ("Archive", "Read twice.")
    assert read.identifiers == [(Scheme.PMID, "12345")]
    assert "<z:castMembers>" in rdf and "categories" not in rdf

    # Report numbers on the item; a book's DOI in Extra; a preprint's
    # repository from its container; absolute file paths as file: URLs.
    read, rdf = zotero_paper(
        ExportedPaper(
            csl={"type": "report", "title": "R", "number": "TR-1", "volume": "2"},
            identifiers=[(Scheme.DOI, "10.1234/r")],
        )
    )
    assert (read.csl["number"], read.csl["volume"]) == ("TR-1", "2")
    assert read.identifiers[0] == (Scheme.DOI, "10.1234/r")
    assert "<dc:description>DOI: 10.1234/r</dc:description>" in rdf
    read, rdf = zotero_paper(
        ExportedPaper(
            csl={"type": "article", "title": "P", "container-title": "bioRxiv"},
            files=[ExportedFile("/home/ada/my notes.pdf")],
        )
    )
    assert read.csl["publisher"] == "bioRxiv"
    assert read.files[0].path == "/home/ada/my notes.pdf"
    assert 'rdf:resource="file:///home/ada/my%20notes.pdf"' in rdf
    # Characters XML cannot hold are left out.
    read, rdf = zotero_paper(
        ExportedPaper(csl={"type": "odd", "title": 'Bell\x07 "quoted" \U0001f600'})
    )
    assert read.csl == {"type": "document", "title": 'Bell "quoted" \U0001f600'}


# RIS (Mendeley)


def test_ris_round_trip() -> None:
    export = library()
    written = ris.write(export)
    back = ris_reader.read(written.content.decode())
    assert back.problems == []
    papers = by_title(back)
    article, book, chapter, preprint, *_ = export.papers

    read = papers[TITLE]
    same_details(
        article,
        read,
        ["type", "container-title", "volume", "issue", "issued", "DOI", "ISSN", "URL"],
    )
    assert read.csl["author"][3] == {
        "family": "Lovelace",
        "given": "Ada",
        "suffix": "Jr.",
    }
    assert read.csl["page"] == "101-120"
    assert read.tags == ["radar", "to read", "Weather"]
    # A note over several lines stays one (RIS keeps no empty lines).
    assert read.notes == [
        "\n".join(line for line in NOTE.splitlines() if line),
        "Second note.",
    ]
    assert [f.path for f in read.files] == [
        "files/1/van Gogh: a;b.pdf",
        "files/1/snapshot.html",
    ]
    read = papers["Clouds"]
    same_details(
        book,
        read,
        [
            "type",
            "publisher",
            "publisher-place",
            "ISBN",
            "edition",
            "issued",
            "collection-title",
        ],
    )
    assert names(read.csl, "editor") == [("Babbage", "Charles")]
    read = papers["Engines of the analytical kind"]
    same_details(chapter, read, ["type", "container-title", "page", "publisher"])
    assert names(read.csl, "editor") == [("Babbage", "Charles")]
    read = papers["Diffusion of $\\mathcal{R}$ain"]
    same_details(preprint, read, ["type", "issued"])
    assert read.csl["URL"] == "https://arxiv.org/abs/2611.00001"
    read = papers["Hail"]
    assert (read.csl["type"], read.csl["publisher"]) == (
        "thesis",
        "Universität Augsburg",
    )
    assert written.warnings == [
        "RIS has one kind of keyword: the papers' own keywords (from their "
        "details) are written together with your tags.",
        "2 notes without a paper are not in the file: RIS holds only papers.",
        "RIS has no collections (and Mendeley imports none): the papers come "
        "without them.",
    ]


def test_ris_lines() -> None:
    text = ris.write(library()).content.decode()
    assert "\n" not in text.replace("\r\n", "")
    records = text.split("\r\n\r\n")
    assert records[-1] == ""
    for record in records[:-1]:
        lines = record.split("\r\n")
        assert lines[0].startswith("TY  - ")
        assert lines[-1] == "ER  - "
    first = records[0].split("\r\n")
    assert first[:6] == [
        "TY  - JOUR",
        "ID  - vanGogh2024",
        "AU  - van Gogh, Vincent",
        "AU  - Müller, Jörg",
        "AU  - Radar Working Group",
        "AU  - Lovelace, Ada, Jr.",
    ]
    assert first[first.index("SP  - 101") :][:2] == ["SP  - 101", "EP  - 120"]
    # A note over several lines goes on without a tag.
    note = first.index("N1  - # Reading notes")
    assert first[note + 1 : note + 6] == [
        "The **gaps** are below the *beam*, see "
        "[the paper](https://example.org/a?b=1&c=2).",
        "- one",
        "- two",
        "  - inner",
        "N1  - Second note.",
    ]
    assert records[3].split("\r\n")[0] == "TY  - GEN"  # RIS has no preprints


def test_ris_odd_values() -> None:
    paper = ExportedPaper(
        csl={
            "type": "book",
            "title": "B",
            "author": [{"family": "Lovelace", "suffix": "Jr."}, {"given": "Plato"}],
            "URL": "https://example.org/a;b",
            "abstract": "First line\nAB  - not a tag",
            "page": "e123",
        },
        identifiers=[(Scheme.ISBN, "9783161484100")],
    )
    text = ris.write(Export("paperus", [paper])).content.decode()
    assert text.split("\r\n")[1:9] == [
        "AU  - Lovelace, , Jr.",
        "AU  - Plato",
        "TI  - B",
        "SP  - e123",
        "SN  - 9783161484100",
        "UR  - https://example.org/a%3Bb",
        "AB  - First line",
        " AB  - not a tag",
    ]
    [read] = ris_reader.read(text).papers
    assert read.csl["abstract"] == "First line AB  - not a tag"


# Markdown notes as HTML (Zotero)


@pytest.mark.parametrize(
    "markdown",
    [
        NOTE,
        "line one\nline two",
        "hard  \nbreak",
        "3. three\n4. four",
        "- a\n\n  more of a\n- b",
        "> quoted\n> more",
        "## Head\n\n---\n\n`code <x>` and ~~gone~~ & <tag>",
        "```\ncode\n  block\n```",
    ],
)
def test_markdown_survives_zotero(markdown: str) -> None:
    html = to_html(markdown)
    back = markdownify(html, heading_style="ATX", bullets="-").strip()
    assert re.sub(r"\n{3,}", "\n\n", back) == markdown


@pytest.mark.parametrize(
    ("markdown", "html"),
    [
        ("```\nnever closed", "<pre><code>never closed</code></pre>"),
        ("### Head ###", "<h3>Head</h3>"),
        ("\\*not em\\* a_b_c", "<p>*not em* a_b_c</p>"),
        ("__strong__ _em_ x\x00", "<p><strong>strong</strong> <em>em</em> x</p>"),
        ('[q](https://x.org/"y")', '<p><a href="https://x.org/%22y%22">q</a></p>'),
        ("-\tthing\n-", "<ul><li>thing</li><li></li></ul>"),
        ("text\n# heading", "<p>text</p><h1>heading</h1>"),
        ("- a\n\n\nb", "<ul><li>a</li></ul><p>b</p>"),
        ("line\\\nbreak", "<p>line<br/>\nbreak</p>"),
        ("- item\n1. other", "<ul><li>item</li></ul><ol><li>other</li></ol>"),
    ],
)
def test_markdown_details(markdown: str, html: str) -> None:
    assert to_html(markdown) == html


# Helpers


def test_dates_and_collections() -> None:
    assert date_parts({"date-parts": [[2024, "x", 2]]}) == [2024]
    assert date_parts({"date-parts": "2024"}) == []
    assert date_parts("2024") == []
    assert raw_date({"raw": " "}) is None
    assert year({"issued": {"raw": "c. 1999"}}) == "1999"
    assert year({"issued": {"raw": "undated"}}) is None
    # Paths only papers and notes name, with their parents.
    export = Export(
        "paperus",
        [ExportedPaper(csl={}, collections=[("A", "B", "C")])],
        [ExportedNote("n", [("D",)])],
        collections=[("A",)],
    )
    assert all_collections(export) == [("A",), ("A", "B"), ("A", "B", "C"), ("D",)]


def test_identifiers_from_lists_and_dois() -> None:
    paper = ExportedPaper(
        csl={
            "type": "book",
            "title": "x",
            "ISBN": ["978-3-16-148410-0", "other"],
            "ISSN": [],
            "DOI": "10.48550/arXiv.2101.00001",
        }
    )
    text = jabref.write(Export("paperus", [paper])).content.decode()
    assert re.search(r"isbn +\= \{978-3-16-148410-0\}", text)
    assert re.search(r"eprint +\= \{2101.00001\}", text)
    assert "issn" not in text


# What the importers read back


def test_bibtex_reads_links_notes_and_groups_as_written() -> None:
    export = bibtex_reader.read(
        "@misc{k,\r\n title = {T},\r\n url = {\\url{https://x.org/a{\\_}b?c=1&d=2}},\r\n"
        " doi = {10.1234/A\\_B},\r\n"
        " annote = {50\\% \\& more\r\n  - indented},\r\n"
        " comment = {100% & {braces}},\r\n"
        " groups = {a},\r\n}\n\n"
        "@Comment{jabref-meta: grouping:\n0 AllEntriesGroup:;\n"
        r"1 StaticGroup:a\\\;b\;0\;1\;\;\;\;;"
        "\n"
        r"2 StaticGroup:x\\\\y\;0\;1\;\;\;\;;"
        "\n}\n"
    )
    [paper] = export.papers
    assert paper.csl["URL"] == "https://x.org/a_b?c=1&d=2"
    assert paper.csl["DOI"] == "10.1234/a_b"
    assert paper.notes == ["50% & more\n  - indented", "100% & {braces}"]
    assert export.collections == [("a;b",), ("a;b", "x\\y")]


def test_bibtex_latex_escapes() -> None:
    [paper] = bibtex_reader.read(
        "@misc{k, title = {{\\textless}{\\textgreater}{\\textbar}"
        "{\\textbraceleft}{\\textbraceright}{\\textasciicircum}}}"
    ).papers
    assert paper.csl["title"] == "<>|{}^"


def test_ris_reads_notes_over_several_lines() -> None:
    [paper] = ris_reader.read(
        "TY  - BOOK\r\nTI  - B\r\nA2  - Babbage, Charles\r\nT3  - Series\r\n"
        "N1  - first\r\n  indented\r\n\r\nN1  - second\r\nKW  - a\r\nb\r\nER  - \r\n"
    ).papers
    assert paper.notes == ["first\n  indented", "second"]
    assert paper.tags == ["a", "b"]
    assert paper.csl["editor"] == [{"family": "Babbage", "given": "Charles"}]
    assert paper.csl["collection-title"] == "Series"
