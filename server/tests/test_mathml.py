"""Formulas in titles: Crossref's MathML kept as $LaTeX$."""

import pytest

from paperus.mathml import to_tex

M = 'xmlns:mml="http://www.w3.org/1998/Math/MathML"'


def test_mathml_becomes_latex() -> None:
    aps = (
        f"Limitations of the\n   <mml:math {M}>\n     <mml:mi>g</mml:mi>\n"
        "   </mml:math>\n   -tensor formalism of semiconductor spin qubits"
    )
    assert to_tex(aps) == (
        "Limitations of the $g$-tensor formalism of semiconductor spin qubits"
    )
    sub = f"<mml:math {M}><mml:msub><mml:mi>In</mml:mi><mml:mi>x</mml:mi></mml:msub></mml:math>"  # noqa: E501
    assert to_tex(f"Grown {sub} wells") == r"Grown ${\mathrm{In}}_{x}$ wells"
    frac = f"<mml:math {M}><mml:mi>ν</mml:mi><mml:mo>=</mml:mo><mml:mfrac><mml:mn>1</mml:mn><mml:mn>3</mml:mn></mml:mfrac></mml:math>"  # noqa: E501, RUF001
    assert to_tex(f"A {frac} state") == r"A $ν=\frac{1}{3}$ state"  # noqa: RUF001
    # Without MathML only the whitespace changes; other tags stay.
    assert to_tex("A  <i>g</i>-factor\n study") == "A <i>g</i>-factor study"
    assert to_tex("<i>X</i> -wave magnets") == "<i>X</i>-wave magnets"
    assert to_tex("<i>Colloquium</i> : Skyrmions") == "<i>Colloquium</i>: Skyrmions"
    assert (
        to_tex("Broken <mml:math><mml:mi>x</mml:mi>")
        == "Broken <mml:math><mml:mi>x</mml:mi>"
    )


def math(inner: str) -> str:
    return f"<mml:math {M}>{inner}</mml:math>"


@pytest.mark.parametrize(
    ("markup", "tex"),
    [
        ("<mml:mo>\u2212</mml:mo><mml:mn>1</mml:mn>", "-1"),
        ("<mml:mtext>if</mml:mtext>", r"\text{if}"),
        ("<mml:mtext> </mml:mtext><mml:mi>x</mml:mi>", "x"),
        ("<mml:mi>a</mml:mi><mml:mspace/><mml:mi>b</mml:mi>", r"a\ b"),
        (
            "<mml:msup><mml:mi>e</mml:mi><mml:mn>2</mml:mn></mml:msup>",
            "{e}^{2}",
        ),
        (
            "<mml:msubsup><mml:mi>x</mml:mi><mml:mn>1</mml:mn>"
            "<mml:mn>2</mml:mn></mml:msubsup>",
            "{x}_{1}^{2}",
        ),
        ("<mml:msqrt><mml:mn>2</mml:mn></mml:msqrt>", r"\sqrt{2}"),
        (
            "<mml:mover><mml:mi>x</mml:mi><mml:mo>~</mml:mo></mml:mover>",
            "{x}^{~}",
        ),
        (
            "<mml:munder><mml:mi>x</mml:mi><mml:mo>_</mml:mo></mml:munder>",
            "{x}_{_}",
        ),
        (
            "<mml:semantics><mml:mi>k</mml:mi>"
            "<mml:annotation>k</mml:annotation></mml:semantics>",
            "k",
        ),
        ("<mml:semantics/>", ""),
        ("<mml:mrow>plain</mml:mrow>", "plain"),
    ],
)
def test_mathml_elements(markup: str, tex: str) -> None:
    expected = f"Before ${tex}$ after" if tex else "Before after"
    assert to_tex(f"Before {math(markup)} after") == expected


def test_broken_mathml_loses_its_tags() -> None:
    assert to_tex("A <mml:math><mml:mi>x</mml:mo></mml:math> b") == "A x b"
