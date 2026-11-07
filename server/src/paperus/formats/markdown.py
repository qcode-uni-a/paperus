"""Markdown notes to HTML (for Zotero, whose notes are HTML).

The Markdown people write in notes: paragraphs, headings, lists (also
nested), quotes, code, rules; bold, italics, strike-through, code and
links within lines. Anything else stays as text. Written so that
markdownify (how the Zotero import reads notes back) gives the same
Markdown again.
"""

import html
import re

_FENCE = re.compile(r"\s{0,3}(```|~~~)")
_HEADING = re.compile(r"\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_RULE = re.compile(r"\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_QUOTE = re.compile(r"\s{0,3}> ?")
_ITEM = re.compile(r"(\s*)(?:([-*+])|(\d{1,9})[.)])(\s+|$)")


def to_html(markdown: str) -> str:
    return "".join(_blocks(markdown.replace("\t", "    ").splitlines()))


def _starts_block(line: str) -> bool:
    return bool(
        _FENCE.match(line)
        or _HEADING.match(line)
        or _RULE.match(line)
        or _QUOTE.match(line)
        or _ITEM.match(line)
    )


def _blocks(lines: list[str]) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
        elif fence := _FENCE.match(line):
            end = next(
                (j for j in range(i + 1, len(lines)) if lines[j].strip() == fence[1]),
                len(lines),
            )
            code = html.escape("\n".join(lines[i + 1 : end]), quote=False)
            out.append(f"<pre><code>{code}</code></pre>")
            i = end + 1
        elif heading := _HEADING.match(line):
            level = len(heading[1])
            out.append(f"<h{level}>{_inline(heading[2])}</h{level}>")
            i += 1
        elif _RULE.match(line):
            out.append("<hr/>")
            i += 1
        elif _QUOTE.match(line):
            end = i
            while end < len(lines) and _QUOTE.match(lines[end]):
                end += 1
            inner = [_QUOTE.sub("", text, count=1) for text in lines[i:end]]
            out.append("<blockquote>" + "".join(_blocks(inner)) + "</blockquote>")
            i = end
        elif _ITEM.match(line):
            html_, i = _list(lines, i)
            out.append(html_)
        else:
            end = i + 1
            while (
                end < len(lines)
                and lines[end].strip()
                and not _starts_block(lines[end])
            ):
                end += 1
            text = "\n".join(text.lstrip() for text in lines[i:end]).rstrip()
            out.append(f"<p>{_inline(text)}</p>")
            i = end
    return out


def _list(lines: list[str], i: int) -> tuple[str, int]:
    """A list from line i: its items, each with the lines indented below
    it (nested lists, more paragraphs)."""
    first = _ITEM.match(lines[i])
    assert first is not None
    indent, ordered = len(first[1]), first[3] is not None
    items: list[list[str]] = []
    while i < len(lines):
        item = _ITEM.match(lines[i])
        if item is None or len(item[1]) != indent or (item[3] is not None) != ordered:
            break
        width = item.end() if item[4] else item.end() + 1
        body = [lines[i][item.end() :]]
        i += 1
        while i < len(lines):
            line = lines[i]
            if line.strip() and len(line) - len(line.lstrip()) >= width:
                body.append(line[width:])
            elif not line.strip() and _continues(lines, i + 1, width):
                body.append("")
            else:
                break
            i += 1
        items.append(body)
    tag = "ol" if ordered else "ul"
    start = int(first[3]) if ordered else 1
    opening = f'<{tag} start="{start}">' if start != 1 else f"<{tag}>"
    html_ = "".join(f"<li>{_item(body)}</li>" for body in items)
    return f"{opening}{html_}</{tag}>", i


def _continues(lines: list[str], i: int, width: int) -> bool:
    """After blank lines, does the item go on (an indented line)?"""
    while i < len(lines) and not lines[i].strip():
        i += 1
    return i < len(lines) and len(lines[i]) - len(lines[i].lstrip()) >= width


def _item(body: list[str]) -> str:
    """A list item: a first paragraph without ``<p>`` (a tight list)."""
    blocks = _blocks(body)
    if blocks and blocks[0].startswith("<p>"):
        blocks[0] = blocks[0][3:-4]
    return "".join(blocks)


_CODE = re.compile(r"(`+)(.+?)\1", re.S)
_ESCAPED = re.compile(r"\\([\\`*_{}\[\]()#+\-.!~|>])")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)\s]+)\)")
_STYLES = (
    (re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*|__(?=\S)(.+?)(?<=\S)__", re.S), "strong"),
    (re.compile(r"\*(?=\S)(.+?)(?<=\S)\*|\b_(?=\S)(.+?)(?<=\S)_\b", re.S), "em"),
    (re.compile(r"~~(?=\S)(.+?)(?<=\S)~~", re.S), "s"),
)


def _inline(text: str) -> str:
    """Bold, italics, strike-through, code and links in a line of text."""
    kept: list[str] = []
    text = text.replace("\x00", "")

    def keep(markup: str) -> str:
        kept.append(markup)
        return f"\x00{len(kept) - 1}\x00"

    text = _CODE.sub(
        lambda m: keep(f"<code>{html.escape(m[2].strip(), quote=False)}</code>"), text
    )
    text = _ESCAPED.sub(lambda m: keep(html.escape(m[1], quote=False)), text)
    text = html.escape(text, quote=False)
    text = re.sub(r"(?: {2,}|\\)\n", lambda m: keep("<br/>\n"), text)
    text = _LINK.sub(
        lambda m: (
            keep(f'<a href="{m[2].replace(chr(34), "%22")}">') + m[1] + keep("</a>")
        ),
        text,
    )
    for pattern, tag in _STYLES:
        text = pattern.sub(
            lambda m, tag=tag: f"<{tag}>{m[m.lastindex or 0]}</{tag}>", text
        )
    return re.sub("\x00(\\d+)\x00", lambda m: kept[int(m[1])], text)
