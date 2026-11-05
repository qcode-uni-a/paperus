"""Who may read and change which library.

A person reads their own library and those of the groups they belong to,
including every group inside those (membership is inherited downwards, and a
subgroup can only raise a role). Site administrators manage users and groups
but read no library because of it. All of this is worked out once per
request (``Access.of``) from the group tree, which is small, and the person's
memberships; lists and searches then filter by library ID in SQL.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import ColumnElement, select
from sqlalchemy.orm import Session

from paperus.models import (
    ROLE_RANK,
    Group,
    Item,
    Library,
    Membership,
    Role,
    User,
)


class Forbidden(Exception):
    """The person may see this but not change it (HTTP 403)."""


class NotVisible(Exception):
    """The person may not see this; answered like a missing object (404)."""


@dataclass
class Access:
    user: User
    own_library: uuid.UUID
    roles: dict[uuid.UUID, Role] = field(default_factory=dict)
    """Effective role per group (direct or inherited)."""
    group_libraries: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    """Library of each group the person belongs to."""
    own_allowed: bool = True
    """False for an access token limited to some groups' libraries."""

    @classmethod
    def of(
        cls, db: Session, user: User, only: list[uuid.UUID] | None = None
    ) -> "Access":
        """What ``user`` may do; with ``only`` (an access token's owner limit),
        nothing outside these libraries."""
        own = db.scalar(select(Library.id).where(Library.user_id == user.id))
        if own is None:  # users from before libraries existed get one now
            library = Library(user_id=user.id)
            db.add(library)
            db.flush()
            own = library.id
        parents: dict[uuid.UUID, uuid.UUID | None] = {
            group_id: parent
            for group_id, parent in db.execute(select(Group.id, Group.parent_id))
        }
        direct = {
            group_id: Role(role)
            for group_id, role in db.execute(
                select(Membership.group_id, Membership.role).where(
                    Membership.user_id == user.id
                )
            )
        }
        roles: dict[uuid.UUID, Role] = {}
        for group_id in parents:
            # The highest role on the way up to the top.
            best: Role | None = None
            current: uuid.UUID | None = group_id
            while current is not None:
                role = direct.get(current)
                if role and (best is None or ROLE_RANK[role] > ROLE_RANK[best]):
                    best = role
                current = parents.get(current)
            if best is not None:
                roles[group_id] = best
        libraries = {
            group_id: library_id
            for group_id, library_id in db.execute(
                select(Library.group_id, Library.id).where(Library.group_id.in_(roles))
            )
            if group_id is not None
        }
        if only is None:
            return cls(user, own, roles, libraries)
        allowed = set(only)
        libraries = {g: lib for g, lib in libraries.items() if lib in allowed}
        roles = {g: r for g, r in roles.items() if g in libraries}
        return cls(user, own, roles, libraries, own_allowed=own in allowed)

    @property
    def readable(self) -> list[uuid.UUID]:
        """Libraries this person may read: their own and their groups'."""
        own = [self.own_library] if self.own_allowed else []
        return [*own, *self.group_libraries.values()]

    def role_in_library(self, library_id: uuid.UUID) -> Role | None:
        for group_id, group_library in self.group_libraries.items():
            if group_library == library_id:
                return self.roles[group_id]
        return None

    def can_read(self, library_id: uuid.UUID) -> bool:
        return (
            library_id == self.own_library
            or library_id in self.group_libraries.values()
        )

    def can_write(self, library_id: uuid.UUID) -> bool:
        """Add, change and delete items, tags and collections."""
        if library_id == self.own_library:
            return self.own_allowed
        role = self.role_in_library(library_id)
        return role is not None and ROLE_RANK[role] >= ROLE_RANK[Role.MEMBER]

    @property
    def writable(self) -> list[uuid.UUID]:
        return [library for library in self.readable if self.can_write(library)]

    def is_group_admin(self, group_id: uuid.UUID) -> bool:
        return self.roles.get(group_id) == Role.ADMIN

    def require_write(self, library_id: uuid.UUID) -> None:
        if not self.can_write(library_id):
            raise Forbidden("readers cannot change this library")

    # Items have one owner (``Item.library_id``): a person or a group.

    def can_read_item(self, item: Item) -> bool:
        return self.can_read(item.library_id)

    def can_write_item(self, item: Item) -> bool:
        return self.can_write(item.library_id)

    def require_write_item(self, item: Item) -> None:
        if not self.can_write_item(item):
            raise Forbidden("readers cannot change this item")

    def item_filter(
        self, libraries: list[uuid.UUID] | None = None
    ) -> ColumnElement[bool]:
        """Items owned by these (by default: everything the person reads)."""
        return Item.library_id.in_(self.readable if libraries is None else libraries)

    def may_tag(self, library_id: uuid.UUID, item: Item) -> bool:
        """Whether the person may put a tag of ``library_id`` on (or take it
        off) the item: their private tags on any item they see; a group's
        tags (they read) on any item they may change, e.g. their own papers
        with the group's vocabulary."""
        if library_id == self.own_library:
            return self.own_allowed and self.can_read_item(item)
        return self.can_read(library_id) and self.can_write_item(item)

    def may_hold(self, library_id: uuid.UUID, item: Item) -> bool:
        """Whether a collection of ``library_id`` may hold the item: a group's
        only the group's items, a person's private ones any item the person
        can read."""
        if library_id == self.own_library:
            return self.own_allowed and self.can_read_item(item)
        return library_id == item.library_id

    def target_library(self, requested: uuid.UUID | None) -> uuid.UUID:
        """Where something new goes: the library asked for (if the person may
        add to it), else their default library, else their own."""
        if requested is not None:
            if not self.can_read(requested):
                raise NotVisible("library not found")
            self.require_write(requested)
            return requested
        default = self.user.default_library_id
        if default is not None and self.can_write(default):
            return default
        if self.own_allowed:
            return self.own_library
        writable = self.writable
        if not writable:
            raise Forbidden("this token may not add anything")
        return writable[0]
