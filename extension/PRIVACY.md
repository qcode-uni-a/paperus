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

What it keeps in your browser: your paperus address, an access token that
may only add papers and see which ones you have, the owner new papers go
to, and the names of the owners you may add to (for the button's menu). Disconnecting in its settings deletes them; the token can also be
ended in paperus under Settings → Access tokens.

What paperus does with the papers is up to whoever runs it; see their
terms.
