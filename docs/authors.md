# Authors as people

paperus knows the authors of its papers as people, not only as names on
each paper (issue #35). An author's page shows their papers in the
library, who they wrote with, where they were and others of the same
name; Manage → Authors lists them all.

## Records and links

- **Author records are shared by the installation.** Authors are public
  facts; what a person sees of them is limited by their papers: an author
  exists for someone only through a paper they may see, and their page
  counts and lists only those papers (`server/src/paperus/api/authors.py`).
- **Each paper's authors are linked by position** (`authorships`), with the
  name as written on that paper, how the link was made (`orcid`,
  `openalex`, `name`, `hand`), and, per paper, the affiliation and the ids
  its details give. The paper's details (CSL-JSON) stay as they are.
- **Names are written as each person chooses** (Settings → Names,
  `users.name_format`): family name first, "Benito, Mónica" (the default),
  or given name first, "Mónica Benito". A record keeps its name both ways:
  `name` ("Mónica Benito") and `written`, the same as on its papers
  ("Benito, Mónica"; read from them, not stored). Only how they are shown:
  citations use each paper's own names.

## Who is who

Linking (`server/src/paperus/authors.py`), best evidence first:

1. **The same ORCID iD, then the same OpenAlex author id.** Ids win over
   names: two different ids never meet in one person.
2. **The same full name**, compared folded: case, accents, hyphens and dots
   ignored ("Mónica Benito" = "monica benito"). Initials are another name
   ("M. Benito"); such a person is merged by hand on their page.
3. **A name several people share** (after a split) goes to the one who
   wrote with this paper's other authors; with nothing to tell, it stays
   unlinked and is listed under Manage → Authors, "To check".

Fixes by hand, which later automatic passes keep:

- **Split** (author page → "Some are by someone else"): the chosen papers
  go to a new person of the same name; the two are remembered as different.
- **Merge** ("Same person as…", "The same person" next to a namesake, or
  "Compare…" at a suggestion): both people side by side (their papers,
  where they were, co-authors), what both have in green (the same place
  or co-author; dashed: probably the same, written differently, "W.
  Huang" and "Wister Huang"), then "The same person" or "Different
  people". The other person's papers come to the one that stays (an
  ORCID iD, else an OpenAlex id, else more papers, else the one whose
  page it is), shown under the fuller spelling. Refused for two
  different ORCID iDs (OpenAlex sometimes has two profiles of one
  person: those may be merged).
- **Decide** a paper's author under "To check", or someone new.

Author records are shared, so a fix changes them for everyone who has
papers by that author. Hence:

- **Who may fix**: someone with a paper of each person concerned that is
  theirs to change (their own library, or a group where they are a
  member, not a reader); splitting and deciding need the right to change
  each paper concerned. "To check", "Probably the same" and their number
  in the menu list only what the person may fix.
- **Every fix is kept** (`author_changes`): what was done, by whom, which
  papers' authors moved. The author's page lists them under "Changed by
  hand" ("by you", or "by someone else": who it was would tell what
  papers they have), and anyone who may fix that author can undo one: a
  merge gives the other person's papers back to a new person of that
  name (kept apart) and the one kept their name before, a split joins
  the two again, "different people" may
  be suggested again.

## Their papers elsewhere

An author's page with an ORCID iD or OpenAlex id offers "Add their
papers…" (`paperus.works`, `GET /api/authors/{id}/works`): one request to
OpenAlex for their works with a DOI (200 at most, newest first; errata,
reviews and the like left out), each marked if a paper with that DOI or
one of its copies is in the library. Copies of one paper (the journal's,
arXiv's, SSRN's, a repository's) are one entry under the journal's DOI.
Those chosen are added by DOI as from "Add" (details, open-access copy,
authors and references follow). Manage → Missing does the same for one's
own ORCID iD (`GET /api/me/works`). Only the iD or id is sent to OpenAlex.

## Ids and affiliations from OpenAlex

For papers with a DOI (or an arXiv ID), an hourly job asks OpenAlex for the
paper's authorships, 50 papers to a request, about a thousand papers an
hour, each paper once (`check_waiting`). Each author on the paper gets
OpenAlex's author id, the ORCID iD, and the affiliation on that paper
(institutions, else the raw affiliation string); then the paper's authors
are linked again, so ids take effect: "M. Benito" with Mónica Benito's id
is her, a Mónica Benito with another id is someone else. Only DOIs are
sent (with the contact email, if one is set). Administration → Settings →
Server → Authors turns it off.

Affiliations belong to the paper, as they change over time; the author's
page derives "where they were" from their papers, the newest one called
"latest known".

## Probably the same

Manage → Authors suggests pairs of people who are probably one
(`likely_the_same`): the same family name, given names that fit ("M." and
"Mónica", "M. F." and "Mario Fernando"; not "Mónica" and "María"; a person
known by a written-out given name is compared by that, not by initials
also seen), not said to be different, not two different ORCID iDs; those
with co-authors in common first. "Compare…" (or "Review one by one" for
all) shows each pair side by side to merge, as above, or keep apart.

## When it happens

A paper's details stamp a key of its author names (`refresh_item`); a
background job every 5 minutes links the papers whose names changed (at
first, every paper) and removes people left without papers.
Administration → Jobs → "Link authors now" starts it, and the OpenAlex
lookup, at once.

## Later (phase 3 of #35)

"This is me" (an account linked to its author record, or by ORCID from the
OIDC login) and "My papers"; "other works" from OpenAlex, with Import.

Done of phase 3: smart collections and the library's filter by author
(the "authors" rule), exports and imports that keep who is who, and AI
assistants' `find_authors`, `get_author`, `list_documents(author_id=…)`
and the people in `get_document`.
