# Annotations

Highlights, comments and drawings on a paper's PDF, made in paperus's
viewer (`web/src/lib/annotations/`, `server/src/paperus/annotations.py`).

## Kinds

As in Zotero, each a standard PDF annotation, so they can be written into a
PDF:

| Kind | PDF annotation | Made by |
| --- | --- | --- |
| Highlight | Highlight | selecting text, then a colour in the menu over it; or the highlighter, dragging over text |
| Underline | Underline | the menu over a selection; or the underline tool |
| Strike-through | StrikeOut | the menu over a selection; or the strike tool |
| Note | Text (sticky note) | the note tool, a tap or click where it goes |
| Text | FreeText | the text tool, a tap or click; its words and size in the popup |
| Area | Square | the area tool, dragging around a figure or an equation |
| Pen | Ink | the pen, drawing (three widths); the eraser takes strokes away |

Each has a colour (Zotero's eight), a comment and tags, and its page label
("iv", "12") when the PDF numbers its pages. Positions are PDF points from
the page's lower left (`rects` [x1, y1, x2, y2], or `paths` [x, y, …] with a
`width`), so they fit any zoom and rotation, and the PDF itself.

## In the viewer

- A large screen: the tools in the viewer's toolbar (select, highlight,
  underline, strike, note, text, area, pen, eraser, colour); selecting text
  with the select tool shows the colours, underline, strike and comment over
  it. Clicking an annotation opens its popup (comment, colour, tags, words
  and size for text, delete); one's own notes, words and areas move by
  dragging. Escape puts the tool down.
- A phone: a round button at the bottom opens the tools and colours; with
  a tool in hand one finger works it and two fingers scroll. The popup is a
  sheet at the bottom of the screen.
- Fluent mode (the toolbar's toggle; on by itself for two-column papers
  on a phone, as last chosen otherwise): the pages cut into pieces in
  reading order (worked out on the server once per file,
  `server/src/paperus/page_layout.py`, from where a page has ink and
  text), each a window onto its page, so all of this works there too; a
  selection over a column break makes one annotation on both columns.
  Tested on layout twins of real papers' pages (`server/tests/twins/`:
  their measured layout with filler words and coloured figures, no
  content); a page fluent mode gets wrong becomes a twin with
  `measure.py` (see there), looked over with `review.py`. Such pages are
  found with `sweep.py`: the library's own PDFs, pages where the pieces
  read many lines against the PDF's text order (often the PDF's order is
  the odd one: look before believing).
- The list (the toolbar's list button): all annotations by page, found by
  their words, comments, tags or author, filtered by colour or to one's own;
  a click goes to one. "Add note from all" gathers them into a note on the
  paper (quotes, comments, tags, pages).

## Who sees them

Annotations are their person's. Anyone who may read a paper may annotate it
(readers of a group too); only their person changes or removes one.
"Show mine to the group" in the list shares one's annotations of that paper
with everyone who may read it (`annotation_shares`); they show with the
person's name and can be gathered into notes, not changed.

## A PDF's own annotations

Annotations made in another reader (Zotero, Acrobat, a tablet) come along
in the PDF. When the file is read, they are taken in once, as annotations
of the person who uploaded it (`paperus.pdf.annotations` with PDFium,
`paperus.annotations.take_in`): highlights, underlines (squiggly ones too),
strike-throughs, sticky notes, words on the page, squares and pen strokes,
with their colour, comment, the text they mark and the page label. Where
each sat in the PDF is kept (`files.file_marks`); the viewer then draws the
pages without exactly those (PDF.js's annotation storage marks them
deleted) for whoever sees the uploader's annotations, also after one was
deleted, and draws the file as it is for others. Annotations paperus does
not take in (links, forms, stamps, words on the page without words) stay
in the PDF as drawn.

## Taking them along

- "Download with annotations" (the list): the PDF with the annotations one
  sees written in as standard PDF annotations (PDFium, `paperus.pdf.
  with_annotations`), for any reader; the PDF's own that were taken in are
  replaced, not doubled.
- The paperus export carries one's annotations (`annotations`), whom one
  shows them (`annotation_shares`) and the files' `file_marks`; importing
  it brings them back (once). Zotero, BibTeX and RIS exports do not hold
  them yet: writing them into the exported PDFs is still to come.
- Assistants read them with `get_annotations` (see [AI](ai.md)).

## API

`GET /api/files/{id}/annotations` (those one sees, in reading order, and
the PDF's own marks to leave out when drawing), `POST` there,
`PATCH`/`DELETE /api/annotations/{id}`, `PUT
/api/items/{id}/annotation-sharing`, `GET /api/files/{id}/annotated` (the
PDF with them). Tokens: reading with `papers.read` (the PDF with
`files.read`), the rest with `notes.write`.
