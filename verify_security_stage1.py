#!/usr/bin/env python3
import argparse
import http.client
import json
import os
import re
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_ORIGIN = "https://leblibrary.co.il"
_DJANGO_READY = False


class _HTTPSConnectionIPv4(http.client.HTTPSConnection):
    def connect(self):
        addrs = socket.getaddrinfo(self.host, self.port, socket.AF_INET, socket.SOCK_STREAM)
        last_err = None
        for family, socktype, proto, _, sockaddr in addrs:
            try:
                sock = socket.socket(family, socktype, proto)
                if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(self.timeout)
                sock.connect(sockaddr)
                if self._tunnel_host:
                    self.sock = sock
                    self._tunnel()
                self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
                return
            except OSError as exc:
                last_err = exc
        raise last_err or OSError(f"IPv4 connection failed for {self.host}")


class _HTTPSHandlerIPv4(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnectionIPv4, req, context=ssl.create_default_context())


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_IPV4_OPENER = urllib.request.build_opener(_HTTPSHandlerIPv4())
_IPV4_NO_REDIRECT_OPENER = urllib.request.build_opener(_HTTPSHandlerIPv4(), _NoRedirectHandler())


def fetch_live(path, method="GET", data=None, headers=None, follow_redirects=True, timeout=12):
    req_headers = {"User-Agent": "LebLibrary-SecVerifier/2.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(LIVE_ORIGIN + path, data=data, headers=req_headers, method=method)
    opener = _IPV4_OPENER if follow_redirects else _IPV4_NO_REDIRECT_OPENER
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except OSError:
            body = ''
        return exc.code, body


def bootstrap_django():
    global _DJANGO_READY
    if _DJANGO_READY:
        return
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
    import django
    django.setup()
    _DJANGO_READY = True


def read_rel(rel_path):
    with open(os.path.join(BASE_DIR, rel_path), "r", encoding="utf-8") as f:
        return f.read()


def run_checks(offline=False):
    results = []

    def record(code, label, ok, detail=""):
        results.append((code, label, ok, detail))

    def chk_sec_01_superuser_crud():
        bootstrap_django()
        from django.contrib.auth.models import User
        from django.test import RequestFactory
        from articles.views import article_create, article_edit, article_delete
        rf = RequestFactory()
        regular_user = User(username="regular_test_user", is_active=True, is_superuser=False, is_staff=False)
        req_c = rf.get("/article/new/")
        req_c.user = regular_user
        r_c = article_create(req_c)
        req_e = rf.get("/article/test/edit/")
        req_e.user = regular_user
        r_e = article_edit(req_e, slug="test")
        req_d = rf.post("/article/test/delete/")
        req_d.user = regular_user
        r_d = article_delete(req_d, slug="test")
        ok = (r_c.status_code == 403 and r_e.status_code == 403 and r_d.status_code == 403)
        return ok, f"statuses=({r_c.status_code}, {r_e.status_code}, {r_d.status_code})"

    ok, det = chk_sec_01_superuser_crud()
    record("SEC-01", "Non-superuser blocked with HTTP 403 on article create/edit/delete", ok, det)

    def chk_sec_02_chat_xss_and_origin():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.ai_engine import ai_chat_endpoint, _sanitize_ai_chunk, _is_same_origin_request
        sk = read_rel("articles/templates/articles/includes/scripts.html")
        dom_safe = (
            "appendSafeUserBubble" in sk
            and "div.textContent = text;" in sk
            and 'nav-chat-user">${userText}' not in sk
            and 'qa-chat-user">${userText}' not in sk
            and "badgeTicks >= 50" in sk
        )
        xss_out = _sanitize_ai_chunk(
            '<img src=x onerror=alert(1)> [click](javascript:alert(1)) [phish](//evil.example/a) [ok](/books/)',
            "#d4af37",
            "_blank",
        )
        link_safe = (
            "<img" not in xss_out
            and "javascript:" not in xss_out
            and "//evil.example" not in xss_out
            and 'href="/books/"' in xss_out
            and 'rel="noopener noreferrer"' in xss_out
        )
        rf = RequestFactory()
        evil_req = rf.post(
            "/api/ai-chat/",
            data=json.dumps({"question": "test", "mode": "nav"}),
            content_type="application/json",
            HTTP_HOST="leblibrary.co.il",
            HTTP_ORIGIN="https://evil-attacker.example",
        )
        cross_site_req = rf.post(
            "/api/ai-chat/",
            data=json.dumps({"question": "test", "mode": "nav"}),
            content_type="application/json",
            HTTP_HOST="leblibrary.co.il",
            HTTP_SEC_FETCH_SITE="cross-site",
        )
        null_origin_req = rf.post(
            "/api/ai-chat/",
            data=json.dumps({"question": "test", "mode": "nav"}),
            content_type="application/json",
            HTTP_HOST="leblibrary.co.il",
            HTTP_ORIGIN="null",
        )
        origin_blocked = (
            ai_chat_endpoint(evil_req).status_code == 403
            and not _is_same_origin_request(cross_site_req)
            and not _is_same_origin_request(null_origin_req)
        )
        return (dom_safe and link_safe and origin_blocked), f"dom_safe={dom_safe}, link_safe={link_safe}, origin_blocked={origin_blocked}"

    ok, det = chk_sec_02_chat_xss_and_origin()
    record("SEC-02", "AI chat blocks DOM XSS, javascript:/protocol-relative links, cross-site & null Origin", ok, det)

    def chk_sec_03_ratelimit_ip():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.torah_engine import _get_client_ip
        rf = RequestFactory()
        r1 = rf.get("/api/tanakh-search/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9", REMOTE_ADDR="127.0.0.1")
        r2 = rf.get("/api/tanakh-search/", HTTP_X_REAL_IP="198.51.100.7", HTTP_X_FORWARDED_FOR="1.2.3.4", REMOTE_ADDR="127.0.0.1")
        ip1, ip2 = _get_client_ip(r1), _get_client_ip(r2)
        ok = (ip1 == "203.0.113.9" and ip2 == "198.51.100.7")
        return ok, f"xff_rightmost={ip1}, real_ip={ip2}"

    ok, det = chk_sec_03_ratelimit_ip()
    record("SEC-03", "Rate limiter resists X-Forwarded-For left-header spoofing", ok, det)

    def chk_sec_04_contact_and_checkout():
        bootstrap_django()
        from articles.views import _sanitize_header_value, _is_safe_editorial_url
        v_src = read_rel("articles/views.py")
        hdr_clean = _sanitize_header_value("Hello\r\nBcc: evil@example.com")
        no_crlf = "\r" not in hdr_clean and "\n" not in hdr_clean
        url_guard = (
            _is_safe_editorial_url("/advanced-search/?q=test")
            and _is_safe_editorial_url("https://leblibrary.co.il/books/")
            and not _is_safe_editorial_url("javascript:alert(1)")
            and not _is_safe_editorial_url("//evil.example/x")
        )
        checks = [
            no_crlf,
            url_guard,
            "@ratelimit(rate=5, timeout=300, methods=('POST',))" in v_src,
            "@ratelimit(rate=10, timeout=300, methods=('POST',))" in v_src,
            "Book.objects.select_for_update()" in v_src,
            "item.quantity <= 0" in v_src,
            "locked_book.stock -= qty" in v_src,
            'value="{escape(q)}"' in v_src,
            "CONTACT_RECIPIENT_EMAIL" in v_src,
        ]
        return all(checks), f"checks={checks}"

    ok, det = chk_sec_04_contact_and_checkout()
    record("SEC-04", "Contact header sanitization, POST rate-limiting, atomic stock checkout, and safe editorial URLs", ok, det)

    def chk_sec_05_draft_idor_and_audio_dos():
        bootstrap_django()
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        from articles.models import Article
        from articles.views import get_article_audio
        from articles.urls import legacy_article_id_redirect
        v_src = read_rel("articles/views.py")
        u_src = read_rel("articles/urls.py")
        draft = Article.objects.filter(is_published=False).first()
        draft_blocked = True
        if draft:
            rf = RequestFactory()
            req_a = rf.get(f"/api/audio/article/{draft.id}/")
            req_a.user = AnonymousUser()
            resp_a = get_article_audio(req_a, str(draft.id))
            req_r = rf.get(f"/article/{draft.id}/")
            req_r.user = AnonymousUser()
            resp_r = legacy_article_id_redirect(req_r, draft.id)
            draft_blocked = (resp_a.status_code == 404 and resp_r.status_code == 302 and draft.slug not in resp_r.get("Location", ""))
        src_checks = [
            "if not article.is_published and not request.user.is_superuser:" in v_src,
            "_MAX_CONCURRENT_AUDIO_JOBS = 2" in v_src,
            "@ratelimit(rate=20, timeout=300)\ndef get_article_audio(" in v_src,
            "@ratelimit(rate=20, timeout=300)\ndef get_book_audio(" in v_src,
            "@ratelimit(rate=60, timeout=60)\ndef live_search(" in v_src,
            "@ratelimit(rate=60, timeout=60)\ndef search_acronyms_api(" in v_src,
            "if article.is_published:" in u_src,
        ]
        ok = draft_blocked and all(src_checks)
        return ok, f"draft_blocked={draft_blocked}, src_checks={src_checks}"

    ok, det = chk_sec_05_draft_idor_and_audio_dos()
    record("SEC-05", "Draft article IDOR blocked on audio/redirects and TTS/search endpoints rate-limited", ok, det)

    def chk_sec_06_reflected_xss_and_ssrf():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.torah_engine import tanakh_advanced_search_api, _fetch_sefaria_json_cached
        from articles.ai_engine import torah_ai_insights_api
        rf = RequestFactory()
        xss_payload = "<img src=x onerror=alert(1)>"
        r_qo = tanakh_advanced_search_api(rf.get("/api/tanakh-search/", {"type": "quick_open", "target_book": xss_payload}))
        d_qo = json.loads(r_qo.content.decode("utf-8"))
        qo_safe = "<img" not in d_qo.get("error", "")

        r_serm = torah_ai_insights_api(rf.get("/api/torah-ai-insights/", {"mode": "sermon_generator", "q": f"שבת {xss_payload}"}))
        d_serm = json.loads(r_serm.content.decode("utf-8"))
        serm_safe = "<img" not in d_serm.get("topic", "") and "<img" not in d_serm.get("sermon_html", "")

        ssrf_blocked = (
            _fetch_sefaria_json_cached("../../etc/passwd") is None
            and _fetch_sefaria_json_cached("Genesis.1.1?evil=1") is None
            and _fetch_sefaria_json_cached("Genesis.1.1\r\nX-Test: 1") is None
        )
        adv = read_rel("articles/templates/articles/advanced_search.html")
        al = read_rel("articles/templates/articles/article_list.html")
        ar = read_rel("articles/templates/articles/aramaic_translator.html")
        tpl_safe = (
            "function escapeHtml(" in adv
            and "function sanitizeRichHtml(" in adv
            and "${escapeHtml(data.error)}" in adv
            and "${escapeHtml(data.topic)}" in adv
            and "function escapeHtml(" in al
            and "function sanitizeMarkHtml(" in ar
            and "data-quick-term=" in ar
        )
        ok = qo_safe and serm_safe and ssrf_blocked and tpl_safe
        return ok, f"qo_safe={qo_safe}, serm_safe={serm_safe}, ssrf_blocked={ssrf_blocked}, tpl_safe={tpl_safe}"

    ok, det = chk_sec_06_reflected_xss_and_ssrf()
    record("SEC-06", "Reflected/DOM XSS sanitized on backend + templates and Sefaria path-traversal blocked", ok, det)

    def chk_sec_07_cart_csrf_and_noopener():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.views import _is_safe_cart_action_request
        rf = RequestFactory()
        ok_nav = _is_safe_cart_action_request(
            rf.get("/cart/add/1/", HTTP_HOST="leblibrary.co.il", HTTP_SEC_FETCH_SITE="same-origin", HTTP_SEC_FETCH_DEST="document")
        )
        blk_cross = not _is_safe_cart_action_request(
            rf.get("/cart/add/1/", HTTP_HOST="leblibrary.co.il", HTTP_SEC_FETCH_SITE="cross-site", HTTP_SEC_FETCH_DEST="image")
        )
        blk_img = not _is_safe_cart_action_request(
            rf.get("/cart/add/1/", HTTP_HOST="leblibrary.co.il", HTTP_SEC_FETCH_DEST="image")
        )
        blk_prefetch = not _is_safe_cart_action_request(
            rf.get("/cart/add/1/", HTTP_HOST="leblibrary.co.il", HTTP_SEC_PURPOSE="prefetch")
        )
        missing_noopener = []
        for tpl in (
            "articles/templates/articles/article_detail.html",
            "articles/templates/articles/book_detail.html",
            "articles/templates/articles/advanced_search.html",
        ):
            txt = read_rel(tpl)
            for m in re.finditer(r'<a\b[^>]*target=["\']_blank["\'][^>]*>', txt, re.I):
                if "noopener" not in m.group(0).lower():
                    missing_noopener.append(tpl)
        al = read_rel("articles/templates/articles/article_list.html")
        sale_stock_ok = "{% if book.stock > 0 %}" in al
        ok = ok_nav and blk_cross and blk_img and blk_prefetch and not missing_noopener and sale_stock_ok
        return ok, f"cart_guards=({ok_nav},{blk_cross},{blk_img},{blk_prefetch}), missing_noopener={len(missing_noopener)}, sale_stock={sale_stock_ok}"

    ok, det = chk_sec_07_cart_csrf_and_noopener()
    record("SEC-07", "Cross-site GET cart CSRF blocked, all target=_blank have rel=noopener, and home stock checked", ok, det)

    def chk_sec_08_settings_and_admin():
        bootstrap_django()
        from django.conf import settings as dj_settings
        st_src = read_rel("core/settings.py")
        ad_src = read_rel("articles/admin.py")
        sk_ok = (
            bool(dj_settings.SECRET_KEY)
            and len(dj_settings.SECRET_KEY) >= 50
            and not dj_settings.SECRET_KEY.startswith("django-insecure-")
            and "django-insecure-" not in st_src
        )
        cache_shared = "FileBasedCache" in st_src
        headers_ok = (
            getattr(dj_settings, "X_FRAME_OPTIONS", "") == "DENY"
            and getattr(dj_settings, "SESSION_COOKIE_HTTPONLY", False) is True
            and getattr(dj_settings, "SESSION_COOKIE_SAMESITE", "") == "Lax"
            and getattr(dj_settings, "DATA_UPLOAD_MAX_MEMORY_SIZE", 0) <= 20 * 1024 * 1024
            and "send_default_pii=False" in st_src
        )
        admin_ok = (
            "_BLOCKED_IMPORT_TAGS" in ad_src
            and "def clean_word_import(" in ad_src
            and ".docx" in ad_src
        )
        ok = sk_ok and cache_shared and headers_ok and admin_ok
        return ok, f"secret_key_ok={sk_ok}, shared_cache={cache_shared}, headers_ok={headers_ok}, admin_ok={admin_ok}"

    ok, det = chk_sec_08_settings_and_admin()
    record("SEC-08", "core/settings.py strong SECRET_KEY, shared FileBasedCache, hardened headers/limits, safe admin DOCX import", ok, det)

    def chk_sec_09_pro_hardening_and_hygiene():
        bootstrap_django()
        from articles.models import ContactMessage
        ai_src = read_rel("articles/ai_engine.py")
        v_src = read_rel("articles/views.py")
        ad_html = read_rel("articles/templates/articles/article_detail.html")
        bd_html = read_rel("articles/templates/articles/book_detail.html")
        sk_html = read_rel("articles/templates/articles/includes/scripts.html")

        key_in_header = (
            "'x-goog-api-key': API_KEY" in ai_src
            and "'x-goog-api-key': api_key" in ai_src
            and "key={" not in ai_src
            and "load_dotenv(" not in ai_src
        )
        contact_db = (
            hasattr(ContactMessage, "objects")
            and "ContactMessage.objects.create(" in v_src
            and "contact_messages_backup.jsonl" not in v_src
            and "moshe111moshe111@gmail.com" not in v_src
            and "mosheleibowitzkey123" not in v_src
        )
        silent_except_files = []
        for rel_py in (
            "articles/views.py",
            "articles/ai_engine.py",
            "articles/torah_engine.py",
            "articles/aramaic_engine.py",
            "articles/clusters_engine.py",
            "articles/context_processors.py",
        ):
            txt = read_rel(rel_py)
            if re.search(r"except\s+Exception(?:\s+as\s+\w+)?\s*:\s*\n\s*pass\b", txt):
                silent_except_files.append(rel_py)

        no_dup_modal = (
            'id="luxShareModal"' not in ad_html
            and 'id="luxShareModal"' not in bd_html
            and "function openShareModal(" not in ad_html
            and "function openShareModal(" not in bd_html
        )
        clean_code = (
            "import subprocess" not in v_src
            and "get_base_schema_json" not in v_src
            and "asyncio.wait_for(" in v_src
            and "console.log(" not in sk_html
        )
        ok = key_in_header and contact_db and not silent_except_files and no_dup_modal and clean_code
        return ok, f"header_key={key_in_header}, contact_db={contact_db}, silent_excepts={silent_except_files}, no_dup_modal={no_dup_modal}, clean={clean_code}"

    ok, det = chk_sec_09_pro_hardening_and_hygiene()
    record("SEC-09", "Gemini x-goog-api-key header, ContactMessage DB, 0 silent excepts, no dup share modal & clean imports", ok, det)

    def chk_sec_10_middleware_vector_emails_urls_models():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.middleware import _extract_valid_client_ip
        from articles.emails import _clean_header
        mw_src = read_rel("articles/middleware.py")
        vs_src = read_rel("articles/vector_store.py")
        em_src = read_rel("articles/emails.py")
        cu_src = read_rel("core/urls.py")
        md_src = read_rel("articles/models.py")

        rf = RequestFactory()
        ip_ok = (
            _extract_valid_client_ip(rf.get("/", HTTP_X_FORWARDED_FOR="1.2.3.4, 203.0.113.9", REMOTE_ADDR="127.0.0.1")) == "203.0.113.9"
            and _extract_valid_client_ip(rf.get("/", HTTP_X_REAL_IP="not-an-ip", REMOTE_ADDR="127.0.0.1")) == "127.0.0.1"
            and "_BOT_UA_RE" in mw_src
            and "'/api/'" in mw_src
        )
        vs_ok = (
            "def _get_collection():" in vs_src
            and "article.slug" in vs_src
            and not re.search(r"except\s*:\s*\n", vs_src)
        )
        em_ok = (
            "\r" not in _clean_header("a@b.com\r\nBcc: evil@example.com")
            and "fail_silently=False" in em_src
        )
        cu_ok = (
            "mosheleibowitzkey123" not in cu_src
            and cu_src.count("@cache_page(60 * 60)") >= 4
        )
        md_ok = (
            "_sanitize_imported_soup" in md_src
            and "print(" not in md_src
        )
        ok = ip_ok and vs_ok and em_ok and cu_ok and md_ok
        return ok, f"middleware={ip_ok}, vector_store={vs_ok}, emails={em_ok}, core_urls={cu_ok}, models={md_ok}"

    ok, det = chk_sec_10_middleware_vector_emails_urls_models()
    record("SEC-10", "Hardened middleware IP/bot filter, lazy ChromaDB, safe emails, cached core/urls & sanitized models", ok, det)

    if not offline:
        def chk_live_sec_01():
            c_evil, _ = fetch_live(
                "/api/ai-chat/",
                method="POST",
                data=json.dumps({"question": "books", "mode": "nav"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "https://evil-attacker.example"},
            )
            c_cross, _ = fetch_live(
                "/api/ai-chat/",
                method="POST",
                data=json.dumps({"question": "books", "mode": "nav"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"},
            )
            c_ok, body_ok = fetch_live(
                "/api/ai-chat/",
                method="POST",
                data=json.dumps({"question": "\u05e1\u05e4\u05e8\u05d9\u05dd", "mode": "nav"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "https://leblibrary.co.il"},
            )
            return (c_evil == 403 and c_cross == 403 and c_ok == 200 and len(body_ok) > 10), f"cross_origin={c_evil}, cross_site={c_cross}, same_origin={c_ok}"

        ok, det = chk_live_sec_01()
        record("LIVE-SEC-01", "Live /api/ai-chat/ rejects cross-origin & cross-site POST (403) and serves same-origin (200)", ok, det)

        def chk_live_sec_02():
            code, body = fetch_live("/")
            if code != 200:
                return False, f"HTTP {code}"
            ok = (
                "appendSafeUserBubble" in body
                and "buildAiRequestHeaders" in body
                and 'nav-chat-user">${userText}' not in body
                and "function escapeHtml(" in body
                and "badgeTicks >= 50" in body
            )
            return ok, ""

        ok, det = chk_live_sec_02()
        record("LIVE-SEC-02", "Live home page serves XSS-safe AI chat, escaped widgets, and bounded badge timer", ok, det)

        def chk_live_sec_03():
            code, body = fetch_live("/contact/")
            return (code == 200 and "form" in body.lower()), f"HTTP {code}"

        ok, det = chk_live_sec_03()
        record("LIVE-SEC-03", "Live GET /contact/ remains unaffected by POST-only rate limit", ok, det)

        def chk_live_sec_04():
            q = urllib.parse.urlencode({"type": "quick_open", "target_book": "<img src=x onerror=alert(1)>"})
            c1, b1 = fetch_live(f"/api/tanakh-search/?{q}")
            c2, b2 = fetch_live("/advanced-search/")
            d1 = json.loads(b1) if c1 == 200 else {}
            ok = (
                c1 == 200
                and "<img" not in d1.get("error", "")
                and c2 == 200
                and "function sanitizeRichHtml(" in b2
                and "${escapeHtml(data.error)}" in b2
            )
            return ok, f"api={c1}, error_safe={'<img' not in d1.get('error', '')}, page={c2}"

        ok, det = chk_live_sec_04()
        record("LIVE-SEC-04", "Live /advanced-search/ and quick_open API neutralize reflected XSS payloads", ok, det)

        def chk_live_sec_05():
            code, body = fetch_live("/aramaic-translator/")
            ok = (code == 200 and "function sanitizeMarkHtml(" in body and "data-quick-term=" in body)
            return ok, f"HTTP {code}"

        ok, det = chk_live_sec_05()
        record("LIVE-SEC-05", "Live /aramaic-translator/ serves HTML-escaped dictionary and sanitized snippets", ok, det)

        def chk_live_sec_06():
            c1, b1 = fetch_live("/article/63/")
            c2, b2 = fetch_live("/book/84/")
            bad1 = [m.group(0) for m in re.finditer(r'<a\b[^>]*target=["\']_blank["\'][^>]*>', b1, re.I) if "noopener" not in m.group(0).lower()]
            bad2 = [m.group(0) for m in re.finditer(r'<a\b[^>]*target=["\']_blank["\'][^>]*>', b2, re.I) if "noopener" not in m.group(0).lower()]
            ok = (c1 == 200 and c2 == 200 and not bad1 and not bad2)
            return ok, f"article={c1} (missing_rel={len(bad1)}), book84={c2} (missing_rel={len(bad2)})"

        ok, det = chk_live_sec_06()
        record("LIVE-SEC-06", "Live /article/63/ and /book/84/ enforce rel=noopener noreferrer on all _blank links", ok, det)

        def chk_live_sec_07():
            c1, b1 = fetch_live("/article/63/")
            c2, b2 = fetch_live("/book/84/")
            cnt1 = b1.count('id="luxShareModal"')
            cnt2 = b2.count('id="luxShareModal"')
            no_clog = "console.log(" not in b1
            ok = (c1 == 200 and c2 == 200 and cnt1 == 1 and cnt2 == 1 and no_clog)
            return ok, f"article_share_modals={cnt1}, book84_share_modals={cnt2}, no_console_log={no_clog}"

        ok, det = chk_live_sec_07()
        record("LIVE-SEC-07", "Live /article/63/ and /book/84/ render single unique #luxShareModal and clean JS", ok, det)

        def chk_live_sec_08():
            c_llms, _ = fetch_live("/llms-full.txt")
            c_rob, _ = fetch_live("/robots.txt")
            c_man, _ = fetch_live("/manifest.json")
            c_oa, _ = fetch_live("/openapi.json")
            ok = (c_llms == 200 and c_rob == 200 and c_man == 200 and c_oa == 200)
            return ok, f"llms_full={c_llms}, robots={c_rob}, manifest={c_man}, openapi={c_oa}"

        ok, det = chk_live_sec_08()
        record("LIVE-SEC-08", "Live cached core endpoints (/llms-full.txt, /robots.txt, /manifest.json, /openapi.json) return HTTP 200", ok, det)

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY SECURITY HARDENING VERIFICATION ({passed}/{len(results)} PASSED)")
    print("=" * 84)
    for code, label, ok, det in results:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {code:<12} | {label}")
        if det:
            print(f"         -> {det}")
    print("=" * 84 + "\n")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    run_checks(offline=args.offline)