from django.conf import settings


def _base_html(title, body_html):
    return f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8" />
  <style>
    body {{ font-family: Arial, sans-serif; background: #f6f8fb; margin: 0; padding: 24px; color: #1f2937; }}
    .card {{ max-width: 620px; margin: 0 auto; background: white; border: 1px solid #e5e7eb; border-radius: 10px; overflow: hidden; }}
    .header {{ padding: 20px 24px; background: #0f62fe; color: white; }}
    .content {{ padding: 24px; line-height: 1.6; }}
    .cta {{ display: inline-block; margin-top: 16px; padding: 10px 16px; background: #0f62fe; color: white; text-decoration: none; border-radius: 6px; }}
    .meta {{ margin-top: 16px; padding: 12px; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; }}
    .footer {{ font-size: 12px; color: #6b7280; padding: 16px 24px 20px; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header"><h2 style="margin:0;">{title}</h2></div>
    <div class="content">{body_html}</div>
    <div class="footer">BI Voice Agent Notifications</div>
  </div>
</body>
</html>
"""


def build_activation_email(user_name, token):
    verify_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
    subject = "Verify Your BI Voice Agent Account"
    text = (
        f"Hello {user_name},\n\n"
        "Please verify your email address to activate your account:\n"
        f"{verify_url}\n\n"
        "This link expires in 24 hours.\n\n"
        "BI Voice Agent Team"
    )
    html = _base_html(
        "Activate Your Account",
        (
            f"<p>Hello <strong>{user_name}</strong>,</p>"
            "<p>Please verify your email address to activate your BI Voice Agent account.</p>"
            f"<p><a class='cta' href='{verify_url}'>Verify My Account</a></p>"
            "<p>This link expires in 24 hours.</p>"
        ),
    )
    return subject, text, html


def build_invitation_email(inviter_name, invited_role, workspace_name, token):
    invitation_url = f"{settings.FRONTEND_URL}/accept-invite?token={token}"
    role_label = (invited_role or 'member').title()
    subject = "BI Voice Agent Workspace Invitation"
    text = (
        "Hello,\n\n"
        f"{inviter_name} invited you to join workspace \"{workspace_name}\" as {role_label}.\n"
        f"Join here: {invitation_url}\n\n"
        "This invitation expires in 48 hours.\n\n"
        "BI Voice Agent Team"
    )
    html = _base_html(
        "Workspace Invitation",
        (
            f"<p><strong>{inviter_name}</strong> invited you to join "
            f"<strong>{workspace_name}</strong> as <strong>{role_label}</strong>.</p>"
            f"<p><a class='cta' href='{invitation_url}'>Join Workspace</a></p>"
            "<p>This invitation expires in 48 hours.</p>"
        ),
    )
    return subject, text, html


def build_workspace_member_joined_email(recipient_name, workspace_name, joined_name, joined_email, joined_role):
    role_label = (joined_role or 'member').title()
    subject = f"New Member Joined {workspace_name}"
    text = (
        f"Hello {recipient_name},\n\n"
        f"{joined_name} ({joined_email}) joined your workspace \"{workspace_name}\" as {role_label}.\n\n"
        "BI Voice Agent Team"
    )
    html = _base_html(
        "New Workspace Member",
        (
            f"<p>Hello <strong>{recipient_name}</strong>,</p>"
            f"<p><strong>{joined_name}</strong> ({joined_email}) joined "
            f"<strong>{workspace_name}</strong> as <strong>{role_label}</strong>.</p>"
        ),
    )
    return subject, text, html


def build_report_created_email(recipient_name, workspace_name, report_id, created_by_name):
    subject = f"New Analytical Report Created in {workspace_name}"
    text = (
        f"Hello {recipient_name},\n\n"
        f"A new analytical report (Report #{report_id}) was created in workspace "
        f"\"{workspace_name}\" by {created_by_name}.\n\n"
        "BI Voice Agent Team"
    )
    html = _base_html(
        "New Analytical Report",
        (
            f"<p>Hello <strong>{recipient_name}</strong>,</p>"
            f"<p>A new analytical report <strong>#{report_id}</strong> was created in "
            f"<strong>{workspace_name}</strong> by <strong>{created_by_name}</strong>.</p>"
        ),
    )
    return subject, text, html


def build_subscription_activated_email(
    recipient_name,
    workspace_name,
    plan_name,
    duration_days,
    start_date,
    end_date,
):
    subject = f"Subscription Activated: {plan_name}"
    text = (
        f"Hello {recipient_name},\n\n"
        f"Your workspace \"{workspace_name}\" subscription is active.\n"
        f"Plan: {plan_name}\n"
        f"Duration: {duration_days} days\n"
        f"Start date: {start_date}\n"
        f"End date: {end_date}\n\n"
        "BI Voice Agent Team"
    )
    html = _base_html(
        "Subscription Activated",
        (
            f"<p>Hello <strong>{recipient_name}</strong>,</p>"
            f"<p>Your subscription for <strong>{workspace_name}</strong> is now active.</p>"
            "<div class='meta'>"
            f"<p><strong>Plan:</strong> {plan_name}</p>"
            f"<p><strong>Duration:</strong> {duration_days} days</p>"
            f"<p><strong>Start Date:</strong> {start_date}</p>"
            f"<p><strong>End Date:</strong> {end_date}</p>"
            "</div>"
        ),
    )
    return subject, text, html


def build_subscription_expiry_warning_email(
    recipient_name,
    workspace_name,
    plan_name,
    end_date,
    days_left,
):
    subject = f"Subscription Expiry Warning: {workspace_name}"
    text = (
        f"Hello {recipient_name},\n\n"
        f"Your {plan_name} subscription for workspace \"{workspace_name}\" expires in "
        f"{days_left} day(s) on {end_date}.\n"
        "Please renew to avoid interruption.\n\n"
        "BI Voice Agent Team"
    )
    html = _base_html(
        "Subscription Expiry Reminder",
        (
            f"<p>Hello <strong>{recipient_name}</strong>,</p>"
            f"<p>Your <strong>{plan_name}</strong> subscription for "
            f"<strong>{workspace_name}</strong> will expire in "
            f"<strong>{days_left} day(s)</strong>.</p>"
            "<div class='meta'>"
            f"<p><strong>Expiry Date:</strong> {end_date}</p>"
            "</div>"
            "<p>Please renew your subscription to avoid interruption.</p>"
        ),
    )
    return subject, text, html


def build_password_reset_code_email(user_name, code, expires_minutes):
    subject = "Your Password Reset Code"
    text = (
        f"Hello {user_name},\n\n"
        f"Use this verification code to reset your password: {code}\n\n"
        f"This code expires in {expires_minutes} minutes.\n\n"
        "If you did not request this, you can ignore this email.\n\n"
        "BI Voice Agent Team"
    )
    html = _base_html(
        "Password Reset Code",
        (
            f"<p>Hello <strong>{user_name}</strong>,</p>"
            "<p>Use the following verification code to reset your password:</p>"
            f"<div class='meta'><h3 style='margin:0; font-size:28px; letter-spacing:4px;'>{code}</h3></div>"
            f"<p>This code expires in {expires_minutes} minutes.</p>"
            "<p>If you did not request this, you can ignore this email.</p>"
        ),
    )
    return subject, text, html
