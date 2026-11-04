import pytest

from paperus.identifiers import (
    InvalidIdentifier,
    Scheme,
    implied_by_doi,
    normalize,
)

DOI = "10.1038/s41586-020-2649-2"


@pytest.mark.parametrize(
    ("scheme", "given", "expected"),
    [
        (Scheme.DOI, DOI, DOI),
        (Scheme.DOI, "10.1038/S41586-020-2649-2", DOI),
        (Scheme.DOI, " https://doi.org/10.1038/s41586-020-2649-2 ", DOI),
        (Scheme.DOI, "doi:10.1038/s41586-020-2649-2", DOI),
        (Scheme.DOI, "https://dx.doi.org/10.1038/s41586-020-2649-2", DOI),
        (Scheme.ARXIV, "2101.00001", "2101.00001"),
        (Scheme.ARXIV, "arXiv:2101.00001v3", "2101.00001"),
        (Scheme.ARXIV, "https://arxiv.org/abs/2101.00001v1", "2101.00001"),
        (Scheme.ARXIV, "hep-th/9901001v2", "hep-th/9901001"),
        (Scheme.ISBN, "978-0-306-40615-7", "9780306406157"),
        (Scheme.ISBN, "0-306-40615-2", "9780306406157"),
        (Scheme.ISBN, "ISBN 0 8044 2957 X", "9780804429573"),
        (Scheme.PMID, "PMID: 32939066", "32939066"),
        (Scheme.URL, " https://example.org/notes ", "https://example.org/notes"),
    ],
)
def test_normalize(scheme: Scheme, given: str, expected: str) -> None:
    assert normalize(scheme, given) == expected


@pytest.mark.parametrize(
    ("scheme", "given"),
    [
        (Scheme.DOI, ""),
        (Scheme.DOI, "10.1/x"),
        (Scheme.DOI, "11.1038/abc"),
        (Scheme.ARXIV, "2101.1"),
        (Scheme.ISBN, "978-0-306-40615-8"),
        (Scheme.ISBN, "0-306-40615-3"),
        (Scheme.PMID, "0123"),
        (Scheme.URL, "ftp://example.org"),
    ],
)
def test_normalize_rejects(scheme: Scheme, given: str) -> None:
    with pytest.raises(InvalidIdentifier):
        normalize(scheme, given)


def test_arxiv_doi_implies_arxiv_id() -> None:
    assert implied_by_doi("10.48550/arxiv.2101.00001") == [(Scheme.ARXIV, "2101.00001")]
    assert implied_by_doi(DOI) == []
