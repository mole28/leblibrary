#!/usr/bin/env python3
import argparse
import http.client
import json
import os
import re
import socket
import ssl
import sys
import time
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
    req = urllib.request.Request(LIVE_ORIGIN + path, headers={"User-Agent": "LebLibrary-PerfVerifier/2.0"})
    t0 = time.monotonic()
    try:
        with _IPV4_OPENER.open(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.status, body, int((time.monotonic() - t0) * 1000)
    except urllib.error.HTTPError as exc:
        return exc.code, "", int((time.monotonic() - t0) * 1000)


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

    def chk_perf_01_fts5():
        bootstrap_django()
        from django.test import RequestFactory
        from articles.torah_engine import _get_verified_fts_table, tanakh_advanced_search_api
        fts_tbl = _get_verified_fts_table(force_recheck=True)
        rf = RequestFactory()
        t0 = time.monotonic()
        r1 = tanakh_advanced_search_api(rf.get("/api/tanakh-search/?type=text&exact=true&q=\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea&book=torah"))
        r2 = tanakh_advanced_search_api(rf.get("/api/tanakh-search/?type=text&exact=true&q=\u05e9\u05de\u05e2&book=mishnah"))
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        d1 = json.loads(r1.content.decode("utf-8"))
        d2 = json.loads(r2.content.decode("utf-8"))
        ok = (r1.status_code == 200 and r2.status_code == 200 and d1.get("total", 0) >= 1 and d2.get("total", 0) >= 50)
        return ok, f"fts_table={fts_tbl}, bereshit={d1.get('total')}, shema_mishnah={d2.get('total')}, {elapsed_ms}ms"

    ok, det = chk_perf_01_fts5()
    record("PERF-01", "FTS5 prefilter active/safe and exact Torah/Mishnah queries return complete results", ok, det)

    def chk_perf_02_ai_articles():
        ai_src = read_rel("articles/ai_engine.py")
        has_sql_prefilter = "art_q |= Q(title__icontains=w) | Q(content__icontains=w)" in ai_src
        has_only_iter = ".only('id', 'title', 'slug', 'content')" in ai_src and ".iterator(chunk_size=50)" in ai_src
        no_full_loop = "for art in Article.objects.filter(is_published=True):" not in ai_src
        ok = (has_sql_prefilter and has_only_iter and no_full_loop)
        return ok, f"sql_prefilter={has_sql_prefilter}, only_iter={has_only_iter}, no_full_loop={no_full_loop}"

    ok, det = chk_perf_02_ai_articles()
    record("PERF-02", "ai_engine.py prefilters published articles in SQL with .only() and iterator()", ok, det)

    def chk_perf_03_aramaic_ipv4():
        ar_src = read_rel("articles/aramaic_engine.py")
        uses_ipv4 = "from .torah_engine import _IPV4_OPENER" in ar_src and "_IPV4_OPENER.open(" in ar_src
        no_raw_open = "urllib.request.urlopen(" not in ar_src
        has_logger = "logging.getLogger(__name__)" in ar_src
        ok = (uses_ipv4 and no_raw_open and has_logger)
        return ok, f"ipv4={uses_ipv4}, no_raw_urlopen={no_raw_open}, logger={has_logger}"

    ok, det = chk_perf_03_aramaic_ipv4()
    record("PERF-03", "aramaic_engine.py uses _IPV4_OPENER for external lookups and logs errors", ok, det)

    def chk_perf_04_views_cache_random_audio():
        bootstrap_django()
        from django.core.cache import cache
        from articles.views import _get_content_cache_version, _bump_content_cache_version
        v_src = read_rel("articles/views.py")
        no_cache_clear = "cache.clear()" not in v_src
        no_order_rand = "order_by('?')" not in v_src
        has_async_audio = "_spawn_audio_generation_job" in v_src and "status=202" in v_src and "os.replace(tmp_path, file_path)" in v_src
        cache.set("perf_stage2_sentinel", "keep_me", 60)
        v1 = _get_content_cache_version()
        time.sleep(0.005)
        v2 = _bump_content_cache_version()
        sentinel_survived = cache.get("perf_stage2_sentinel") == "keep_me"
        cache.delete("perf_stage2_sentinel")
        ok = (no_cache_clear and no_order_rand and has_async_audio and v2 != v1 and sentinel_survived)
        return ok, f"no_clear={no_cache_clear}, no_rand={no_order_rand}, async_202={has_async_audio}, sentinel_ok={sentinel_survived}"

    ok, det = chk_perf_04_views_cache_random_audio()
    record("PERF-04", "views.py uses cache versioning (preserves Sefaria/ratelimit), avoids order_by('?'), and runs non-blocking 202 TTS", ok, det)

    def chk_perf_05_frontend_lazy_and_poll():
        adv = read_rel("articles/templates/articles/advanced_search.html")
        ad = read_rel("articles/templates/articles/article_detail.html")
        bd = read_rel("articles/templates/articles/book_detail.html")
        base_html = read_rel("articles/templates/articles/base.html")
        no_blocking_vis = '<script src="https://unpkg.com/vis-network' not in adv
        has_lazy_vis = "function ensureVisNetworkLoaded()" in adv
        has_poll_art = "response.status === 202" in ad and "fetchAudioWithPolling" in ad
        has_poll_book = "response.status === 202" in bd and "fetchAudioWithPolling" in bd
        has_preconnect = 'rel="preconnect" href="https://cdn.jsdelivr.net"' in base_html
        ok = (no_blocking_vis and has_lazy_vis and has_poll_art and has_poll_book and has_preconnect)
        return ok, f"lazy_vis={no_blocking_vis and has_lazy_vis}, poll_art={has_poll_art}, poll_book={has_poll_book}, preconnect={has_preconnect}"

    ok, det = chk_perf_05_frontend_lazy_and_poll()
    record("PERF-05", "Frontend lazy-loads vis-network, polls 202 audio jobs, and includes preconnect hints", ok, det)

    if not offline:
        def chk_live_perf_01():
            code, body, ms = fetch_live("/advanced-search/")
            if code != 200:
                return False, f"HTTP {code}"
            ok = ('<script src="https://unpkg.com/vis-network' not in body and "function ensureVisNetworkLoaded()" in body)
            return ok, f"HTTP {code}, {ms}ms"

        ok, det = chk_live_perf_01()
        record("LIVE-PERF-01", "Live /advanced-search/ lazy-loads vis-network without render-blocking script", ok, det)

        def chk_live_perf_02():
            code, body, ms = fetch_live("/")
            if code != 200:
                return False, f"HTTP {code}"
            ok = ('rel="preconnect" href="https://cdn.jsdelivr.net"' in body and 'rel="preconnect" href="https://fonts.gstatic.com"' in body)
            return ok, f"HTTP {code}, {ms}ms"

        ok, det = chk_live_perf_02()
        record("LIVE-PERF-02", "Live home page serves preconnect hints and loads cleanly", ok, det)

        def chk_live_perf_03():
            q = urllib.parse.urlencode({"type": "text", "exact": "true", "q": "\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea", "book": "torah"})
            code, body, ms = fetch_live(f"/api/tanakh-search/?{q}")
            if code != 200:
                return False, f"HTTP {code}"
            data = json.loads(body)
            ok = (data.get("total", 0) >= 1 and any(r.get("book") == "\u05d1\u05e8\u05d0\u05e9\u05d9\u05ea" for r in data.get("results", [])))
            return ok, f"total={data.get('total')}, {ms}ms"

        ok, det = chk_live_perf_03()
        record("LIVE-PERF-03", "Live exact Torah search for Bereshit succeeds cleanly with FTS5/fallback", ok, det)

        def chk_live_perf_04():
            c1, b1, _ = fetch_live("/article/63/")
            c2, b2, _ = fetch_live("/book/84/")
            ok = (c1 == 200 and c2 == 200 and "fetchAudioWithPolling" in b1 and "fetchAudioWithPolling" in b2)
            return ok, f"article={c1}, book={c2}"

        ok, det = chk_live_perf_04()
        record("LIVE-PERF-04", "Live /article/63/ and /book/84/ serve non-blocking 202 audio polling", ok, det)

    passed = sum(1 for _, _, ok, _ in results if ok)
    failed = len(results) - passed
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY PERFORMANCE STAGE-2 VERIFICATION ({passed}/{len(results)} PASSED)")
    print("=" * 84)
    for code, label, ok, det in results:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {code:<13} | {label}")
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