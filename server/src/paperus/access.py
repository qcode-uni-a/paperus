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

from sqlalchemy import select
from sqlalchemy.orm import Session

from paperus.models import ROLE_RANK, Group, Library, Membership, Role, User


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

    @classmethod
    def of(cls, db: Session, user: User) -> "Access":
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
        return cls(user, own, roles, libraries)

    @property
    def readable(self) -> list[uuid.UUID]:
        """Libraries this person may read: their own and their groups'."""
        return [self.own_library, *self.group_libraries.values()]

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
            return True
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

    def may_hold(self, library_id: uuid.UUID, item_library_id: uuid.UUID) -> bool:
        """Whether a tag or collection of ``library_id`` may hold an item of
        ``item_library_id``: a group's only its own items, a person's private
        ones any item the person can read."""
        if library_id == self.own_library:
            return self.can_read(item_library_id)
        return library_id == item_library_id

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
        return self.own_library
