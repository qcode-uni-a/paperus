"""What the person chooses before a paperus export is imported: where each
of its owners goes, and what its tags and collections become where names
clash with those already here (see ``paperus.importing.mapping``)."""

import uuid
from typing import Any, Literal

from pydantic import BaseModel

from paperus.importing.names import Likeness


class OwnerChoice(BaseModel):
    """Where one owner of the export goes."""

    action: Literal["library", "into", "create", "collection"] = "collection"
    """``library``: the person's own library; ``into``: the library
    ``library_id`` (a group's they may add to); ``create``: the group is
    created here, the person its admin; ``collection``: the person's own
    library, in a collection named after the group (the default for
    groups; "Me" goes to ``library`` by default)."""
    library_id: uuid.UUID | None = None


class NameChoice(BaseModel):
    """What a tag or collection of the export becomes where one of the
    same or a similar name exists here."""

    action: Literal["merge", "new", "map"]
    """``merge``: into the same-named one (``target_id``); ``new``: a new
    one ("Thesis (imported)"); ``map``: into another one here
    (``target_id``)."""
    target_id: uuid.UUID | None = None


class Choices(BaseModel):
    """The person's choices (what is not named takes its default)."""

    owners: dict[str, OwnerChoice] = {}
    """By the owner's id in the export."""
    tags: dict[str, NameChoice] = {}
    """By the tag's id in the export."""
    collections: dict[str, NameChoice] = {}
    """By the collection's id in the export."""
    all_new: bool = False
    """Every tag and collection whose name clashes is made new."""


class GroupSuggestion(BaseModel):
    library_id: uuid.UUID
    name: str
    """The group's path here ("Uni/QCode Lab")."""
    likeness: Likeness


class Suggestion(BaseModel):
    id: uuid.UUID
    name: str
    """The tag's name, or the collection's path."""
    likeness: Likeness
    papers: int


class Clash(BaseModel):
    """A tag or collection of the export with the same or a similar name
    as one where it goes."""

    kind: Literal["tag", "collection"]
    id: str
    """Its id in the export."""
    name: str
    """Its name, or the collection's path, in the export."""
    library_id: uuid.UUID
    """Where it goes."""
    smart: bool = False
    default: NameChoice
    chosen: NameChoice
    """The person's choice, else the default."""
    new_name: str
    """Its name if made new."""
    suggestions: list[Suggestion]
    """At most three, best first."""
    may_map: bool = True
    """Whether it may go into another one than the same-named (not for
    smart collections)."""
    note: str | None = None
    """Why the default is what it is, if not plain."""


class Target(BaseModel):
    """A tag or collection here an imported one may be mapped to."""

    id: uuid.UUID
    name: str
    papers: int
    smart: bool = False


class Preview(BaseModel):
    """The clashes for the owner choices given."""

    tags: list[Clash] = []
    collections: list[Clash] = []
    targets: dict[str, dict[str, list[Target]]] = {}
    """For each library with clashes (by id): its ``tags`` and
    ``collections`` (by path), to map to."""


class ExportTag(BaseModel):
    id: str
    library_id: str
    name: str
    keyword: bool
    """Only on papers as a keyword (from their details): merged with the
    same keyword by name, never asked."""


class ExportCollection(BaseModel):
    id: str
    library_id: str
    name: str
    parent_id: str | None
    rules: dict[str, Any] | None


class ExportNames(BaseModel):
    """The export's tags and collections, kept with the import for the
    choices (not shown as such)."""

    tags: list[ExportTag] = []
    collections: list[ExportCollection] = []
