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
