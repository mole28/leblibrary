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


def fetch_live(path, timeout=12):
    req = urllib.request.Request(LIVE_ORIGIN + path, headers={"User-Agent": "LebLibrary-QAVerifier/4.0"})
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


def read_rel(rel_path):
    with open(os.path.join(BASE_DIR, rel_path), "r", encoding="utf-8") as f:
        return f.read()


def run_checks(offline=False):
    results = []

    def record(code, label, ok, detail=""):
        results.append((code, label, ok, detail))

    def chk_38_local():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.aramaic_engine import execute_aramaic_translation
        rf = RequestFactory()
        issues = []

        p1, s1 = execute_aramaic_translation(rf.get("/api/aramaic-translate/?q=\u05dc\u05de\u05d4&dir=he_to_ar&dialect=bavli"))
        if s1 != 200 or not p1.get("detected_direction", "").startswith("\u05e2\u05d1\u05e8\u05d9\u05ea \u2b05 \u05d0\u05e8\u05de\u05d9\u05ea") or "\u05d0\u05de\u05d0\u05d9" not in p1.get("main_translation", ""):
            issues.append(f"he_to_ar(lama)={p1.get('detected_direction')}|{p1.get('main_translation')}")

        p2, s2 = execute_aramaic_translation(rf.get("/api/aramaic-translate/?q=\u05de\u05d9\u05dd&dir=ar_to_he&dialect=bavli"))
        if s2 != 200 or not p2.get("detected_direction", "").startswith("\u05d0\u05e8\u05de\u05d9\u05ea \u2b05 \u05e2\u05d1\u05e8\u05d9\u05ea") or not p2.get("direction_mismatch"):
            issues.append(f"ar_to_he(mayim)={p2.get('detected_direction')}|mismatch={p2.get('direction_mismatch')}")

        p3, s3 = execute_aramaic_translation(rf.get("/api/aramaic-translate/?q=\u05de\u05d9\u05dd&dir=he_to_ar&dialect=bavli"))
        if s3 != 200 or not p3.get("detected_direction", "").startswith("\u05e2\u05d1\u05e8\u05d9\u05ea \u2b05 \u05d0\u05e8\u05de\u05d9\u05ea") or "\u05de\u05d9\u05d0" not in p3.get("main_translation", ""):
            issues.append(f"he_to_ar(mayim)={p3.get('detected_direction')}|{p3.get('main_translation')}")

        p4, s4 = execute_aramaic_translation(rf.get("/api/aramaic-translate/?q=\u05d0\u05de\u05d0\u05d9&dir=he_to_ar&dialect=bavli"))
        if s4 != 200 or not p4.get("detected_direction", "").startswith("\u05e2\u05d1\u05e8\u05d9\u05ea \u2b05 \u05d0\u05e8\u05de\u05d9\u05ea") or not p4.get("direction_mismatch"):
            issues.append(f"he_to_ar(amai)={p4.get('detected_direction')}|mismatch={p4.get('direction_mismatch')}")

        p5, s5 = execute_aramaic_translation(rf.get("/api/aramaic-translate/?q=\u05d6\u05d1\u05e8\u05d1\u05dc\u05d0&dir=auto&dialect=zohar"))
        if s5 != 200 or p5.get("talmud_examples"):
            issues.append(f"gibberish_zohar={p5.get('talmud_examples')}")

        return len(issues) == 0, "; ".join(issues) or f"he_to_ar(lama)={p1.get('main_translation')}; ar_to_he(mayim)=mismatch->he_to_ar"

    ok, det = chk_38_local()
    record("LEB-UI-38A", "Aramaic engine strictly enforces explicit he_to_ar and ar_to_he directions", ok, det)

    def chk_39_local():
        adv = read_rel("articles/templates/articles/advanced_search.html")
        m_inp = re.search(r"searchQueryInput\.addEventListener\('input',\s*\(\)\s*=>\s*\{(?P<body>.*?)\n    \}\);", adv, re.S)
        body = m_inp.group("body") if m_inp else ""
        bad_reset = "elsPreselectSkip.value = ''" in body or "currentSkipFilter = ''" in body
        good_sync = "currentSkipFilter = elsPreselectSkip.value" in body
        return (not bad_reset and good_sync), f"bad_reset={bad_reset}, good_sync={good_sync}"

    ok, det = chk_39_local()
    record("LEB-UI-39A", "Typing in advanced_search.html preserves preselected ELS skip value", ok, det)

    def chk_40_local():
        qa = read_rel("articles/templates/articles/qa_list.html")
        has_center = "block: 'center'" in qa or 'block: "center"' in qa
        has_scroll_fn = "function scrollToQaStart" in qa and "scrollToQaStart(cardEl, headerEl)" in qa
        has_margin = "scroll-margin-top:" in qa
        return (not has_center and has_scroll_fn and has_margin), f"has_center={has_center}, scroll_fn={has_scroll_fn}, margin={has_margin}"

    ok, det = chk_40_local()
    record("LEB-UI-40A", "qa_list.html scrolls direct QA links to question top instead of center", ok, det)

    def chk_41_local():
        nav = read_rel("articles/templates/articles/includes/navbar.html")
        needed = [
            'id="mainNavToggleBtn"',
            'aria-label="\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9"',
            'aria-controls="navbarCollapseContent"',
            'aria-expanded="false"',
            'toggleMainNavMenu',
            '<i class="bi bi-list" aria-hidden="true"></i>',
        ]
        missing = [t for t in needed if t not in nav]
        return len(missing) == 0, ", ".join(missing)

    ok, det = chk_41_local()
    record("LEB-UI-41A", "navbar.html main menu button has accessible name, controls, and dynamic aria-expanded", ok, det)

    if not offline:
        def chk_live_38():
            q1 = urllib.parse.urlencode({"q": "\u05dc\u05de\u05d4", "dir": "he_to_ar", "dialect": "bavli"})
            q2 = urllib.parse.urlencode({"q": "\u05de\u05d9\u05dd", "dir": "ar_to_he", "dialect": "bavli"})
            q3 = urllib.parse.urlencode({"q": "\u05de\u05d9\u05dd", "dir": "he_to_ar", "dialect": "bavli"})
            c1, b1 = fetch_live(f"/api/aramaic-translate/?{q1}")
            c2, b2 = fetch_live(f"/api/aramaic-translate/?{q2}")
            c3, b3 = fetch_live(f"/api/aramaic-translate/?{q3}")
            if not (c1 == c2 == c3 == 200):
                return False, f"HTTP {c1}/{c2}/{c3}"
            d1, d2, d3 = json.loads(b1), json.loads(b2), json.loads(b3)
            ok1 = d1.get("detected_direction", "").startswith("\u05e2\u05d1\u05e8\u05d9\u05ea \u2b05 \u05d0\u05e8\u05de\u05d9\u05ea") and "\u05d0\u05de\u05d0\u05d9" in d1.get("main_translation", "")
            ok2 = d2.get("detected_direction", "").startswith("\u05d0\u05e8\u05de\u05d9\u05ea \u2b05 \u05e2\u05d1\u05e8\u05d9\u05ea") and d2.get("direction_mismatch") is True
            ok3 = d3.get("detected_direction", "").startswith("\u05e2\u05d1\u05e8\u05d9\u05ea \u2b05 \u05d0\u05e8\u05de\u05d9\u05ea") and "\u05de\u05d9\u05d0" in d3.get("main_translation", "")
            return (ok1 and ok2 and ok3), f"lama_he2ar={ok1} ({d1.get('main_translation')}), mayim_ar2he_mismatch={ok2}, mayim_he2ar={ok3}"

        ok, det = chk_live_38()
        record("LIVE-38", "Live /api/aramaic-translate/ enforces explicit he_to_ar and ar_to_he", ok, det)

        def chk_live_39():
            code, body = fetch_live("/advanced-search/")
            if code != 200:
                return False, f"HTTP {code}"
            m_inp = re.search(r"searchQueryInput\.addEventListener\('input',\s*\(\)\s*=>\s*\{(?P<body>.*?)\n    \}\);", body, re.S)
            inp_body = m_inp.group("body") if m_inp else ""
            ok_ui = ("currentSkipFilter = elsPreselectSkip.value" in inp_body and "elsPreselectSkip.value = ''" not in inp_body)
            q_skip = urllib.parse.urlencode({"type": "els", "q": "\u05d1\u05d0\u05d9", "book": "torah", "skip": "1"})
            c_api, b_api = fetch_live(f"/api/tanakh-search/?{q_skip}")
            if c_api != 200:
                return False, f"API HTTP {c_api}"
            api_data = json.loads(b_api)
            ok_api = api_data.get("active_skip") == 1 and api_data.get("total", 0) > 0 and all(r.get("skip_distance") == 1 for r in api_data.get("results", []))
            return (ok_ui and ok_api), f"ui_preserved={ok_ui}, skip1_total={api_data.get('total')}"

        ok, det = chk_live_39()
        record("LIVE-39", "Live /advanced-search/ preserves preselected ELS skip while typing", ok, det)

        def chk_live_40():
            code, body = fetch_live("/qa/1/")
            if code != 200:
                return False, f"HTTP {code}"
            ok = ("scrollToQaStart(cardEl, headerEl)" in body and "block: 'center'" not in body)
            return ok, ""

        ok, det = chk_live_40()
        record("LIVE-40", "Live /qa/1/ scrolls to start of question card instead of center", ok, det)

        def chk_live_41():
            code, body = fetch_live("/")
            if code != 200:
                return False, f"HTTP {code}"
            tokens = [
                'id="mainNavToggleBtn"',
                'aria-label="\u05ea\u05e4\u05e8\u05d9\u05d8 \u05e8\u05d0\u05e9\u05d9"',
                'aria-controls="navbarCollapseContent"',
                'aria-expanded="false"',
                'toggleMainNavMenu',
            ]
            missing = [t for t in tokens if t not in body]
            return len(missing) == 0, ", ".join(missing)

        ok, det = chk_live_41()
        record("LIVE-41", "Live home page navbar toggle has aria-label, aria-controls, and aria-expanded", ok, det)

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY QA 38-41 VERIFICATION ({passed}/{len(results)} PASSED)")
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