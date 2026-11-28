import ipaddress
import logging
import re
from .models import VisitorLog

logger = logging.getLogger(__name__)

_SKIP_PREFIXES = (
    '/static/',
    '/media/',
    '/api/',
    '/.well-known/',
)
_SKIP_EXACT = {
    '/favicon.ico',
    '/robots.txt',
    '/sitemap.xml',
    '/sw.js',
    '/service-worker.js',
    '/manifest.json',
    '/humans.txt',
    '/llms.txt',
    '/llms-full.txt',
    '/openapi.json',
}
_SKIP_IPS = {'127.0.0.1', '::1'}
_BOT_UA_RE = re.compile(
    r'(?:bot|crawler|spider|slurp|bingpreview|facebookexternalhit|headless|scrapy|'
    r'curl|wget|python-urllib|python-requests|httpx|go-http-client|uptime|sentry|'
    r'gptbot|claudebot|perplexitybot|leblibrary-audit)',
    re.IGNORECASE,
)


def _extract_valid_client_ip(request):
    candidates = []
    real_ip = (request.META.get('HTTP_X_REAL_IP') or '').strip()
    if real_ip:
        candidates.append(real_ip)
    xff = (request.META.get('HTTP_X_FORWARDED_FOR') or '').strip()
    if xff:
        parts = [p.strip() for p in xff.split(',') if p.strip()]
        if parts:
            candidates.append(parts[-1])
    remote = (request.META.get('REMOTE_ADDR') or '').strip()
    if remote:
        candidates.append(remote)
    for raw_ip in candidates:
        try:
            return str(ipaddress.ip_address(raw_ip))
        except ValueError:
            continue
    return None


class VisitorTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        path = request.path or ''
        user_agent = (request.META.get('HTTP_USER_AGENT') or '').strip()[:500]
        ip = _extract_valid_client_ip(request)
        should_log = (
            bool(user_agent)
            and ip not in _SKIP_IPS
            and path not in _SKIP_EXACT
            and not path.startswith(_SKIP_PREFIXES)
            and not _BOT_UA_RE.search(user_agent)
        )
        if should_log:
            try:
                user = request.user if (hasattr(request, 'user') and request.user.is_authenticated) else None
                VisitorLog.objects.create(
                    ip_address=ip,
                    path=path[:500],
                    user=user,
                    user_agent=user_agent,
                )
            except Exception:
                logger.warning('Failed recording VisitorLog for path %s', path[:120], exc_info=True)

        return self.get_response(request)
