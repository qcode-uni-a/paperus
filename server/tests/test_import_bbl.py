"""References of LaTeX papers: .bbl files, arXiv sources, import by arXiv ID."""

import gzip
import io
import tarfile
import uuid
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Literal

import httpx2
import pytest
from fastapi.testclient import TestClient
from procrastinate import App
from procrastinate.testing import InMemoryConnector
from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.identifiers import Scheme
from paperus.importing import Export, ExportedPaper, bbl, references
from paperus.importing import run as run_module
from paperus.importing.run import NotAnExport, open_export, open_upload, run_import
from paperus.models import Collection, CollectionItem, Import, Item
from paperus.storage import BlobStore
from tests.conftest import FakeDOIRegistry
from tests.people import Person

# Modelled on biber's output (biblatex 3.x), shortened.
BIBLATEX = r"""% $ biblatex auxiliary file $
% $ biblatex bbl format version 3.2 $
% Do not modify the above lines!
\begingroup
\makeatletter
\@ifundefined{ver@biblatex.sty}
  {\@latex@error
     {Missing 'biblatex' package}
     {The bibliography requires the 'biblatex' package.}
      \aftergroup\endinput}
  {}
\endgroup

\refsection{0}
  \datalist[entry]{nty/global//global/global}
    \entry{kitaev2001}{article}{}
      \name{author}{1}{}{%
        {{hash=a1}{%
           family={Kitaev},
           familyi={K\bibinitperiod},
           given={Alexei\bibnamedelima Yu.},
           giveni={A\bibinitperiod\bibinitdelim Y\bibinitperiod}}}%
      }
      \strng{namehash}{a1}
      \field{sortinit}{K}
      \field{title}{Unpaired {Majorana} fermions in quantum wires}
      \field{journaltitle}{Physics-Uspekhi}
      \field{volume}{44}
      \field{number}{10S}
      \field{year}{2001}
      \field{pages}{131\bibrangedash 136}
      \range{pages}{6}
      \verb{doi}
      \verb 10.1070/1063-7869/44/10S/S29
      \endverb
      \verb{url}
      \verb https://example.org/kitaev%20chain
      \endverb
    \endentry
    \entry{muller2024}{misc}{}{}
      \name{author}{2}{}{%
        {{hash=b2}{%
           family={M{\"u}ller},
           familyi={M\bibinitperiod},
           given={J{\"o}rg},
           giveni={J\bibinitperiod},
           prefix={von},
           prefixi={v\bibinitperiod},
           suffix={Jr.},
           suffixi={J\bibinitperiod}}}%
        {{hash=c3}{%
           family={{Radar Working Group}},
           familyi={R\bibinitperiod}}}%
      }
      \field{title}{Rain over the {Alps}}
      \field{subtitle}{an $\alpha$-field study}
      \field{eprinttype}{arXiv}
      \field{eprintclass}{physics.ao-ph}
      \field{year}{2024}
      \field{month}{3}
      \verb{eprint}
      \verb 2403.01234v2
      \endverb
    \endentry
    \entry{tinkham}{book}{}
      \name{author}{1}{}{%
        {{uniquename=0,hash=d4}{Tinkham}{T\bibinitperiod}{Michael}{M\bibinitperiod}{}{}{}{}}%
      }
      \list{publisher}{1}{%
        {Dover}%
      }
      \list{location}{1}{%
        {New York}%
      }
      \field{title}{Introduction to Superconductivity}
      \field{edition}{2}
      \field{year}{2004}
      \field{isbn}{0486435032}
    \endentry
    \entry{set1}{set}{}
    \endentry
  \enddatalist
  \datalist[entry]{nyt/global//global/global}
    \entry{kitaev2001}{article}{}
      \field{title}{Repeated in a second list}
    \endentry
  \enddatalist
\endrefsection
\endinput
"""

# Modelled on apsrev4-2 (REVTeX) output: preamble shortened, lines as BibTeX
# breaks them (with % inside long words).
PREAMBLE = r"""%apsrev4-2.bst 2019-01-14 (MD) hand-edited version of apsrev4-1.bst
\begin{thebibliography}{6}%
\makeatletter
\providecommand \@ifxundefined [1]{%
 \@ifx{#1\undefined}
}%
\providecommand \bibnamefont  [1]{#1}%
\providecommand \Eprint [0]{\href }%
\providecommand \doibase [0]{https://doi.org/}%
\providecommand \bibinfo  [0]{\@secondoftwo}%
\let\auto@bib@innerbib\@empty
%</preamble>
"""
REVTEX = (
    PREAMBLE
    + r"""\bibitem [{\citenamefont {Kitaev}(2001)}]{kitaev2001unpaired}%
  \BibitemOpen
  \bibfield  {author} {\bibinfo {author} {\bibfnamefont {A.~Y.}\ \bibnamefont
  {Kitaev}},\ }\bibfield  {title} {\bibinfo {title} {Unpaired majorana
  fermions in quantum wires},\ }\href {https://doi.org/10.1070/1063-7869/44/%
  10S/S29} {\bibfield  {journal} {\bibinfo  {journal} {Physics-Uspekhi}\
  }\textbf {\bibinfo {volume} {44}},\ \bibinfo {pages} {131--136} (\bibinfo
  {year} {2001})}\BibitemShut {NoStop}%
\bibitem [{\citenamefont {Yannouleas}\ and\ \citenamefont
  {Landman}(2022{\natexlab{b}})}]{Yannouleas:2022}%
  \BibitemOpen
  \bibfield  {author} {\bibinfo {author} {\bibfnamefont {C.}~\bibnamefont
  {Yannouleas}}\ and\ \bibinfo {author} {\bibfnamefont {U.}~\bibnamefont
  {Landman}},\ }\href {\doibase 10.1103/PhysRevB.105.205302} {\bibfield
  {journal} {\bibinfo  {journal} {Phys. Rev. B}\ }\textbf {\bibinfo {volume}
  {105}},\ \bibinfo {pages} {205302} (\bibinfo {year}
  {2022}{\natexlab{b}})}\BibitemShut {NoStop}%
\bibitem [{\citenamefont {Miles}\ \emph {et~al.}(2023)}]{miles2023kitaev}%
  \BibitemOpen
  \bibfield  {author} {\bibinfo {author} {\bibfnamefont {S.}~\bibnamefont
  {Miles}},\ and\ \bibinfo {author} {\bibnamefont {{Quantum Dot
  Collaboration}}},\ }\href@noop {} {\bibinfo {title} {Kitaev chain in an
  alternating quantum dot-andreev bound state array}} (\bibinfo {year}
  {2023}),\ \Eprint {https://arxiv.org/abs/2309.15777} {arXiv:2309.15777
  [cond-mat.mes-hall]} \BibitemShut {NoStop}%
\bibitem [{\citenamefont {Koppens}\ \emph {et~al.}(2006)}]{Koppens:2006}%
  \BibitemOpen
  \bibfield  {author} {\bibinfo {author} {\bibfnamefont {F.~H.~L.}\
  \bibnamefont {Koppens}}\ and\ \bibinfo {author} {\bibfnamefont
  {C.}~\bibnamefont {Buizert}},\ }\href@noop {} {\bibfield  {journal}
  {\bibinfo  {journal} {Nature}\ }\textbf {\bibinfo {volume} {442}},\ \bibinfo
  {pages} {766} (\bibinfo {year} {2006})}\BibitemShut {NoStop}%
\bibitem [{\citenamefont {Tinkham}(2004)}]{tinkham}%
  \BibitemOpen
  \bibfield  {author} {\bibinfo {author} {\bibfnamefont {M.}~\bibnamefont
  {Tinkham}},\ }\href@noop {} {\emph {\bibinfo {title} {Introduction to
  Superconductivity}}},\ \bibinfo {edition} {2nd}\ ed.\ (\bibinfo  {publisher}
  {Dover},\ \bibinfo {address} {New York},\ \bibinfo {year} {2004})\BibitemShut
  {NoStop}%
\bibitem [{\citenamefont {Doe}(2020)}]{doe2020}%
  \BibitemOpen
  \bibfield  {author} {\bibinfo {author} {\bibfnamefont {J.}~\bibnamefont
  {Doe}},\ }in\ \href@noop {} {\emph {\bibinfo {booktitle} {Proceedings of
  Rain}}}\ (\bibinfo {year} {2020})\ \url{https://example.org/rain}\BibitemShut
  {NoStop}%
\bibitem [{Note1()}]{Note1}%
  \BibitemOpen
  \bibinfo {note} {Appendix B presents a simplified calculation.}\BibitemShut
  {Stop}%
\end{thebibliography}%
"""
)

# plain/unsrt (\newblock), ieeetr (``title,''), amsplain (\emph{title}).
PLAIN = r"""\begin{thebibliography}{10}

\bibitem{kitaev}
A.~Y. Kitaev.
\newblock Unpaired {M}ajorana fermions in quantum wires.
\newblock {\em Physics-Uspekhi}, 44(10S):131, 2001.
\newblock \doi{10.1070/1063-7869/44/10S/S29}.

\bibitem{lovelace}
Ada Lovelace, Charles Babbage, and others.
\newblock The diffusion of rain.
\newblock {\em arXiv preprint arXiv:2611.00001}, 2026.

\bibitem{witten}
E.~Witten.
\newblock Bound states of strings and $p$-branes.
\newblock Preprint hep-th/9510135, 1995.

\bibitem{data}
Radar group.
\newblock Weather data.
\newblock \url{https://example.org/data\_set}, 2020.

\bibitem{wimmer}
M.~Wimmer.
\newblock Private communication, 2023.

\bibitem{schlawin}
F.~Schlawin, D.~M. Kennes, and M.~A. Sentef.
\newblock Cavity quantum materials.
\newblock {\em Applied Physics Reviews}, 9(1), 2022.

\bibitem{ieee}
F.~Schlawin and M.~A. Sentef, ``Cavity {QED} materials,'' {\em Rev. Mod.
  Phys.}, vol.~9, 2023.

\bibitem[Kitaev(2001)]{ams}
A.~Y. Kitaev, \emph{Unpaired {M}ajorana fermions}, Physics-Uspekhi \textbf{44}
  (2001), 131, \href{https://doi.org/10.1070/1063-7869%2F44%2F10S%2FS29}{doi}.

\bibitem{eprint}
J.~Doe, Notes on rain, \eprint{2101.00001v3}.

\bibitem{nothing}
\end{thebibliography}
"""

TEX = r"""\documentclass[aps,prb]{revtex4-2}
% \title{Commented out}
\begin{document}
\title[Short]{Poor man's {M}ajorana \\ states\thanks{Funded by rain.}}
\maketitle
As shown~\cite{kitaev2001unpaired,Koppens:2006} and \citep[p.~3]{tinkham}.
\bibliography{refs}
\end{document}
"""


def by_key(found: Sequence[ExportedPaper]) -> dict[str, bbl.Reference]:
    """References by their key."""
    assert all(isinstance(r, bbl.Reference) for r in found)
    return {r.source_key: r for r in found if isinstance(r, bbl.Reference)}


def test_biblatex() -> None:
    export = bbl.read(BIBLATEX)
    assert export.format == "bbl"
    found = by_key(export.papers)
    assert list(found) == ["kitaev2001", "muller2024", "tinkham"]
    kitaev = found["kitaev2001"]
    assert kitaev.style == "biblatex"
    assert kitaev.csl == {
        "type": "article-journal",
        "title": "Unpaired Majorana fermions in quantum wires",
        "author": [{"family": "Kitaev", "given": "Alexei Yu."}],
        "container-title": "Physics-Uspekhi",
        "volume": "44",
        "issue": "10S",
        "page": "131-136",
        "URL": "https://example.org/kitaev%20chain",
        "issued": {"date-parts": [[2001]]},
        "DOI": "10.1070/1063-7869/44/10s/s29",
        "citation-key": "kitaev2001",
    }
    assert kitaev.identifiers == [(Scheme.DOI, "10.1070/1063-7869/44/10s/s29")]
    assert kitaev.text == (
        "Kitaev. Unpaired Majorana fermions in quantum wires. Physics-Uspekhi. "
        "44. 131-136. 2001"
    )
    muller = found["muller2024"]
    assert muller.csl["type"] == "article"
    assert muller.csl["title"] == r"Rain over the Alps: an $\alpha$-field study"
    assert muller.csl["author"] == [
        {
            "family": "Müller",
            "given": "Jörg",
            "non-dropping-particle": "von",
            "suffix": "Jr.",
        },
        {"literal": "Radar Working Group"},
    ]
    assert muller.csl["issued"] == {"date-parts": [[2024, 3]]}
    assert muller.identifiers == [(Scheme.ARXIV, "2403.01234")]
    tinkham = found["tinkham"]
    assert tinkham.csl["author"] == [{"family": "Tinkham", "given": "Michael"}]
    assert (tinkham.csl["publisher"], tinkham.csl["publisher-place"]) == (
        "Dover",
        "New York",
    )
    assert tinkham.identifiers == [(Scheme.ISBN, "9780486435039")]
    assert bbl.style_of(list(found.values())) == "biblatex"


def test_revtex() -> None:
    found = by_key(bbl.references(REVTEX))
    assert "Note1" not in found  # REVTeX's footnotes are no references
    kitaev = found["kitaev2001unpaired"]
    assert kitaev.style == "revtex"
    assert kitaev.csl["title"] == "Unpaired majorana fermions in quantum wires"
    assert kitaev.csl["author"] == [{"family": "Kitaev", "given": "A. Y."}]
    assert kitaev.csl["page"] == "131-136"
    # The DOI was broken over two lines with %.
    assert kitaev.identifiers == [(Scheme.DOI, "10.1070/1063-7869/44/10s/s29")]
    assert kitaev.text == (
        "A. Y. Kitaev, Unpaired majorana fermions in quantum wires, "
        "Physics-Uspekhi 44, 131\u2013136 (2001)"
    )
    yannouleas = found["Yannouleas:2022"]
    assert yannouleas.identifiers == [(Scheme.DOI, "10.1103/physrevb.105.205302")]
    assert yannouleas.csl["issued"] == {"date-parts": [[2022]]}
    assert "title" not in yannouleas.csl  # Phys. Rev. styles print none
    miles = found["miles2023kitaev"]
    assert miles.identifiers == [(Scheme.ARXIV, "2309.15777")]
    assert miles.csl["type"] == "article"
    assert miles.csl["author"][1] == {"literal": "Quantum Dot Collaboration"}
    koppens = found["Koppens:2006"]
    assert (koppens.identifiers, koppens.csl["container-title"]) == ([], "Nature")
    assert koppens.text.endswith("Nature 442, 766 (2006)")
    tinkham = found["tinkham"]
    assert (tinkham.csl["type"], tinkham.csl["publisher"]) == ("book", "Dover")
    assert tinkham.csl["title"] == "Introduction to Superconductivity"
    doe = found["doe2020"]
    assert (doe.csl["type"], doe.csl["container-title"]) == (
        "book",
        "Proceedings of Rain",
    )
    assert doe.csl["URL"] == "https://example.org/rain"


def test_plain_styles() -> None:
    found = by_key(bbl.references(PLAIN))
    assert all(r.style == "plain" for r in found.values())
    kitaev = found["kitaev"]
    assert kitaev.identifiers == [(Scheme.DOI, "10.1070/1063-7869/44/10s/s29")]
    assert kitaev.csl["title"] == "Unpaired Majorana fermions in quantum wires"
    assert kitaev.text.startswith("A. Y. Kitaev. Unpaired Majorana fermions")
    lovelace = found["lovelace"]
    assert lovelace.identifiers == [(Scheme.ARXIV, "2611.00001")]
    assert lovelace.csl["author"] == [
        {"literal": "Ada Lovelace"},
        {"literal": "Charles Babbage"},
    ]
    assert found["witten"].identifiers == [(Scheme.ARXIV, "hep-th/9510135")]
    data = found["data"]
    assert (data.identifiers, data.csl["URL"]) == ([], "https://example.org/data_set")
    assert found["wimmer"].identifiers == []
    assert found["ieee"].csl["title"] == "Cavity QED materials"
    ams = found["ams"]
    assert ams.csl["title"] == "Unpaired Majorana fermions"
    assert ams.identifiers == [(Scheme.DOI, "10.1070/1063-7869/44/10s/s29")]
    assert found["eprint"].identifiers == [(Scheme.ARXIV, "2101.00001")]
    assert found["nothing"].text == ""
    # Two lists (e.g. a .bbl per chapter) are read one after the other.
    assert len(bbl.references(PLAIN + PLAIN)) == 2 * len(found)


def test_odd_input() -> None:
    assert bbl.read("no references here").problems == [
        "No references (\\bibitem or \\entry) were found."
    ]
    assert bbl.style_of([]) == "none"
    # Unclosed groups and arguments run to the end instead of failing.
    odd = bbl.references(
        "\\begin{thebibliography}{1}\\bibitem[{x]{a} \\bibinfo{title}{Open"
        "\\bibitem{b} \\href{https://example.org/x}"
    )
    assert [r.source_key for r in odd] == ["b"]
    odd = bbl.references(
        "\\begin{thebibliography}{1}\\bibitem{a} \\bibinfo{title} \\emph"
        "\\bibitem{b} \\bibinfo{title}{Open \\url{x"
    )
    assert [r.source_key for r in odd] == ["a", "b"]
    assert odd[1].csl["title"] == "Open x"
    entry = bbl.references(
        "\\entry{a}{online}{}\\name{author}{1}{}{{{hash=1}{Plain Name}}}"
        "\\field{title}{T}\\endentry"
    )[0]
    assert entry.csl["author"] == [{"literal": "Plain Name"}]
    assert entry.csl["type"] == "webpage"


def test_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bbl, "MAX_REFERENCES", 2)
    export = bbl.read(PLAIN)
    assert [p.source_key for p in export.papers] == ["kitaev", "lovelace"]
    assert export.problems == ["Only the first 2 references were read."]
    assert len(bbl.read(BIBLATEX).papers) == 2
    monkeypatch.setattr(bbl, "MAX_REFERENCE", 20)
    cut = bbl.references(PLAIN)[0]
    assert (cut.source_key, cut.text) == ("kitaev", "A. Y. Kitae")


def test_tex_title_and_cited_keys() -> None:
    assert bbl.tex_title(TEX) == "Poor man's Majorana states"
    assert bbl.tex_title("\\documentclass{article}") is None
    assert bbl.cited_keys(TEX) == {"kitaev2001unpaired", "koppens:2006", "tinkham"}
    assert bbl.cited_keys(TEX + "\\nocite{*}") is None
    assert bbl.cited_keys("no citations") is None


# --- archives ----------------------------------------------------------------


def tar_bytes(members: dict[str, bytes], mode: Literal["w", "w:gz"] = "w:gz") -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode=mode) as archive:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


BIB = rb"""@article{kitaev2001unpaired, title={Unpaired}, doi={10.1070/x}}
@article{Koppens:2006, title={Driven oscillations}}
@article{uncited, title={Not cited}}
"""


def opened(tmp_path: Path, data: bytes, name: str) -> run_module.Opened:
    path = tmp_path / "upload"
    path.write_bytes(data)
    with open_upload(path, name) as result:
        return result


def test_arxiv_sources(tmp_path: Path) -> None:
    # An arXiv source: the .bbl wins over the .bib beside it.
    source = tar_bytes(
        {
            "main.tex": TEX.encode(),
            "main.bbl": REVTEX.encode(),
            "refs.bib": BIB,
            "figures/plot.pdf": b"%PDF-1.4",
        }
    )
    result = opened(tmp_path, source, "arXiv:2407.12088")
    assert (result.format, result.latex) == ("bbl", True)
    assert result.title == "Poor man's Majorana states"
    assert "kitaev2001unpaired" in result.text
    # Without a .bbl: the .bib, limited to what the .tex cites.
    source = tar_bytes({"paper/main.tex": TEX.encode(), "paper/refs.bib": BIB})
    result = opened(tmp_path, source, "source.tar.gz")
    assert (result.format, result.cited) == (
        "bibtex",
        {"kitaev2001unpaired", "koppens:2006", "tinkham"},
    )
    # A thebibliography in the .tex itself, gzipped alone (arXiv's single files).
    single = gzip.compress((TEX + PLAIN).encode())
    result = opened(tmp_path, single, "2407.12088.gz")
    assert (result.format, result.title) == ("bbl", "Poor man's Majorana states")
    # A plain tar; a gzipped .bib is an ordinary export.
    result = opened(tmp_path, tar_bytes({"a.bbl": PLAIN.encode()}, "w"), "x.tar")
    assert result.format == "bbl"
    result = opened(tmp_path, gzip.compress(BIB), "refs.bib.gz")
    assert (result.format, result.latex) == ("bibtex", False)
    # A .bbl or .tex alone.
    assert opened(tmp_path, BIBLATEX.encode(), "main.bbl").format == "bbl"
    assert opened(tmp_path, PLAIN.encode(), "references").format == "bbl"
    with pytest.raises(NotAnExport, match="No reference list"):
        opened(tmp_path, TEX.encode(), "main.tex")
    # The old interface still gives (format, text, files).
    path = tmp_path / "plain.bbl"
    path.write_text(PLAIN)
    with open_export(path, "plain.bbl") as (format_, text, _):
        assert (format_, text) == ("bbl", PLAIN)
    assert run_module._guess("library", PLAIN) == "bbl"


def test_zips_of_latex_projects(tmp_path: Path) -> None:
    project = zip_bytes({"main.tex": TEX.encode(), "refs.bib": BIB})
    result = opened(tmp_path, project, "Overleaf.zip")
    assert (result.format, result.latex, result.title) == (
        "bibtex",
        True,
        "Poor man's Majorana states",
    )
    # arXiv's processing notes are no CSL-JSON export.
    project = zip_bytes({"00README.json": b"{}", "main.tex": (TEX + PLAIN).encode()})
    assert opened(tmp_path, project, "source.zip").format == "bbl"
    # A Zotero export with a LaTeX file attached deeper down stays an export.
    export = zip_bytes(
        {
            "Library/Library.bib": BIB,
            "Library/files/3/paper.tex": TEX.encode(),
        }
    )
    result = opened(tmp_path, export, "Library.zip")
    assert (result.format, result.latex) == ("bibtex", False)


def test_hostile_archives(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Names leading out of the archive and links are only read, never written.
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        data = PLAIN.encode()
        info = tarfile.TarInfo("../../escaped.bbl")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo("link.bbl")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)
    result = opened(tmp_path, buffer.getvalue(), "evil.tar.gz")
    assert result.text == PLAIN
    assert not (tmp_path.parent / "escaped.bbl").exists()

    many = tar_bytes({f"f{n}.txt": b"x" for n in range(5)})
    monkeypatch.setattr(run_module, "MAX_MEMBERS", 3)
    with pytest.raises(NotAnExport, match="more than 3 files"):
        opened(tmp_path, many, "many.tar.gz")
    with pytest.raises(NotAnExport, match="more than 3 files"):
        opened(tmp_path, zip_bytes({f"{n}.tex": b"" for n in range(5)}), "m.zip")
    monkeypatch.setattr(run_module, "MAX_MEMBERS", 10_000)

    monkeypatch.setattr(run_module, "MAX_UNPACKED_BYTES", 3)
    with pytest.raises(NotAnExport, match="unpacks to more than"):
        opened(tmp_path, many, "many.tar.gz")
    monkeypatch.setattr(run_module, "MAX_UNPACKED_BYTES", 2**30)
    monkeypatch.setattr(run_module, "MAX_EXPORT_BYTES", 10)
    big = {"main.bbl": PLAIN.encode()}
    with pytest.raises(NotAnExport, match="at most"):
        opened(tmp_path, tar_bytes(big, "w"), "big.tar")
    with pytest.raises(NotAnExport, match="at most"):
        opened(tmp_path, zip_bytes(big), "big.zip")
    with pytest.raises(NotAnExport, match="unpacks to more than"):
        opened(tmp_path, gzip.compress(PLAIN.encode()), "big.gz")

    monkeypatch.setattr(run_module, "MAX_EXPORT_BYTES", 2**20)
    broken = gzip.compress(PLAIN.encode())[:40]
    with pytest.raises(NotAnExport, match="could not be unpacked"):
        opened(tmp_path, broken, "broken.gz")
    truncated = tar_bytes({"a.bbl": PLAIN.encode() * 50})[:300]
    with pytest.raises(NotAnExport, match="could not be"):
        opened(tmp_path, truncated, "truncated.tar.gz")
    with pytest.raises(NotAnExport, match="No reference list"):
        opened(tmp_path, tar_bytes({"README": b"hello"}), "empty.tar.gz")


def test_arxiv_in_name() -> None:
    assert run_module.arxiv_in_name("arXiv:2401.12345v2") == "2401.12345"
    assert run_module.arxiv_in_name("2401.12345.tar.gz") == "2401.12345"
    assert run_module.arxiv_in_name("arXiv:hep-th/9901001") == "hep-th/9901001"
    assert run_module.arxiv_in_name("thesis.tar.gz") is None
    assert run_module.arxiv_in_name("arXiv:9999.99999x") is None


# --- looking references up -----------------------------------------------------


class FakeCrossref:
    """doi.org (``registry``) and Crossref's search (``matches``: the answer
    for a reference text containing the key)."""

    def __init__(self, registry: FakeDOIRegistry) -> None:
        self.registry = registry
        self.matches: dict[str, dict[str, Any]] = {}
        self.searched: list[str] = []
        self.e_print: httpx2.Response | None = None
        self.down = False

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        if self.down:
            raise httpx2.ConnectError("down", request=request)
        if request.url.host == "doi.org":
            return self.registry(request)
        if request.url.host == "arxiv.org" and self.e_print is not None:
            return self.e_print
        if request.url.host == "api.crossref.org":
            text = request.url.params["query.bibliographic"]
            self.searched.append(text)
            items = [m for key, m in self.matches.items() if key in text]
            return httpx2.Response(200, json={"message": {"items": items[:1]}})
        return httpx2.Response(404)


@pytest.fixture
def online(doi_registry: FakeDOIRegistry) -> FakeCrossref:
    return FakeCrossref(doi_registry)


SCHLAWIN = {
    "DOI": "10.1063/5.0083825",
    "title": ["Cavity quantum materials"],
    "author": [{"family": "Schlawin"}, {"family": "Kennes"}],
    "issued": {"date-parts": [[2022, 3]]},
    "score": 84.7,
}
KOPPENS = {
    "DOI": "10.1038/nature05065",
    "title": ["Driven coherent oscillations of a single electron spin"],
    "author": [{"given": "F. H. L.", "family": "Koppens"}],
    "issued": {"date-parts": [[2006]]},
    "volume": "442",
    "page": "766-771",
    "score": 105.2,
}


def records(registry: FakeDOIRegistry) -> None:
    registry.records.update(
        {
            "10.1070/1063-7869/44/10s/s29": {
                "type": "journal-article",
                "title": "Unpaired Majorana fermions in quantum wires",
                "container-title": "Physics-Uspekhi",
            },
            "10.48550/arxiv.2611.00001": {
                "type": "article-journal",
                "title": "The diffusion of rain",
            },
            "10.48550/arxiv.2309.15777": {"type": "article", "title": "Kitaev chain"},
            "10.1063/5.0083825": {
                "type": "journal-article",
                "title": "Cavity quantum materials",
            },
            "10.1038/nature05065": {
                "type": "journal-article",
                "title": "Driven coherent oscillations of a single electron spin",
            },
        }
    )


def test_lookups(online: FakeCrossref, monkeypatch: pytest.MonkeyPatch) -> None:
    records(online.registry)
    online.matches = {
        "Schlawin, D. M. Kennes": SCHLAWIN,
        # A best match Crossref is not sure of (a private communication).
        "Wimmer": {**SCHLAWIN, "author": [{"family": "Wimmer"}], "score": 20.0},
        # Sure, but of other authors.
        "Radar group": {**SCHLAWIN, "title": ["Weather data"], "score": 99},
    }
    export = bbl.read(PLAIN)
    export.papers.append(ExportedPaper(csl={"title": "Not from a .bbl"}))
    monkeypatch.setattr(references, "PAUSE", 0)
    with httpx2.Client(transport=httpx2.MockTransport(online)) as http:
        references.complete(export, http)
    found = {p.source_key: p for p in export.papers}
    assert list(found) == [
        "kitaev",
        "lovelace",
        "witten",
        "schlawin",
        "ams",
        "eprint",
        "",
    ]
    kitaev = found["kitaev"]
    assert kitaev.csl["container-title"] == "Physics-Uspekhi"  # from the registry
    assert kitaev.csl["citation-key"] == "kitaev"
    lovelace = found["lovelace"]
    assert lovelace.csl["type"] == "article"  # a preprint, as when added by DOI
    assert lovelace.identifiers == [
        (Scheme.DOI, "10.48550/arxiv.2611.00001"),
        (Scheme.ARXIV, "2611.00001"),
    ]
    # Not in the registry: kept as the reference list gives it.
    assert found["witten"].csl["title"] == "Bound states of strings and $p$-branes"
    schlawin = found["schlawin"]
    assert schlawin.identifiers == [(Scheme.DOI, "10.1063/5.0083825")]
    assert schlawin.csl["citation-key"] == "schlawin"
    assert export.problems == [
        "Not recognised: Radar group. Weather data. "
        "https://example.org/data_set, 2020.",
        "Not recognised: M. Wimmer. Private communication, 2023.",
        "Not recognised: F. Schlawin and M. A. Sentef, “Cavity QED materials,” "
        "Rev. Mod. Phys., vol. 9, 2023.",
        "Not recognised: nothing",
    ]


def test_lookups_of_structured_references(online: FakeCrossref) -> None:
    records(online.registry)
    online.matches = {"Koppens": KOPPENS, "Doe": {"score": 10}}
    export = bbl.read(REVTEX)
    with httpx2.Client(transport=httpx2.MockTransport(online)) as http:
        references.complete(export, http, pause=0)
    found = {p.source_key: p for p in export.papers}
    # No title in the reference: year, volume and first page agree.
    assert found["Koppens:2006"].identifiers == [(Scheme.DOI, "10.1038/nature05065")]
    assert found["miles2023kitaev"].csl["title"] == "Kitaev chain"
    # With fields and a title, kept unfound like a BibTeX entry would be.
    assert found["tinkham"].csl["title"] == "Introduction to Superconductivity"
    # Without a title, but a DOI: named by its reference text.
    assert found["Yannouleas:2022"].csl["title"].startswith("C. Yannouleas and")
    assert export.problems == [
        "Not recognised: J. Doe, in Proceedings of Rain (2020) https://example.org/rain"
    ]
    assert [t for t in online.searched if "Koppens" in t]


def test_lookups_offline_and_failing(online: FakeCrossref) -> None:
    export = bbl.read(PLAIN)
    references.complete(export, None)
    assert [p.source_key for p in export.papers] == [
        "kitaev",
        "lovelace",
        "witten",
        "ams",
        "eprint",
    ]
    assert len(export.problems) == 5
    online.down = True
    export = bbl.read(PLAIN)
    with httpx2.Client(transport=httpx2.MockTransport(online)) as http:
        references.complete(export, http, pause=0)
    assert len(export.papers) == 5
    # Crossref sure, but the DOI's details cannot be fetched: its title.
    online.down = False
    online.matches = {"Schlawin, D. M.": {**SCHLAWIN, "DOI": "10.1063/gone"}}
    export = Export(format="bbl", papers=[by_key(bbl.references(PLAIN))["schlawin"]])
    with httpx2.Client(transport=httpx2.MockTransport(online)) as http:
        references.complete(export, http, pause=0)
    assert export.papers[0].csl["title"] == "Cavity quantum materials"
    assert export.papers[0].identifiers == [(Scheme.DOI, "10.1063/gone")]
    # Answers that are no answers.
    for answer in (
        httpx2.Response(500),
        httpx2.Response(200, text="not json"),
        httpx2.Response(200, json={"message": {"items": []}}),
        httpx2.Response(
            200,
            json={
                "message": {
                    "items": [
                        {
                            "DOI": "nonsense",
                            "score": 99,
                            "title": ["Private communication"],
                        }
                    ]
                }
            },
        ),
    ):
        with httpx2.Client(
            transport=httpx2.MockTransport(lambda request, answer=answer: answer)
        ) as http:
            export = Export(
                format="bbl", papers=[by_key(bbl.references(PLAIN))["wimmer"]]
            )
            references.complete(export, http, pause=0)
            assert export.papers == []


@pytest.mark.parametrize(
    ("found", "sure"),
    [
        (SCHLAWIN, True),
        ({**SCHLAWIN, "score": 59.9}, False),
        ({**SCHLAWIN, "score": "high"}, False),
        ({**SCHLAWIN, "author": [{"family": "Sentef-Other"}]}, False),
        ({**SCHLAWIN, "author": [{"name": "Kennes"}]}, True),
        ({**SCHLAWIN, "author": []}, True),
        ({**SCHLAWIN, "title": ["Cavity quantum gravity of black holes"]}, False),
        ({**SCHLAWIN, "title": [], "volume": "9", "page": "011312"}, False),
        ({**SCHLAWIN, "title": [], "volume": "9", "page": "1"}, True),
        ({**SCHLAWIN, "title": [], "issued": {}, "volume": "9", "page": "1"}, False),
    ],
)
def test_confident(found: dict[str, Any], sure: bool) -> None:
    text = (
        "F. Schlawin, D. M. Kennes, Cavity quantum materials, "
        "Appl. Phys. Rev. 9, 1 (2022)"
    )
    assert references.confident(found, text) is sure


def test_short() -> None:
    assert references.short("a  b\nc") == "a b c"
    long = "word " * 40
    assert references.short(long).endswith("word …")
    assert len(references.short(long)) <= references.SHORT + 2


# --- through the import --------------------------------------------------------


def run_queued(
    db: Session, blobs: BlobStore, job_app: App, http: httpx2.Client | None
) -> None:
    assert isinstance(job_app.connector, InMemoryConnector)
    for job in list(job_app.connector.jobs.values()):
        if job["task_name"] != "paperus:import_library":
            continue
        record = db.get(Import, uuid.UUID(job["args"]["import_id"]))
        assert record is not None and record.blob_sha256 is not None
        with blobs.local_file(record.blob_sha256) as path:
            run_import(db, blobs, record, path=path, max_file_bytes=10_000, http=http)


def collection_titles(db: Session) -> dict[str, list[str]]:
    rows = db.execute(
        select(Collection.name, Item.title)
        .join(CollectionItem, CollectionItem.collection_id == Collection.id)
        .join(Item, Item.id == CollectionItem.item_id)
    ).all()
    found: dict[str, list[str]] = {}
    for name, title in rows:
        found.setdefault(name, []).append(title)
    return {name: sorted(titles) for name, titles in found.items()}


def test_import_an_arxiv_source(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
    online: FakeCrossref,
) -> None:
    records(online.registry)
    online.matches = {"Koppens": KOPPENS}
    ada = Person(client, db, "ada")
    source = tar_bytes({"main.tex": TEX.encode(), "main.bbl": REVTEX.encode()})
    response = ada.post(
        "/api/imports", files={"upload": ("source.tar.gz", source, "application/gzip")}
    )
    assert response.status_code == 201, response.text
    with httpx2.Client(transport=httpx2.MockTransport(online)) as http:
        run_queued(db, blobs, job_app, http)
    done = ada.get(f"/api/imports/{response.json()['id']}").json()
    assert (done["status"], done["format"]) == ("done", "bbl")
    report = done["report"]
    assert (report["added"], report["collections"]) == (5, 1)
    assert report["problems"] == [
        "Not recognised: J. Doe, in Proceedings of Rain (2020) https://example.org/rain"
    ]
    titles = collection_titles(db)["Poor man's Majorana states"]
    assert "Driven coherent oscillations of a single electron spin" in titles
    assert "Unpaired Majorana fermions in quantum wires" in titles


def test_import_by_arxiv_id(
    client: TestClient,
    db: Session,
    blobs: BlobStore,
    job_app: App,
    online: FakeCrossref,
) -> None:
    records(online.registry)
    online.registry.records["10.48550/arxiv.2407.12088"] = {
        "type": "article",
        "title": "High-quality poor man's Majorana bound states",
    }
    ada = Person(client, db, "ada")
    app: Any = client.app
    app.state.http = httpx2.Client(transport=httpx2.MockTransport(online))
    online.e_print = httpx2.Response(
        200,
        content=tar_bytes({"main.tex": TEX.encode(), "main.bbl": PLAIN.encode()}),
        headers={"Content-Type": "application/gzip"},
    )
    response = ada.post(
        "/api/imports/arxiv", json={"arxiv_id": "https://arxiv.org/abs/2407.12088v2"}
    )
    assert response.status_code == 201, response.text
    assert response.json()["filename"] == "arXiv:2407.12088v2"
    run_queued(db, blobs, job_app, app.state.http)
    done = ada.get(f"/api/imports/{response.json()['id']}").json()
    assert done["status"] == "done", done
    # Named as arXiv names the paper, not by the .tex.
    assert list(collection_titles(db)) == [
        "High-quality poor man's Majorana bound states"
    ]

    def refused(arxiv_id: str) -> httpx2.Response:
        return ada.post("/api/imports/arxiv", json={"arxiv_id": arxiv_id})

    assert refused("not an id").status_code == 422
    online.e_print = httpx2.Response(404)
    assert refused("2401.99999").status_code == 404
    online.e_print = httpx2.Response(503)
    assert refused("arXiv:2401.99999").status_code == 502
    online.e_print = httpx2.Response(200, content=b"%PDF-1.5 only a PDF")
    assert refused("hep-th/9901001").status_code == 422
    online.e_print = httpx2.Response(200, content=b"x" * 2000)
    app.state.settings.max_import_bytes = 1000
    assert refused("2401.99999").status_code == 413
    online.down = True
    assert refused("2401.99999").status_code == 502


def test_collection_names(
    tmp_path: Path, online: FakeCrossref, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain_only = run_module.Opened("bbl", "", run_module.NoFiles(), latex=True)
    titled = run_module.Opened(
        "bbl", "", run_module.NoFiles(), latex=True, title="From the tex"
    )
    with httpx2.Client(transport=httpx2.MockTransport(online)) as http:
        # arXiv does not know it: the .tex's title, else the file's name.
        assert run_module._collection_name(titled, "arXiv:2401.00009", http) == (
            "From the tex"
        )
        online.registry.records["10.48550/arxiv.2401.00009"] = {"type": "article"}
        assert run_module._collection_name(plain_only, "arXiv:2401.00009", http) == (
            "arXiv:2401.00009"
        )
    assert run_module._collection_name(plain_only, "main.bbl", None) == "main"
    assert run_module._collection_name(plain_only, "x.tar.gz", None) == "x"
    assert run_module._collection_name(plain_only, ".bbl", None) == "References"


def test_import_a_latex_project_with_a_bib(
    client: TestClient, db: Session, blobs: BlobStore, job_app: App
) -> None:
    ada = Person(client, db, "ada")
    project = zip_bytes({"main.tex": TEX.encode(), "refs.bib": BIB})
    response = ada.post(
        "/api/imports", files={"upload": ("Paper.zip", project, "application/zip")}
    )
    run_queued(db, blobs, job_app, None)
    done = ada.get(f"/api/imports/{response.json()['id']}").json()
    assert (done["format"], done["report"]["added"]) == ("bibtex", 2)
    assert collection_titles(db) == {
        "Poor man's Majorana states": ["Driven oscillations", "Unpaired"]
    }
