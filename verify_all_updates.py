#!/usr/bin/env python3
"""
LebLibrary Deep Verification Suite
בודק לעומק את כל השינויים בפרויקט:
1. קבצי ליבה (views.py, torah_engine.py, core/urls.py)
2. תבניות HTML, PWA, SEO ותצורה (advanced_search, connections_audit, sw.js, humans.txt, assetlinks.json, pytest.ini)
3. בדיקות מתמטיות ו-Django Runtime (הכלה מלאה, אמות קריאה כפולות, יחיד/רבים, ללא CacheKeyWarning, ונקודות קצה דינמיות)
4. בדיקות HTTP חיות מול https://leblibrary.co.il (אלא אם הופעל --offline)

הרצה ב-VS Code (מקומי):
    python verify_all_updates.py --offline

הרצה בשרת Ubuntu (מלא כולל בדיקות חיות):
    ./venv/bin/python verify_all_updates.py
"""

import argparse
import ast
import configparser
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
import warnings


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LIVE_ORIGIN = "https://leblibrary.co.il"
SKIP_DIRS = {
    "venv", ".venv", ".git", "staticfiles", "__pycache__",
    "node_modules", "media", ".pytest_cache", ".idea", ".vscode",
}
SHA256_RE = re.compile(r"^([0-9A-F]{2}:){31}[0-9A-F]{2}$")
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
_NO_REDIRECT_OPENER = urllib.request.build_opener(_HTTPSHandlerIPv4(), _NoRedirectHandler())


def find_project_files(filename):
    matches = []
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        if filename in files:
            matches.append(os.path.join(root, filename))
    matches.sort(key=lambda p: (p.count(os.sep), p))
    return matches


def relpath(path):
    try:
        return os.path.relpath(path, BASE_DIR).replace("\\", "/")
    except Exception:
        return path


def read_text_and_bom(path):
    with open(path, "rb") as f:
        raw = f.read()
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig" if has_bom else "utf-8", errors="replace")
    return text, has_bom


def fetch_live(path, allow_redirects=True, timeout=8):
    url = LIVE_ORIGIN + path
    req = urllib.request.Request(url, headers={"User-Agent": "LebLibrary-DeepVerifier/2.0"})
    opener = _IPV4_OPENER if allow_redirects else _NO_REDIRECT_OPENER
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers.items()), resp.read()
    except urllib.error.HTTPError as exc:
        body = b""
        try:
            body = exc.read()
        except Exception:
            pass
        return exc.code, dict(exc.headers.items()) if exc.headers else {}, body


def bootstrap_django():
    global _DJANGO_READY
    if _DJANGO_READY:
        return
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)
    if not os.environ.get("DJANGO_SETTINGS_MODULE"):
        manage_path = os.path.join(BASE_DIR, "manage.py")
        settings_mod = None
        if os.path.exists(manage_path):
            txt, _ = read_text_and_bom(manage_path)
            m = re.search(r"DJANGO_SETTINGS_MODULE['\"],\s*['\"]([^'\"]+)['\"]", txt)
            if m:
                settings_mod = m.group(1)
        os.environ["DJANGO_SETTINGS_MODULE"] = settings_mod or "core.settings"
    import django
    django.setup()
    _DJANGO_READY = True


class Report:
    def __init__(self):
        self.sections = []
        self._current = None

    def section(self, title):
        self._current = {"title": title, "items": []}
        self.sections.append(self._current)

    def run(self, code, desc, fn):
        try:
            status, detail = fn()
            if isinstance(status, bool):
                status = "PASS" if status else "FAIL"
            self._current["items"].append((code, desc, status, detail))
        except Exception as exc:
            self._current["items"].append((code, desc, "FAIL", f"{type(exc).__name__}: {exc}"))

    def print_summary(self):
        total = passed = warned = failed = 0
        print("\n" + "=" * 88)
        print("  LEBLIBRARY DEEP VERIFICATION REPORT")
        print("=" * 88)

        for sec in self.sections:
            print(f"\n--- {sec['title']} ---")
            for code, desc, status, detail in sec["items"]:
                total += 1
                if status == "PASS":
                    passed += 1
                    icon = "✅ PASS"
                elif status == "WARN":
                    warned += 1
                    icon = "⚠️ WARN"
                else:
                    failed += 1
                    icon = "❌ FAIL"
                print(f"{icon} | {code:<10} | {desc}")
                if detail and (status != "PASS" or detail.startswith("Note:")):
                    print(f"         └─ {detail}")

        print("\n" + "=" * 88)
        print(f"  SUMMARY: {passed}/{total} PASSED | {warned} WARNINGS | {failed} FAILED")
        print("=" * 88 + "\n")
        return failed == 0


# ============================================================================
# חלק א': קבצי ליבה בפייתון (views.py, torah_engine.py, core/urls.py)
# ============================================================================
def check_core_python_files(rep):
    rep.section("חלק א': קבצי ליבה בפייתון (views.py, torah_engine.py, core/urls.py)")

    def _chk_views():
        path = os.path.join(BASE_DIR, "articles", "views.py")
        if not os.path.exists(path):
            return False, "articles/views.py לא נמצא"
        text, has_bom = read_text_and_bom(path)
        if has_bom:
            return False, "נמצא UTF-8 BOM בתחילת articles/views.py"
        tree = ast.parse(text, filename=path)
        fn_names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}

        required_fns = {
            "article_list", "article_detail", "connections_audit_view",
            "qa_list", "books", "book_detail", "advanced_search_view",
            "aramaic_translator_view", "aramaic_translate_api", "ai_open_search",
        }
        missing_fns = sorted(required_fns - fn_names)

        m_adv = re.search(r"def\s+advanced_search_view\s*\(request\):(?P<body>.*?)(?=\ndef\s+|\Z)", text, re.S)
        adv_body = m_adv.group("body") if m_adv else ""
        issues = []
        if missing_fns:
            issues.append(f"פונקציות חסרות: {', '.join(missing_fns)}")
        if any(tok in adv_body for tok in ("sync_script", "origFetch", "applyUrlStateToUiWithRetry", "<script>")):
            issues.append("advanced_search_view עדיין מזריק sync_script/origFetch ישן")
        if "articles/advanced_search.html" not in adv_body:
            issues.append("advanced_search_view לא מרנדר את articles/advanced_search.html")
        return len(issues) == 0, "; ".join(issues) or f"Note: {len(fn_names)} פונקציות תקינות"

    rep.run("CORE-01", "articles/views.py: שלמות פונקציות, AST תקין ו-advanced_search_view נקי", _chk_views)

    def _chk_torah_engine():
        path = os.path.join(BASE_DIR, "articles", "torah_engine.py")
        if not os.path.exists(path):
            return False, "articles/torah_engine.py לא נמצא"
        text, has_bom = read_text_and_bom(path)
        if has_bom:
            return False, "נמצא UTF-8 BOM בתחילת articles/torah_engine.py"
        tree = ast.parse(text, filename=path)
        fn_names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}

        required_fns = {
            "build_hebrew_fuzzy_patterns",
            "build_hebrew_fuzzy_morph_patterns",
            "_build_sql_bigram_q_for_stem",
            "_build_fuzzy_sql_filter_for_word",
            "tanakh_advanced_search_api",
        }
        issues = []
        missing_fns = sorted(required_fns - fn_names)
        if missing_fns:
            issues.append(f"פונקציות חסרות: {', '.join(missing_fns)}")
        if "import hashlib" not in text or "hashlib.md5" not in text:
            issues.append("חסר hashlib.md5 למפתח הקאש (עלול לגרום ל-CacheKeyWarning)")
        if "text_fuzzy_morph" not in text or "include_plural" not in text:
            issues.append("חסרה תמיכה ב-text_fuzzy_morph / include_plural")
        if "'יי'" not in text or "'וו'" not in text:
            issues.append("חסרה תמיכה באמות קריאה כפולות (יי/וו) במסנן ה-SQL")
        return len(issues) == 0, "; ".join(issues)

    rep.run("CORE-02", "articles/torah_engine.py: מלא/חסר + יחיד/רבים, אמות כפולות וקאש MD5", _chk_torah_engine)

    def _chk_core_urls():
        path = os.path.join(BASE_DIR, "core", "urls.py")
        if not os.path.exists(path):
            return False, "core/urls.py לא נמצא"
        text, has_bom = read_text_and_bom(path)
        if has_bom:
            return False, "נמצא UTF-8 BOM בתחילת core/urls.py"
        ast.parse(text, filename=path)

        required_tokens = [
            ("def robots_txt(", "פונקציית robots_txt"),
            ("def manifest_json(", "פונקציית manifest_json"),
            ("def llms_full_txt(", "פונקציית llms_full_txt"),
            ("Allow: /api/ai-search/", "פתיחת /api/ai-search/ ב-robots_txt"),
            ("Disallow: /connections-audit/", "חסימת /connections-audit/ ב-robots_txt"),
            ("sw.js", "הגשת sw.js דרך TemplateView"),
            ("assetlinks.json", "הגשת assetlinks.json דרך TemplateView"),
            ("humans.txt", "הגשת humans.txt דרך TemplateView"),
            ("https://leblibrary.co.il/index/", "קישור /index/ תקין ב-llms.txt"),
            ("https://leblibrary.co.il/aramaic-translator/", "קישור מתרגם ארמי ב-llms.txt"),
            ("יחיד/רבים", "אזכור מצב יחיד/רבים ב-llms.txt"),
            ("IDENTITY DISAMBIGUATION", "הנחיות בידול זהות ל-AI"),
        ]
        issues = [label for tok, label in required_tokens if tok not in text]
        if '"wakelock"' in text or "'wakelock'" in text:
            issues.append("שדה לא תקני wakelock עדיין קיים ב-manifest_json")
        if '"iarc_rating_id"' in text or "'iarc_rating_id'" in text:
            issues.append("שדה ריק iarc_rating_id עדיין קיים ב-manifest_json")
        return len(issues) == 0, "; ".join(issues)

    rep.run("CORE-03", "core/urls.py: robots, manifest, llms, llms-full, sw.js ו-assetlinks", _chk_core_urls)


# ============================================================================
# חלק ב': תבניות HTML, PWA, SEO, תצורה וניקיון קבצים
# ============================================================================
def check_templates_and_assets(rep):
    rep.section("חלק ב': תבניות HTML, PWA, SEO, תצורה וניקיון פרויקט")

    def _chk_adv_search_html():
        path = os.path.join(BASE_DIR, "articles", "templates", "articles", "advanced_search.html")
        if not os.path.exists(path):
            return False, "articles/templates/articles/advanced_search.html לא נמצא"
        text, has_bom = read_text_and_bom(path)
        if has_bom:
            return False, "נמצא UTF-8 BOM"
        required = [
            ("data-action=\"text_fuzzy_morph\"", "כרטיס הפעולה החדש מלא/חסר + יחיד/רבים"),
            ("'text_fuzzy_morph': 'text_fuzzy_morph'", "מיפוי text_fuzzy_morph ב-normalizeActionType"),
            ("normalizeActionType", "נירמול סוג פעולה"),
            ("setActiveActionCard", "סימון כרטיס פעולה"),
            ("syncBrowserUrlFromState", "סנכרון URL"),
            ("restoreExcludeBooksInSelect", "שחזור החרגת ספרים"),
            ("applyUrlStateToUiWithRetry", "שחזור מלא בטעינה"),
            ("fetchAllResultsForExport", "ייצוא והעתקת כל התוצאות (LEB-UI-24)"),
            ("cleanCopiedTorahText", "ניקוי תוויות בהעתקת פרק מלא (LEB-UI-18)"),
            ("initSearchCardsKeyboardA11y", "נגישות מקלדת לכרטיסים (LEB-UI-25)"),
            ("tabParam === 'acronyms'", "פתיחה ישירה ללשונית ר\"ת"),
        ]
        issues = [label for tok, label in required if tok not in text]
        o_sc, c_sc = len(re.findall(r"<script\b", text, re.I)), len(re.findall(r"</script>", text, re.I))
        if o_sc != c_sc:
            issues.append(f"חוסר איזון בתגיות <script> ({o_sc} מול {c_sc})")
        return len(issues) == 0, "; ".join(issues)

    rep.run("TPL-01", "advanced_search.html: כרטיס יחיד/רבים + URL טבעי + QA מוטמע", _chk_adv_search_html)

    def _chk_conn_audit_html():
        path = os.path.join(BASE_DIR, "articles", "templates", "articles", "connections_audit.html")
        if not os.path.exists(path):
            return False, "articles/templates/articles/connections_audit.html לא נמצא"
        text, has_bom = read_text_and_bom(path)
        if has_bom:
            return False, "נמצא UTF-8 BOM"
        required = [
            ("value=\"search_fuzzy_morph\"", "אפשרות כתיב מלא/חסר + יחיד/רבים במודאל"),
            ("'search_fuzzy_morph': ['text_fuzzy_morph'", "מיפוי search_fuzzy_morph -> text_fuzzy_morph"),
            ("ed-tool-subtitle", "הצגת תת-כותרת ותנאי חיפוש"),
            ("{{ t.subtitle }}", "רינדור t.subtitle"),
            ("auditTableQuickSearch", "תיבת איתור מהיר בטבלה"),
            ("applyAuditTableFilters", "סינון משולב"),
            ("updateStatusCounters", "עדכון מונים בזמן אמת"),
            ("tool-live-preview-card", "תצוגה מקדימה חיה"),
            ("syncLiveToolPreviewFromInputs", "סנכרון תצוגה מקדימה"),
            ("'search_rashei': ['acronym'", "פרמטר acronym לראשי תיבות"),
            ("document.getElementById('auditTbQuery').value = ''", "איפוס שדה החיפוש בפתיחה"),
        ]
        issues = [label for tok, label in required if tok not in text]
        if "|| 'חזקה'" in text:
            issues.append("ברירת המחדל הישנה 'חזקה' עדיין קיימת")
        o_sc, c_sc = len(re.findall(r"<script\b", text, re.I)), len(re.findall(r"</script>", text, re.I))
        if o_sc != c_sc:
            issues.append(f"חוסר איזון בתגיות <script> ({o_sc} מול {c_sc})")
        return len(issues) == 0, "; ".join(issues)

    rep.run("TPL-02", "connections_audit.html: יחיד/רבים, תת-כותרות, תצוגה מקדימה ואיפוס", _chk_conn_audit_html)

    def _chk_sw():
        path = os.path.join(BASE_DIR, "articles", "templates", "sw.js")
        if not os.path.exists(path):
            return False, "articles/templates/sw.js לא נמצא"
        text, has_bom = read_text_and_bom(path)
        issues = []
        if has_bom:
            issues.append("נמצא UTF-8 BOM")
        if "leblibrary-cache-v4" not in text:
            issues.append("שם הקאש אינו leblibrary-cache-v4")
        if text.count("{") != text.count("}") or text.count("(") != text.count(")"):
            issues.append("חוסר איזון בסוגריים ב-JS")
        for tok, label in [
            ("caches.delete", "מחיקת קאש ישן ב-activate"),
            ("url.origin !== self.location.origin", "התעלמות מדומיינים חיצוניים"),
            ("/admin/", "החרגת /admin/"),
            ("/api/", "החרגת /api/"),
            ("/cart/", "החרגת /cart/"),
            ("/checkout/", "החרגת /checkout/"),
            ("/connections-audit/", "החרגת /connections-audit/"),
            ("/media/", "החרגת /media/"),
            ("networkResponse.ok", "בדיקת תגובה תקינה לפני שמירה בקאש"),
        ]:
            if tok not in text:
                issues.append(f"חסר {label}")
        return len(issues) == 0, "; ".join(issues)

    rep.run("PWA-01", "articles/templates/sw.js: גרסת v4, Network-First והחרגת נתיבים רגישים", _chk_sw)

    def _chk_assetlinks():
        files = find_project_files("assetlinks.json")
        if not files:
            return False, "assetlinks.json לא נמצא בפרויקט"
        issues = []
        for p in files:
            txt, has_bom = read_text_and_bom(p)
            rp = relpath(p)
            if has_bom:
                issues.append(f"{rp}: UTF-8 BOM")
            data = json.loads(txt)
            if not isinstance(data, list) or not data:
                issues.append(f"{rp}: חייב להיות מערך JSON לא ריק")
                continue
            pkgs = set()
            for entry in data:
                target = entry.get("target", {})
                pkg = target.get("package_name", "")
                pkgs.add(pkg)
                fps = target.get("sha256_cert_fingerprints", [])
                if not fps:
                    issues.append(f"{rp}: חסרות טביעות SHA-256 עבור {pkg}")
                for fp in fps:
                    if not SHA256_RE.match(str(fp)):
                        issues.append(f"{rp}: טביעת SHA-256 לא תקינה ({fp})")
            if "il.co.leblibrary.v2" not in pkgs:
                issues.append(f"{rp}: חסר il.co.leblibrary.v2")
        return len(issues) == 0, "; ".join(issues) or f"Note: {', '.join(relpath(x) for x in files)}"

    rep.run("PWA-02", "assetlinks.json: JSON תקין, חבילת v2 וטביעות SHA-256 מאומתות", _chk_assetlinks)

    def _chk_icons():
        missing = [ic for ic in ("icon-192x192.png", "icon-512x512.png") if not find_project_files(ic)]
        return len(missing) == 0, f"אייקונים חסרים: {', '.join(missing)}" if missing else ""

    rep.run("PWA-03", "קבצי אייקוני PWA (icon-192x192.png ו-icon-512x512.png) קיימים בדיסק", _chk_icons)

    def _chk_humans():
        path = os.path.join(BASE_DIR, "articles", "templates", "humans.txt")
        if not os.path.exists(path):
            return False, "articles/templates/humans.txt לא נמצא"
        txt, has_bom = read_text_and_bom(path)
        issues = []
        if has_bom:
            issues.append("UTF-8 BOM")
        for tok in ("LebLibrary", "leblibrary.co.il", "Advanced Torah Search Engine", "Aramaic Translator"):
            if tok not in txt:
                issues.append(f"חסר '{tok}'")
        return len(issues) == 0, "; ".join(issues)

    rep.run("SEO-01", "articles/templates/humans.txt: מעודכן וללא BOM", _chk_humans)

    def _chk_pytest_ini():
        path = os.path.join(BASE_DIR, "pytest.ini")
        if not os.path.exists(path):
            return False, "pytest.ini לא נמצא בתיקייה הראשית"
        txt, has_bom = read_text_and_bom(path)
        if has_bom:
            return False, "נמצא UTF-8 BOM ב-pytest.ini"
        cp = configparser.ConfigParser()
        cp.read_string(txt)
        if "pytest" not in cp:
            return False, "חסר מקטע [pytest]"
        sec = cp["pytest"]
        settings_val = sec.get("DJANGO_SETTINGS_MODULE", "").strip()
        if not settings_val:
            return False, "חסר DJANGO_SETTINGS_MODULE"
        manage_path = os.path.join(BASE_DIR, "manage.py")
        if os.path.exists(manage_path):
            m_txt, _ = read_text_and_bom(manage_path)
            m = re.search(r"DJANGO_SETTINGS_MODULE['\"],\s*['\"]([^'\"]+)['\"]", m_txt)
            if m and m.group(1) != settings_val:
                return False, f"אי-התאמה ל-manage.py ({settings_val} != {m.group(1)})"
        if "venv" not in sec.get("norecursedirs", ""):
            return False, "חסר החרגת venv ב-norecursedirs"
        addopts = sec.get("addopts", "")
        if "--reuse-db" in addopts:
            try:
                import pytest_django  # noqa: F401
            except ImportError:
                return "WARN", "מוגדר --reuse-db ב-pytest.ini אבל pytest-django לא מותקן בסביבה הנוכחית"
        return True, f"Note: DJANGO_SETTINGS_MODULE={settings_val}"

    rep.run("CFG-01", "pytest.ini: תקין, תואם ל-manage.py ומחריג venv", _chk_pytest_ini)

    def _chk_cleanliness():
        leftovers = []
        dead_candidates = [
            "articles/static/service-worker.js",
            "articles/static/manifest.json",
            "articles/templates/manifest.json",
            "oauth.yml",
        ]
        for rel in dead_candidates:
            if os.path.exists(os.path.join(BASE_DIR, rel)):
                leftovers.append(f"קובץ כפול/לא פעיל: {rel}")

        stray_drafts = {
            "service-worker_js.txt", "manifest_json.txt", "style_css.txt",
            "oauth_yml.txt", "pytest_ini.txt", "sw_js.txt",
            "בדיקת הקבצים הקטנים.txt", "להרצת בדיקה.txt", "להריץ.txt",
        }
        for name in stray_drafts:
            for p in find_project_files(name):
                leftovers.append(f"קובץ טיוטה: {relpath(p)}")

        for p in find_project_files("style.css"):
            txt, _ = read_text_and_bom(p)
            if "1380px" in txt:
                leftovers.append(f"style.css ישן עם 1380px ({relpath(p)})")

        if leftovers:
            return "WARN", " | ".join(leftovers)
        return True, ""

    rep.run("CLEAN-01", "ניקיון ריפוזיטורי: אין קבצים כפולים ישנים או פתקי טיוטה", _chk_cleanliness)


# ============================================================================
# חלק ג': בדיקות אלגוריתם מתמטיות + Django Runtime מלא מול מסד הנתונים
# ============================================================================
def check_algorithm_and_django_runtime(rep, is_offline=False):
    rep.section("חלק ג': בדיקות אלגוריתם מתמטיות + Django Runtime מלא")

    def _chk_math_fuzzy_engine():
        bootstrap_django()
        from articles.torah_engine import build_hebrew_fuzzy_patterns, build_hebrew_fuzzy_morph_patterns

        # 1. Superset invariant: every word must match itself in both modes
        tricky_words = [
            "שהחיינו", "שהחינו", "האב", "מברך", "מצוות", "מצות", "מצוה", "מצווה",
            "דיינים", "דינים", "עניינים", "ענינים", "בניין", "בנין", "קניין", "קנין",
            "ציווי", "ציוי", "מכוונים", "מכונים", "עוונות", "עונות", "חייבים", "חיבים",
            "שואלין", "שואלים", "שואלי", "שואל", "גשמים", "גשם", "בראשית", "יהוה",
            "תפילה", "תפלה", "זכויות", "זכות", "קורבן", "קרבן", "שבת", "קללות",
        ]
        issues = []
        for w in tricky_words:
            _, rx_f = build_hebrew_fuzzy_patterns(w)
            _, rx_m = build_hebrew_fuzzy_morph_patterns(w)
            if not rx_f or not rx_f.match(w):
                issues.append(f"text_fuzzy לא מתאים לעצמו עבור '{w}'")
            if not rx_m or not rx_m.match(w):
                issues.append(f"text_fuzzy_morph לא מתאים לעצמו עבור '{w}'")

        # 2. Bi-directional double matres & complex prefixes
        pair_checks = [
            ("שהחיינו", ["שהחיינו", "שהחינו", "ושהחיינו"]),
            ("שהחינו", ["שהחיינו", "שהחינו", "ושהחיינו"]),
            ("מצוות", ["מצוות", "מצות", "המצוות", "במצות"]),
            ("מצות", ["מצוות", "מצות", "המצוות", "במצות"]),
            ("דינים", ["דיינים", "דינים", "הדיינים"]),
            ("ענינים", ["עניינים", "ענינים", "בעניינים"]),
            ("האב", ["האב", "והאב", "כשהאב"]),
        ]
        for q, targets in pair_checks:
            _, rx_f = build_hebrew_fuzzy_patterns(q)
            _, rx_m = build_hebrew_fuzzy_morph_patterns(q)
            for t in targets:
                if not rx_f.match(t):
                    issues.append(f"text_fuzzy: '{q}' פספס '{t}'")
                if not rx_m.match(t):
                    issues.append(f"text_fuzzy_morph: '{q}' פספס '{t}'")

        # 3. Clean separation between basic fuzzy and morph fuzzy
        _, rx_basic_shoali = build_hebrew_fuzzy_patterns("שואלי")
        if rx_basic_shoali.match("ושואלין"):
            issues.append("text_fuzzy (בלי יחיד/רבים) התאים בטעות 'שואלי' ל-'ושואלין'")

        morph_checks = [
            ("שואלי", ["שואל", "שואלים", "שואלין", "ושואלין", "שואלות"], ["שולח"]),
            ("גשמים", ["גשם", "הגשם", "גשמים", "הגשמים", "גשמין", "גשמי"], ["גוש"]),
            ("קללה", ["קללה", "קללת", "קללות", "הקללות"], ["קלל"]),
            ("זכות", ["זכות", "זכויות", "הזכויות"], ["זך"]),
            ("מצוה", ["מצוה", "מצווה", "מצות", "מצוות"], ["מצה"]),
        ]
        for q, pos_list, neg_list in morph_checks:
            _, rx_m = build_hebrew_fuzzy_morph_patterns(q)
            for p_w in pos_list:
                if not rx_m.match(p_w):
                    issues.append(f"morph: '{q}' פספס '{p_w}'")
            for n_w in neg_list:
                if rx_m.match(n_w):
                    issues.append(f"morph: '{q}' תפס התאמת שווא '{n_w}'")

        return len(issues) == 0, "; ".join(issues[:6])

    rep.run("MATH-01", "מנוע Regex: הכלה מלאה (40 מילים), אמות כפולות והפרדת יחיד/רבים", _chk_math_fuzzy_engine)

    def _chk_django_dynamic_endpoints():
        bootstrap_django()
        from django.test import Client

        client = Client(HTTP_HOST="leblibrary.co.il")
        issues = []

        # robots.txt (secure=True כדי למנוע הפניית 301 מ-SECURE_SSL_REDIRECT)
        r = client.get("/robots.txt", secure=True)
        r_txt = r.content.decode("utf-8", errors="replace")
        if r.status_code != 200 or "Allow: /api/ai-search/" not in r_txt or "Disallow: /connections-audit/" not in r_txt:
            issues.append(f"/robots.txt לא תקין (HTTP {r.status_code})")

        # manifest.json
        m = client.get("/manifest.json", secure=True)
        if m.status_code != 200:
            issues.append(f"/manifest.json החזיר HTTP {m.status_code}")
        else:
            m_data = json.loads(m.content.decode("utf-8"))
            if m_data.get("scope") != "/" or "wakelock" in m_data or "iarc_rating_id" in m_data:
                issues.append("/manifest.json חסר scope או מכיל שדות ישנים")
            if len(m_data.get("shortcuts", [])) < 2:
                issues.append("/manifest.json חסר shortcuts")

        # llms.txt & llms-full.txt
        l1 = client.get("/llms.txt", secure=True)
        l1_txt = l1.content.decode("utf-8", errors="replace")
        if l1.status_code != 200 or "IDENTITY DISAMBIGUATION" not in l1_txt or "/index/" not in l1_txt or "יחיד/רבים" not in l1_txt:
            issues.append(f"/llms.txt חסר תוכן מעודכן (HTTP {l1.status_code})")

        l2 = client.get("/llms-full.txt", secure=True)
        l2_txt = l2.content.decode("utf-8", errors="replace")
        if l2.status_code != 200 or "IDENTITY DISAMBIGUATION" not in l2_txt:
            issues.append(f"/llms-full.txt לא תקין (HTTP {l2.status_code})")

        # sw.js, service-worker.js, humans.txt, assetlinks.json
        for ep, expected_tok in [
            ("/sw.js", "leblibrary-cache-v4"),
            ("/service-worker.js", "leblibrary-cache-v4"),
            ("/humans.txt", "Aramaic Translator"),
            ("/.well-known/assetlinks.json", "il.co.leblibrary.v2"),
        ]:
            resp = client.get(ep, secure=True)
            body = resp.content.decode("utf-8", errors="replace")
            if resp.status_code != 200 or expected_tok not in body:
                issues.append(f"{ep} נכשל (HTTP {resp.status_code})")

        return len(issues) == 0, "; ".join(issues)

    rep.run("DJ-01", "Django Client: כל 8 נקודות הקצה (robots, manifest, sw, llms, humans, assetlinks)", _chk_django_dynamic_endpoints)

    def _chk_django_adv_view():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.views import advanced_search_view

        rf = RequestFactory()
        try:
            resp = advanced_search_view(
                rf.get("/advanced-search/?q=שואלי גשמים&type=text_fuzzy_morph&book=mishnah", HTTP_HOST="leblibrary.co.il")
            )
        except ValueError as exc:
            if is_offline and "Missing staticfiles manifest entry" in str(exc):
                return "WARN", f"סביבה מקומית בלי collectstatic עדכני ({exc}) — יאומת בשרת Ubuntu"
            raise
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        html = resp.content.decode("utf-8")
        if "origFetch" in html:
            return False, "advanced_search_view עדיין מכיל origFetch מוזרק"
        if "text_fuzzy_morph" not in html or "normalizeActionType" not in html:
            return False, "חסרים מנגנוני text_fuzzy_morph או normalizeActionType בעמוד"
        return True, ""

    rep.run("DJ-02", "Django advanced_search_view: HTTP 200, ללא origFetch וכולל text_fuzzy_morph", _chk_django_adv_view)

    def _chk_django_shehecheyanu_superset():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.models import TorahText
        from articles.torah_engine import tanakh_advanced_search_api

        if is_offline and not TorahText.objects.filter(book__startswith="שולחן ערוך ").exists():
            return "WARN", "מסד הנתונים המקומי אינו מכיל שולחן ערוך — ייבדק במלואו בשרת Ubuntu"

        rf = RequestFactory()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            totals = {}
            for t in ("text_exact", "text_fuzzy", "text_fuzzy_morph"):
                r = tanakh_advanced_search_api(
                    rf.get(f"/api/tanakh-search/?q=האב מברך שהחיינו&type={t}&book=shulchan_aruch", HTTP_HOST="leblibrary.co.il")
                )
                if r.status_code != 200:
                    return False, f"type={t} החזיר HTTP {r.status_code}"
                totals[t] = json.loads(r.content.decode("utf-8")).get("total", 0)

            r_def = tanakh_advanced_search_api(
                rf.get("/api/tanakh-search/?q=האב מברך שהחינו&type=text_fuzzy&book=shulchan_aruch", HTTP_HOST="leblibrary.co.il")
            )
            def_total = json.loads(r_def.content.decode("utf-8")).get("total", 0)

        cache_warns = [w for w in caught if "CacheKeyWarning" in str(w.category.__name__)]
        issues = []
        if totals["text_exact"] < 1:
            issues.append(f"text_exact החזיר {totals['text_exact']} (צפוי >= 1)")
        if totals["text_fuzzy"] < totals["text_exact"]:
            issues.append(f"הפרת הכלה: text_fuzzy ({totals['text_fuzzy']}) < text_exact ({totals['text_exact']})")
        if totals["text_fuzzy_morph"] < totals["text_fuzzy"]:
            issues.append(f"הפרת הכלה: text_fuzzy_morph ({totals['text_fuzzy_morph']}) < text_fuzzy ({totals['text_fuzzy']})")
        if def_total < 1:
            issues.append(f"כתיב חסר 'שהחינו' החזיר 0 תוצאות (צפוי >= 1)")
        if cache_warns:
            issues.append(f"התקבלו {len(cache_warns)} אזהרות CacheKeyWarning")

        note = f"Note: exact={totals['text_exact']}, fuzzy={totals['text_fuzzy']}, morph={totals['text_fuzzy_morph']}, defective(שהחינו)={def_total}"
        return len(issues) == 0, "; ".join(issues) or note

    rep.run("DJ-03", "DB API: 'האב מברך שהחיינו'/'שהחינו' בשו\"ע (הכלה מלאה + ללא CacheKeyWarning)", _chk_django_shehecheyanu_superset)

    def _chk_django_shoali_geshamim():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.models import TorahText
        from articles.torah_engine import tanakh_advanced_search_api

        if is_offline and not TorahText.objects.filter(book="ברכות").exists():
            return "WARN", "מסד הנתונים המקומי אינו מכיל משנה/ירושלמי — ייבדק במלואו בשרת Ubuntu"

        rf = RequestFactory()
        r_basic = json.loads(tanakh_advanced_search_api(
            rf.get("/api/tanakh-search/?q=שואלי גשמים&type=text_fuzzy&book=mishnah,yerushalmi", HTTP_HOST="leblibrary.co.il")
        ).content.decode("utf-8"))
        r_morph = json.loads(tanakh_advanced_search_api(
            rf.get("/api/tanakh-search/?q=שואלי גשמים&type=text_fuzzy_morph&book=mishnah,yerushalmi", HTTP_HOST="leblibrary.co.il")
        ).content.decode("utf-8"))
        r_flag = json.loads(tanakh_advanced_search_api(
            rf.get("/api/tanakh-search/?q=שואלי גשמים&type=text_fuzzy&include_plural=true&book=mishnah,yerushalmi", HTTP_HOST="leblibrary.co.il")
        ).content.decode("utf-8"))

        t_basic, t_morph, t_flag = r_basic.get("total", -1), r_morph.get("total", -1), r_flag.get("total", -1)
        issues = []
        if t_basic != 0:
            issues.append(f"text_fuzzy (בלי יחיד/רבים) צפוי 0, התקבל {t_basic}")
        if t_morph < 2:
            issues.append(f"text_fuzzy_morph צפוי >= 2, התקבל {t_morph}")
        if t_flag != t_morph:
            issues.append(f"include_plural=true ({t_flag}) שונה מ-text_fuzzy_morph ({t_morph})")
        return len(issues) == 0, "; ".join(issues) or f"Note: fuzzy={t_basic}, morph={t_morph}, include_plural={t_flag}"

    rep.run("DJ-04", "DB API: 'שואלי גשמים' במשנה וירושלמי (הפרדת text_fuzzy מול text_fuzzy_morph)", _chk_django_shoali_geshamim)

    def _chk_django_bereshit_and_shema():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.models import TorahText
        from articles.torah_engine import tanakh_advanced_search_api

        has_mishnah_local = TorahText.objects.filter(book="ברכות").exclude(chapter__startswith="דף").exists()

        rf = RequestFactory()
        b_exact = json.loads(tanakh_advanced_search_api(
            rf.get("/api/tanakh-search/?q=בראשית&type=text_exact&book=torah", HTTP_HOST="leblibrary.co.il")
        ).content.decode("utf-8")).get("total", 0)
        b_fuzzy = json.loads(tanakh_advanced_search_api(
            rf.get("/api/tanakh-search/?q=בראשית&type=text_fuzzy&book=torah", HTTP_HOST="leblibrary.co.il")
        ).content.decode("utf-8")).get("total", 0)
        m_shema = json.loads(tanakh_advanced_search_api(
            rf.get("/api/tanakh-search/?q=שמע&type=text_fuzzy&book=mishnah", HTTP_HOST="leblibrary.co.il")
        ).content.decode("utf-8")).get("total", 0)

        issues = []
        if b_exact < 1 or b_fuzzy < b_exact:
            issues.append(f"בראשית בתורה: exact={b_exact}, fuzzy={b_fuzzy}")
        if m_shema < 1:
            if is_offline and not has_mishnah_local:
                return "WARN", f"בראשית בתורה עבר (exact={b_exact}, fuzzy={b_fuzzy}); משנה אינה במסד המקומי — תיבדק בשרת Ubuntu"
            issues.append(f"שמע במשנה: fuzzy={m_shema}")
        return len(issues) == 0, "; ".join(issues) or f"Note: בראשית(exact={b_exact}, fuzzy={b_fuzzy}), שמע(mishnah={m_shema})"

    rep.run("DJ-05", "DB API: 'בראשית' בתורה (אות רבתי) + 'שמע' במשנה", _chk_django_bereshit_and_shema)


# ============================================================================
# חלק ד': בדיקות HTTP חיות מול השרת (https://leblibrary.co.il)
# ============================================================================
def check_live_production(rep):
    rep.section(f"חלק ד': בדיקות HTTP חיות מול שרת הייצור ({LIVE_ORIGIN})")

    def _live_robots():
        code, _, body = fetch_live("/robots.txt")
        txt = body.decode("utf-8", errors="replace")
        if code != 200:
            return False, f"HTTP {code}"
        for tok in ("Allow: /api/ai-search/", "Disallow: /connections-audit/", "User-agent: GPTBot", "Sitemap: https://leblibrary.co.il/sitemap.xml"):
            if tok not in txt:
                return False, f"חסר '{tok}' ב-/robots.txt החי"
        if txt.count("Disallow: /api/") > 1:
            return False, "שורה כפולה Disallow: /api/"
        return True, ""

    rep.run("LIVE-01", "GET /robots.txt -> HTTP 200 ותוכן מעודכן", _live_robots)

    def _live_manifest():
        code, _, body = fetch_live("/manifest.json")
        if code != 200:
            return False, f"HTTP {code}"
        data = json.loads(body.decode("utf-8"))
        if data.get("scope") != "/" or "wakelock" in data or "iarc_rating_id" in data:
            return False, "השרת עדיין מגיש manifest.json ישן"
        if len(data.get("shortcuts", [])) < 2:
            return False, "חסר shortcuts ב-/manifest.json החי"
        for ic in ("/static/images/icon-192x192.png", "/static/images/icon-512x512.png"):
            ic_code, _, _ = fetch_live(ic)
            if ic_code != 200:
                return False, f"{ic} החזיר HTTP {ic_code}"
        return True, ""

    rep.run("LIVE-02", "GET /manifest.json + אייקוני 192x192 ו-512x512 -> HTTP 200", _live_manifest)

    def _live_sw():
        issues = []
        for ep in ("/sw.js", "/service-worker.js"):
            code, headers, body = fetch_live(ep)
            txt = body.decode("utf-8", errors="replace")
            if code != 200:
                issues.append(f"{ep} -> HTTP {code}")
                continue
            if "leblibrary-cache-v4" not in txt or "/connections-audit/" not in txt:
                issues.append(f"{ep} עדיין מגיש גרסה ישנה")
            ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
            if "javascript" not in ctype:
                issues.append(f"{ep} Content-Type='{ctype}'")
        return len(issues) == 0, "; ".join(issues)

    rep.run("LIVE-03", "GET /sw.js ו-/service-worker.js -> HTTP 200, JS וגרסת v4", _live_sw)

    def _live_texts():
        issues = []
        for path, must_have in [
            ("/humans.txt", "Aramaic Translator"),
            ("/llms.txt", "https://leblibrary.co.il/index/"),
            ("/llms.txt", "יחיד/רבים"),
            ("/llms-full.txt", "IDENTITY DISAMBIGUATION"),
            ("/index/", "מאמר"),
        ]:
            code, _, body = fetch_live(path)
            if code != 200:
                issues.append(f"{path} -> HTTP {code}")
                continue
            txt = body.decode("utf-8", errors="replace")
            if must_have not in txt:
                issues.append(f"{path}: לא נמצא '{must_have}'")
        return len(issues) == 0, "; ".join(issues)

    rep.run("LIVE-04", "GET /humans.txt, /llms.txt, /llms-full.txt, /index/ -> HTTP 200 ומעודכנים", _live_texts)

    def _live_assetlinks():
        code, headers, body = fetch_live("/.well-known/assetlinks.json", allow_redirects=False)
        if code != 200:
            loc = headers.get("Location") or headers.get("location") or ""
            return False, f"HTTP {code} (חייב 200 ישיר ללא הפניה; Location='{loc}')"
        ctype = (headers.get("Content-Type") or headers.get("content-type") or "").lower()
        if "application/json" not in ctype:
            return False, f"Content-Type='{ctype}' במקום application/json"
        data = json.loads(body.decode("utf-8"))
        pkgs = [x.get("target", {}).get("package_name") for x in data if isinstance(x, dict)]
        if "il.co.leblibrary.v2" not in pkgs:
            return False, f"il.co.leblibrary.v2 חסר ({pkgs})"
        return True, ""

    rep.run("LIVE-05", "GET /.well-known/assetlinks.json -> HTTP 200 ישיר + application/json", _live_assetlinks)

    def _live_adv_search_page():
        q = urllib.parse.quote("שואלי גשמים")
        code, _, body = fetch_live(f"/advanced-search/?q={q}&type=text_fuzzy_morph&book=mishnah")
        if code != 200:
            return False, f"HTTP {code}"
        html = body.decode("utf-8", errors="replace")
        if "origFetch" in html:
            return False, "עדיין מוגש origFetch מ-views.py ישן"
        if "text_fuzzy_morph" not in html or "normalizeActionType" not in html:
            return False, "השרת עדיין מגיש advanced_search.html ישן"
        return True, ""

    rep.run("LIVE-06", "GET /advanced-search/?type=text_fuzzy_morph -> גרסה חדשה ללא origFetch", _live_adv_search_page)

    def _live_api_shehecheyanu():
        q_full = urllib.parse.quote("האב מברך שהחיינו")
        q_def = urllib.parse.quote("האב מברך שהחינו")
        totals = {}
        for t in ("text_exact", "text_fuzzy", "text_fuzzy_morph"):
            code, _, body = fetch_live(f"/api/tanakh-search/?q={q_full}&type={t}&book=shulchan_aruch")
            if code != 200:
                return False, f"type={t} -> HTTP {code}"
            totals[t] = json.loads(body.decode("utf-8")).get("total", 0)
        code_d, _, body_d = fetch_live(f"/api/tanakh-search/?q={q_def}&type=text_fuzzy&book=shulchan_aruch")
        if code_d != 200:
            return False, f"defective שהחינו -> HTTP {code_d}"
        def_t = json.loads(body_d.decode("utf-8")).get("total", 0)

        if totals["text_exact"] < 1 or totals["text_fuzzy"] < totals["text_exact"] or totals["text_fuzzy_morph"] < totals["text_fuzzy"] or def_t < 1:
            return False, f"exact={totals['text_exact']}, fuzzy={totals['text_fuzzy']}, morph={totals['text_fuzzy_morph']}, defective={def_t}"
        return True, f"Note: exact={totals['text_exact']}, fuzzy={totals['text_fuzzy']}, morph={totals['text_fuzzy_morph']}, defective={def_t}"

    rep.run("LIVE-07", "Live API: 'האב מברך שהחיינו'/'שהחינו' בשו\"ע (הכלה + אמות כפולות)", _live_api_shehecheyanu)

    def _live_api_shoali():
        q = urllib.parse.quote("שואלי גשמים")
        c1, _, b1 = fetch_live(f"/api/tanakh-search/?q={q}&type=text_fuzzy&book=mishnah,yerushalmi")
        c2, _, b2 = fetch_live(f"/api/tanakh-search/?q={q}&type=text_fuzzy_morph&book=mishnah,yerushalmi")
        if c1 != 200 or c2 != 200:
            return False, f"HTTP {c1}/{c2}"
        t1 = json.loads(b1.decode("utf-8")).get("total", -1)
        t2 = json.loads(b2.decode("utf-8")).get("total", -1)
        if t1 != 0 or t2 < 2:
            return False, f"fuzzy={t1} (צפוי 0), morph={t2} (צפוי >= 2)"
        return True, f"Note: fuzzy={t1}, morph={t2}"

    rep.run("LIVE-08", "Live API: 'שואלי גשמים' במשנה/ירושלמי (בלי יחיד/רבים=0, עם=2+)", _live_api_shoali)

    def _live_ai_search():
        q = urllib.parse.quote("תפילה")
        code, _, body = fetch_live(f"/api/ai-search/?q={q}")
        if code != 200:
            return False, f"HTTP {code}"
        data = json.loads(body.decode("utf-8"))
        if "meta" not in data or not isinstance(data.get("results"), list):
            return False, "מבנה JSON לא צפוי מ-/api/ai-search/"
        return True, f"Note: total_results={data.get('meta', {}).get('total_results')}"

    rep.run("LIVE-09", "Live API: GET /api/ai-search/?q=תפילה -> HTTP 200 ו-JSON תקין", _live_ai_search)


def main():
    parser = argparse.ArgumentParser(description="LebLibrary Deep Verification Suite")
    parser.add_argument("--offline", action="store_true", help="דלג על בדיקות HTTP חיות מול https://leblibrary.co.il")
    args = parser.parse_args()

    rep = Report()
    check_core_python_files(rep)
    check_templates_and_assets(rep)
    check_algorithm_and_django_runtime(rep, is_offline=args.offline)
    if not args.offline:
        check_live_production(rep)

    all_ok = rep.print_summary()
    if not all_ok:
        sys.exit(1)


if __name__ == "__main__":
    main()