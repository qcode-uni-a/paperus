"""Groups, their members, and the libraries a person can use.

Site administrators create top-level groups and may manage every group's
members; group admins manage their group and the groups inside it. Neither
reads a library because of it (see ``paperus.access``).
"""

import uuid
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from paperus import organize
from paperus.access import Access, Forbidden
from paperus.api.deps import DB, CurrentAccess
from paperus.avatars import avatar_url
from paperus.models import (
    ROLE_RANK,
    Group,
    Item,
    Library,
    Membership,
    Note,
    Role,
    User,
)

router = APIRouter(tags=["groups"])

Name = Annotated[str, Field(min_length=1, max_length=200)]


class LibraryOut(BaseModel):
    id: uuid.UUID
    name: str
    """"Me" or the group's name."""
    kind: Literal["personal", "group"]
    group_id: uuid.UUID | None
    path: list[str]
    """Names of the groups above, top first (for nested groups)."""
    role: Role | None
    """The person's role in the group; ``None`` for their own library."""
    writable: bool
    """Whether the person may add and change items here."""
    default: bool
    """Where new items go unless another library is chosen."""


class DefaultLibrary(BaseModel):
    library_id: uuid.UUID


class GroupOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    parent_id: uuid.UUID | None
    library_id: uuid.UUID
    role: Role | None
    """The person's role (direct or inherited); ``None`` for site
    administrators who are not members."""
    can_manage: bool
    """Whether the person may change the group, its members and subgroups."""
    members: int
    """Direct members (people inherited from groups above not counted)."""
    items: int | None
    """Items in the group's library; only for its members."""
    created_at: datetime


class GroupIn(BaseModel):
    name: Name
    description: str | None = None
    parent_id: uuid.UUID | None = None
    admin_id: uuid.UUID | None = None
    """First admin of a top-level group; the creator if not given."""


class GroupChange(BaseModel):
    name: Name | None = None
    description: str | None = None
    parent_id: uuid.UUID | None = None
    """Move into another group (whose admin one is), or ``null`` to the top
    (site administrators); never into itself or a group inside it."""


class MemberOut(BaseModel):
    user_id: uuid.UUID
    username: str
    role: Role
    """Effective role: the highest of the direct and inherited ones."""
    direct_role: Role | None
    """Given in this group; ``None`` if only inherited."""
    inherited_from: str | None
    """The group above that gives the (higher) inherited role, if any."""
    avatar_url: str | None = None


class MemberIn(BaseModel):
    role: Role


class UserBrief(BaseModel):
    id: uuid.UUID
    username: str


def _ancestors(db: DB, group: Group) -> list[Group]:
    """The groups above, nearest first."""
    found: list[Group] = []
    while group.parent_id is not None:
        # Groups with groups inside cannot be deleted: the parent is there.
        group = db.get_one(Group, group.parent_id)
        found.append(group)
    return found


def _library_of(db: DB, group_id: uuid.UUID) -> uuid.UUID:
    # Every group gets one when created.
    return db.scalars(select(Library.id).where(Library.group_id == group_id)).one()


def _can_manage(access: Access, group_id: uuid.UUID) -> bool:
    return access.site_admin or access.is_group_admin(group_id)


def _visible_group(db: DB, access: Access, group_id: uuid.UUID) -> Group:
    group = db.get(Group, group_id)
    if group is None or not (access.site_admin or group_id in access.roles):
        raise HTTPException(404, "group not found")
    return group


def _managed_group(db: DB, access: Access, group_id: uuid.UUID) -> Group:
    group = _visible_group(db, access, group_id)
    if not _can_manage(access, group_id):
        raise HTTPException(403, "only the group's admins can change it")
    return group


# Libraries


@router.get("/api/libraries")
def list_libraries(db: DB, access: CurrentAccess) -> list[LibraryOut]:
    """The libraries the person can read: their own first, then their groups'."""
    try:
        default: uuid.UUID | None = access.target_library(None)
    except Forbidden:  # a read-only token limited to groups
        default = None
    groups = {
        group.id: group
        for group in db.scalars(select(Group).where(Group.id.in_(access.roles)))
    }
    parents = dict(db.execute(select(Group.id, Group.parent_id)).all())
    names = dict(db.execute(select(Group.id, Group.name)).all())

    def path(group_id: uuid.UUID) -> list[str]:
        above: list[str] = []
        current = parents.get(group_id)
        while current is not None:
            above.insert(0, names[current])
            current = parents.get(current)
        return above

    libraries = (
        [
            LibraryOut(
                id=access.own_library,
                name="Me",
                kind="personal",
                group_id=None,
                path=[],
                role=None,
                writable=True,
                default=default == access.own_library,
            )
        ]
        if access.own_allowed
        else []
    )
    group_libraries = sorted(
        access.group_libraries.items(),
        key=lambda pair: [n.lower() for n in [*path(pair[0]), groups[pair[0]].name]],
    )
    for group_id, library_id in group_libraries:
        libraries.append(
            LibraryOut(
                id=library_id,
                name=groups[group_id].name,
                kind="group",
                group_id=group_id,
                path=path(group_id),
                role=access.roles[group_id],
                writable=access.can_write(library_id),
                default=default == library_id,
            )
        )
    return libraries


@router.put("/api/me/default-library", status_code=204)
def set_default_library(
    body: DefaultLibrary, db: DB, access: CurrentAccess
) -> Response:
    """Where new items go unless another library is chosen."""
    access.target_library(body.library_id)  # readable and writable
    access.user.default_library_id = body.library_id
    db.commit()
    return Response(status_code=204)


# Groups


def _group_out(db: DB, access: Access, group: Group) -> GroupOut:
    library_id = _library_of(db, group.id)
    members = db.scalar(select(func.count()).where(Membership.group_id == group.id))
    role = access.roles.get(group.id)
    items = None
    if role is not None:
        items = db.scalar(
            select(func.count()).where(
                Item.library_id == library_id, Item.deleted_at.is_(None)
            )
        )
    return GroupOut(
        id=group.id,
        name=group.name,
        description=group.description,
        parent_id=group.parent_id,
        library_id=library_id,
        role=role,
        can_manage=_can_manage(access, group.id),
        members=members or 0,
        items=items,
        created_at=group.created_at,
    )


@router.get("/api/groups")
def list_groups(db: DB, access: CurrentAccess) -> list[GroupOut]:
    """The groups the person belongs to (directly or through a group above);
    site administrators see every group. Flat; ``parent_id`` gives the tree."""
    query = select(Group).order_by(func.lower(Group.name))
    if not access.site_admin:
        query = query.where(Group.id.in_(access.roles))
    return [_group_out(db, access, group) for group in db.scalars(query)]


@router.post("/api/groups", status_code=201)
def create_group(body: GroupIn, db: DB, access: CurrentAccess) -> GroupOut:
    """A group with its library. Top-level groups: site administrators only,
    with a first admin. Subgroups: the parent's admins (who are then admins
    of the subgroup too)."""
    try:
        name = organize.clean_name(body.name)
    except ValueError as error:
        raise HTTPException(422, str(error)) from error
    if body.parent_id is None:
        if not access.site_admin:
            raise HTTPException(403, "only site administrators create top-level groups")
        admin_id = body.admin_id or access.user.id
        if db.get(User, admin_id) is None:
            raise HTTPException(422, "unknown user for the first admin")
    else:
        _managed_group(db, access, body.parent_id)
        admin_id = None
    group = Group(
        name=name,
        description=(body.description or "").strip() or None,
        parent_id=body.parent_id,
        created_by=access.user.id,
    )
    db.add(group)
    db.flush()
    db.add(Library(group_id=group.id))
    if admin_id is not None:
        db.add(
            Membership(
                group_id=group.id,
                user_id=admin_id,
                role=Role.ADMIN,
                added_by=access.user.id,
            )
        )
    db.commit()
    return _group_out(db, Access.of(db, access.user), group)


@router.patch("/api/groups/{group_id}")
def change_group(
    group_id: uuid.UUID, body: GroupChange, db: DB, access: CurrentAccess
) -> GroupOut:
    group = _managed_group(db, access, group_id)
    if body.name is not None:
        try:
            group.name = organize.clean_name(body.name)
        except ValueError as error:
            raise HTTPException(422, str(error)) from error
    if "description" in body.model_fields_set:
        group.description = (body.description or "").strip() or None
    if "parent_id" in body.model_fields_set and body.parent_id != group.parent_id:
        _move(db, access, group, body.parent_id)
    db.commit()
    return _group_out(db, Access.of(db, access.user), group)


def _move(db: DB, access: Access, group: Group, parent_id: uuid.UUID | None) -> None:
    if parent_id is None:
        if not access.site_admin:
            raise HTTPException(403, "only site administrators make top-level groups")
    else:
        _managed_group(db, access, parent_id)
        current: uuid.UUID | None = parent_id
        while current is not None:
            if current == group.id:
                raise HTTPException(409, "a group cannot move into itself")
            above = db.get(Group, current)
            current = above.parent_id if above else None
    group.parent_id = parent_id


@router.delete("/api/groups/{group_id}", status_code=204)
def delete_group(group_id: uuid.UUID, db: DB, access: CurrentAccess) -> Response:
    """Delete an empty group: no groups inside and no items or notes (not
    even in its trash). Its tags, collections and memberships go with it."""
    group = _managed_group(db, access, group_id)
    if db.scalar(select(func.count()).where(Group.parent_id == group.id)):
        raise HTTPException(409, "delete or move the groups inside first")
    library_id = _library_of(db, group.id)
    if db.scalar(select(func.count()).where(Item.library_id == library_id)):
        raise HTTPException(409, "the group's library still has items")
    if db.scalar(select(func.count()).where(Note.library_id == library_id)):
        raise HTTPException(409, "the group's library still has notes")
    db.delete(group)
    db.commit()
    return Response(status_code=204)


# Members


@router.get("/api/groups/{group_id}/members")
def list_members(group_id: uuid.UUID, db: DB, access: CurrentAccess) -> list[MemberOut]:
    """Everyone in the group: given a role here or in a group above."""
    group = _visible_group(db, access, group_id)
    chain = [group, *_ancestors(db, group)]
    names = {g.id: g.name for g in chain}
    rows = db.execute(
        select(Membership, User.username, User.avatar_version)
        .join(User, User.id == Membership.user_id)
        .where(Membership.group_id.in_(names))
    )
    members: dict[uuid.UUID, MemberOut] = {}
    for membership, username, avatar_version in rows:
        role = Role(membership.role)
        here = membership.group_id == group.id
        current = members.get(membership.user_id) or MemberOut(
            user_id=membership.user_id,
            username=username,
            role=role,
            direct_role=None,
            inherited_from=None,
            avatar_url=avatar_url(membership.user_id, avatar_version),
        )
        if here:
            current.direct_role = role
        elif (
            current.inherited_from is None or ROLE_RANK[role] > ROLE_RANK[current.role]
        ):
            current.inherited_from = names[membership.group_id]
        if ROLE_RANK[role] >= ROLE_RANK[current.role]:
            current.role = role
        members[membership.user_id] = current
    for member in members.values():
        # Inherited only matters while it is what gives the role.
        if (
            member.direct_role is not None
            and ROLE_RANK[member.direct_role] >= ROLE_RANK[member.role]
        ):
            member.inherited_from = None
    return sorted(
        members.values(), key=lambda m: (-ROLE_RANK[m.role], m.username.lower())
    )


@router.put("/api/groups/{group_id}/members/{user_id}")
def set_member(
    group_id: uuid.UUID,
    user_id: uuid.UUID,
    body: MemberIn,
    db: DB,
    access: CurrentAccess,
) -> list[MemberOut]:
    """Add someone to the group, or change their role here. A role lower than
    one inherited from a group above has no effect (inherited roles win)."""
    _managed_group(db, access, group_id)
    if db.get(User, user_id) is None:
        raise HTTPException(404, "user not found")
    membership = db.get(Membership, (group_id, user_id))
    if membership is None:
        membership = Membership(
            group_id=group_id, user_id=user_id, added_by=access.user.id
        )
        db.add(membership)
    elif membership.role == Role.ADMIN and body.role != Role.ADMIN:
        _keep_an_admin(db, group_id, user_id)
    membership.role = body.role
    db.commit()
    return list_members(group_id, db, access)


@router.delete("/api/groups/{group_id}/members/{user_id}")
def remove_member(
    group_id: uuid.UUID, user_id: uuid.UUID, db: DB, access: CurrentAccess
) -> list[MemberOut]:
    """Remove someone's membership here (inherited ones stay)."""
    _managed_group(db, access, group_id)
    membership = db.get(Membership, (group_id, user_id))
    if membership is None:
        raise HTTPException(404, "not a direct member of this group")
    if membership.role == Role.ADMIN:
        _keep_an_admin(db, group_id, user_id)
    db.delete(membership)
    db.commit()
    return list_members(group_id, db, access)


@router.post("/api/groups/{group_id}/leave", status_code=204)
def leave_group(group_id: uuid.UUID, db: DB, access: CurrentAccess) -> Response:
    """Leave a group one was added to. Membership through a group above can
    only be left there."""
    group = _visible_group(db, access, group_id)
    membership = db.get(Membership, (group_id, access.user.id))
    if membership is None:
        above = next(
            (
                g
                for g in _ancestors(db, group)
                if db.get(Membership, (g.id, access.user.id))
            ),
            None,
        )
        where = f"through {above.name}; leave that group" if above else "not directly"
        raise HTTPException(409, f"you are in this group {where} instead")
    if membership.role == Role.ADMIN:
        _keep_an_admin(db, group_id, access.user.id)
    db.delete(membership)
    db.commit()
    return Response(status_code=204)


def _keep_an_admin(db: DB, group_id: uuid.UUID, leaving: uuid.UUID) -> None:
    """A top-level group must keep an admin of its own."""
    group = db.get(Group, group_id)
    if group is None or group.parent_id is not None:
        return
    others = db.scalar(
        select(func.count()).where(
            Membership.group_id == group_id,
            Membership.role == Role.ADMIN,
            Membership.user_id != leaving,
        )
    )
    if not others:
        raise HTTPException(409, "the group needs another admin first")


@router.get("/api/users")
def find_users(
    db: DB,
    access: CurrentAccess,
    q: Annotated[str, Query(max_length=64)] = "",
) -> list[UserBrief]:
    """People to add to a group, by username; for site administrators and
    group admins."""
    if not (access.site_admin or Role.ADMIN in access.roles.values()):
        raise HTTPException(403, "only admins look up people")
    query = select(User).order_by(func.lower(User.username)).limit(20)
    if q.strip():
        query = query.where(User.username.icontains(q.strip(), autoescape=True))
    return [UserBrief(id=user.id, username=user.username) for user in db.scalars(query)]
