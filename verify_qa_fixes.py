import json
import os
import re
import sys


def _bootstrap_django():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)

    if not os.environ.get('DJANGO_SETTINGS_MODULE'):
        manage_path = os.path.join(base_dir, 'manage.py')
        settings_mod = None
        if os.path.exists(manage_path):
            with open(manage_path, 'r', encoding='utf-8') as f:
                m = re.search(r"DJANGO_SETTINGS_MODULE['\"],\s*['\"]([^'\"]+)['\"]", f.read())
                if m:
                    settings_mod = m.group(1)
        os.environ['DJANGO_SETTINGS_MODULE'] = settings_mod or 'mosheArticles.settings'

    import django
    django.setup()


def _read_file(rel_path):
    full_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)
    if not os.path.exists(full_path):
        return ''
    with open(full_path, 'r', encoding='utf-8') as f:
        return f.read()


def run_all_checks():
    _bootstrap_django()

    from django.test import RequestFactory
    import articles.views as views_mod
    from articles.views import (
        article_list,
        qa_list,
        books,
        advanced_search_view,
        aramaic_translator_view,
        apply_tts_dictionary,
    )
    from articles.torah_engine import (
        tanakh_advanced_search_api,
        format_divine_name,
        _fix_hebrew_numeral_order,
    )
    from articles.aramaic_engine import (
        get_full_compiled_lexicon,
        execute_aramaic_translation,
    )
    from articles.clusters_engine import ClusterEngine
    from articles.ai_engine import ai_chat_endpoint

    HOST = 'leblibrary.co.il'
    rf = RequestFactory()

    def make_get(path):
        return rf.get(path, HTTP_HOST=HOST)

    def make_post(path, payload):
        return rf.post(
            path,
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_HOST=HOST,
        )

    base_html = _read_file('articles/templates/articles/base.html')
    scripts_html = _read_file('articles/templates/articles/includes/scripts.html')
    article_html = _read_file('articles/templates/articles/article_detail.html')
    book_html = _read_file('articles/templates/articles/book_detail.html')

    adv_resp = advanced_search_view(make_get('/advanced-search/')).content.decode('utf-8')
    b_units = ClusterEngine._get_indexed_book_units()
    lex = get_full_compiled_lexicon()

    results = []

    def check(bug_id, desc, fn):
        try:
            ok, detail = fn()
            results.append((bug_id, desc, bool(ok), detail))
        except Exception as e:
            results.append((bug_id, desc, False, f'Exception: {type(e).__name__}: {e}'))

    # 01
    check('LEB-UI-01', 'חיווי אות שגוי בחיפוש במילון הארמי', lambda: (
        'תוצאות חיפוש בכל האותיות' in aramaic_translator_view(make_get('/aramaic-translator/')).content.decode('utf-8'),
        'סקריפט תיקון כותרת תחתונה קיים'
    ))

    # 02
    def _chk_02():
        resp = qa_list(make_get('/qa/?q=צומות'))
        return resp.status_code == 200, f'HTTP {resp.status_code}'
    check('LEB-UI-02', 'חיפוש בשו"ת (/qa/?q=צומות) ללא שגיאת 500', _chk_02)

    # 03
    check('LEB-UI-03', 'הפניית כרטיס ספר לעותק קריא / תיוג רכישה ברור', lambda: (
        len(b_units) > 0 and all('cta_label' in u for u in b_units),
        f'נבדקו {len(b_units)} יחידות ספרים'
    ))

    # 04
    def _chk_04():
        has_br_in_units = any('<br' in (u.get('title', '') + u.get('badge', '')).lower() for u in b_units)
        has_striptags = 'b_unit.badge|striptags' in article_html and 'b_unit.title|striptags' in article_html
        return (not has_br_in_units) and has_striptags, f'has_br={has_br_in_units}, striptags={has_striptags}'
    check('LEB-UI-04', 'הסרת תגית <br> גלויה בכרטיסי המלצות ספרים', _chk_04)

    # 05
    check('LEB-UI-05', 'הסרת כותרות כפולות בתוך עמוד ספר', lambda: (
        'deduplicateBookHeadings' in book_html,
        'deduplicateBookHeadings קיימת ב-book_detail.html'
    ))

    # 06
    def _chk_06():
        data = json.loads(tanakh_advanced_search_api(make_get('/api/tanakh-search/?q=בראשית&type=text_exact&book=torah')).content)
        total = data.get('total', 0)
        return total >= 1, f'total={total}'
    check('LEB-UI-06', 'חיפוש מדויק של "בראשית" בתורה מחזיר תוצאות', _chk_06)

    # 07
    def _chk_07():
        resp = ai_chat_endpoint(make_post('/api/ai-chat/', {'question': 'איפה נמצא מחשבון מידות האורך באתר?', 'mode': 'nav'}))
        body = b''.join(resp.streaming_content).decode('utf-8') if hasattr(resp, 'streaming_content') else resp.content.decode('utf-8')
        ok = ('Missing API key' not in body) and (not body.strip().startswith('{')) and ('/calculator/' in body or 'מחשבון' in body)
        return ok, body[:90].replace('\n', ' ')
    check('LEB-UI-07', 'עוזר הניווט אינו מציג JSON גולמי או שגיאת מפתח', _chk_07)

    # 08
    check('LEB-UI-08', 'מרכוז סמל הנגישות לאחר סגירת התפריט', lambda: (
        "toggle.style.display = 'flex'" in scripts_html,
        "display='flex' מוגדר בסגירה"
    ))

    # 09
    check('LEB-UI-09', 'היפוך צבעים אינו מעלים את תפריט הנגישות בגלילה', lambda: (
        'body.a11y-invert-colors .content-wrapper' in base_html,
        'filter: invert מוחל על content-wrapper ולא על body'
    ))

    # 10
    check('LEB-UI-10', 'כפתור "מההתחלה" להתחלת הקראה מחדש', lambda: (
        ('speechRestartBtn' in article_html and 'restartSpeech' in article_html and 'speechRestartBtn' in book_html),
        'כפתור restartSpeech קיים במאמרים ובספרים'
    ))

    # 11
    def _chk_11():
        out = apply_tts_dictionary("רבי יהושע או' מיו\"ט או חול")
        ok = ('רבי יהושע אומר' in out) and ('או חול' in out)
        return ok, out.replace('\n', ' ')
    check('LEB-UI-11', "הגיית הקיצור או' -> אומר בלי לפגוע במילה 'או'", _chk_11)

    # 12
    check('LEB-UI-12', 'קריאות טקסט פנימי במצב "הדגשת קישורים"', lambda: (
        'body.a11y-highlight-links a *' in base_html,
        'כלל CSS לשחור על צהוב גם לרכיבים פנימיים'
    ))

    # 13
    def _chk_13():
        fixed = format_divine_name("שנא' (שופטים ד) ראש האשמורת התיכונה")
        return '(שופטים ז, יט)' in fixed, fixed
    check('LEB-UI-13', 'תיקון מראה מקום בתוספתא ברכות א, ג -> שופטים ז, יט', _chk_13)

    # 14
    check('LEB-UI-14', 'נגישות מקלדת (Tab/Enter/Esc) לכפתור ותפריט הנגישות', lambda: (
        'initAccessibilityKeyboardSupport' in scripts_html and "setAttribute('tabindex', '0')" in scripts_html,
        'initAccessibilityKeyboardSupport פעילה ב-scripts.html'
    ))

    # 15
    check('LEB-UI-15', 'קריאות כותרות מאמרים במצב לילה (Dark Mode)', lambda: (
        'body.dark-mode h1 a' in base_html and 'body.dark-mode .card-title a' in base_html,
        'כללי ניגודיות לכותרות וקישורים במצב לילה קיימים'
    ))

    # 16
    def _chk_16():
        t1 = _fix_hebrew_numeral_order('סימן טות')
        t2 = _fix_hebrew_numeral_order('סימן טזת')
        t3 = _fix_hebrew_numeral_order('סימן טותק')
        ok = (t1 == 'סימן תטו') and (t2 == 'סימן תטז') and (t3 == 'סימן תקטו')
        return ok, f'{t1}, {t2}, {t3}'
    check('LEB-UI-16', 'תיקון סדר אותיות בסימני שו"ע (טות->תטו, טזת->תטז, טותק->תקטו)', _chk_16)

    # 17
    def _chk_17():
        resp = books(make_get('/books/?q=כיפה'))
        html = resp.content.decode('utf-8')
        return resp.status_code == 200 and 'applyBooksFilter' in html, f'HTTP {resp.status_code}'
    check('LEB-UI-17', 'שדה החיפוש בעמוד הספרים מסנן תוצאות ומציג חיווי', _chk_17)

    # 18
    check('LEB-UI-18', 'ניקוי תוויות כפתורים ("פירוש רש"י") בהעתקת פרק מלא', lambda: (
        'cleanCopiedTorahText' in adv_resp,
        'cleanCopiedTorahText פעילה ב-advanced_search_view'
    ))

    # 19 & 20 (לא נמסרו דוחות נפרדים - בדיקת שפיות דף הבית וטעינת המודולים)
    def _chk_19_20():
        resp = article_list(make_get('/'))
        has_api = hasattr(views_mod, 'aramaic_translate_api')
        return resp.status_code == 200 and has_api, f'Home HTTP {resp.status_code}, aramaic_translate_api={has_api}'
    check('LEB-UI-19/20', 'בדיקת תקינות כללית (דף הבית + שלמות views.py)', _chk_19_20)

    # 21
    def _chk_21():
        arabic_keys = [k for k in lex.keys() if re.search(r'[\u0600-\u06FF]', k)]
        ok = ('אשתמודע' in lex) and (len(arabic_keys) == 0)
        return ok, f'אשתמודע={"אשתמודע" in lex}, arabic_keys={len(arabic_keys)}'
    check('LEB-UI-21', 'הסרת אותיות ערביות מערכי המילון הארמי (אשתמודע)', _chk_21)

    # 22
    check('LEB-UI-22', 'שחזור סוג פעולה והחרגת ספרים אחרי רענון בחיפוש המתקדם', lambda: (
        'function applyUrlStateToUiWithRetry(attemptsLeft, triggerSearchIfNeeded' in adv_resp
        and 'restoreExcludeBooksInSelect' in adv_resp,
        'מנגנון שחזור עם Retry ו-restoreExcludeBooksInSelect תקין'
    ))

    # 23
    def _chk_23():
        payload, status = execute_aramaic_translation(make_get('/api/aramaic-translate/?q=בדיקתמילון123&dialect=zohar'))
        no_fake = len(payload.get('talmud_examples', [])) == 0
        clear_msg = 'לא נמצא' in payload.get('main_translation', '')
        return status == 200 and no_fake and clear_msg, payload.get('main_translation', '')
    check('LEB-UI-23', 'קלט מומצא אינו מוצג כציטוט חי מספר הזוהר', _chk_23)

    # 24
    def _chk_24():
        data = json.loads(tanakh_advanced_search_api(make_get('/api/tanakh-search/?q=ושב&type=text_exact&book=torah,tanakh&per_page=2500')).content)
        has_js = 'fetchAllResultsForExport' in adv_resp
        ok = has_js and data.get('per_page') == 2500 and len(data.get('results', [])) == data.get('total', 0)
        return ok, f"exported={len(data.get('results', []))}/{data.get('total', 0)}"
    check('LEB-UI-24', '"העתק הכל" ו-TXT מייצאים את כל התוצאות מכל העמודים', _chk_24)

    # 25
    check('LEB-UI-25', 'נגישות מקלדת (Tab/Enter/Space) לכרטיסי המאגרים וסוגי החיפוש', lambda: (
        'initSearchCardsKeyboardA11y' in adv_resp and 'a11y-search-card-focusable' in adv_resp,
        'initSearchCardsKeyboardA11y פעילה ב-advanced_search_view'
    ))

    passed_count = sum(1 for _, _, ok, _ in results if ok)
    total_count = len(results)

    print('\n' + '=' * 78)
    print(f'  LEBLIBRARY QA VERIFICATION REPORT ({passed_count}/{total_count} PASSED)')
    print('=' * 78)
    for bug_id, desc, ok, detail in results:
        status_icon = '✅ PASS' if ok else '❌ FAIL'
        print(f'{status_icon} | {bug_id:<12} | {desc}')
        if not ok:
            print(f'         └─ Detail: {detail}')
    print('=' * 78 + '\n')

    if passed_count != total_count:
        sys.exit(1)


if __name__ == '__main__':
    run_all_checks()