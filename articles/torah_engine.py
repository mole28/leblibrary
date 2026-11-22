import json
import urllib.request
import urllib.parse
import http.client
import socket
import re
import time
import hashlib
from functools import wraps
from django.http import JsonResponse
from django.core.cache import cache
from django.db.models import Q
from django.utils.html import strip_tags
from .models import TorahText

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
    'בראשית': 'Genesis',
    'שמות': 'Exodus',
    'ויקרא': 'Leviticus',
    'במדבר': 'Numbers',
    'דברים': 'Deuteronomy',
    'יהושע': 'Joshua',
    'שופטים': 'Judges',
    'שמואל א': 'I Samuel',
    'שמואל ב': 'II Samuel',
    'מלכים א': 'I Kings',
    'מלכים ב': 'II Kings',
    'ישעיהו': 'Isaiah',
    'ישעיה': 'Isaiah',
    'ירמיהו': 'Jeremiah',
    'ירמיה': 'Jeremiah',
    'יחזקאל': 'Ezekiel',
    'הושע': 'Hosea',
    'יואל': 'Joel',
    'עמוס': 'Amos',
    'עובדיה': 'Obadiah',
    'יונה': 'Jonah',
    'מיכה': 'Micah',
    'נחום': 'Nahum',
    'חבקוק': 'Habakkuk',
    'צפניה': 'Zephaniah',
    'חגי': 'Haggai',
    'זכריה': 'Zechariah',
    'מלאכי': 'Malachi',
    'תהלים': 'Psalms',
    'תהילים': 'Psalms',
    'משלי': 'Proverbs',
    'איוב': 'Job',
    'שיר השירים': 'Song of Songs',
    'רות': 'Ruth',
    'איכה': 'Lamentations',
    'קהלת': 'Ecclesiastes',
    'קוהלת': 'Ecclesiastes',
    'אסתר': 'Esther',
    'דניאל': 'Daniel',
    'עזרא': 'Ezra',
    'נחמיה': 'Nehemiah',
    'דברי הימים א': 'I Chronicles',
    'דברי הימים ב': 'II Chronicles',
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

TORAH_CORE_CONCEPTS = [
    'תורה', 'מצוה', 'שבת', 'אמת', 'שלום', 'חיים', 'אור', 'קדש', 'ברכה', 'חסד',
    'משה', 'אהרן', 'דוד', 'משיח', 'גאולה', 'תשובה', 'תפילה', 'צדקה', 'אמונה', 'בטחון',
    'חכמה', 'בינה', 'דעת', 'יראה', 'אהבה', 'שמחה', 'נשמה', 'רוח', 'נפש', 'כהן',
    'לוי', 'ישראל', 'ציון', 'מקדש', 'מזבח', 'קרבן', 'ברית', 'מילה', 'ציצית', 'תכלת',
    'תפילין', 'מזוזה', 'שופר', 'סוכה', 'לולב', 'אתרוג', 'מצה', 'פסח', 'סיני', 'ארון',
    'מזל', 'נס', 'פדיון', 'שכינה', 'נבואה', 'ענוה', 'טהרה'
]

_MISORDERED_TU_TZ_RE = re.compile(r'(?<![א-ת])(ט[וז])([ק-ת]+)(?![א-ת])')
_PROPER_TU_TZ_RE = re.compile(r'(?<![א-ת])([ק-ת]+)(ט[וז])(?![א-ת])')
_EDITORIAL_MARKER_RE = re.compile(r'\{\s*[א-ת"״\'׳\s]{1,6}\s*\}')
_CHAPTERS_DB_HEALED = False
_GEMATRIA_DB_HEALED = False

def _fix_hebrew_numeral_order(label: str) -> str:
    if not label:
        return ''
    return _MISORDERED_TU_TZ_RE.sub(r'\2\1', str(label))

def _resolve_chapter_in_list(explicit_chapter: str, raw_chapters: list) -> str:
    if not raw_chapters:
        return ''
    target = _fix_hebrew_numeral_order(str(explicit_chapter or '').strip())
    if not target:
        return raw_chapters[0]
    if target in raw_chapters:
        return target

    strip_re = re.compile(r'^(?:פרק|סימן|דף|הלכה|משנה|סעיף)\s+')
    clean_punct = lambda s: re.sub(r'["״\'׳\s]+', ' ', s).strip()
    t_norm = clean_punct(strip_re.sub('', target))
    t_is_daf = target.startswith('דף')
    t_is_amud_b = ('עמוד ב' in target or ':' in target or 'ע"ב' in target or 'ע״ב' in target)
    t_num = parse_hebrew_number(target)

    for ch in raw_chapters:
        ch_norm = clean_punct(strip_re.sub('', str(ch)))
        if ch_norm == t_norm:
            return ch

    if t_num > 0:
        t_heb = int_to_hebrew(t_num)
        for ch in raw_chapters:
            ch_str = str(ch)
            if t_is_daf or ch_str.startswith('דף'):
                ch_is_amud_b = ('עמוד ב' in ch_str or ':' in ch_str or 'ע"ב' in ch_str or 'ע״ב' in ch_str)
                if parse_hebrew_number(ch_str) == t_num and ch_is_amud_b == t_is_amud_b:
                    return ch
            else:
                ch_num = parse_hebrew_number(ch_str)
                if ch_num == t_num or clean_punct(strip_re.sub('', ch_str)) in (str(t_num), t_heb):
                    return ch

    return raw_chapters[0]


def _chapter_db_variants(chapter_str: str) -> list:
    c = str(chapter_str or '').strip()
    if not c:
        return []
    fixed = _fix_hebrew_numeral_order(c)
    inverted = _PROPER_TU_TZ_RE.sub(r'\2\1', fixed)
    out = []
    for candidate in (c, fixed, inverted):
        if candidate and candidate not in out:
            out.append(candidate)
    return out

def _auto_heal_misordered_chapters_in_db():
    global _CHAPTERS_DB_HEALED
    if _CHAPTERS_DB_HEALED:
        return
    _CHAPTERS_DB_HEALED = True
    try:
        bad_Chapters = list(
            TorahText.objects.filter(
                Q(chapter__icontains='טות') | Q(chapter__icontains='טזת') |
                Q(chapter__icontains='טוק') | Q(chapter__icontains='טזק') |
                Q(chapter__icontains='טור') | Q(chapter__icontains='טזר') |
                Q(chapter__icontains='טוש') | Q(chapter__icontains='טזש')
            ).values_list('chapter', flat=True).distinct()
        )
        for bad_ch in bad_Chapters:
            fixed_ch = _fix_hebrew_numeral_order(bad_ch)
            if fixed_ch and fixed_ch != bad_ch:
                TorahText.objects.filter(chapter=bad_ch).update(chapter=fixed_ch)
    except Exception:
        pass

def strip_editorial_markers(text):
    if not text:
        return ""
    s = _INLINE_TAGS_RE.sub('', str(text))
    s = _EDITORIAL_MARKER_RE.sub(' ', s)
    s = s.replace('\u034f', '').replace('\u200d', '').replace('\u200c', '').replace('\ufeff', '')
    if 'ראש' in s:
        s = _SPLIT_BERESHIT_RE.sub(r'\1\2', s)
    return s

def calculate_gematria(text):
    clean = strip_editorial_markers(text)
    return sum(HEBREW_GEMATRIA.get(char, 0) for char in clean)

def _auto_heal_parasha_gematria_in_db():
    global _GEMATRIA_DB_HEALED
    if _GEMATRIA_DB_HEALED:
        return
    _GEMATRIA_DB_HEALED = True
    try:
        dirty_rows = list(
            TorahText.objects.filter(
                Q(text_with_nikkud__contains='{') | Q(clean_text__contains='{') |
                Q(text_with_nikkud__contains='<') | Q(clean_text__contains='<')
            ).only('id', 'text_with_nikkud', 'clean_text', 'verse_gematria', 'words_gematria')
        )
        to_update = []
        for row in dirty_rows:
            src_txt = row.text_with_nikkud or row.clean_text or ''
            sanitized = strip_editorial_markers(src_txt)
            true_v_gem = sum(HEBREW_GEMATRIA.get(c, 0) for c in sanitized)
            words = _HEB_WORDS_FAST_RE.findall(sanitized.translate(_DELETE_NIKKUD_TRANS))
            true_w_gem = (',' + ','.join(str(sum(HEBREW_GEMATRIA.get(c, 0) for c in w)) for w in words) + ',') if words else ''
            if row.verse_gematria != true_v_gem or row.words_gematria != true_w_gem:
                row.verse_gematria = true_v_gem
                row.words_gematria = true_w_gem
                to_update.append(row)
        if to_update:
            TorahText.objects.bulk_update(to_update, ['verse_gematria', 'words_gematria'], batch_size=500)
    except Exception:
        pass

def format_divine_name(text):
    if not text:
        return ""
    if 'שופטים' in text and 'אשמורת' in text:
        text = re.sub(r'\(\s*שופטים\s+ד[\'׳]?\s*\)', '(שופטים ז, יט)', text)

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

def format_verse_hebrew(val):
    s = str(val or '').strip()
    if not s:
        return ''
    if s.isdigit():
        return int_to_hebrew(int(s))
    m = re.match(r'^(\d+)$', s)
    if m:
        return int_to_hebrew(int(m.group(1)))
    return _fix_hebrew_numeral_order(s)

def parse_hebrew_number(val):
    s = str(val or '').strip()
    if not s:
        return 0
    if s.isdigit():
        return int(s)

    if ':' in s and not re.search(r'דף\s+[א-ת]+:', s):
        colon_parts = [p.strip() for p in s.split(':') if p.strip()]
        if len(colon_parts) >= 2:
            s = colon_parts[-1]
        elif len(colon_parts) == 1:
            s = colon_parts[0]

    nums = re.findall(r'\d+', s)
    if nums:
        return int(nums[-1])

    s_clean = re.sub(r'(פרק|סימן|דף|הלכה|משנה|סעיף|שורה|פסוק|עמוד\s+[אב]|ע"א|ע"ב|ע״א|ע״ב)\s*[:\-]?\s*', ' ', s).strip()
    parts = [p for p in s_clean.split() if re.sub(r'[^א-ת]', '', p)]
    if parts:
        heb_token = re.sub(r'[^א-ת]', '', parts[-1])
        if heb_token:
            return sum(HEBREW_GEMATRIA.get(c, 0) for c in heb_token)
    return 0

def generate_word_variations(word):
    variations = {word}
    if len(word) > 3 and word[0] in 'הבוכשמל':
        variations.add(word[1:])
    if len(word) > 4 and word[:2] in ['וה', 'בה', 'מה', 'שה', 'כה', 'וש', 'ול', 'וכ', 'ומ']:
        variations.add(word[2:])
    return list(variations)

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

def safe_int(v, default=0):
    if isinstance(v, int):
        return v
    s = str(v or '').strip()
    if not s:
        return default
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
    return default

def _resolve_torah_book_in_db(book_name):
    b = str(book_name or '').strip()
    if not b:
        return b
    b = re.sub(r"\s+", " ", b)
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
    c_variants = _chapter_db_variants(c)
    v_int = parse_hebrew_number(v_raw)
    v_heb = int_to_hebrew(v_int) if v_int > 0 else v_raw
    candidates = [
        v_raw, str(v_int), v_heb, f"{v_heb}'",
        f"פסוק {v_heb}", f"הלכה {v_heb}", f"משנה {v_heb}", f"סעיף {v_heb}", f"שורה {v_heb}",
        f"פסוק {v_int}", f"הלכה {v_int}", f"משנה {v_int}", f"סעיף {v_int}", f"שורה {v_int}"
    ]
    obj = TorahText.objects.filter(book=b, chapter__in=c_variants, verse__in=candidates).first()
    if not obj and v_int > 0:
        all_ch = list(TorahText.objects.filter(book=b, chapter__in=c_variants))
        all_ch.sort(key=lambda x: safe_int(x.verse))
        if 1 <= v_int <= len(all_ch):
            obj = all_ch[v_int - 1]
    return obj

def _generate_spelling_variants(title_str):
    variants = [title_str]
    replacements = [
        ('ייבום', 'יבום'), ('כלאיים', 'כלאים'), ('מעשה הקורבנות', 'מעשה הקרבנות'),
        ('קורבן פסח', 'קרבן פסח'), ('מלווה ולווה', 'מלוה ולוה'), ('גזילה ואבידה', 'גזלה ואבדה'),
        ('זכייה ומתנה', 'זכיה ומתנה'), ('שאלה ופיקדון', 'שאלה ופקדון'), ('מקוואות', 'מקואות'),
        ('מקואות', 'מקוואות'), ('ידים', 'ידיים'), ('ידיים', 'ידים'), ('מדות', 'מידות'),
        ('מידות', 'מדות'), ('עדיות', 'עדויות'), ('נדה', 'נידה'), ('נידה', 'נדה'),
        ('ביכורים ושאר מתנות כהונה שבגבולין', 'ביכורים'),
        ('סנהדרין והעונשין המסורין להם', 'סנהדרין'),
        ('תפילה וברכת כהנים', 'תפילה וברכות כהנים'),
        ('עבודה זרה וחוקות הגויים', 'עבודה זרה'),
    ]
    for old_w, new_w in replacements:
        if old_w in title_str:
            v_new = title_str.replace(old_w, new_w)
            if v_new not in variants:
                variants.append(v_new)
    return variants

def _get_tanakh_en_book(book_str):
    b_clean = str(book_str or '').strip()
    b_clean = re.sub(r"['\"׳״]", "", b_clean)
    b_clean = re.sub(r"\s+", " ", b_clean).strip()
    if b_clean in TANAKH_BOOKS_EN:
        return TANAKH_BOOKS_EN[b_clean]
    for heb_name, en_name in TANAKH_BOOKS_EN.items():
        if b_clean.endswith(heb_name):
            return en_name
    return ''

def _extract_sefaria_he_list(he_data):
    flat = []
    if isinstance(he_data, str):
        if he_data.strip():
            flat.append(format_divine_name(he_data.strip()))
    elif isinstance(he_data, list):
        for item in he_data:
            flat.extend(_extract_sefaria_he_list(item))
    return flat

RAMBAM_BOOKS_EN = {
    'רמב"ם הלכות יסודי התורה': 'Mishneh Torah, Foundations of the Torah',
    'רמב"ם הלכות דעות': 'Mishneh Torah, Human Dispositions',
    'רמב"ם הלכות תלמוד תורה': 'Mishneh Torah, Torah Study',
    'רמב"ם הלכות עבודה זרה וחוקות הגויים': 'Mishneh Torah, Foreign Worship and Customs of the Nations',
    'רמב"ם הלכות תשובה': 'Mishneh Torah, Repentance',
    'רמב"ם הלכות קריאת שמע': 'Mishneh Torah, Reading the Shema',
    'רמב"ם הלכות תפילה וברכת כהנים': 'Mishneh Torah, Prayer and the Priestly Blessing',
    'רמב"ם הלכות תפילין ומזוזה וספר תורה': 'Mishneh Torah, Tefillin, Mezuzah and the Torah Scroll',
    'רמב"ם הלכות ציצית': 'Mishneh Torah, Fringes',
    'רמב"ם הלכות ברכות': 'Mishneh Torah, Blessings',
    'רמב"ם הלכות מילה': 'Mishneh Torah, Circumcision',
    'רמב"ם הלכות סדר תפילות': 'Mishneh Torah, Order of Prayer',
    'רמב"ם הלכות שבת': 'Mishneh Torah, Sabbath',
    'רמב"ם הלכות עירובין': 'Mishneh Torah, Eruvin',
    'רמב"ם הלכות שביתת עשור': 'Mishneh Torah, Rest on the Tenth of Tishrei',
    'רמב"ם הלכות שביתת יום טוב': 'Mishneh Torah, Rest on a Holiday',
    'רמב"ם הלכות חמץ ומצה': 'Mishneh Torah, Leavened and Unleavened Bread',
    'רמב"ם הלכות שופר וסוכה ולולב': 'Mishneh Torah, Shofar, Sukkah and Lulav',
    'רמב"ם הלכות שקלים': 'Mishneh Torah, Sheqel Dues',
    'רמב"ם הלכות קידוש החודש': 'Mishneh Torah, Sanctification of the New Month',
    'רמב"ם הלכות תעניות': 'Mishneh Torah, Fasts',
    'רמב"ם הלכות מגילה וחנוכה': 'Mishneh Torah, Scroll of Esther and Hanukkah',
    'רמב"ם הלכות אישות': 'Mishneh Torah, Marriage',
    'רמב"ם הלכות גירושין': 'Mishneh Torah, Divorce',
    'רמב"ם הלכות ייבום וחליצה': 'Mishneh Torah, Levirate Marriage and Release',
    'רמב"ם הלכות נערה בתולה': 'Mishneh Torah, Virgin Maiden',
    'רמב"ם הלכות סוטה': 'Mishneh Torah, Woman Suspected of Infidelity',
    'רמב"ם הלכות איסורי ביאה': 'Mishneh Torah, Forbidden Intercourse',
    'רמב"ם הלכות מאכלות אסורות': 'Mishneh Torah, Forbidden Foods',
    'רמב"ם הלכות שחיטה': 'Mishneh Torah, Ritual Slaughter',
    'רמב"ם הלכות שבועות': 'Mishneh Torah, Oaths',
    'רמב"ם הלכות נדרים': 'Mishneh Torah, Vows',
    'רמב"ם הלכות נזירות': 'Mishneh Torah, Nazariteship',
    'רמב"ם הלכות ערכין וחרמין': 'Mishneh Torah, Appraisals and Devoted Property',
    'רמב"ם הלכות כלאיים': 'Mishneh Torah, Diverse Species',
    'רמב"ם הלכות מתנות עניים': 'Mishneh Torah, Gifts to the Poor',
    'רמב"ם הלכות תרומות': 'Mishneh Torah, Heave Offerings',
    'רמב"ם הלכות מעשרות': 'Mishneh Torah, Tithes',
    'רמב"ם הלכות מעשר שני ונטע רבעי': "Mishneh Torah, Second Tithes and Fourth Year's Fruit",
    'רמב"ם הלכות ביכורים ושאר מתנות כהונה שבגבולין': 'Mishneh Torah, First Fruits and other Gifts to Priests Outside the Sanctuary',
    'רמב"ם הלכות שמיטה ויובל': 'Mishneh Torah, Sabbatical Year and the Jubilee',
    'רמב"ם הלכות בית הבחירה': 'Mishneh Torah, The Chosen Temple',
    'רמב"ם הלכות כלי המקדש והעובדין בו': 'Mishneh Torah, Vessels of the Sanctuary and Those Who Serve Therein',
    'רמב"ם הלכות ביאת מקדש': 'Mishneh Torah, Admission into the Sanctuary',
    'רמב"ם הלכות איסורי המזבח': 'Mishneh Torah, Things Forbidden on the Altar',
    'רמב"ם הלכות מעשה הקורבנות': 'Mishneh Torah, Sacrificial Procedure',
    'רמב"ם הלכות תמידין ומוספין': 'Mishneh Torah, Daily Offerings and Additional Offerings',
    'רמב"ם הלכות פסולי המוקדשין': 'Mishneh Torah, Sacrifices Rendered Unfit',
    'רמב"ם הלכות עבודת יום הכיפורים': 'Mishneh Torah, Service on the Day of Atonement',
    'רמב"ם הלכות מעילה': 'Mishneh Torah, Trespass',
    'רמב"ם הלכות קורבן פסח': 'Mishneh Torah, Paschal Offering',
    'רמב"ם הלכות חגיגה': 'Mishneh Torah, Festival Offering',
    'רמב"ם הלכות בכורות': 'Mishneh Torah, Firstlings',
    'רמב"ם הלכות שגגות': 'Mishneh Torah, Offerings for Unintentional Transgressions',
    'רמב"ם הלכות מחוסרי כפרה': 'Mishneh Torah, Offerings for Those with Incomplete Atonement',
    'רמב"ם הלכות תמורה': 'Mishneh Torah, Substituted Offerings',
    'רמב"ם הלכות טומאת מת': 'Mishneh Torah, Defilement by a Corpse',
    'רמב"ם הלכות פרה אדומה': 'Mishneh Torah, Red Heifer',
    'רמב"ם הלכות טומאת צרעת': 'Mishneh Torah, Defilement by Leprosy',
    'רמב"ם הלכות מטמאי משכב ומושב': 'Mishneh Torah, Those Who Defile Bed or Seat',
    'רמב"ם הלכות שאר אבות הטומאות': 'Mishneh Torah, Other Sources of Defilement',
    'רמב"ם הלכות טומאת אוכלין': 'Mishneh Torah, Defilement of Foods',
    'רמב"ם הלכות כלים': 'Mishneh Torah, Vessels',
    'רמב"ם הלכות מקוואות': 'Mishneh Torah, Immersion Pools',
    'רמב"ם הלכות נזקי ממון': 'Mishneh Torah, Property Damages',
    'רמב"ם הלכות גניבה': 'Mishneh Torah, Theft',
    'רמב"ם הלכות גזילה ואבידה': 'Mishneh Torah, Robbery and Lost Property',
    'רמב"ם הלכות חובל ומזיק': 'Mishneh Torah, One Who Injures a Person or Property',
    'רמב"ם הלכות רוצח ושמירת נפש': 'Mishneh Torah, Murderer and the Preservation of Life',
    'רמב"ם הלכות מכירה': 'Mishneh Torah, Sales',
    'רמב"ם הלכות זכייה ומתנה': 'Mishneh Torah, Ownerless Property and Gifts',
    'רמב"ם הלכות שכנים': 'Mishneh Torah, Neighbors',
    'רמב"ם הלכות שלוחין ושותפין': 'Mishneh Torah, Agents and Partners',
    'רמב"ם הלכות עבדים': 'Mishneh Torah, Slaves',
    'רמב"ם הלכות שכירות': 'Mishneh Torah, Hiring',
    'רמב"ם הלכות שאלה ופיקדון': 'Mishneh Torah, Borrowing and Deposit',
    'רמב"ם הלכות מלווה ולווה': 'Mishneh Torah, Creditor and Debtor',
    'רמב"ם הלכות טוען ונטען': 'Mishneh Torah, Plaintiff and Defendant',
    'רמב"ם הלכות נחלות': 'Mishneh Torah, Inheritances',
    'רמב"ם הלכות סנהדרין והעונשין המסורין להם': 'Mishneh Torah, The Sanhedrin and the Penalties within their Jurisdiction',
    'רמב"ם הלכות עדות': 'Mishneh Torah, Testimony',
    'רמב"ם הלכות ממרים': 'Mishneh Torah, Rebels',
    'רמב"ם הלכות אבל': 'Mishneh Torah, Mourning',
    'רמב"ם הלכות מלכים ומלחמות': 'Mishneh Torah, Kings and Wars',
}

def _is_commentary_item_for_verse(c_item, chap_int, verse_int):
    if not isinstance(c_item, dict):
        return False
    anchor_v = c_item.get('anchorVerse')
    if anchor_v is not None:
        try:
            if int(anchor_v) != verse_int:
                return False
        except (ValueError, TypeError):
            pass
    anchor_ref = str(c_item.get('anchorRef') or c_item.get('sourceRef') or '')
    m = re.search(r'(\d+)[:.](\d+)\s*$', anchor_ref)
    if m:
        c_num = int(m.group(1))
        v_num = int(m.group(2))
        if (chap_int > 0 and c_num != chap_int) or (verse_int > 0 and v_num != verse_int):
            return False
    return True

def _extract_sefaria_verse_comments(data, verse_int, chap_int=0):
    if not isinstance(data, dict):
        return []
    he_data = data.get('he')
    if not he_data:
        return []

    sections = data.get('sections') or []
    try:
        text_depth = int(data.get('textDepth') or 3)
    except (ValueError, TypeError):
        text_depth = 3

    if len(sections) >= 1 and chap_int > 0:
        sec_c = re.sub(r'[^0-9]', '', str(sections[0]))
        if sec_c and int(sec_c) != chap_int:
            return []

    if isinstance(he_data, str):
        if len(sections) >= 2 and verse_int > 0:
            sec_v = re.sub(r'[^0-9]', '', str(sections[1]))
            if sec_v and int(sec_v) != verse_int:
                return []
        return _extract_sefaria_he_list(he_data)

    if isinstance(he_data, list):
        has_sublists = any(isinstance(x, list) for x in he_data)
        if has_sublists:
            is_3d = any(
                isinstance(sub, list) and any(isinstance(inner, list) for inner in sub)
                for sub in he_data
            )
            if is_3d or text_depth == 2:
                if chap_int <= 0 or chap_int > len(he_data):
                    return []
                chap_entry = he_data[chap_int - 1]
                if not isinstance(chap_entry, list) or verse_int <= 0 or verse_int > len(chap_entry):
                    return []
                return _extract_sefaria_he_list(chap_entry[verse_int - 1])

            if verse_int <= 0 or verse_int > len(he_data):
                return []
            return _extract_sefaria_he_list(he_data[verse_int - 1])

        if text_depth == 2:
            if verse_int <= 0 or verse_int > len(he_data):
                return []
            return _extract_sefaria_he_list(he_data[verse_int - 1])

        if len(sections) >= 2 and verse_int > 0:
            sec_v = re.sub(r'[^0-9]', '', str(sections[1]))
            if sec_v and int(sec_v) != verse_int:
                return []
            return _extract_sefaria_he_list(he_data)

        return []

    return []

def _fetch_commentary_for_source(book_name, chapter_name, verse_num, requested_commentator=''):
    b_str = _resolve_torah_book_in_db(book_name).replace('״', '"').replace('׳', "'")
    c_str = _fix_hebrew_numeral_order(str(chapter_name or '').strip())
    v_str = str(verse_num or '').strip()
    req_comm = str(requested_commentator or '').strip()

    chap_int = max(1, parse_hebrew_number(c_str))
    verse_int = max(1, parse_hebrew_number(v_str))

    cache_key = f"torah_comm_v56_{b_str}_{chap_int}_{verse_int}_{req_comm}"
    cached = cache.get(cache_key)
    if cached and cached.get('comments'):
        return cached

    v_obj = _resolve_torah_verse_obj(b_str, c_str, v_str)
    source_clean_txt = (v_obj.clean_text if v_obj else '') or ''

    comments_out = []
    target_commentator = 'רש"י'

    en_tanakh = _get_tanakh_en_book(b_str)

    if (b_str in TANAKH_NAMES or en_tanakh) and not c_str.startswith('דף'):
        target_commentator = 'רש"י'
        refs = []
        if en_tanakh:
            refs.append(f"Rashi on {en_tanakh}.{chap_int}.{verse_int}")
            refs.append(f"Rashi on {en_tanakh}.{chap_int}")
        refs.append(f'רש"י על {b_str}.{chap_int}.{verse_int}')
        for r in refs:
            d = _fetch_sefaria_json_cached(r, "context=0&commentary=0")
            if d and d.get('he'):
                comments_out = _extract_sefaria_verse_comments(d, verse_int, chap_int)
                if comments_out:
                    break

        if not comments_out and en_tanakh:
            v_data = _fetch_sefaria_json_cached(f"{en_tanakh}.{chap_int}.{verse_int}", "commentary=1&context=0")
            if v_data and isinstance(v_data.get('commentary'), list):
                for c_item in v_data['commentary']:
                    if not _is_commentary_item_for_verse(c_item, chap_int, verse_int):
                        continue
                    c_ident = f"{c_item.get('commentator', '')} {c_item.get('collectiveTitle', '')} {c_item.get('sourceHeRef', '')}"
                    if 'Rashi' in c_ident or 'רש"י' in c_ident:
                        for ex in _extract_sefaria_he_list(c_item.get('he', [])):
                            if ex not in comments_out:
                                comments_out.append(ex)

    elif c_str.startswith('דף') and not b_str.startswith('ירושלמי '):
        target_commentator = 'רש"י'
        en_book = BAVLI_TRACTATES_EN.get(b_str, b_str)
        daf_num = max(2, chap_int)
        amud = 'b' if ('עמוד ב' in c_str or ':' in c_str or 'ע"ב' in c_str or 'ע״ב' in c_str) else 'a'

        d_seg = _fetch_sefaria_json_cached(f"Rashi on {en_book}.{daf_num}{amud}.{verse_int}", "context=0&commentary=0")
        if d_seg and d_seg.get('he'):
            comments_out = _extract_sefaria_verse_comments(d_seg, verse_int)

        if not comments_out:
            d_daf = _fetch_sefaria_json_cached(f"Rashi on {en_book}.{daf_num}{amud}.1-150", "context=0&commentary=0")
            if d_daf and d_daf.get('he'):
                all_daf = _extract_sefaria_he_list(d_daf['he'])
                comments_out = _match_comments_by_dibbur_hamatchil(all_daf, source_clean_txt)

    elif b_str.startswith('ירושלמי '):
        target_commentator = 'פני משה'
        masechet = b_str.replace('ירושלמי ', '', 1).strip()
        en_book = YERUSHALMI_TRACTATES_EN.get(masechet)
        refs = []
        if en_book:
            refs.append(f"Penei Moshe on Jerusalem Talmud {en_book}.{chap_int}.{verse_int}")
        for m_var in _generate_spelling_variants(masechet):
            refs.append(f'פני משה על תלמוד ירושלמי {m_var}.{chap_int}.{verse_int}')
        for r in refs:
            d = _fetch_sefaria_json_cached(r, "context=0&commentary=0")
            if d and d.get('he'):
                comments_out = _extract_sefaria_verse_comments(d, verse_int, chap_int)
                if comments_out:
                    break

    elif b_str.startswith('שולחן ערוך '):
        target_commentator = 'באר היטב'
        sa_en = SHULCHAN_ARUCH_EN.get(b_str, '')
        chelek_he = b_str.replace('שולחן ערוך ', '', 1).strip()
        if sa_en:
            sa_data = _fetch_sefaria_json_cached(f"{sa_en}.{chap_int}.{verse_int}", "commentary=1&context=0")
            if sa_data and isinstance(sa_data.get('commentary'), list):
                for c_item in sa_data['commentary']:
                    if not _is_commentary_item_for_verse(c_item, chap_int, verse_int):
                        continue
                    c_ident = f"{c_item.get('collectiveTitle', '')} {c_item.get('sourceHeRef', '')} {c_item.get('commentator', '')}"
                    if 'באר היטב' in c_ident or 'Hetev' in c_ident or 'Heitev' in c_ident:
                        for ex in _extract_sefaria_he_list(c_item.get('he', [])):
                            if ex not in comments_out:
                                comments_out.append(ex)
        if not comments_out:
            bh_refs = [f"באר היטב על שולחן ערוך, {chelek_he}.{chap_int}"]
            if sa_en:
                bh_refs.insert(0, f"Ba'er Hetev on {sa_en}.{chap_int}")
            for r in bh_refs:
                d = _fetch_sefaria_json_cached(r, "context=0&commentary=0")
                if d and d.get('he'):
                    all_bh = _extract_sefaria_he_list(d['he'])
                    comments_out = _match_comments_by_dibbur_hamatchil(all_bh, source_clean_txt) or all_bh[:8]
                    if comments_out:
                        break

    elif b_str.startswith('רמב"ם ') or b_str.startswith('רמב״ם '):
        is_kesef = ('כסף משנה' in req_comm or 'kesef' in req_comm.lower() or 'kessef' in req_comm.lower())
        if is_kesef:
            target_commentator = 'כסף משנה'
            comm_en_prefixes = ['Kessef Mishneh', 'Kesef Mishneh']
            comm_he_prefix = 'כסף משנה'
            match_keywords = ('Kessef Mishneh', 'Kesef Mishneh', 'כסף משנה')
        else:
            target_commentator = 'מגיד משנה'
            comm_en_prefixes = ['Maggid Mishneh']
            comm_he_prefix = 'מגיד משנה'
            match_keywords = ('Maggid Mishneh', 'Magid Mishneh', 'מגיד משנה')

        en_rambam = RAMBAM_BOOKS_EN.get(b_str, '')
        hilchot = b_str.replace('רמב"ם ', '', 1).replace('רמב״ם ', '', 1).strip()
        direct_refs = []
        base_refs = []
        if en_rambam:
            for c_pref in comm_en_prefixes:
                direct_refs.append(f"{c_pref} on {en_rambam}.{chap_int}.{verse_int}")
                direct_refs.append(f"{c_pref} on {en_rambam}.{chap_int}")
            base_refs.append(f"{en_rambam}.{chap_int}.{verse_int}")
        for h_var in _generate_spelling_variants(hilchot):
            direct_refs.append(f'{comm_he_prefix} על משנה תורה, {h_var}.{chap_int}.{verse_int}')
            direct_refs.append(f'{comm_he_prefix} על משנה תורה, {h_var}.{chap_int}')
            base_refs.append(f'משנה תורה, {h_var}.{chap_int}.{verse_int}')

        for r in direct_refs:
            d = _fetch_sefaria_json_cached(r, "context=0&commentary=0")
            if d and d.get('he'):
                comments_out = _extract_sefaria_verse_comments(d, verse_int, chap_int)
                if comments_out:
                    break

        if not comments_out:
            for b_ref in base_refs:
                v_data = _fetch_sefaria_json_cached(b_ref, "commentary=1&context=0")
                if v_data and isinstance(v_data.get('commentary'), list):
                    for c_item in v_data['commentary']:
                        if not _is_commentary_item_for_verse(c_item, chap_int, verse_int):
                            continue
                        c_ident = f"{c_item.get('commentator', '')} {c_item.get('collectiveTitle', '')} {c_item.get('sourceHeRef', '')} {c_item.get('ref', '')}"
                        if any(k in c_ident for k in match_keywords):
                            for ex in _extract_sefaria_he_list(c_item.get('he', [])):
                                if ex not in comments_out:
                                    comments_out.append(ex)
                    if comments_out:
                        break

    elif b_str in MISHNAH_BOOKS:
        target_commentator = 'רבינו עובדיה מברטנורא'
        en_book = MISHNAH_BOOKS_EN.get(b_str)
        refs = []
        if en_book:
            refs.append(f"Bartenura on Mishnah {en_book}.{chap_int}.{verse_int}")
            refs.append(f"Bartenura on Mishnah {en_book}.{chap_int}")
        for m_var in _generate_spelling_variants(b_str):
            refs.append(f'ברטנורא על משנה {m_var}.{chap_int}.{verse_int}')
        for r in refs:
            d = _fetch_sefaria_json_cached(r, "context=0&commentary=0")
            if d and d.get('he'):
                comments_out = _extract_sefaria_verse_comments(d, verse_int, chap_int)
                if comments_out:
                    break

    payload = {'commentator': target_commentator, 'comments': comments_out[:15]}
    if comments_out:
        cache.set(cache_key, payload, 3600 * 24)
    return payload

def _match_comments_by_dibbur_hamatchil(all_comments_list, source_clean_text):
    if not source_clean_text or not all_comments_list:
        return []
    raw_src_words = re.findall(r'[א-ת]{2,}', source_clean_text)
    if not raw_src_words:
        return []

    src_expanded = set()
    for sw in raw_src_words:
        for var in generate_word_variations(sw):
            src_expanded.add(var)

    ignore_tokens = {'וכו', 'גמ', 'מתני', 'שם', 'דף', 'הגהה', 'סעיף', 'ס"ק', 'סק'}
    matched = []

    for comm_str in all_comments_list:
        bold_match = re.search(r'<(?:b|strong)[^>]*>(.*?)</(?:b|strong)>', comm_str, flags=re.IGNORECASE | re.DOTALL)
        if bold_match:
            dh_part = strip_tags(bold_match.group(1)).strip()
        else:
            plain_comm = re.sub(r'<[^>]+>', ' ', comm_str).strip()
            plain_comm = re.sub(r'^\([א-ת]{1,3}\)\s*', '', plain_comm)
            dh_part = re.split(r'[-–—:.]', plain_comm, maxsplit=1)[0].strip()
            if not dh_part or len(dh_part) > 60:
                dh_part = " ".join(plain_comm.split()[:3])

        dh_words = [w for w in re.findall(r'[א-ת]{2,}', dh_part) if w not in ignore_tokens and len(w) >= 2]
        if not dh_words:
            continue

        overlap = sum(1 for dw in dh_words if any(v in src_expanded for v in generate_word_variations(dw)))
        if (len(dh_words) == 1 and overlap == 1) or (len(dh_words) >= 2 and overlap >= 2) or (overlap / len(dh_words) >= 0.5):
            if comm_str not in matched:
                matched.append(comm_str)

    return matched

def _fetch_sefaria_json_cached(sefaria_ref, extra_params="context=0&commentary=0"):
    c_key = f"sefaria_ipv4_v45_{ urllib.parse.quote(sefaria_ref) }_{extra_params}"
    cached = cache.get(c_key)
    if cached is not None:
        return cached
    url = f"https://www.sefaria.org/api/texts/{urllib.parse.quote(sefaria_ref)}?{extra_params}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json',
    }
    for opener_fn in (_IPV4_OPENER.open, urllib.request.urlopen):
        try:
            req = urllib.request.Request(url, headers=headers)
            with opener_fn(req, timeout=5.0) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                if isinstance(data, dict) and not data.get('error') and (data.get('he') or data.get('commentary')):
                    cache.set(c_key, data, 3600 * 24)
                    return data
        except Exception:
            continue
    return None

_NIKKUD_RANGE_CHARS = (
    list(range(0x0591, 0x05BE)) +
    [0x05BF, 0x05C1, 0x05C2, 0x05C4, 0x05C5, 0x05C7, 0x034F, 0x200B, 0x200C, 0x200D, 0x200E, 0x200F, 0xFEFF]
)
_DELETE_NIKKUD_TRANS = {c: None for c in _NIKKUD_RANGE_CHARS}
_INLINE_TAGS_RE = re.compile(r'<[^>]+>')
_SPLIT_BERESHIT_RE = re.compile(r'^(\s*ב[\u0591-\u05c7]*)\s+(ר[\u0591-\u05c7]*א[\u0591-\u05c7]*ש[\u0591-\u05c7]*י[\u0591-\u05c7]*ת\b)')
_HEB_WORDS_FAST_RE = re.compile(r'[א-ת]+')
_WORD_TOKEN_GLOBAL_RE = re.compile(r'[א-ת\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]+')
_FINAL_TO_REG_MAP = {'ך': 'כ', 'ם': 'מ', 'ן': 'נ', 'ף': 'פ', 'ץ': 'צ'}
_REG_TO_FINAL_MAP = {'כ': 'ך', 'מ': 'ם', 'נ': 'ן', 'פ': 'ף', 'צ': 'ץ'}

def _sanitize_torah_verse_text(raw_text: str) -> str:
    if not raw_text:
        return ""
    s = _INLINE_TAGS_RE.sub('', raw_text)
    s = s.replace('\u034f', '').replace('\u200d', '').replace('\u200c', '').replace('\ufeff', '')
    if 'ראש' in s:
        s = _SPLIT_BERESHIT_RE.sub(r'\1\2', s)
    return s

def _fast_extract_clean_words(raw_text: str):
    if not raw_text:
        return []
    s = strip_editorial_markers(raw_text)
    return _HEB_WORDS_FAST_RE.findall(s.translate(_DELETE_NIKKUD_TRANS))

def _extract_valid_spans_for_match(raw_text: str):
    excluded = [m.span() for m in _EDITORIAL_MARKER_RE.finditer(raw_text)]
    spans = []
    for tok in _WORD_TOKEN_GLOBAL_RE.finditer(raw_text):
        s_idx, e_idx = tok.span()
        if excluded and any(ex_s <= s_idx and e_idx <= ex_e for ex_s, ex_e in excluded):
            continue
        if any('א' <= ch <= 'ת' for ch in tok.group(0)):
            spans.append((s_idx, e_idx))
    return spans

def _highlight_matched_words(raw_text: str, matched_indices: set) -> str:
    raw_text = _sanitize_torah_verse_text(raw_text)
    valid_spans = _extract_valid_spans_for_match(raw_text)
    out_parts, last_idx = [], 0
    for w_i, (s_idx, e_idx) in enumerate(valid_spans):
        out_parts.append(raw_text[last_idx:s_idx])
        word_str = raw_text[s_idx:e_idx]
        if w_i in matched_indices:
            out_parts.append(
                f'<mark style="background-color: rgba(255, 235, 59, 0.45); padding: 0 4px; border-radius: 4px; font-weight: bold;">{word_str}</mark>'
            )
        else:
            out_parts.append(word_str)
        last_idx = e_idx
    out_parts.append(raw_text[last_idx:])
    return "".join(out_parts)

_VALID_HEB_PREFIX_RX = r'(?:ו?כש|ו?ש[בכלמ]ה?|ו?[בכלמש]ה|ו?[הבכלמש]|ו)?'

def _build_stem_fuzzy_body(stem: str) -> str:
    n = len(stem)
    if n == 0:
        return ''
    has_internal_matres = any(ch in ('ו', 'י') for ch in stem[1:-1])
    parts = []
    idx = 0
    while idx < n:
        ch = stem[idx]
        is_first = (idx == 0)
        is_last = (idx == n - 1)
        if not is_first and not is_last and ch in ('ו', 'י'):
            run_end = idx
            while run_end < n - 1 and stem[run_end] == ch:
                run_end += 1
            max_rep = max(2, run_end - idx)
            min_rep = 1 if (ch == 'ו' and run_end == n - 1 and stem[-1] == 'ה') else 0
            parts.append(f'{re.escape(ch)}{{{min_rep},{max_rep}}}')
            idx = run_end
        else:
            parts.append(re.escape(ch))
            next_is_matres = (idx + 1 < n - 1) and (stem[idx + 1] in ('ו', 'י'))
            if not is_last and not next_is_matres:
                if not has_internal_matres or n >= 5:
                    parts.append(r'[וי]?')
            idx += 1
    return "".join(parts)

def build_hebrew_fuzzy_patterns(word: str):
    clean_w = re.sub(r'[^א-ת]', '', word)
    if not clean_w:
        return [], None

    stems = [clean_w]
    if clean_w.startswith('ו') and len(clean_w) >= 4:
        without_vav = clean_w[1:]
        consonants_after = [c for c in without_vav if c not in ('ו', 'י')]
        if len(consonants_after) >= 3:
            stems.append(without_vav)

    regex_branches = [rf'{_VALID_HEB_PREFIX_RX}{re.escape(clean_w)}']
    mandatory_sets = []

    for stem in stems:
        stem_mandatory = {stem[0], stem[-1]} | {c for c in stem if c not in ('ו', 'י')}
        mandatory_sets.append(stem_mandatory)
        branch_body = _build_stem_fuzzy_body(stem)
        regex_branches.append(rf'{_VALID_HEB_PREFIX_RX}{branch_body}')

    unique_branches = list(dict.fromkeys(regex_branches))
    common_mandatory = set.intersection(*mandatory_sets) if mandatory_sets else set(clean_w)
    combined_pattern = rf'^(?:{"|".join(unique_branches)})$'

    return list(common_mandatory), re.compile(combined_pattern)

def build_hebrew_fuzzy_morph_patterns(word: str):
    clean_w = re.sub(r'[^א-ת]', '', word)
    if not clean_w:
        return [], None

    _, basic_rx = build_hebrew_fuzzy_patterns(clean_w)
    basic_inner = basic_rx.pattern[4:-2] if basic_rx else rf'{_VALID_HEB_PREFIX_RX}{re.escape(clean_w)}'

    forms = [clean_w]
    if clean_w.startswith('ו') and len(clean_w) >= 4:
        without_vav = clean_w[1:]
        if len([c for c in without_vav if c not in ('ו', 'י')]) >= 3:
            forms.append(without_vav)

    regex_branches = [basic_inner]
    sql_stems = [clean_w]

    def add_stem_branches(base_reg: str, allow_bare: bool, suffix_alts: list):
        if not base_reg:
            return
        if base_reg not in sql_stems:
            sql_stems.append(base_reg)
        last_reg = _FINAL_TO_REG_MAP.get(base_reg[-1], base_reg[-1])
        last_fin = _REG_TO_FINAL_MAP.get(last_reg, last_reg)
        full_body = _build_stem_fuzzy_body(base_reg[:-1] + last_reg)
        esc_last = re.escape(last_reg)
        body_before = full_body[:-len(esc_last)]

        if allow_bare:
            regex_branches.append(rf'{_VALID_HEB_PREFIX_RX}{body_before}{re.escape(last_fin)}')

        if suffix_alts:
            sfx_group = "|".join(suffix_alts)
            regex_branches.append(rf'{_VALID_HEB_PREFIX_RX}{body_before}{esc_last}(?:{sfx_group})')

    for form in forms:
        handled_special = False

        if form.endswith('ויות') and len(form) >= 6:
            base = form[:-4]
            base_reg = base[:-1] + _FINAL_TO_REG_MAP.get(base[-1], base[-1])
            if len(base_reg) >= 2:
                add_stem_branches(base_reg, allow_bare=False, suffix_alts=['ות', 'ויות', 'וית'])
                handled_special = True

        elif form.endswith(('ים', 'ין')) and len(form) >= 4:
            base = form[:-2]
            base_reg = base[:-1] + _FINAL_TO_REG_MAP.get(base[-1], base[-1])
            non_matres = [c for c in base_reg if c not in ('ו', 'י')]
            if len(base_reg) >= 3 or len(non_matres) >= 2:
                sfx = ['ים', 'ין', 'י', 'ו?ת', 'ה'] if len(base_reg) >= 3 else ['ים', 'ין', 'י']
                add_stem_branches(base_reg, allow_bare=True, suffix_alts=sfx)
                handled_special = True

        elif form.endswith('ות') and len(form) >= 4:
            base = form[:-2]
            base_reg = base[:-1] + _FINAL_TO_REG_MAP.get(base[-1], base[-1])
            non_matres = [c for c in base_reg if c not in ('ו', 'י')]
            if len(base_reg) >= 3 or len(non_matres) >= 2:
                if base_reg.endswith('ו') and len(base_reg) >= 3:
                    core = base_reg.rstrip('ו')
                    if len(core) >= 2:
                        if core not in sql_stems:
                            sql_stems.append(core)
                        core_body = _build_stem_fuzzy_body(core)
                        regex_branches.append(rf'{_VALID_HEB_PREFIX_RX}{core_body}ו{{1,2}}(?:ה|ת)')
                        handled_special = True
                if not handled_special:
                    allow_bare = len(base_reg) >= 3 or base_reg in ('שמ', 'אב', 'אות')
                    sfx = ['ה', 'ו?ת', 'ויות', 'ים', 'ין', 'י'] if len(base_reg) >= 3 else ['ה', 'ו?ת', 'ויות', 'ו{1,2}ה', 'ו{1,2}ת']
                    add_stem_branches(base_reg, allow_bare=allow_bare, suffix_alts=sfx)
                    handled_special = True

        elif form.endswith(('ה', 'ת')) and len(form) >= 4:
            base = form[:-1]
            non_matres = [c for c in base if c not in ('ו', 'י')]
            if len(base) >= 3 and len(non_matres) >= 2:
                base_reg = base[:-1] + _FINAL_TO_REG_MAP.get(base[-1], base[-1])
                if form.endswith('וה'):
                    core = base_reg.rstrip('ו')
                    if len(core) >= 2:
                        if core not in sql_stems:
                            sql_stems.append(core)
                        core_body = _build_stem_fuzzy_body(core)
                        regex_branches.append(rf'{_VALID_HEB_PREFIX_RX}{core_body}ו{{1,2}}(?:ה|ת)')
                        handled_special = True
                else:
                    add_stem_branches(base_reg, allow_bare=False, suffix_alts=['ה', 'ו?ת', 'ים', 'ין', 'י'])
                    handled_special = True

        elif form.endswith('ה') and len(form) == 3:
            base = form[:-1]
            non_matres = [c for c in base if c not in ('ו', 'י')]
            if len(non_matres) == 2:
                base_reg = base[:-1] + _FINAL_TO_REG_MAP.get(base[-1], base[-1])
                add_stem_branches(base_reg, allow_bare=False, suffix_alts=['ה', 'ות', 'ת'])
                handled_special = True

        elif form.endswith('י') and len(form) >= 4:
            base = form[:-1]
            non_matres = [c for c in base if c not in ('ו', 'י')]
            if len(base) >= 3 and len(non_matres) >= 2:
                base_reg = base[:-1] + _FINAL_TO_REG_MAP.get(base[-1], base[-1])
                add_stem_branches(base_reg, allow_bare=True, suffix_alts=['ים', 'ין', 'י', 'ו?ת', 'ה'])
                handled_special = True

        if not handled_special:
            reg_self = form[:-1] + _FINAL_TO_REG_MAP.get(form[-1], form[-1])
            add_stem_branches(reg_self, allow_bare=True, suffix_alts=['ים', 'ין', 'י', 'ות'])

    unique_branches = list(dict.fromkeys(regex_branches))
    combined_pattern = rf'^(?:{"|".join(unique_branches)})$'
    return sql_stems, re.compile(combined_pattern)

def _build_sql_bigram_q_for_stem(stem: str, clean_w: str = '', allow_final_swap: bool = False) -> Q:
    q_filter = Q()
    n = len(stem)
    skeleton_positions = [idx for idx, ch in enumerate(stem) if idx == 0 or idx == n - 1 or ch not in ('ו', 'י')]
    skeleton = [stem[i] for i in skeleton_positions]

    if len(skeleton) >= 2:
        for i in range(len(skeleton) - 1):
            pos1, pos2 = skeleton_positions[i], skeleton_positions[i + 1]
            c1 = skeleton[i]
            c2_raw = skeleton[i + 1]
            orig_gap = stem[pos1 + 1 : pos2]

            c2_reg = _FINAL_TO_REG_MAP.get(c2_raw, c2_raw)
            c2_list = [c2_raw]
            if allow_final_swap and i == len(skeleton) - 2:
                c2_fin = _REG_TO_FINAL_MAP.get(c2_reg, c2_reg)
                c2_list = list(dict.fromkeys([c2_reg, c2_fin]))

            gaps = ['', 'ו', 'י', 'יי', 'וו', 'וי', 'יו']
            if orig_gap and orig_gap not in gaps:
                gaps.append(orig_gap)

            pair_q = Q()
            for c2 in c2_list:
                for g in gaps:
                    pair_q |= Q(clean_text__icontains=f"{c1}{g}{c2}")
            q_filter &= pair_q

        if len(skeleton) >= 3:
            last_reg = _FINAL_TO_REG_MAP.get(skeleton[-1], skeleton[-1])
            last_fin = _REG_TO_FINAL_MAP.get(last_reg, last_reg)
            last_q = Q(clean_text__icontains=last_reg) | Q(clean_text__icontains=last_fin)
            q_filter |= (
                Q(clean_text__icontains='<') &
                Q(clean_text__icontains=skeleton[1]) &
                last_q
            )
            if clean_w == 'בראשית':
                q_filter |= (Q(book='בראשית') & Q(clean_text__icontains='ראשית'))
    else:
        for ch in skeleton:
            c_reg = _FINAL_TO_REG_MAP.get(ch, ch)
            c_fin = _REG_TO_FINAL_MAP.get(c_reg, c_reg)
            q_filter &= (Q(clean_text__icontains=c_reg) | Q(clean_text__icontains=c_fin))

    return q_filter

def _build_fuzzy_sql_filter_for_word(word: str, include_morph: bool = False, morph_stems=None) -> Q:
    clean_w = re.sub(r'[^א-ת]', '', word)
    if not clean_w:
        return Q()

    exact_q = Q(clean_text__icontains=clean_w)
    if len(clean_w) >= 3:
        exact_q |= (Q(clean_text__icontains=clean_w[1:]) & Q(clean_text__icontains='<'))
        exact_q |= (Q(clean_text__icontains=clean_w[:-1]) & Q(clean_text__icontains='<'))
        exact_q |= Q(clean_text__icontains=f"{clean_w[0]} {clean_w[1:]}")

    if include_morph:
        stems = morph_stems if morph_stems is not None else build_hebrew_fuzzy_morph_patterns(clean_w)[0]
        if not stems:
            return exact_q
        combined_q = exact_q
        for st in stems:
            combined_q |= _build_sql_bigram_q_for_stem(st, clean_w=clean_w, allow_final_swap=True)
        return combined_q

    common_stem = clean_w
    if clean_w.startswith('ו') and len(clean_w) >= 4:
        without_vav = clean_w[1:]
        if len([c for c in without_vav if c not in ('ו', 'י')]) >= 3:
            common_stem = without_vav

    return exact_q | _build_sql_bigram_q_for_stem(common_stem, clean_w=clean_w, allow_final_swap=False)

@ratelimit(rate=45, timeout=60)
def tanakh_advanced_search_api(request):
    _auto_heal_misordered_chapters_in_db()

    query_type = request.GET.get('type', 'text').strip()
    query_val = request.GET.get('q', '').strip()
    book_filter = request.GET.get('book', 'torah').strip()
    is_exact = request.GET.get('exact', 'false').lower() == 'true'
    include_plural = request.GET.get('include_plural', 'false').lower() == 'true'
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
        raw_ch_list = list(ch_qs.values_list('chapter', flat=True).distinct())
        seen_ch = set()
        chapters_list = []
        for ch_item in raw_ch_list:
            fixed_ch = _fix_hebrew_numeral_order(ch_item)
            if fixed_ch not in seen_ch:
                seen_ch.add(fixed_ch)
                chapters_list.append(fixed_ch)
        chapters_list.sort(key=safe_int)
        return JsonResponse({'book': target_book, 'chapters': chapters_list}, json_dumps_params={'ensure_ascii': False})

    if query_type == 'commentary':
        t_book = request.GET.get('target_book', '').strip()
        t_chap = request.GET.get('target_chapter', '').strip()
        t_verse = request.GET.get('target_verse', '').strip()
        t_comm = request.GET.get('target_commentator', '').strip()
        if t_book and t_chap and t_verse:
            return JsonResponse(_fetch_commentary_for_source(t_book, t_chap, t_verse, t_comm), json_dumps_params={'ensure_ascii': False})
        return JsonResponse({'commentator': '', 'comments': []})

    if query_type == 'chapter_context':
        target_book = _resolve_torah_book_in_db(request.GET.get('target_book', '').strip())
        target_chapter = request.GET.get('target_chapter', '').strip()
        if target_book and target_chapter:
            c_variants = _chapter_db_variants(target_chapter)
            ch_verses = list(TorahText.objects.filter(book=target_book, chapter__in=c_variants).values('verse', 'text_with_nikkud', 'clean_text'))
            ch_verses.sort(key=lambda x: safe_int(x['verse']))
            fixed_chapter = _fix_hebrew_numeral_order(target_chapter)
            return JsonResponse({
                'book': target_book, 'chapter': fixed_chapter,
                'verse_label': get_verse_label(target_book, fixed_chapter),
                'verses': [
                    {'verse': format_verse_hebrew(v['verse']), 'raw_verse': v['verse'], 'text': format_divine_name(v['text_with_nikkud'] or v['clean_text'] or '')}
                    for v in ch_verses
                ]
            }, json_dumps_params={'ensure_ascii': False})
        return JsonResponse({'verses': []})

    if query_type == 'quick_open':
        explicit_book = request.GET.get('target_book', '').strip()
        explicit_chapter = _fix_hebrew_numeral_order(request.GET.get('target_chapter', '').strip())
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

        db_chapters = list(ch_qs.values_list('chapter', flat=True).distinct()) or list(TorahText.objects.filter(book=matched_book).values_list('chapter', flat=True).distinct())
        seen_ch = set()
        raw_chapters = []
        for ch_item in db_chapters:
            fixed_ch = _fix_hebrew_numeral_order(ch_item)
            if fixed_ch not in seen_ch:
                seen_ch.add(fixed_ch)
                raw_chapters.append(fixed_ch)
        raw_chapters.sort(key=safe_int)
        if not raw_chapters:
            return JsonResponse({'error': f'לא נמצאו פרקים עבור "{matched_book}".'})

        chosen_chapter = _resolve_chapter_in_list(explicit_chapter, raw_chapters)
        c_variants = _chapter_db_variants(chosen_chapter)
        ch_verses = list(TorahText.objects.filter(book=matched_book, chapter__in=c_variants).values('verse', 'text_with_nikkud', 'clean_text'))
        ch_verses.sort(key=lambda x: safe_int(x['verse']))

        curr_idx = raw_chapters.index(chosen_chapter) if chosen_chapter in raw_chapters else 0
        return JsonResponse({
            'book': matched_book, 'chapter': chosen_chapter, 'all_chapters': raw_chapters,
            'prev_chapter': raw_chapters[curr_idx - 1] if curr_idx > 0 else None,
            'next_chapter': raw_chapters[curr_idx + 1] if curr_idx < len(raw_chapters) - 1 else None,
            'verse_label': get_verse_label(matched_book, chosen_chapter),
            'verses': [
                {'verse': format_verse_hebrew(v['verse']), 'raw_verse': v['verse'], 'text': format_divine_name(v['text_with_nikkud'] or v['clean_text'] or '')}
                for v in ch_verses
            ]
        }, json_dumps_params={'ensure_ascii': False})

    try:
        per_page = int(request.GET.get('per_page', 10))
        if per_page not in [10, 20, 50, 100, 500, 1000, 2500, 5000]:
            per_page = 10
    except ValueError:
        per_page = 10

    effective_query_type = 'text_fuzzy_morph' if (query_type == 'text_fuzzy' and include_plural) else query_type

    _raw_cache_key = f"v55|{effective_query_type}|{query_val}|{book_filter}|{is_exact}|{exclude_books_param}|{skip_param}|{page}|{per_page}"
    search_cache_key = "tanakh_srch_v55_" + hashlib.md5(_raw_cache_key.encode("utf-8")).hexdigest()
    cached_search_data = cache.get(search_cache_key)
    if cached_search_data:
        return JsonResponse(cached_search_data, json_dumps_params={'ensure_ascii': False})

    results = []
    qs = TorahText.objects.all()
    selected_corpora = [b.strip() for b in book_filter.split(',') if b.strip()] or ['torah']
    known_corpora = {'torah', 'tanakh', 'mishnah', 'tosefta', 'talmud', 'yerushalmi', 'rambam', 'shulchan_aruch', 'all'}

    if 'all' not in selected_corpora and any(c in known_corpora for c in selected_corpora):
        corpus_q = Q()
        if 'torah' in selected_corpora:
            corpus_q |= (Q(book__in=TORAH_NAMES) & ~Q(chapter__startswith='דף'))
        if 'tanakh' in selected_corpora:
            corpus_q |= (Q(book__in=TANAKH_NAMES) & ~Q(book__in=MISHNAH_BOOKS) & ~Q(chapter__startswith='דף'))
        if 'mishnah' in selected_corpora:
            corpus_q |= (~Q(book__in=TANAKH_NAMES) & ~Q(chapter__startswith='דף') & ~Q(book__startswith='ירושלמי ') & ~Q(book__startswith='תוספתא ') & ~Q(book__startswith='רמב"ם ') & ~Q(book__startswith='שולחן ערוך '))
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
    elif 'all' not in selected_corpora:
        qs = qs.filter(book__icontains=book_filter)

    if exclude_books_param:
        for ex in [b.strip() for b in exclude_books_param.split(',') if b.strip()]:
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
    norm_heb = lambda s: s.translate(FINAL_TO_REGULAR)
    WORD_TOKEN_RE = _WORD_TOKEN_GLOBAL_RE
    HEB_LETTER_CLUSTER_RE = re.compile(r'[א-ת][\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]*')

    calculated_gematria_val = None
    reversed_query_val = None
    available_skips = []
    active_skip = int(skip_param) if skip_param.isdigit() else None

    try:
        if effective_query_type in ['text', 'text_exact', 'text_broad'] and query_val:
            if effective_query_type == 'text_exact':
                is_exact = True
            elif effective_query_type == 'text_broad':
                is_exact = False
            q_words = re.sub(r'[^א-ת\s]', '', query_val.replace('י-ה-ו-ה', 'יהוה')).strip().split()
            if q_words:
                num_q_words = len(q_words)
                text_query = Q()
                for target_w in q_words:
                    w_q = Q(clean_text__icontains=target_w)
                    if len(target_w) >= 3:
                        w_q |= (Q(clean_text__icontains=target_w[1:]) & Q(clean_text__icontains='<'))
                        w_q |= (Q(clean_text__icontains=target_w[:-1]) & Q(clean_text__icontains='<'))
                        w_q |= Q(clean_text__icontains=f"{target_w[0]} {target_w[1:]}")
                        if target_w == 'בראשית':
                            w_q |= (Q(book='בראשית') & Q(clean_text__icontains='ראשית'))
                    text_query &= w_q

                match_label = 'חיפוש מדויק' if is_exact else 'חיפוש חופשי (רחב)'
                for m in qs.filter(text_query).values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text').iterator(chunk_size=2500):
                    raw_text = m.get('text_with_nikkud') or m.get('clean_text') or ""
                    if not raw_text:
                        continue
                    clean_words = _fast_extract_clean_words(raw_text)
                    if len(clean_words) < num_q_words:
                        continue
                    matched_indices = set()
                    if num_q_words == 1:
                        target = q_words[0]
                        for idx, vw_clean in enumerate(clean_words):
                            if (vw_clean == target) if is_exact else (target in vw_clean):
                                matched_indices.add(idx)
                    else:
                        for i in range(len(clean_words) - num_q_words + 1):
                            if all((clean_words[i + j] == q_words[j]) if is_exact else (q_words[j] in clean_words[i + j]) for j in range(num_q_words)):
                                matched_indices.update(range(i, i + num_q_words))
                    if matched_indices:
                        fixed_ch = _fix_hebrew_numeral_order(m['chapter'])
                        results.append({
                            'book': m['book'], 'chapter': fixed_ch, 'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'], 'verse_label': get_verse_label(m['book'], fixed_ch),
                            'text': _highlight_matched_words(raw_text, matched_indices),
                            'match_type': match_label
                        })

        elif effective_query_type in ['text_fuzzy', 'text_fuzzy_morph'] and query_val:
            use_morph = (effective_query_type == 'text_fuzzy_morph')
            q_words = re.sub(r'[^א-ת\s]', '', query_val.replace('י-ה-ו-ה', 'יהוה')).strip().split()
            if q_words:
                word_patterns = [
                    build_hebrew_fuzzy_morph_patterns(w) if use_morph else build_hebrew_fuzzy_patterns(w)
                    for w in q_words
                ]
                valid_pairs = [(w, wp) for w, wp in zip(q_words, word_patterns) if wp[1] is not None]

                if valid_pairs:
                    num_q_words = len(valid_pairs)
                    text_query = Q()
                    for w_str, (stems_or_chars, _) in valid_pairs:
                        text_query &= _build_fuzzy_sql_filter_for_word(
                            w_str,
                            include_morph=use_morph,
                            morph_stems=stems_or_chars if use_morph else None
                        )

                    compiled_rxs = [wp[1] for _, wp in valid_pairs]
                    rx0 = compiled_rxs[0]
                    fuzzy_match_label = 'כתיב מלא/חסר + יחיד/רבים' if use_morph else 'כתיב מלא / חסר ותחיליות'

                    for m in qs.filter(text_query).values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text').iterator(chunk_size=2500):
                        raw_text = m.get('text_with_nikkud') or m.get('clean_text') or ""
                        if not raw_text:
                            continue

                        clean_words = _fast_extract_clean_words(raw_text)
                        if len(clean_words) < num_q_words:
                            continue

                        matched_indices = set()
                        if num_q_words == 1:
                            for idx, vw_clean in enumerate(clean_words):
                                if rx0.match(vw_clean):
                                    matched_indices.add(idx)
                        else:
                            for i in range(len(clean_words) - num_q_words + 1):
                                if rx0.match(clean_words[i]) and all(compiled_rxs[j].match(clean_words[i + j]) for j in range(1, num_q_words)):
                                    matched_indices.update(range(i, i + num_q_words))

                        if matched_indices:
                            fixed_ch = _fix_hebrew_numeral_order(m['chapter'])
                            results.append({
                                'book': m['book'],
                                'chapter': fixed_ch,
                                'verse': format_verse_hebrew(m['verse']),
                                'raw_verse': m['verse'],
                                'verse_label': get_verse_label(m['book'], fixed_ch),
                                'text': _highlight_matched_words(raw_text, matched_indices),
                                'match_type': fuzzy_match_label
                            })

        elif effective_query_type == 'gematria' and query_val:
            _auto_heal_parasha_gematria_in_db()
            calc_word_gem = lambda w: sum(HEBREW_GEMATRIA.get(c, 0) for c in re.sub(r'[^א-ת]', '', w))
            target_val = int(query_val) if query_val.isdigit() else calc_word_gem(query_val)
            calculated_gematria_val = target_val
            if target_val > 0:
                search_str = f",{target_val},"
                gem_q = Q(verse_gematria=target_val) | Q(words_gematria__contains=search_str) | Q(clean_text__icontains='<')
                for m in qs.filter(gem_q).values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text', 'verse_gematria').iterator(chunk_size=2500):
                    raw_text = _sanitize_torah_verse_text(m['text_with_nikkud'] or m['clean_text'] or "")
                    fixed_ch = _fix_hebrew_numeral_order(m['chapter'])
                    true_verse_gem = calculate_gematria(raw_text)
                    if true_verse_gem == target_val:
                        m_type = f'גימטריה מלאה לפסוק (הערך: {target_val})'
                        final_text = f'<mark style="background-color: rgba(255, 235, 59, 0.4); padding: 0 4px; border-radius: 4px; color: inherit;">{raw_text}</mark>'
                        results.append({
                            'book': m['book'], 'chapter': fixed_ch, 'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'], 'verse_label': get_verse_label(m['book'], fixed_ch),
                            'text': final_text, 'match_type': m_type
                        })
                    else:
                        excluded_ranges = [em.span() for em in _EDITORIAL_MARKER_RE.finditer(raw_text)]
                        has_word_hit = False
                        def _mark_gem_word(match):
                            nonlocal has_word_hit
                            s_i, e_i = match.span()
                            if excluded_ranges and any(es <= s_i and e_i <= ee for es, ee in excluded_ranges):
                                return match.group(0)
                            w_tok = match.group(0)
                            if calc_word_gem(w_tok) == target_val:
                                has_word_hit = True
                                return f'<mark style="background-color: rgba(255, 235, 59, 0.4); padding: 0 4px; border-radius: 4px; color: inherit;">{w_tok}</mark>'
                            return w_tok
                        final_text = WORD_TOKEN_RE.sub(_mark_gem_word, raw_text)
                        if has_word_hit:
                            results.append({
                                'book': m['book'], 'chapter': fixed_ch, 'verse': format_verse_hebrew(m['verse']),
                                'raw_verse': m['verse'], 'verse_label': get_verse_label(m['book'], fixed_ch),
                                'text': final_text, 'match_type': f'גימטריה למילה בפסוק (הערך: {target_val})'
                            })

        elif effective_query_type in ['acronym', 'rashei_tevot', 'sofei_tevot', 'suffix'] and query_val:
            is_sofei = effective_query_type in ['sofei_tevot', 'suffix']
            target_acr = norm_heb(re.sub(r'[^א-ת]', '', query_val))
            if target_acr:
                acr_len = len(target_acr)
                char_q = Q()
                for ch in set(target_acr):
                    fin_ch = REGULAR_TO_FINAL.get(ch)
                    if fin_ch:
                        char_q &= (Q(clean_text__icontains=ch) | Q(clean_text__icontains=fin_ch))
                    else:
                        char_q &= Q(clean_text__icontains=ch)

                m_label = f'סופי תיבות ({query_val})' if is_sofei else f'ראשי תיבות ({query_val})'
                for m in qs.filter(char_q).values('book', 'chapter', 'verse', 'text_with_nikkud').iterator(chunk_size=2500):
                    raw_text = m.get('text_with_nikkud') or ""
                    if not raw_text:
                        continue
                    raw_clean_words = _fast_extract_clean_words(raw_text)
                    if len(raw_clean_words) < acr_len:
                        continue
                    letters_seq = "".join([norm_heb(w[-1] if is_sofei else w[0]) for w in raw_clean_words])
                    match_pos = letters_seq.find(target_acr)
                    if match_pos != -1:
                        matched_word_indices = set()
                        while match_pos != -1:
                            matched_word_indices.update(range(match_pos, match_pos + acr_len))
                            match_pos = letters_seq.find(target_acr, match_pos + 1)
                        fixed_ch = _fix_hebrew_numeral_order(m['chapter'])
                        results.append({
                            'book': m['book'], 'chapter': fixed_ch, 'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'], 'verse_label': get_verse_label(m['book'], fixed_ch),
                            'text': _highlight_matched_words(raw_text, matched_word_indices),
                            'match_type': m_label
                        })

        elif effective_query_type in ['reverse', 'palindrome'] and query_val:
            q_words_raw = re.findall(r'[א-ת]+', query_val)
            if q_words_raw:
                rev_words = []
                for w in q_words_raw:
                    rev_raw = w[::-1]
                    rev_words.append((norm_heb(rev_raw[:-1]) + REGULAR_TO_FINAL.get(norm_heb(rev_raw[-1]), norm_heb(rev_raw[-1]))) if len(rev_raw) > 1 else rev_raw)
                reversed_query_val = " ".join(rev_words)
                rev_words_norm = [norm_heb(rw) for rw in rev_words]
                num_q_words = len(rev_words_norm)
                text_query = Q()
                for rw, rw_norm in zip(rev_words, rev_words_norm):
                    w_q = Q(clean_text__icontains=rw) | Q(clean_text__icontains=rw_norm)
                    if len(rw) >= 3:
                        w_q |= (Q(clean_text__icontains=rw[1:]) & Q(clean_text__icontains='<'))
                        w_q |= (Q(clean_text__icontains=rw[:-1]) & Q(clean_text__icontains='<'))
                    text_query &= w_q

                is_palindrome = (norm_heb("".join(q_words_raw)) == "".join(rev_words_norm))
                m_label = f'פלינדרום ("{reversed_query_val}")' if is_palindrome else f'מילה הפוכה: "{reversed_query_val}"'

                for m in qs.filter(text_query).values('book', 'chapter', 'verse', 'text_with_nikkud').iterator(chunk_size=2500):
                    raw_text = m.get('text_with_nikkud') or ""
                    if not raw_text:
                        continue
                    clean_words_norm = [norm_heb(w) for w in _fast_extract_clean_words(raw_text)]
                    if len(clean_words_norm) < num_q_words:
                        continue
                    matched_indices = set()
                    for i in range(len(clean_words_norm) - num_q_words + 1):
                        if all(clean_words_norm[i + j] == rev_words_norm[j] for j in range(num_q_words)):
                            matched_indices.update(range(i, i + num_q_words))
                    if matched_indices:
                        fixed_ch = _fix_hebrew_numeral_order(m['chapter'])
                        results.append({
                            'book': m['book'], 'chapter': fixed_ch, 'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'], 'verse_label': get_verse_label(m['book'], fixed_ch),
                            'text': _highlight_matched_words(raw_text, matched_indices),
                            'match_type': m_label
                        })

        elif effective_query_type in ['els', 'skip', 'dilugim'] and query_val:
            target_els = norm_heb(re.sub(r'[^א-ת]', '', query_val))
            k = len(target_els)
            if k >= 2:
                char_q = Q()
                for ch in set(target_els):
                    fin_ch = REGULAR_TO_FINAL.get(ch)
                    char_q &= (Q(clean_text__icontains=ch) | Q(clean_text__icontains=fin_ch)) if fin_ch else Q(clean_text__icontains=ch)

                skip_counts = {}
                t0 = target_els[0]
                for m in qs.filter(char_q).values('book', 'chapter', 'verse', 'text_with_nikkud').iterator(chunk_size=2500):
                    raw_text = _sanitize_torah_verse_text(m.get('text_with_nikkud') or "")
                    if not raw_text:
                        continue
                    fast_words = _fast_extract_clean_words(raw_text)
                    has_any_word_hit = False
                    for fw in fast_words:
                        n_fw = len(fw)
                        if n_fw < k:
                            continue
                        w_norm = norm_heb(fw)
                        if w_norm == target_els:
                            has_any_word_hit = True
                            break
                        pos0 = w_norm.find(t0)
                        while pos0 != -1:
                            for step in range(2, (n_fw - 1 - pos0) // (k - 1) + 1):
                                if w_norm[pos0 : pos0 + k * step : step] == target_els:
                                    has_any_word_hit = True
                                    break
                            if has_any_word_hit:
                                break
                            pos0 = w_norm.find(t0, pos0 + 1)
                        if has_any_word_hit:
                            break

                    if not has_any_word_hit:
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
                            for step in range(2, (n - 1 - pos0) // (k - 1) + 1):
                                if w_norm[pos0 : pos0 + k * step : step] == target_els:
                                    verse_skip_matches.setdefault(step - 1, []).append((tok_i, {pos0 + idx * step for idx in range(k)}, word_str))
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
                        matched_tokens_map, matched_words_sample = {}, []
                        for tok_i, letter_idxs, w_str in verse_skip_matches[chosen_skip]:
                            matched_tokens_map.setdefault(tok_i, set()).update(letter_idxs)
                            if w_str not in matched_words_sample:
                                matched_words_sample.append(w_str)
                        out_parts, last_idx = [], 0
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
                                    return f'<strong style="color: #9c6500; text-decoration: underline;">{cl}</strong>' if c_idx[0] in target_positions else cl
                                out_parts.append(f'<mark style="background-color: rgba(255, 235, 59, 0.45); padding: 0 4px; border-radius: 4px;">{HEB_LETTER_CLUSTER_RE.sub(mark_cluster, word_str)}</mark>')
                            else:
                                out_parts.append(word_str)
                            last_idx = e_idx
                        out_parts.append(raw_text[last_idx:])
                        sample_w = matched_words_sample[0] if matched_words_sample else ""
                        fixed_ch = _fix_hebrew_numeral_order(m['chapter'])
                        results.append({
                            'book': m['book'], 'chapter': fixed_ch, 'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'], 'verse_label': get_verse_label(m['book'], fixed_ch),
                            'text': "".join(out_parts),
                            'match_type': f'דילוג 0 במילה ({sample_w})' if chosen_skip == 0 else f'דילוג {chosen_skip} במילה: "{sample_w}"',
                            'skip_distance': chosen_skip
                        })
                available_skips = [{'skip': s_d, 'count': skip_counts[s_d]} for s_d in sorted(skip_counts.keys())]

        elif effective_query_type == 'els_verse' and query_val:
            target_els = norm_heb(re.sub(r'[^א-ת]', '', query_val))
            k = len(target_els)
            if k >= 2:
                char_q = Q()
                for ch in set(target_els):
                    fin_ch = REGULAR_TO_FINAL.get(ch)
                    char_q &= (Q(clean_text__icontains=ch) | Q(clean_text__icontains=fin_ch)) if fin_ch else Q(clean_text__icontains=ch)

                t0, t1 = target_els[0], target_els[1]
                skip_counts = {}
                for m in qs.filter(char_q).values('book', 'chapter', 'verse', 'text_with_nikkud').iterator(chunk_size=2500):
                    raw_text = _sanitize_torah_verse_text(m.get('text_with_nikkud') or "")
                    if not raw_text:
                        continue
                    fast_words = _fast_extract_clean_words(raw_text)
                    letters_str = norm_heb("".join(fast_words))
                    n = len(letters_str)
                    if n < k:
                        continue

                    verse_skip_matches = {}
                    letter_to_word_idx = None
                    pos0 = letters_str.find(t0)
                    while pos0 != -1:
                        max_step = min(26, (n - 1 - pos0) // (k - 1))
                        if max_step >= 1:
                            pos1 = letters_str.find(t1, pos0 + 1, pos0 + max_step + 1)
                            while pos1 != -1:
                                step = pos1 - pos0
                                if k == 2 or letters_str[pos0 : pos0 + k * step : step] == target_els:
                                    if letter_to_word_idx is None:
                                        letter_to_word_idx = []
                                        for w_idx, fw in enumerate(fast_words):
                                            letter_to_word_idx.extend([w_idx] * len(fw))
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
                            chosen_skip = min(cross_skips) if cross_skips else (min(non_zero) if non_zero else 0)
                        target_global_positions, participating_words, is_cross_word = verse_skip_matches[chosen_skip]
                        tokens = list(WORD_TOKEN_RE.finditer(raw_text))
                        out_parts, last_idx, global_letter_idx = [], 0, [-1]
                        for tok_i, tok in enumerate(tokens):
                            s_idx, e_idx = tok.span()
                            out_parts.append(raw_text[last_idx:s_idx])
                            word_str = raw_text[s_idx:e_idx]
                            def mark_verse_cluster(c_match):
                                global_letter_idx[0] += 1
                                cl = c_match.group(0)
                                return f'<strong style="background-color: #ffca28; color: #000; padding: 0 3px; border-radius: 3px; border-bottom: 2px solid #b8860b;">{cl}</strong>' if global_letter_idx[0] in target_global_positions else cl
                            marked_word = HEB_LETTER_CLUSTER_RE.sub(mark_verse_cluster, word_str)
                            out_parts.append(f'<mark style="background-color: rgba(255, 235, 59, 0.28); padding: 0 3px; border-radius: 4px;">{marked_word}</mark>' if tok_i in participating_words else marked_word)
                            last_idx = e_idx
                        out_parts.append(raw_text[last_idx:])
                        cross_label = "חוצה מילים" if is_cross_word else "באותה מילה"
                        fixed_ch = _fix_hebrew_numeral_order(m['chapter'])
                        results.append({
                            'book': m['book'], 'chapter': fixed_ch, 'verse': format_verse_hebrew(m['verse']),
                            'raw_verse': m['verse'], 'verse_label': get_verse_label(m['book'], fixed_ch),
                            'text': "".join(out_parts), 'match_type': f'דילוג {chosen_skip} בפסוק ({cross_label})',
                            'skip_distance': chosen_skip
                        })
                available_skips = [{'skip': s_d, 'count': skip_counts[s_d]} for s_d in sorted(skip_counts.keys())]

        results.sort(key=lambda x: (get_book_order(x['book'], x.get('chapter', '')), safe_int(x['chapter']), safe_int(x.get('raw_verse') or x['verse'])))
        total_results = len(results)
        total_pages = (total_results + per_page - 1) // per_page if total_results > 0 else 1
        paginated_results = results[(page - 1) * per_page : page * per_page]
        for item in paginated_results:
            item['text'] = format_divine_name(item.get('text', ''))
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

    response_payload = {
        'results': paginated_results, 'total': total_results, 'page': page,
        'total_pages': total_pages, 'per_page': per_page,
        'calculated_gematria': calculated_gematria_val, 'reversed_query': reversed_query_val,
        'available_skips': available_skips, 'active_skip': active_skip
    }
    cache.set(search_cache_key, response_payload, 900)
    return JsonResponse(response_payload, json_dumps_params={'ensure_ascii': False})