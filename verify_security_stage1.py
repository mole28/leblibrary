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


def fetch_live(path, method="GET", data=None, headers=None, timeout=12):
    req_headers = {"User-Agent": "LebLibrary-SecVerifier/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(LIVE_ORIGIN + path, data=data, headers=req_headers, method=method)
    try:
        with _IPV4_OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
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
        from articles.ai_engine import ai_chat_endpoint, _sanitize_ai_chunk
        sk = read_rel("articles/templates/articles/includes/scripts.html")
        dom_safe = (
            "appendSafeUserBubble" in sk
            and "div.textContent = text;" in sk
            and 'nav-chat-user">${userText}' not in sk
            and 'qa-chat-user">${userText}' not in sk
        )
        xss_out = _sanitize_ai_chunk('<img src=x onerror=alert(1)> [click](javascript:alert(1)) [ok](/books/)', "#d4af37", "_blank")
        link_safe = (
            "<img" not in xss_out
            and "javascript:" not in xss_out
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
        evil_resp = ai_chat_endpoint(evil_req)
        origin_blocked = evil_resp.status_code == 403
        return (dom_safe and link_safe and origin_blocked), f"dom_safe={dom_safe}, link_safe={link_safe}, evil_origin={evil_resp.status_code}"

    ok, det = chk_sec_02_chat_xss_and_origin()
    record("SEC-02", "AI chat blocks DOM XSS, javascript: links, and cross-origin POSTs", ok, det)

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
        from articles.views import _sanitize_header_value
        v_src = read_rel("articles/views.py")
        hdr_clean = _sanitize_header_value("Hello\r\nBcc: evil@example.com")
        no_crlf = "\r" not in hdr_clean and "\n" not in hdr_clean
        checks = [
            no_crlf,
            "@ratelimit(rate=5, timeout=300, methods=('POST',))" in v_src,
            "@ratelimit(rate=10, timeout=300, methods=('POST',))" in v_src,
            "Book.objects.select_for_update()" in v_src,
            "locked_book.stock -= qty" in v_src,
            'value="{escape(q)}"' in v_src,
            "CONTACT_RECIPIENT_EMAIL" in v_src,
        ]
        return all(checks), f"checks={checks}"

    ok, det = chk_sec_04_contact_and_checkout()
    record("SEC-04", "Contact header sanitization, POST rate-limiting, atomic stock checkout, and qa_list escaping", ok, det)

    if not offline:
        def chk_live_sec_01():
            c_evil, _ = fetch_live(
                "/api/ai-chat/",
                method="POST",
                data=json.dumps({"question": "books", "mode": "nav"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "https://evil-attacker.example"},
            )
            c_ok, body_ok = fetch_live(
                "/api/ai-chat/",
                method="POST",
                data=json.dumps({"question": "\u05e1\u05e4\u05e8\u05d9\u05dd", "mode": "nav"}).encode("utf-8"),
                headers={"Content-Type": "application/json", "Origin": "https://leblibrary.co.il"},
            )
            return (c_evil == 403 and c_ok == 200 and len(body_ok) > 10), f"cross_origin={c_evil}, same_origin={c_ok}"

        ok, det = chk_live_sec_01()
        record("LIVE-SEC-01", "Live /api/ai-chat/ rejects cross-origin POST (403) and serves same-origin POST (200)", ok, det)

        def chk_live_sec_02():
            code, body = fetch_live("/")
            if code != 200:
                return False, f"HTTP {code}"
            ok = ("appendSafeUserBubble" in body and "buildAiRequestHeaders" in body and 'nav-chat-user">${userText}' not in body)
            return ok, ""

        ok, det = chk_live_sec_02()
        record("LIVE-SEC-02", "Live home page serves XSS-safe AI chat bubble renderer", ok, det)

        def chk_live_sec_03():
            code, body = fetch_live("/contact/")
            return (code == 200 and "form" in body.lower()), f"HTTP {code}"

        ok, det = chk_live_sec_03()
        record("LIVE-SEC-03", "Live GET /contact/ remains unaffected by POST-only rate limit", ok, det)

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY SECURITY STAGE-1 VERIFICATION ({passed}/{len(results)} PASSED)")
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