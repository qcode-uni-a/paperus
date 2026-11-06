# Permissions

Who may do what with papers, tags, collections and groups. The server
enforces all of this (`server/src/paperus/access.py`); the website only
hides what one may not do.

Every row below has a test in `server/tests/test_permissions.py`, named
after its table and row (e.g. `test_tags_create`), which checks each
column; keep the two in step. Inherited roles in nested groups are tested
in `test_groups.py`. Not tested on the server: the licence reminder (a
website text) and the planned collection link.

## Owners and roles

Every paper, tag and collection has one **owner**: a person (private) or a
group (shared with its members). People see everything they own and
everything their groups own, mixed in one list.

Roles in a group, inherited by every group inside it (a subgroup can raise
a role, never lower it; nothing is inherited upwards):

| Role | In short |
| --- | --- |
| Reader | sees and searches the group's things |
| Member | also adds, changes and deletes them |
| Admin | also manages members and subgroups |

**Site administrators** manage users and groups but see no one's papers
because of it; they need a membership like everyone else.

## Papers

"Mine" means owned by me; "group's" means owned by a group I am in.

| Action | Mine | Group's, as reader | Group's, as member or admin |
| --- | --- | --- | --- |
| See, search, open files | yes | yes | yes |
| Change details, versions, files | yes | no | yes |
| Move to the trash, restore | yes | no | yes |
| Give to a group I may add to | yes | no | yes |
| Take for myself | (already mine) | no | yes |
| Merge into another paper (this one goes to the trash) | yes | no | yes |

- New papers belong to my default owner (me, or a group I chose) or to
  the owner picked when adding.
- Adding a DOI or file that matches a paper I can already see finds that
  paper instead of adding it again. Papers in other people's private space
  stay invisible, so two people adding the same paper independently get
  two items.
- When a paper changes owner, the collections of a group that no longer
  owns it let it go. Tags stay.
- **Merging** two papers that are the same: the one merged away goes to the
  trash; the other keeps its details and takes over its versions and files
  (only if I may change it), its tags and its collections (where the rules
  below allow). What cannot move stays with the trashed paper. Likely
  duplicates (same identifier or file, among papers I can see) are
  suggested; nothing is merged automatically. "Not the same paper" hides a
  pair for everyone who sees both, so it needs the right to change at
  least one of them.

## Tags

| Action | My tags | A group's tags, as reader | A group's tags, as member or admin |
| --- | --- | --- | --- |
| See | yes | yes | yes |
| Create | yes | no | yes |
| Rename, recolour, describe, delete | yes | no | yes |
| Give to another owner | yes, to a group I may add to | no | yes, to me or a group I may add to |
| Put on / take off a paper of mine | yes | yes | yes |
| Put on / take off a group's paper (reader) | yes, only I see it | no | no |
| Put on / take off a group's paper (member) | yes, only I see it | — | yes |

- Private tags on shared papers are visible only to their owner.
- A group's tags on my private papers are visible only to me (others do
  not see the paper); counts are always counted per viewer.
- Giving a tag to another owner keeps it on all its papers.

## Collections

| Action | My collections | A group's, as reader | A group's, as member or admin |
| --- | --- | --- | --- |
| See | yes | yes | yes |
| Create, rename, describe, nest, delete | yes | no | yes |
| Give to another owner | yes, to a group I may add to | no | yes, to me or a group I may add to |
| Add / remove papers and notes | yes | no | yes |

- **What a collection may hold:** my collections, any paper or note I can
  see; a group's collections, only papers and notes the group owns.
- Collections nest only within one owner.
- Giving a collection to a group: the dialog says how many of its papers
  the group does not own yet; they are given to the group too (if I may
  change them) or leave the collection.
- Giving a group's collection to me: its papers stay where they are.
- Planned: showing a group's collection inside one of mine (a personal
  link); never the other way round.
- **Smart collections** hold the papers that match their rules (tags,
  type, year, owner, recently added) instead of papers added to them. Each
  person sees the matching papers they can see; a group's smart collection
  matches only the group's papers. They hold no other collections, and a
  folder they are kept in does not count their papers. Only an empty
  collection can become smart.

## Groups

| Action | Not a member | Reader or member | Admin (or admin of a group above) | Site administrator |
| --- | --- | --- | --- | --- |
| See the group and its members | no | yes | yes | yes |
| Create a top-level group | no | no | no | yes, naming its first admin |
| Create a group inside | no | no | yes | yes |
| Rename, describe | no | no | yes | yes |
| Delete (only without papers and subgroups) | no | no | yes | yes |
| Add people, change roles, remove people | no | no | yes | yes |
| Look up users to add | no | no | yes | yes |
| Leave (only a group one was added to directly) | — | yes | yes, unless the last admin | — |
| Move into another group (admin of both) or to the top (site administrators) | no | no | yes, into groups one administers | yes |

- A top-level group always keeps at least one admin of its own.
- Who is in a group through a group above leaves it there.
- When adding people, the website reminds that the group's licences must
  allow sharing its PDFs.

## Users

| Action | Everyone | Site administrator |
| --- | --- | --- |
| List users, create users | no | yes |
| Reset a password (logs the person out everywhere) | no (own password: Settings) | yes |
| Grant or take administrator rights | no | yes, but one active administrator always stays |
| Deactivate (no login; papers and groups stay), reactivate | no | yes, not oneself |

## Access tokens

Personal access tokens (Settings → Access tokens) are for scripts and AI
assistants. A token acts as its person, narrowed by its scopes and
optionally to some owners; it never gets more than the person has.

| Scope | Allows |
| --- | --- |
| `search` | Searching by words and meaning |
| `papers.read` | Papers, versions, tags, collections, notes |
| `files.read` | The files (PDFs, …) and their full text (search alone gives snippets) |
| `papers.write` | Adding, changing, merging and trashing papers and their files |
| `tags.write` | Tagging, creating and changing tags |
| `collections.write` | Creating and changing collections, filing papers |
| `groups.read` | One's groups and their members |
| `notes.write` | Writing, changing and trashing notes |

Never with a token, whatever its scopes: passwords, users, groups (changes),
tokens, imports, settings and administration (a site administrator's token
gets no administration either), nor the person's own view (stars, pinned
collections, what they opened). A token limited to some owners reaches
nothing else, also not by id. Expired or revoked tokens, and those of
deactivated people, stop working at once. Tested in
`server/tests/test_tokens.py`, which pins the answer for every route.

## Notes

| Action | My notes | A group's notes, as reader | A group's notes, as member or admin |
| --- | --- | --- | --- |
| See, search | yes | yes | yes |
| Write, change, move to the trash, restore | yes | no | yes |
| Give to another owner | yes, to a group I may add to | no | yes, to me or a group I may add to |
| Link to / unlink from papers | yes, any paper I can see | no | yes, any paper I can see |

- A note's links to papers a reader cannot see are hidden from that reader
  (like a group's tags on private papers); the note's writers can remove
  them.
- Merging papers moves the notes about the merged one (everyone's) and
  everyone's star to the paper that stays.
- A group with notes (also in its trash) cannot be deleted, like one with
  papers.
- A private note on a group's paper is visible only to its owner.
