import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from .models import OTPCode

logger = logging.getLogger(__name__)

# Maps an OTP purpose to its subject line + HTML template.
_EMAIL_CONFIG = {
    OTPCode.Purpose.EMAIL_VERIFICATION: {
        "subject": "Verify your account",
        "template": "emails/verify_account.html",
    },
    OTPCode.Purpose.PASSWORD_RESET: {
        "subject": "Your password reset code",
        "template": "emails/password_reset.html",
    },
}


@shared_task
def send_otp_email_task(user_id, otp_code, purpose):
    """Send an OTP email (verification or password reset) as HTML + plain text.

    Runs in Celery so the request thread never blocks on SMTP. Renders an
    HTML template and attaches a plain-text fallback generated from it.
    """
    User = get_user_model()
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        logger.warning("send_otp_email_task: user %s no longer exists", user_id)
        return

    config = _EMAIL_CONFIG.get(purpose, _EMAIL_CONFIG[OTPCode.Purpose.EMAIL_VERIFICATION])
    context = {
        "full_name": user.full_name,
        "otp_code": otp_code,
        "expiry_minutes": settings.OTP_EXPIRY_MINUTES,
    }

    html_body = render_to_string(config["template"], context)
    text_body = strip_tags(html_body)

    message = EmailMultiAlternatives(
        subject=config["subject"],
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
    logger.info("Sent %s email to %s", purpose, user.email)


@shared_task
def send_temp_password_email_task(user_id, temp_password):
    """Send a temporary password email as HTML + plain text."""
    User = get_user_model()
    user = User.objects.filter(pk=user_id).first()
    if user is None:
        logger.warning("send_temp_password_email_task: user %s no longer exists", user_id)
        return

    context = {
        "full_name": user.full_name,
        "temp_password": temp_password,
    }

    html_body = render_to_string("emails/temp_password.html", context)
    text_body = strip_tags(html_body)

    message = EmailMultiAlternatives(
        subject="Your Temporary Password",
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
    logger.info("Sent temporary password email to %s", user.email)


@shared_task
def send_contact_email_task(full_name, email, subject, message_content):
    """Send support/contact email to all active superadmins (superusers)."""
    User = get_user_model()
    superadmins = User.objects.filter(is_superuser=True, is_active=True)
    recipient_list = [admin.email for admin in superadmins if admin.email]

    if not recipient_list:
        logger.warning("send_contact_email_task: No active superusers found to receive contact email.")
        return

    email_subject = f"Contact Us Form Submission: {subject}"
    context = {
        "full_name": full_name,
        "email": email,
        "subject": subject,
        "message": message_content,
    }

    html_body = render_to_string("emails/contact_form.html", context)
    text_body = strip_tags(html_body)

    message = EmailMultiAlternatives(
        subject=email_subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=recipient_list,
        reply_to=[email],
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)
    logger.info("Sent contact email from %s to superadmins: %s", email, recipient_list)