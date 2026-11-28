import pytest
import json
import os
from django.urls import reverse
from django.test import TestCase, RequestFactory
from django.conf import settings
from articles.models import Acronym
from articles.views import search_acronyms_api

# הדקורטור הזה חובה לכל טסט שניגש למסד הנתונים או מנסה ליצור אובייקטים של ג'נגו
@pytest.mark.django_db
def test_article_list_view_loads_successfully(client):
    # 'client' הוא דפדפן וירטואלי ש-pytest מספק לנו
    url = reverse('articles:list')
    # הוספנו כאן secure=True כדי למנוע את שגיאת ההפניה (301)
    response = client.get(url, secure=True)
    
    # הבדיקה עצמה: האם השרת החזיר קוד 200 (הכל תקין)?
    assert response.status_code == 200

class AcronymSearchAPITest(TestCase):
    def setUp(self):
        Acronym.objects.create(short='רמב"ם', meaning='רבי משה בן מימון')
        Acronym.objects.create(short="רש'י", meaning='רבי שלמה יצחקי')
        self.factory = RequestFactory()

    def test_search_normalizes_quotes(self):
        test_cases = [
            ('רמב"ם', 'רמב"ם'),
            ('רמב״ם', 'רמב"ם'),
            ('רמב”ם', 'רמב"ם'),
            ("רש'י", "רש'י"),
            ("רש׳י", "רש'י"),
            ("רש`י", "רש'י"),
        ]

        for query, expected_short in test_cases:
            request = self.factory.get('/dummy/', {'q': query, 'type': 'short'})
            response = search_acronyms_api(request)
            
            self.assertEqual(response.status_code, 200)
            data = json.loads(response.content)
            
            self.assertTrue(len(data['results']) > 0, f"Search failed for: {query}")
            self.assertEqual(data['results'][0]['short'], expected_short)

class ResponsiveDesignTest(TestCase):
    def test_base_html_has_responsive_meta_and_css(self):
        base_html_path = os.path.join(settings.BASE_DIR, 'articles', 'templates', 'articles', 'base.html')
        
        # Verify the file exists
        self.assertTrue(os.path.exists(base_html_path), "base.html file not found in the expected path.")
        
        with open(base_html_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
            # 1. Check for standard viewport meta tag (crucial for mobile)
            self.assertIn('<meta name="viewport" content="width=device-width, initial-scale=1.0">', content, 
                          "Viewport meta tag is missing. Site won't scale properly on mobile.")
            
            # 2. Check for the word-break fix we added
            self.assertTrue('overflow-wrap: break-word' in content or 'word-break: break-word' in content, 
                            "Missing CSS rule to prevent long words from breaking the mobile screen layout.")
            
            # 3. Check for the image scaling fix
            self.assertIn('max-width: 100%', content, 
                          "Missing CSS rule to constrain image widths on mobile screens.")
            
            # 4. Check for dynamic base font size in media queries
            self.assertTrue('html { font-size:' in content or '@media' in content, 
                            "Missing media queries or dynamic base font sizing for responsive typography.")


class SEOBrandingConsistencyTest(TestCase):
    def test_templates_have_consistent_brand_titles_and_no_known_typos(self):
        import os, re
        base_dir = os.path.join("articles", "templates")
        bad_title_re = re.compile(r"(\|\s*הספרייה\s*\{%\s*endblock|-\s*הספרייה התורנית\s*\{%\s*endblock)")
        for root, _, files in os.walk(base_dir):
            for fn in files:
                if not fn.endswith(".html"):
                    continue
                p = os.path.join(root, fn)
                content = open(p, encoding="utf-8").read()
                self.assertNotIn("המדוייק", content, f"Typo 'המדוייק' found in {p}")
                self.assertNotIn("והברכותיה", content, f"Typo 'והברכותיה' found in {p}")
                self.assertIsNone(bad_title_re.search(content), f"Inconsistent title brand in {p}")

    def test_public_subpages_define_dedicated_meta_descriptions(self):
        import os
        required_templates = [
            "articles/templates/articles/calculator.html",
            "articles/templates/articles/volume_calculator.html",
            "articles/templates/articles/weight_calculator.html",
            "articles/templates/articles/advanced_search.html",
            "articles/templates/articles/aramaic_translator.html",
            "articles/templates/articles/about.html",
            "articles/templates/articles/contact.html",
            "articles/templates/articles/parasha_list.html",
            "articles/templates/articles/books_list.html",
            "articles/templates/articles/qa_list.html",
        ]
        for path in required_templates:
            content = open(path, encoding="utf-8").read()
            self.assertIn("block meta_description", content, f"Missing dedicated meta_description in {path}")


class SQLitePragmaConfigTest(TestCase):
    def test_sqlite_connection_applies_performance_pragmas(self):
        from django.db import connection
        if connection.vendor != 'sqlite':
            self.skipTest('SQLite-only pragma check')
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA busy_timeout;')
            self.assertEqual(cursor.fetchone()[0], 20000)
            cursor.execute('PRAGMA cache_size;')
            self.assertEqual(cursor.fetchone()[0], -16000)
            cursor.execute('PRAGMA temp_store;')
            self.assertEqual(cursor.fetchone()[0], 2)


class VisitorLogPruneCommandTest(TestCase):
    def test_prune_visitor_logs_removes_only_bots_and_noise(self):
        from io import StringIO
        from django.core.management import call_command
        from articles.models import VisitorLog

        VisitorLog.objects.create(ip_address='1.2.3.4', path='/', user_agent='Mozilla/5.0 (Windows NT 10.0)')
        VisitorLog.objects.create(ip_address='5.6.7.8', path='/', user_agent='SentryUptimeBot/1.0')
        VisitorLog.objects.create(ip_address='127.0.0.1', path='/', user_agent='Mozilla/5.0')
        VisitorLog.objects.create(ip_address='9.9.9.9', path='/sw.js', user_agent='Mozilla/5.0')
        VisitorLog.objects.create(ip_address='8.8.8.8', path='/', user_agent='')

        out = StringIO()
        call_command('prune_visitor_logs', '--dry-run', stdout=out)
        self.assertEqual(VisitorLog.objects.count(), 5)
        self.assertIn('matching_noise=4', out.getvalue())

        call_command('prune_visitor_logs', stdout=StringIO())
        remaining = list(VisitorLog.objects.values_list('ip_address', flat=True))
        self.assertEqual(remaining, ['1.2.3.4'])


class VisitorMiddlewareFilterTest(TestCase):
    def test_middleware_skips_bots_empty_ua_and_localhost(self):
        from django.http import HttpResponse
        from django.test import RequestFactory
        from articles.middleware import VisitorTrackingMiddleware
        from articles.models import VisitorLog

        rf = RequestFactory()
        mw = VisitorTrackingMiddleware(lambda req: HttpResponse('ok'))

        mw(rf.get('/', REMOTE_ADDR='203.0.113.10', HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0)'))
        mw(rf.get('/', REMOTE_ADDR='203.0.113.11', HTTP_USER_AGENT=''))
        mw(rf.get('/', REMOTE_ADDR='127.0.0.1', HTTP_USER_AGENT='Mozilla/5.0'))
        mw(rf.get('/', REMOTE_ADDR='203.0.113.12', HTTP_USER_AGENT='SentryUptimeBot/1.0'))
        mw(rf.get('/manifest.json', REMOTE_ADDR='203.0.113.13', HTTP_USER_AGENT='Mozilla/5.0'))

        logged_ips = list(VisitorLog.objects.values_list('ip_address', flat=True))
        self.assertEqual(logged_ips, ['203.0.113.10'])
