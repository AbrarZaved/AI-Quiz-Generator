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