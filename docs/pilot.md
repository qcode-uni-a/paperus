# Pilot

The tester-facing proposal (short, with a diagram) is a shared doc:
"Shared Research Library: Design Proposal" (https://claude.ai/artifact/V2r7EQagTMTDpNBJzW6Pek).
This file keeps the plan and the questions in the repository.

## Plan

1. **Before building**: send the proposal and the questions. Feedback is
   optional; talk to those who want to. Ask more about current habits than
   about the idea.
2. **Prototype**: adding papers (DOI, upload), a shared collection, search by
   meaning, BibTeX export, MCP connection.
3. **Two to three weeks of real use** by the group, five-minute check-in each
   week. Note failed searches, feature requests, and who struggles with the
   MCP setup.

What we want to learn:

- Does search by meaning find what people look for?
- Is a shared library plus AI access worth switching for, or do people want it
  next to Zotero?
- Which writing tools must work first?
- How much setup do people accept for the AI connection?

## Questions for testers

1. What do you use for papers today (Zotero, Mendeley, folders)? What annoys
   you most about it?
2. When did you last fail to find a paper you knew you had read? What did you
   search for?
3. Do you use AI for literature work? Which tools, and is there anything you
   would not send to them?
4. Which of your notes would you share with the group, and which should stay
   private?
5. What do you write in, and how do you insert citations?
6. What must survive moving your library over, and what would make you quit
   after a week?

## Requirements collected so far

- Local cache of PDFs; opening must be fast (content-addressed cache in the
  browser's private file storage via a service worker, range requests,
  server-rendered first page).
- Multiple versions per item: internal drafts, preprint, published, … (see
  [ingestion.md](ingestion.md)).
- AI with its own space for notes, tags and uploads, and a clear way to
  interact with the user (open: see [ai.md](ai.md)).
- Automatic links between related papers, as a list or a graph (later).
- Easy to use: university login, the admin adds you to a group, upload or
  import papers and go.
- Metadata-only items, with automatic open-access PDF lookup.
- User notes and annotations included in search by meaning.
- Other sources: lecture notes (also from Overleaf/GitLab), meeting notes,
  handwritten notes.
- Frequent updates (e.g. typo fixes in long lecture notes) must not clutter
  the database.
- Private space is visible only to its owner and the owner's AI assistant
  (promised in the proposal), not to group admins.
