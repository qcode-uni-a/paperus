"""Generate the paperus logo: three sheets fanned like a papyrus head, the
front one with a highlighted line, and the wordmark in Literata.

Text becomes paths, so the SVGs need no fonts. Run from the repository root
(after `npm install` in web/, which provides the font):

    uvx --with fonttools --with brotli python docs/logo/make_logo.py
"""

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont

ROOT = Path(__file__).resolve().parents[2]
FONT = (
    ROOT
    / "web/node_modules/@fontsource-variable/literata/files/literata-latin-opsz-normal.woff2"
)
OUT = Path(__file__).resolve().parent

INK, INK_DARK = "#1B2440", "#E6E9F2"
ROYAL, ROYAL_MID, ROYAL_DEEP = "#2338A8", "#5468D4", "#1A2B85"
HIGHLIGHTER, HIGHLIGHTER_DEEP, HIGHLIGHTER_FOLD = "#FFE45C", "#F2C230", "#D9A91E"
PIVOT = (32, 58)
FAN = 23  # degrees each back sheet turns away from the front one


def sheet_paths(
    x: float = 19, y: float = 12, w: float = 26, h: float = 37, fold: float = 8
) -> tuple[str, str]:
    r = 3
    body = (
        f"M{x + r} {y}h{w - fold - r}l{fold} {fold}v{h - fold - r}a{r} {r} 0 0 1-{r} {r}"
        f"H{x + r}a{r} {r} 0 0 1-{r}-{r}V{y + r}a{r} {r} 0 0 1 {r}-{r}Z"
    )
    corner = f"M{x + w - fold} {y}v{fold - 1.5}a1.5 1.5 0 0 0 1.5 1.5h{fold - 1.5}Z"
    return body, corner


BODY, CORNER = sheet_paths()


def defs(prefix: str) -> str:
    """Gradients and the shadow, with ids unique per file (SVGs may share a page)."""
    return f"""<defs>
    <linearGradient id="{prefix}front" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF"/><stop offset="1" stop-color="#EEF1FB"/>
    </linearGradient>
    <linearGradient id="{prefix}blue" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{ROYAL_MID}"/><stop offset="1" stop-color="{ROYAL}"/>
    </linearGradient>
    <linearGradient id="{prefix}yellow" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="{HIGHLIGHTER}"/><stop offset="1" stop-color="{HIGHLIGHTER_DEEP}"/>
    </linearGradient>
    <filter id="{prefix}shadow" x="-30%" y="-30%" width="160%" height="160%">
      <feDropShadow dx="0" dy="1.2" stdDeviation="1.4" flood-color="#1B2440" flood-opacity="0.28"/>
    </filter>
  </defs>"""


def sheet(prefix: str, angle: float, fill: str, corner: str) -> str:
    return (
        f'<g transform="rotate({angle} {PIVOT[0]} {PIVOT[1]})" filter="url(#{prefix}shadow)">'
        f'<path d="{BODY}" fill="{fill}"/><path d="{CORNER}" fill="{corner}"/></g>'
    )


def mark(prefix: str) -> str:
    return "\n  ".join(
        [
            defs(prefix),
            sheet(prefix, -FAN, f"url(#{prefix}blue)", ROYAL_DEEP),
            sheet(prefix, FAN, f"url(#{prefix}yellow)", HIGHLIGHTER_FOLD),
            sheet(prefix, 0, f"url(#{prefix}front)", "#C9D1F2"),
            f'<path d="M22.5 31.6 L42 30.9 L41.6 36.8 L22 37.4Z" fill="{HIGHLIGHTER}"/>',
            (
                f'<path d="M24.5 27h11M24.5 34.2h15M24.5 41.4h9" stroke="{ROYAL}" '
                'stroke-width="2.2" stroke-linecap="round"/>'
            ),
        ]
    )


def wordmark(size: float, x: float, baseline: float) -> tuple[str, float]:
    font = instantiateVariableFont(TTFont(FONT), {"wght": 620, "opsz": 48})
    glyphs, cmap, upm = font.getGlyphSet(), font.getBestCmap(), font["head"].unitsPerEm
    scale, pen, cursor = size / upm, SVGPathPen(glyphs), 0.0
    for char in "paperus":
        name = cmap[ord(char)]
        glyphs[name].draw(
            TransformPen(pen, (scale, 0, 0, -scale, x + cursor * scale, baseline))
        )
        cursor += glyphs[name].width - 14
    return pen.getCommands(), cursor * scale


def write(name: str, body: str, width: float, height: float) -> None:
    (OUT / name).write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}" role="img" aria-label="paperus">\n'
        f"  <title>paperus</title>\n  {body}\n</svg>\n"
    )


if __name__ == "__main__":
    write("paperus-mark.svg", mark("m-"), 64, 64)
    words, width = wordmark(40, 70, 44)
    for name, ink, prefix in [
        ("paperus-logo.svg", INK, "l-"),
        ("paperus-logo-dark.svg", INK_DARK, "d-"),
    ]:
        write(
            name,
            f'{mark(prefix)}\n  <path d="{words}" fill="{ink}"/>',
            70 + width + 8,
            64,
        )
    print("wrote", ", ".join(sorted(p.name for p in OUT.glob("*.svg"))))
