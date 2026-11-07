"""Where a paperus export's owners, tags and collections go: what is
offered, the defaults, checking the person's choices, and the plan the
import follows. The rule book is docs/import-mapping.md.

Owners: "Me" goes to the person's own library; a group into a group here
(``into``), into a group created here (``create``), into the person's
library in a holding collection named after it (``collection``, the
default) or without one (``library``). Then the export's tags and
collections are compared by name with those where they go; same and nearly
the same names merge by default, similar ones are only suggested.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from paperus import organize
from paperus.access import Access
from paperus.export import owners_of
from paperus.importing.choices import (
    Choices,
    Clash,
    ExportCollection,
    ExportNames,
    GroupSuggestion,
    NameChoice,
    OwnerChoice,
    Preview,
    Suggestion,
    Target,
)
from paperus.importing.names import RANK, Likeness, likeness, score
from paperus.importing.paperus_export import (
    ImportChoices,
    NotAnExport,
    Opened,
    Plan,
    _query,
)
from paperus.models import (
    Collection,
    CollectionItem,
    Group,
    ItemTag,
    Library,
    Membership,
    Role,
    Tag,
)

SUGGESTIONS = 3
HOLDING = uuid.UUID("0e3c6f50-7c1a-4b0e-9a55-5f6a1f2d7c11")
"""Namespace of holding collections' ids: one per group of an export and
person, so importing again finds it."""


class Refused(NotAnExport):
    """A choice the person may not make (shown as it is)."""


def holding_id(owner_id: str, user_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(HOLDING, f"{owner_id}/{user_id}")


def read_names(opened: Opened) -> ExportNames:
    """The export's tags (keywords marked) and collections."""
    tags = [
        {
            "id": str(row[0]),
            "library_id": str(row[1]),
            "name": str(row[2]),
            "keyword": bool(row[4]) and not row[3],
        }
        for row in _query(
            opened.database,
            "SELECT id, library_id, name,"
            " (SELECT count(*) FROM item_tags WHERE tag_id = tags.id"
            "  AND source != 'automatic'),"
            " (SELECT count(*) FROM item_tags WHERE tag_id = tags.id)"
            " FROM tags",
        )
    ]
    collections = []
    for row in _query(
        opened.database,
        "SELECT id, library_id, name, parent_id, rules FROM collections",
    ):
        try:
            rules = organize.Rules.model_validate_json(row[4]).model_dump(mode="json")
        except (TypeError, ValueError):
            rules = {} if row[4] is not None else None
        collections.append(
            {
                "id": str(row[0]),
                "library_id": str(row[1]),
                "name": str(row[2]),
                "parent_id": str(row[3]) if row[3] is not None else None,
                "rules": rules,
            }
        )
    return ExportNames.model_validate({"tags": tags, "collections": collections})


# Owners


class _Groups:
    """Groups here by path, and which an export's group path stands for
    or may be created as."""

    def __init__(
        self, db: Session, access: Access, export: ImportChoices, chosen: Choices
    ) -> None:
        self.db = db
        self.access = access
        self.chosen = chosen
        known = owners_of(db, access)
        self.here = {o.name: o for o in known.values() if o.kind == "group"}
        """Groups the person is in, by path."""
        self.by_path = {o.name: o for o in export.owners if o.kind == "group"}
        self.done: dict[str, uuid.UUID | None] = {}

    def _admin(self, group_id: uuid.UUID) -> bool:
        return self.access.site_admin or self.access.is_group_admin(group_id)

    def _group_of(self, library_id: uuid.UUID) -> uuid.UUID | None:
        return self.db.scalar(select(Library.group_id).where(Library.id == library_id))

    def parent(self, path: str, *, make: bool) -> uuid.UUID | None:
        """The group here that ``path`` stands for as the parent of a group
        to create: one an export owner of that path goes into or is created
        as, else the group of that path here, else created (where allowed;
        None while only checking). Raises ``Refused``."""
        if path in self.done:
            return self.done[path]
        owner = self.by_path.get(path)
        choice = self.chosen.owners.get(owner.id) if owner else None
        if choice is not None and choice.action == "into" and choice.library_id:
            group_id = self._group_of(choice.library_id)
            if group_id is None or not self._admin(group_id):
                raise Refused(
                    f"A group can be made inside “{path}” only where you are "
                    "an administrator of the group it goes into."
                )
            found: uuid.UUID | None = group_id
        elif path in self.here and not (choice and choice.action == "create"):
            group_id = self.here[path].group_id
            if group_id is None or not self._admin(group_id):
                raise Refused(
                    f"Only the administrators of “{path}” can make groups inside it."
                )
            found = group_id
        else:
            found = self.create(path, make=make)
        self.done[path] = found
        return found

    def create(self, path: str, *, make: bool) -> uuid.UUID | None:
        """Create the group of this path (with the levels above it that are
        missing), the person its admin; None while only checking."""
        if path in self.here:
            raise Refused(
                f"“{path}” exists here already: choose to put its papers into it."
            )
        above, _, name = path.rpartition("/")
        parent_id = self.parent(above, make=make) if above else None
        if not above and not self.access.site_admin:
            raise Refused(
                f"Only site administrators can create top-level groups such as "
                f"“{path}”."
            )
        if not make:
            return None
        group = Group(
            name=organize.clean_name(name)[:200],
            parent_id=parent_id,
            created_by=self.access.user.id,
        )
        self.db.add(group)
        self.db.flush()
        self.db.add(Library(group_id=group.id))
        self.db.add(
            Membership(
                group_id=group.id,
                user_id=self.access.user.id,
                role=Role.ADMIN,
                added_by=self.access.user.id,
            )
        )
        self.db.flush()
        self.done[path] = group.id
        return group.id


def describe_owners(db: Session, access: Access, export: ImportChoices) -> None:
    """For each group of the export: whether the person may create it here,
    and groups here of a similar name (suggested, never chosen)."""
    writable = [
        o
        for o in owners_of(db, access).values()
        if o.kind == "group" and access.can_write(o.id)
    ]
    for owner in export.owners:
        if owner.kind != "group":
            continue
        try:
            _Groups(db, access, export, Choices()).create(owner.name, make=False)
            owner.can_create = True
        except Refused:
            owner.can_create = False
        owner.suggestions = [
            GroupSuggestion(library_id=here.id, name=here.name, likeness=like)
            for here, like in _best(owner.name, ((h, h.name) for h in writable))
        ]


@dataclass
class _Owner:
    library_id: uuid.UUID | None
    """Where its things go; None: a group created by the import (empty)."""
    holding: bool = False


def _owners(
    db: Session,
    access: Access,
    export: ImportChoices,
    chosen: Choices,
    *,
    default: uuid.UUID | None = None,
    make: bool = False,
) -> tuple[dict[str, _Owner], _Groups]:
    """Each owner's place, checked; groups created with ``make``."""
    groups = _Groups(db, access, export, chosen)
    known = {o.id for o in export.owners}
    for key in chosen.owners:
        if key not in known:
            raise ValueError(f"the export has no owner {key}")
    places: dict[str, _Owner] = {}
    for owner in sorted(export.owners, key=lambda o: o.name.count("/")):
        if owner.kind == "me":
            fallback = OwnerChoice(action="library")
        elif default is not None and default != access.own_library:
            fallback = OwnerChoice(action="into", library_id=default)
        else:
            fallback = OwnerChoice(action="collection")
        choice = chosen.owners.get(owner.id, fallback)
        if owner.kind == "me" and choice.action != "library":
            raise ValueError("“Me” goes into your library")
        if choice.action == "into":
            if choice.library_id is None or not access.can_read(choice.library_id):
                raise LookupError("library not found")
            if not access.can_write(choice.library_id):
                raise Refused("You may not add papers there.")
            places[owner.id] = _Owner(choice.library_id)
        elif choice.action == "create":
            group_id = groups.create(owner.name, make=make)
            library_id = (
                db.scalar(select(Library.id).where(Library.group_id == group_id))
                if group_id
                else None
            )
            places[owner.id] = _Owner(library_id)
        else:
            places[owner.id] = _Owner(
                access.own_library, holding=choice.action == "collection"
            )
    return places, groups


# Tags and collections


@dataclass
class _Here:
    """A library's tags and collections, for comparing."""

    tags: list[Target] = field(default_factory=list)
    collections: list[tuple[Collection, str, int]] = field(default_factory=list)
    """Each with its path and number of papers."""


def _library(db: Session, library_id: uuid.UUID) -> _Here:
    tag_counts = dict(
        db.execute(
            select(ItemTag.tag_id, func.count())
            .join(Tag, Tag.id == ItemTag.tag_id)
            .where(Tag.library_id == library_id)
            .group_by(ItemTag.tag_id)
        ).all()
    )
    tags = [
        Target(id=tag.id, name=tag.name, papers=tag_counts.get(tag.id, 0))
        for tag in db.scalars(
            select(Tag).where(Tag.library_id == library_id).order_by(Tag.name)
        )
    ]
    collections = list(
        db.scalars(select(Collection).where(Collection.library_id == library_id))
    )
    counts = dict(
        db.execute(
            select(CollectionItem.collection_id, func.count())
            .where(CollectionItem.collection_id.in_([c.id for c in collections]))
            .group_by(CollectionItem.collection_id)
        ).all()
    )
    by_id = {c.id: c for c in collections}

    def path(collection: Collection) -> str:
        names, current = [], collection
        while current is not None:
            names.insert(0, current.name)
            current = by_id.get(current.parent_id) if current.parent_id else None
        return "/".join(names)

    return _Here(
        tags=tags,
        collections=sorted(
            ((c, path(c), counts.get(c.id, 0)) for c in collections),
            key=lambda entry: entry[1].lower(),
        ),
    )


def _unique(name: str, taken: Iterable[str]) -> str:
    """ "Thesis (imported)", "Thesis (imported 2)", … not among ``taken``."""
    used = {t.casefold() for t in taken}
    number = 1
    while True:
        candidate = f"{name} (imported{f' {number}' if number > 1 else ''})"
        if candidate.casefold() not in used:
            return candidate
        number += 1


def _best[T](
    name: str, candidates: Iterable[tuple[T, str]]
) -> list[tuple[T, Likeness]]:
    """The candidates like ``name`` (each with its name), best first, at
    most ``SUGGESTIONS``."""
    found = [
        (score(name, other) or (len(RANK), 0.0), candidate, like)
        for candidate, other in candidates
        if (like := likeness(name, other)) is not None
    ]
    found.sort(key=lambda entry: entry[0])
    return [(candidate, like) for _, candidate, like in found[:SUGGESTIONS]]


def _ranked(
    name: str, candidates: Iterable[tuple[uuid.UUID, str, int]]
) -> list[Suggestion]:
    return [
        Suggestion(id=id_, name=other, likeness=like, papers=n)
        for (id_, other, n), like in _best(name, ((c, c[1]) for c in candidates))
    ]


def _rules_key(
    rules: dict[str, Any], tag_names: dict[str, str], owners: dict[str, str]
) -> dict[str, Any]:
    """Rules with tags by name and owners by library here, to compare
    (through ``Rules``, so rules stored before a rule existed compare the
    same)."""
    key = organize.Rules.model_validate(rules).model_dump(mode="json")
    for name in ("tags_all", "tags_any", "tags_none"):
        key[name] = sorted(tag_names.get(str(t), str(t)).casefold() for t in key[name])
    key["owners"] = sorted(owners.get(str(o), str(o)) for o in key["owners"])
    return key


def preview(
    db: Session,
    access: Access,
    export: ImportChoices,
    names: ExportNames,
    chosen: Choices,
    *,
    default: uuid.UUID | None = None,
) -> Preview:
    """The clashes for these owner choices (checked; raises ``Refused``,
    ``LookupError`` or ``ValueError``), with each one's default and choice."""
    places, _ = _owners(db, access, export, chosen, default=default)
    return _clashes(db, access, names, chosen, places)


def _clashes(
    db: Session,
    access: Access,
    names: ExportNames,
    chosen: Choices,
    places: dict[str, _Owner],
) -> Preview:
    result = Preview()
    libraries: dict[uuid.UUID, _Here] = {}

    def here(library_id: uuid.UUID) -> _Here:
        if library_id not in libraries:
            libraries[library_id] = _library(db, library_id)
        return libraries[library_id]

    def decided(clash: Clash, given: NameChoice | None) -> Clash:
        clash.chosen = clash.default if given is None else given
        return clash

    # Tags: keywords join by name; tags already imported are found by id.
    for tag in names.tags:
        place = places.get(tag.library_id)
        if tag.keyword or place is None or place.library_id is None:
            continue
        if _readable(db, access, Tag, tag.id):
            continue
        target = here(place.library_id)
        suggestions = _ranked(tag.name, ((t.id, t.name, t.papers) for t in target.tags))
        if not suggestions:
            continue
        best = suggestions[0]
        default = (
            NameChoice(action="merge", target_id=best.id)
            if best.likeness in ("same", "nearly") and not chosen.all_new
            else NameChoice(action="new")
        )
        result.tags.append(
            decided(
                Clash(
                    kind="tag",
                    id=tag.id,
                    name=tag.name,
                    library_id=place.library_id,
                    default=default,
                    chosen=default,
                    new_name=_unique(tag.name, (t.name for t in target.tags)),
                    suggestions=suggestions,
                ),
                chosen.tags.get(tag.id),
            )
        )

    # Collections, parents first, each compared within where it lands.
    tag_names = {t.id: t.name for t in names.tags}
    owner_libraries = {
        key: str(place.library_id) for key, place in places.items() if place.library_id
    }
    landing: dict[str, uuid.UUID | None] = {}
    """Export collection → the collection here it merges into (its
    children are compared inside); None: made new (nothing to compare)."""
    for collection in _parents_first(names.collections):
        place = places.get(collection.library_id)
        if place is None or place.library_id is None or place.holding:
            landing[collection.id] = None
            continue
        if collection.parent_id is not None and collection.parent_id in landing:
            parent_here = landing[collection.parent_id]
            if parent_here is None:
                landing[collection.id] = None
                continue
        else:
            parent_here = None
        same_id = _readable(db, access, Collection, collection.id)
        if same_id is not None:
            landing[collection.id] = same_id  # imported before
            continue
        target = here(place.library_id)
        siblings = [c for c, _, _ in target.collections if c.parent_id == parent_here]
        close = [
            s
            for s in _ranked(
                collection.name,
                ((c.id, c.name, n) for c, _, n in target.collections if c in siblings),
            )
            if s.likeness in ("same", "nearly")
        ]
        similar = [
            s
            for s in _ranked(
                collection.name, ((c.id, p, n) for c, p, n in target.collections)
            )
            if s.likeness == "similar" and s.id not in {c.id for c in close}
        ]
        suggestions = (close + similar)[:SUGGESTIONS]
        if not suggestions:
            landing[collection.id] = None
            continue
        smart = collection.rules is not None
        note = None
        default = NameChoice(action="new")
        if close and not chosen.all_new:
            best = next(c for c, _, _ in target.collections if c.id == close[0].id)
            if smart or best.rules is not None:
                same_rules = (
                    smart
                    and best.rules is not None
                    and _rules_key(collection.rules, tag_names, owner_libraries)
                    == _rules_key(
                        best.rules, {str(t.id): t.name for t in target.tags}, {}
                    )
                )
                if same_rules:
                    default = NameChoice(action="merge", target_id=best.id)
                else:
                    note = (
                        "A smart collection of this name with other rules is "
                        "there: it is imported as a new one."
                        if smart
                        else "The one of this name there is a smart collection: "
                        "it is imported as a new one."
                    )
            else:
                default = NameChoice(action="merge", target_id=best.id)
        clash = decided(
            Clash(
                kind="collection",
                id=collection.id,
                name=_export_path(collection, names.collections),
                library_id=place.library_id,
                smart=smart,
                default=default,
                chosen=default,
                new_name=_unique(collection.name, (c.name for c in siblings)),
                suggestions=suggestions,
                may_map=not smart,
                note=note,
            ),
            chosen.collections.get(collection.id),
        )
        result.collections.append(clash)
        landing[collection.id] = (
            clash.chosen.target_id if clash.chosen.action != "new" else None
        )
    for library_id in {c.library_id for c in [*result.tags, *result.collections]}:
        found = here(library_id)
        result.targets[str(library_id)] = {
            "tags": found.tags,
            "collections": [
                Target(id=c.id, name=p, papers=n, smart=c.rules is not None)
                for c, p, n in found.collections
            ],
        }
    return result


def _readable(
    db: Session, access: Access, model: type[Tag] | type[Collection], value: str
) -> uuid.UUID | None:
    """The id, if a tag or collection of it is here and the person sees it
    (made by an import before)."""
    try:
        found = db.get(model, uuid.UUID(value))
    except ValueError:
        return None
    return found.id if found is not None and access.can_read(found.library_id) else None


def _parents_first(collections: list[ExportCollection]) -> list[ExportCollection]:
    ids = {c.id for c in collections}
    by_parent: dict[str | None, list[ExportCollection]] = {}
    for collection in collections:
        parent = collection.parent_id if collection.parent_id in ids else None
        by_parent.setdefault(parent, []).append(collection)
    ordered: list[ExportCollection] = []
    waiting: list[str | None] = [None]
    while waiting:
        for collection in by_parent.pop(waiting.pop(0), []):
            ordered.append(collection)
            waiting.append(collection.id)
    return ordered


def _export_path(collection: ExportCollection, all_: list[ExportCollection]) -> str:
    by_id = {c.id: c for c in all_}
    names: list[str] = []
    current: ExportCollection | None = collection
    while current is not None:
        names.insert(0, current.name)
        current = by_id.get(current.parent_id) if current.parent_id else None
    return "/".join(names)


def check(
    db: Session,
    access: Access,
    export: ImportChoices,
    names: ExportNames,
    chosen: Choices,
) -> Preview:
    """The choices, checked before the import starts (raises ``Refused``,
    ``LookupError`` or ``ValueError`` with what is wrong)."""
    found = preview(db, access, export, names, chosen)
    for clash in [*found.tags, *found.collections]:
        _valid(clash, found)
    for key in chosen.tags:
        if key not in {c.id for c in found.tags}:
            raise ValueError(f"the tag {key} needs no choice")
    for key in chosen.collections:
        if key not in {c.id for c in found.collections}:
            raise ValueError(f"the collection {key} needs no choice")
    return found


def _valid(clash: Clash, found: Preview) -> None:
    """The chosen target is there and may take it."""
    choice = clash.chosen
    if choice.action == "new":
        return
    targets = found.targets[str(clash.library_id)][
        "tags" if clash.kind == "tag" else "collections"
    ]
    target = next((t for t in targets if t.id == choice.target_id), None)
    if target is None:
        raise ValueError(f"“{clash.name}” cannot go there")
    if clash.kind != "collection":
        return
    if clash.smart and choice != clash.default:
        raise ValueError(
            f"The smart collection “{clash.name}” merges only into one with "
            "the same rules"
        )
    if not clash.smart and target.smart:
        raise ValueError(
            f"“{clash.name}” cannot go into a smart collection (it holds no "
            "papers added to it)"
        )


# Following the choices


def holding_description(path: str, server: str | None, exported_at: str) -> str:
    where = f" from {server}" if server else ""
    return (
        f"Papers of the group “{path}”{where}, exported on {exported_at[:10]}. "
        "Once the group exists here, set this collection's owner to the group "
        "(Edit collection → Owner, with “also move the papers”): the papers "
        "and the collections inside move there. Notes and tags stay yours; "
        "move them by hand."
    )


def prepare(
    db: Session,
    access: Access,
    export: ImportChoices,
    names: ExportNames,
    chosen: Choices | None,
    *,
    default: uuid.UUID,
) -> Plan:
    """Check the choices again, create the groups chosen to be created and
    the holding collections, and give the plan for the import (commits).
    Without choices (``paperus import`` on the command line): "Me" to the
    person's library, groups into holding collections, or everything to
    ``default`` if that is a group."""
    chosen = chosen or Choices()
    try:
        places, _ = _owners(db, access, export, chosen, default=default, make=True)
    except Refused:
        raise
    except (LookupError, ValueError) as error:
        raise Refused(f"The choices cannot be followed: {error}.") from error
    db.flush()
    # The person is admin of what they created: read their rights again.
    access = Access.of(db, access.user)
    plan = Plan(
        owners={
            key: place.library_id for key, place in places.items() if place.library_id
        }
    )
    for owner in export.owners:
        if places[owner.id].holding:
            plan.holding[owner.id] = _holding(db, access, owner.id, owner.name, export)
    found = _clashes(db, access, names, chosen, places)
    for clash in [*found.tags, *found.collections]:
        try:
            _valid(clash, found)
        except ValueError as error:
            raise Refused(f"{error}.") from error
        decided = (
            ("new", clash.new_name)
            if clash.chosen.action == "new"
            else (clash.chosen.action, clash.chosen.target_id)
        )
        if clash.kind == "tag":
            plan.tags[clash.id] = decided
        else:
            plan.collections[clash.id] = decided
    db.commit()
    return plan


def _holding(
    db: Session, access: Access, owner_id: str, path: str, export: ImportChoices
) -> uuid.UUID:
    """The holding collection of an export's group: found again, else made
    (named after the group, unique among the person's collections)."""
    collection_id = holding_id(owner_id, access.user.id)
    found = db.get(Collection, collection_id)
    if found is not None and access.can_read(found.library_id):
        return found.id
    top = set(
        db.scalars(
            select(Collection.name).where(
                Collection.library_id == access.own_library,
                Collection.parent_id.is_(None),
            )
        )
    )
    name = organize.clean_name(path.rsplit("/", 1)[-1])[:190]
    unique, number = name, 1
    while unique.casefold() in {t.casefold() for t in top}:
        number += 1
        unique = f"{name} ({number})"
    db.add(
        Collection(
            id=collection_id,
            library_id=access.own_library,
            name=unique,
            description=holding_description(
                path, export.server_url, export.exported_at
            ),
            created_by=access.user.id,
            change=0,
        )
    )
    db.flush()
    return collection_id
