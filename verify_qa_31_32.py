#!/usr/bin/env python3
import argparse
import http.client
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
    req = urllib.request.Request(LIVE_ORIGIN + path, headers={"User-Agent": "LebLibrary-QAVerifier/2.0"})
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


def analyze_footnotes_html(html_text):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html_text, "html.parser")
    body = soup.find(id="articleBodyContent") or soup
    all_ids = [el["id"] for el in body.find_all(id=True)]
    dup_ids = sorted({i for i in all_ids if all_ids.count(i) > 1})
    refs = body.find_all("a", class_="footnote-ref")
    backrefs = body.find_all("a", class_="footnote-backref")
    broken_refs = []
    for r in refs:
        href = (r.get("href") or "").strip()
        if not href.startswith("#") or not body.find(id=href[1:]):
            broken_refs.append(href)
    broken_backrefs = []
    for b in backrefs:
        href = (b.get("href") or "").strip()
        if not href.startswith("#") or not body.find(id=href[1:]):
            broken_backrefs.append(href)
    return {
        "ref_count": len(refs),
        "backref_count": len(backrefs),
        "dup_ids": dup_ids,
        "broken_refs": broken_refs,
        "broken_backrefs": broken_backrefs,
        "groups": sorted({r.get("data-fn-group") for r in refs if r.get("data-fn-group")}),
    }


def run_checks(offline=False):
    results = []

    def record(code, label, ok, detail=""):
        results.append((code, label, ok, detail))

    def chk_31_art6_db():
        bootstrap_django()
        from articles.models import Article, normalize_article_footnotes_html
        art = Article.objects.filter(pk=6).first()
        if not art:
            return False, "Article 6 not found in DB"
        rendered = normalize_article_footnotes_html(art.content or "")
        stats = analyze_footnotes_html(rendered)
        ok = (
            stats["ref_count"] >= 15
            and stats["backref_count"] >= 15
            and len(stats["groups"]) >= 3
            and not stats["dup_ids"]
            and not stats["broken_refs"]
            and not stats["broken_backrefs"]
        )
        return ok, f"refs={stats['ref_count']}, backrefs={stats['backref_count']}, groups={stats['groups']}, dups={stats['dup_ids']}, broken={stats['broken_refs']}"

    ok, det = chk_31_art6_db()
    record("LEB-UI-31A", "Article 6 multi-section footnotes normalized with unique bidirectional IDs", ok, det)

    def chk_31_art63_regression():
        bootstrap_django()
        from articles.models import Article, normalize_article_footnotes_html
        art = Article.objects.filter(pk=63).first()
        if not art:
            return False, "Article 63 not found in DB"
        rendered = normalize_article_footnotes_html(art.content or "")
        stats = analyze_footnotes_html(rendered)
        ok = (stats["ref_count"] >= 1 and not stats["broken_refs"] and not stats["dup_ids"])
        return ok, f"refs={stats['ref_count']}, backrefs={stats['backref_count']}, broken={stats['broken_refs']}"

    ok, det = chk_31_art63_regression()
    record("LEB-UI-31B", "Article 63 standard footnotes regression check", ok, det)

    def chk_32_model_dates():
        bootstrap_django()
        from articles.models import Article
        checked = []
        missing = []
        for pk in (63, 59, 52, 51):
            art = Article.objects.filter(pk=pk).first()
            if not art:
                continue
            heb = art.display_hebrew_date
            greg = art.display_gregorian_date
            full = art.display_full_date
            checked.append(f"#{pk}:{full}")
            if not heb or not greg or not re.search(r"[\u05d0-\u05ea]", heb) or not re.match(r"^\d{2}\.\d{2}\.\d{4}$", greg):
                missing.append(f"#{pk}({heb}|{greg})")
        dummy = Article(title="NoDate", created_at=None, hebrew_date="")
        if dummy.display_full_date != "":
            missing.append(f"nodate={dummy.display_full_date}")
        return len(checked) > 0 and len(missing) == 0, "; ".join(missing or checked)

    ok, det = chk_32_model_dates()
    record("LEB-UI-32A", "Article model exposes consistent Hebrew and Gregorian dates and handles empty dates", ok, det)

    if not offline:
        def chk_live_31_art6():
            code, body = fetch_live("/article/6/")
            if code != 200:
                return False, f"HTTP {code}"
            stats = analyze_footnotes_html(body)
            ok = (
                stats["ref_count"] >= 15
                and stats["backref_count"] >= 15
                and len(stats["groups"]) >= 3
                and not stats["dup_ids"]
                and not stats["broken_refs"]
                and not stats["broken_backrefs"]
                and "scrollAndPulseTarget" in body
            )
            return ok, f"refs={stats['ref_count']}, backrefs={stats['backref_count']}, groups={stats['groups']}, broken={stats['broken_refs']}"

        ok, det = chk_live_31_art6()
        record("LIVE-31A", "Live /article/6/ resolves all 3 sections footnotes uniquely with backlinks", ok, det)

        def chk_live_31_art63():
            code, body = fetch_live("/article/63/")
            if code != 200:
                return False, f"HTTP {code}"
            stats = analyze_footnotes_html(body)
            return (stats["ref_count"] >= 1 and not stats["broken_refs"] and not stats["dup_ids"]), f"refs={stats['ref_count']}, backrefs={stats['backref_count']}"

        ok, det = chk_live_31_art63()
        record("LIVE-31B", "Live /article/63/ footnotes regression check", ok, det)

        def chk_live_32_articles():
            bad = []
            samples = []
            for pk in (63, 59, 52, 51):
                code, body = fetch_live(f"/article/{pk}/")
                if code != 200:
                    bad.append(f"#{pk}:HTTP {code}")
                    continue
                m = re.search(r'<time[^>]*datetime="(\d{4}-\d{2}-\d{2})"[^>]*>(.*?)</time>', body, re.S)
                if not m:
                    bad.append(f"#{pk}:missing <time>")
                    continue
                inner = re.sub(r"<[^>]+>", "", m.group(2)).strip()
                has_heb = bool(re.search(r"[\u05d0-\u05ea]", inner))
                has_greg = bool(re.search(r"\d{2}\.\d{2}\.\d{4}", inner))
                if not (has_heb and has_greg):
                    bad.append(f"#{pk}:incomplete({inner})")
                else:
                    samples.append(f"#{pk}:{inner}")
            return len(bad) == 0, "; ".join(bad or samples)

        ok, det = chk_live_32_articles()
        record("LIVE-32A", "Live articles 63, 59, 52, 51 render visible Hebrew + Gregorian <time>", ok, det)

        def chk_live_32_parasha():
            q = urllib.parse.urlencode({"p": "\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea"})
            code, body = fetch_live(f"/parasha/?{q}")
            if code != 200:
                return False, f"HTTP {code}"
            has_empty_label = "\u05e0\u05d5\u05e6\u05e8 \u05d1\u05ea\u05d0\u05e8\u05d9\u05da:" in body
            has_glued = "\u05d4\u05e7\u05d3\u05de\u05d4\u05d1\u05de\u05d0\u05de\u05e8" in body or "\u05e0\u05d9\u05e9\u05d5\u05d0\u05d9\u05df\u05d1\u05d1\u05e8\u05d9\u05d0\u05ea" in body
            has_time = bool(re.search(r'<time[^>]*datetime="\d{4}-\d{2}-\d{2}"[^>]*>.*?\d{2}\.\d{2}\.\d{4}', body, re.S))
            return (not has_empty_label and not has_glued and has_time), f"empty_label={has_empty_label}, glued={has_glued}, has_time={has_time}"

        ok, det = chk_live_32_parasha()
        record("LIVE-32B", "Live /parasha/?p=Bereshit shows Hebrew + Gregorian date and clean excerpt", ok, det)

        def chk_live_32_lists():
            issues = []
            for path in ("/recently-added/", "/"):
                code, body = fetch_live(path)
                if code != 200:
                    issues.append(f"{path}:HTTP {code}")
                    continue
                if not re.search(r'<time[^>]*datetime="\d{4}-\d{2}-\d{2}"[^>]*>.*?\d{2}\.\d{2}\.\d{4}', body, re.S):
                    issues.append(f"{path}:missing visible date")
            return len(issues) == 0, "; ".join(issues)

        ok, det = chk_live_32_lists()
        record("LIVE-32C", "Live /recently-added/ and home page show visible Hebrew + Gregorian dates", ok, det)

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY QA 31-32 VERIFICATION ({passed}/{len(results)} PASSED)")
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