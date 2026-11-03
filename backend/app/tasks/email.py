from urllib.parse import quote

from app.services.email import send_email
from app.tasks.celery_app import celery_app, settings


@celery_app.task(
    name="email.password_reset",
    autoretry_for=(OSError,),
    retry_backoff=True,
    max_retries=5,
)
def send_password_reset(email: str, token: str) -> None:
    link = f"{settings.app_base_url}/redefinir-senha?token={quote(token)}"
    body = (
        "Olá,\n\n"
        "Recebemos uma solicitação para redefinir a senha da sua conta no DataFlow Analytics.\n"
        f"Use o link abaixo em até {settings.password_reset_ttl_minutes} minutos:\n\n"
        f"{link}\n\n"
        "Se você não fez esta solicitação, ignore este e-mail. Sua senha continua a mesma.\n"
    )
    send_email(email, "Redefinição de senha — DataFlow Analytics", body)


ROLE_LABELS = {"admin": "Administrador", "analyst": "Analista", "viewer": "Visualizador"}


@celery_app.task(
    name="email.invitation",
    autoretry_for=(OSError,),
    retry_backoff=True,
    max_retries=5,
)
def send_invitation(email: str, token: str, workspace_name: str, role: str) -> None:
    link = f"{settings.app_base_url}/convite?token={quote(token)}"
    body = (
        "Olá,\n\n"
        f"Você foi convidado para o workspace “{workspace_name}” no DataFlow Analytics, "
        f"com o perfil {ROLE_LABELS.get(role, role)}.\n\n"
        f"Para aceitar, abra o link abaixo em até {settings.invitation_ttl_days} dias e entre "
        "(ou crie sua conta) com este mesmo e-mail:\n\n"
        f"{link}\n\n"
        "Se você não esperava este convite, ignore este e-mail.\n"
    )
    send_email(email, f"Convite para {workspace_name} — DataFlow Analytics", body)
