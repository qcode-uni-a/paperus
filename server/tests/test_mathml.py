"""Formulas in titles: Crossref's MathML kept as $LaTeX$."""

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
