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


def fetch_live(path, follow_redirects=True, timeout=12):
    req = urllib.request.Request(LIVE_ORIGIN + path, headers={"User-Agent": "LebLibrary-SEOVerifier/3.0"})
    opener = _IPV4_OPENER if follow_redirects else _IPV4_NO_REDIRECT_OPENER
    try:
        with opener.open(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        return exc.code, dict(exc.headers), body


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


def extract_json_ld_blocks(html_body):
    raw_blocks = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', html_body, re.S | re.I)
    parsed = []
    errors = []
    for raw in raw_blocks:
        try:
            parsed.append(json.loads(raw.strip()))
        except Exception as exc:
            errors.append(str(exc))
    return parsed, errors


def count_schema_types(parsed_blocks):
    counts = {}
    for blk in parsed_blocks:
        items = blk.get("@graph", [blk]) if isinstance(blk, dict) else (blk if isinstance(blk, list) else [])
        for it in items:
            if not isinstance(it, dict):
                continue
            t = it.get("@type")
            types = t if isinstance(t, list) else ([t] if t else [])
            for tn in types:
                counts[tn] = counts.get(tn, 0) + 1
    return counts


def run_checks(offline=False):
    results = []

    def record(code, label, ok, detail=""):
        results.append((code, label, ok, detail))

    def chk_seo_01_base_unified():
        base_html = read_rel("articles/templates/articles/base.html")
        has_sys_note = "SYSTEM NOTE FOR AI" in base_html
        blocks = re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>', base_html)
        has_canonical_block = "{% block canonical_url %}" in base_html
        has_browse_noindex = "request.GET.mode" in base_html and "request.GET.target_book" in base_html
        ok = (not has_sys_note and len(blocks) == 2 and has_canonical_block and has_browse_noindex)
        return ok, f"sys_note={has_sys_note}, ld_tags={len(blocks)}, canonical_block={has_canonical_block}, browse_noindex={has_browse_noindex}"

    ok, det = chk_seo_01_base_unified()
    record("SEO-01", "base.html uses unified JSON-LD @graph without SYSTEM NOTE FOR AI and extensible canonical", ok, det)

    def chk_seo_02_article_no_docwrite():
        ad_html = read_rel("articles/templates/articles/article_detail.html")
        has_doc_write = "document.write" in ad_html
        has_parasha_links = "articles:parasha_detail" in ad_html
        has_breadcrumb_ld = '"BreadcrumbList"' in ad_html
        has_dup_website = '"@type": "WebSite"' in ad_html
        ok = (not has_doc_write and has_parasha_links and has_breadcrumb_ld and not has_dup_website)
        return ok, f"doc_write={has_doc_write}, parasha_links={has_parasha_links}, breadcrumb_ld={has_breadcrumb_ld}, dup_website={has_dup_website}"

    ok, det = chk_seo_02_article_no_docwrite()
    record("SEO-02", "article_detail.html removes document.write, adds semantic parasha links and clean JSON-LD", ok, det)

    def chk_seo_03_book_a11y_schema():
        bd_html = read_rel("articles/templates/articles/book_detail.html")
        has_old_fn_gold = bool(re.search(r"sup,.*color:\s*#d4af37", bd_html, re.S))
        has_aa_fn = "color: #7a4f16 !important;" in bd_html and "color: #f3d36b !important;" in bd_html
        has_normalized_render = "section.rendered_content" in bd_html
        has_dup_website = '"@type": "WebSite"' in bd_html
        has_fake_faq = '"@type": "FAQPage"' in bd_html
        has_js_comment = bool(re.search(r"^\s*//", bd_html, re.M))
        ok = (not has_old_fn_gold and has_aa_fn and has_normalized_render and not has_dup_website and not has_fake_faq and not has_js_comment)
        return ok, f"old_gold={has_old_fn_gold}, aa_fn={has_aa_fn}, normalized={has_normalized_render}, fake_faq={has_fake_faq}, comments={has_js_comment}"

    ok, det = chk_seo_03_book_a11y_schema()
    record("SEO-03", "book_detail.html meets WCAG AA contrast, normalizes footnotes, and unifies Book JSON-LD", ok, det)

    def chk_seo_04_parasha_routes():
        bootstrap_django()
        from django.test import Client
        client = Client()
        r_old = client.get("/parasha/?p=\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea")
        r_new = client.get("/parasha/\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea/")
        r_multi = client.get("/parasha/\u05dc\u05da-\u05dc\u05da/")
        body_new = r_new.content.decode("utf-8", errors="replace")
        has_canon = 'rel="canonical" href="https://leblibrary.co.il/parasha/\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea/"' in body_new
        ok = (r_old.status_code == 301 and r_new.status_code == 200 and r_multi.status_code == 200 and has_canon)
        return ok, f"old_status={r_old.status_code}, new_status={r_new.status_code}, multi_status={r_multi.status_code}, canonical={has_canon}"

    ok, det = chk_seo_04_parasha_routes()
    record("SEO-04", "Parasha semantic routes /parasha/<slug>/ return 200 with canonical and 301 from ?p=", ok, det)

    if not offline:
        def chk_live_seo_home():
            code, _, body = fetch_live("/")
            if code != 200:
                return False, f"HTTP {code}"
            blocks, errs = extract_json_ld_blocks(body)
            counts = count_schema_types(blocks)
            ok = (
                not errs
                and "SYSTEM NOTE FOR AI" not in body
                and counts.get("WebSite", 0) == 1
                and counts.get("Person", 0) == 1
            )
            return ok, f"errs={errs}, counts={counts}"

        ok, det = chk_live_seo_home()
        record("LIVE-SEO-01", "Live home page serves valid unified JSON-LD (1 WebSite, 1 Person, no SYSTEM NOTE)", ok, det)

        def chk_live_seo_article():
            code, _, body = fetch_live("/article/63/")
            if code != 200:
                return False, f"HTTP {code}"
            blocks, errs = extract_json_ld_blocks(body)
            counts = count_schema_types(blocks)
            ok = (
                not errs
                and "document.write" not in body
                and counts.get("WebSite", 0) == 1
                and counts.get("ScholarlyArticle", 0) == 1
                and counts.get("BreadcrumbList", 0) == 1
            )
            return ok, f"errs={errs}, counts={counts}"

        ok, det = chk_live_seo_article()
        record("LIVE-SEO-02", "Live /article/63/ has valid unified ScholarlyArticle JSON-LD and no document.write", ok, det)

        def chk_live_seo_parasha():
            q = urllib.parse.urlencode({"p": "\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea"})
            c_301, hdrs, _ = fetch_live(f"/parasha/?{q}", follow_redirects=False)
            p_enc = urllib.parse.quote("\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea")
            c_200, _, body = fetch_live(f"/parasha/{p_enc}/", follow_redirects=True)
            blocks, errs = extract_json_ld_blocks(body)
            counts = count_schema_types(blocks)
            has_canon = 'rel="canonical" href="https://leblibrary.co.il/parasha/\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea/"' in body
            has_index = 'content="index, follow' in body
            ok = (c_301 == 301 and c_200 == 200 and not errs and has_canon and has_index and counts.get("CollectionPage", 0) == 1)
            return ok, f"301={c_301}, 200={c_200}, canon={has_canon}, index={has_index}, counts={counts}"

        ok, det = chk_live_seo_parasha()
        record("LIVE-SEO-03", "Live /parasha/?p=Bereshit 301-redirects to indexable canonical /parasha/Bereshit/", ok, det)

        def chk_live_seo_book():
            code, _, body = fetch_live("/book/84/")
            if code != 200:
                return False, f"HTTP {code}"
            blocks, errs = extract_json_ld_blocks(body)
            counts = count_schema_types(blocks)
            ok = (
                not errs
                and counts.get("Book", 0) == 1
                and counts.get("WebSite", 0) == 1
                and counts.get("FAQPage", 0) == 0
                and "color: #7a4f16 !important;" in body
            )
            return ok, f"errs={errs}, counts={counts}"

        ok, det = chk_live_seo_book()
        record("LIVE-SEO-04", "Live /book/84/ has single Book JSON-LD (no fake FAQPage) and WCAG AA footnote CSS", ok, det)

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY SEO & A11Y STAGE-3 VERIFICATION ({passed}/{len(results)} PASSED)")
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