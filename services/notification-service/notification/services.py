import hashlib
import hmac
import json
import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from .email_templates import (
    build_activation_email,
    build_invitation_email,
    build_password_reset_code_email,
    build_report_created_email,
    build_subscription_activated_email,
    build_subscription_expiry_warning_email,
    build_workspace_member_joined_email,
)
from .models import (
    NotificationDispatchLog,
    SubscriptionRecord,
    WorkspaceMemberRecord,
    WorkspaceRecord,
)

logger = logging.getLogger(__name__)

EVENT_ACCOUNT_ACTIVATION = 'account_activation'
EVENT_WORKSPACE_INVITATION = 'workspace_invitation'
EVENT_WORKSPACE_MEMBER_JOINED = 'workspace_member_joined'
EVENT_WORKSPACE_REPORT_CREATED = 'workspace_report_created'
EVENT_SUBSCRIPTION_ACTIVATED = 'subscription_activated'
EVENT_SUBSCRIPTION_EXPIRY_WARNING = 'subscription_expiry_warning'
EVENT_PASSWORD_RESET_CODE = 'password_reset_code'


def _merge_counts(base_counts, next_counts):
    return {
        'sent': base_counts.get('sent', 0) + next_counts.get('sent', 0),
        'failed': base_counts.get('failed', 0) + next_counts.get('failed', 0),
        'skipped': base_counts.get('skipped', 0) + next_counts.get('skipped', 0),
    }


def _normalize_email(value):
    return (value or '').strip().lower()


def _normalize_name(value):
    return (value or '').strip() or 'there'


def _extract_payload_recipients(payload):
    recipients = []
    seen = set()
    payload = payload or {}

    def _add(email, name):
        normalized = _normalize_email(email)
        if not normalized or normalized in seen:
            return
        seen.add(normalized)
        recipients.append((normalized, _normalize_name(name)))

    for entry in payload.get('recipient_emails') or []:
        _add(entry, payload.get('owner_name'))

    for entry in payload.get('recipients') or []:
        if isinstance(entry, dict):
            _add(entry.get('email'), entry.get('name'))
        elif isinstance(entry, str):
            _add(entry, payload.get('owner_name'))

    _add(payload.get('owner_email'), payload.get('owner_name'))
    _add(payload.get('recipient_email'), payload.get('recipient_name'))
    return recipients


def _get_workspace_record(workspace_id):
    if not workspace_id:
        return None
    try:
        return WorkspaceRecord.objects.select_related('owner').filter(id=workspace_id).first()
    except Exception as exc:
        logger.warning("Workspace lookup failed workspace_id=%s error=%s", workspace_id, exc)
        return None


def _resolve_event_key(event_type, event_key, payload):
    key = (event_key or '').strip()
    if key:
        return key
    payload_json = json.dumps(payload or {}, sort_keys=True, default=str)
    payload_hash = hashlib.sha256(payload_json.encode('utf-8')).hexdigest()[:24]
    return f"{event_type}:{payload_hash}"


def _dispatch_email(*, event_type, event_key, recipient_email, subject, text_content, html_content, payload):
    normalized_email = _normalize_email(recipient_email)
    if not normalized_email:
        return {'sent': 0, 'failed': 1, 'skipped': 0}

    resolved_event_key = _resolve_event_key(event_type, event_key, payload)
    dispatch_log, created = NotificationDispatchLog.objects.get_or_create(
        event_type=event_type,
        event_key=resolved_event_key,
        recipient_email=normalized_email,
        defaults={
            'status': NotificationDispatchLog.STATUS_PENDING,
            'payload': payload or {},
        },
    )
    if not created:
        return {'sent': 0, 'failed': 0, 'skipped': 1}

    try:
        message = EmailMultiAlternatives(
            subject=subject,
            body=text_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[normalized_email],
            reply_to=['no-reply@bivoiceagent.com'],
        )
        message.attach_alternative(html_content, 'text/html')
        message.send(fail_silently=False)

        dispatch_log.status = NotificationDispatchLog.STATUS_SENT
        dispatch_log.sent_at = timezone.now()
        dispatch_log.error_message = ''
        dispatch_log.save(update_fields=['status', 'sent_at', 'error_message'])
        logger.info(
            "Notification email sent event_type=%s key=%s email=%s",
            event_type,
            resolved_event_key,
            normalized_email,
        )
        return {'sent': 1, 'failed': 0, 'skipped': 0}
    except Exception as exc:
        dispatch_log.status = NotificationDispatchLog.STATUS_FAILED
        dispatch_log.error_message = str(exc)
        dispatch_log.save(update_fields=['status', 'error_message'])
        logger.error(
            "Notification email failed event_type=%s key=%s email=%s error=%s",
            event_type,
            resolved_event_key,
            normalized_email,
            exc,
        )
        return {'sent': 0, 'failed': 1, 'skipped': 0}


def _collect_workspace_recipients(*, workspace_id, include_manager=True, roles=None, require_verified=True):
    recipients = []
    seen_emails = set()
    workspace = _get_workspace_record(workspace_id)

    def _add(email, display_name):
        normalized = _normalize_email(email)
        if not normalized or normalized in seen_emails:
            return
        seen_emails.add(normalized)
        recipients.append((normalized, display_name or 'there'))

    if include_manager and workspace and workspace.owner and workspace.owner.is_active:
        if (not require_verified) or workspace.owner.is_verified:
            _add(workspace.owner.email, workspace.owner.name)

    try:
        members = WorkspaceMemberRecord.objects.select_related('user').filter(
            workspace_id=workspace_id,
            status='active',
            user__isnull=False,
        )
        if roles:
            members = members.filter(role__in=list(roles))

        for member in members:
            user = member.user
            if not user or not user.is_active:
                continue
            if require_verified and not user.is_verified:
                continue
            _add(user.email, user.name)
    except Exception as exc:
        logger.warning("Workspace members lookup failed workspace_id=%s error=%s", workspace_id, exc)

    return recipients


def _handle_account_activation(*, payload, event_key):
    email = payload.get('email')
    token = payload.get('token')
    user_name = payload.get('user_name') or payload.get('name') or 'there'
    if not email or not token:
        raise ValueError('account_activation event requires email and token')

    subject, text, html = build_activation_email(user_name=user_name, token=token)
    return _dispatch_email(
        event_type=EVENT_ACCOUNT_ACTIVATION,
        event_key=event_key,
        recipient_email=email,
        subject=subject,
        text_content=text,
        html_content=html,
        payload=payload,
    )


def _handle_workspace_invitation(*, payload, event_key):
    invited_email = payload.get('invited_email')
    token = payload.get('token')
    inviter_name = payload.get('inviter_name') or 'Workspace Manager'
    workspace_name = payload.get('workspace_name') or 'Workspace'
    role = payload.get('role') or 'member'
    if not invited_email or not token:
        raise ValueError('workspace_invitation event requires invited_email and token')

    subject, text, html = build_invitation_email(
        inviter_name=inviter_name,
        invited_role=role,
        workspace_name=workspace_name,
        token=token,
    )
    return _dispatch_email(
        event_type=EVENT_WORKSPACE_INVITATION,
        event_key=event_key,
        recipient_email=invited_email,
        subject=subject,
        text_content=text,
        html_content=html,
        payload=payload,
    )


def _handle_workspace_member_joined(*, payload, event_key):
    workspace_id = payload.get('workspace_id')
    joined_name = payload.get('joined_user_name') or 'A new member'
    joined_email = payload.get('joined_user_email') or 'unknown@unknown'
    joined_role = payload.get('joined_role') or 'member'
    payload_recipients = _extract_payload_recipients(payload)
    if not workspace_id and not payload_recipients:
        raise ValueError('workspace_member_joined event requires workspace_id or recipient_emails')

    workspace = _get_workspace_record(workspace_id)
    workspace_name = payload.get('workspace_name') or (
        workspace.name if workspace else (f'Workspace #{workspace_id}' if workspace_id else 'Workspace')
    )

    recipients = []
    seen_emails = set()

    def _append(recipient_items):
        for recipient_email, recipient_name in recipient_items:
            normalized_email = _normalize_email(recipient_email)
            if not normalized_email or normalized_email in seen_emails:
                continue
            seen_emails.add(normalized_email)
            recipients.append((normalized_email, _normalize_name(recipient_name)))

    _append(payload_recipients)
    if workspace_id:
        _append(
            _collect_workspace_recipients(
                workspace_id=workspace_id,
                include_manager=True,
                roles=('analyst', 'executive'),
            )
        )

    if not recipients:
        logger.warning(
            'workspace_member_joined has no resolved recipients workspace_id=%s payload=%s',
            workspace_id,
            payload,
        )
        return {'sent': 0, 'failed': 1, 'skipped': 0}

    counts = {'sent': 0, 'failed': 0, 'skipped': 0}
    for recipient_email, recipient_name in recipients:
        subject, text, html = build_workspace_member_joined_email(
            recipient_name=recipient_name,
            workspace_name=workspace_name,
            joined_name=joined_name,
            joined_email=joined_email,
            joined_role=joined_role,
        )
        counts = _merge_counts(
            counts,
            _dispatch_email(
                event_type=EVENT_WORKSPACE_MEMBER_JOINED,
                event_key=event_key,
                recipient_email=recipient_email,
                subject=subject,
                text_content=text,
                html_content=html,
                payload=payload,
            ),
        )
    return counts


def _handle_workspace_report_created(*, payload, event_key):
    workspace_id = payload.get('workspace_id')
    report_id = payload.get('report_id')
    created_by_name = payload.get('created_by_name') or 'Manager'
    payload_recipients = _extract_payload_recipients(payload)
    if not workspace_id or not report_id:
        raise ValueError('workspace_report_created event requires workspace_id and report_id')

    workspace = _get_workspace_record(workspace_id)
    workspace_name = payload.get('workspace_name') or (
        workspace.name if workspace else f'Workspace #{workspace_id}'
    )

    recipients = []
    seen_emails = set()

    def _append(recipient_items):
        for recipient_email, recipient_name in recipient_items:
            normalized_email = _normalize_email(recipient_email)
            if not normalized_email or normalized_email in seen_emails:
                continue
            seen_emails.add(normalized_email)
            recipients.append((normalized_email, _normalize_name(recipient_name)))

    _append(payload_recipients)
    _append(
        _collect_workspace_recipients(
            workspace_id=workspace_id,
            include_manager=False,
            roles=('analyst', 'executive'),
        )
    )

    if not recipients:
        logger.warning(
            'workspace_report_created has no resolved recipients workspace_id=%s report_id=%s payload=%s',
            workspace_id,
            report_id,
            payload,
        )
        return {'sent': 0, 'failed': 1, 'skipped': 0}

    counts = {'sent': 0, 'failed': 0, 'skipped': 0}
    for recipient_email, recipient_name in recipients:
        subject, text, html = build_report_created_email(
            recipient_name=recipient_name,
            workspace_name=workspace_name,
            report_id=report_id,
            created_by_name=created_by_name,
        )
        counts = _merge_counts(
            counts,
            _dispatch_email(
                event_type=EVENT_WORKSPACE_REPORT_CREATED,
                event_key=event_key,
                recipient_email=recipient_email,
                subject=subject,
                text_content=text,
                html_content=html,
                payload=payload,
            ),
        )
    return counts


def _handle_subscription_activated(*, payload, event_key):
    workspace_id = payload.get('workspace_id')
    plan_name = payload.get('plan_name') or 'Plan'
    duration_days = payload.get('duration_days') or ''
    start_date = payload.get('start_date') or ''
    end_date = payload.get('end_date') or ''
    if not workspace_id:
        raise ValueError('subscription_activated event requires workspace_id')

    workspace = _get_workspace_record(workspace_id)
    owner_email = _normalize_email(payload.get('owner_email') or payload.get('recipient_email'))
    owner_name = payload.get('owner_name') or payload.get('recipient_name') or 'Manager'
    workspace_name = payload.get('workspace_name')

    if not owner_email and workspace and workspace.owner:
        owner_email = _normalize_email(workspace.owner.email)
        owner_name = workspace.owner.name or owner_name
    if not workspace_name:
        workspace_name = workspace.name if workspace else f'Workspace #{workspace_id}'

    if not owner_email:
        logger.warning(
            'subscription_activated has no owner email workspace_id=%s payload=%s',
            workspace_id,
            payload,
        )
        return {'sent': 0, 'failed': 1, 'skipped': 0}

    subject, text, html = build_subscription_activated_email(
        recipient_name=owner_name,
        workspace_name=workspace_name,
        plan_name=plan_name,
        duration_days=duration_days,
        start_date=start_date,
        end_date=end_date,
    )
    return _dispatch_email(
        event_type=EVENT_SUBSCRIPTION_ACTIVATED,
        event_key=event_key,
        recipient_email=owner_email,
        subject=subject,
        text_content=text,
        html_content=html,
        payload=payload,
    )


def _handle_subscription_expiry_warning(*, payload, event_key):
    workspace_id = payload.get('workspace_id')
    plan_name = payload.get('plan_name') or 'Current Plan'
    end_date = payload.get('end_date') or ''
    days_left = payload.get('days_left')
    if not workspace_id:
        raise ValueError('subscription_expiry_warning event requires workspace_id')

    workspace = _get_workspace_record(workspace_id)
    owner_email = _normalize_email(payload.get('owner_email') or payload.get('recipient_email'))
    owner_name = payload.get('owner_name') or payload.get('recipient_name') or 'Manager'
    workspace_name = payload.get('workspace_name')

    if not owner_email and workspace and workspace.owner:
        owner_email = _normalize_email(workspace.owner.email)
        owner_name = workspace.owner.name or owner_name
    if not workspace_name:
        workspace_name = workspace.name if workspace else f'Workspace #{workspace_id}'

    if not owner_email:
        logger.warning(
            'subscription_expiry_warning has no owner email workspace_id=%s payload=%s',
            workspace_id,
            payload,
        )
        return {'sent': 0, 'failed': 1, 'skipped': 0}

    subject, text, html = build_subscription_expiry_warning_email(
        recipient_name=owner_name,
        workspace_name=workspace_name,
        plan_name=plan_name,
        end_date=end_date,
        days_left=days_left,
    )
    return _dispatch_email(
        event_type=EVENT_SUBSCRIPTION_EXPIRY_WARNING,
        event_key=event_key,
        recipient_email=owner_email,
        subject=subject,
        text_content=text,
        html_content=html,
        payload=payload,
    )


def _handle_password_reset_code(*, payload, event_key):
    email = payload.get('email')
    code = payload.get('code')
    user_name = payload.get('user_name') or 'there'
    expires_minutes = payload.get('expires_minutes') or 15
    if not email or not code:
        raise ValueError('password_reset_code event requires email and code')

    subject, text, html = build_password_reset_code_email(
        user_name=user_name,
        code=code,
        expires_minutes=expires_minutes,
    )
    return _dispatch_email(
        event_type=EVENT_PASSWORD_RESET_CODE,
        event_key=event_key,
        recipient_email=email,
        subject=subject,
        text_content=text,
        html_content=html,
        payload=payload,
    )


EVENT_HANDLERS = {
    EVENT_ACCOUNT_ACTIVATION: _handle_account_activation,
    EVENT_WORKSPACE_INVITATION: _handle_workspace_invitation,
    EVENT_WORKSPACE_MEMBER_JOINED: _handle_workspace_member_joined,
    EVENT_WORKSPACE_REPORT_CREATED: _handle_workspace_report_created,
    EVENT_SUBSCRIPTION_ACTIVATED: _handle_subscription_activated,
    EVENT_SUBSCRIPTION_EXPIRY_WARNING: _handle_subscription_expiry_warning,
    EVENT_PASSWORD_RESET_CODE: _handle_password_reset_code,
}


def process_event(*, event_type, payload, event_key=''):
    handler = EVENT_HANDLERS.get(event_type)
    if handler is None:
        raise ValueError(f'Unsupported event_type: {event_type}')
    return handler(payload=payload or {}, event_key=event_key or '')


def parse_expiry_warning_days(value=None):
    raw_value = value if value is not None else getattr(settings, 'SUBSCRIPTION_EXPIRY_WARNING_DAYS', '7,3,1')
    days = set()
    for token in str(raw_value).split(','):
        token = token.strip()
        if not token:
            continue
        try:
            parsed = int(token)
            if parsed >= 0:
                days.add(parsed)
        except ValueError:
            logger.warning("Invalid SUBSCRIPTION_EXPIRY_WARNING_DAYS token ignored: %s", token)
    return sorted(days)


def dispatch_subscription_expiry_warnings():
    warning_days = parse_expiry_warning_days()
    if not warning_days:
        return {'sent': 0, 'failed': 0, 'skipped': 0, 'matched_subscriptions': 0}

    today = timezone.now().date()
    max_warning_day = max(warning_days)
    try:
        candidate_subscriptions = SubscriptionRecord.objects.select_related('plan').filter(
            is_active=True,
            end_date__isnull=False,
            end_date__gte=today,
            end_date__lte=today + timedelta(days=max_warning_day),
        )
    except Exception as exc:
        logger.error('Failed to query expiring subscriptions: %s', exc, exc_info=True)
        return {'sent': 0, 'failed': 1, 'skipped': 0, 'matched_subscriptions': 0}

    counts = {'sent': 0, 'failed': 0, 'skipped': 0}
    matched = 0
    for subscription in candidate_subscriptions:
        try:
            if not subscription.end_date:
                continue
            days_left = (subscription.end_date - today).days
            if days_left not in warning_days:
                continue
            matched += 1

            workspace = _get_workspace_record(subscription.workspace_id)
            owner_email = None
            owner_name = None
            workspace_name = None
            if workspace:
                workspace_name = workspace.name
                if workspace.owner:
                    owner_email = workspace.owner.email
                    owner_name = workspace.owner.name

            payload = {
                'workspace_id': subscription.workspace_id,
                'workspace_name': workspace_name,
                'owner_email': owner_email,
                'owner_name': owner_name,
                'plan_name': getattr(subscription.plan, 'name', 'Current Plan'),
                'end_date': subscription.end_date.isoformat(),
                'days_left': days_left,
                'subscription_id': subscription.id,
            }
            counts = _merge_counts(
                counts,
                process_event(
                    event_type=EVENT_SUBSCRIPTION_EXPIRY_WARNING,
                    event_key=f"subscription-expiry:{subscription.id}:{days_left}:{subscription.end_date.isoformat()}",
                    payload=payload,
                ),
            )
        except Exception as exc:
            logger.error(
                'Failed processing subscription expiry warning subscription_id=%s error=%s',
                getattr(subscription, 'id', None),
                exc,
                exc_info=True,
            )
            counts = _merge_counts(counts, {'sent': 0, 'failed': 1, 'skipped': 0})

    return {
        **counts,
        'matched_subscriptions': matched,
    }


def is_internal_api_key_valid(request_key):
    expected = getattr(settings, 'NOTIFICATION_INTERNAL_API_KEY', '').strip()
    if not expected:
        return True
    provided = (request_key or '').strip()
    return hmac.compare_digest(expected, provided)
