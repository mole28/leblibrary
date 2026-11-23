import logging
import re
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)
_HEADER_UNSAFE_RE = re.compile(r'[\r\n]+')


def _clean_header(value: str) -> str:
    return _HEADER_UNSAFE_RE.sub(' ', str(value or '')).strip()


def send_order_confirmation(order):
    from_email = _clean_header(getattr(settings, 'DEFAULT_FROM_EMAIL', ''))
    to_addr = _clean_header(getattr(order, 'email', ''))
    if not from_email or not to_addr:
        logger.warning('Skipping order confirmation email for order %s: missing sender/recipient', getattr(order, 'id', None))
        return False

    subject = _clean_header(f"אישור הזמנה #{order.id} - ספריית לייבוביץ")
    html_content = render_to_string('articles/emails/order_confirmation.html', {'order': order})
    text_content = f"תודה רבה על הזמנתך! מספר ההזמנה שלך הוא {order.id}."

    msg = EmailMultiAlternatives(subject, text_content, from_email, [to_addr])
    msg.attach_alternative(html_content, 'text/html')
    try:
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('Failed sending order confirmation email for order %s', getattr(order, 'id', None))
        return False


def send_shipping_update(order):
    from_email = _clean_header(getattr(settings, 'DEFAULT_FROM_EMAIL', ''))
    to_addr = _clean_header(getattr(order, 'email', ''))
    if not from_email or not to_addr:
        logger.warning('Skipping shipping update email for order %s: missing sender/recipient', getattr(order, 'id', None))
        return False

    subject = _clean_header(f"ההזמנה שלך יצאה לדרך! (הזמנה #{order.id})")
    html_content = render_to_string('articles/emails/order_shipped.html', {'order': order})
    text_content = f"ההזמנה שלך נשלחה! מספר מעקב: {order.tracking_number}"

    msg = EmailMultiAlternatives(subject, text_content, from_email, [to_addr])
    msg.attach_alternative(html_content, 'text/html')
    try:
        msg.send(fail_silently=False)
        return True
    except Exception:
        logger.exception('Failed sending shipping update email for order %s', getattr(order, 'id', None))
        return False