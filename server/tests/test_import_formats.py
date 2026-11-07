"""Reading exports of other reference managers: small, odd and broken files."""

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest

from paperus.identifiers import Scheme
from paperus.importing import ExportedPaper, bibtex, csljson, ris, zotero
from paperus.importing import run as run_module
from paperus.importing.apply import FolderFiles, NoFiles, ZipFiles
from paperus.importing.common import date_parts, identifiers_of, split_keywords
from paperus.importing.run import NotAnExport, open_export

# Common helpers


def test_identifiers_of_leaves_out_invalid_ones() -> None:
    assert identifiers_of(doi="not a doi", arxiv="2101.00001", pmid="0") == [
        (Scheme.ARXIV, "2101.00001")
    ]
    # An arXiv DOI implies the arXiv ID; repeats are dropped.
    assert identifiers_of(doi="10.48550/arXiv.2101.00001", arxiv="2101.00001") == [
        (Scheme.DOI, "10.48550/arxiv.2101.00001"),
        (Scheme.ARXIV, "2101.00001"),
    ]
    # An ISBN counts for whole books only.
    assert identifiers_of(isbn="978-3-16-148410-0") == []


@pytest.mark.parametrize(
    ("text", "year", "month", "expected"),
    [
        ("2024-03-02", None, None, {"date-parts": [[2024, 3, 2]]}),
        ("2024/3", None, None, {"date-parts": [[2024, 3]]}),
        (" Spring 2024 ", None, None, {"raw": "Spring 2024"}),
        (None, "2024", 3, {"date-parts": [[2024, 3]]}),
        (None, "c. 1999", 13, {"date-parts": [[1999]]}),
        (None, " forthcoming ", None, {"raw": "forthcoming"}),
        (None, None, 3, None),
    ],
)
def test_date_parts(
    text: str | None, year: str | None, month: int | None, expected: object
) -> None:
    assert date_parts(text, year, month) == expected


def test_split_keywords() -> None:
    assert split_keywords(" a, b;c ,, a ;") == ["a", "b", "c"]
    assert split_keywords("") == []


# BibTeX


def test_bibtex_fields_and_names() -> None:
    export = bibtex.read(
        r"""
@mastersthesis{thesis,
  author = {Lovelace, Ada and {Radar Group}},
  title = {Engines},
  school = {Uni},
  year = {1843},
  month = {12},
  urldate = {2026-01-05},
  file = {C\:\\Thesis\\engines.pdf;notes.html;Slides:slides.key:Keynote},
}
@phdthesis{phd, title = {Rain}, type = {Habilitation}, month = {Smarch}}
@online{page, title = {Weather}, month = {²}, pages = {3 -- 4}}
@weird{odd, title = {Odd \verb}, number = {7}}
"""
    )
    thesis, phd, page, odd = export.papers
    assert thesis.csl["genre"] == "Master's thesis"
    assert thesis.csl["publisher"] == "Uni"
    assert thesis.csl["issued"] == {"date-parts": [[1843, 12]]}
    assert thesis.csl["accessed"] == {"date-parts": [[2026, 1, 5]]}
    assert thesis.csl["author"][0] == {"family": "Lovelace", "given": "Ada"}
    assert thesis.csl["author"][1] == {"literal": "Radar Group"}
    assert [(f.path, f.media_type, f.description) for f in thesis.files] == [
        ("C:\\Thesis\\engines.pdf", None, None),
        ("notes.html", None, None),
        ("slides.key", None, "Slides"),
    ]
    assert phd.csl["genre"] == "Habilitation"
    assert "issued" not in phd.csl  # no year, an unknown month
    # A month that is a digit but no number is no month (not a lost entry).
    assert page.csl["type"] == "webpage"
    assert page.csl["page"] == "3-4"
    assert "issued" not in page.csl
    assert (odd.csl["type"], odd.csl["number"]) == ("document", "7")
    # pylatexenc gives up on "\verb": only the braces are dropped.
    assert odd.csl["title"] == "Odd \\verb"


def test_bibtex_media_types() -> None:
    [paper] = bibtex.read(
        "@article{a, title={A}, file={:a.pdf:PDF;:b.htm:text/html;:c.html:HTML}}"
    ).papers
    assert [f.media_type for f in paper.files] == [
        "application/pdf",
        "text/html",
        "text/html",
    ]


def test_bibtex_broken_entries() -> None:
    # A repeated field fails the whole file in pybtex; read entry by entry,
    # nothing is left.
    broken = bibtex.read("@article{a, title={x}, title={y}}")
    assert broken.papers == []
    assert broken.problems[0].startswith("An entry could not be read")
    assert broken.problems[-1].startswith("The file could not be read as BibTeX")
    # One broken entry among good ones: the others are read.
    mixed = bibtex.read(
        "@article{a, title={x}}\n@article{b, title={y}, title={z}}\n"
        "@article{a, title={again}}\n"
    )
    assert [p.source_key for p in mixed.papers] == ["a", "a-2"]
    assert len(mixed.problems) == 2


def test_bibtex_one_line_comments() -> None:
    # Emacs's bibtex-mode starts files so; BibTeX skips such a line (a
    # real arXiv source failed to import).
    found = bibtex.read(
        "@Comment -*- bibtex-align-at-equal-sign: t; fill-column: nil; -*-\n"
        "@comment{kept apart}\n@string{PRL={Phys. Rev. Lett.}}\n"
        "@article{a, title={Scaling theory}, journal=PRL, year={1979}}\n"
    )
    assert found.problems == []
    [paper] = found.papers
    assert paper.csl["container-title"] == "Phys. Rev. Lett."


def test_bibtex_jabref_groups() -> None:
    export = bibtex.read(
        """@article{a, title={A}, groups={Inner, Elsewhere}}

@Comment{jabref-meta: grouping:
0 AllEntriesGroup:;
not a group line;
1 StaticGroup:Outer\\;0\\;1\\;\\;\\;;
2 KeywordGroup:Search\\;0\\;keywords\\;x\\;0\\;0\\;;
2 ExplicitGroup:Inner\\;0\\;\\;;
}
"""
    )
    assert export.collections == [("Outer",), ("Outer", "Inner")]
    [paper] = export.papers
    assert paper.collections == [("Outer", "Inner"), ("Elsewhere",)]


# RIS


def test_ris_details() -> None:
    export = ris.read(
        """TY  - CHAP
AU  - Lovelace, Ada, Jr.
AU  - Radar Working Group
A2  - Babbage, Charles
TI  - Engines
T2  - Collected Notes
PY  - 1843
SP  - 7
SN  - 978-3-16-148410-0
UR  - https://example.org/engines
ER  -

TY  - BOOK
TI  - Clouds
SN  - 978-3-16-148410-0
ER  -

TY  - JOUR
TI  - Rain
SN  - 1234-5678
DO  - not a doi
L1  - internal-pdf://1234/rain%20paper.pdf
L1  -
ER  -
"""
    )
    chapter, book, article = export.papers
    assert chapter.csl["author"] == [
        {"family": "Lovelace", "given": "Ada", "suffix": "Jr."},
        {"literal": "Radar Working Group"},
    ]
    assert chapter.csl["editor"] == [{"family": "Babbage", "given": "Charles"}]
    assert chapter.csl["container-title"] == "Collected Notes"
    assert chapter.csl["page"] == "7"
    assert chapter.csl["ISBN"] == "978-3-16-148410-0"
    assert chapter.identifiers == []  # a chapter shares its book's ISBN
    assert book.identifiers == [(Scheme.ISBN, "9783161484100")]
    assert article.csl["ISSN"] == "1234-5678"
    assert "DOI" not in article.csl
    assert [f.path for f in article.files] == ["rain paper.pdf"]


def test_ris_that_breaks_the_reader() -> None:
    # A continued line where the field it continues is not set yet.
    broken = ris.read("TY  - JOUR\nTI  - A\nER  -\nTY  - JOUR\ngoes on\nER  -\n")
    assert broken.problems[0].startswith("The file could not be read as RIS")
    assert ris.read("nothing here").papers == []


# CSL-JSON


def test_csl_json_odd_files() -> None:
    assert csljson.read("{not json").problems[0].startswith("The file is not valid")
    assert csljson.read('{"items": 3}').problems == [
        "The file holds no list of references."
    ]
    export = csljson.read(
        json.dumps({"items": [{"title": "A", "id": "http://x", "DOI": []}, "B"]})
    )
    [paper] = export.papers
    assert paper.csl == {"title": "A", "DOI": [], "type": "document"}
    assert (paper.identifiers, paper.source_key) == ([], "http://x")
    assert export.problems == ["Entry 2 has no title and was skipped."]


@pytest.mark.parametrize(
    ("module", "text"),
    [
        (bibtex, "@article{a, title={A}}\n@article{b, title={B}}"),
        (ris, "TY  - JOUR\nTI  - A\nER  -\nTY  - JOUR\nTI  - B\nER  -\n"),
        (csljson, json.dumps([{"title": "A"}, {"title": "B"}])),
    ],
)
def test_one_unreadable_entry_does_not_stop_the_rest(
    module: Any,  # noqa: ANN401
    text: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = module._paper

    def flaky(key: Any, entry: Any, *rest: Any) -> ExportedPaper:  # noqa: ANN401
        paper = real(key, entry, *rest)
        if paper.csl["title"] == "A":
            raise ValueError("odd")
        return paper

    monkeypatch.setattr(module, "_paper", flaky)
    export = module.read(text)
    assert [p.csl["title"] for p in export.papers] == ["B"]
    assert export.problems[0].endswith("could not be read: odd")


# Zotero RDF

NAMESPACES = (
    'xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#" '
    'xmlns:z="http://www.zotero.org/namespaces/export#" '
    'xmlns:dcterms="http://purl.org/dc/terms/" '
    'xmlns:bib="http://purl.org/net/biblio#" '
    'xmlns:foaf="http://xmlns.com/foaf/0.1/" '
    'xmlns:link="http://purl.org/rss/1.0/modules/link/" '
    'xmlns:dc="http://purl.org/dc/elements/1.1/" '
    'xmlns:prism="http://prismstandard.org/namespaces/1.2/basic/" '
    'xmlns:vcard="http://nwalsh.com/rdf/vCard#"'
)


def rdf(body: str) -> str:
    return f'<?xml version="1.0"?>\n<rdf:RDF {NAMESPACES}>{body}</rdf:RDF>'


def collection(about: str, title: str | None, *parts: str) -> str:
    name = f"<dc:title>{title}</dc:title>" if title else ""
    links = "".join(f'<dcterms:hasPart rdf:resource="{p}"/>' for p in parts)
    return f'<z:Collection rdf:about="{about}">{name}{links}</z:Collection>'


def test_zotero_collection_loops_and_repeats() -> None:
    export = zotero.read(
        rdf(
            collection("#c1", "Thesis", "#c2", "#c4", "#c5", "#c6")
            + collection("#c2", "Loop", "#c3")
            + collection("#c3", "Inner", "#c2", "#item_1")
            + collection("#c4", "Same", "#item_1")
            + collection("#c5", "Same")
            + collection("#c6", None)
            + '<bib:Article rdf:about="#item_1"><z:itemType>journalArticle'
            "</z:itemType><dc:title>A</dc:title></bib:Article>"
        )
    )
    assert export.collections == [
        ("Thesis",),
        ("Thesis", "Loop"),
        ("Thesis", "Loop", "Inner"),
        ("Thesis", "Same"),
        ("Thesis", "Untitled collection"),
    ]
    [paper] = export.papers
    assert paper.collections == [("Thesis", "Loop", "Inner"), ("Thesis", "Same")]


def test_zotero_item_details() -> None:
    export = zotero.read(
        rdf(
            """
<bib:BookSection rdf:about="#item_1">
  <z:itemType>bookSection</z:itemType>
  <dc:title>Engines</dc:title>
  <dcterms:isPartOf>
    <bib:Part><dc:title>Part II</dc:title></bib:Part>
  </dcterms:isPartOf>
  <dcterms:isPartOf>
    <bib:Part><dc:title> </dc:title></bib:Part>
  </dcterms:isPartOf>
  <dcterms:isPartOf>
    <bib:Book><dc:title>Collected Notes</dc:title></bib:Book>
  </dcterms:isPartOf>
  <prism:volume>3</prism:volume>
  <prism:number>7</prism:number>
  <z:castMembers>
    <rdf:Seq><rdf:li><foaf:Person><foaf:surname>Byron</foaf:surname>
    <foaf:givenName>Ada</foaf:givenName></foaf:Person></rdf:li></rdf:Seq>
  </z:castMembers>
  <z:notes>not people</z:notes>
  <bib:authors>
    <rdf:Seq><rdf:li><foaf:Person><foaf:surname>Lovelace</foaf:surname>
    </foaf:Person></rdf:li></rdf:Seq>
  </bib:authors>
  <dc:date>Spring 1843</dc:date>
  <dcterms:dateSubmitted>some day</dcterms:dateSubmitted>
  <dc:publisher><foaf:Organization><vcard:adr><vcard:Address>
  </vcard:Address></vcard:adr></foaf:Organization></dc:publisher>
  <bib:presentedAt><bib:Conference><dc:title>Engine Days</dc:title>
  </bib:Conference></bib:presentedAt>
  <dcterms:isReferencedBy rdf:resource="#item_2"/>
  <link:link rdf:resource="#item_3"/>
  <dc:description>arXiv: 2101.00001 [physics]
PMID: 12345</dc:description>
</bib:BookSection>
<bib:Memo rdf:about="#item_2"><z:itemType>note</z:itemType></bib:Memo>
<z:Attachment rdf:about="#item_3">
  <z:itemType>attachment</z:itemType>
  <z:path>file:///home/ada/engines%20notes.pdf</z:path>
</z:Attachment>
<bib:Memo rdf:about="#item_4"><z:itemType>note</z:itemType>
  <rdf:value> </rdf:value></bib:Memo>
<z:Attachment rdf:about="#item_5">
  <z:itemType>attachment</z:itemType>
  <dc:title>A web page</dc:title>
</z:Attachment>
<bib:Conference rdf:about="#item_6">
  <z:itemType>conferencePaper</z:itemType>
  <bib:presentedAt><bib:Conference/></bib:presentedAt>
  <dc:publisher><foaf:Organization><foaf:name>Press</foaf:name>
  </foaf:Organization></dc:publisher>
</bib:Conference>
"""
        )
    )
    # The bare web link and the empty notes are left out.
    assert export.notes == []
    section, untitled = export.papers
    csl = section.csl
    assert csl["type"] == "chapter"
    assert csl["section"] == "Part II"
    assert csl["container-title"] == "Collected Notes"
    assert (csl["volume"], csl["number"]) == ("3", "7")
    assert csl["author"] == [{"literal": "Lovelace"}]
    assert csl["cast-member"] == [{"family": "Byron", "given": "Ada"}]
    assert "notes" not in csl
    assert csl["issued"] == {"date-parts": [[1843]], "raw": "Spring 1843"}
    assert csl["accessed"] == {"raw": "some day"}
    assert "publisher" not in csl and "publisher-place" not in csl
    assert csl["event-title"] == "Engine Days"
    assert "note" not in csl
    assert section.identifiers == [
        (Scheme.ARXIV, "2101.00001"),
        (Scheme.PMID, "12345"),
    ]
    assert section.notes == []
    assert [f.path for f in section.files] == ["/home/ada/engines notes.pdf"]
    assert untitled.csl == {
        "type": "paper-conference",
        "title": "(untitled)",
        "publisher": "Press",
    }


def test_zotero_unreadable_item(monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(self: Any, subject: Any, kind: str) -> ExportedPaper:  # noqa: ANN401
        raise ValueError("odd")

    monkeypatch.setattr(zotero._Reader, "paper", broken)
    export = zotero.read(
        rdf(
            '<bib:Article rdf:about="#item_1"><z:itemType>journalArticle'
            "</z:itemType><dc:title>A</dc:title></bib:Article>"
        )
    )
    assert (export.papers, export.problems) == ([], ["An item could not be read: odd"])


# Finding the export in an upload


@pytest.mark.parametrize(
    ("data", "text"),
    [
        ("Müller".encode(), "Müller"),
        ("\ufeffMüller\x00".encode(), "Müller"),
        (
            "M\u00fcller \u2013 \u201cx\u201d".encode("cp1252"),
            "M\u00fcller \u2013 \u201cx\u201d",
        ),
        (b"M\x81ller", "M\x81ller"),  # not even Windows-1252
    ],
)
def test_decode(data: bytes, text: str) -> None:
    assert run_module._decode(data) == text


@pytest.mark.parametrize(
    ("name", "text", "format_"),
    [
        ("export.BIB", "", "bibtex"),
        ("Exported Items", '<?xml version="1.0"?><rdf:RDF>', "zotero-rdf"),
        ("library", "  @article{a,", "bibtex"),
        ("library", "% JabRef\n@article{a,", "bibtex"),
        ("library", "TY  - JOUR", "ris"),
        ("library", ' [{"title": "A"}]', "csl-json"),
        ("library", '{"items": []}', "csl-json"),
    ],
)
def test_guess(name: str, text: str, format_: str) -> None:
    assert run_module._guess(name, text) == format_


def test_open_a_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(NotAnExport, match="in the folder"), open_export(tmp_path, ""):
        pass
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "library.ris").write_text("TY  - JOUR\nER  -\n")
    with open_export(tmp_path, "export") as (format_, text, files):
        assert format_ == "ris"
        assert text.startswith("TY")
        assert isinstance(files, FolderFiles)
    monkeypatch.setattr(run_module, "MAX_EXPORT_BYTES", 5)
    with pytest.raises(NotAnExport, match="at most 0 MB"), open_export(tmp_path, ""):
        pass


def test_open_a_zip_or_a_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("__MACOSX/._library.bib", b"junk")
        archive.writestr("Library/files/1/cited.json", b"[]")
        archive.writestr("Library/library.bib", b"@article{a, title={A}}")
    upload = tmp_path / "upload"
    upload.write_bytes(buffer.getvalue())
    with open_export(upload, "Library.zip") as (format_, text, files):
        assert (format_, isinstance(files, ZipFiles)) == ("bibtex", True)
        assert text.startswith("@article")
    single = tmp_path / "single"
    single.write_text("TY  - JOUR\nER  -\n")
    with open_export(single, "export.txt") as (format_, _, files):
        assert (format_, isinstance(files, NoFiles)) == ("ris", True)
    monkeypatch.setattr(run_module, "MAX_EXPORT_BYTES", 5)
    for path in (upload, single):
        with pytest.raises(NotAnExport, match="at most"), open_export(path, "x"):
            pass
