from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from articles.middleware import _SKIP_EXACT, _SKIP_PREFIXES
from articles.models import VisitorLog

_NOISE_UA_TERMS = (
    'bot', 'crawler', 'spider', 'slurp', 'bingpreview', 'facebookexternalhit',
    'headless', 'scrapy', 'curl', 'wget', 'python-urllib', 'python-requests',
    'httpx', 'go-http-client', 'uptime', 'sentry', 'leblibrary-audit',
)


class Command(BaseCommand):
    help = 'Safely prune bot, uptime-monitor, and technical-path noise from VisitorLog.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Show how many rows would be removed without deleting anything.',
        )
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='Also prune any remaining VisitorLog rows older than N days.',
        )
        parser.add_argument(
            '--batch-size',
            type=int,
            default=5000,
            help='Number of rows to delete per batch (default: 5000).',
        )
        parser.add_argument(
            '--vacuum',
            action='store_true',
            help='Run SQLite WAL checkpoint and VACUUM after pruning to reclaim disk space.',
        )

    def handle(self, *args, **options):
        noise_q = Q(user_agent='') | Q(ip_address__in=('127.0.0.1', '::1')) | Q(path__in=_SKIP_EXACT)
        for prefix in _SKIP_PREFIXES:
            noise_q |= Q(path__startswith=prefix)
        for term in _NOISE_UA_TERMS:
            noise_q |= Q(user_agent__icontains=term)

        days = options['days']
        if days is not None:
            cutoff = timezone.now() - timedelta(days=days)
            noise_q |= Q(timestamp__lt=cutoff)

        qs = VisitorLog.objects.filter(noise_q)
        total_before = VisitorLog.objects.count()
        to_delete = qs.count()

        if options['dry_run']:
            self.stdout.write(
                f'[DRY-RUN] VisitorLog total={total_before}, matching_noise={to_delete}, remaining={total_before - to_delete}'
            )
            return

        batch_size = max(100, options['batch_size'])
        deleted_total = 0
        while True:
            pks = list(qs.values_list('pk', flat=True)[:batch_size])
            if not pks:
                break
            deleted, _ = VisitorLog.objects.filter(pk__in=pks).delete()
            deleted_total += deleted

        total_after = VisitorLog.objects.count()
        self.stdout.write(
            self.style.SUCCESS(
                f'Pruned {deleted_total} VisitorLog rows (before={total_before}, after={total_after}).'
            )
        )

        if options['vacuum'] and connection.vendor == 'sqlite':
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA wal_checkpoint(TRUNCATE);')
                cursor.execute('VACUUM;')
            self.stdout.write(self.style.SUCCESS('Completed SQLite WAL checkpoint and VACUUM.'))
