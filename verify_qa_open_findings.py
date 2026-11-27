import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path
import django

BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from articles.models import sanitize_unsafe_links_html

LIVE_BASE = "https://leblibrary.co.il"
UA = {"User-Agent": "LebLibrary-QA-Verify/1.0"}


def fetch_live(path):
    req = urllib.request.Request(LIVE_BASE + path, headers=UA)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return resp.status, resp.read().decode("utf-8", errors="ignore")


def test_finding_19_local_link_sanitizer():
    sample = (
        '<p><a href="file:///C:/Program%20Files/%D7%AA%D7%95%D7%A8%D7%AA%20%D7%90%D7%9E%D7%AA/Temp/his_temp_1_3.htm#bm:1-#ויקרא פרק-יח-{ג}!">(ויקרא פרק יח)</a> '
        '<a href="file:///C:/Program%20Files/Temp/his_temp_3_0.htm#bm:2-#ירמיה פרק-לד-{ה}!">(ירמיה פרק לד)</a> '
        '<a href="file:///C:/Users/admin/Desktop/notes.docx">קובץ פנימי</a></p>'
    )
    cleaned = sanitize_unsafe_links_html(sample)
    assert "file:///" not in cleaned.lower()
    assert "his_temp" not in cleaned.lower()
    assert "/advanced-search/?mode=browse&amp;corpus=tanakh&amp;target_book=%D7%95%D7%99%D7%A7%D7%A8%D7%90&amp;target_chapter=18" in cleaned
    assert "/advanced-search/?mode=browse&amp;corpus=tanakh&amp;target_book=%D7%99%D7%A8%D7%9E%D7%99%D7%94%D7%95&amp;target_chapter=34" in cleaned
    assert 'rel="noopener noreferrer"' in cleaned
    assert "קובץ פנימי" in cleaned
    assert "notes.docx" not in cleaned


def test_finding_20_accessible_browse_selects():
    adv_html = (BASE_DIR / "articles/templates/articles/advanced_search.html").read_text(encoding="utf-8")
    assert 'for="browseBookSelect"' in adv_html
    assert 'id="browseBookSelect" aria-label="בחר ספר"' in adv_html
    assert 'for="browseChapterSelect"' in adv_html
    assert 'id="browseChapterSelect" aria-label="בחר פרק"' in adv_html


def test_finding_24_full_export_and_truthful_cap_ui():
    adv_html = (BASE_DIR / "articles/templates/articles/advanced_search.html").read_text(encoding="utf-8")
    assert "const EXPORT_PAGE_SIZE = 2500;" in adv_html
    assert "const MAX_EXPORT_RESULTS = 10000;" in adv_html
    assert "function updateExportToolbarState(" in adv_html
    assert 'id="exportCapNotice"' in adv_html
    assert "for (let p = 1; p <= pagesNeeded; p++)" in adv_html
    assert "הועתקו ${countFmt} מתוך ${totalFmt} תוצאות." in adv_html


def test_finding_26_deterministic_modal_focus_restoration():
    adv_html = (BASE_DIR / "articles/templates/articles/advanced_search.html").read_text(encoding="utf-8")
    assert 'onclick="openFullChapterModalByIdx(${idx}, this)"' in adv_html
    assert 'data-modal-trigger="chapter"' in adv_html
    assert "function resolveModalReturnTarget(" in adv_html
    assert "function restoreModalFocusTarget(" in adv_html
    assert "let activeClosingModalEl = null;" in adv_html
    assert "let chapterModalRequestSeq = 0;" in adv_html


def main():
    offline = "--offline" in sys.argv
    results = []

    def record(code, label, ok, det=""):
        results.append((code, label, ok, det))

    for code, label, fn in (
        ("QA-19", "Local file:/// sanitizer rewrites Tanakh refs & unwraps unsafe links", test_finding_19_local_link_sanitizer),
        ("QA-20", "Browse book/chapter selects expose explicit labels and aria-label", test_finding_20_accessible_browse_selects),
        ("QA-24", "Export paginates full results up to 10,000 with truthful cap messaging", test_finding_24_full_export_and_truthful_cap_ui),
        ("QA-26", "Chapter modal captures trigger element and restores focus deterministically", test_finding_26_deterministic_modal_focus_restoration),
    ):
        try:
            fn()
            record(code, label, True, "")
        except Exception as exc:
            record(code, label, False, str(exc))

    if not offline:
        try:
            code, body = fetch_live("/book/25/")
            has_local = bool(re.search(r"file:///|his_temp|Program%20Files", body, re.I))
            has_lev = "target_book=%D7%95%D7%99%D7%A7%D7%A8%D7%90&amp;target_chapter=18" in body or "target_book=%D7%95%D7%99%D7%A7%D7%A8%D7%90&target_chapter=18" in body
            has_jer = "target_book=%D7%99%D7%A8%D7%9E%D7%99%D7%94%D7%95&amp;target_chapter=34" in body or "target_book=%D7%99%D7%A8%D7%9E%D7%99%D7%94%D7%95&target_chapter=34" in body
            ok19 = (code == 200 and not has_local and has_lev and has_jer)
            record("LIVE-19", "Live /book/25/ has zero local file links and valid Lev 18 & Jer 34 links", ok19, f"http={code}, local={has_local}, lev={has_lev}, jer={has_jer}")
        except Exception as exc:
            record("LIVE-19", "Live /book/25/ check", False, str(exc))

        try:
            c1, b1 = fetch_live("/api/tanakh-search/?type=quick_open&target_book=" + urllib.parse.quote("ויקרא") + "&target_chapter=18&corpus=tanakh")
            c2, b2 = fetch_live("/api/tanakh-search/?type=quick_open&target_book=" + urllib.parse.quote("ירמיהו") + "&target_chapter=34&corpus=tanakh")
            d1, d2 = json.loads(b1), json.loads(b2)
            ok19b = (c1 == 200 and len(d1.get("verses", [])) >= 25 and c2 == 200 and len(d2.get("verses", [])) >= 20)
            record("LIVE-19B", "Live quick_open resolves Leviticus 18 and Jeremiah 34 chapters", ok19b, f"lev={len(d1.get('verses', []))}, jer={len(d2.get('verses', []))}")
        except Exception as exc:
            record("LIVE-19B", "Live quick_open targets check", False, str(exc))

        try:
            code, body = fetch_live("/advanced-search/")
            ok20 = (
                code == 200
                and 'for="browseBookSelect"' in body
                and 'id="browseBookSelect" aria-label="בחר ספר"' in body
                and 'for="browseChapterSelect"' in body
                and 'id="browseChapterSelect" aria-label="בחר פרק"' in body
            )
            record("LIVE-20", "Live /advanced-search/ serves accessible names for book & chapter selects", ok20, f"http={code}")
            ok24 = (code == 200 and "MAX_EXPORT_RESULTS = 10000" in body and "exportCapNotice" in body)
            record("LIVE-24A", "Live /advanced-search/ serves multi-page full export and cap UI", ok24, f"http={code}")
            ok26 = (code == 200 and "resolveModalReturnTarget" in body and "openFullChapterModalByIdx(${idx}, this)" in body)
            record("LIVE-26", "Live /advanced-search/ serves deterministic modal focus restoration", ok26, f"http={code}")
        except Exception as exc:
            record("LIVE-20", "Live /advanced-search/ checks", False, str(exc))

        try:
            p1_c, p1_b = fetch_live("/api/tanakh-search/?type=gematria&q=26&book=torah,tanakh&page=1&per_page=2500")
            p2_c, p2_b = fetch_live("/api/tanakh-search/?type=gematria&q=26&book=torah,tanakh&page=2&per_page=2500")
            p3_c, p3_b = fetch_live("/api/tanakh-search/?type=gematria&q=26&book=torah,tanakh&page=3&per_page=2500")
            d1, d2, d3 = json.loads(p1_b), json.loads(p2_b), json.loads(p3_b)
            total_sum = len(d1.get("results", [])) + len(d2.get("results", [])) + len(d3.get("results", []))
            reported = d1.get("total", 0)
            ok24b = (p1_c == p2_c == p3_c == 200 and reported >= 5000 and total_sum == reported)
            record("LIVE-24B", "Live gematria 26 multi-page export retrieves all results completely", ok24b, f"collected={total_sum}/{reported}")
        except Exception as exc:
            record("LIVE-24B", "Live gematria 26 export check", False, str(exc))

    passed = sum(1 for _, _, ok, _ in results if ok)
    print("\n" + "=" * 84)
    print(f"  LEBLIBRARY OPEN QA FINDINGS VERIFICATION ({passed}/{len(results)} PASSED)")
    print("=" * 84)
    for code, label, ok, det in results:
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {code:<10} | {label}")
        if det:
            print(f"       -> {det}")
    print("=" * 84)
    sys.exit(0 if passed == len(results) else 1)


if __name__ == "__main__":
    main()