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
- **Merge** ("Same person as…", or "The same person" next to a namesake
  or a suggestion): the other person's papers come here. Refused for two
  different ORCID iDs (OpenAlex sometimes has two profiles of one person:
  those may be merged).
- **Decide** a paper's author under "To check", or someone new.

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
with co-authors in common first. "The same person" merges them (the one
with more papers stays), "Different people" remembers them as two.

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
