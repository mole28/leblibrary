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


_IPV4_OPENER = urllib.request.build_opener(_HTTPSHandlerIPv4())


def fetch_live(path, timeout=10):
    req = urllib.request.Request(LIVE_ORIGIN + path, headers={"User-Agent": "LebLibrary-QAVerifier/1.0"})
    try:
        with _IPV4_OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


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


def find_file(filename):
    skip = {"venv", ".venv", ".git", "staticfiles", "__pycache__", "media"}
    for root, dirs, files in os.walk(BASE_DIR):
        dirs[:] = [d for d in dirs if d not in skip]
        if filename in files:
            return os.path.join(root, filename)
    return None


def run_checks(offline=False):
    results = []

    def record(code, label, ok, detail=""):
        results.append((code, label, ok, detail))

    def chk_29_unit():
        bootstrap_django()
        from articles.torah_engine import calculate_gematria, strip_editorial_markers
        isaiah_1_9 = "\u05dc\u05d5\u05bc\u05dc\u05b5\u05d9 \u05d9\u05b0\u05d4\u05d5\u05b8\u05d4 \u05e6\u05b0\u05d1\u05b8\u05d0\u05d5\u05b9\u05ea \u05d4\u05d5\u05b9\u05ea\u05b4\u05d9\u05e8 \u05dc\u05b8\u05e0\u05d5\u05bc \u05e9\u05b8\u05c2\u05e8\u05b4\u05d9\u05d3 \u05db\u05b4\u05bc\u05de\u05b0\u05e2\u05b8\u05d8 \u05db\u05b4\u05bc\u05e1\u05b0\u05d3\u05b9\u05dd \u05d4\u05b8\u05d9\u05b4\u05d9\u05e0\u05d5\u05bc \u05dc\u05b7\u05e2\u05b2\u05de\u05b9\u05e8\u05b8\u05d4 \u05d3\u05b8\u05bc\u05de\u05b4\u05d9\u05e0\u05d5\u05bc\u05c3 {\u05e4}"
        gen_1_1 = "<big>\u05d1\u05b0\u05bc</big>\u05e8\u05b5\u05d0\u05e9\u05b4\u05c1\u05d9\u05ea \u05d1\u05b8\u05bc\u05e8\u05b8\u05d0 \u05d0\u05b1\u05dc\u05b9\u05d4\u05b4\u05d9\u05dd \u05d0\u05b5\u05ea \u05d4\u05b7\u05e9\u05b8\u05bc\u05c1\u05de\u05b7\u05d9\u05b4\u05dd \u05d5\u05b0\u05d0\u05b5\u05ea \u05d4\u05b8\u05d0\u05b8\u05e8\u05b6\u05e5\u05c3"
        g_isa = calculate_gematria(isaiah_1_9)
        g_gen = calculate_gematria(gen_1_1)
        g_setuma = calculate_gematria("\u05e9\u05dc\u05d5\u05dd {\u05e1}")
        ok = (g_isa == 2621 and g_gen == 2701 and g_setuma == 376 and "{\u05e4}" not in strip_editorial_markers(isaiah_1_9))
        return ok, f"isaiah={g_isa}, genesis={g_gen}, setuma={g_setuma}"

    ok, det = chk_29_unit()
    record("LEB-UI-29A", "Editorial markers stripped before gematria calculation", ok, det)

    def chk_29_db():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.ai_engine import torah_ai_insights_api
        from articles.torah_engine import calculate_gematria
        rf = RequestFactory()
        req = rf.get("/api/torah-ai-insights/?mode=code_finder&book=%D7%91%D7%A8%D7%90%D7%A9%D7%99%D7%AA&chapter=1&verse=1", HTTP_HOST="leblibrary.co.il")
        resp = torah_ai_insights_api(req)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        data = json.loads(resp.content.decode("utf-8"))
        if data.get("verse_gematria") != 2701:
            return False, f"verse_gematria={data.get('verse_gematria')}"
        bad = []
        for ev in data.get("equal_verses", []):
            ev_gem = calculate_gematria(ev.get("text", ""))
            if ev_gem != 2701 or ("\u05d9\u05e9\u05e2\u05d9\u05d4\u05d5" in ev.get("ref", "") and "1:" in ev.get("ref", "")):
                bad.append(f"{ev.get('ref')} ({ev_gem})")
        return len(bad) == 0, ", ".join(bad) or f"verified {len(data.get('equal_verses', []))} equal verses"

    ok, det = chk_29_db()
    record("LEB-UI-29B", "DB AI insights for Genesis 1:1 excludes Isaiah 1:9 and matches 2701 strictly", ok, det)

    def chk_30_unit():
        bootstrap_django()
        from articles.views import _build_clean_excerpt
        html1 = '<p>\u05d1\u05e2"\u05d4.</p><h2>\u05d2\u05d3\u05e8\u05d9 \u05d7\u05d6\u05e7\u05d4</h2><h3>\u05d0. \u05e9\u05d9\u05d8\u05ea \u05e8\u05e9"\u05d9</h3><p>\u05ea\u05e0\u05d9\' \u05ea\u05d9\u05e0\u05d5\u05e7</p>'
        html2 = '<h3>\u05d0\u05e8\u05e5 \u05d9\u05e9\u05e8\u05d0\u05dc</h3><p>\u05e0\u05d0\u05de\u05e8 \u05d1\u05d3\u05d1\u05e8\u05d9\u05dd</p>'
        e1 = _build_clean_excerpt(html1, 25)
        e2 = _build_clean_excerpt(html2, 25)
        ok = ("\u05d7\u05d6\u05e7\u05d4\u05d0." not in e1 and '\u05e8\u05e9"\u05d9\u05ea\u05e0\u05d9' not in e1 and "\u05d9\u05e9\u05e8\u05d0\u05dc\u05e0\u05d0\u05de\u05e8" not in e2)
        return ok, f"e1={e1[:45]}"

    ok, det = chk_30_unit()
    record("LEB-UI-30A", "Clean excerpt builder preserves spaces across HTML block boundaries", ok, det)

    def chk_26_static():
        path = os.path.join(BASE_DIR, "articles", "templates", "articles", "advanced_search.html")
        with open(path, "r", encoding="utf-8") as f:
            txt = f.read()
        tokens = ["captureModalReturnFocus", "showAccessibleModal", "__returnFocusEl", "hidden.bs.modal", "target.focus()"]
        missing = [t for t in tokens if t not in txt]
        return len(missing) == 0, ", ".join(missing)

    ok, det = chk_26_static()
    record("LEB-UI-26", "Modal focus capture and W3C H102 focus restoration in advanced_search.html", ok, det)

    def chk_28_static():
        scripts_path = None
        for candidate in ("scripts.html", "base.html"):
            p = find_file(candidate)
            if p:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    if "acronymDict" in f.read():
                        scripts_path = p
                        break
        if not scripts_path:
            return False, "scripts file containing acronymDict not found"
        with open(scripts_path, "r", encoding="utf-8") as f:
            txt = f.read()
        needed = ["resolveAcronymMeaning", "singleQuoteAllowedPrefixes", "\u05d1\u05e2\u05d9\\'", "\u05d1\u05e2\u05d9\u05e0\u05df"]
        missing = [t for t in needed if t not in txt]
        return len(missing) == 0, ", ".join(missing) or os.path.relpath(scripts_path, BASE_DIR)

    ok, det = chk_28_static()
    record("LEB-UI-28", "Aramaic acronym mapping and safe single-quote prefix rules", ok, det)

    if not offline:
        def chk_live_29():
            q = urllib.parse.urlencode({"mode": "code_finder", "book": "\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea", "chapter": "1", "verse": "1"})
            code, body = fetch_live(f"/api/torah-ai-insights/?{q}")
            if code != 200:
                return False, f"HTTP {code}"
            data = json.loads(body)
            refs = [ev.get("ref", "") for ev in data.get("equal_verses", [])]
            has_isaiah_1_9 = any("\u05d9\u05e9\u05e2\u05d9\u05d4\u05d5" in r and ("\u05d0:\u05d8" in r or "1:\u05d8" in r or "1:9" in r) for r in refs)
            return (data.get("verse_gematria") == 2701 and not has_isaiah_1_9), f"refs={refs}"

        ok, det = chk_live_29()
        record("LIVE-29", "Live API Genesis 1:1 code_finder excludes Isaiah 1:9", ok, det)

        def chk_live_30():
            code, body = fetch_live("/recently-added/")
            if code != 200:
                return False, f"HTTP {code}"
            glued = [s for s in ["\u05d7\u05d6\u05e7\u05d4\u05d0.", '\u05e8\u05e9"\u05d9\u05ea\u05e0\u05d9', "\u05d9\u05e9\u05e8\u05d0\u05dc\u05e0\u05d0\u05de\u05e8", '\u05d1\u05e2"\u05d4.\u05d2\u05d3\u05e8\u05d9'] if s in body]
            return len(glued) == 0, ", ".join(glued)

        ok, det = chk_live_30()
        record("LIVE-30", "Live /recently-added/ has no glued words across block boundaries", ok, det)

        def chk_live_26():
            code, body = fetch_live("/advanced-search/")
            if code != 200:
                return False, f"HTTP {code}"
            return ("showAccessibleModal" in body and "__returnFocusEl" in body), ""

        ok, det = chk_live_26()
        record("LIVE-26", "Live /advanced-search/ serves W3C H102 modal focus manager", ok, det)

        def chk_live_28():
            code, body = fetch_live("/article/63/")
            if code != 200:
                return False, f"HTTP {code}"
            return ("resolveAcronymMeaning" in body and "\u05d1\u05e2\u05d9\u05e0\u05df" in body), ""

        ok, det = chk_live_28()
        record("LIVE-28", "Live /article/63/ serves Aramaic expansion for bei' without false ayen", ok, det)

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY QA 26-30 VERIFICATION ({passed}/{len(results)} PASSED)")
    print("=" * 84)
    for code, label, ok, det in results:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {code:<10} | {label}")
        if det:
            print(f"       -> {det}")
    print("=" * 84 + "\n")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    run_checks(offline=args.offline)