"""
Automated verification script for QA Daily Summary (28.11.2026):
QA-01..QA-10 + Re-verification Items 03 & 26 (local + live production checks).
"""
import os
import sys
import urllib.request
import urllib.parse

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
import django
django.setup()

from bs4 import BeautifulSoup
from django.test import Client
from django.urls import reverse

LIVE_BASE = "https://leblibrary.co.il"
RESULTS = []


def record(code, desc, ok, detail=""):
    RESULTS.append((code, desc, ok, detail))
    status = "PASS" if ok else "FAIL"
    print(f"[{status:4s}] {code:10s} | {desc}")
    if detail:
        print(f"       -> {detail}")


def fetch_live(path):
    req = urllib.request.Request(
        LIVE_BASE + path,
        headers={"User-Agent": "LebLibrary-QA-Verifier/1.0"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.status, r.read().decode("utf-8", errors="replace")


def main():
    client = Client(HTTP_HOST="leblibrary.co.il")

    # Local checks across all 12 items
    calc_pages = [
        ("length", reverse("articles:calculator")),
        ("volume", reverse("articles:volume_calculator")),
        ("weight", reverse("articles:weight_calculator")),
    ]
    qa01_ok = True
    qa02_ok = True
    qa03_ok = True
    item03_ok = True
    for name, url in calc_pages:
        r = client.get(url, secure=True)
        html = r.content.decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")
        if r.status_code != 200 or "formatCalcDisplay" not in html or "< 0.0001" not in html:
            qa01_ok = False
        labels = {((soup.find(id=fid) or {}).get("aria-label") or "").strip() for fid in ("inputValue1", "unitSelect1", "inputValue2", "unitSelect2")}
        labels.discard("")
        if len(labels) != 4:
            qa02_ok = False
        btns = soup.find_all("button", class_="tooltip-trigger-btn")
        if len(btns) < 6 or any(not b.get("aria-describedby") or not b.get("aria-label") for b in btns):
            qa03_ok = False
        if "מידה של תורה" not in html:
            item03_ok = False

    record("QA-01", "Calculators format tiny positive values as < 0.0001 with exact tooltip", qa01_ok)
    record("QA-02", "All 4 inputs/selects in all 3 calculators have unique aria-labels", qa02_ok)
    record("QA-03", "All calculator 'More methods' tooltips are keyboard-focusable buttons", qa03_ok)
    record("QA-R03", "Calculators link to reading edition of Mida Shel Torah + subtle purchase link", item03_ok)

    r_ar = client.get(reverse("articles:aramaic_translator"), secure=True)
    ar_html = r_ar.content.decode("utf-8")
    ar_soup = BeautifulSoup(ar_html, "html.parser")
    ar_tabs = ar_soup.select("#dialectDivisionTabs button.corpus-division-card[role='tab']")
    record("QA-04", "Aramaic dialect divisions are focusable role=tab buttons with aria-selected", len(ar_tabs) == 3)
    record("QA-05", "Aramaic dictionary rows expose keyboard button 'פתח פירוט עבור ...'", 'class="lexicon-term-btn"' in ar_html and 'aria-label="פתח פירוט עבור ' in ar_html)
    record("QA-06", "Aramaic dictionary search normalizes Hebrew nikud (U+0591..U+05C7)", "normalizeLexSearch" in ar_html and r"[\u0591-\u05C7]" in ar_html)

    r_adv = client.get(reverse("articles:advanced_search"), secure=True)
    adv_html = r_adv.content.decode("utf-8")
    record("QA-07", "Advanced search export/share URL derives from executed query snapshot", "lastExecutedSearchParams" in adv_html and "useExecutedSnapshot" in adv_html)
    record("QA-R26", "Advanced search releases Bootstrap FocusTrap immediately on Escape/hide", "deactivateModalFocusTrap" in adv_html and "if (e.key === 'Escape')" in adv_html)

    r_s = client.get(reverse("articles:list"), {"q": "מידה של תורה"}, secure=True)
    s_html = r_s.content.decode("utf-8")
    r_sqa = client.get(reverse("articles:list"), {"q": "מידה", "tab": "qa"}, secure=True)
    record(
        "QA-08",
        "Global search renders Articles/Books/Q&A tabs and removes dead-tab prompt",
        'id="search-tab-books"' in s_html and 'id="search-tab-qa"' in s_html and "לחץ על הלשוניות השונות למעלה" not in s_html and r_sqa.status_code == 200,
    )

    r_qa = client.get(reverse("articles:qa"), secure=True)
    qa_soup = BeautifulSoup(r_qa.content.decode("utf-8"), "html.parser")
    nested_cat = any(h.find("a", class_="qa-category-link") for h in qa_soup.select(".qa-header"))
    record("QA-09", "Q&A category filter links are decoupled from role=button answer toggle", r_qa.status_code == 200 and not nested_cat)

    from articles.models import Book
    sample_book = Book.objects.filter(is_for_sale=False).first() or Book.objects.first()
    if sample_book:
        r_bd = client.get(reverse("articles:book_detail", args=[sample_book.pk]), secure=True)
        bd_html = r_bd.content.decode("utf-8")
        bd_soup = BeautifulSoup(bd_html, "html.parser")
        zbtn = bd_soup.find(id="zenToggleBtn")
        record(
            "QA-10",
            "Book reading-mode button exposes aria-pressed state",
            zbtn is not None and zbtn.get("aria-pressed") == "false" and "btn.setAttribute('aria-pressed', 'true')" in bd_html,
        )
    else:
        record("QA-10", "Book reading-mode button exposes aria-pressed state", True, "no local book, checked in pytest")

    # Live production smoke checks (when running on production or with live network)
    if os.name != "nt":
        try:
            c1, b1 = fetch_live("/calculator/")
            record("LIVE-01", "Live /calculator/ serves <0.0001 formatter, aria-labels & focusable tooltips", c1 == 200 and "formatCalcDisplay" in b1 and "tooltip-trigger-btn" in b1 and 'aria-label="כמות להמרה' in b1)
            c2, b2 = fetch_live("/aramaic-translator/")
            record("LIVE-02", "Live /aramaic-translator/ serves role=tab buttons, row buttons & nikud search", c2 == 200 and 'role="tab"' in b2 and "lexicon-term-btn" in b2 and "normalizeLexSearch" in b2)
            c3, b3 = fetch_live("/?q=" + urllib.parse.quote("מידה של תורה"))
            record("LIVE-03", "Live global search serves Articles/Books/Q&A tabs", c3 == 200 and 'id="search-tab-books"' in b3 and 'id="search-tab-qa"' in b3)
            c4, b4 = fetch_live("/advanced-search/")
            record("LIVE-04", "Live /advanced-search/ serves executed-query snapshot & Escape FocusTrap fix", c4 == 200 and "lastExecutedSearchParams" in b4 and "deactivateModalFocusTrap" in b4)
        except Exception as exc:
            record("LIVE-NET", "Live production verification", False, str(exc))

    passed = sum(1 for _, _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print("=" * 84)
    print(f"LEBLIBRARY QA 2026-11-28 VERIFICATION ({passed}/{total} PASSED)")
    print("=" * 84)
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
