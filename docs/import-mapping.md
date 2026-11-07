# Importing a paperus export: where things go

An export ([export.md](export.md)) holds what one person could see: their
own papers and their groups' papers, with tags, keywords, collections and
notes. Importing it, on another server or the same one, the person decides
where each part goes. This page is the rule book: what is asked, what is
chosen unless changed, and the cases the tests check.

Two principles:

- **Nothing goes into a group by itself.** Every group target is chosen by
  the person.
- **Only what needs a decision is asked.** In an empty library, or one
  without overlapping names, the only question is where the papers go, and
  the defaults are right.

## 1. Owners: whose papers go where

The export's owners are "Me" (the exporting person's own papers) and each
group, by its path ("Uni/QCode Lab/Theory").

| Owner in the export | Choices offered | Default |
| --- | --- | --- |
| Me | my library | my library |
| A group | a. into a group here the person may add papers to | — (never preselected) |
| | b. create the group here (only if the person may: see below) | — |
| | c. into my library, kept in a collection named after the group | **c** |
| | d. into my library, without a collection | — |

**Who may create a group** ([permissions.md](permissions.md)): a top-level
group only a site administrator; a group inside another group that
group's administrators. For a path like "Uni/QCode Lab/Theory", choice b
is offered only if every missing level may be created: a parent that
exists here with the person as administrator, or one created in the same
import. The person becomes the new group's administrator; members are not
in the export and are added afterwards.

**The holding collection (c).** A collection in the person's library named
after the group ("QCode Lab", made unique among their collections), with
the group's collections inside it. Its description says where the papers
come from (group, server, date) and how to hand them over: once the group
exists here, Edit collection → Owner → the group, with "also move the
papers", moves the papers and collections there. Notes and tags stay the
person's and are moved by hand. Importing again finds the same holding
collection; it is not made twice.

**Suggestions for groups.** A group here with the same or a similar name
(rules in section 3) is *suggested* next to choice a, never preselected.

## 2. Tags and collections that exist here already

After the owners are chosen, the import compares the export's tags and
collections with those of each target library (my library for "Me", c and
d; the chosen group for a; nothing for b, which starts empty). Only
entries needing a decision are listed.

| Export entry compared with the target | Listed? | Choices | Default |
| --- | --- | --- | --- |
| No similar name there | no | — | made new |
| Exactly the same name (case ignored) | yes | merge · make new · map to another | **merge** |
| Nearly the same name (section 3) | yes | merge into the suggestion · make new · map to another | **merge into the suggestion** |
| Similar name (section 3) | yes | make new · map to the suggestion · map to another | **make new** |
| Keyword (tag from a paper's details) | no | — | joins the same-named keyword, else new |
| Smart collection, same name, same rules | yes | merge · make new · map to another | merge |
| Smart collection, same name, other rules | yes | make new · map to another | **make new** (says why) |
| Collection inside a holding collection (1c) | no | — | made new inside it |
| Collection inside a merged or mapped collection | compared within its new parent | as above | as above |

- **"Make new"** names it "<name> (imported)", unique in the target.
- **"Map to another"** offers the target's tags, or its collections by
  path ("PhD/Thesis").
- **"Import all as new"** (a switch above the list) sets every listed
  entry to "make new"; keywords still join same-named keywords.
- A merged or mapped collection gets the export collection's papers; its
  sub-collections go inside it and are compared there.

## 3. Names: nearly the same, similar, different

Names are compared after **folding**: lower case, accents removed
("é" → "e"), spaces, `-` and `_` removed (so "ToRead" and "to read"
fold alike), and a simple English plural taken off: a final "s" or "es",
"ies" → "y" ("Studies" · "Study"), "es" ↔ "is" ("Theses" · "Thesis").
Whole words are compared on the last part of a path.

| Kind | Rule | Example pairs |
| --- | --- | --- |
| Exactly the same | equal ignoring case | "Thesis" · "thesis" |
| Nearly the same | equal after folding | "ToRead" · "to read"; "Quantum_Dots" · "Quantum dots"; "Thesis" · "Theses"; "Mónica" · "Monica" |
| Similar | one contains the other as whole words; or the last part of a path is equal; or the folded names are very close (difflib ratio ≥ 0.85) | "Thesis" · "PhD/Thesis"; "Floquet" · "Floquet systems"; "Floquet sytems" · "Floquet systems" |
| Different | none of these | "ML" · "Machine learning"; "Optics" · "Topics"; "Qubits" · "Quantum"; "Uni" · "Uni/QCode Lab" |

At most three suggestions per entry, the closest first. Abbreviations and
meanings are not guessed.

## 4. Importing again

- The same export imported again with the same choices adds nothing:
  papers are found by id, DOI, arXiv ID or identical file; merged or
  mapped tags and collections are found again; holding and "(imported)"
  collections made by the first import are reused, not made twice.
- Papers the person can already see are found, not copied, whatever the
  owner choice.

## 5. Cases the tests check

| # | Situation | Expected |
| --- | --- | --- |
| O1 | Export with "Me" only, empty server | no questions beyond the owner; all in my library |
| O2 | A group, no group here, person not an administrator | choices c, d only; c preselected; holding collection made with the description |
| O3 | A group, person is site administrator | choice b offered; choosing it creates the group, person its admin, papers there |
| O4 | Nested "Uni/QCode Lab/Theory", only "Uni" exists with person as admin | b offered for "QCode Lab" and "Theory" (made inside "Uni") |
| O5 | Nested path, parent exists, person not its admin | b not offered |
| O6 | Group "QCode-Lab" here, export has "QCode Lab" | suggested next to a, not preselected; c stays the default |
| O7 | Holding collection later given to a new group (Owner → group, move papers) | papers and sub-collections now the group's |
| O8 | Create refused when not allowed (forged request) | clear error, nothing imported |
| T1 | Tag "to read" here, export has "to read" | listed, merge preselected |
| T2 | Tag "to read" here, export has "ToRead" | listed, merge into "to read" preselected |
| T3 | Collection "PhD/Thesis" here, export has "Thesis" | listed, "make new" default, "PhD/Thesis" suggested |
| T4 | Tag "Optics" here, export has "Topics" | not listed; made new |
| T5 | Keyword "Quantum Physics" on both sides | not listed; joins |
| T6 | Smart collection, same name, other rules | listed, "make new" default with the reason |
| T7 | Collection clash inside a merged collection ("Thesis/Chapter 1" both sides) | listed as a path inside the merged one |
| T8 | "Import all as new" | every listed entry "(imported)"; keywords still join |
| T9 | Map to another: export "Thesis" → existing "PhD/Thesis" | papers in "PhD/Thesis", sub-collections inside it |
| R1 | Same export, same choices, imported twice | second import adds nothing (no new papers, tags, collections, holding collections) |
| N1 | Name pairs of section 3 | each pair classified as in the table |

## 6. Where this is built

- `server/src/paperus/importing/names.py`: folding and likeness (N1);
  `importing/mapping.py`: what is offered, the defaults, checking the
  choices and the plan the import follows; `importing/choices.py`: the
  shapes of choices and previews.
- API (session only): the upload answers with the owners (`can_create`,
  `suggestions`); `POST /api/imports/{id}/preview` takes the owner choices
  (and any tag and collection choices) and lists the clashes with their
  defaults; `POST /api/imports/{id}/start` takes the same choices, checks
  them (403 with the reason for a group that may not be created, 422 for
  a choice that cannot be followed) and starts. The worker checks them
  again (rights may have changed), creates the groups and holding
  collections, then imports.
- A holding collection's id is derived from the export's group and the
  person, so importing again finds it even when renamed. When "QCode Lab"
  is taken among the person's collections, it is "QCode Lab (2)".
- On the command line (`paperus import`), "Me" goes to the person's
  library, each group into its holding collection, clashes take their
  defaults; `--group NAME` puts everything into that group instead.
- Tests: `server/tests/test_import_mapping.py`, named by the cases above.
