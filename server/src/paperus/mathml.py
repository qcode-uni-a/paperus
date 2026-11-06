"""Formulas in titles from Crossref come as MathML; paperus keeps them as
LaTeX between dollar signs (as APS writes titles, and as the website
typesets them): ``<mml:mi>g</mml:mi>`` becomes ``$g$``."""

import re
import xml.etree.ElementTree as ET

_MATH = re.compile(r"<(?:mml:)?math\b.*?</(?:mml:)?math>", re.DOTALL)
_SPACES = re.compile(r"\s+")


def _name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].removeprefix("mml:")


def _tex(element: ET.Element) -> str:
    name = _name(element)
    children = list(element)
    inner = [_tex(child) for child in children]
    text = (element.text or "").strip()
    if name == "mi":
        return text if len(text) <= 1 else rf"\mathrm{{{text}}}"
    if name in ("mn", "mo"):
        return {"\u2212": "-", "\u2217": "*"}.get(text, text)
    if name == "mtext":
        return rf"\text{{{text}}}" if text else ""
    if name == "mspace":
        return r"\ "
    if name in ("msub", "msup") and len(inner) == 2:
        mark = "_" if name == "msub" else "^"
        return f"{{{inner[0]}}}{mark}{{{inner[1]}}}"
    if name == "msubsup" and len(inner) == 3:
        return f"{{{inner[0]}}}_{{{inner[1]}}}^{{{inner[2]}}}"
    if name == "mfrac" and len(inner) == 2:
        return rf"\frac{{{inner[0]}}}{{{inner[1]}}}"
    if name == "msqrt":
        return rf"\sqrt{{{''.join(inner)}}}"
    if name in ("mover", "munder") and len(inner) == 2:
        mark = "^" if name == "mover" else "_"
        return f"{{{inner[0]}}}{mark}{{{inner[1]}}}"
    if name == "semantics":
        return inner[0] if inner else ""
    if name in ("annotation", "annotation-xml"):
        return ""
    return "".join(inner) or text


def to_tex(text: str) -> str:
    """MathML in a title as $LaTeX$, whitespace collapsed; text without
    MathML stays as it is (apart from whitespace)."""

    def replace(match: re.Match[str]) -> str:
        markup = re.sub(r"<(/?)mml:", r"<\1", match.group(0))
        markup = re.sub(r"\sxmlns(:\w+)?=\"[^\"]*\"", "", markup)
        try:
            tex = _tex(ET.fromstring(markup))
        except ET.ParseError:
            return re.sub(r"<[^>]+>", "", match.group(0))
        return f"${tex}$" if tex.strip() else ""

    tidy = _MATH.sub(replace, text) if "math" in text else text
    tidy = _SPACES.sub(" ", tidy).strip()
    # Line breaks around markup are no spaces in the title: "$g$-tensor",
    # "<i>X</i>-wave", "<i>Colloquium</i>: …".
    tidy = re.sub(r"(\$|</(?:i|b|em|strong|sub|sup)>) (?=[-\u2013,.;:)])", r"\1", tidy)
    return re.sub(r"(?<=[(\-]) (?=\$|<(?:i|b|em|strong|sub|sup)>)", "", tidy)
