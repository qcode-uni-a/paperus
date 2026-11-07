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
- **Merge** ("Same person as…", or "The same person" next to a namesake):
  the other person's papers come here. Refused for two different ids.
- **Decide** a paper's author under "To check", or someone new.

## When it happens

A paper's details stamp a key of its author names (`refresh_item`); a
background job every 5 minutes links the papers whose names changed (at
first, every paper) and removes people left without papers.
Administration → Jobs → "Link authors now" starts it at once.

## Later (phase 2 and 3 of #35)

Author ids, ORCIDs and affiliations from OpenAlex for papers with a DOI;
"probably the same" suggestions (same family name, compatible initials,
shared co-authors); "This is me"; authors in smart-collection rules and
for AI assistants.
