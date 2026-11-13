# Page twins

A page twin is a publisher's page as the extension sees it: its `<meta>`
tags, links, frames, headings, and the data a site keeps in a script. It
holds nothing that could be a problem to pass on: no article text, no
abstract or figures, no references' titles or authors, none of the site's
scripts or styles, nothing of the reader (institution, session, signed
addresses). The paper gets an unrelated title and invented authors; the
journal, the publisher and their hosts get parody names that keep the
acronym (IEEE Xplore → EEEK Xplore at eeekxplore.eeek.org). Addresses keep
their shapes (`/document/…`, `/doi/pdf/<DOI>`, `/pii/…/pdfft`), which the
extension's rules read; DOIs are under 10.5555 (Crossref's prefix for
examples), and other papers' DOIs and IDs, authors' profile links, ORCID
iDs and headlines in addresses become placeholders. A site whose rules name its
host (Wiley's reader, arXiv, Google Scholar) will need its twin read at
the real host.

```
pages/NAME/page.html     the twin           checked in
pages/NAME/expect.json   what to expect     checked in, written by hand
raw/SITE/page.html       the page as saved  never (.gitignore)
raw/SITE/names.json      real → parody      never
```

`npm test` reads each twin as the extension reads a page in its tab
(`readPage` in jsdom, at the twin's address) and checks `expect.json`:
`mode` (the popup's choice, `paper` or `list`) and any of `readPage`'s
fields.

## Forwarding pages: a chain

What a PDF link leads to (a page in between, a script's redirect, a frame,
a check for robots) is a `chain` in `expect.json`: what each address
answers a script's fetch (`fetch`) and a page load (`load`, for tests in
a browser). The test plays it as the network and fetches the PDF as the
extension does in the page (`fetchPdf`); `expectPdf` says how that ends:

```json
"chain": {
  "https://…/pdfft?…": { "fetch": { "redirect": "https://…/article?ref=…" },
                         "load": { "redirect": "https://pdf.…/main.pdf?…" } },
  "https://…/article?ref=…": { "fetch": { "html": "<title>…</title>" } },
  "https://pdf.…/main.pdf?…": { "fetch": "robot-check", "load": "pdf", "cors": true }
},
"expectPdf": { "error": "The PDF link gave a web page, not a PDF.", "at": "https://…/article?ref=…" }
```

Answers: `"pdf"`, `"robot-check"`, `{"redirect": …}`, `{"html": …,
"status": …}`; an address of another site refuses a fetch unless it says
`"cors": true`, as browsers do. `expectPdf`: `{"pdf": true}`, `{"next":
…}` (left to the extension, which may fetch other sites) or `{"error":
…, "at": …}`. The extension's log records each step (the addresses,
where they landed, the title of what came back): a site's chain is read
from it. `chainFrom` says where a chain comes from.

## A new twin

1. Open the paper's page in Firefox, with your usual access, and wait for
   it to load. Ctrl+S, **Web Page, complete** (not "HTML only": the page
   after its scripts ran), into `twins/raw/SITE/` as `page.html`.
2. Next to it, `names.json`: the twin's name, the page's address, the real
   names (paper title, journal, publisher, hosts, DOI, article numbers)
   with their parodies, and words that must not be left (your
   institution, the authors' names, the publisher's name in any case):

   ```json
   { "twin": "eeek", "url": "https://…",
     "replace": { "Real Title": "Another Title", "IEEE": "EEEK", "ieee": "eeek" },
     "forbid": ["Your University", "ieee"] }
   ```

   Authors not named there get invented names.
3. `node twins/make.mjs SITE` writes `pages/TWIN/page.html`. It refuses
   (and shows where) if a replaced or forbidden word is left, or a title,
   journal or publisher has no parody. Read the twin through before
   checking it in.
4. `pages/TWIN/expect.json`: `about` (what the page shows that matters,
   and when it was saved), `url` (the twin's address) and `expect`. Check
   that the test fails without the fix it is for.
