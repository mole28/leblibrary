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
    req = urllib.request.Request(LIVE_ORIGIN + path, headers={"User-Agent": "LebLibrary-QAVerifier/3.0"})
    try:
        with _IPV4_OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""


def srgb_to_lin(val):
    c = val / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def contrast_ratio(hex1, hex2):
    def lum(hx):
        hx = hx.lstrip("#")
        r, g, b = int(hx[0:2], 16), int(hx[2:4], 16), int(hx[4:6], 16)
        return 0.2126 * srgb_to_lin(r) + 0.7152 * srgb_to_lin(g) + 0.0722 * srgb_to_lin(b)
    l1, l2 = lum(hex1), lum(hex2)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def read_rel(rel_path):
    with open(os.path.join(BASE_DIR, rel_path), "r", encoding="utf-8") as f:
        return f.read()


def run_checks(offline=False):
    results = []

    def record(code, label, ok, detail=""):
        results.append((code, label, ok, detail))

    def chk_34_local():
        sk = read_rel("articles/templates/articles/includes/scripts.html")
        ad = read_rel("articles/templates/articles/article_detail.html")
        m_light = re.search(r"body:not\(\.dark-mode\):not\(\.a11y-high-contrast\)\s*\.lux-acronym\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", sk, re.S)
        m_dark = re.search(r"body\.dark-mode:not\(\.a11y-high-contrast\)\s*\.lux-acronym\s*\{[^}]*color:\s*(#[0-9a-fA-F]{6})", sk, re.S)
        if not m_light or not m_dark:
            return False, "Missing light/dark .lux-acronym contrast rules"
        c_light = contrast_ratio(m_light.group(1), "#ffffff")
        c_zen = contrast_ratio(m_light.group(1), "#fdfbf7")
        c_dark = contrast_ratio(m_dark.group(1), "#1e293b")
        ad_ok = "#7a4f16" in ad and "#f3d36b" in ad
        ok = (c_light >= 4.5 and c_zen >= 4.5 and c_dark >= 4.5 and ad_ok)
        return ok, f"light={m_light.group(1)} ({c_light:.2f}:1 on white, {c_zen:.2f}:1 on zen), dark={m_dark.group(1)} ({c_dark:.2f}:1)"

    ok, det = chk_34_local()
    record("LEB-UI-34A", "Acronym and footnote contrast rules meet WCAG 2.2 AA (>= 4.5:1)", ok, det)

    def chk_36_local():
        adv = read_rel("articles/templates/articles/advanced_search.html")
        m_clear = re.search(r"window\.clearResultsScreen\s*=\s*function\(\)\s*\{(?P<body>.*?)\n    \};", adv, re.S)
        body = m_clear.group("body") if m_clear else ""
        checks = [
            "browseChapterSelect" in body,
            "chapterSelectEl.value = ''" in body,
            "activeBrowseState =" in body,
            "window.history.replaceState" in body,
            "browseChapterSelectEl.addEventListener('keydown'" in adv,
        ]
        return all(checks), f"checks={checks}"

    ok, det = chk_36_local()
    record("LEB-UI-36A", "clearResultsScreen resets chapter dropdown, browse state, and URL", ok, det)

    def chk_37_local():
        adv = read_rel("articles/templates/articles/advanced_search.html")
        needed = [
            "params.set('mode', 'browse')",
            "params.set('target_book', activeBrowseState.book)",
            "params.set('target_chapter', activeBrowseState.chapter)",
            "inferBrowseCorpusForBook",
            "modeParam === 'browse' || targetBookParam",
            "shareEmailLink').href = `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(fullShareString)}`",
            "triggerUniversalShare(title, bodyTxt, buildShareableCurrentUrl())",
        ]
        missing = [t for t in needed if t not in adv]
        return len(missing) == 0, ", ".join(missing)

    ok, det = chk_37_local()
    record("LEB-UI-37A", "Unified share URL preserves search filters and chapter browse mode across all channels", ok, det)

    if not offline:
        def chk_live_34():
            code, body = fetch_live("/article/63/")
            if code != 200:
                return False, f"HTTP {code}"
            ok = ("#7a4f16" in body and "body:not(.dark-mode):not(.a11y-high-contrast) .lux-acronym" in body)
            return ok, ""

        ok, det = chk_live_34()
        record("LIVE-34", "Live /article/63/ serves WCAG AA/AAA contrast CSS for .lux-acronym", ok, det)

        def chk_live_36_37():
            code, body = fetch_live("/advanced-search/")
            if code != 200:
                return False, f"HTTP {code}"
            tokens = [
                "chapterSelectEl.value = ''",
                "params.set('mode', 'browse')",
                "params.set('target_book', activeBrowseState.book)",
                "params.set('target_chapter', activeBrowseState.chapter)",
                "modeParam === 'browse' || targetBookParam",
                "shareEmailLink').href = `mailto:?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(fullShareString)}`",
            ]
            missing = [t for t in tokens if t not in body]
            return len(missing) == 0, ", ".join(missing)

        ok, det = chk_live_36_37()
        record("LIVE-36-37", "Live /advanced-search/ serves clear-screen reset and unified share/browse URL state", ok, det)

        def chk_live_37_gematria_api():
            q = urllib.parse.urlencode({"type": "gematria", "q": "26", "book": "torah,tanakh"})
            code, body = fetch_live(f"/api/tanakh-search/?{q}")
            if code != 200:
                return False, f"HTTP {code}"
            data = json.loads(body)
            total = data.get("total", 0)
            return total > 1000, f"gematria 26 torah+tanakh total={total}"

        ok, det = chk_live_37_gematria_api()
        record("LIVE-37B", "Live gematria 26 torah+tanakh API reproduces full results", ok, det)

        def chk_live_37_chapter_api():
            q1 = urllib.parse.urlencode({"type": "quick_open", "target_book": "\u05d1\u05e8\u05db\u05d5\u05ea", "target_chapter": "\u05e4\u05e8\u05e7 \u05d0", "corpus": "mishnah"})
            q2 = urllib.parse.urlencode({"type": "quick_open", "target_book": "\u05d1\u05e8\u05db\u05d5\u05ea", "target_chapter": "\u05e4\u05e8\u05e7 \u05d1", "corpus": "mishnah"})
            c1, b1 = fetch_live(f"/api/tanakh-search/?{q1}")
            c2, b2 = fetch_live(f"/api/tanakh-search/?{q2}")
            if c1 != 200 or c2 != 200:
                return False, f"HTTP {c1}/{c2}"
            d1, d2 = json.loads(b1), json.loads(b2)
            v1, v2 = len(d1.get("verses", [])), len(d2.get("verses", []))
            return (v1 == 5 and v2 == 8), f"berakhot ch1={v1} mishnayot, ch2={v2} mishnayot"

        ok, det = chk_live_37_chapter_api()
        record("LIVE-37C", "Live quick_open API resolves Mishnah Berakhot ch1 (5) and ch2 (8) for shared browse links", ok, det)

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY QA 34-37 VERIFICATION ({passed}/{len(results)} PASSED)")
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