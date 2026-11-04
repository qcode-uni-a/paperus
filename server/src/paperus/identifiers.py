"""Identifiers of versions (DOI, arXiv, ISBN, …) and their normal forms.

Normal forms make the same identifier compare equal however it was typed, so
the library can recognise a work it already has.
"""

import re
from enum import StrEnum


class Scheme(StrEnum):
    DOI = "doi"
    ARXIV = "arxiv"
    ISBN = "isbn"
    PMID = "pmid"
    URL = "url"


class InvalidIdentifier(ValueError):
    def __init__(self, scheme: Scheme, value: str) -> None:
        super().__init__(f"not a valid {scheme.value}: {value!r}")
        self.scheme = scheme
        self.value = value


_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
_DOI_PREFIXES = ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:")
_ARXIV_NEW = re.compile(r"^\d{4}\.\d{4,5}$")
_ARXIV_OLD = re.compile(r"^[a-z-]+(\.[a-z]{2})?/\d{7}$")
_ARXIV_PREFIXES = ("https://arxiv.org/abs/", "http://arxiv.org/abs/", "arxiv:")
_ARXIV_DOI_PREFIX = "10.48550/arxiv."


def _strip_prefix(value: str, prefixes: tuple[str, ...]) -> str:
    for prefix in prefixes:
        if value.lower().startswith(prefix):
            return value[len(prefix) :]
    return value


def normalize_doi(value: str) -> str:
    """Without prefixes, lowercased (DOIs are case-insensitive)."""
    doi = _strip_prefix(value.strip(), _DOI_PREFIXES).lower()
    if not _DOI.match(doi):
        raise InvalidIdentifier(Scheme.DOI, value)
    return doi


def normalize_arxiv(value: str) -> str:
    """Without prefix and version suffix: ``2101.00001v2`` → ``2101.00001``."""
    arxiv = _strip_prefix(value.strip(), _ARXIV_PREFIXES).lower()
    arxiv = re.sub(r"v\d+$", "", arxiv)
    if not (_ARXIV_NEW.match(arxiv) or _ARXIV_OLD.match(arxiv)):
        raise InvalidIdentifier(Scheme.ARXIV, value)
    return arxiv


def _isbn13_check_digit(first12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def normalize_isbn(value: str) -> str:
    """As ISBN-13 digits; ISBN-10 is converted. Check digits are verified."""
    isbn = re.sub(r"[\s-]", "", value.removeprefix("ISBN").removeprefix("isbn"))
    isbn = isbn.lstrip(":").upper()
    if re.fullmatch(r"\d{9}[\dX]", isbn):
        total = sum((10 - i) * (10 if c == "X" else int(c)) for i, c in enumerate(isbn))
        if total % 11:
            raise InvalidIdentifier(Scheme.ISBN, value)
        first12 = "978" + isbn[:9]
        return first12 + _isbn13_check_digit(first12)
    if re.fullmatch(r"97[89]\d{10}", isbn) and isbn[-1] == _isbn13_check_digit(
        isbn[:12]
    ):
        return isbn
    raise InvalidIdentifier(Scheme.ISBN, value)


def normalize_pmid(value: str) -> str:
    pmid = value.strip().removeprefix("PMID:").strip()
    if not re.fullmatch(r"[1-9]\d{0,8}", pmid):
        raise InvalidIdentifier(Scheme.PMID, value)
    return pmid


def normalize_url(value: str) -> str:
    url = value.strip()
    if not re.match(r"^https?://\S+$", url):
        raise InvalidIdentifier(Scheme.URL, value)
    return url


_NORMALIZERS = {
    Scheme.DOI: normalize_doi,
    Scheme.ARXIV: normalize_arxiv,
    Scheme.ISBN: normalize_isbn,
    Scheme.PMID: normalize_pmid,
    Scheme.URL: normalize_url,
}


def normalize(scheme: Scheme, value: str) -> str:
    return _NORMALIZERS[scheme](value)


def implied_by_doi(doi: str) -> list[tuple[Scheme, str]]:
    """Other identifiers a DOI implies, e.g. arXiv DOIs carry the arXiv ID."""
    if doi.startswith(_ARXIV_DOI_PREFIX):
        try:
            return [(Scheme.ARXIV, normalize_arxiv(doi[len(_ARXIV_DOI_PREFIX) :]))]
        except InvalidIdentifier:
            return []
    return []


def is_arxiv_doi(doi: str) -> bool:
    return doi.startswith(_ARXIV_DOI_PREFIX)
