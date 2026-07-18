"""
Auditoria reutilizável: grava no AuditLog (banco) e espelha no fluxo de logs
(Better Stack), sem dados sensíveis. Usado por auth e por ações financeiras.
"""
import logging

from .models import AuditLog

_audit_logger = logging.getLogger('apps.audit')


def get_client_ip(request) -> str:
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() or request.META.get('REMOTE_ADDR')) or ''


def log_event(request, event: str, *, user=None, detail: dict | None = None) -> None:
    """
    Registra um evento de auditoria. Nunca quebra o fluxo principal.
    `detail` deve conter apenas identificadores (ex.: debt_id) — nada sensível.
    """
    ip = get_client_ip(request)
    try:
        AuditLog.objects.create(
            user=user,
            event=event,
            ip=ip,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:256],
            detail=detail or {},
        )
    except Exception:
        pass

    try:
        _audit_logger.info(
            'audit.%s',
            event,
            extra={'audit_event': event, 'user_id': getattr(user, 'pk', None), 'ip': ip, **(detail or {})},
        )
    except Exception:
        pass
