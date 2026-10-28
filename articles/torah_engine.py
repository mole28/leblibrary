import json
import urllib.request
import urllib.parse
import http.client
import socket
import re
import time
from functools import wraps
from django.http import JsonResponse
from django.core.cache import cache
from django.db.models import Q
from django.utils.html import strip_tags
from .models import TorahText


# ========= חיבור HTTPS מהיר ב-IPv4 בלבד (מונע תקיעות של 6-12 שניות בשרת האובונטו) =========
class _HTTPSConnectionIPv4(http.client.HTTPSConnection):
    def connect(self):
        addrs = socket.getaddrinfo(self.host, self.port or 443, socket.AF_INET, socket.SOCK_STREAM)
        sock = None
        last_err = None
        for family, socktype, proto, canonname, sockaddr in addrs:
            try:
                s = socket.socket(family, socktype, proto)
                if self.timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    s.settimeout(self.timeout)
                s.connect(sockaddr)
                sock = s
                break
            except Exception as e:
                last_err = e
        if sock is None:
            raise last_err or OSError("IPv4 connection failed")
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class _HTTPSHandlerIPv4(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_HTTPSConnectionIPv4, req, context=self._context)


_IPV4_OPENER = urllib.request.build_opener(_HTTPSHandlerIPv4())


HEBREW_GEMATRIA = {
    'א': 1, 'ב': 2, 'ג': 3, 'ד': 4, 'ה': 5, 'ו': 6, 'ז': 7, 'ח': 8, 'ט': 9,
    'י': 10, 'כ': 20, 'ך': 20, 'ל': 30, 'מ': 40, 'ם': 40, 'נ': 50, 'ן': 50,
    'ס': 60, 'ע': 70, 'פ': 80, 'ף': 80, 'צ': 90, 'ץ': 90,
    'ק': 100, 'ר': 200, 'ש': 300, 'ת': 400
}

TANAKH_NAMES = [
    'בראשית', 'שמות', 'ויקרא', 'במדבר', 'דברים', 'יהושע', 'שופטים',
    'שמואל א', 'שמואל ב', 'מלכים א', 'מלכים ב', 'ישעיהו', 'ירמיהו',
    'יחזקאל', 'הושע', 'יואל', 'עמוס', 'עובדיה', 'יונה', 'מיכה', 'נחום',
    'חבקוק', 'צפניה', 'חגי', 'זכריה', 'מלאכי', 'תהילים', 'משלי', 'איוב',
    'שיר השירים', 'רות', 'איכה', 'קהלת', 'אסתר', 'דניאל', 'עזרא',
    'נחמיה', 'דברי הימים א', 'דברי הימים ב'
]

TORAH_NAMES = ['בראשית', 'שמות', 'ויקרא', 'במדבר', 'דברים']

MISHNAH_BOOKS = [
    'ברכות', 'פאה', 'דמאי', 'כלאים', 'שביעית', 'תרומות', 'מעשרות', 'מעשר שני', 'חלה', 'ערלה', 'ביכורים',
    'שבת', 'עירובין', 'פסחים', 'שקלים', 'יומא', 'סוכה', 'ביצה', 'ראש השנה', 'תענית', 'מגילה', 'מועד קטן', 'חגיגה',
    'יבמות', 'כתובות', 'נדרים', 'נזיר', 'סוטה', 'גיטין', 'קידושין',
    'בבא קמא', 'בבא מציעא', 'בבא בתרא', 'סנהדרין', 'מכות', 'שבועות', 'עדיות', 'עבודה זרה', 'אבות', 'הוריות',
    'זבחים', 'מנחות', 'חולין', 'בכורות', 'ערכין', 'תמורה', 'כריתות', 'מעילה', 'תמיד', 'מדות', 'קינים',
    'כלים', 'אהלות', 'נגעים', 'פרה', 'טהרות', 'מקואות', 'נדה', 'מכשירין', 'זבים', 'טבול יום', 'ידים', 'עוקצין'
]

TANAKH_BOOKS_EN = {
    'בראשית': 'Genesis', 'שמות': 'Exodus', 'ויקרא': 'Leviticus', 'במדבר': 'Numbers', 'דברים': 'Deuteronomy',
    'יהושע': 'Joshua', 'שופטים': 'Judges', 'שמואל א': 'I Samuel', 'שמואל ב': 'II Samuel',
    'מלכים א': 'I Kings', 'מלכים ב': 'II Kings', 'ישעיהו': 'Isaiah', 'ירמיהו': 'Jeremiah',
    'יחזקאל': 'Ezekiel', 'הושע': 'Hosea', 'יואל': 'Joel', 'עמוס': 'Amos', 'עובדיה': 'Obadiah',
    'יונה': 'Jonah', 'מיכה': 'Micah', 'נחום': 'Nahum', 'חבקוק': 'Habakkuk', 'צפניה': 'Zephaniah',
    'חגי': 'Haggai', 'זכריה': 'Zechariah', 'מלאכי': 'Malachi', 'תהילים': 'Psalms', 'משלי': 'Proverbs',
    'איוב': 'Job', 'שיר השירים': 'Song of Songs', 'רות': 'Ruth', 'איכה': 'Lamentations',
    'קהלת': 'Ecclesiastes', 'אסתר': 'Esther', 'דניאל': 'Daniel', 'עזרא': 'Ezra', 'נחמיה': 'Nehemiah',
    'דברי הימים א': 'I Chronicles', 'דברי הימים ב': 'II Chronicles'
}

MISHNAH_BOOKS_EN = {
    'ברכות': 'Berakhot', 'פאה': 'Peah', 'דמאי': 'Demai', 'כלאים': 'Kilayim', 'שביעית': 'Sheviit',
    'תרומות': 'Terumot', 'מעשרות': 'Maasrot', 'מעשר שני': 'Maaser Sheni', 'חלה': 'Challah',
    'ערלה': 'Orlah', 'ביכורים': 'Bikkurim', 'שבת': 'Shabbat', 'עירובין': 'Eruvin', 'פסחים': 'Pesachim',
    'שקלים': 'Shekalim', 'יומא': 'Yoma', 'סוכה': 'Sukkah', 'ביצה': 'Beitzah', 'ראש השנה': 'Rosh Hashanah',
    'תענית': 'Taanit', 'מגילה': 'Megillah', 'מועד קטן': 'Moed Katan', 'חגיגה': 'Chagigah',
    'יבמות': 'Yevamot', 'כתובות': 'Ketubot', 'נדרים': 'Nedarim', 'נזיר': 'Nazir', 'סוטה': 'Sotah',
    'גיטין': 'Gittin', 'קידושין': 'Kiddushin', 'בבא קמא': 'Bava Kamma', 'בבא מציעא': 'Bava Metzia',
    'בבא בתרא': 'Bava Batra', 'סנהדרין': 'Sanhedrin', 'מכות': 'Makkot', 'שבועות': 'Shevuot',
    'עדיות': 'Eduyot', 'עבודה זרה': 'Avodah Zarah', 'אבות': 'Pirkei Avot', 'הוריות': 'Horayot',
    'זבחים': 'Zevachim', 'מנחות': 'Menachot', 'חולין': 'Chullin', 'בכורות': 'Bekhorot', 'ערכין': 'Arakhin',
    'תמורה': 'Temurah', 'כריתות': 'Keritot', 'מעילה': 'Meilah', 'תמיד': 'Tamid', 'מדות': 'Middot',
    'קינים': 'Kinnim', 'כלים': 'Kelim', 'אהלות': 'Oholot', 'נגעים': 'Negaim', 'פרה': 'Parah',
    'טהרות': 'Tahorot', 'מקואות': 'Mikvaot', 'נדה': 'Niddah', 'מכשירין': 'Makhshirin', 'זבים': 'Zavim',
    'טבול יום': 'Tevul Yom', 'ידים': 'Yadayim', 'עוקצין': 'Oktzin'
}

BAVLI_TRACTATES_EN = {
    'ברכות': 'Berakhot', 'שבת': 'Shabbat', 'עירובין': 'Eruvin', 'פסחים': 'Pesachim',
    'שקלים': 'Shekalim', 'יומא': 'Yoma', 'סוכה': 'Sukkah', 'ביצה': 'Beitzah',
    'ראש השנה': 'Rosh Hashanah', 'תענית': 'Taanit', 'מגילה': 'Megillah',
    'מועד קטן': 'Moed Katan', 'חגיגה': 'Chagigah', 'יבמות': 'Yevamot',
    'כתובות': 'Ketubot', 'נדרים': 'Nedarim', 'נזיר': 'Nazir', 'סוטה': 'Sotah',
    'גיטין': 'Gittin', 'קידושין': 'Kiddushin', 'בבא קמא': 'Bava Kamma',
    'בבא מציעא': 'Bava Metzia', 'בבא בתרא': 'Bava Batra', 'סנהדרין': 'Sanhedrin',
    'מכות': 'Makkot', 'שבועות': 'Shevuot', 'עבודה זרה': 'Avodah Zarah',
    'הוריות': 'Horayot', 'זבחים': 'Zevachim', 'מנחות': 'Menachot', 'חולין': 'Chullin',
    'בכורות': 'Bekhorot', 'ערכין': 'Arakhin', 'תמורה': 'Temurah', 'כריתות': 'Keritot',
    'מעילה': 'Meilah', 'תמיד': 'Tamid', 'נדה': 'Niddah', 'נידה': 'Niddah'
}

YERUSHALMI_TRACTATES_EN = {
    'ברכות': 'Berakhot', 'פאה': 'Peah', 'דמאי': 'Demai', 'כלאים': 'Kilayim',
    'שביעית': 'Sheviit', 'תרומות': 'Terumot', 'מעשרות': 'Maasrot', 'מעשר שני': 'Maaser Sheni',
    'חלה': 'Challah', 'ערלה': 'Orlah', 'ביכורים': 'Bikkurim', 'שבת': 'Shabbat',
    'עירובין': 'Eruvin', 'פסחים': 'Pesachim', 'יומא': 'Yoma', 'שקלים': 'Shekalim',
    'סוכה': 'Sukkah', 'ראש השנה': 'Rosh Hashanah', 'ביצה': 'Beitzah', 'תענית': 'Taanit',
    'מגילה': 'Megillah', 'חגיגה': 'Chagigah', 'מועד קטן': 'Moed Katan', 'יבמות': 'Yevamot',
    'סוטה': 'Sotah', 'כתובות': 'Ketubot', 'נדרים': 'Nedarim', 'נזיר': 'Nazir',
    'גיטין': 'Gittin', 'קידושין': 'Kiddushin', 'בבא קמא': 'Bava Kamma', 'בבא מציעא': 'Bava Metzia',
    'בבא בתרא': 'Bava Batra', 'סנהדרין': 'Sanhedrin', 'שבועות': 'Shevuot',
    'עבודה זרה': 'Avodah Zarah', 'מכות': 'Makkot', 'הוריות': 'Horayot', 'נדה': 'Niddah', 'נידה': 'Niddah'
}

SHULCHAN_ARUCH_EN = {
    'שולחן ערוך אורח חיים': 'Shulchan Arukh, Orach Chayim',
    'שולחן ערוך יורה דעה': "Shulchan Arukh, Yoreh De'ah",
    'שולחן ערוך אבן העזר': 'Shulchan Arukh, Even HaEzer',
    'שולחן ערוך חושן משפט': 'Shulchan Arukh, Choshen Mishpat',
}

def calculate_gematria(text):
    return sum(HEBREW_GEMATRIA.get(char, 0) for char in text)

def format_divine_name(text):
    if not text:
        return ""
    pattern = re.compile(
        r'(י[\u0591-\u05C7]*(?:</?(?:strong|mark)[^>]*>)*)'
        r'(ה[\u0591-\u05C7]*(?:</?(?:strong|mark)[^>]*>)*)'
        r'(ו[\u0591-\u05C7]*(?:</?(?:strong|mark)[^>]*>)*)'
        r'(ה[\u0591-\u05C7]*)',
        re.UNICODE
    )
    return pattern.sub(r'\1-\2-\3-\4', text)


def ratelimit(rate=30, timeout=60):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            ip = x_forwarded_for.split(',')[0].strip() if x_forwarded_for else request.META.get('REMOTE_ADDR', 'unknown')
            cache_key = f"api_ratelimit_{ip}"
            history = cache.get(cache_key, [])
            now = time.time()
            history = [t for t in history if now - t < timeout]
            if len(history) >= rate:
                return JsonResponse({
                    'meta': {'error': 'Rate limit exceeded.', 'retry_after_seconds': timeout},
                    'results': []
                }, status=429)
            history.append(now)
            cache.set(cache_key, history, timeout)
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator


def int_to_hebrew(num):
    if num <= 0:
        return str(num)
    hebrew_letters = [
        (400, 'ת'), (300, 'ש'), (200, 'ר'), (100, 'ק'),
        (90, 'צ'), (80, 'פ'), (70, 'ע'), (60, 'ס'), (50, 'נ'), (40, 'מ'), (30, 'ל'), (20, 'כ'), (10, 'י'),
        (9, 'ט'), (8, 'ח'), (7, 'ז'), (6, 'ו'), (5, 'ה'), (4, 'ד'), (3, 'ג'), (2, 'ב'), (1, 'א')
    ]
    result = ""
    while num >= 400:
        result += 'ת'
        num -= 400
    for val, letter in hebrew_letters:
        if num in (15, 16):
            result += 'טו' if num == 15 else 'טז'
            break
        if num >= val:
            result += letter
            num -= val
    return result


def parse_hebrew_number(val):
    s = str(val or '').strip()
    if not s:
        return 0
    if s.isdigit():
        return int(s)
    m = re.search(r'\d+', s)
    if m:
        return int(m.group(0))
    s_clean = re.sub(r'^(פרק|סימן|דף|הלכה|משנה|סעיף|שורה|פסוק)\s+', '', s).strip()
    s_clean = re.sub(r'(עמוד\s+[אב])', '', s_clean).strip()
    parts = s_clean.split()
    if parts:
        heb_token = re.sub(r'[^א-ת]', '', parts[0])
        if heb_token:
            return sum(HEBREW_GEMATRIA.get(c, 0) for c in heb_token)
    return 0


def format_verse_hebrew(val):
    s = str(val or '').strip()
    if not s:
        return ''
    if s.isdigit():
        return int_to_hebrew(int(s))
    m = re.match(r'^(\d+)$', s)
    if m:
        return int_to_hebrew(int(m.group(1)))
    return s


def get_book_order(book_name, chapter_name=""):
    name = str(book_name or '').strip()
    chap = str(chapter_name or '').strip()
    BOOK_ORDER = {b: i + 1 for i, b in enumerate(TANAKH_NAMES)}
    for i, b in enumerate(MISHNAH_BOOKS):
        BOOK_ORDER.setdefault(b, 40 + i)

    if name.startswith('תוספתא '):
        base = name.replace('תוספתא ', '', 1).strip()
        return 120 + BOOK_ORDER.get(base, 90)
    if chap.startswith('דף') and not name.startswith('ירושלמי '):
        return 230 + BOOK_ORDER.get(name, 90)
    if name.startswith('ירושלמי '):
        base = name.replace('ירושלמי ', '', 1).strip()
        return 350 + BOOK_ORDER.get(base, 90)
    if name.startswith('רמב"ם ') or name.startswith('רמב״ם '):
        return 500
    if name.startswith('שולחן ערוך '):
        sa_order = {
            'שולחן ערוך אורח חיים': 601, 'שולחן ערוך יורה דעה': 602,
            'שולחן ערוך אבן העזר': 603, 'שולחן ערוך חושן משפט': 604
        }
        return sa_order.get(name, 610)
    return BOOK_ORDER.get(name, 999)


def safe_int(v):
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    m = re.search(r'\d+', s)
    if m:
        return int(m.group(0))
    s_clean = re.sub(r'^(פרק|סימן|דף|הלכה|משנה|סעיף|שורה|פסוק)\s+', '', s)
    parts = s_clean.split()
    if parts:
        heb_num = sum(HEBREW_GEMATRIA.get(c, 0) for c in re.sub(r'[^א-ת]', '', parts[0]))
        amud = 2 if ('עמוד ב' in s or ':' in s) else 1
        return heb_num * 10 + amud
    return 0


def _resolve_torah_book_in_db(book_name):
    b = str(book_name or '').strip()
    if not b:
        return b
    if TorahText.objects.filter(book=b).exists():
        return b
    alt_b = b.replace('"', '״') if '"' in b else b.replace('״', '"')
    if TorahText.objects.filter(book=alt_b).exists():
        return alt_b
    return b


def _resolve_torah_verse_obj(book_name, chapter_name, verse_val):
    b = _resolve_torah_book_in_db(book_name)
    c = str(chapter_name or '').strip()
    v_raw = str(verse_val or '').strip()
    if not (b and c and v_raw):
        return None
    v_int = parse_hebrew_number(v_raw)
    v_heb = int_to_hebrew(v_int) if v_int > 0 else v_raw
    candidates = [
        v_raw, str(v_int), v_heb, f"{v_heb}'",
        f"פסוק {v_heb}", f"הלכה {v_heb}", f"משנה {v_heb}", f"סעיף {v_heb}", f"שורה {v_heb}",
        f"פסוק {v_int}", f"הלכה {v_int}", f"משנה {v_int}", f"סעיף {v_int}", f"שורה {v_int}"
    ]
    obj = TorahText.objects.filter(book=b, chapter=c, verse__in=candidates).first()
    if not obj and v_int > 0:
        all_ch = list(TorahText.objects.filter(book=b, chapter=c))
        all_ch.sort(key=lambda x: safe_int(x.verse))
        if 1 <= v_int <= len(all_ch):
            obj = all_ch[v_int - 1]
    return obj


def _extract_sefaria_he_list(he_data):
    flat = []
    if isinstance(he_data, str):
        if he_data.strip():
            flat.append(format_divine_name(he_data.strip()))
    elif isinstance(he_data, list):
        for item in he_data:
            flat.extend(_extract_sefaria_he_list(item))
    return flat


def _fetch_sefaria_json_cached(sefaria_ref, extra_params="context=0&pad=0"):
    c_key = f"sefaria_ipv4_v20_{sefaria_ref}_{extra_params}"
    cached = cache.get(c_key)
    if cached is not None:
        return cached
    url = f"https://www.sefaria.org/api/texts/{urllib.parse.quote(sefaria_ref)}?{extra_params}"
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        # Time-out קצר במיוחד למניעת תקיעות של השרת
        with _IPV4_OPENER.open(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            if isinstance(data, dict) and not data.get('error') and (data.get('he') or data.get('commentary')):
                cache.set(c_key, data, 3600 * 24)
                return data
    except Exception:
        pass
    return None


def _fetch_commentary_for_source(book_name, chapter_name, verse_num):
    """
    מנוע שליפת המפרשים המחודש והמהיר:
    1. מתחבר לספריא אך ורק באנגלית (מהיר ונתמך ב-100%).
    2. פונה ישירות לפסוק עצמו (`Genesis 1:1`) ושואב את כל המפרשים (`commentary=1`).
    3. מחלץ את *כל* הפירושים של אותו מפרש לפסוק בלי לסנן אותם החוצה.
    4. במידה וזה תלמוד בבלי, מושך את העמוד ושולף לפי האינדקס המדויק.
    """
    b_str = _resolve_torah_book_in_db(book_name).replace('״', '"')
    c_str = str(chapter_name or '').strip()
    v_str = str(verse_num or '').strip()

    chap_int = max(1, parse_hebrew_number(c_str))
    verse_int = max(1, parse_hebrew_number(v_str))

    cache_key = f"torah_comm_v20_{b_str}_{c_str}_{verse_int}"
    cached = cache.get(cache_key)
    if cached and cached.get('comments'):
        return cached

    comments_out = []
    target_commentator = 'רש"י'
    pref_commentator_he = 'רש"י'

    if b_str.startswith('ירושלמי '):
        target_commentator = 'פני משה'
        pref_commentator_he = 'פני משה'
    elif b_str.startswith('שולחן ערוך '):
        target_commentator = 'באר היטב'
        pref_commentator_he = 'באר היטב'
    elif b_str.startswith('רמב"ם '):
        target_commentator = 'מגיד משנה'
        pref_commentator_he = 'מגיד משנה'
    elif b_str in MISHNAH_BOOKS:
        target_commentator = 'רבינו עובדיה מברטנורא'
        pref_commentator_he = 'ברטנורא'

    # בניית הפנייה לספריא באנגלית כדי שירוץ מהר:
    base_ref_en = ""
    if b_str in TANAKH_BOOKS_EN and not c_str.startswith('דף'):
        base_ref_en = f"{TANAKH_BOOKS_EN[b_str]} {chap_int}:{verse_int}"
    elif c_str.startswith('דף') and not b_str.startswith('ירושלמי '):
        daf_num = max(2, chap_int)
        amud = 'b' if ('עמוד ב' in c_str or ':' in c_str) else 'a'
        if b_str in BAVLI_TRACTATES_EN:
            base_ref_en = f"{BAVLI_TRACTATES_EN[b_str]} {daf_num}{amud}:{verse_int}"
    elif b_str.startswith('ירושלמי '):
        masechet_base = b_str.replace('ירושלמי ', '', 1).strip()
        if masechet_base in YERUSHALMI_TRACTATES_EN:
            base_ref_en = f"Jerusalem Talmud {YERUSHALMI_TRACTATES_EN[masechet_base]} {chap_int}:{verse_int}"
    elif b_str.startswith('שולחן ערוך '):
        if b_str in SHULCHAN_ARUCH_EN:
            base_ref_en = f"{SHULCHAN_ARUCH_EN[b_str]} {chap_int}:{verse_int}"
    elif b_str in MISHNAH_BOOKS_EN:
        base_ref_en = f"Mishnah {MISHNAH_BOOKS_EN[b_str]} {chap_int}:{verse_int}"

    # שיטה 1: אם יש לנו שם באנגלית, מבקשים מיד את כל המפרשים של הפסוק
    if base_ref_en:
        data = _fetch_sefaria_json_cached(base_ref_en, "commentary=1&context=0&pad=0")
        if data and isinstance(data.get('commentary'), list):
            for c_item in data['commentary']:
                c_title_he = c_item.get('collectiveTitle', {}).get('he', '') if isinstance(c_item.get('collectiveTitle'), dict) else str(c_item.get('collectiveTitle', ''))
                c_name_he = str(c_item.get('commentator', ''))
                
                # אם זה המפרש שלנו, נוסיף את כל הפירושים שלו לפסוק הזה! בלי לחתוך!
                if pref_commentator_he in c_title_he or pref_commentator_he in c_name_he:
                    extracted = _extract_sefaria_he_list(c_item.get('he', []))
                    for ex in extracted:
                        if ex not in comments_out:
                            comments_out.append(ex)
            
            if comments_out:
                payload = {'commentator': target_commentator, 'comments': comments_out}
                cache.set(cache_key, payload, 3600 * 24)
                return payload

    # שיטה 2: גיבוי בעברית - אם ספריא לא הבין את השם באנגלית או שזה רמב"ם
    direct_refs = []
    if b_str in TANAKH_NAMES:
        direct_refs.append(f'רש"י על {b_str} {int_to_hebrew(chap_int)}:{int_to_hebrew(verse_int)}')
    elif c_str.startswith('דף') and not b_str.startswith('ירושלמי '):
        amud_heb = 'ב' if ('עמוד ב' in c_str or ':' in c_str) else 'א'
        direct_refs.append(f'רש"י על {b_str} {int_to_hebrew(max(2, chap_int))} {amud_heb}:{int_to_hebrew(verse_int)}')
    elif b_str.startswith('ירושלמי '):
        masechet = b_str.replace('ירושלמי ', '', 1).strip()
        direct_refs.append(f'פני משה על תלמוד ירושלמי {masechet} {int_to_hebrew(chap_int)}:{int_to_hebrew(verse_int)}')
    elif b_str.startswith('שולחן ערוך '):
        chelek = b_str.replace('שולחן ערוך ', '', 1).strip()
        direct_refs.append(f'באר היטב על שולחן ערוך, {chelek} {int_to_hebrew(chap_int)}:{int_to_hebrew(verse_int)}')
    elif b_str.startswith('רמב"ם '):
        hilchot = b_str.replace('רמב"ם ', '', 1).strip()
        direct_refs.append(f'מגיד משנה על משנה תורה, {hilchot} {int_to_hebrew(chap_int)}:{int_to_hebrew(verse_int)}')
    elif b_str in MISHNAH_BOOKS:
        direct_refs.append(f'ברטנורא על משנה {b_str} {int_to_hebrew(chap_int)}:{int_to_hebrew(verse_int)}')

    for d_ref in direct_refs:
        c_data = _fetch_sefaria_json_cached(d_ref)
        if c_data and c_data.get('he'):
            comments_out = _extract_sefaria_he_list(c_data['he'])
            if comments_out:
                payload = {'commentator': target_commentator, 'comments': comments_out}
                cache.set(cache_key, payload, 3600 * 24)
                return payload

    return {'commentator': target_commentator, 'comments': []}


@ratelimit(rate=45, timeout=60)
def tanakh_advanced_search_api(request):
    query_type = request.GET.get('type', 'text').strip()
    query_val = request.GET.get('q', '').strip()
    book_filter = request.GET.get('book', 'torah').strip()
    is_exact = request.GET.get('exact', 'false').lower() == 'true'
    exclude_books_param = request.GET.get('exclude_books', '').strip()
    skip_param = request.GET.get('skip', '').strip()
    try:
        page = max(1, int(request.GET.get('page', 1)))
    except (ValueError, TypeError):
        page = 1

    def get_verse_label(book_name, chapter_name):
        b_str, c_str = str(book_name), str(chapter_name)
        if b_str.startswith('שולחן ערוך '):
            return 'סעיף'
        elif b_str.startswith(('רמב"ם ', 'רמב״ם ', 'ירושלמי ', 'תוספתא ')):
            return 'הלכה'
        elif c_str.startswith('דף'):
            return 'שורה'
        elif b_str not in TANAKH_NAMES:
            return 'משנה'
        return 'פסוק'

    if query_type == 'book_chapters':
        target_book = _resolve_torah_book_in_db(request.GET.get('target_book', '').strip())
        corpus_hint = request.GET.get('corpus', '').strip()
        if not target_book:
            return JsonResponse({'chapters': []})

        ch_qs = TorahText.objects.filter(book=target_book)
        if target_book in MISHNAH_BOOKS:
            if corpus_hint == 'talmud':
                ch_qs = ch_qs.filter(chapter__startswith='דף')
            elif corpus_hint == 'mishnah':
                ch_qs = ch_qs.exclude(chapter__startswith='דף')

        chapters_list = list(ch_qs.values_list('chapter', flat=True).distinct())
        chapters_list.sort(key=safe_int)
        return JsonResponse({
            'book': target_book,
            'chapters': chapters_list
        }, json_dumps_params={'ensure_ascii': False})

    if query_type == 'commentary':
        t_book = request.GET.get('target_book', '').strip()
        t_chap = request.GET.get('target_chapter', '').strip()
        t_verse = request.GET.get('target_verse', '').strip()
        if t_book and t_chap and t_verse:
            comm_data = _fetch_commentary_for_source(t_book, t_chap, t_verse)
            return JsonResponse(comm_data, json_dumps_params={'ensure_ascii': False})
        return JsonResponse({'commentator': '', 'comments': []})

    if query_type == 'chapter_context':
        target_book = _resolve_torah_book_in_db(request.GET.get('target_book', '').strip())
        target_chapter = request.GET.get('target_chapter', '').strip()
        if target_book and target_chapter:
            ch_verses = list(
                TorahText.objects.filter(book=target_book, chapter=target_chapter)
                .values('verse', 'text_with_nikkud', 'clean_text')
            )
            ch_verses.sort(key=lambda x: safe_int(x['verse']))
            return JsonResponse({
                'book': target_book,
                'chapter': target_chapter,
                'verse_label': get_verse_label(target_book, target_chapter),
                'verses': [
                    {
                        'verse': format_verse_hebrew(v['verse']),
                        'raw_verse': v['verse'],
                        'text': format_divine_name(v['text_with_nikkud'] or v['clean_text'] or '')
                    }
                    for v in ch_verses
                ]
            }, json_dumps_params={'ensure_ascii': False})
        return JsonResponse({'verses': []})

    if query_type == 'quick_open':
        explicit_book = request.GET.get('target_book', '').strip()
        explicit_chapter = request.GET.get('target_chapter', '').strip()
        corpus_hint = request.GET.get('corpus', '').strip()

        matched_book = _resolve_torah_book_in_db(explicit_book)
        if not matched_book:
            return JsonResponse({'error': 'נא לבחור ספר ופרק לעיון.'})

        ch_qs = TorahText.objects.filter(book=matched_book)
        if matched_book in MISHNAH_BOOKS:
            if corpus_hint == 'talmud' or explicit_chapter.startswith('דף'):
                ch_qs = ch_qs.filter(chapter__startswith='דף')
            elif corpus_hint == 'mishnah' or not explicit_chapter.startswith('דף'):
                ch_qs = ch_qs.exclude(chapter__startswith='דף')

        raw_chapters = list(ch_qs.values_list('chapter', flat=True).distinct())
        if not raw_chapters:
            raw_chapters = list(TorahText.objects.filter(book=matched_book).values_list('chapter', flat=True).distinct())

        raw_chapters.sort(key=safe_int)
        if not raw_chapters:
            return JsonResponse({'error': f'לא נמצאו פרקים עבור "{matched_book}".'})

        chosen_chapter = explicit_chapter if explicit_chapter in raw_chapters else raw_chapters[0]

        ch_verses = list(
            TorahText.objects.filter(book=matched_book, chapter=chosen_chapter)
            .values('verse', 'text_with_nikkud', 'clean_text')
        )
        ch_verses.sort(key=lambda x: safe_int(x['verse']))

        curr_idx = raw_chapters.index(chosen_chapter) if chosen_chapter in raw_chapters else 0
        prev_ch = raw_chapters[curr_idx - 1] if curr_idx > 0 else None
        next_ch = raw_chapters[curr_idx + 1] if curr_idx < len(raw_chapters) - 1 else None

        return JsonResponse({
            'book': matched_book,
            'chapter': chosen_chapter,
            'all_chapters': raw_chapters,
            'prev_chapter': prev_ch,
            'next_chapter': next_ch,
            'verse_label': get_verse_label(matched_book, chosen_chapter),
            'verses': [
                {
                    'verse': format_verse_hebrew(v['verse']),
                    'raw_verse': v['verse'],
                    'text': format_divine_name(v['text_with_nikkud'] or v['clean_text'] or '')
                }
                for v in ch_verses
            ]
        }, json_dumps_params={'ensure_ascii': False})

    try:
        per_page = int(request.GET.get('per_page', 10))
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except ValueError:
        per_page = 10

    search_cache_key = f"tanakh_srch_v20_{query_type}_{query_val}_{book_filter}_{is_exact}_{exclude_books_param}_{skip_param}_{page}_{per_page}"
    cached_search_data = cache.get(search_cache_key)
    if cached_search_data:
        return JsonResponse(cached_search_data, json_dumps_params={'ensure_ascii': False})

    results = []
    qs = TorahText.objects.all()

    selected_corpora = [b.strip() for b in book_filter.split(',') if b.strip()]
    known_corpora = {'torah', 'tanakh', 'mishnah', 'tosefta', 'talmud', 'yerushalmi', 'rambam', 'shulchan_aruch', 'all'}

    if not selected_corpora:
        selected_corpora = ['torah']

    if 'all' in selected_corpora:
        pass
    elif any(c in known_corpora for c in selected_corpora):
        corpus_q = Q()
        if 'torah' in selected_corpora:
            corpus_q |= (Q(book__in=TORAH_NAMES) & ~Q(chapter__startswith='דף'))
        if 'tanakh' in selected_corpora:
            corpus_q |= (Q(book__in=TANAKH_NAMES) & ~Q(book__in=MISHNAH_BOOKS) & ~Q(chapter__startswith='דף'))
        if 'mishnah' in selected_corpora:
            corpus_q |= (
                ~Q(book__in=TANAKH_NAMES) &
                ~Q(chapter__startswith='דף') &
                ~Q(book__startswith='ירושלמי ') &
                ~Q(book__startswith='תוספתא ') &
                ~Q(book__startswith='רמב"ם ') &
                ~Q(book__startswith='שולחן ערוך ')
            )
        if 'tosefta' in selected_corpora:
            corpus_q |= Q(book__startswith='תוספתא ')
        if 'talmud' in selected_corpora:
            corpus_q |= (Q(chapter__startswith='דף') & ~Q(book__startswith='ירושלמי '))
        if 'yerushalmi' in selected_corpora:
            corpus_q |= Q(book__startswith='ירושלמי ')
        if 'rambam' in selected_corpora:
            corpus_q |= Q(book__startswith='רמב"ם ')
        if 'shulchan_aruch' in selected_corpora:
            corpus_q |= Q(book__startswith='שולחן ערוך ')
        qs = qs.filter(corpus_q)
    else:
        qs = qs.filter(book__icontains=book_filter)

    if exclude_books_param:
        excluded = [b.strip() for b in exclude_books_param.split(',') if b.strip()]
        for ex in excluded:
            if ':' in ex:
                cat, b_name = ex.split(':', 1)
                b_name = b_name.strip()
                if cat in ['torah', 'tanakh', 'tosefta', 'yerushalmi', 'rambam', 'shulchan_aruch']:
                    qs = qs.exclude(book=b_name)
                elif cat == 'mishnah':
                    qs = qs.exclude(Q(book=b_name) & ~Q(chapter__startswith='דף'))
                elif cat == 'talmud':
                    qs = qs.exclude(Q(book=b_name) & Q(chapter__startswith='דף'))
            else:
                qs = qs.exclude(book=ex)

    FINAL_TO_REGULAR = str.maketrans({'ך': 'כ', 'ם': 'מ', 'ן': 'נ', 'ף': 'פ', 'ץ': 'צ'})
    REGULAR_TO_FINAL = {'כ': 'ך', 'מ': 'ם', 'נ': 'ן', 'פ': 'ף', 'צ': 'ץ'}

    def norm_heb(s):
        return s.translate(FINAL_TO_REGULAR)

    WORD_TOKEN_RE = re.compile(r'[א-ת\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]+')
    HEB_LETTER_CLUSTER_RE = re.compile(r'[א-ת][\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]*')

    calculated_gematria_val = None
    reversed_query_val = None
    available_skips = []
    active_skip = int(skip_param) if skip_param.isdigit() else None

    try:
        if query_type in ['text', 'text_exact', 'text_broad'] and query_val:
            if query_type == 'text_exact':
                is_exact = True
            elif query_type == 'text_broad':
                is_exact = False

            q_normalized = query_val.replace('י-ה-ו-ה', 'יהוה')
            q_no_nikkud = re.sub(r'[^א-ת\s]', '', q_normalized).strip()
            q_words = q_no_nikkud.split()

            if q_words:
                num_q_words = len(q_words)
                text_query = Q()
                for target_w in q_words:
                    text_query &= (Q(clean_text__icontains=target_w) | Q(text_with_nikkud__icontains=target_w))

                qs = qs.filter(text_query)
                all_verses = qs.values('book', 'chapter', 'verse', 'text_with_nikkud').iterator(chunk_size=2000)

                for m in all_verses:
                    raw_text = m.get('text_with_nikkud') or ""
                    if not raw_text:
                        continue

                    tokens = list(WORD_TOKEN_RE.finditer(raw_text))
                    clean_words = []
                    valid_spans = []
                    for tok in tokens:
                        w_heb = re.sub(r'[^א-ת]', '', tok.group(0))
                        if w_heb:
                            clean_words.append(w_heb)
                            valid_spans.append(tok.span())

                    if len(clean_words) < num_q_words:
                        continue

                    matched_indices = set()
                    if num_q_words == 1:
                        target = q_words[0]
                        for idx, vw_clean in enumerate(clean_words):
                            if is_exact:
                                if vw_clean == target:
                                    matched_indices.add(idx)
                            else:
                                if target in vw_clean:
                                    matched_indices.add(idx)
                    else:
                        for i in range(len(clean_words) - num_q_words + 1):
                            seq_match = True
                            for j in range(num_q_words):
                                target = q_words[j]
                                current_vw = clean_words[i + j]
                                if is_exact:
                                    if current_vw != target:
                                        seq_match = False
                                        break
                                else:
                                    if target not in current_vw:
                                        seq_match = False
                                        break
                            if seq_match:
                                for j in range(num_q_words):
                                    matched_indices.add(i + j)

                    if matched_indices:
                        out_parts = []
                        last_idx = 0
                        for w_i, (s_idx, e_idx) in enumerate(valid_spans):
                            out_parts.append(raw_text[last_idx:s_idx])
                            word_str = raw_text[s_idx:e_idx]
                            if w_i in matched_indices:
                                out_parts.append(f'<mark style="background-color: rgba(255, 235, 59, 0.45); padding: 0 4px; border-radius: 4px; font-weight: bold;">{word_str}</mark>')
                            else:
                                out_parts.append(word_str)
                            last_idx = e_idx
                        out_parts.append(raw_text[last_idx:])
                        highlighted_text = "".join(out_parts)

                        results.append({
                            'book': m['book'],
                            'chapter': m['chapter'],
                            'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'],
                            'verse_label': get_verse_label(m['book'], m['chapter']),
                            'text': highlighted_text,
                            'match_type': 'חיפוש מדויק' if is_exact else 'חיפוש חופשי (רחב)'
                        })

        elif query_type == 'gematria' and query_val:
            def calc_word_gem(w):
                clean_w = re.sub(r'[^א-ת]', '', w)
                return sum(HEBREW_GEMATRIA.get(c, 0) for c in clean_w)

            if query_val.isdigit():
                target_val = int(query_val)
            else:
                target_val = calc_word_gem(query_val)

            calculated_gematria_val = target_val

            if target_val > 0:
                search_str = f",{target_val},"
                matching_qs = qs.filter(Q(verse_gematria=target_val) | Q(words_gematria__contains=search_str))
                all_verses = matching_qs.values('book', 'chapter', 'verse', 'text_with_nikkud', 'verse_gematria').iterator(chunk_size=2000)

                for m in all_verses:
                    raw_text = m['text_with_nikkud']
                    if m['verse_gematria'] == target_val:
                        m_type = f'גימטריה מלאה לפסוק (הערך: {target_val})'
                        final_text = f'<mark style="background-color: rgba(255, 235, 59, 0.4); padding: 0 4px; border-radius: 4px; color: inherit;">{raw_text}</mark>'
                    else:
                        m_type = f'גימטריה למילה בפסוק (הערך: {target_val})'

                        def highlight_word(match):
                            word = match.group(0)
                            if calc_word_gem(word) == target_val:
                                return f'<mark style="background-color: rgba(255, 235, 59, 0.4); padding: 0 4px; border-radius: 4px; color: inherit;">{word}</mark>'
                            return word

                        final_text = WORD_TOKEN_RE.sub(highlight_word, raw_text)

                    results.append({
                        'book': m['book'],
                        'chapter': m['chapter'],
                        'verse': format_verse_hebrew(m['verse']),
                        'raw_verse': m['verse'],
                        'verse_label': get_verse_label(m['book'], m['chapter']),
                        'text': final_text,
                        'match_type': m_type
                    })

        elif query_type in ['acronym', 'rashei_tevot', 'sofei_tevot', 'suffix'] and query_val:
            is_sofei = query_type in ['sofei_tevot', 'suffix']
            target_acr = norm_heb(re.sub(r'[^א-ת]', '', query_val))

            if target_acr:
                acr_len = len(target_acr)
                all_verses = qs.values('book', 'chapter', 'verse', 'text_with_nikkud').iterator(chunk_size=2000)

                for m in all_verses:
                    raw_text = m.get('text_with_nikkud') or ""
                    if not raw_text:
                        continue

                    tokens = list(WORD_TOKEN_RE.finditer(raw_text))
                    clean_words = []
                    valid_token_spans = []

                    for tok in tokens:
                        w_heb = re.sub(r'[^א-ת]', '', tok.group(0))
                        if w_heb:
                            clean_words.append(norm_heb(w_heb))
                            valid_token_spans.append(tok.span())

                    if len(clean_words) < acr_len:
                        continue

                    if is_sofei:
                        letters_seq = "".join([w[-1] for w in clean_words])
                    else:
                        letters_seq = "".join([w[0] for w in clean_words])

                    match_pos = letters_seq.find(target_acr)
                    if match_pos != -1:
                        matched_word_indices = set()
                        while match_pos != -1:
                            for idx in range(match_pos, match_pos + acr_len):
                                matched_word_indices.add(idx)
                            match_pos = letters_seq.find(target_acr, match_pos + 1)

                        out_parts = []
                        last_idx = 0
                        for w_i, (s_idx, e_idx) in enumerate(valid_token_spans):
                            out_parts.append(raw_text[last_idx:s_idx])
                            word_str = raw_text[s_idx:e_idx]
                            if w_i in matched_word_indices:
                                out_parts.append(f'<mark style="background-color: rgba(255, 235, 59, 0.45); padding: 0 4px; border-radius: 4px; font-weight: bold;">{word_str}</mark>')
                            else:
                                out_parts.append(word_str)
                            last_idx = e_idx
                        out_parts.append(raw_text[last_idx:])
                        final_text = "".join(out_parts)

                        results.append({
                            'book': m['book'],
                            'chapter': m['chapter'],
                            'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'],
                            'verse_label': get_verse_label(m['book'], m['chapter']),
                            'text': final_text,
                            'match_type': f'סופי תיבות ({query_val})' if is_sofei else f'ראשי תיבות ({query_val})'
                        })

        elif query_type in ['reverse', 'palindrome'] and query_val:
            q_words_raw = re.findall(r'[א-ת]+', query_val)
            if q_words_raw:
                rev_words = []
                for w in q_words_raw:
                    rev_raw = w[::-1]
                    if len(rev_raw) > 1:
                        base_norm = norm_heb(rev_raw[:-1])
                        last_c = norm_heb(rev_raw[-1])
                        last_c_final = REGULAR_TO_FINAL.get(last_c, last_c)
                        rev_words.append(base_norm + last_c_final)
                    else:
                        rev_words.append(rev_raw)

                reversed_query_val = " ".join(rev_words)
                rev_words_norm = [norm_heb(rw) for rw in rev_words]
                num_q_words = len(rev_words_norm)

                text_query = Q()
                for rw, rw_norm in zip(rev_words, rev_words_norm):
                    text_query &= (
                        Q(clean_text__icontains=rw) |
                        Q(clean_text__icontains=rw_norm) |
                        Q(text_with_nikkud__icontains=rw)
                    )
                qs = qs.filter(text_query)
                all_verses = qs.values('book', 'chapter', 'verse', 'text_with_nikkud').iterator(chunk_size=2000)

                for m in all_verses:
                    raw_text = m.get('text_with_nikkud') or ""
                    if not raw_text:
                        continue

                    tokens = list(WORD_TOKEN_RE.finditer(raw_text))
                    clean_words_norm = []
                    valid_spans = []
                    for tok in tokens:
                        w_heb = re.sub(r'[^א-ת]', '', tok.group(0))
                        if w_heb:
                            clean_words_norm.append(norm_heb(w_heb))
                            valid_spans.append(tok.span())

                    if len(clean_words_norm) < num_q_words:
                        continue

                    matched_indices = set()
                    for i in range(len(clean_words_norm) - num_q_words + 1):
                        seq_ok = True
                        for j in range(num_q_words):
                            if clean_words_norm[i + j] != rev_words_norm[j]:
                                seq_ok = False
                                break
                        if seq_ok:
                            for j in range(num_q_words):
                                matched_indices.add(i + j)

                    if matched_indices:
                        out_parts = []
                        last_idx = 0
                        for w_i, (s_idx, e_idx) in enumerate(valid_spans):
                            out_parts.append(raw_text[last_idx:s_idx])
                            word_str = raw_text[s_idx:e_idx]
                            if w_i in matched_indices:
                                out_parts.append(f'<mark style="background-color: rgba(255, 235, 59, 0.45); padding: 0 4px; border-radius: 4px; font-weight: bold;">{word_str}</mark>')
                            else:
                                out_parts.append(word_str)
                            last_idx = e_idx
                        out_parts.append(raw_text[last_idx:])
                        final_text = "".join(out_parts)

                        is_palindrome = (norm_heb("".join(q_words_raw)) == "".join(rev_words_norm))
                        m_label = f'פלינדרום ("{reversed_query_val}")' if is_palindrome else f'מילה הפוכה: "{reversed_query_val}"'

                        results.append({
                            'book': m['book'],
                            'chapter': m['chapter'],
                            'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'],
                            'verse_label': get_verse_label(m['book'], m['chapter']),
                            'text': final_text,
                            'match_type': m_label
                        })

        elif query_type in ['els', 'skip', 'dilugim'] and query_val:
            target_els = norm_heb(re.sub(r'[^א-ת]', '', query_val))
            k = len(target_els)
            if k >= 2:
                all_verses = qs.values('book', 'chapter', 'verse', 'text_with_nikkud').iterator(chunk_size=2000)
                skip_counts = {}

                for m in all_verses:
                    raw_text = m.get('text_with_nikkud') or ""
                    if not raw_text:
                        continue

                    tokens = list(WORD_TOKEN_RE.finditer(raw_text))
                    verse_skip_matches = {}

                    for tok_i, tok in enumerate(tokens):
                        word_str = tok.group(0)
                        clusters = list(HEB_LETTER_CLUSTER_RE.finditer(word_str))
                        n = len(clusters)
                        if n < k:
                            continue

                        w_norm = "".join([norm_heb(c.group(0)[0]) for c in clusters])

                        if w_norm == target_els:
                            verse_skip_matches.setdefault(0, []).append((tok_i, set(range(n)), word_str))

                        for pos0 in range(n):
                            if w_norm[pos0] != target_els[0]:
                                continue
                            max_step = (n - 1 - pos0) // (k - 1)
                            for step in range(2, max_step + 1):
                                if w_norm[pos0 : pos0 + k * step : step] == target_els:
                                    skip_d = step - 1
                                    letter_idxs = {pos0 + idx * step for idx in range(k)}
                                    verse_skip_matches.setdefault(skip_d, []).append((tok_i, letter_idxs, word_str))

                    if verse_skip_matches:
                        for s_d in verse_skip_matches.keys():
                            skip_counts[s_d] = skip_counts.get(s_d, 0) + 1

                        if active_skip is not None:
                            if active_skip not in verse_skip_matches:
                                continue
                            chosen_skip = active_skip
                        else:
                            non_zero = [s for s in verse_skip_matches.keys() if s > 0]
                            chosen_skip = min(non_zero) if non_zero else 0

                        matched_tokens_map = {}
                        matched_words_sample = []
                        for tok_i, letter_idxs, w_str in verse_skip_matches[chosen_skip]:
                            matched_tokens_map.setdefault(tok_i, set()).update(letter_idxs)
                            if w_str not in matched_words_sample:
                                matched_words_sample.append(w_str)

                        out_parts = []
                        last_idx = 0
                        for tok_i, tok in enumerate(tokens):
                            s_idx, e_idx = tok.span()
                            out_parts.append(raw_text[last_idx:s_idx])
                            word_str = raw_text[s_idx:e_idx]
                            if tok_i in matched_tokens_map:
                                target_positions = matched_tokens_map[tok_i]
                                c_idx = [-1]

                                def mark_cluster(c_match):
                                    c_idx[0] += 1
                                    cl = c_match.group(0)
                                    if c_idx[0] in target_positions:
                                        return f'<strong style="color: #9c6500; text-decoration: underline;">{cl}</strong>'
                                    return cl

                                marked_word = HEB_LETTER_CLUSTER_RE.sub(mark_cluster, word_str)
                                out_parts.append(f'<mark style="background-color: rgba(255, 235, 59, 0.45); padding: 0 4px; border-radius: 4px;">{marked_word}</mark>')
                            else:
                                out_parts.append(word_str)
                            last_idx = e_idx
                        out_parts.append(raw_text[last_idx:])
                        final_text = "".join(out_parts)

                        sample_w = matched_words_sample[0] if matched_words_sample else ""
                        if chosen_skip == 0:
                            m_type = f'דילוג 0 במילה ({sample_w})'
                        else:
                            m_type = f'דילוג {chosen_skip} במילה: "{sample_w}"'

                        results.append({
                            'book': m['book'],
                            'chapter': m['chapter'],
                            'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'],
                            'verse_label': get_verse_label(m['book'], m['chapter']),
                            'text': final_text,
                            'match_type': m_type,
                            'skip_distance': chosen_skip
                        })

                available_skips = [
                    {'skip': s_d, 'count': skip_counts[s_d]}
                    for s_d in sorted(skip_counts.keys())
                ]

        elif query_type == 'els_verse' and query_val:
            target_els = norm_heb(re.sub(r'[^א-ת]', '', query_val))
            k = len(target_els)
            if k >= 2:
                t0 = target_els[0]
                t1 = target_els[1]
                max_skip_limit = 25
                NON_HEB_RE = re.compile(r'[^א-ת]+')

                all_verses = qs.values('book', 'chapter', 'verse', 'text_with_nikkud').iterator(chunk_size=2000)
                skip_counts = {}

                for m in all_verses:
                    raw_text = m.get('text_with_nikkud') or ""
                    if not raw_text:
                        continue

                    letters_str = NON_HEB_RE.sub('', raw_text).translate(FINAL_TO_REGULAR)
                    n = len(letters_str)
                    if n < k:
                        continue

                    tokens = list(WORD_TOKEN_RE.finditer(raw_text))
                    letter_to_word_idx = []
                    for tok_i, tok in enumerate(tokens):
                        w_heb_len = len(NON_HEB_RE.sub('', tok.group(0)))
                        letter_to_word_idx.extend([tok_i] * w_heb_len)

                    verse_skip_matches = {}
                    pos0 = letters_str.find(t0)
                    while pos0 != -1:
                        max_step = min(max_skip_limit + 1, (n - 1 - pos0) // (k - 1))
                        if max_step >= 1:
                            pos1 = letters_str.find(t1, pos0 + 1, pos0 + max_step + 1)
                            while pos1 != -1:
                                step = pos1 - pos0
                                if k == 2 or letters_str[pos0 : pos0 + k * step : step] == target_els:
                                    skip_d = step - 1
                                    positions = [pos0 + idx * step for idx in range(k)]
                                    word_idxs = {letter_to_word_idx[p] for p in positions if p < len(letter_to_word_idx)}
                                    is_cross = len(word_idxs) > 1
                                    if skip_d not in verse_skip_matches or (is_cross and not verse_skip_matches[skip_d][2]):
                                        verse_skip_matches[skip_d] = (set(positions), word_idxs, is_cross)
                                pos1 = letters_str.find(t1, pos1 + 1, pos0 + max_step + 1)
                        pos0 = letters_str.find(t0, pos0 + 1)

                    if verse_skip_matches:
                        for s_d in verse_skip_matches.keys():
                            skip_counts[s_d] = skip_counts.get(s_d, 0) + 1

                        if active_skip is not None:
                            if active_skip not in verse_skip_matches:
                                continue
                            chosen_skip = active_skip
                        else:
                            cross_skips = [s for s, val in verse_skip_matches.items() if val[2] and s > 0]
                            non_zero = [s for s in verse_skip_matches.keys() if s > 0]
                            if cross_skips:
                                chosen_skip = min(cross_skips)
                            elif non_zero:
                                chosen_skip = min(non_zero)
                            else:
                                chosen_skip = 0

                        target_global_positions, participating_words, is_cross_word = verse_skip_matches[chosen_skip]

                        out_parts = []
                        last_idx = 0
                        global_letter_idx = [-1]

                        for tok_i, tok in enumerate(tokens):
                            s_idx, e_idx = tok.span()
                            out_parts.append(raw_text[last_idx:s_idx])
                            word_str = raw_text[s_idx:e_idx]

                            def mark_verse_cluster(c_match):
                                global_letter_idx[0] += 1
                                cl = c_match.group(0)
                                if global_letter_idx[0] in target_global_positions:
                                    return f'<strong style="background-color: #ffca28; color: #000; padding: 0 3px; border-radius: 3px; border-bottom: 2px solid #b8860b;">{cl}</strong>'
                                return cl

                            marked_word = HEB_LETTER_CLUSTER_RE.sub(mark_verse_cluster, word_str)
                            if tok_i in participating_words:
                                out_parts.append(f'<mark style="background-color: rgba(255, 235, 59, 0.28); padding: 0 3px; border-radius: 4px;">{marked_word}</mark>')
                            else:
                                out_parts.append(marked_word)
                            last_idx = e_idx

                        out_parts.append(raw_text[last_idx:])
                        final_text = "".join(out_parts)

                        cross_label = "חוצה מילים" if is_cross_word else "באותה מילה"
                        if chosen_skip == 0:
                            m_type = f'דילוג 0 בפסוק ({cross_label})'
                        else:
                            m_type = f'דילוג {chosen_skip} בפסוק ({cross_label})'

                        results.append({
                            'book': m['book'],
                            'chapter': m['chapter'],
                            'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'],
                            'verse_label': get_verse_label(m['book'], m['chapter']),
                            'text': final_text,
                            'match_type': m_type,
                            'skip_distance': chosen_skip
                        })

                available_skips = [
                    {'skip': s_d, 'count': skip_counts[s_d]}
                    for s_d in sorted(skip_counts.keys())
                ]

        results.sort(key=lambda x: (get_book_order(x['book'], x.get('chapter', '')), safe_int(x['chapter']), safe_int(x.get('raw_verse') or x['verse'])))

        total_results = len(results)
        total_pages = (total_results + per_page - 1) // per_page if total_results > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_results = results[start_idx:end_idx]

        for item in paginated_results:
            item['text'] = format_divine_name(item.get('text', ''))

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    response_payload = {
        'results': paginated_results,
        'total': total_results,
        'page': page,
        'total_pages': total_pages,
        'per_page': per_page,
        'calculated_gematria': calculated_gematria_val,
        'reversed_query': reversed_query_val,
        'available_skips': available_skips,
        'active_skip': active_skip
    }
    cache.set(search_cache_key, response_payload, 900)
    return JsonResponse(response_payload, json_dumps_params={'ensure_ascii': False})


@ratelimit(rate=30, timeout=60)
def torah_ai_insights_api(request):
    mode = request.GET.get('mode', 'code_finder').strip()
    query = request.GET.get('q', '').strip()
    book = _resolve_torah_book_in_db(request.GET.get('book', '').strip())
    chapter = request.GET.get('chapter', '').strip()
    verse = request.GET.get('verse', '').strip()

    cache_key = f"torah_ai_v20_{mode}_{book}_{chapter}_{verse}_{query}"
    cached_resp = cache.get(cache_key)
    if cached_resp:
        return JsonResponse(cached_resp, json_dumps_params={'ensure_ascii': False})

    FINAL_TO_REGULAR = str.maketrans({'ך': 'כ', 'ם': 'מ', 'ן': 'נ', 'ף': 'פ', 'ץ': 'צ'})
    REGULAR_TO_FINAL = {'כ': 'ך', 'מ': 'ם', 'נ': 'ן', 'פ': 'ף', 'צ': 'ץ'}
    NON_HEB_RE = re.compile(r'[^א-ת]+')
    WORD_TOKEN_RE = re.compile(r'[א-ת\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]+')
    HEB_LETTER_CLUSTER_RE = re.compile(r'[א-ת][\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]*')

    def norm_heb(s):
        return s.translate(FINAL_TO_REGULAR)

    def reverse_heb_word(w):
        rev = w[::-1]
        if len(rev) <= 1:
            return rev
        base = norm_heb(rev[:-1])
        last_c = norm_heb(rev[-1])
        return base + REGULAR_TO_FINAL.get(last_c, last_c)

    def extract_highlighted_snippet(raw_text, matched_spans, max_len=340):
        if not raw_text:
            return ""
        if not matched_spans:
            trimmed = raw_text[:max_len] + ("..." if len(raw_text) > max_len else "")
            return format_divine_name(trimmed)

        first_s, first_e = matched_spans[0]
        if len(raw_text) > max_len:
            half = max_len // 2
            win_start = max(0, first_s - half)
            win_end = min(len(raw_text), first_e + half)
            if win_start > 0:
                sp = raw_text.find(' ', win_start)
                if sp != -1 and sp < first_s:
                    win_start = sp + 1
            if win_end < len(raw_text):
                sp = raw_text.rfind(' ', first_e, win_end)
                if sp != -1:
                    win_end = sp
        else:
            win_start, win_end = 0, len(raw_text)

        out = []
        if win_start > 0:
            out.append("... ")
        last_pos = win_start
        for s_idx, e_idx in matched_spans:
            if s_idx < win_start or e_idx > win_end:
                continue
            out.append(raw_text[last_pos:s_idx])
            out.append(f'<mark style="background-color: #fde047; color: #000; padding: 0 4px; border-radius: 4px; font-weight: bold;">{raw_text[s_idx:e_idx]}</mark>')
            last_pos = e_idx
        out.append(raw_text[last_pos:win_end])
        if win_end < len(raw_text):
            out.append(" ...")
        return format_divine_name("".join(out))

    torah_set = set(TORAH_NAMES)
    tanakh_set = set(TANAKH_NAMES)

    try:
        if mode == 'code_finder':
            verse_obj = None
            if book and chapter and verse:
                verse_obj = _resolve_torah_verse_obj(book, chapter, verse)
            elif query:
                clean_q = re.sub(r'[^א-ת\s]', '', query).strip()
                verse_obj = TorahText.objects.filter(clean_text__icontains=clean_q).first()

            if not verse_obj:
                return JsonResponse({'error': 'לא נמצא פסוק או מקור לניתוח.'}, status=404)

            v_heb_disp = format_verse_hebrew(verse_obj.verse)
            raw_text = format_divine_name(verse_obj.text_with_nikkud or verse_obj.clean_text)
            toks_v = [NON_HEB_RE.sub('', m.group(0)) for m in WORD_TOKEN_RE.finditer(raw_text)]
            clean_words = [w for w in toks_v if len(w) >= 2]
            v_gem = verse_obj.verse_gematria or calculate_gematria(verse_obj.clean_text or '')

            equal_verses_qs = TorahText.objects.filter(book__in=TANAKH_NAMES, verse_gematria=v_gem).exclude(id=verse_obj.id).exclude(chapter__startswith='דף')[:4]
            equal_verses = [
                {
                    'ref': f"{ev.book} {ev.chapter}:{format_verse_hebrew(ev.verse)}",
                    'text': format_divine_name(ev.text_with_nikkud or ev.clean_text)
                }
                for ev in equal_verses_qs
            ]

            word_gem_matches = []
            seen_words = set()
            for w in clean_words:
                if len(w) >= 2 and w not in seen_words:
                    seen_words.add(w)
                    w_val = calculate_gematria(w)
                    for concept in TORAH_CORE_CONCEPTS:
                        if concept != w and calculate_gematria(concept) == w_val:
                            word_gem_matches.append({'word': w, 'concept': concept, 'val': w_val})
                    if len(word_gem_matches) >= 6:
                        break

            letters_seq = NON_HEB_RE.sub('', raw_text).translate(FINAL_TO_REGULAR)
            els_findings = []
            n_len = len(letters_seq)

            for concept in TORAH_CORE_CONCEPTS:
                c_norm = norm_heb(concept)
                k = len(c_norm)
                if k < 3 or n_len < k:
                    continue
                found_for_concept = False
                for pos0 in range(n_len):
                    if letters_seq[pos0] != c_norm[0]:
                        continue
                    max_step = min(15, (n_len - 1 - pos0) // (k - 1))
                    for step in range(2, max_step + 1):
                        if letters_seq[pos0 : pos0 + k * step : step] == c_norm:
                            els_findings.append({'word': concept, 'skip': step - 1})
                            found_for_concept = True
                            break
                    if found_for_concept:
                        break
                if len(els_findings) >= 6:
                    break

            rashei_seq = "".join([norm_heb(w[0]) for w in clean_words])
            sofei_seq = "".join([norm_heb(w[-1]) for w in clean_words])
            acronym_findings = []

            for concept in TORAH_CORE_CONCEPTS:
                c_norm = norm_heb(concept)
                if len(c_norm) >= 3:
                    idx_r = rashei_seq.find(c_norm)
                    if idx_r != -1:
                        phrase = " ".join(clean_words[idx_r:idx_r+len(c_norm)])
                        acronym_findings.append({'type': 'ראשי תיבות', 'word': concept, 'phrase': phrase})
                    idx_s = sofei_seq.find(c_norm)
                    if idx_s != -1:
                        phrase = " ".join(clean_words[idx_s:idx_s+len(c_norm)])
                        acronym_findings.append({'type': 'סופי תיבות', 'word': concept, 'phrase': phrase})

            summary_parts = [f"המקור ב{verse_obj.book} ({verse_obj.chapter}, {v_heb_disp}) מחזיק {len(clean_words)} תיבות וערכו הגימטרי הכולל הוא {v_gem}."]
            if equal_verses:
                summary_parts.append(f"במאגר התנ\"ך נמצאה הקבלה גימטרית מדויקת ({v_gem}) לפסוק ב{equal_verses[0]['ref']}: \"{equal_verses[0]['text']}\".")
            if word_gem_matches:
                wm_str = ", ".join([f"התיבה \"{m['word']}\" שווה בגימטריה ({m['val']}) למושג \"{m['concept']}\"" for m in word_gem_matches[:3]])
                summary_parts.append(f"הקבלות גימטריה במילות המקור: {wm_str}.")
            if els_findings:
                el_str = ", ".join([f"\"{e['word']}\" (דילוג {e['skip']})" for e in els_findings[:3]])
                summary_parts.append(f"בסריקת מרווחי אותיות (ELS) לאורך המקור אותרו המושגים: {el_str}.")
            if acronym_findings:
                ac_str = ", ".join([f"{a['type']} \"{a['word']}\" בתיבות \"{a['phrase']}\"" for a in acronym_findings[:2]])
                summary_parts.append(f"ממצאי ראשי וסופי תיבות: {ac_str}.")

            resp_payload = {
                'source_ref': f"{verse_obj.book} | {verse_obj.chapter} | {v_heb_disp}",
                'text': raw_text,
                'verse_gematria': v_gem,
                'equal_verses': equal_verses,
                'word_gematria_matches': word_gem_matches,
                'els_findings': els_findings,
                'acronym_findings': acronym_findings,
                'ai_commentary': " ".join(summary_parts)
            }
            cache.set(cache_key, resp_payload, 3600 * 12)
            return JsonResponse(resp_payload, json_dumps_params={'ensure_ascii': False})

        return JsonResponse({'error': 'מצב פעולה לא חוקי.'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)