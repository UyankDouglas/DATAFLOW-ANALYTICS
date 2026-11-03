"""Membros, convites e configurações do workspace."""

import uuid
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.core.db import session_scope
from app.models import AuditLog, Role, WorkspaceInvitation
from app.models.base import utcnow
from tests.conftest import add_member, csrf, new_client, register


def _invite(client: TestClient, email: str, role: str = "analyst") -> Any:
    return client.post(
        "/api/v1/workspaces/current/invitations",
        json={"email": email, "role": role},
        headers=csrf(client),
    )


def _token(dispatched: list[tuple[str, list[Any]]]) -> str:
    sent = [args for name, args in dispatched if name == "email.invitation"]
    assert sent, dispatched
    return str(sent[-1][1])


def _member_id(client: TestClient, email: str) -> str:
    members = client.get("/api/v1/workspaces/current/members").json()
    return next(m["id"] for m in members if m["email"] == email)


def test_invitation_flow(client: TestClient, dispatched: list[tuple[str, list[Any]]]) -> None:
    owner = register(client, workspace="Comercial")
    response = _invite(client, "Nova.Pessoa@Example.com", "analyst")
    assert response.status_code == 202, response.text
    email, token, workspace_name, role = next(
        args for name, args in dispatched if name == "email.invitation"
    )
    assert (email, workspace_name, role) == ("nova.pessoa@example.com", "Comercial", "analyst")
    pending = client.get("/api/v1/workspaces/current/invitations").json()
    assert [(i["email"], i["role"]) for i in pending] == [("nova.pessoa@example.com", "analyst")]
    with session_scope() as db:
        stored = db.scalar(select(WorkspaceInvitation.token_hash))
    assert stored != token  # o banco guarda só o hash

    guest = new_client()
    preview = guest.post("/api/v1/invitations/preview", json={"token": token}, headers=csrf(guest))
    assert preview.json()["workspace_name"] == "Comercial"
    register(guest, email="nova.pessoa@example.com", workspace="Pessoal")
    accepted = guest.post("/api/v1/invitations/accept", json={"token": token}, headers=csrf(guest))
    assert accepted.status_code == 200, accepted.text
    me = guest.get("/api/v1/auth/me").json()
    assert me["workspace"]["id"] == owner["workspace"]["id"]  # já entra no workspace convidado
    assert me["workspace"]["role"] == "analyst"
    assert client.get("/api/v1/workspaces/current/invitations").json() == []
    again = guest.post("/api/v1/invitations/accept", json={"token": token}, headers=csrf(guest))
    assert again.status_code == 410
    assert again.json()["error"]["code"] == "invitation_used"
    with session_scope() as db:
        actions = list(
            db.scalars(
                select(AuditLog.action)
                .where(AuditLog.workspace_id == uuid.UUID(owner["workspace"]["id"]))
                .where(AuditLog.action.startswith("member."))
                .order_by(AuditLog.created_at)
            )
        )
    assert actions == ["member.invited", "member.joined"]


def test_invitation_rules(client: TestClient, dispatched: list[tuple[str, list[Any]]]) -> None:
    owner = register(client, email="dona@example.com")
    assert _invite(client, "dona@example.com").json()["error"]["code"] == "already_member"

    _invite(client, "convidada@example.com")
    first = _token(dispatched)
    _invite(client, "convidada@example.com", "viewer")  # reenviar substitui o anterior
    second = _token(dispatched)
    other = new_client()
    register(other, email="outra@example.com")
    wrong = other.post("/api/v1/invitations/accept", json={"token": second}, headers=csrf(other))
    assert wrong.status_code == 403
    assert wrong.json()["error"]["code"] == "invitation_email_mismatch"
    assert (
        other.post(
            "/api/v1/invitations/accept", json={"token": first}, headers=csrf(other)
        ).status_code
        == 404
    )
    with session_scope() as db:
        db.execute(
            update(WorkspaceInvitation)
            .where(WorkspaceInvitation.revoked_at.is_(None))
            .values(expires_at=utcnow() - timedelta(minutes=1))
        )
    expired = other.post("/api/v1/invitations/preview", json={"token": second}, headers=csrf(other))
    assert expired.json()["error"]["code"] == "invitation_expired"

    _invite(client, "cancelada@example.com")
    pending = client.get("/api/v1/workspaces/current/invitations").json()
    revoked = client.delete(
        f"/api/v1/workspaces/current/invitations/{pending[0]['id']}", headers=csrf(client)
    )
    assert revoked.status_code == 204
    assert client.get("/api/v1/workspaces/current/invitations").json() == []
    assert owner["workspace"]["id"]


def test_roles_and_the_last_admin(client: TestClient) -> None:
    owner = register(client, email="dona@example.com")
    colleague = new_client()
    member = register(colleague, email="colega@example.com", workspace="Do colega")
    add_member(owner["workspace"]["id"], member["user"]["id"], Role.VIEWER)
    colleague.post(
        "/api/v1/workspaces/switch",
        json={"workspace_id": owner["workspace"]["id"]},
        headers=csrf(colleague),
    )
    me = _member_id(client, "dona@example.com")
    them = _member_id(client, "colega@example.com")
    base = "/api/v1/workspaces/current/members"

    last = client.patch(f"{base}/{me}", json={"role": "analyst"}, headers=csrf(client))
    assert last.status_code == 409
    assert last.json()["error"]["code"] == "last_admin"
    assert client.delete(f"{base}/{me}", headers=csrf(client)).status_code == 409

    promoted = client.patch(f"{base}/{them}", json={"role": "admin"}, headers=csrf(client))
    assert promoted.status_code == 200
    assert "members:manage" in colleague.get("/api/v1/auth/me").json()["permissions"]
    assert (
        client.patch(f"{base}/{me}", json={"role": "analyst"}, headers=csrf(client)).status_code
        == 200
    )
    # Agora a dona é analista: vê os membros, mas não altera.
    assert client.get(base).status_code == 200
    assert client.delete(f"{base}/{them}", headers=csrf(client)).status_code == 403

    removed = colleague.delete(f"{base}/{me}", headers=csrf(colleague))
    assert removed.status_code == 204
    # Quem foi removido perde o acesso na hora (o pertencimento é relido a cada requisição).
    assert client.get("/api/v1/datasets").status_code == 403
    assert client.get("/api/v1/auth/me").json()["workspace"] is None


def test_viewer_and_analyst_cannot_manage(client: TestClient) -> None:
    owner = register(client)
    clients = {}
    for role in (Role.ANALYST, Role.VIEWER):
        other = new_client()
        member = register(other, workspace=f"Outro {role}")
        add_member(owner["workspace"]["id"], member["user"]["id"], role)
        other.post(
            "/api/v1/workspaces/switch",
            json={"workspace_id": owner["workspace"]["id"]},
            headers=csrf(other),
        )
        clients[role] = other
    analyst, viewer = clients[Role.ANALYST], clients[Role.VIEWER]
    assert analyst.get("/api/v1/workspaces/current/members").status_code == 200
    assert viewer.get("/api/v1/workspaces/current/members").status_code == 403
    for actor in (analyst, viewer):
        assert _invite(actor, "x@example.com").status_code == 403
        assert actor.get("/api/v1/workspaces/current/invitations").status_code == 403
        assert (
            actor.patch(
                "/api/v1/workspaces/current", json={"name": "Novo"}, headers=csrf(actor)
            ).status_code
            == 403
        )


def test_workspace_settings(client: TestClient) -> None:
    owner = register(client, workspace="Comercial")
    current = client.get("/api/v1/workspaces/current/settings").json()
    assert current["settings"] == {
        "export_ttl_hours": 24,
        "viewer_exports": False,
        "original_retention_days": None,
    }
    updated = client.patch(
        "/api/v1/workspaces/current",
        json={
            "name": "Comercial Sul",
            "settings": {"export_ttl_hours": 48, "original_retention_days": 30},
        },
        headers=csrf(client),
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Comercial Sul"
    assert updated.json()["settings"]["export_ttl_hours"] == 48
    for invalid in (
        {"export_ttl_hours": 0},
        {"original_retention_days": 3},
        {"export_ttl_hours": 500},
    ):
        response = client.patch(
            "/api/v1/workspaces/current", json={"settings": invalid}, headers=csrf(client)
        )
        assert response.status_code == 422, invalid
    with session_scope() as db:
        details = db.scalar(
            select(AuditLog.details).where(
                AuditLog.action == "workspace.updated",
                AuditLog.workspace_id == uuid.UUID(owner["workspace"]["id"]),
            )
        )
    assert details == {
        "changed": {
            "name": True,
            "export_ttl_hours": {"from": 24, "to": 48},
            "original_retention_days": {"from": None, "to": 30},
        }
    }
