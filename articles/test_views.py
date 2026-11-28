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


class ArticleFootnotesPreservationTest(TestCase):
    def test_clean_word_html_preserves_and_restores_footnotes_divider(self):
        from articles.models import clean_word_html

        # מקרה א: מאמר שנערך עם class_ ישן, <hr> וכותרת הערות שוליים
        html_with_divider = (
            '<p>טקסט עם <a href="/article/test/">קישור</a>'
            '<a class="footnote-ref" href="#footnote-1" id="footnote-ref-1"><sup>[1]</sup></a></p>'
            '<hr style="border-top:5px solid #2c3e50;">'
            '<h2><strong>הערות שוליים</strong></h2>'
            '<div class_="custom-footnotes-container">'
            '<div id="footnote-1"><span>1.</span><span>תוכן הערה</span></div>'
            '</div>'
        )
        res = clean_word_html(html_with_divider)
        self.assertIn('<hr', res)
        self.assertIn('הערות שוליים', res)
        self.assertIn('class="custom-footnotes-container"', res)
        self.assertNotIn('class_=', res)
        self.assertIn('href="/article/test/"', res)

        # מקרה ב: מאמר שבו <hr> ו-<h2> כבר נמחקו בעריכה קודמת — משחזר אותם אוטומטית
        html_missing_divider = (
            '<p>פסקה אחרונה</p>'
            '<div class_="custom-footnotes-container">'
            '<div id="footnote-1"><span>1.</span><span>הערה ראשונה</span></div>'
            '</div>'
        )
        restored = clean_word_html(html_missing_divider)
        self.assertIn('<hr', restored)
        self.assertIn('הערות שוליים', restored)
        self.assertIn('class="custom-footnotes-container"', restored)
        self.assertLess(restored.index('<hr'), restored.index('הערות שוליים'))
        self.assertLess(restored.index('הערות שוליים'), restored.index('id="footnote-1"'))

    def test_process_mammoth_html_emits_valid_class_and_survives_edit(self):
        from articles.models import process_mammoth_html, clean_word_html

        raw_word_html = (
            '<p>פסקת תוכן עם הפניה<sup><a href="#footnote-1" id="footnote-ref-1">1</a></sup>.</p>'
            '<ol><li id="footnote-1"><p>מקור בהערה <a href="#footnote-ref-1">↑</a></p></li></ol>'
        )
        from_word = process_mammoth_html(raw_word_html)
        self.assertIn('<hr', from_word)
        self.assertIn('הערות שוליים', from_word)
        self.assertIn('class="custom-footnotes-container"', from_word)
        self.assertNotIn('class_=', from_word)

        # מדמה עריכה ידנית ושמירה חוזרת לאחר העלאה מ-Word
        after_edit = clean_word_html(from_word)
        self.assertEqual(after_edit.count('<hr'), 1)
        self.assertEqual(after_edit.count('הערות שוליים'), 1)
        self.assertIn('class="custom-footnotes-container"', after_edit)
        self.assertNotIn('class_=', after_edit)

    def test_article_save_roundtrip_is_idempotent_and_preserves_links(self):
        from articles.models import Article

        content = (
            '<p>עי\' במאמר <a href="/article/first/">מאמר ראשון</a>'
            '<a class="footnote-ref" href="#footnote-1" id="footnote-ref-1"><sup>[1]</sup></a>.</p>'
            '<div class_="custom-footnotes-container">'
            '<div id="footnote-1"><span>1.</span><span>ועי\' <a href="/article/second/">מאמר שני</a>.</span></div>'
            '</div>'
        )
        art = Article.objects.create(title='בדיקת שימור הערות שוליים', content=content)
        art.refresh_from_db()
        # שמירה חוזרת (מדמה עריכה שנייה של אותו מאמר)
        art.save()
        art.refresh_from_db()

        self.assertEqual(art.content.count('<hr'), 1)
        self.assertEqual(art.content.count('הערות שוליים'), 1)
        self.assertIn('class="custom-footnotes-container"', art.content)
        self.assertNotIn('class_=', art.content)
        self.assertIn('href="/article/first/"', art.content)
        self.assertIn('href="/article/second/"', art.content)

    def test_normalize_footnotes_merges_split_flex_children_with_links(self):
        from bs4 import BeautifulSoup
        from articles.models import normalize_article_footnotes_html

        # מדמה HTML שפוצל ע"י CKEditor כאשר יש קישור בתוך הערת שוליים
        split_html = (
            '<p>טקסט<a class="footnote-ref" href="#footnote-7" id="footnote-ref-7"><sup>[7]</sup></a></p>'
            '<div class="custom-footnotes-container">'
            '<div id="footnote-7" style="align-items:flex-start;display:flex;margin-bottom:15px;">'
            '<span style="color:#d4af37;"><span style="flex-shrink:0;min-width:35px;"><strong>7.</strong></span></span>'
            '<span style="flex-grow:1;"> באם הבנים שמחה וע"ע במאמר \'</span>'
            '<a href="/article/house/"><span style="flex-grow:1;">שהחיינו על בית חדש בארץ ישראל</span></a>'
            '<span style="flex-grow:1;">\' שהעלנו שיש לברך.</span>'
            '</div></div>'
        )
        out1 = normalize_article_footnotes_html(split_html)
        out2 = normalize_article_footnotes_html(out1)

        soup = BeautifulSoup(out2, 'html.parser')
        fn = soup.find('div', id='footnote-7')
        self.assertIsNotNone(fn)
        direct_tags = [c for c in fn.contents if getattr(c, 'name', None)]
        # בדיוק 3 אלמנטים ישירים ב-flex: מספר, גוף מאוחד אחד, וחץ חזרה
        self.assertEqual(len(direct_tags), 3)
        bodies = fn.find_all('div', class_='footnote-body')
        self.assertEqual(len(bodies), 1)
        link = bodies[0].find('a', href='/article/house/')
        self.assertIsNotNone(link)
        self.assertIn('באם הבנים שמחה', bodies[0].get_text())
        self.assertIn('שהעלנו שיש לברך', bodies[0].get_text())
        self.assertIn('flex-shrink: 0', direct_tags[0].get('style', ''))
        self.assertEqual(len(fn.find_all('a', class_='footnote-backref')), 1)

    def test_article_detail_view_renders_merged_footnote_body_with_links(self):
        from bs4 import BeautifulSoup
        from django.urls import reverse
        from articles.models import Article

        split_html = (
            '<p>טקסט פתיחה<a class="footnote-ref" href="#footnote-1" id="footnote-ref-1"><sup>[1]</sup></a>.</p>'
            '<div class="custom-footnotes-container">'
            '<div id="footnote-1" style="align-items:flex-start;display:flex;margin-bottom:15px;">'
            '<span style="color:#d4af37;"><span style="flex-shrink:0;min-width:35px;"><strong>1.</strong></span></span>'
            '<span style="flex-grow:1;"> וע"ע במאמר </span>'
            '<a href="/article/house/"><span style="flex-grow:1;">שהחיינו על בית חדש</span></a>'
            '<span style="flex-grow:1;"> שהעלנו שיש לברך.</span>'
            '</div></div>'
        )
        art = Article.objects.create(
            title="בדיקת תצוגת קישור בהערת שוליים",
            content=split_html,
            is_published=True,
        )
        url = reverse("articles:detail", kwargs={"slug": art.slug})
        resp = self.client.get(url, secure=True)
        self.assertEqual(resp.status_code, 200)

        soup = BeautifulSoup(resp.content.decode("utf-8"), "html.parser")
        fn = soup.find("div", id="footnote-1")
        self.assertIsNotNone(fn)
        direct_tags = [c for c in fn.contents if getattr(c, "name", None)]
        self.assertEqual(len(direct_tags), 3)
        body = fn.find("div", class_="footnote-body")
        self.assertIsNotNone(body)
        self.assertIsNotNone(body.find("a", href="/article/house/"))
        self.assertIn("שהעלנו שיש לברך", body.get_text())
        self.assertIsNotNone(fn.find("a", class_="footnote-backref"))


class QADailyReport20261128Test(TestCase):
    def setUp(self):
        from articles.models import Article, Book, QA
        self.book_read = Book.objects.create(
            title="מידה של תורה",
            summary="ספר עיון מלא במידות ושיעורי תורה",
            is_for_sale=False,
        )
        self.book_sale = Book.objects.create(
            title="מידה של תורה",
            summary="מהדורה מודפסת לרכישה",
            is_for_sale=True,
            price=20,
        )
        self.article = Article.objects.create(
            title="מאמר על מידה של תורה",
            content="<p>עיון במידות חז״ל ושיעורי תורה.</p>",
            is_published=True,
        )
        self.qa1 = QA.objects.create(
            question="מהו עניין הצומות ומידה של תורה?",
            answer="תשובה מפורטת בנושא צומות ומידות.",
            category="צומות",
        )
        self.qa2 = QA.objects.create(
            question="שאלה בעניין ברכות ומידה של תורה",
            answer="תשובה בעניין ברכות.",
            category="ברכות",
        )

    def test_qa01_02_03_and_recheck03_calculators_accessibility_and_threshold(self):
        from bs4 import BeautifulSoup
        from django.urls import reverse

        for url_name in ("articles:calculator", "articles:volume_calculator", "articles:weight_calculator"):
            resp = self.client.get(reverse(url_name), secure=True)
            self.assertEqual(resp.status_code, 200)
            html = resp.content.decode("utf-8")
            soup = BeautifulSoup(html, "html.parser")

            # QA-01: explicit < 0.0001 threshold formatter + exact value in tooltip
            self.assertIn("formatCalcDisplay", html)
            self.assertIn("< 0.0001", html)
            self.assertIn("formatCalcExact", html)

            # QA-02: distinct accessible names for all 4 inputs/selects
            labels = []
            for fid in ("inputValue1", "unitSelect1", "inputValue2", "unitSelect2"):
                el = soup.find(id=fid)
                self.assertIsNotNone(el, f"{fid} missing in {url_name}")
                lbl = (el.get("aria-label") or "").strip()
                self.assertTrue(len(lbl) >= 8, f"{fid} missing aria-label in {url_name}")
                labels.append(lbl)
            self.assertEqual(len(set(labels)), 4, f"Duplicate aria-labels in {url_name}")

            # QA-03: focusable tooltip buttons with aria-describedby & role="tooltip"
            tt_btns = soup.find_all("button", class_="tooltip-trigger-btn")
            self.assertGreaterEqual(len(tt_btns), 6)
            for b in tt_btns:
                self.assertTrue(b.get("aria-label"))
                desc = b.get("aria-describedby")
                self.assertTrue(desc)
                tt_el = soup.find(id=desc)
                self.assertIsNotNone(tt_el)
                self.assertEqual(tt_el.get("role"), "tooltip")

            # Item 03: main link points to reading edition, subtle secondary link points to sale edition
            read_href = reverse("articles:book_detail", args=[self.book_read.pk])
            sale_href = reverse("articles:book_detail", args=[self.book_sale.pk])
            self.assertIn(f'href="{read_href}"', html)
            self.assertIn(f'href="{sale_href}"', html)

    def test_qa04_05_06_aramaic_translator_keyboard_and_nikud(self):
        from bs4 import BeautifulSoup
        from django.urls import reverse

        resp = self.client.get(reverse("articles:aramaic_translator"), secure=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")

        # QA-04: dialect tabs are focusable <button role="tab"> with aria-selected
        tabs = soup.select("#dialectDivisionTabs button.corpus-division-card[role='tab']")
        self.assertEqual(len(tabs), 3)
        self.assertEqual(tabs[0].get("aria-selected"), "true")
        self.assertEqual(tabs[1].get("aria-selected"), "false")
        self.assertEqual(tabs[2].get("aria-selected"), "false")

        # QA-05: keyboard button per lexicon row
        self.assertIn('class="lexicon-term-btn"', html)
        self.assertIn('aria-label="פתח פירוט עבור ', html)

        # QA-06: nikud normalization in lexicon filtering
        self.assertIn("function normalizeLexSearch", html)
        self.assertIn(r"[\u0591-\u05C7]", html)

    def test_qa07_and_recheck26_advanced_search_export_snapshot_and_focus_trap(self):
        from django.urls import reverse

        resp = self.client.get(reverse("articles:advanced_search"), secure=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")

        # QA-07: share/copy URL derived from lastExecutedSearchParams snapshot
        self.assertIn("let lastExecutedSearchParams = null;", html)
        self.assertIn("lastExecutedSearchParams = {", html)
        self.assertIn("const snap = (useExecutedSnapshot !== false && lastExecutedSearchParams", html)

        # Item 26: Escape immediately deactivates Bootstrap focus trap and handles Tab deterministically
        self.assertIn("function deactivateModalFocusTrap", html)
        self.assertIn("if (e.key === 'Escape')", html)
        self.assertIn("deactivateModalFocusTrap(modalEl);", html)

    def test_qa08_global_search_tabs_books_and_sorted_qa(self):
        from bs4 import BeautifulSoup
        from django.urls import reverse

        base_url = reverse("articles:list")

        # Articles tab
        r_art = self.client.get(base_url, {"q": "מידה של תורה"}, secure=True)
        self.assertEqual(r_art.status_code, 200)
        html_art = r_art.content.decode("utf-8")
        soup_art = BeautifulSoup(html_art, "html.parser")
        self.assertNotIn("לחץ על הלשוניות השונות למעלה", html_art)
        self.assertIsNotNone(soup_art.find(id="search-tab-articles"))
        self.assertIsNotNone(soup_art.find(id="search-tab-books"))
        self.assertIsNotNone(soup_art.find(id="search-tab-qa"))

        # Books tab shows matching book
        r_books = self.client.get(base_url, {"q": "מידה של תורה", "tab": "books"}, secure=True)
        self.assertEqual(r_books.status_code, 200)
        self.assertIn("מידה של תורה", r_books.content.decode("utf-8"))
        self.assertIn('id="search-panel-books"', r_books.content.decode("utf-8"))

        # Q&A tab shows sorted Q&As (ברכות before צומות alphabetically)
        r_qa = self.client.get(base_url, {"q": "מידה של תורה", "tab": "qa"}, secure=True)
        self.assertEqual(r_qa.status_code, 200)
        html_qa = r_qa.content.decode("utf-8")
        self.assertIn('id="search-panel-qa"', html_qa)
        self.assertIn("ברכות", html_qa)
        self.assertIn("צומות", html_qa)
        self.assertLess(html_qa.index("שאלה בעניין ברכות"), html_qa.index("מהו עניין הצומות"))

        # Live search API includes Q&A results
        r_live = self.client.get(reverse("articles:live_search"), {"q": "מידה של תורה"}, secure=True)
        self.assertEqual(r_live.status_code, 200)
        types = {item["type"] for item in r_live.json().get("results", [])}
        self.assertIn("שו״ת", types)

    def test_qa09_qa_category_link_decoupled_from_toggle_header(self):
        from bs4 import BeautifulSoup
        from django.urls import reverse

        resp = self.client.get(reverse("articles:qa"), secure=True)
        self.assertEqual(resp.status_code, 200)
        soup = BeautifulSoup(resp.content.decode("utf-8"), "html.parser")

        header = soup.find(id=f"header-qa-{self.qa1.id}")
        self.assertIsNotNone(header)
        # Category link must NOT be nested inside role="button" header
        self.assertIsNone(header.find("a", class_="qa-category-link"))
        card = soup.find(id=f"qa-{self.qa1.id}")
        cat_link = card.find("a", class_="qa-category-link")
        self.assertIsNotNone(cat_link)
        self.assertIn("category=", cat_link.get("href", ""))

    def test_qa10_book_detail_zen_mode_button_exposes_aria_pressed(self):
        from bs4 import BeautifulSoup
        from django.urls import reverse

        resp = self.client.get(reverse("articles:book_detail", args=[self.book_read.pk]), secure=True)
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")
        btn = soup.find(id="zenToggleBtn")
        self.assertIsNotNone(btn)
        self.assertEqual(btn.get("aria-pressed"), "false")
        self.assertEqual(btn.get("aria-label"), "מצב קריאה נקי")
        self.assertIn("btn.setAttribute('aria-pressed', 'true')", html)
        self.assertIn("btn.setAttribute('aria-pressed', 'false')", html)
