from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import AuthSession, client_ip, get_auth_session, get_db
from app.core.config import get_settings
from app.core.security import csrf_token_for_session, hash_token, new_anonymous_csrf_token
from app.models import UserSession
from app.models.base import utcnow
from app.schemas.auth import (
    CsrfResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RegisterRequest,
    ResetPasswordRequest,
)
from app.schemas.common import Message
from app.services import auth_service
from app.tasks.dispatch import enqueue_password_reset_email

router = APIRouter(prefix="/auth", tags=["auth"])


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    settings = get_settings()
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    _set_csrf_cookie(response, csrf_token, max_age)


def _set_csrf_cookie(response: Response, csrf_token: str, max_age: int | None = None) -> None:
    settings = get_settings()
    # Legível pelo frontend (double-submit); a sessão em si continua HttpOnly.
    response.set_cookie(
        settings.csrf_cookie_name,
        csrf_token,
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


def _clear_cookies(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")


@router.get("/csrf", response_model=CsrfResponse, summary="Obtém token CSRF")
def get_csrf(request: Request, response: Response, db: Session = Depends(get_db)) -> CsrfResponse:
    settings = get_settings()
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        token_hash = hash_token(token)
        session = db.query(UserSession).filter(UserSession.token_hash == token_hash).first()
        if session and session.revoked_at is None and session.expires_at > utcnow():
            csrf = csrf_token_for_session(token_hash)
            _set_csrf_cookie(response, csrf, settings.session_ttl_hours * 3600)
            return CsrfResponse(csrf_token=csrf)
        response.delete_cookie(settings.session_cookie_name, path="/")
    csrf = new_anonymous_csrf_token()
    _set_csrf_cookie(response, csrf)
    return CsrfResponse(csrf_token=csrf)


@router.post("/register", response_model=MeResponse, status_code=status.HTTP_201_CREATED)
def register(
    data: RegisterRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> MeResponse:
    user, issued = auth_service.register(
        db, data, ip=client_ip(request), user_agent=request.headers.get("user-agent")
    )
    _set_session_cookies(response, issued.token, issued.csrf_token)
    return auth_service.build_me(db, user, issued.session)


@router.post("/login", response_model=MeResponse)
def login(
    data: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> MeResponse:
    user, issued = auth_service.login(
        db,
        data.email,
        data.password,
        ip=client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    _set_session_cookies(response, issued.token, issued.csrf_token)
    return auth_service.build_me(db, user, issued.session)


@router.post("/logout", response_model=Message)
def logout(
    request: Request,
    response: Response,
    auth: AuthSession = Depends(get_auth_session),
    db: Session = Depends(get_db),
) -> Message:
    auth_service.logout(db, auth.session, ip=client_ip(request))
    _clear_cookies(response)
    return Message(message="Sessão encerrada.")


@router.get("/me", response_model=MeResponse)
def me(auth: AuthSession = Depends(get_auth_session), db: Session = Depends(get_db)) -> MeResponse:
    return auth_service.build_me(db, auth.user, auth.session)


@router.post("/password/forgot", response_model=Message, status_code=status.HTTP_202_ACCEPTED)
def forgot_password(
    data: ForgotPasswordRequest, request: Request, db: Session = Depends(get_db)
) -> Message:
    token = auth_service.request_password_reset(db, data.email, ip=client_ip(request))
    if token is not None:
        enqueue_password_reset_email(auth_service.normalize_email(data.email), token)
    # Resposta idêntica exista ou não a conta (evita enumeração de usuários).
    return Message(message="Se o e-mail estiver cadastrado, enviaremos um link de redefinição.")


@router.post("/password/reset", response_model=Message)
def reset_password(
    data: ResetPasswordRequest, request: Request, db: Session = Depends(get_db)
) -> Message:
    auth_service.reset_password(db, data.token, data.password, ip=client_ip(request))
    return Message(message="Senha redefinida. Entre com a nova senha.")
