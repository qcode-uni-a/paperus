# paperus extension: privacy

The extension talks only to the paperus server you connect it to (your own
or your group's). It sends nothing to its developers or anyone else, and
keeps no statistics.

What it sends to your paperus, and when:

- **When you click its button** (or a paperus button on arXiv): the page's
  address and the paper's details from the page (title, authors, DOI, …),
  and the paper's PDF, downloaded in your browser with your own access
  (in Firefox's PDF viewer: by the extension, from the website you allowed
  it to).
- **On arXiv pages**: the arXiv IDs of the papers listed there, to show
  which ones are already in your library.
- **On Google Scholar's results**: the DOIs and arXiv IDs found in the
  results' links, to show which ones are already in your library; on a
  click, the paper's page is opened out of sight and saved like any other.
- **When you ask from paperus' Missing page**: for each paper you chose,
  the extension opens its publisher's page in a background tab (with your
  access), downloads the PDF the page links and sends it to your paperus.
  It uses its access to websites (asked for once, when installing) only
  for these requests and for the paperus button.
- **When something goes wrong** (a paper saved without its PDF, a PDF it
  could not get, an error): what happened, with the page's address and
  the extension's version, for the administrators of your paperus
  (Administration → Logs).
- **The steps of a save** (the page's address and details, each address
  it fetched from and the answer), to your paperus's log too, for
  finding out what goes wrong.

The log leaves out what may stand for you: addresses keep their site and
path, and the names of their parameters, but not their values (a signed
PDF address's signature, a session, a proxy's ticket, a search's words)
nor a name and password in them; libraries appear by their id, not their
name.

On your paperus' own pages, a small script tells paperus that the
extension is installed and passes on such requests; it reads nothing
there.

It also keeps a log of its last 20 steps in your browser, shown in its
settings (to copy and pass on, or clear).

What it keeps in your browser: your paperus address, an access token that
may only add papers and see which ones you have, the owner new papers go
to, and the names of the owners you may add to (for the button's menu). Disconnecting in its settings deletes them; the token can also be
ended in paperus under Settings → Access tokens.

What paperus does with the papers is up to whoever runs it; see their
terms.
