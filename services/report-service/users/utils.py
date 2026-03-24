from django.core.signing import TimestampSigner, BadSignature, SignatureExpired
from django.core.mail import EmailMessage
from django.conf import settings
import logging
import json

# Use 'users' logger to match configured logger in settings.py
logger = logging.getLogger('users')


def generate_verification_token(user_id):
    """
    Generate a signed verification token for email verification.
    
    Args:
        user_id: The ID of the user to generate token for
        
    Returns:
        A signed token string
    """
    signer = TimestampSigner()
    token = signer.sign(str(user_id))
    return token


def verify_token(token, max_age=86400):
    """
    Verify a signed token and extract the user ID.
    
    Args:
        token: The signed token to verify
        max_age: Maximum age of token in seconds (default: 24 hours)
        
    Returns:
        user_id if valid, None otherwise
    """
    signer = TimestampSigner()
    try:
        user_id = signer.unsign(token, max_age=max_age)
        return int(user_id)
    except (BadSignature, SignatureExpired):
        return None


def verify_email_token(token, max_age=86400):
    """
    Verify email verification token and return detailed result.
    
    Args:
        token: The signed token to verify
        max_age: Maximum age of token in seconds (default: 24 hours)
        
    Returns:
        tuple: (success: bool, user_id: int or None, error_type: str or None)
        error_type can be: 'expired', 'invalid', or None
    """
    signer = TimestampSigner()
    try:
        user_id = signer.unsign(token, max_age=max_age)
        return (True, int(user_id), None)
    except SignatureExpired:
        return (False, None, 'expired')
    except BadSignature:
        return (False, None, 'invalid')


def send_verification_email(user_email, user_name, token):
    """
    Send verification email to the user.
    
    Args:
        user_email: Email address of the user
        user_name: Name of the user
        token: Verification token
        
    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        verification_url = f"{settings.FRONTEND_URL}/verify-email?token={token}"
        
        subject = "Verify Your BI Voice Agent Account"
        
        # Plain text version
        text_content = f"""
Hello {user_name},

Thank you for signing up for BI Voice Agent!

Please verify your email address by clicking the link below:

{verification_url}

This link will expire in 24 hours.

If you didn't create an account, please ignore this email.

Best regards,
BI Voice Agent Team
"""
        
        # HTML version with better styling
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
            border-radius: 10px 10px 0 0;
        }}
        .content {{
            background: white;
            padding: 30px;
            border: 1px solid #e0e0e0;
            border-top: none;
        }}
        .button {{
            display: inline-block;
            background-color: #4CAF50;
            color: white;
            padding: 14px 30px;
            text-align: center;
            text-decoration: none;
            border-radius: 5px;
            margin: 20px 0;
            font-weight: bold;
        }}
        .footer {{
            text-align: center;
            color: #777;
            font-size: 12px;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Welcome to BI Voice Agent!</h1>
        </div>
        <div class="content">
            <h2>Hello {user_name},</h2>
            <p>Thank you for signing up for BI Voice Agent!</p>
            <p>Please verify your email address by clicking the button below:</p>
            <p style="text-align: center;">
                <a href="{verification_url}" class="button">Verify My Account</a>
            </p>
            <p><em>This link will expire in 24 hours.</em></p>
            <p>If you didn't create an account, please ignore this email.</p>
            <div class="footer">
                <p>Best regards,<br><strong>BI Voice Agent Team</strong></p>
            </div>
        </div>
    </div>
</body>
</html>
"""
        
        # Create email message with display name
        email = EmailMessage(
            subject=subject,
            body=html_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user_email],
            reply_to=['no-reply@bivoiceagent.com']
        )
        email.content_subtype = 'html'
        email.send(fail_silently=False)
        
        logger.info(f"Verification email sent to {user_email}")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send verification email to {user_email}: {str(e)}")
        return False


def generate_invitation_token():
    """
    Generate a simple unique token for workspace invitation.
    
    This token is stored in the Invitation model and used to accept invitations.
    Different from email verification tokens.
    
    Returns:
        Unique token string (UUID-based)
    """
    import uuid
    import secrets
    # Generate a secure random token
    # Using UUID + secrets for extra uniqueness
    return f"{uuid.uuid4().hex}{secrets.token_urlsafe(16)}"


def send_invitation_email(invited_email, inviter_name, workspace_name, token, role='member'):
    """
    Send workspace invitation email to the invited user.
    
    Args:
        invited_email: Email of the invited user
        inviter_name: Name of the manager who sent the invitation
        workspace_name: Name of the workspace
        token: Invitation token (UUID string)
        role: Role they will join as (analyst/executive)
    
    Returns:
        Boolean indicating success or failure
    """
    try:
        # Validate inputs
        if not invited_email or not inviter_name or not workspace_name or not token:
            logger.error(f"Missing required parameters for invitation email: email={invited_email}, inviter={inviter_name}, workspace={workspace_name}, token={'present' if token else 'missing'}")
            return False
        
        # Simple token - no URL encoding needed (it's just a UUID string)
        invitation_url = f"{settings.FRONTEND_URL}/accept-invite?token={token}"
        
        logger.info(f"Preparing invitation email to {invited_email} for workspace {workspace_name} as {role}")
        
        subject = f"BI Voice Agent – Workspace Invitation"
        
        # Plain text version
        text_content = f"""
Hello,

You have been invited to join workspace "{workspace_name}" as {role.title()}.

Invited by: {inviter_name}
Your role: {role.title()}

Click the link below to join:
{invitation_url}

This invitation will expire in 48 hours.

If you did not expect this invitation, you can safely ignore this email.

Best regards,
BI Voice Agent Team
"""
        
        # HTML version with better styling
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{
            font-family: Arial, sans-serif;
            line-height: 1.6;
            color: #333;
        }}
        .container {{
            max-width: 600px;
            margin: 0 auto;
            padding: 20px;
        }}
        .header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
            border-radius: 10px 10px 0 0;
        }}
        .content {{
            background: white;
            padding: 30px;
            border: 1px solid #e0e0e0;
            border-top: none;
        }}
        .button {{
            display: inline-block;
            background-color: #2196F3;
            color: white;
            padding: 14px 30px;
            text-align: center;
            text-decoration: none;
            border-radius: 5px;
            margin: 20px 0;
            font-weight: bold;
        }}
        .info-box {{
            background: #f5f5f5;
            padding: 15px;
            border-left: 4px solid #2196F3;
            margin: 20px 0;
        }}
        .footer {{
            text-align: center;
            color: #777;
            font-size: 12px;
            margin-top: 20px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🎉 Workspace Invitation</h1>
        </div>
        <div class="content">
            <h2>Hello,</h2>
            <p>You have been invited to join workspace <strong>"{workspace_name}"</strong> as <strong>{role.title()}</strong>.</p>
            
            <div class="info-box">
                <p><strong>Invitation Details:</strong></p>
                <ul>
                    <li><strong>Invited by:</strong> {inviter_name}</li>
                    <li><strong>Workspace:</strong> {workspace_name}</li>
                    <li><strong>Your role:</strong> {role.title()}</li>
                </ul>
            </div>
            
            <p>Click the button below to join:</p>
            <p style="text-align: center;">
                <a href="{invitation_url}" class="button">Join Workspace</a>
            </p>
            <p><em>This invitation will expire in 48 hours.</em></p>
            <p>If you did not expect this invitation, you can safely ignore this email.</p>
            <div class="footer">
                <p>Best regards,<br><strong>BI Voice Agent Team</strong></p>
            </div>
        </div>
    </div>
</body>
</html>
"""
        
        # Validate email settings
        if not hasattr(settings, 'DEFAULT_FROM_EMAIL') or not settings.DEFAULT_FROM_EMAIL:
            logger.error("DEFAULT_FROM_EMAIL is not configured in settings")
            return False
        
        if not hasattr(settings, 'FRONTEND_URL') or not settings.FRONTEND_URL:
            logger.error("FRONTEND_URL is not configured in settings")
            return False
        
        # Create email message with display name
        email = EmailMessage(
            subject=subject,
            body=html_content,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[invited_email],
            reply_to=['no-reply@bivoiceagent.com']
        )
        email.content_subtype = 'html'
        
        # Send email with explicit error handling
        logger.info(f"Attempting to send invitation email to {invited_email} via SMTP")
        email.send(fail_silently=False)
        
        logger.info(f"Invitation email sent successfully to {invited_email} for workspace {workspace_name} as {role}")
        return True
        
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        logger.error(f"Failed to send invitation email to {invited_email}: {str(e)}")
        logger.error(f"Error traceback: {error_details}")
        return False
