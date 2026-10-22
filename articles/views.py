import json
import urllib.request
import urllib.parse
import re
import random
import datetime
import concurrent.futures
import os
import time
import asyncio
import subprocess
import tempfile
import sys
import threading
import edge_tts
import socket
import smtplib
from html import unescape
from functools import wraps
from django.http import JsonResponse, HttpResponse, StreamingHttpResponse, Http404
from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.core.mail import send_mail
from django.contrib import messages
from django.conf import settings
from django.core.exceptions import FieldError
from django.core.cache import cache
from django.views.decorators.cache import cache_page
from django.db.models import Q, Case, When, Value, IntegerField
from django.urls import reverse
from django.db import models, transaction
from django.utils.html import strip_tags
from .forms import ArticleForm
from .models import Article, Book, Chapter, Section, Cart, CartItem, Order, OrderItem, TorahText, QA, Acronym
from .emails import send_order_confirmation
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .vector_store import search_similar_articles


def _load_local_env():
    for env_path in [
        os.path.join(settings.BASE_DIR, '.env'),
        os.path.join(settings.BASE_DIR, 'articles', '.env')
    ]:
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
            except Exception:
                pass


_load_local_env()


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

TORAH_CORE_CONCEPTS = [
    'תורה', 'מצוה', 'שבת', 'אמת', 'שלום', 'חיים', 'אור', 'קדש', 'ברכה', 'חסד',
    'משה', 'אהרן', 'דוד', 'משיח', 'גאולה', 'תשובה', 'תפילה', 'צדקה', 'אמונה', 'בטחון',
    'חכמה', 'בינה', 'דעת', 'יראה', 'אהבה', 'שמחה', 'נשמה', 'רוח', 'נפש', 'כהן',
    'לוי', 'ישראל', 'ציון', 'מקדש', 'מזבח', 'קרבן', 'ברית', 'מילה', 'ציצית', 'תכלת',
    'תפילין', 'מזוזה', 'שופר', 'סוכה', 'לולב', 'אתרוג', 'מצה', 'פסח', 'סיני', 'ארון',
    'מזל', 'נס', 'פדיון', 'שכינה', 'נבואה', 'ענוה', 'טהרה'
]


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


def get_base_schema_json():
    return json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "@id": "https://leblibrary.co.il/#website",
                "url": "https://leblibrary.co.il",
                "name": "LebLibrary - ספריית לייבוביץ",
                "alternateName": ["ספריית ליבוביץ", "הספרייה של משה לייבוביץ", "ספרית לייבוביץ"],
                "publisher": {"@id": "https://leblibrary.co.il/#person"},
                "potentialAction": [
                    {
                        "@type": "SearchAction",
                        "target": "https://leblibrary.co.il/?q={search_term_string}",
                        "query-input": "required name=search_term_string"
                    },
                    {
                        "@type": "SearchAction",
                        "name": "מנוע חיפוש תורני מתקדם",
                        "target": "https://leblibrary.co.il/advanced-search/?q={search_term_string}",
                        "query-input": "required name=search_term_string"
                    }
                ]
            },
            {
                "@type": "Person",
                "@id": "https://leblibrary.co.il/#person",
                "name": "הרב משה לייבוביץ",
                "alternateName": ["משה ליבוביץ", "Moshe Leibowitz", "משה בן יעקב לייבוביץ"],
                "url": "https://leblibrary.co.il",
                "homeLocation": {
                    "@type": "Place",
                    "name": "טירת כרמל, ישראל"
                },
                "sameAs": [
                    "https://leblibrary.co.il/about/",
                    "https://merhav.nli.org.il/primo-explore/search?query=any,contains,משה%20לייבוביץ&vid=NLI",
                    "https://hebrewbooks.org/"
                ],
                "jobTitle": "תלמיד חכם, אברך ומחבר ספרים תורניים",
                "worksFor": {
                    "@type": "Organization",
                    "name": "ספריית לייבוביץ - LebLibrary"
                },
                "description": "הרב משה לייבוביץ (משה ליבוביץ) הוא תלמיד חכם ואברך בישיבה מטירת כרמל, מחבר מאמרים תורניים ועשרה ספרי הלכה ומייסד אתר ספריית לייבוביץ.",
                "disambiguatingDescription": "אתר זה הוקם ומנוהל על ידי הרב משה לייבוביץ, תלמיד חכם ואברך מטירת כרמל. אין לו שום קשר למשה ליבוביץ ממקימי ביתר עילית (וראש המועצה הראשון שלה), אין לו שום קשר לפרופ' ישעיהו לייבוביץ, ואין לו שום קשר למשה ליבוביץ הטוען הרבני או לאתרים din.co.il ו-www.mleibowitz.co.il."
            }
        ]
    }, ensure_ascii=False)

def ratelimit(rate=30, timeout=60):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
            else:
                ip = request.META.get('REMOTE_ADDR', 'unknown')

            cache_key = f"api_ratelimit_{ip}"
            history = cache.get(cache_key, [])
            now = time.time()
            history = [t for t in history if now - t < timeout]

            if len(history) >= rate:
                return JsonResponse({
                    'meta': {
                        'error': 'Rate limit exceeded. Maximum requests per minute allowed.',
                        'retry_after_seconds': timeout
                    },
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
    hebrew_letters = {
        400: 'ת', 300: 'ש', 200: 'ר', 100: 'ק',
        90: 'צ', 80: 'פ', 70: 'ע', 60: 'ס', 50: 'נ', 40: 'מ', 30: 'ל', 20: 'כ', 10: 'י',
        9: 'ט', 8: 'ח', 7: 'ז', 6: 'ו', 5: 'ה', 4: 'ד', 3: 'ג', 2: 'ב', 1: 'א'
    }
    result = ""
    rem = num % 100
    if rem in (15, 16):
        result += 'טו' if rem == 15 else 'טז'
        num -= rem

    for val in hebrew_letters.keys():
        while num >= val:
            result += hebrew_letters[val]
            num -= val
    return result


def translate_haftarah(text):
    if not text:
        return ""
    if '|' in text:
        text = text.split('|')[0].strip()

    books = {
        'Genesis': 'בראשית', 'Exodus': 'שמות', 'Leviticus': 'ויקרא', 'Numbers': 'במדבר', 'Deuteronomy': 'דברים',
        'Joshua': 'יהושע', 'Judges': 'שופטים', 'I Samuel': 'שמואל א', 'II Samuel': 'שמואל ב', 'Samuel': 'שמואל',
        'I Kings': 'מלכים א', 'II Kings': 'מלכים ב', 'Kings': 'מלכים', 'Isaiah': 'ישעיהו', 'Jeremiah': 'ירמיהו',
        'Ezekiel': 'יחזקאל', 'Hosea': 'הושע', 'Joel': 'יואל', 'Amos': 'עמוס', 'Obadiah': 'עובדיה', 'Jonah': 'יונה',
        'Micah': 'מיכה', 'Nahum': 'נחום', 'Habakkuk': 'חבקוק', 'Zephaniah': 'צפניה', 'Haggai': 'חגי',
        'Zechariah': 'זכריה', 'Malachi': 'מלאכי', 'Psalms': 'תהילים', 'Proverbs': 'משלי', 'Job': 'איוב',
        'Song of Songs': 'שיר השירים', 'רות': 'רות', 'Lamentations': 'איכה', 'Ecclesiastes': 'קהלת',
        'Esther': 'אסתר', 'Daniel': 'דניאל', 'Ezra': 'עזרא', 'Nehemiah': 'נחמיה', 'I Chronicles': 'דברי הימים א',
        'II Chronicles': 'דברי הימים ב'
    }
    for eng, heb in books.items():
        text = text.replace(eng, heb)

    text = re.sub(r'[a-zA-Z]', '', text).strip()
    text = text.replace('()', '').replace('( )', '').strip()
    text = re.sub(r'\d+', lambda m: int_to_hebrew(int(m.group())), text)
    text = text.replace(':', ', ')
    return text


def get_jewish_calendar_info():
    today = datetime.date.today()
    cache_key = f'jewish_cal_data_v5_{today.strftime("%Y_%m_%d")}'
    cached_data = cache.get(cache_key)

    if cached_data:
        return cached_data

    cal_data = {'parasha': '', 'haftarah': '', 'holidays': [], 'hebrew_date': ''}

    try:
        days_ahead = 5 - today.weekday()
        if days_ahead < 0:
            days_ahead += 7

        next_saturday = today + datetime.timedelta(days=days_ahead)
        start_date = today.strftime('%Y-%m-%d')
        end_date = next_saturday.strftime('%Y-%m-%d')

        try:
            date_url = f'https://www.hebcal.com/converter?cfg=json&date={start_date}&g2h=1&strict=1'
            date_req = urllib.request.Request(date_url, headers={'User-Agent': 'Mozilla/5.0'})
            date_resp = urllib.request.urlopen(date_req, timeout=5)
            date_data = json.loads(date_resp.read().decode('utf-8'))
            cal_data['hebrew_date'] = date_data.get('hebrew', '')
        except Exception:
            cal_data['hebrew_date'] = ''

        url = f'https://www.hebcal.com/hebcal?v=1&cfg=json&geo=IL&lg=he&s=on&maj=on&min=on&start={start_date}&end={end_date}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = urllib.request.urlopen(req, timeout=5)
        data = json.loads(response.read().decode('utf-8'))

        for item in data.get('items', []):
            cat = item.get('category')
            hebrew_text = item.get('hebrew', '')

            if cat == 'parashat':
                cal_data['parasha'] = hebrew_text
                leyning = item.get('leyning', {})
                if 'haftarah' in leyning:
                    cal_data['haftarah'] = translate_haftarah(leyning.get('haftarah', ''))
            elif cat in ['holiday', 'roshchodesh', 'fast']:
                if hebrew_text and hebrew_text not in cal_data['holidays']:
                    if not re.search('[a-zA-Z]', hebrew_text) and 'מבקרים' not in hebrew_text and 'שבת' not in hebrew_text:
                        cal_data['holidays'].append(hebrew_text)

        cache.set(cache_key, cal_data, 60 * 60 * 24)
    except Exception:
        pass

    return cal_data


def generate_word_variations(word):
    variations = set([word])
    if len(word) > 3 and word[0] in 'הבוכשמל':
        variations.add(word[1:])
    if len(word) > 4 and word[:2] in ['וה', 'בה', 'מה', 'שה', 'כה', 'וש', 'ול', 'וכ', 'ומ']:
        variations.add(word[2:])
    return list(variations)


def smart_hebrew_search(queryset, query, search_fields):
    if not query:
        return queryset
    words = [w for w in query.strip().split() if len(w) > 1]
    if not words:
        fallback_q = Q()
        for field in search_fields:
            fallback_q |= Q(**{f"{field}__icontains": query})
        return queryset.filter(fallback_q)

    main_q_and = Q()
    main_q_or = Q()

    for word in words:
        word_variations = generate_word_variations(word)
        word_q = Q()
        for var in word_variations:
            for field in search_fields:
                word_q |= Q(**{f"{field}__icontains": var})
        main_q_and &= word_q
        main_q_or |= word_q

    results = queryset.filter(main_q_and)
    if not results.exists():
        results = queryset.filter(main_q_or)

    score_expr = Value(0)
    score_expr += Case(When(**{f"{search_fields[0]}__icontains": query}, then=Value(50)), default=Value(0), output_field=IntegerField())
    for word in words:
        variations = generate_word_variations(word)
        for var in variations:
            score_expr += Case(When(**{f"{search_fields[0]}__icontains": var}, then=Value(10)), default=Value(0), output_field=IntegerField())
            if len(search_fields) > 1:
                score_expr += Case(When(**{f"{search_fields[1]}__icontains": var}, then=Value(2)), default=Value(0), output_field=IntegerField())

    return results.annotate(relevance=score_expr).order_by('-relevance').distinct()


def get_text_fields(model_class):
    valid_fields = []
    try:
        for f in model_class._meta.get_fields():
            if hasattr(f, 'get_internal_type'):
                if f.get_internal_type() in ['CharField', 'TextField', 'RichTextField', 'RichTextUploadingField', 'HTMLField']:
                    valid_fields.append(f.name)
    except Exception:
        pass
    return valid_fields


def get_item_title(item):
    for field in ['title', 'name', 'header', 'subject', 'question']:
        if hasattr(item, field):
            val = getattr(item, field)
            if val and isinstance(val, str):
                return val.strip()
    try:
        return str(item)
    except Exception:
        return f"{item.__class__.__name__} {getattr(item, 'pk', '')}"


def get_item_text(item):
    text = ""
    try:
        for f in item._meta.get_fields():
            if hasattr(f, 'get_internal_type') and f.get_internal_type() in ['CharField', 'TextField', 'RichTextField', 'RichTextUploadingField', 'HTMLField']:
                val = getattr(item, f.name, '')
                if val and isinstance(val, str) and len(val) > 10:
                    text += val + "\n"
    except Exception:
        pass

    try:
        if item.__class__.__name__ == 'Chapter':
            sections = None
            if hasattr(item, 'sections'):
                sections = item.sections.all()
            elif hasattr(item, 'section_set'):
                sections = item.section_set.all()

            if sections:
                for sec in sections:
                    for f in sec._meta.get_fields():
                        if hasattr(f, 'get_internal_type') and f.get_internal_type() in ['CharField', 'TextField', 'RichTextField', 'RichTextUploadingField', 'HTMLField']:
                            val = getattr(sec, f.name, '')
                            if val and isinstance(val, str) and len(val) > 10:
                                text += val + "\n"
    except Exception:
        pass

    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def ai_document_search(queryset, search_query, search_fields, words, limit=4):
    if not search_fields or not words:
        return []

    main_q_or = Q()
    score_expr = Value(0)

    for word in words:
        word_q = Q()
        for var in generate_word_variations(word):
            for field in search_fields:
                word_q |= Q(**{f"{field}__icontains": var})
        main_q_or |= word_q
        score_expr += Case(When(word_q, then=Value(1)), default=Value(0), output_field=IntegerField())

    candidates = list(queryset.filter(main_q_or).distinct().annotate(match_score=score_expr).order_by('-match_score', '-pk')[:40])

    if not candidates:
        return []

    def get_score(item):
        score = getattr(item, 'match_score', 0) * 1000
        title = get_item_title(item).lower()
        content = get_item_text(item).lower()
        full_text = title + " " + content

        if search_query.lower() in full_text:
            score += 1000000

        unique_matches = sum(1 for word in words if word in full_text)
        score += (unique_matches ** 4) * 50000

        if len(words) > 1 and unique_matches < 2:
            score -= 100000

        for word in words:
            score += full_text.count(word) * 10

        return score

    candidates.sort(key=get_score, reverse=True)
    candidates = [c for c in candidates if get_score(c) > 0]

    return candidates[:limit]


def get_smart_content(text, query_words, max_chars=40000):
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    if not query_words:
        return text[:max_chars]

    best_idx = 0
    max_score = -1
    chunk_size = max_chars
    step = chunk_size // 2

    text_lower = text.lower()
    for i in range(0, len(text), step):
        chunk = text_lower[i:i+chunk_size]
        score = sum(chunk.count(w.lower()) for w in query_words)
        if score > max_score:
            max_score = score
            best_idx = i

    start = max(0, best_idx)
    end = min(len(text), start + chunk_size)
    return ("... " if start > 0 else "") + text[start:end] + (" ..." if end < len(text) else "")


@csrf_exempt
@ratelimit(rate=20, timeout=86400)
def ai_chat_endpoint(request):
    if request.method == 'POST':
        try:
            API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
            if not API_KEY:
                return JsonResponse({'answer': 'Error: Missing API key.'})

            data = json.loads(request.body)
            user_question = data.get('question', '')
            mode = data.get('mode', 'content')

            if not user_question:
                return JsonResponse({'answer': 'Please provide a question.'})

            prompt = ""

            if mode == 'nav':
                nav_context = (
                    "- דף הבית: /\n"
                    "- מנוע חיפוש תורני מתקדם: /advanced-search/\n"
                    "- מתרגם ארמי-עברי (בבלי, ירושלמי והזוהר): /aramaic-translator/\n"
                    "- צור קשר: /contact/\n"
                    "- אודות: /about/\n"
                    "- שאלות ותשובות (שו\"ת): /qa/\n"
                    "- ספרים / חנות ספרים: /books/\n"
                    "- מחשבון מידות אורך: /calculator/\n"
                    "- מחשבון מידות נפח: /volume_calculator/\n"
                    "- מחשבון מידות משקל: /weight_calculator/\n"
                    "- עגלת קניות: /cart/\n"
                    "- קופה / תשלום: /checkout/\n"
                    "- אינדקס מאמרים: /article_index/\n"
                    "- פרשת שבוע: /parasha/\n"
                    "- נוספו לאחרונה: /recently_added/\n"
                    "- תנאי שימוש: /terms/\n"
                    "- מילון ראשי תיבות: /acronyms/\n"
                )
                prompt = f"אתה עוזר וירטואלי באתר 'ספריית לייבוביץ'. עזור לגולש לנווט באתר.\n{nav_context}\nהגולש שואל אותך: '{user_question}'\nחובה עליך לשלב קישור בפורמט מרקדאון עם הנתיב היחסי."
            else:
                clean_question = re.sub(r'[^\w\sא-ת]', '', user_question)
                stop_words = {'מהי', 'מה', 'מי', 'האם', 'מדוע', 'למה', 'איך', 'כיצד', 'מתי', 'היכן', 'איפה', 'של', 'על', 'את', 'עם'}
                words = [w for w in clean_question.split() if len(w) > 1 and w not in stop_words]

                if not words:
                    words = [w for w in clean_question.split() if len(w) > 1]

                semantic_results = []
                try:
                    semantic_results = search_similar_articles(user_question, top_k=2)
                except Exception:
                    pass

                article_fields = get_text_fields(Article)
                db_articles = []
                try:
                    if article_fields:
                        db_articles = ai_document_search(Article.objects.filter(is_published=True), clean_question, article_fields, words, limit=2)
                except Exception:
                    pass

                chapter_fields = get_text_fields(Chapter)
                db_chapters = []
                try:
                    if chapter_fields:
                        db_chapters = ai_document_search(Chapter.objects.all(), clean_question, chapter_fields, words, limit=3)
                except Exception:
                    pass

                section_fields = get_text_fields(Section)
                db_sections = []
                try:
                    if section_fields:
                        db_sections = ai_document_search(Section.objects.all(), clean_question, section_fields, words, limit=2)
                except Exception:
                    pass

                qa_fields = get_text_fields(QA)
                db_qas = []
                try:
                    if qa_fields:
                        db_qas = ai_document_search(QA.objects.all(), clean_question, qa_fields, words, limit=2)
                except Exception:
                    pass

                acronym_matches = []
                try:
                    acronym_matches = list(Acronym.objects.filter(Q(short__icontains=user_question) | Q(meaning__icontains=user_question))[:5])
                except Exception:
                    pass

                context_text = ""
                unique_relevant_items = []
                seen_urls = set()

                def add_to_context(title, url, snippet):
                    nonlocal context_text
                    if url not in seen_urls and snippet and len(snippet.strip()) > 10:
                        seen_urls.add(url)
                        context_text += f"--- מקור: '{title}' ---\nקישור: {url}\n{snippet}\n\n"
                        unique_relevant_items.append({'title': title, 'url': url})

                if acronym_matches:
                    acr_snippet = "\n".join([f"{a.short}: {a.meaning}" for a in acronym_matches])
                    add_to_context("מילון ראשי תיבות", request.build_absolute_uri(reverse('articles:acronyms_view')), acr_snippet)

                if semantic_results:
                    for item in semantic_results:
                        add_to_context(item.get('title', ''), item.get('url', ''), item.get('content_snippet', ''))

                for a in db_articles:
                    url = request.build_absolute_uri(reverse('articles:detail', args=[a.slug]))
                    snippet = get_smart_content(get_item_text(a), words, max_chars=8000)
                    add_to_context(get_item_title(a), url, snippet)

                for c in db_chapters:
                    try:
                        book_id = getattr(c, 'book_id', None) or (c.book.id if hasattr(c, 'book') else None)
                        if book_id:
                            base_book_url = request.build_absolute_uri(reverse('articles:book_detail', args=[book_id]))
                            url = f"{base_book_url}#chapter-{c.id}"
                            title = f"{get_item_title(c.book) if hasattr(c, 'book') else 'ספר'} - {get_item_title(c)}"
                            snippet = get_smart_content(get_item_text(c), words, max_chars=8000)
                            add_to_context(title, url, snippet)
                    except Exception:
                        pass

                for s in db_sections:
                    try:
                        chapter = getattr(s, 'chapter', None)
                        if chapter:
                            book_id = getattr(chapter, 'book_id', None) or (chapter.book.id if hasattr(chapter, 'book') else None)
                            if book_id:
                                base_book_url = request.build_absolute_uri(reverse('articles:book_detail', args=[book_id]))
                                url = f"{base_book_url}#chapter-{chapter.id}"
                                title = f"{get_item_title(chapter.book) if hasattr(chapter, 'book') else 'ספר'} - {get_item_title(chapter)}"
                                snippet = get_smart_content(get_item_text(s), words, max_chars=8000)
                                add_to_context(title, url, snippet)
                    except Exception:
                        pass

                for qa_item in db_qas:
                    try:
                        url = request.build_absolute_uri(reverse('articles:qa'))
                        title = f"שו\"ת - {get_item_title(qa_item)}"
                        snippet = get_smart_content(get_item_text(qa_item), words, max_chars=8000)
                        add_to_context(title, url, snippet)
                    except Exception:
                        pass

                if not unique_relevant_items:
                    return JsonResponse({'answer': 'מצטער, לא הצלחתי לאתר חומרים רלוונטיים במאגרי הספרייה לשאלתך. נסה לנסח אחרת.'})

                prompt = (
                    f"אתה מסייע וירטואלי באתר 'ספריית לייבוביץ'.\n"
                    f"הגולש שואל אותך: '{user_question}'\n\n"
                    f"חוקי יסוד:\n"
                    f"1. ספק תשובה עניינית וישירה אך ורק מתוך המקורות שהובאו בפניך.\n"
                    f"2. הפנה את הגולש לקרוא את המאמר המקורי.\n"
                    f"3. ציין במפורש את שמו של המקור שעליו הסתמכת.\n"
                    f"4. אל תוסיף חתימה או משפטי סיום בסוף התשובה.\n"
                    f"5. המחבר משה לייבוביץ איננו עורך דין ואינו טוען רבני.\n\n"
                    f"מקורות שנסרקו:\n{context_text}"
                )

            def stream_google_response():
                KNOWN_GOOD_MODELS = [
                    'gemini-2.5-flash',
                    'gemini-2.5-flash-lite',
                    'gemini-flash-latest',
                    'gemini-pro-latest'
                ]

                payload = {"contents": [{"parts": [{"text": prompt}]}]}
                data_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')

                response = None
                last_error = ""

                for model in KNOWN_GOOD_MODELS:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={API_KEY}"
                    req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
                    try:
                        response = urllib.request.urlopen(req, timeout=25)
                        break
                    except Exception as e:
                        last_error = str(e)
                        continue

                if not response:
                    yield f"מצטער, שגיאת תקשורת מול השרתים. נסה שוב בעוד מספר שניות. (שגיאה: {last_error})"
                    return

                try:
                    full_generated_text = ""
                    for line in response:
                        decoded_line = line.decode('utf-8').strip()
                        if decoded_line.startswith('data: '):
                            try:
                                json_data = json.loads(decoded_line[6:])
                                text_chunk = json_data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')

                                if text_chunk:
                                    full_generated_text += text_chunk
                                    if mode == 'nav':
                                        text_chunk = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_self" style="color: #2575fc; font-weight: bold; text-decoration: underline;">\1</a>', text_chunk)
                                    else:
                                        text_chunk = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" style="color: #d4af37; font-weight: bold; text-decoration: underline;">\1</a>', text_chunk)

                                    text_chunk = text_chunk.replace('*', '')
                                    yield text_chunk

                            except json.JSONDecodeError:
                                continue

                    if mode != 'nav' and unique_relevant_items and "לא מצאתי לכך התייחסות מפורשת" not in full_generated_text:
                        sources_list_html = ""
                        sources_added = False

                        for item in unique_relevant_items:
                            title = item.get('title', '')
                            url = item.get('url', '')
                            if title and url:
                                title_part = title.split('-')[-1].strip()
                                if title in full_generated_text or (len(title_part) >= 4 and title_part in full_generated_text):
                                    sources_list_html += f"<li style='margin-bottom: 5px;'><a href='{url}' target='_blank' style='color: #d4af37; font-weight: bold; text-decoration: underline;'>{title}</a></li>"
                                    sources_added = True

                        if sources_added:
                            sources_html = "<br><br><div style='margin-top: 15px; padding-top: 10px; border-top: 1px solid #e0e0e0; font-size: 0.95em;'>"
                            sources_html += "<strong>📚 מקורות מהספרייה (לחיץ):</strong><ul style='margin-top: 8px; padding-right: 20px; list-style-type: square;'>"
                            sources_html += sources_list_html
                            sources_html += "</ul></div>"
                            yield sources_html

                except Exception as e:
                    yield f"\n\n[החיבור נקטע: {str(e)}]"
                finally:
                    response.close()

            return StreamingHttpResponse(stream_google_response(), content_type='text/plain')

        except Exception as e:
            return JsonResponse({'answer': f'שגיאת שרת פנימית (views): {str(e)}'})
    return JsonResponse({'error': 'Invalid method'}, status=400)


def article_list(request):
    query = request.GET.get('q')

    if query:
        query = query.strip()
        published_articles = Article.objects.filter(is_published=True).order_by('-created_at')
        articles = smart_hebrew_search(published_articles, query, ['title', 'content'])
        return render(request, 'articles/article_list.html', {
            'articles': articles, 'latest_articles': None, 'reading_books': None, 'sale_books': None,
            'parasha_article': None, 'jewish_cal': None, 'query': query, 'current_page': 'home',
            'schema_json_ld': get_base_schema_json()
        })

    today_str = str(datetime.date.today())
    cache_key = f'home_dynamic_content_{today_str}'

    dynamic_content = cache.get(cache_key)

    if not dynamic_content:
        parasha_article = Article.objects.filter(is_published=True).exclude(
            Q(parasha__isnull=True) |
            Q(parasha__exact='') |
            Q(parasha__exact=',') |
            Q(parasha__exact=',,') |
            Q(parasha__icontains='general')
        ).order_by('?').first()

        recent_15 = list(Article.objects.filter(is_published=True).order_by('-created_at')[:15])
        if parasha_article and parasha_article in recent_15:
            recent_15.remove(parasha_article)
        latest_articles = random.sample(recent_15, min(2, len(recent_15)))

        reading_books = list(Book.objects.filter(is_for_sale=False).order_by('?')[:3])
        sale_books = list(Book.objects.filter(is_for_sale=True).order_by('?')[:3])

        dynamic_content = {
            'parasha_article': parasha_article,
            'latest_articles': latest_articles,
            'reading_books': reading_books,
            'sale_books': sale_books
        }
        cache.set(cache_key, dynamic_content, 60 * 60 * 24)

    parasha_article = dynamic_content['parasha_article']
    latest_articles = dynamic_content['latest_articles']
    reading_books = dynamic_content['reading_books']
    sale_books = dynamic_content['sale_books']

    latest_qa = None
    try:
        qa_pool = list(QA.objects.order_by('-created_at')[:7])
        if qa_pool:
            latest_qa = random.choice(qa_pool)
    except Exception:
        pass

    jewish_cal = get_jewish_calendar_info()

    return render(request, 'articles/article_list.html', {
        'articles': None,
        'parasha_article': parasha_article,
        'latest_articles': latest_articles,
        'reading_books': reading_books,
        'sale_books': sale_books,
        'latest_qa': latest_qa,
        'jewish_cal': jewish_cal,
        'current_page': 'home',
        'schema_json_ld': get_base_schema_json()
    })


def article_detail(request, slug):
    slug_str = str(slug).strip()
    article = Article.objects.filter(slug=slug_str).first()

    if not article and slug_str.isdigit():
        article = Article.objects.filter(pk=int(slug_str)).first()
        if article and article.slug:
            return redirect('articles:detail', slug=article.slug, permanent=True)

    if article:
        if article.slug and article.slug != slug_str:
            return redirect('articles:detail', slug=article.slug, permanent=True)
        return render(request, 'articles/article_detail.html', {'article': article, 'current_page': 'articles'})

    raise Http404(f"העמוד '{slug_str}' לא נמצא.")


@login_required
def article_create(request):
    if request.method == 'POST':
        form = ArticleForm(request.POST)
        if form.is_valid():
            article = form.save()
            ping_indexnow(request.build_absolute_uri(reverse('articles:detail', args=[article.slug])))
        return redirect('articles:list')
    return render(request, 'articles/article_form.html', {'form': ArticleForm(), 'current_page': 'articles'})


@login_required
def article_edit(request, slug):
    if str(slug).isdigit():
        article = get_object_or_404(Article, pk=int(slug))
        return redirect('articles:edit', slug=article.slug, permanent=True)

    article = get_object_or_404(Article, slug=slug)
    if request.method == 'POST':
        form = ArticleForm(request.POST, instance=article)
        if form.is_valid():
            article = form.save()
            ping_indexnow(request.build_absolute_uri(reverse('articles:detail', args=[article.slug])))
        return redirect('articles:detail', slug=article.slug)
    return render(request, 'articles/article_form.html', {'form': ArticleForm(instance=article), 'current_page': 'articles'})


@login_required
def article_delete(request, slug):
    if str(slug).isdigit():
        article = get_object_or_404(Article, pk=int(slug))
        return redirect('articles:delete', slug=article.slug, permanent=True)

    article = get_object_or_404(Article, slug=slug)
    if request.method == 'POST':
        article.delete()
    return redirect('articles:list')


class _SMTP_IPv4(smtplib.SMTP):
    def _get_socket(self, host, port, timeout):
        addrs = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        last_err = None
        for family, socktype, proto, canonname, sockaddr in addrs:
            try:
                sock = socket.socket(family, socktype, proto)
                if timeout is not socket._GLOBAL_DEFAULT_TIMEOUT:
                    sock.settimeout(timeout)
                sock.connect(sockaddr)
                return sock
            except Exception as e:
                last_err = e
        raise last_err or OSError("Could not connect via IPv4")


def _send_gmail_ipv4(subject, body, recipient_list, reply_to_email=None):
    from email.mime.text import MIMEText
    from email.header import Header
    from email.utils import formataddr

    for env_path in [
        os.path.join(settings.BASE_DIR, '.env'),
        os.path.join(settings.BASE_DIR, 'articles', '.env')
    ]:
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            k, v = line.split('=', 1)
                            os.environ[k.strip()] = v.strip().strip('"').strip("'")
            except Exception:
                pass

    smtp_user = os.environ.get('EMAIL_HOST_USER', '').strip() or 'moshe111moshe111@gmail.com'
    raw_pass = os.environ.get('EMAIL_HOST_PASSWORD', '').strip()
    smtp_pass = re.sub(r'\s+', '', raw_pass)

    if not smtp_pass or smtp_pass == 'YOUR_16_LETTER_PASSWORD':
        raise Exception("טרם הוגדרה סיסמת אפליקציה (EMAIL_HOST_PASSWORD) בקובץ ה-.env שבשרת האובונטו.")

    msg = MIMEText(body, 'plain', 'utf-8')
    msg['Subject'] = Header(subject, 'utf-8')
    msg['From'] = formataddr((str(Header('ספריית לייבוביץ', 'utf-8')), smtp_user))
    msg['To'] = ", ".join(recipient_list)
    if reply_to_email:
        msg['Reply-To'] = reply_to_email

    server = _SMTP_IPv4('smtp.gmail.com', 587, timeout=5)
    server.ehlo()
    server.starttls()
    server.ehlo()
    server.login(smtp_user, smtp_pass)
    server.sendmail(smtp_user, recipient_list, msg.as_string())
    server.quit()
    return True


def contact(request):
    if request.method == 'POST':
        try:
            honeypot = request.POST.get('website_url', '').strip()
            if honeypot:
                messages.success(request, 'תודה רבה! הודעתך נשלחה בהצלחה.')
                return redirect('articles:contact')

            name = request.POST.get('name', '').strip() or 'ללא שם'
            phone = request.POST.get('phone', '').strip() or 'לא צוין'
            email = request.POST.get('email', '').strip() or 'לא צוין'
            subject = request.POST.get('subject', '').strip() or 'פנייה כללית מהאתר'
            message = request.POST.get('message', '').strip() or '[הגולש לא כתב תוכן]'

            full_message = (
                f"התקבלה פנייה חדשה מאתר ספריית לייבוביץ:\n\n"
                f"שם: {name}\n"
                f"טלפון: {phone}\n"
                f"אימייל לחזרה: {email}\n"
                f"נושא הפנייה: {subject}\n\n"
                f"תוכן ההודעה:\n{message}"
            )

            try:
                log_path = os.path.join(settings.BASE_DIR, 'contact_messages_backup.jsonl')
                with open(log_path, 'a', encoding='utf-8') as lf:
                    lf.write(json.dumps({
                        'date': str(datetime.datetime.now()),
                        'name': name, 'phone': phone, 'email': email,
                        'subject': subject, 'message': message
                    }, ensure_ascii=False) + "\n")
            except Exception:
                pass

            _send_gmail_ipv4(
                subject=f"פנייה מהאתר: {subject} ({name})",
                body=full_message,
                recipient_list=['moshe111moshe111@gmail.com'],
                reply_to_email=email if '@' in email else None
            )
            messages.success(request, 'תודה רבה! הודעתך נשלחה בהצלחה ונחזור אליך בהקדם.')
        except Exception as e:
            messages.error(request, f'הפנייה נשמרה במערכת, אך שרת המייל החזיר הערה: {e}')
        return redirect('articles:contact')

    return render(request, 'articles/contact.html', {'current_page': 'contact'})

def calculator(request):
    mida_book = Book.objects.filter(title__icontains='מידה').first()
    return render(request, 'articles/calculator.html', {'current_page': 'calculator', 'mida_book': mida_book})


def volume_calculator(request):
    mida_book = Book.objects.filter(title__icontains='מידה').first()
    return render(request, 'articles/volume_calculator.html', {'current_page': 'calculator', 'mida_book': mida_book})


def weight_calculator(request):
    mida_book = Book.objects.filter(title__icontains='מידה').first()
    return render(request, 'articles/weight_calculator.html', {'current_page': 'calculator', 'mida_book': mida_book})


@cache_page(60 * 60 * 24)
def about(request):
    return render(request, 'articles/about.html', {'current_page': 'about', 'schema_json_ld': get_base_schema_json()})


@cache_page(60 * 60 * 24)
def terms(request):
    return render(request, 'articles/terms.html', {'current_page': 'terms'})


def books_list(request):
    return render(request, 'articles/books_list.html', {'current_page': 'books'})


def qa_list(request):
    try:
        questions = QA.objects.all().order_by('-created_at')
        categories = QA.objects.exclude(category__isnull=True).exclude(category__exact='').values_list('category', flat=True).distinct()

        q = request.GET.get('q')
        if q:
            questions = questions.filter(Q(question__icontains=q) | Q(answer__icontains=q))

        category = request.GET.get('category')
        if category:
            questions = questions.filter(category=category)

    except Exception:
        questions = None
        categories = []

    return render(request, 'articles/qa_list.html', {
        'questions': questions,
        'categories': categories,
        'current_page': 'qa'
    })


def acronyms_view(request):
    query = request.GET.get('q', '').strip()
    search_type = request.GET.get('type', 'short')

    acronyms = None
    if query:
        query_clean = re.sub(r'["״”“\'׳`]', '', query)
        query_with_geresh = query_clean
        if len(query_clean) > 1 and '"' not in query:
            query_with_geresh = query_clean[:-1] + '"' + query_clean[-1]

        if search_type == 'meaning':
            acronyms = Acronym.objects.filter(meaning__icontains=query).order_by('short')
        else:
            acronyms = Acronym.objects.filter(
                Q(short__icontains=query) |
                Q(short__icontains=query_clean) |
                Q(short__icontains=query_with_geresh)
            ).distinct().order_by('short')
    else:
        acronyms = Acronym.objects.all().order_by('short')[:100]

    return render(request, 'articles/acronyms.html', {
        'acronyms': acronyms,
        'query': query,
        'search_type': search_type,
        'current_page': 'acronyms'
    })


def article_index(request):
    published_articles = Article.objects.filter(is_published=True).order_by('title')
    articles_count = published_articles.count()
    grouped_articles = {}
    for article in published_articles:
        if article.title:
            first_letter = article.title.strip()[0]
            if first_letter not in grouped_articles:
                grouped_articles[first_letter] = []
            grouped_articles[first_letter].append(article)
    sorted_groups = {k: grouped_articles[k] for k in sorted(grouped_articles.keys())}
    return render(request, 'articles/article_index.html', {
        'grouped_articles': sorted_groups,
        'articles_count': articles_count,
        'current_page': 'articles'
    })


def recently_added(request):
    recent_articles = Article.objects.filter(is_published=True).order_by('-id')[:12]
    return render(request, 'articles/recently_added.html', {'articles': recent_articles, 'current_page': 'recently_added'})


def parasha_list(request):
    selected_parasha = request.GET.get('p')
    articles = None
    if selected_parasha:
        parasha_q = Q(parasha__icontains=f",{selected_parasha},") | Q(parasha=selected_parasha)
        articles = Article.objects.filter(parasha_q, is_published=True).order_by('-created_at')
    return render(request, 'articles/parasha_list.html', {'current_page': 'parasha', 'selected_parasha': selected_parasha, 'articles': articles})


def book_detail(request, pk):
    book = get_object_or_404(
        Book.objects.prefetch_related('chapters__sections'),
        pk=pk
    )
    book_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "Book",
        "@id": f"https://leblibrary.co.il/book/{book.pk}/#book",
        "name": strip_tags(book.title or ""),
        "author": {
            "@type": "Person",
            "name": "הרב משה לייבוביץ",
            "homeLocation": "טירת כרמל",
            "url": "https://leblibrary.co.il/about/"
        },
        "publisher": {
            "@type": "Organization",
            "name": "ספריית לייבוביץ - LebLibrary"
        },
        "inLanguage": "he",
        "url": f"https://leblibrary.co.il/book/{book.pk}/",
        "description": strip_tags(book.summary or book.title or "")[:300]
    }, ensure_ascii=False)

    return render(request, 'articles/book_detail.html', {
        'book': book,
        'current_page': 'books',
        'schema_json_ld': book_schema
    })


def books(request):
    books_ordered = Book.objects.all().order_by('order', 'title')
    return render(request, 'articles/books_list.html', {'books': books_ordered, 'current_page': 'books'})


def live_search(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'results': []})
    cache_key = f'live_search_{q}'
    cached_results = cache.get(cache_key)
    if cached_results:
        return JsonResponse({'results': cached_results})

    books_qs = Book.objects.all()
    articles_qs = Article.objects.filter(is_published=True)
    books_res = smart_hebrew_search(books_qs, q, ['title', 'author']).only('id', 'title')[:3]
    articles_res = smart_hebrew_search(articles_qs, q, ['title', 'content']).only('id', 'title', 'slug')[:4]

    results = []
    for book in books_res:
        results.append({'title': book.title, 'type': 'ספר שלם', 'icon': 'bi-journal-bookmark-fill', 'url': reverse('articles:book_detail', args=[book.id])})
    for article in articles_res:
        results.append({'title': article.title, 'type': 'מאמר', 'icon': 'bi-file-earmark-text', 'url': reverse('articles:detail', args=[article.slug])})

    cache.set(cache_key, results, timeout=300)
    return JsonResponse({'results': results})


@ratelimit(rate=30, timeout=60)
def ai_open_search(request):
    q = request.GET.get('q', '').strip()
    results = []

    if len(q) < 2:
        return JsonResponse({
            'meta': {'error': 'Missing or too short query parameter "q".'},
            'results': []
        }, status=400)

    words = [w for w in q.split() if len(w) > 1]
    books_qs = Book.objects.all()
    articles_qs = Article.objects.filter(is_published=True)

    semantic_results = []
    try:
        semantic_results = search_similar_articles(q, top_k=3)
    except Exception:
        semantic_results = []

    if semantic_results:
        for item in semantic_results:
            results.append({
                'title': item.get('title', ''),
                'type': 'Article',
                'url': request.build_absolute_uri(item.get('url', '/')),
                'content_snippet': item.get('content_snippet', '')
            })
    else:
        books_res = smart_hebrew_search(books_qs, q, ['title', 'author', 'summary'])[:3]
        articles_res = smart_hebrew_search(articles_qs, q, ['title', 'content'])[:3]

        for article in articles_res:
            results.append({
                'title': get_item_title(article),
                'type': 'Article',
                'url': request.build_absolute_uri(reverse('articles:detail', args=[article.slug])),
                'content_snippet': get_smart_content(get_item_text(article), words, max_chars=1500)
            })

        for book in books_res:
            results.append({
                'title': get_item_title(book),
                'type': 'Book',
                'url': request.build_absolute_uri(reverse('articles:book_detail', args=[book.id])),
                'content_snippet': get_smart_content(get_item_text(book), words, max_chars=1500)
            })

    return JsonResponse({
        'meta': {
            'provider': 'LebLibrary - ספריית לייבוביץ בניהולו של הרב משה לייבוביץ (טירת כרמל)',
            'query': q,
            'total_results': len(results),
            'license': 'Open for AI crawling with attribution'
        },
        'results': results
    }, json_dumps_params={'ensure_ascii': False})


def _get_or_create_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart
    else:
        if not request.session.session_key:
            request.session.create()
        cart, _ = Cart.objects.get_or_create(session_id=request.session.session_key)
        return cart


def add_to_cart(request, book_id):
    book = get_object_or_404(Book, id=book_id, is_for_sale=True)
    cart = _get_or_create_cart(request)
    cart_item, created = CartItem.objects.get_or_create(cart=cart, book=book)
    if not created:
        cart_item.quantity += 1
        cart_item.save()
    messages.success(request, f'הספר "{book.title}" נוסף לעגלת הקניות בהצלחה.')
    return redirect('articles:cart_detail')


def remove_from_cart(request, item_id):
    cart = _get_or_create_cart(request)
    item = get_object_or_404(CartItem, id=item_id, cart=cart)
    item.delete()
    messages.info(request, 'הפריט הוסר מעגלת הקניות.')
    return redirect('articles:cart_detail')


def cart_detail(request):
    cart = _get_or_create_cart(request)
    items = cart.items.select_related('book').all()
    total_price = sum(item.get_total_price() for item in items)
    return render(request, 'articles/cart_detail.html', {'cart': cart, 'items': items, 'total_price': total_price, 'current_page': 'cart'})


def checkout(request):
    cart = _get_or_create_cart(request)
    items = cart.items.select_related('book').all()
    if not items:
        messages.error(request, 'העגלה שלך ריקה. אנא הוסף ספרים לפני המעבר לקופה.')
        return redirect('articles:books')
    total_price = sum(item.get_total_price() for item in items)
    if request.method == 'POST':
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        email = request.POST.get('email')
        phone = request.POST.get('phone')
        address = request.POST.get('address')
        city = request.POST.get('city')
        zip_code = request.POST.get('zip_code', '')
        notes = request.POST.get('notes', '')

        with transaction.atomic():
            order = Order.objects.create(
                first_name=first_name, last_name=last_name, email=email, phone=phone,
                address=address, city=city, zip_code=zip_code, notes=notes,
                total_paid=total_price, status='pending'
            )
            for item in items:
                OrderItem.objects.create(order=order, book=item.book, price=item.book.price, quantity=item.quantity)
            cart.items.all().delete()

        try:
            send_order_confirmation(order)
        except Exception:
            pass
        return render(request, 'articles/order_success.html', {'order': order})
    return render(request, 'articles/checkout.html', {'items': items, 'total_price': total_price, 'current_page': 'cart'})


def ping_indexnow(article_url):
    host = "leblibrary.co.il"
    key = "mosheleibowitzkey123"
    url = f"https://api.indexnow.org/indexnow?url={urllib.parse.quote(article_url)}&key={key}&keyLocation=https://{host}/{key}.txt"
    try:
        urllib.request.urlopen(url, timeout=5)
    except Exception:
        pass


@receiver([post_save, post_delete], sender=Article)
@receiver([post_save, post_delete], sender=Book)
def clear_cache_on_db_change(sender, instance, **kwargs):
    cache.clear()


def load_tts_dictionary():
    dict_path = os.path.join(settings.BASE_DIR, 'tts_dictionary.json')
    if not os.path.exists(dict_path):
        dict_path = os.path.join(settings.BASE_DIR, 'articles', 'tts_dictionary.json')

    if os.path.exists(dict_path):
        try:
            with open(dict_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass

    return {
        'רמב"ם': 'רמבם', 'רש"י': 'רשי', 'שו"ע': 'שולחן ערוך', 'שו"ת': 'שאלות ותשובות',
        'רמב"ן': 'רמבן', 'רס"ג': 'רב סעדיה גאון', "תוס'": 'תוספות', "גמ'": 'גמרא',
        'וכו\'': 'וכולי', 'ע"ד': 'על דרך', 'ע"י': 'על ידי', "לכאו'": 'לכאורה',
        'כמו"ש': 'כמו שכתוב', 'ע"כ': 'עד כאן', 'קא משמע לן': 'קָא מַשְׁמַע לָן',
        'אי נמי': 'אִי נַמִּי', 'מנא לן': 'מְנָא לָן', 'פשיטא': 'פְּשִׁיטָא',
        'הכי נמי': 'הָכִי נַמִּי', 'תנא': 'תַּנָּא', 'א"כ': 'אם כן', 'ג"כ': 'גם כן',
        'אע"פ': 'אף על פי', 'בד"כ': 'בדרך כלל', 'חז"ל': 'חכמינו זיכרונם לברכה',
        'יו"ט': 'יום טוב', 'ק"ו': 'קל וחומר', 'ת"ח': 'תלמיד חכם', 'בע"ה': 'בעזרת השם',
        'זצ"ל': 'זכר צדיק לברכה', 'שליט"א': 'שיחיה לאורך ימים טובים אמן',
        'הקב"ה': 'הקדוש ברוך הוא', 'רבש"ע': 'ריבונו של עולם',
        'איתא': 'אִיתָא', 'ליתא': 'לֵיתָא', 'הכא': 'הָכָא', 'התם': 'הָתָם', 'האי': 'זה', 'הני': 'אלה',
        'מאי': 'מַאי', 'אמאי': 'אַמַּאי', 'בשלמא': 'בִּשְׁלָמָא', 'אדרבה': 'אַדְּרַבָּה', 'אלמא': 'אלמא',
        'הפ"ש הה"ש': 'הפה שאסר הוא הפה שהתיר',
        'ממע"ה': 'המוציא מחברו עליו הראיה',
        'עדל"ת': 'עשה דוחה לא תעשה',
        'הו"א': 'הוה אמינא',
        'קיי"ל': 'קיימא לן',
        'קי"ל': 'קיימא לן',
        'ס"ל': 'סבירא ליה',
        'דאו\'': 'דאורייתא',
        'ד"ת': 'דבר תורה',
        'דרבנן': 'מדרבנן',
        'ד"ס': 'דברי סופרים',
        'ל"א': 'לשון אחר',
        'ה"ה': 'הוא הדין',
        'הה"ה': 'הוא הדין',
        'ס.': 'סימן',
        'שו"פ': 'שווה פרוטה',
        'שו"כ': 'שווה כסף',
        'שכו"ע': 'שאר כסות ועונה',
        'ע"ע': 'עבד עברי',
        'ש"כ': 'שפחה כנענית',
        'אמ"ה': 'אבר מן החי',
        'איסוה"נ': 'איסורי הנאה',
        'מחוק"צ': 'מחוסר קציצה',
        'ע"ח': 'עדי חתימה',
        'ע"מ': 'עדי מסירה',
        'ב"א': 'בת אחת',
        'ש"ש': 'שור שחוט',
        'א"א': 'אשת איש',
        'בע"ד': 'בעל דין',
        'פס"ד': 'פסק דין',
        'בי"ד': 'בית דין',
        'למדה"י': 'למדינת הים',
        'ל"ת': 'לא תעשה',
        'אאחע"א': 'אין איסור חל על איסור',
        'אחע"א': 'איסור חל על איסור',
        'ריטב"א': 'רבי יום טוב בן אברהם אשבילי',
        'רא"ש': 'רבנו אשר',
        'ר"ן': 'רבנו נסים',
        'תו"ר': 'תוספות רא"ש',
        'ראמ"ה': 'רבינו אברהם מן ההר',
        'ב"ש': 'בית שמאי',
        'ב"ה': 'בית הלל',
        'ר"ע': 'רבי עקיבא',
        'ר"מ': 'רבי מאיר',
        'ריה"ג': 'רבי יוסי הגלילי',
        'ר"ל': 'ריש לקיש',
        'אר"נ': 'אמר רב נחמן',
        'ר"י': 'רבינו יצחק',
        'ריבר"י': 'רבי יוסי בן יהודה',
        'ריב"ח': 'רבי יהושע בן חנינא',
        'ת"ר': 'תנו רבנן',
        'ב"ק': 'בבא קמא',
        'ב"מ': 'בבא מציעא',
        'ב"ב': 'בבא בתרא',
        'קי\'': 'קידושין',
        'כת\'': 'כתובות',
        'יב\'': 'יבמות',
        'סנ\'': 'סנהדרין',
        'פס\'': 'פסחים',
        'מו"ק': 'מועד קטן',
        'אוה"ע': 'אומות העולם',
        'איסו"ב': 'איסורי ביאה',
        'אסו"ב': 'איסורי ביאה',
        'בד"א': 'במה דברים אמורים',
        'פ"ח': 'פנים חדשות',
        'פו"ר': 'פריה ורביה',
        'פיה"מ': 'פירוש המשניות',
        'ד"מ': 'דרכי משה',
        'תוה"א': 'תורת האדם',
        'פמ"ג': 'פרי מגדים',
        'כס"מ': 'כסף משנה',
        'לח"מ': 'לחם משנה',
        'משל"מ': 'משנה למלך',
        'נ"י': 'נימוקי יוסף',
        'או"ז': 'אור זרוע',
        'אר"ח': 'אורחות חיים',
        'ראב"ד': 'רבנו אברהם בן דוד',
        'רשב"א': 'רבינו שלמה בן אדרת',
        'רשב"ג': 'רבן שמעון בן גמליאל',
        'רי"ף': 'רבנו יצחק אלפסי',
        'ר"ח': 'רבנו חננאל',
        'רי"ו': 'רבינו ירוחם',
        'מהרי"ק': 'מורנו הרב רבי יוסף קולון',
        'ריב"ש': 'רבינו יצחק בן ששת',
        'רדב"ז': 'רבי דוד בן זמרא',
        'תשב"ץ': 'תשובות שמעון בן צמח'
    }


def apply_tts_dictionary(text):
    if not text:
        return ""

    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.IGNORECASE | re.DOTALL)

    text = text.replace('><', '> <').replace('</p>', '.\n').replace('</li>', '.\n')
    text = strip_tags(text)
    text = unescape(text)

    text = re.sub(r'\[.*?\]', '', text)
    text = re.sub(r'\(\d+\)', '', text)
    text = re.sub(r'[*_#]', '', text)

    tts_dict = load_tts_dictionary()
    sorted_keys = sorted(tts_dict.keys(), key=len, reverse=True)

    for key in sorted_keys:
        val = tts_dict[key]
        if '"' in key or "'" in key or " " in key:
            text = text.replace(key, val)
        else:
            text = re.sub(rf'(?<![א-ת]){key}(?![א-ת])', val, text)

    text = re.sub(r'([א-ת])"([א-ת])', r'\1\2', text)
    text = re.sub(r"([א-ת])'([א-ת])", r'\1\2', text)

    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\.+', '.', text)

    text = text.replace('. ', '.\n')
    text = text.replace(':\n', ': \n')

    text = '\n'.join([s.strip() for s in text.splitlines() if s.strip()])

    return text.strip()


def generate_audio_sync(text, file_path):
    async def _generate():
        communicate = edge_tts.Communicate(text, "he-IL-AvriNeural")
        await communicate.save(file_path)

    try:
        asyncio.run(_generate())
    except Exception as e:
        raise Exception(f"Edge-TTS Error: {str(e)}")


def generate_article_audio_background(article_id):
    try:
        article = Article.objects.get(id=article_id)
        if not article.is_published:
            return
        base_media = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
        audio_dir = os.path.join(base_media, 'audio')
        os.makedirs(audio_dir, exist_ok=True)

        file_name = f"article_{article.id}.mp3"
        file_path = os.path.join(audio_dir, file_name)

        if not os.path.exists(file_path):
            raw_text = f"{article.title}. {article.content or ''}"
            try:
                if hasattr(article, 'chapter') and article.chapter:
                    sections = Section.objects.filter(chapter=article.chapter).order_by('order')
                    for sec in sections:
                        if sec.title:
                            raw_text += f" {sec.title}. "
                        if sec.content:
                            raw_text += f"{sec.content} "
                elif hasattr(article, 'book') and article.book:
                    chapters = Chapter.objects.filter(book=article.book).order_by('order')
                    for ch in chapters:
                        if ch.title:
                            raw_text += f" {ch.title}. "
                        sections = Section.objects.filter(chapter=ch).order_by('order')
                        for sec in sections:
                            if sec.title:
                                raw_text += f" {sec.title}. "
                            if sec.content:
                                raw_text += f"{sec.content} "
            except Exception:
                pass
            final_text = apply_tts_dictionary(raw_text)
            generate_audio_sync(final_text, file_path)
    except Exception:
        pass


@receiver(post_save, sender=Article)
def trigger_article_audio_pregeneration(sender, instance, created, **kwargs):
    if instance.is_published:
        base_media = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
        file_path = os.path.join(base_media, 'audio', f"article_{instance.id}.mp3")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

        transaction.on_commit(lambda: threading.Thread(target=generate_article_audio_background, args=(instance.id,)).start())


def get_article_audio(request, identifier):
    try:
        if str(identifier).isdigit():
            article = Article.objects.get(id=int(identifier))
        else:
            article = Article.objects.get(slug=identifier)
    except Article.DoesNotExist:
        return JsonResponse({'error': 'Article not found'}, status=404)

    base_media = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
    audio_dir = os.path.join(base_media, 'audio')
    os.makedirs(audio_dir, exist_ok=True)

    file_name = f"article_{article.id}.mp3"
    file_path = os.path.join(audio_dir, file_name)
    media_url = getattr(settings, 'MEDIA_URL', '/media/')

    if not os.path.exists(file_path):
        raw_text = f"{article.title}. {article.content or ''}"
        try:
            if hasattr(article, 'chapter') and article.chapter:
                sections = Section.objects.filter(chapter=article.chapter).order_by('order')
                for sec in sections:
                    if sec.title:
                        raw_text += f" {sec.title}. "
                    if sec.content:
                        raw_text += f"{sec.content} "
            elif hasattr(article, 'book') and article.book:
                chapters = Chapter.objects.filter(book=article.book).order_by('order')
                for ch in chapters:
                    if ch.title:
                        raw_text += f" {ch.title}. "
                    sections = Section.objects.filter(chapter=ch).order_by('order')
                    for sec in sections:
                        if sec.title:
                            raw_text += f" {sec.title}. "
                        if sec.content:
                            raw_text += f"{sec.content} "
        except Exception:
            pass
        final_text = apply_tts_dictionary(raw_text)
        try:
            generate_audio_sync(final_text, file_path)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    file_version = int(os.path.getmtime(file_path)) if os.path.exists(file_path) else 1
    audio_url = f"{media_url}audio/{file_name}?v={file_version}"

    return JsonResponse({'audio_url': audio_url})


def get_book_audio(request, book_id):
    try:
        book = Book.objects.get(id=book_id)
    except Book.DoesNotExist:
        return JsonResponse({'error': 'Book not found'}, status=404)

    base_media = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
    audio_dir = os.path.join(base_media, 'audio')
    os.makedirs(audio_dir, exist_ok=True)

    file_name = f"book_{book.id}.mp3"
    file_path = os.path.join(audio_dir, file_name)
    media_url = getattr(settings, 'MEDIA_URL', '/media/')

    if not os.path.exists(file_path):
        raw_text = f"{book.title}. "
        if book.summary:
            raw_text += book.summary + " "

        try:
            chapters = Chapter.objects.filter(book=book).order_by('order')
            for ch in chapters:
                if ch.title:
                    raw_text += f" {ch.title}. "
                sections = Section.objects.filter(chapter=ch).order_by('order')
                for sec in sections:
                    if sec.title:
                        raw_text += f" {sec.title}. "
                    if sec.content:
                        raw_text += f"{sec.content} "
        except Exception:
            pass

        final_text = apply_tts_dictionary(raw_text)
        try:
            generate_audio_sync(final_text, file_path)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    file_version = int(os.path.getmtime(file_path)) if os.path.exists(file_path) else 1
    audio_url = f"{media_url}audio/{file_name}?v={file_version}"

    return JsonResponse({'audio_url': audio_url})


def search_acronyms_api(request):
    query = request.GET.get('q', '').strip()
    search_type = request.GET.get('type', 'short')

    results = []
    if len(query) >= 1:
        query_clean = re.sub(r'["״”“\'׳`]', '', query)
        query_with_geresh = query_clean
        if len(query_clean) > 1 and '"' not in query:
            query_with_geresh = query_clean[:-1] + '"' + query_clean[-1]

        if search_type == 'meaning':
            matches = Acronym.objects.filter(meaning__icontains=query)[:20]
        else:
            matches = Acronym.objects.filter(
                Q(short__icontains=query) |
                Q(short__icontains=query_clean) |
                Q(short__icontains=query_with_geresh)
            ).distinct()[:20]

        for item in matches:
            results.append({
                'short': item.short,
                'meaning': item.meaning
            })

    return JsonResponse({'results': results})


def advanced_search_view(request):
    return render(request, 'articles/advanced_search.html', {'current_page': 'advanced_search'})


def or_hacarmel_view(request):
    return render(request, 'articles/or_hacarmel.html')


def get_book_order(book_name):
    name = book_name.strip()
    BOOK_ORDER = {
        'בראשית': 1, 'שמות': 2, 'ויקרא': 3, 'במדבר': 4, 'דברים': 5,
        'יהושע': 6, 'שופטים': 7, 'שמואל א': 8, 'שמואל ב': 9, 'מלכים א': 10, 'מלכים ב': 11,
        'ישעיהו': 12, 'ירמיהו': 13, 'יחזקאל': 14, 'הושע': 15, 'יואל': 16, 'עמוס': 17, 'עובדיה': 18,
        'יונה': 19, 'מיכה': 20, 'נחום': 21, 'חבקוק': 22, 'צפניה': 23, 'חגי': 24, 'זכריה': 25, 'מלאכי': 26,
        'תהילים': 27, 'משלי': 28, 'איוב': 29, 'שיר השירים': 30, 'רות': 31, 'איכה': 32, 'קהלת': 33,
        'אסתר': 34, 'דניאל': 35, 'עזרא': 36, 'נחמיה': 37, 'דברי הימים א': 38, 'דברי הימים ב': 39,
        'ברכות': 40, 'פאה': 41, 'דמאי': 42, 'כלאים': 43, 'שביעית': 44, 'תרומות': 45, 'מעשרות': 46, 'מעשר שני': 47, 'חלה': 48, 'ערלה': 49, 'ביכורים': 50,
        'שבת': 51, 'עירובין': 52, 'פסחים': 53, 'שקלים': 54, 'יומא': 55, 'סוכה': 56, 'ביצה': 57, 'ראש השנה': 58, 'תענית': 59, 'מגילה': 60, 'מועד קטן': 61, 'חגיגה': 62,
        'יבמות': 63, 'כתובות': 64, 'נדרים': 65, 'נזיר': 66, 'סוטה': 67, 'גיטין': 68, 'קידושין': 69,
        'בבא קמא': 70, 'בבא מציעא': 71, 'בבא בתרא': 72, 'סנהדרין': 73, 'מכות': 74, 'שבועות': 75, 'עדיות': 76, 'עבודה זרה': 77, 'אבות': 78, 'הוריות': 79,
        'זבחים': 80, 'מנחות': 81, 'חולין': 82, 'בכורות': 83, 'ערכין': 84, 'תמורה': 85, 'כריתות': 86, 'מעילה': 87, 'תמיד': 88, 'מדות': 89, 'קינים': 90,
        'כלים': 91, 'אהלות': 92, 'נגעים': 93, 'פרה': 94, 'טהרות': 95, 'מקואות': 96, 'נדה': 97, 'מכשירין': 98, 'זבים': 99, 'טבול יום': 100, 'ידים': 101, 'עוקצין': 102
    }
    if name.startswith('תוספתא '):
        base = name.replace('תוספתא ', '', 1).strip()
        return 120 + BOOK_ORDER.get(base, 90)
    if name.startswith('ירושלמי '):
        base = name.replace('ירושלמי ', '', 1).strip()
        return 250 + BOOK_ORDER.get(base, 90)
    if name.startswith('רמב"ם '):
        return 400
    if name.startswith('שולחן ערוך '):
        sa_order = {'שולחן ערוך אורח חיים': 501, 'שולחן ערוך יורה דעה': 502, 'שולחן ערוך אבן העזר': 503, 'שולחן ערוך חושן משפט': 504}
        return sa_order.get(name, 510)
    return BOOK_ORDER.get(name, 999)


def safe_int(v):
    s = str(v).strip()
    if s.isdigit():
        return int(s)
    m = re.search(r'\d+', s)
    if m:
        return int(m.group(0))
    s_clean = re.sub(r'^(פרק|סימן|דף|הלכה|משנה|סעיף)\s+', '', s)
    parts = s_clean.split()
    if parts:
        heb_num = sum(HEBREW_GEMATRIA.get(c, 0) for c in parts[0])
        amud = 2 if 'עמוד ב' in s else 1
        return heb_num * 10 + amud
    return 0


@ratelimit(rate=30, timeout=60)
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
        b_str = str(book_name)
        c_str = str(chapter_name)
        if b_str.startswith('שולחן ערוך '):
            return 'סעיף'
        elif b_str.startswith('רמב"ם ') or b_str.startswith('ירושלמי ') or b_str.startswith('תוספתא '):
            return 'הלכה'
        elif c_str.startswith('דף'):
            return 'שורה'
        elif b_str not in TANAKH_NAMES:
            return 'משנה'
        return 'פסוק'

    if query_type == 'chapter_context':
        target_book = request.GET.get('target_book', '').strip()
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
                        'verse': v['verse'],
                        'text': format_divine_name(v['text_with_nikkud'] or v['clean_text'] or '')
                    }
                    for v in ch_verses
                ]
            }, json_dumps_params={'ensure_ascii': False})
        return JsonResponse({'verses': []})

    try:
        per_page = int(request.GET.get('per_page', 10))
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except ValueError:
        per_page = 10

    search_cache_key = f"tanakh_srch_v3_{query_type}_{query_val}_{book_filter}_{is_exact}_{exclude_books_param}_{skip_param}_{page}_{per_page}"
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
                all_verses = qs.values('book', 'chapter', 'verse','text_with_nikkud').iterator(chunk_size=2000)

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
                            'verse': m['verse'],
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
                        'verse': m['verse'],
                        'verse_label': get_verse_label(m['book'], m['chapter']),
                        'text': final_text,
                        'match_type': m_type
                    })

        elif query_type in ['acronym', 'rashei_tevot', 'sofei_tevot', 'suffix'] and query_val:
            is_sofei = query_type in ['sofei_tevot', 'suffix']
            target_acr = norm_heb(re.sub(r'[^א-ת]', '', query_val))

            if target_acr:
                acr_len = len(target_acr)
                all_verses = qs.values('book', 'chapter', 'verse','text_with_nikkud').iterator(chunk_size=2000)
                                       
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
                            'verse': m['verse'],
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
                all_verses = qs.values('book', 'chapter', 'verse','text_with_nikkud').iterator(chunk_size=2000)

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
                            'verse': m['verse'],
                            'verse_label': get_verse_label(m['book'], m['chapter']),
                            'text': final_text,
                            'match_type': m_label
                        })

        elif query_type in ['els', 'skip', 'dilugim'] and query_val:
            target_els = norm_heb(re.sub(r'[^א-ת]', '', query_val))
            k = len(target_els)
            if k >= 2:
                all_verses = qs.values('book', 'chapter', 'verse','text_with_nikkud').iterator(chunk_size=2000)
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
                            'verse': m['verse'],
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

                all_verses = qs.values('book', 'chapter', 'verse','text_with_nikkud').iterator(chunk_size=2000)
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
                            'verse': m['verse'],
                            'verse_label': get_verse_label(m['book'], m['chapter']),
                            'text': final_text,
                            'match_type': m_type,
                            'skip_distance': chosen_skip
                        })

                available_skips = [
                    {'skip': s_d, 'count': skip_counts[s_d]}
                    for s_d in sorted(skip_counts.keys())
                ]

        results.sort(key=lambda x: (get_book_order(x['book']), safe_int(x['chapter']), safe_int(x['verse'])))

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
    book = request.GET.get('book', '').strip()
    chapter = request.GET.get('chapter', '').strip()
    verse = request.GET.get('verse', '').strip()

    cache_key = f"torah_ai_v6_{mode}_{book}_{chapter}_{verse}_{query}"
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

    def call_gemini_fast(prompt_text):
        api_key = os.environ.get('GEMINI_API_KEY', '').strip() or getattr(settings, 'GEMINI_API_KEY', '').strip()
        if not api_key:
            return ""
        models_list = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash-latest']
        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
        data_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        for m_name in models_list:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
            req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=5) as resp:
                    resp_data = json.loads(resp.read().decode('utf-8'))
                    ans = resp_data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                    if ans and len(ans.strip()) > 20:
                        cleaned = re.sub(r'[*#]+', '', ans).strip()
                        return format_divine_name(cleaned)
            except Exception:
                continue
        return ""

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

    def analyze_concept_deeply(raw_query):
        clean_q = re.sub(r'[^א-ת\s]', '', raw_query.replace('י-ה-ו-ה', 'יהוה')).strip()
        search_core = re.sub(r'^(פרשת|הלכות|מסכת|מצוות|מצות|עניין|דיני)\s+', '', clean_q).strip() or clean_q
        q_words = [w for w in search_core.split() if len(w) >= 1]
        q_gem = calculate_gematria(search_core)
        q_letters_only = NON_HEB_RE.sub('', search_core)
        q_norm = norm_heb(q_letters_only)

        base_qs = TorahText.objects.all()
        for w in q_words:
            base_qs = base_qs.filter(Q(clean_text__icontains=w) | Q(text_with_nikkud__icontains=w))

        tanakh_matches_raw = list(
            base_qs.filter(book__in=TANAKH_NAMES).exclude(chapter__startswith='דף')
            .values('id', 'book', 'chapter', 'verse', 'clean_text', 'text_with_nikkud', 'verse_gematria')[:800]
        )
        other_matches_raw = list(
            base_qs.exclude(book__in=TANAKH_NAMES)
            .values('id', 'book', 'chapter', 'verse', 'clean_text', 'text_with_nikkud', 'verse_gematria')[:1200]
        )
        bavli_tanakh_named = list(
            base_qs.filter(book__in=TANAKH_NAMES, chapter__startswith='דף')
            .values('id', 'book', 'chapter', 'verse', 'clean_text', 'text_with_nikkud', 'verse_gematria')[:400]
        )
        candidates = tanakh_matches_raw + other_matches_raw + bavli_tanakh_named

        corpus_counts = {'torah': 0, 'nach': 0, 'mishnah_tosefta': 0, 'talmud': 0, 'halacha': 0}
        book_freq = {}
        chapter_freq = {}
        valid_records = []
        num_q_words = len(q_words)

        for row in candidates:
            raw_txt = row.get('text_with_nikkud') or row.get('clean_text') or ''
            if not raw_txt:
                continue

            tokens = list(WORD_TOKEN_RE.finditer(raw_txt))
            tok_words = []
            tok_spans = []
            for tok in tokens:
                w_heb = NON_HEB_RE.sub('', tok.group(0))
                if w_heb:
                    tok_words.append(w_heb)
                    tok_spans.append(tok.span())

            if len(tok_words) < num_q_words:
                continue

            exact_spans = []
            prefix_spans = []

            if num_q_words == 1:
                tw = q_words[0]
                for idx_t, vw in enumerate(tok_words):
                    if vw == tw:
                        exact_spans.append(tok_spans[idx_t])
                    elif len(vw) == len(tw) + 1 and vw[0] in 'משהוכלב' and vw[1:] == tw:
                        prefix_spans.append(tok_spans[idx_t])
            else:
                for i in range(len(tok_words) - num_q_words + 1):
                    is_ex = True
                    is_pr = True
                    for j in range(num_q_words):
                        tw = q_words[j]
                        vw = tok_words[i + j]
                        if vw != tw:
                            is_ex = False
                            if not (len(vw) == len(tw) + 1 and vw[0] in 'משהוכלב' and vw[1:] == tw):
                                is_pr = False
                                break
                    if is_ex:
                        for j in range(num_q_words):
                            exact_spans.append(tok_spans[i + j])
                    elif is_pr:
                        for j in range(num_q_words):
                            prefix_spans.append(tok_spans[i + j])

            if not exact_spans and not prefix_spans:
                continue

            b_name = row['book']
            c_name = row['chapter']
            if b_name in torah_set and not str(c_name).startswith('דף'):
                cat = 'torah'
            elif b_name in tanakh_set and not str(c_name).startswith('דף'):
                cat = 'nach'
            elif b_name.startswith('רמב"ם ') or b_name.startswith('שולחן ערוך '):
                cat = 'halacha'
            elif str(c_name).startswith('דף') or b_name.startswith('ירושלמי '):
                cat = 'talmud'
            else:
                cat = 'mishnah_tosefta'

            weight = len(exact_spans) * 5 + len(prefix_spans)
            corpus_counts[cat] += 1
            book_freq[b_name] = book_freq.get(b_name, 0) + 1
            chapter_freq[(b_name, c_name)] = chapter_freq.get((b_name, c_name), 0) + 1

            row['_cat'] = cat
            row['_exact_count'] = len(exact_spans)
            row['_weight'] = weight
            row['_spans'] = exact_spans if exact_spans else prefix_spans
            row['_raw_txt'] = raw_txt
            valid_records.append(row)

        for row in valid_records:
            b_name = row['book']
            c_name = row['chapter']
            score = (1000 if row['_exact_count'] > 0 else 100)
            score += row['_weight'] * 20
            score += chapter_freq.get((b_name, c_name), 0) * 15
            score += min(book_freq.get(b_name, 0), 30) * 5
            if search_core in b_name:
                score += 800
            if not b_name.startswith('ירושלמי '):
                score += 50
            row['_score'] = score

        valid_records.sort(key=lambda x: x['_score'], reverse=True)

        def pick_top_sources(records_subset, limit=3):
            picked = []
            seen_ch = set()
            for r in records_subset:
                key = (r['book'], r['chapter'])
                if key not in seen_ch:
                    seen_ch.add(key)
                    picked.append({
                        'book': r['book'],
                        'chapter': r['chapter'],
                        'verse': r['verse'],
                        'ref': f"{r['book']} {r['chapter']}:{r['verse']}",
                        'text': extract_highlighted_snippet(r['_raw_txt'], r['_spans']),
                        'is_exact': r['_exact_count'] > 0,
                        'chapter_hits': chapter_freq.get(key, 1),
                        'book_hits': book_freq.get(r['book'], 1)
                    })
                    if len(picked) >= limit:
                        break
            return picked

        top_tanakh = pick_top_sources([r for r in valid_records if r['_cat'] in ('torah', 'nach')], limit=3)
        top_chazal = pick_top_sources([r for r in valid_records if r['_cat'] in ('talmud', 'mishnah_tosefta')], limit=3)
        top_halacha = pick_top_sources([r for r in valid_records if r['_cat'] == 'halacha'], limit=2)

        top_books_sorted = sorted(book_freq.items(), key=lambda x: x[1], reverse=True)[:5]
        dominant_books = [{'book': b, 'score': s} for b, s in top_books_sorted]

        gem_concepts = [c for c in TORAH_CORE_CONCEPTS if c != search_core and calculate_gematria(c) == q_gem]
        gem_tanakh_verses = []
        gem_word_verses = []

        if q_gem > 0:
            gem_v_qs = list(
                TorahText.objects.filter(book__in=TANAKH_NAMES, verse_gematria=q_gem)
                .exclude(chapter__startswith='דף')
                .values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')[:2]
            )
            for gv in gem_v_qs:
                gem_tanakh_verses.append({
                    'ref': f"{gv['book']} {gv['chapter']}:{gv['verse']}",
                    'text': format_divine_name(gv['text_with_nikkud'] or gv['clean_text'])
                })

            gem_w_qs = list(
                TorahText.objects.filter(book__in=TORAH_NAMES, words_gematria__contains=f",{q_gem},")
                .exclude(chapter__startswith='דף')
                .values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')[:25]
            )
            seen_gem_words = set()
            for gw in gem_w_qs:
                raw_t = gw.get('text_with_nikkud') or gw.get('clean_text') or ''
                toks = list(WORD_TOKEN_RE.finditer(raw_t))
                for tok in toks:
                    w_clean = NON_HEB_RE.sub('', tok.group(0))
                    if len(w_clean) >= 2 and w_clean != search_core and calculate_gematria(w_clean) == q_gem:
                        if w_clean not in gem_concepts and len(gem_concepts) < 6:
                            gem_concepts.append(w_clean)
                        if w_clean not in seen_gem_words and len(gem_word_verses) < 2:
                            seen_gem_words.add(w_clean)
                            gem_word_verses.append({
                                'word': w_clean,
                                'ref': f"{gw['book']} {gw['chapter']}:{gw['verse']}",
                                'text': extract_highlighted_snippet(raw_t, [tok.span()])
                            })

        rev_str = " ".join([reverse_heb_word(w) for w in q_words])
        rev_matches = []
        if rev_str and rev_str != search_core and len(q_words) == 1 and len(q_words[0]) >= 2:
            rev_qs = list(
                TorahText.objects.filter(book__in=TANAKH_NAMES, clean_text__icontains=rev_str)
                .exclude(chapter__startswith='דף')
                .values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')[:50]
            )
            for rm in rev_qs:
                raw_t = rm.get('text_with_nikkud') or rm.get('clean_text') or ''
                toks = list(WORD_TOKEN_RE.finditer(raw_t))
                hit_spans = [t.span() for t in toks if NON_HEB_RE.sub('', t.group(0)) == rev_str]
                if hit_spans:
                    rev_matches.append({
                        'word': rev_str,
                        'ref': f"{rm['book']} {rm['chapter']}:{rm['verse']}",
                        'text': extract_highlighted_snippet(raw_t, hit_spans)
                    })
                    if len(rev_matches) >= 2:
                        break

        rashei_matches = []
        sofei_matches = []
        els_matches = []

        if 2 <= len(q_norm) <= 6:
            torah_scan_pool = list(
                TorahText.objects.filter(book__in=TORAH_NAMES)
                .exclude(chapter__startswith='דף')
                .values('book', 'chapter', 'verse', 'clean_text', 'text_with_nikkud')[:600]
            )
            k_len = len(q_norm)
            for item in torah_scan_pool:
                raw_t = item.get('text_with_nikkud') or item.get('clean_text') or ''
                toks = list(WORD_TOKEN_RE.finditer(raw_t))
                t_words = []
                t_spans = []
                for t in toks:
                    wh = NON_HEB_RE.sub('', t.group(0))
                    if wh:
                        t_words.append(norm_heb(wh))
                        t_spans.append(t.span())

                if len(t_words) >= k_len:
                    if len(rashei_matches) < 2:
                        r_seq = "".join([w[0] for w in t_words])
                        pos_r = r_seq.find(q_norm)
                        if pos_r != -1:
                            spans_r = t_spans[pos_r:pos_r + k_len]
                            phrase_r = " ".join([NON_HEB_RE.sub('', raw_t[s:e]) for s, e in spans_r])
                            rashei_matches.append({
                                'ref': f"{item['book']} {item['chapter']}:{item['verse']}",
                                'phrase': phrase_r,
                                'text': extract_highlighted_snippet(raw_t, spans_r)
                            })
                    if len(sofei_matches) < 2:
                        s_seq = "".join([w[-1] for w in t_words])
                        pos_s = s_seq.find(q_norm)
                        if pos_s != -1:
                            spans_s = t_spans[pos_s:pos_s + k_len]
                            phrase_s = " ".join([NON_HEB_RE.sub('', raw_t[s:e]) for s, e in spans_s])
                            sofei_matches.append({
                                'ref': f"{item['book']} {item['chapter']}:{item['verse']}",
                                'phrase': phrase_s,
                                'text': extract_highlighted_snippet(raw_t, spans_s)
                            })

                if len(els_matches) < 2:
                    letters_only = NON_HEB_RE.sub('', item.get('clean_text') or '').translate(FINAL_TO_REGULAR)
                    n_l = len(letters_only)
                    if n_l >= k_len:
                        for p0 in range(n_l):
                            if letters_only[p0] != q_norm[0]:
                                continue
                            max_st = min(12, (n_l - 1 - p0) // (k_len - 1))
                            found_els = False
                            for st in range(2, max_st + 1):
                                if letters_only[p0 : p0 + k_len * st : st] == q_norm:
                                    target_positions = {p0 + idx * st for idx in range(k_len)}
                                    g_idx = [-1]
                                    def mark_els_char(c_m):
                                        g_idx[0] += 1
                                        cl = c_m.group(0)
                                        if g_idx[0] in target_positions:
                                            return f'<mark style="background-color: #fde047; color: #000; padding: 0 3px; border-radius: 3px; font-weight: bold; border-bottom: 2px solid #b8860b;">{cl}</mark>'
                                        return cl
                                    marked_verse = format_divine_name(HEB_LETTER_CLUSTER_RE.sub(mark_els_char, raw_t))
                                    els_matches.append({
                                        'ref': f"{item['book']} {item['chapter']}:{item['verse']}",
                                        'skip': st - 1,
                                        'text': marked_verse
                                    })
                                    found_els = True
                                    break
                            if found_els:
                                break
                if len(rashei_matches) >= 2 and len(sofei_matches) >= 2 and len(els_matches) >= 2:
                    break

        verified_articles = []
        try:
            for art in Article.objects.filter(is_published=True):
                if not getattr(art, 'slug', None):
                    continue
                t_str = art.title or ''
                c_str = re.sub(r'<[^>]+>', ' ', art.content or '')
                toks_t = [NON_HEB_RE.sub('', m.group(0)) for m in WORD_TOKEN_RE.finditer(t_str)]
                in_title = any(w in toks_t for w in q_words if len(w) >= 2)
                toks_c = [m for m in WORD_TOKEN_RE.finditer(c_str) if NON_HEB_RE.sub('', m.group(0)) in q_words]
                if in_title or len(toks_c) >= 5:
                    spans_c = [m.span() for m in toks_c]
                    verified_articles.append({
                        'title': t_str.strip(),
                        'url': reverse('articles:detail', args=[art.slug]),
                        'snippet': extract_highlighted_snippet(c_str, spans_c, max_len=240),
                        'score': (100 if in_title else 0) + len(toks_c),
                        'occurrences': len(toks_c)
                    })
            verified_articles.sort(key=lambda x: x['score'], reverse=True)
            verified_articles = verified_articles[:2]
        except Exception:
            verified_articles = []

        return {
            'query': raw_query,
            'search_core': search_core,
            'gematria': q_gem,
            'total_matches': sum(corpus_counts.values()),
            'corpus_counts': corpus_counts,
            'dominant_books': dominant_books,
            'top_tanakh': top_tanakh,
            'top_chazal': top_chazal,
            'top_halacha': top_halacha,
            'gem_concepts': gem_concepts,
            'gem_tanakh_verses': gem_tanakh_verses,
            'gem_word_verses': gem_word_verses,
            'rashei_matches': rashei_matches,
            'sofei_matches': sofei_matches,
            'els_matches': els_matches,
            'reversed_word': rev_str if rev_str != search_core else '',
            'rev_matches': rev_matches,
            'verified_articles': verified_articles
        }

    try:
        if mode == 'code_finder':
            verse_obj = None
            if book and chapter and verse:
                verse_obj = TorahText.objects.filter(book=book, chapter=chapter, verse=verse).first()
            elif query:
                clean_q = re.sub(r'[^א-ת\s]', '', query).strip()
                verse_obj = TorahText.objects.filter(clean_text__icontains=clean_q).first()

            if not verse_obj:
                return JsonResponse({'error': 'לא נמצא פסוק או מקור לניתוח.'}, status=404)

            raw_text = format_divine_name(verse_obj.text_with_nikkud or verse_obj.clean_text)
            toks_v = [NON_HEB_RE.sub('', m.group(0)) for m in WORD_TOKEN_RE.finditer(raw_text)]
            clean_words = [w for w in toks_v if len(w) >= 2]
            v_gem = verse_obj.verse_gematria or calculate_gematria(verse_obj.clean_text or '')

            equal_verses_qs = TorahText.objects.filter(book__in=TANAKH_NAMES, verse_gematria=v_gem).exclude(id=verse_obj.id).exclude(chapter__startswith='דף')[:4]
            equal_verses = [
                {
                    'ref': f"{ev.book} {ev.chapter}:{ev.verse}",
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

            summary_parts = [f"המקור ב{verse_obj.book} ({verse_obj.chapter}, {verse_obj.verse}) מחזיק {len(clean_words)} תיבות וערכו הגימטרי הכולל הוא {v_gem}."]
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
                'source_ref': f"{verse_obj.book} | {verse_obj.chapter} | {verse_obj.verse}",
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

        elif mode == 'concept_map':
            if not query:
                return JsonResponse({'error': 'יש להזין מושג למיפוי.'}, status=400)

            analysis = analyze_concept_deeply(query)
            q_gem = analysis['gematria']
            cc = analysis['corpus_counts']
            core = analysis['search_core']

            nodes = [
                {
                    'id': 'root',
                    'label': f"{core}\n(גימטריה: {q_gem})",
                    'group': 'center',
                    'snippet': (
                        f"<b>מושג המפתח: \"{core}\"</b> (גימטריה: <b>{q_gem}</b>) | "
                        f"נמצאו <b>{analysis['total_matches']}</b> מקורות במאגרי האתר "
                        f"(תורה: {cc['torah']}, נ\"ך: {cc['nach']}, משנה ותוספתא: {cc['mishnah_tosefta']}, תלמודים: {cc['talmud']}, הלכה: {cc['halacha']}). "
                        f"לחץ על כל אחת מהתיבות במפה לצפייה במקור המודגש."
                    ),
                    'url': ''
                }
            ]
            edges = []

            for idx, th in enumerate(analysis['top_tanakh']):
                nid = f"tanakh_{idx}"
                nodes.append({
                    'id': nid,
                    'label': f"📖 תנ\"ך\n{th['ref']}",
                    'group': 'tanakh',
                    'snippet': f"<b>מקור במקרא ({th['ref']}):</b><br>{th['text']}",
                    'url': ''
                })
                edges.append({'from': 'root', 'to': nid, 'label': 'הופעה במקרא'})

            for idx, ch in enumerate(analysis['top_chazal'][:2]):
                nid = f"chazal_{idx}"
                nodes.append({
                    'id': nid,
                    'label': f"🏛️ חז\"ל\n{ch['book']} ({ch['chapter']})",
                    'group': 'talmud',
                    'snippet': f"<b>מקור בדברי חז\"ל ({ch['book']} {ch['chapter']}, {ch['verse']}):</b><br>{ch['text']}",
                    'url': ''
                })
                edges.append({'from': 'root', 'to': nid, 'label': 'הופעה בחז"ל'})

            for idx, hh in enumerate(analysis['top_halacha'][:2]):
                nid = f"halacha_{idx}"
                nodes.append({
                    'id': nid,
                    'label': f"👑 הלכה\n{hh['book']} ({hh['chapter']})",
                    'group': 'halacha',
                    'snippet': f"<b>פסיקת הלכה ({hh['book']} {hh['chapter']}, {hh['verse']}):</b><br>{hh['text']}",
                    'url': ''
                })
                edges.append({'from': 'root', 'to': nid, 'label': 'פסיקת הלכה'})

            if analysis['gem_concepts'] or analysis['gem_word_verses'] or analysis['gem_tanakh_verses']:
                gem_parts = []
                if analysis['gem_concepts']:
                    gem_parts.append(f"<b>מילים ומושגים בתנ\"ך בעלי גימטריה זהה ({q_gem}):</b> {', '.join(analysis['gem_concepts'])}")
                for gwv in analysis['gem_word_verses']:
                    gem_parts.append(f"<b>מקור בתורה למילה שווה בגימטריה (\"{gwv['word']}\" = {q_gem}) — {gwv['ref']}:</b> {gwv['text']}")
                for gtv in analysis['gem_tanakh_verses']:
                    gem_parts.append(f"<b>פסוק שלם שערכו הגימטרי {q_gem} — {gtv['ref']}:</b> {gtv['text']}")
                nodes.append({
                    'id': 'gem_node',
                    'label': f"🔢 הקבלות גימטריה ({q_gem})\n{', '.join(analysis['gem_concepts'][:3]) or 'פסוקים מקבילים'}",
                    'group': 'gematria',
                    'snippet': "<br><br>".join(gem_parts),
                    'url': ''
                })
                edges.append({'from': 'root', 'to': 'gem_node', 'label': f'שווה בגימטריה ({q_gem})'})

            if analysis['rev_matches']:
                rv0 = analysis['rev_matches'][0]
                nodes.append({
                    'id': 'rev_node',
                    'label': f"🔄 היפוך אותיות: \"{rv0['word']}\"\n{rv0['ref']}",
                    'group': 'trends',
                    'snippet': f"<b>היפוך האותיות של \"{core}\" הוא \"{rv0['word']}\" (גימטריה: {q_gem}) — מופיע ב{rv0['ref']}:</b><br>{rv0['text']}",
                    'url': ''
                })
                edges.append({'from': 'root', 'to': 'rev_node', 'label': 'היפוך אותיות'})

            if analysis['rashei_matches'] or analysis['sofei_matches']:
                acr_parts = []
                for rm in analysis['rashei_matches']:
                    acr_parts.append(f"<b>ראשי תיבות (ר\"ת) של \"{core}\" ב{rm['ref']}:</b><br>{rm['text']}")
                for sm in analysis['sofei_matches']:
                    acr_parts.append(f"<b>סופי תיבות (ס\"ת) של \"{core}\" ב{sm['ref']}:</b><br>{sm['text']}")
                nodes.append({
                    'id': 'acr_node',
                    'label': f"🔠 ראשי וסופי תיבות\nבפסוקי התורה",
                    'group': 'trends',
                    'snippet': "<br><br>".join(acr_parts),
                    'url': ''
                })
                edges.append({'from': 'root', 'to': 'acr_node', 'label': 'ר"ת / ס"ת בתורה'})

            if analysis['els_matches']:
                el0 = analysis['els_matches'][0]
                nodes.append({
                    'id': 'els_node',
                    'label': f"⚡ דילוג אותיות ({el0['skip']})\n{el0['ref']}",
                    'group': 'gematria',
                    'snippet': f"<b>דילוג אותיות שווה במרווח {el0['skip']} של האותיות \"{core}\" ב{el0['ref']}:</b><br>{el0['text']}",
                    'url': ''
                })
                edges.append({'from': 'root', 'to': 'els_node', 'label': f"דילוג אותיות ({el0['skip']})"})

            for idx, art in enumerate(analysis['verified_articles']):
                nid = f"article_{idx}"
                nodes.append({
                    'id': nid,
                    'label': f"✍️ מאמר בספרייה\n{art['title'][:28]}",
                    'group': 'site_content',
                    'snippet': f"<b>מאמר באתר ספריית לייבוביץ ({art['title']}):</b><br>{art['snippet']}",
                    'url': art['url']
                })
                edges.append({'from': 'root', 'to': nid, 'label': 'מאמר רלוונטי באתר'})

            resp_payload = {
                'query': query,
                'gematria': q_gem,
                'nodes': nodes,
                'edges': edges
            }
            cache.set(cache_key, resp_payload, 3600 * 12)
            return JsonResponse(resp_payload, json_dumps_params={'ensure_ascii': False})

        elif mode == 'sermon_generator':
            if not query:
                return JsonResponse({'error': 'יש להזין נושא או מושג לניתוח.'}, status=400)

            analysis = analyze_concept_deeply(query)
            q_gem = analysis['gematria']
            cc = analysis['corpus_counts']
            core = analysis['search_core']

            html_sections = []

            dom_b = ", ".join([f"<b>{b['book']}</b> ({b['score']} מופעים)" for b in analysis['dominant_books'][:5]]) or "ללא מוקד בודד"
            html_sections.append(
                f"<div class='mb-4'>"
                f"<h6 class='fw-bold mb-2' style='color: #8c6239; border-bottom: 1px solid #e2d9c5; padding-bottom: 6px;'>א. ניתוח תפוצה ומוקדי הסוגיה במאגרי התורה</h6>"
                f"<div>בסריקת כלל מאגרי האתר עבור <b>\"{core}\"</b> אותרו <b>{analysis['total_matches']}</b> מקורות: "
                f"בתורה: <b>{cc['torah']}</b> | בנביאים וכתובים: <b>{cc['nach']}</b> | במשנה ובתוספתא: <b>{cc['mishnah_tosefta']}</b> | "
                f"בתלמוד הבבלי והירושלמי: <b>{cc['talmud']}</b> | ברמב\"ם ובשולחן ערוך: <b>{cc['halacha']}</b>.<br>"
                f"הספרים והמסכתות שבהם מתרכז עיקר הדיון במאגר: {dom_b}.</div>"
                f"</div>"
            )

            sources_html_list = []
            if analysis['top_tanakh']:
                for x in analysis['top_tanakh']:
                    sources_html_list.append(f"<li class='mb-2'><b>מקרא ({x['ref']}):</b> {x['text']}</li>")
            else:
                sources_html_list.append(f"<li class='mb-2 text-muted'>התיבה המדויקת \"{core}\" אינה מופיעה כתיבה עצמאית במקרא (ראה להלן הופעותיה בראשי/סופי תיבות, בדילוגים ובהיפוך אותיות).</li>")

            for x in analysis['top_chazal'][:2]:
                sources_html_list.append(f"<li class='mb-2'><b>חז\"ל ({x['book']} {x['chapter']}, {x['verse']}):</b> {x['text']}</li>")
            for x in analysis['top_halacha'][:2]:
                sources_html_list.append(f"<li class='mb-2'><b>הלכה ({x['book']} {x['chapter']}, {x['verse']}):</b> {x['text']}</li>")

            html_sections.append(
                f"<div class='mb-4'>"
                f"<h6 class='fw-bold mb-2' style='color: #8c6239; border-bottom: 1px solid #e2d9c5; padding-bottom: 6px;'>ב. מקורות היסוד במקרא, בחז\"ל ובהלכה (עם סימון ההופעה המדויקת)</h6>"
                f"<ul class='mb-0 ps-3'>{''.join(sources_html_list)}</ul>"
                f"</div>"
            )

            crypto_items = []
            crypto_items.append(f"<li class='mb-2'><b>ערך גימטרי מדויק:</b> המילה <b>\"{core}\"</b> עולה בגימטריה <b>{q_gem}</b>.")
            if analysis['gem_concepts']:
                crypto_items[-1] += f" מילים ומושגים בתנ\"ך בעלי ערך גימטרי זהה (<b>{q_gem}</b>): <b>{', '.join(analysis['gem_concepts'])}</b>."
            crypto_items[-1] += "</li>"

            for gwv in analysis['gem_word_verses']:
                crypto_items.append(f"<li class='mb-2'><b>הקבלה גימטרית בתורה (\"{gwv['word']}\" = {q_gem}) ב{gwv['ref']}:</b> {gwv['text']}</li>")
            for gtv in analysis['gem_tanakh_verses']:
                crypto_items.append(f"<li class='mb-2'><b>פסוק שלם במקרא שערכו הגימטרי {q_gem} ({gtv['ref']}):</b> {gtv['text']}</li>")
            for rv in analysis['rev_matches']:
                crypto_items.append(f"<li class='mb-2'><b>היפוך אותיות מדויק (\"{core}\" ⬅ \"{rv['word']}\", גימטריה {q_gem}) ב{rv['ref']}:</b> {rv['text']}</li>")
            for rm in analysis['rashei_matches']:
                crypto_items.append(f"<li class='mb-2'><b>ראשי תיבות (ר\"ת) של \"{core}\" בתורה ({rm['ref']}):</b> {rm['text']}</li>")
            for sm in analysis['sofei_matches']:
                crypto_items.append(f"<li class='mb-2'><b>סופי תיבות (ס\"ת) של \"{core}\" בתורה ({sm['ref']}):</b> {sm['text']}</li>")
            for el in analysis['els_matches']:
                crypto_items.append(f"<li class='mb-2'><b>דילוג אותיות שווה (ELS במרווח {el['skip']}) בתורה ({el['ref']}):</b> {el['text']}</li>")

            html_sections.append(
                f"<div class='mb-4'>"
                f"<h6 class='fw-bold mb-2' style='color: #8c6239; border-bottom: 1px solid #e2d9c5; padding-bottom: 6px;'>ג. הצלבת גימטריאות, היפוך אותיות, ראשי/סופי תיבות ודילוגים (נתוני אמת)</h6>"
                f"<ul class='mb-0 ps-3'>{''.join(crypto_items)}</ul>"
                f"</div>"
            )

            plain_summary_for_ai = (
                f"מושג: {core} (גימטריה: {q_gem}). "
                f"תפוצה: תורה {cc['torah']}, נ\"ך {cc['nach']}, חז\"ל {cc['mishnah_tosefta'] + cc['talmud']}, הלכה {cc['halacha']}. "
                f"מקורות תנ\"ך: {', '.join([x['ref'] for x in analysis['top_tanakh']]) or 'ללא'}. "
                f"מקורות חז\"ל והלכה: {', '.join([x['book'] + ' ' + str(x['chapter']) for x in (analysis['top_chazal'] + analysis['top_halacha'])[:3]])}. "
                f"מילים שוות בגימטריה ({q_gem}): {', '.join(analysis['gem_concepts'])}. "
                f"היפוך אותיות במקרא: {analysis['rev_matches'][0]['word'] + ' (' + analysis['rev_matches'][0]['ref'] + ')' if analysis['rev_matches'] else 'ללא'}. "
                f"ראשי תיבות בתורה: {analysis['rashei_matches'][0]['phrase'] + ' (' + analysis['rashei_matches'][0]['ref'] + ')' if analysis['rashei_matches'] else 'ללא'}."
            )

            ai_synthesis = call_gemini_fast(
                f"אתה חוקר תורני באתר 'ספריית לייבוביץ'. להלן נתוני אמת שנשלפו ממסד הנתונים על המושג '{core}':\n"
                f"{plain_summary_for_ai}\n"
                f"כתוב פסקה מסכמת אחת או שתיים (ללא כותרות וללא כוכביות) המחברת באופן ענייני ומדויק בין המקורות וההקבלות הגימטריות/לשוניות שעלו בנתונים אלו לרעיון תורני משותף. "
                f"אל תמציא שום נתון שלא מופיע כאן, וכתוב את שם ה' אך ורק כ-י-ה-ו-ה."
            )

            if not ai_synthesis:
                synth_parts = [f"בחינה משולבת של כלל הממצאים עבור \"{core}\" (גימטריה: {q_gem}) מצביעה על חוט שני המחבר בין הרבדים השונים במאגר:"]
                if analysis['top_tanakh']:
                    t_refs = ", ".join([x['ref'] for x in analysis['top_tanakh']])
                    synth_parts.append(f"במקרא מופיעה התיבה במפורש ב{t_refs}.")
                if analysis['top_chazal'] or analysis['top_halacha']:
                    c_refs = ", ".join([f"{x['book']} ({x['chapter']})" for x in (analysis['top_chazal'][:2] + analysis['top_halacha'][:1])])
                    synth_parts.append(f"בדברי חז\"ל ובהלכה מתבררים ההקשרים המעשיים והלשוניים ב{c_refs}.")
                if analysis['gem_concepts']:
                    synth_parts.append(f"במישור הגימטרי ({q_gem}), המושג מתקשר בערכו המדויק לתיבות המקראיות {', '.join(analysis['gem_concepts'][:4])}.")
                if analysis['rev_matches']:
                    rv0 = analysis['rev_matches'][0]
                    synth_parts.append(f"בנוסף, היפוך אותיות התיבה חושף את המילה המקראית \"{rv0['word']}\" ({rv0['ref']}), והצירוף מופיע ברמזי ראשי/סופי תיבות ודילוגי אותיות בפסוקי התורה המוצגים לעיל.")
                ai_synthesis = " ".join(synth_parts)

            html_sections.append(
                f"<div class='p-3 rounded-3' style='background-color: #fff8dc; border-right: 4px solid #d4af37;'>"
                f"<h6 class='fw-bold mb-2' style='color: #1e293b;'><i class='bi bi-layers-half ms-1' style='color: #b8860b;'></i>ד. חיבור הנתונים לרעיון משותף</h6>"
                f"<div style='line-height: 1.8;'>{ai_synthesis}</div>"
                f"</div>"
            )

            top_art = analysis['verified_articles'][0] if analysis['verified_articles'] else None

            resp_payload = {
                'topic': query,
                'gematria': q_gem,
                'total_matches': analysis['total_matches'],
                'corpus_counts': cc,
                'dominant_books': analysis['dominant_books'],
                'article_link': top_art['url'] if top_art else '',
                'article_title': top_art['title'] if top_art else '',
                'sermon_html': "".join(html_sections)
            }
            cache.set(cache_key, resp_payload, 3600 * 12)
            return JsonResponse(resp_payload, json_dumps_params={'ensure_ascii': False})

        return JsonResponse({'error': 'מצב פעולה לא חוקי.'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)

CORE_ARAMAIC_LEXICON = {
    'אבוקה': {'he': 'לפיד אש (המורכב ממספר פתילות)', 'dialect': 'בבלי, ירושלמי', 'cat': 'שם עצם', 'note': 'נר להבדלה מצוה מן המובחר באבוקה'},
    'אגב': {'he': 'על גב / דרך אגב / מכוח (קניין אגב קרקע)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'מטלטלין נקנין אגב מקרקעי'},
    'אגרא': {'he': 'שכר / רווח', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'לפום צערא אגרא (לפי הצער השכר)'},
    'אדהכי והכי': {'he': 'בינתיים / בתוך כך', 'dialect': 'בבלי', 'cat': 'ביטוי זמן', 'note': 'אדהכי והכי אתא ההוא גברא'},
    'אדעתא': {'he': 'על דעת / מתוך כוונה ש-', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'אדעתא דהכי לא נדר'},
    'אדרבה': {'he': 'להפך! (הסברא הפוכה מזו שאמרת)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'אדרבה, איפכא מסתברא'},
    'אודיתא': {'he': 'הודאת בעל דין / שטר הודאה', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'קניין אודיתא'},
    'אוקי': {'he': 'העמד! / העמיד (את המשנה במקרה מסוים)', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'אוקי ממונא בחזקת מרא קמא'},
    'אוקימתא': {'he': 'העמדת משנה או ברייתא במקרה מוגדר', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'שורש: קו"ם'},
    'אומדנא': {'he': 'אומדן דעת / הערכת כוונת האדם', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'אומדנא דמוכח'},
    'אולפן': {'he': 'לימוד / מסורת תלמודית', 'dialect': 'ירושלמי', 'cat': 'שם עצם', 'note': 'לא כן אולפן (לא כך לימודנו)'},
    'אורחא': {'he': 'דרך / מנהג רגיל', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'אורחא דמילתא (דרך הדבר)'},
    'אורייתא': {'he': 'תורה', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'אורייתא וקוב"ה וישראל חד הוא'},
    'אושפיזא': {'he': 'אורח / אכסניה / מארח', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'אושפיזין עילאין בסוכה'},
    'אזדו': {'he': 'הלכו לשיטתם', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'ואזדו לטעמייהו (והלכו לפי טעמם ושיטתם)'},
    'אזיל': {'he': 'הולך', 'dialect': 'בבלי, זוהר', 'cat': 'פועל', 'note': 'בתר רובא אזלינן (אחר הרוב אנו הולכים)'},
    'אטו': {'he': 'וכי? / האומנם? (מילת תמיהה)', 'dialect': 'בבלי', 'cat': 'מילת שאלה', 'note': 'אטו בכולי תלמודא'},
    'אי': {'he': 'אם / או', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת תנאי', 'note': 'אי הכי (אם כך), אי נמי (או גם)'},
    'איבעיא להו': {'he': 'נשאלה להם (לבני הישיבה שאלה הלכתית)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'פתיחה לספק הלכתי בגמרא'},
    'איגלאי מילתא': {'he': 'נתגלה הדבר למפרע', 'dialect': 'בבלי', 'cat': 'ביטוי תלמודי', 'note': 'איגלאי מילתא למפרע'},
    'איהו': {'he': 'הוא', 'dialect': 'בבלי, זוהר', 'cat': 'כינוי גוף', 'note': 'איהו ואיהי (הוא והיא)'},
    'איהי': {'he': 'היא', 'dialect': 'בבלי, זוהר', 'cat': 'כינוי גוף', 'note': 'שכיח מאוד בספר הזוהר'},
    'איכא': {'he': 'יש כאן (אית הכא)', 'dialect': 'בבלי', 'cat': 'מילת קיום', 'note': 'איכא בינייהו (יש הבדל ביניהם)'},
    'אימא': {'he': 'אמור / תאמר / אשער', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'אימא סיפא (אמור ועיין בסוף המשנה)'},
    'אינהו': {'he': 'הם', 'dialect': 'בבלי', 'cat': 'כינוי גוף', 'note': 'אינהו סברי (הם סוברים)'},
    'אינון': {'he': 'הם / אלו', 'dialect': 'ירושלמי, זוהר', 'cat': 'כינוי גוף', 'note': 'הני אינון (אלו הם)'},
    'איסורא': {'he': 'דבר אסור / דיני איסור והיתר (לעומת ממונא)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'ממונא מאיסורא לא ילפינן'},
    'איפכא': {'he': 'להפך / הפוך', 'dialect': 'בבלי', 'cat': 'תואר הפועל', 'note': 'איפכא מסתברא (ההפך הוא המסתבר)'},
    'איצטריך': {'he': 'הוצרך / היה הכרח לומר זאת', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'סלקא דעתך אמינא... קמ"ל ואיצטריך'},
    'אית': {'he': 'יש', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת קיום', 'note': 'אית ליה (יש לו / סובר כך)'},
    'איתא': {'he': 'ישנו / קיים / נכון הדבר', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת קיום', 'note': 'הפך מ"ליתא"'},
    'איתמר': {'he': 'נאמר (פתיחה למחלוקת אמוראים)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'איתמר: רב ושמואל דאמרי תרוייהו'},
    'איתתא': {'he': 'אישה', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'ברבים: נשי'},
    'אית תניי תני': {'he': 'יש תנאים השונים (חילופי גרסאות בברייתא)', 'dialect': 'ירושלמי', 'cat': 'מונח ירושלמי', 'note': 'מציג שתי מסורות תנאיות מנוגדות'},
    'אלא': {'he': 'אבל / אולם (פתיחה לקושיה או חזרה מהסבר קודם)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת קישור', 'note': 'אלא אמר רבא'},
    'אלמא': {'he': 'מכאן מוכח / הרי ש-', 'dialect': 'בבלי', 'cat': 'מונח הוכחה', 'note': 'אלמא קסבר (מכאן שהוא סובר)'},
    'אמאי': {'he': 'למה? / מדוע? / על שום מה?', 'dialect': 'בבלי', 'cat': 'מילת שאלה', 'note': 'מורכב מן א-מאי (על מה). למשל: אמאי קאמר הכי?'},
    'אמינא': {'he': 'אני אומר / הייתי אומר', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'הוה אמינא (הייתי אומר)'},
    'אמרי': {'he': 'אומרים (בני הישיבה)', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'אמרי במערבא (אומרים בארץ ישראל)'},
    'אנן': {'he': 'אנחנו / אנו', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'כינוי גוף', 'note': 'אנן סהדי (אנו עדים בדבר ברור)'},
    'אסמכתא': {'he': 'סמך בפסוק לדין דרבנן / התחייבות ממונית ללא גמירות דעת', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'אסמכתא בעלמא; אסמכתא לא קניא'},
    'אספקלריא': {'he': 'מראה / מחיצה מאירה (דרגת נבואה או הארה)', 'dialect': 'בבלי, זוהר', 'cat': 'מושג יסוד', 'note': 'אספקלריא המאירה'},
    'אפקעתא': {'he': 'הפקעה (הפקעת קידושין או הפקעת הלוואה)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'אפקעתא דמלכא'},
    'אפילו': {'he': 'אפילו / גם אם', 'dialect': 'בבלי, ירושלמי', 'cat': 'מילת קישור', 'note': 'אפילו תימא (אפילו אם תאמר)'},
    'ארעא': {'he': 'ארץ / אדמה / קרקע', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'ארעא דישראל (ארץ ישראל)'},
    'אתא': {'he': 'בא', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'פועל', 'note': 'אתא לקמיה (בא לפניו לדין)'},
    'אתמר': {'he': 'נאמר (כתיב חסר של איתמר)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'פתיחה למחלוקת אמוראים'},
    'בבא': {'he': 'שער / פרק / חלק ממשנה', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'בבא קמא (השער הראשון), רישא בבבא קמייתא'},
    'בגין': {'he': 'בשביל / למען / מפני', 'dialect': 'זוהר, ירושלמי', 'cat': 'מילת יחס', 'note': 'בגין כך (משום כך), בגין ד- (מפני ש-)'},
    'בגין מה': {'he': 'מפני מה? / מדוע? (מקביל ל"אמאי")', 'dialect': 'זוהר', 'cat': 'מילת שאלה', 'note': 'לשון שאלה שכיחה בספר הזוהר'},
    'בגיני': {'he': 'בשבילי / בגללי', 'dialect': 'ירושלמי, בבלי', 'cat': 'מילת יחס', 'note': 'בגינך = בשבילך'},
    'בדיעבד': {'he': 'לאחר מעשה (לעומת לכתחילה)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'לכתחילה לא, בדיעבד שפיר דמי'},
    'בוצינא': {'he': 'נר / מאור / כינוי לחכם גדול', 'dialect': 'בבלי, זוהר', 'cat': 'מושג יסוד', 'note': 'בוצינא קדישא (המאור הקדוש - רשב"י), בוצינא דקרדינותא'},
    'בי': {'he': 'בית / בית מדרש', 'dialect': 'בבלי', 'cat': 'שם עצם', 'note': 'בי מדרשא, תנא דבי רבי ישמעאל'},
    'בריך': {'he': 'ברוך', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'תואר', 'note': 'קודשא בריך הוא, בריך רחמנא'},
    'ברי': {'he': 'ברור / ודאי (טענת ברי מול טענת שמא)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'ברי ושמא — ברי עדיף'},
    'ברייתא': {'he': 'משנה חיצונית (שלא נכנסה למשנת רבי יהודה הנשיא)', 'dialect': 'בבלי, ירושלמי', 'cat': 'מונח תנאי', 'note': 'מתניתא ברייתא'},
    'בר נש': {'he': 'בן אדם / איש', 'dialect': 'ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'נפוץ מאוד בירושלמי ובזוהר (בבבלי: איניש / בר אינש)'},
    'בשלמא': {'he': 'ניחא / מובן הדבר (לפי שיטת...)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'בשלמא למאן דאמר... אלא למאן דאמר...'},
    'בתר': {'he': 'אחרי / בעקבות', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת יחס', 'note': 'בתר רובא אזלינן (אחרי הרוב הולכים)'},
    'בתרא': {'he': 'אחרון', 'dialect': 'בבלי, זוהר', 'cat': 'תואר', 'note': 'בבא בתרא, הלכתא כבתראי'},
    'גברא': {'he': 'איש / אדם (ובהלכה: האדם הפועל לעומת ה"חפצא")', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'איסור גברא ואיסור חפצא; גברא רבא'},
    'גוונא': {'he': 'צבע / אופן / צורה', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'כהאי גוונא (כאופן הזה)'},
    'גופא': {'he': 'הגוף עצמו (חזרה לדון במקור שהוזכר קודם בדרך אגב)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'פתיחה לדיון במקור שהובא כראיה'},
    'גושפנקא': {'he': 'חותם / טבעת חתימה', 'dialect': 'בבלי', 'cat': 'שם עצם', 'note': 'גושפנקא דמלכא'},
    'גירסא': {'he': 'נוסח הלימוד / שינון בפה', 'dialect': 'בבלי', 'cat': 'שם עצם', 'note': 'גירסא דינקותא (לימוד הילדות)'},
    'גמיר': {'he': 'למד במסורת מרבו', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'גמירנא (למדתי במסורת)'},
    'גרמיה': {'he': 'עצמו (מקביל ל"נפשיה" בבבלי)', 'dialect': 'ירושלמי, זוהר', 'cat': 'כינוי גוף', 'note': 'לגרמיה (לעצמו)'},
    'דא': {'he': 'זה / זו (מקביל ל"האי" בבבלי)', 'dialect': 'זוהר, ירושלמי', 'cat': 'מילת רמז', 'note': 'דא הוא דכתיב (זהו שכתוב)'},
    'דאורייתא': {'he': 'מן התורה (לעומת דרבנן)', 'dialect': 'בבלי, זוהר', 'cat': 'מונח הלכתי', 'note': 'ספק דאורייתא לחומרא'},
    'דוכתא': {'he': 'מקום', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'בכל דוכתא (בכל מקום)'},
    'דיוקנא': {'he': 'דמות / צורה / דיוקן', 'dialect': 'זוהר, בבלי', 'cat': 'שם עצם', 'note': 'דיוקנא קדישא'},
    'דילמא': {'he': 'שמא / אולי', 'dialect': 'בבלי', 'cat': 'מילת ספק', 'note': 'ממאי? דילמא שאני התם'},
    'דינא': {'he': 'דין / משפט / הלכה / מידת הדין', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'דינא דמלכותא דינא'},
    'דלמא': {'he': 'שמא / אולי', 'dialect': 'בבלי', 'cat': 'מילת ספק', 'note': 'דלמא לא היא'},
    'דמי': {'he': 'דומה / נחשב / שווי כספי', 'dialect': 'בבלי', 'cat': 'פועל / שם', 'note': 'היכי דמי (איך מדובר / למה הדבר דומה)'},
    'דרבנן': {'he': 'מדברי חכמים (לעומת דאורייתא)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'ספק דרבנן לקולא'},
    'דרגא': {'he': 'מדרגה / שלב רוחני', 'dialect': 'זוהר, בבלי', 'cat': 'שם עצם', 'note': 'תלת דרגין אינון מתקשרן דא בדא'},
    'דרדקי': {'he': 'ילדים קטנים הלומדים תורה', 'dialect': 'בבלי', 'cat': 'שם עצם', 'note': 'מקרי דרדקי (מלמד תינוקות)'},
    'דתימא': {'he': 'שתאמר', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'מהו דתימא (מה היית אומר)'},
    'הא': {'he': 'הרי / זו / זאת', 'dialect': 'בבלי, זוהר', 'cat': 'מילת רמז', 'note': 'הא גופא קשיא (הרי דבר זה עצמו קשה)'},
    'האי': {'he': 'זה / זו', 'dialect': 'בבלי, זוהר', 'cat': 'מילת רמז', 'note': 'האי מאן דאמר (זה מי שאומר)'},
    'הדא': {'he': 'זו / זאת (מקביל ל"הא" או "האי" בבבלי)', 'dialect': 'ירושלמי', 'cat': 'מילת רמז', 'note': 'הדא דתימר (זאת שאתה אומר)'},
    'הדא אמרה': {'he': 'זאת אומרת / מכאן מוכח (מקביל ל"שמע מינה")', 'dialect': 'ירושלמי', 'cat': 'מונח ירושלמי', 'note': 'מונח הכרעה מרכזי בתלמוד הירושלמי'},
    'הדר': {'he': 'חזר / שב', 'dialect': 'בבלי, זוהר', 'cat': 'פועל', 'note': 'הדר ביה (חזר בו מדבריו)'},
    'הדין': {'he': 'זה (מקביל ל"האי" בבבלי)', 'dialect': 'ירושלמי', 'cat': 'מילת רמז', 'note': 'הדין קרייא (הפסוק הזה)'},
    'הוה': {'he': 'היה', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'פועל', 'note': 'הוה קאי (היה עומד)'},
    'הוה אמינא': {'he': 'הייתי אומר (סברא ראשונית שנדחית במסקנה)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: הו"א'},
    'הורמנותא': {'he': 'רשות / צו המלך / רצון עליון', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'בריש הורמנותא דמלכא (בזוהר בראשית)'},
    'היכא': {'he': 'איפה / היכן / במקום ש-', 'dialect': 'בבלי', 'cat': 'מילת שאלה', 'note': 'תנא היכא קאי (היכן עומד התנא)'},
    'היכי': {'he': 'איך / כיצד', 'dialect': 'בבלי', 'cat': 'מילת שאלה', 'note': 'היכי דמי (כיצד מדובר?)'},
    'היכי דמי': {'he': 'איך מדובר? / באיזה מקרה מדובר?', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: ה"ד'},
    'הכא': {'he': 'כאן / במקרה זה', 'dialect': 'בבלי, זוהר', 'cat': 'תואר הפועל', 'note': 'הכא במאי עסקינן (כאן במה אנו עוסקים)'},
    'הכי': {'he': 'כך / כן', 'dialect': 'בבלי', 'cat': 'תואר הפועל', 'note': 'הכי קאמר (כך הוא אומר)'},
    'הכי נמי': {'he': 'כך גם כן / אכן כן הוא', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: ה"נ'},
    'הכן': {'he': 'כך / כן / כאן', 'dialect': 'ירושלמי', 'cat': 'תואר הפועל', 'note': 'אופייני לארמית גלילית בתלמוד הירושלמי'},
    'הלכתא': {'he': 'ההלכה הפסוקה', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'והלכתא כוותיה (וההלכה כמותו)'},
    'הני': {'he': 'אלו', 'dialect': 'בבלי, זוהר', 'cat': 'מילת רמז', 'note': 'הני מילי (דברים אלו)'},
    'השתא': {'he': 'עכשיו / כעת / הרי במצב זה', 'dialect': 'בבלי, זוהר', 'cat': 'תואר הפועל', 'note': 'השתא דאתיא להכי'},
    'התם': {'he': 'שם / במקרה ההוא', 'dialect': 'בבלי, זוהר', 'cat': 'תואר הפועל', 'note': 'שאני התם (שונה שם)'},
    'ודאי': {'he': 'דבר ברור ומוחלט (לעומת ספק)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מונח הלכתי', 'note': 'אין ספק מוציא מידי ודאי'},
    'ויהיב': {'he': 'ונותן / ונתן', 'dialect': 'בבלי, זוהר', 'cat': 'פועל', 'note': 'שורש: יה"ב (לתת)'},
    'זוזא': {'he': 'זוז (מטבע כסף תלמודי, רבע שקל)', 'dialect': 'בבלי', 'cat': 'שם עצם', 'note': 'ברבים: זוזי (מאה זוזי = מנה)'},
    'זיל': {'he': 'לך! (ציווי משורש אז"ל)', 'dialect': 'בבלי, זוהר', 'cat': 'פועל (ציווי)', 'note': 'זיל גמור (לך ולמד)'},
    'זימנא': {'he': 'פעם / זמן', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'חדא זימנא (פעם אחת), זימנין (לפעמים)'},
    'זעיר אנפין': {'he': 'קצר אפיים / מידת התפארת והרחמים בקבלה', 'dialect': 'זוהר', 'cat': 'מושג קבלי', 'note': 'ראשי תיבות: ז"א'},
    'חברייא': {'he': 'החברים / תלמידי החכמים בחבורה', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'בזוהר: חבורתו הקדושה של רשב"י'},
    'חד': {'he': 'אחד (בנקבה: חדא)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם מספר', 'note': 'חד אמר... וחד אמר...'},
    'חזי': {'he': 'רואה / ראוי', 'dialect': 'בבלי, זוהר', 'cat': 'פועל', 'note': 'תא חזי (בוא וראה), חזי לאצטרופי'},
    'חזקה': {'he': 'הנחה משפטית מבוססת / מעשה קניין בקרקע', 'dialect': 'בבלי, ירושלמי', 'cat': 'מונח הלכתי', 'note': 'חזקה דמעיקרא, חזקת מרא קמא'},
    'חמי': {'he': 'רואה (מקביל ל"חזי" בבבלי)', 'dialect': 'ירושלמי, זוהר', 'cat': 'פועל', 'note': 'מה אנן חמיי (מה אנו רואים)'},
    'חפצא': {'he': 'החפץ / הדבר עצמו (לעומת ה"גברא" - האדם)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'איסור חפצא ואיסור גברא'},
    'חקל תפוחין קדישין': {'he': 'שדה התפוחים הקדושים (כינוי לשכינה ולגן עדן)', 'dialect': 'זוהר', 'cat': 'מושג קבלי', 'note': 'מונח יסוד בספר הזוהר ובכתבי האר"י'},
    'טבא': {'he': 'טוב', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'תואר', 'note': 'לטבא (לטובה), יומא טבא (יום טוב)'},
    'טליא': {'he': 'נער / ילד / טלה', 'dialect': 'ירושלמי, בבלי, זוהר', 'cat': 'שם עצם', 'note': 'בנקבה: טליתא'},
    'טעמא': {'he': 'טעם / סיבה / נימוק הלכתי', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'מאי טעמא (מה הטעם)'},
    'טסקא': {'he': 'מס קרקע שנתי למלכות', 'dialect': 'בבלי', 'cat': 'שם עצם', 'note': 'יהיב טסקא (משלם את מס הקרקע)'},
    'יהיב': {'he': 'נותן / נתן', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'פועל', 'note': 'מאן דיהיב חיי יהיב מזוני'},
    'יומא': {'he': 'יום', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'יומא דכיפורי, כל יומא'},
    'יליף': {'he': 'לומד / גוזר לימוד מן הכתוב', 'dialect': 'בבלי, ירושלמי', 'cat': 'פועל', 'note': 'גמר וילף גזירה שוה'},
    'ינוקא': {'he': 'ילד / תינוק', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'מדור ה"ינוקא" בספר הזוהר'},
    'יקרא': {'he': 'כבוד / תפארת', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'יקרא דאורייתא (כבוד התורה)'},
    'יתיה': {'he': 'אותו', 'dialect': 'ירושלמי, זוהר', 'cat': 'מילת יחס', 'note': 'חמא יתיה (ראה אותו)'},
    'כד': {'he': 'כאשר / כש-', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת זמן', 'note': 'כד הוה (כאשר היה)'},
    'כדון': {'he': 'כעת / עכשיו / הרי זה', 'dialect': 'ירושלמי', 'cat': 'תואר הפועל', 'note': 'עד כדון (עד כאן)'},
    'כוותיה': {'he': 'כמותו / כשיטתו', 'dialect': 'בבלי, ירושלמי', 'cat': 'מילת יחס', 'note': 'הלכתא כוותיה דרב'},
    'כולי עלמא': {'he': 'כל העולם (כל החכמים החולקים בסוגיה מסכימים ש-)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: כו"ע לא פליגי'},
    'כמאן': {'he': 'כמו מי? / כשיטת מי?', 'dialect': 'בבלי', 'cat': 'מילת שאלה', 'note': 'כמאן אזלא הא דאמר...'},
    'כתיב': {'he': 'כתוב (במקרא)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'פועל', 'note': 'דכתיב (שכתוב בפסוק)'},
    'לאו': {'he': 'לא / מצוות לא תעשה', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת שלילה / מונח', 'note': 'לאו שאין בו מעשה'},
    'לבסוף': {'he': 'בסוף / למסקנה', 'dialect': 'בבלי', 'cat': 'תואר הפועל', 'note': 'מעיקרא... ולבסוף...'},
    'לגמרי': {'he': 'לחלוטין / באופן מוחלט', 'dialect': 'בבלי', 'cat': 'תואר הפועל', 'note': 'פטר לגמרי'},
    'להו': {'he': 'להם', 'dialect': 'בבלי', 'cat': 'מילת יחס', 'note': 'איבעיא להו (נשאלה להם)'},
    'לחוד': {'he': 'בנפרד / לבד', 'dialect': 'בבלי, זוהר', 'cat': 'תואר הפועל', 'note': 'הא לחוד והא לחוד'},
    'ליכא': {'he': 'אין כאן (לית הכא)', 'dialect': 'בבלי', 'cat': 'מילת שלילה', 'note': 'תו ליכא (אין יותר)'},
    'לימא': {'he': 'האם נאמר? / יאמר', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'לימא כתנאי (האם נאמר שמחלוקתם כמחלוקת תנאים?)'},
    'לישנא': {'he': 'לשון / ניסוח', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'לישנא אחרינא (לשון אחרת - רש"י)'},
    'לית': {'he': 'אין (לא אית)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת שלילה', 'note': 'לית ליה (אין לו / אינו סובר כך)'},
    'ליתא': {'he': 'איננו / אינו קיים / הדבר נדחה', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת שלילה', 'note': 'ליתא להא שמעתתא'},
    'לכתחילה': {'he': 'מראש / כמצווה הראויה (לעומת בדיעבד)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'לכתחילה ובדיעבד'},
    'למה': {'he': 'מדוע? / לאיזה צורך? (בירושלמי משמש כ"אמאי")', 'dialect': 'ירושלמי', 'cat': 'מילת שאלה', 'note': 'למה לי'},
    'למפרע': {'he': 'לאחור / משעה ראשונה רטרואקטיבית', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'מכאן ולהבא או למפרע'},
    'מאי': {'he': 'מה / מהו', 'dialect': 'בבלי', 'cat': 'מילת שאלה', 'note': 'מאי קא משמע לן (מה משמיע לנו)'},
    'מאי טעמא': {'he': 'מה הטעם? / מדוע?', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: מ"ט'},
    'מאי שנא': {'he': 'מה שונה? / במה נבדל דין זה?', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'מאי שנא רישא ומאי שנא סיפא'},
    'מאן': {'he': 'מי', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מילת שאלה', 'note': 'מאן תנא (מי הוא התנא)'},
    'מגו': {'he': 'מתוך (טענת "מגו": נאמן בטענתו כי יכול היה לטעון טענה טובה ממנה)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'מגו דזכי לנפשיה זכי נמי לחבריה'},
    'מהו': {'he': 'מה הדין? (מקביל ל"מאי" או "איבעיא להו")', 'dialect': 'ירושלמי, בבלי', 'cat': 'מילת שאלה', 'note': 'פתיחת שאלה הלכתית'},
    'מהו דתימא': {'he': 'מה היית אומר (לולא החידוש שבא להשמיענו)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: מהו"ד... קמ"ל'},
    'מוחזק': {'he': 'מי שהממון נמצא תחת ידו (לעומת המוציא מחברו)', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'המוציא מחברו עליו הראיה'},
    'מוקי': {'he': 'מעמיד (את המשנה או הברייתא במקרה מסוים)', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'במאי מוקי לה (במה הוא מעמיד אותה)'},
    'מזלא': {'he': 'מזל / שפע רוחני עליון', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'אין מזל לישראל; מזלא קדישא'},
    'מיא': {'he': 'מים', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'מיא דאורייתא'},
    'מיגו': {'he': 'מתוך (כתיב מלא של "מגו")', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'מיגו להוציא לא אמרינן'},
    'מילי': {'he': 'דברים / מילים', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם (רבים)', 'note': 'הני מילי (דברים אלו), מנא הני מילי'},
    'מילתא': {'he': 'דבר / מילה / עניין / הלכה', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'מילתא דפשיטא (דבר פשוט)'},
    'מינה': {'he': 'ממנה / ממנו', 'dialect': 'בבלי, זוהר', 'cat': 'מילת יחס', 'note': 'נפקא מינה, שמע מינה'},
    'ממאי': {'he': 'ממה? / מניין לך זאת?', 'dialect': 'בבלי', 'cat': 'מילת שאלה', 'note': 'ממאי? דלמא לא היא'},
    'ממונא': {'he': 'ממון / כסף / דיני ממונות', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'ממונא לקולא'},
    'מנא הני מילי': {'he': 'מניין הדברים הללו? (מה המקור לכך מן הפסוק)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: מנה"מ'},
    'מנלן': {'he': 'מניין לנו? (מה המקור לכך)', 'dialect': 'בבלי', 'cat': 'מילת שאלה', 'note': 'קיצור של מנא לן'},
    'מסתברא': {'he': 'מסתבר / מתקבל על הדעת', 'dialect': 'בבלי, ירושלמי', 'cat': 'מונח הכרעה', 'note': 'וכן מסתברא'},
    'מעיקרא': {'he': 'מתחילה / בהתחלה / מעיקר הדין', 'dialect': 'בבלי', 'cat': 'תואר הפועל', 'note': 'מעיקרא מאי סבר ולבסוף מאי סבר'},
    'מציעתא': {'he': 'החלק האמצעי של המשנה (אמצע)', 'dialect': 'בבלי', 'cat': 'מונח מבנה', 'note': 'בבא מציעא = השער האמצעי'},
    'מרא קמא': {'he': 'הבעלים הראשון של הנכס', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'אוקי ממונא בחזקת מרא קמא'},
    'מתניתא': {'he': 'משנה או ברייתא', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מונח תנאי', 'note': 'מתניתין = משנתנו'},
    'נהורא': {'he': 'אור', 'dialect': 'זוהר, בבלי', 'cat': 'שם עצם', 'note': 'נהורא עילאה (אור עליון)'},
    'נורא': {'he': 'אש', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'נורא דאורייתא'},
    'ניחא': {'he': 'נוח / מובן היטב (מקביל ל"בשלמא" בבבלי)', 'dialect': 'ירושלמי, בבלי, זוהר', 'cat': 'מונח שקלא וטריא', 'note': 'ניחא ליה (נוח לו)'},
    'נימא': {'he': 'נאמר / האם נאמר', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'נימא תיהוי תיובתא'},
    'נמי': {'he': 'גם / גם כן', 'dialect': 'בבלי', 'cat': 'מילת ריבוי', 'note': 'אי נמי (או גם), הכי נמי (כך גם)'},
    'נפקא': {'he': 'יוצא / יוצאת', 'dialect': 'בבלי, זוהר', 'cat': 'פועל', 'note': 'נפקא מינה (יוצא ממנה)'},
    'נפקא מינה': {'he': 'יוצא ממנה (ההבדל ההלכתי המעשי בין שתי שיטות)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: נ"מ; למאי נפקא מינה?'},
    'נפשיה': {'he': 'עצמו', 'dialect': 'בבלי', 'cat': 'כינוי גוף', 'note': 'קם דינא לנפשיה'},
    'סבא': {'he': 'זקן / חכם ישיש', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'פרשת "סבא דמשפטים" בזוהר'},
    'סבירא ליה': {'he': 'סבור הוא / דעתו ההלכתית היא', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: ס"ל'},
    'סבר': {'he': 'סובר / חושב (קסבר = קא סבר)', 'dialect': 'בבלי, ירושלמי', 'cat': 'פועל', 'note': 'מר סבר... ומר סבר...'},
    'סברא': {'he': 'היגיון הלכתי / נימוק שכלי (לעומת קרא או גמרא)', 'dialect': 'בבלי', 'cat': 'מונח יסוד', 'note': 'למה לי קרא? סברא היא!'},
    'סהדי': {'he': 'עדים (ביחיד: סהדא)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'אנן סהדי; סהדי שקרי'},
    'סוגיא': {'he': 'מהלך הדיון התלמודי / הלכה רווחת', 'dialect': 'בבלי', 'cat': 'מונח יסוד', 'note': 'סוגיא דשמעתא'},
    'סיהרא': {'he': 'ירח / לבנה', 'dialect': 'זוהר, בבלי', 'cat': 'שם עצם', 'note': 'אשלמותא דסיהרא'},
    'סיפא': {'he': 'החלק האחרון של המשנה או הברייתא (סוף)', 'dialect': 'בבלי', 'cat': 'מונח מבנה', 'note': 'רישא וסיפא'},
    'סטרא אחרא': {'he': 'הצד האחר (כוחות הטומאה והקליפה)', 'dialect': 'זוהר', 'cat': 'מושג בזוהר', 'note': 'ראשי תיבות: ס"א'},
    'סלקא דעתך': {'he': 'יעלה על דעתך (סלקא דעתך אמינא = סד"א)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: ס"ד'},
    'ספיקא': {'he': 'ספק הלכתי או מציאותי', 'dialect': 'בבלי, זוהר', 'cat': 'מונח הלכתי', 'note': 'ספק ספיקא, ספיקא דאורייתא'},
    'עביד': {'he': 'עושה / עשוי', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'פועל', 'note': 'עביד איניש דגזים ולא עביד'},
    'עילאה': {'he': 'עליון', 'dialect': 'זוהר, בבלי', 'cat': 'תואר', 'note': 'נהורא עילאה, עלמא עילאה (הפך מ"תתאה")'},
    'עלמא': {'he': 'עולם', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'עלמא דאתי (העולם הבא), כולי עלמא'},
    'עסקינן': {'he': 'אנו עוסקים', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'הכא במאי עסקינן'},
    'עתיקא קדישא': {'he': 'העתיק הקדוש (הדרגה העליונה בכתר)', 'dialect': 'זוהר', 'cat': 'מושג קבלי', 'note': 'עתיק יומין'},
    'פירכא': {'he': 'קושיה / הפרכה של היקש או קל וחומר', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'מה להצד השווה שבהן... איכא למיפרך'},
    'פיקודא': {'he': 'מצווה / ציווי התורה', 'dialect': 'זוהר', 'cat': 'מושג יסוד בזוהר', 'note': 'ברבים: פיקודין דאורייתא'},
    'פליגי': {'he': 'חולקים (שרויים במחלוקת)', 'dialect': 'בבלי, ירושלמי', 'cat': 'פועל', 'note': 'בהא קמיפלגי (בזה הם חולקים)'},
    'פלוגתא': {'he': 'מחלוקת תנאים או אמוראים', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'פלוגתא דרבי מאיר ורבנן'},
    'פשיטא': {'he': 'פשוט וברור! (מדוע הוצרך התנא או האמורא לומר זאת?)', 'dialect': 'בבלי, ירושלמי', 'cat': 'מונח שקלא וטריא', 'note': 'פשיטא! מהו דתימא... קמ"ל'},
    'צורבא מרבנן': {'he': 'תלמיד חכם צעיר וחריף', 'dialect': 'בבלי', 'cat': 'ביטוי תלמודי', 'note': 'האי צורבא מרבנן דרתח אורייתא היא דקא מרתחא ליה'},
    'צורכה': {'he': 'צריכה (הסוגיה או הברייתא צריכה ביאור)', 'dialect': 'ירושלמי', 'cat': 'מונח ירושלמי', 'note': 'מקביל ל"צריכא" בבבלי'},
    'צלותא': {'he': 'תפילה', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'צלותא דעניא'},
    'צריכא': {'he': 'צריך! (הסבר מדוע נצרכו כל הדוגמאות במשנה או בפסוק)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'וצריכא: דאי אשמועינן...'},
    'קא': {'he': 'עומד ו... (מילית המציינת הווה מתמשך, מקור מן "קאי")', 'dialect': 'בבלי', 'cat': 'מילית פועל', 'note': 'קא אמינא (אני אומר כעת)'},
    'קאי': {'he': 'עומד / נמצא / נסוב על (משורש קו"ם)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'פועל יסוד', 'note': 'תנא היכא קאי (היכן עומד התנא בברכות ב.), קושטא קאי'},
    'קאימנא': {'he': 'אני עומד (משורש קו"ם)', 'dialect': 'בבלי, זוהר', 'cat': 'פועל', 'note': 'גוף ראשון של "קאי"'},
    'קאמר': {'he': 'אומר (קא אמר)', 'dialect': 'בבלי', 'cat': 'פועל', 'note': 'מאי קאמר (מה הוא אומר)'},
    'קודשא בריך הוא': {'he': 'הקדוש ברוך הוא (הקב"ה)', 'dialect': 'זוהר, בבלי', 'cat': 'כינוי קודש', 'note': 'ראשי תיבות: קוב"ה'},
    'קומי': {'he': 'לפני (מקביל ל"קמיה" בבבלי)', 'dialect': 'ירושלמי', 'cat': 'מילת יחס', 'note': 'תני קומי רבי יוחנן (שנה לפני רבי יוחנן)'},
    'קושטא': {'he': 'אמת', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'קושטא קאי (האמת עומדת ועדולם קיימת)'},
    'קיימא': {'he': 'עומדת / קיימת (צורת נקבה של "קאי", משורש קו"ם)', 'dialect': 'בבלי, זוהר', 'cat': 'פועל', 'note': 'כל העומד ליזרק כזרוק דמי; קיימא לן'},
    'קיימא לן': {'he': 'עומד לנו / מוחזק ופשוט בידינו להלכה', 'dialect': 'בבלי', 'cat': 'מונח הלכתי', 'note': 'ראשי תיבות: קיי"ל / קי"ל'},
    'קיימי': {'he': 'עומדים (צורת רבים של "קאי")', 'dialect': 'בבלי, זוהר', 'cat': 'פועל', 'note': 'הנך דקיימי התם'},
    'קיימין': {'he': 'עומדים / עוסקים (מקביל ל"עסקינן" בבבלי, ריבוי של "קאי")', 'dialect': 'ירושלמי, זוהר', 'cat': 'פועל', 'note': 'הכן אנן קיימין (במה אנו עוסקים)'},
    'קם': {'he': 'עמד / קם (זמן עבר של "קאי", משורש קו"ם)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'פועל', 'note': 'קם דינא (עמד הדין)'},
    'קמא': {'he': 'ראשון / קדמון', 'dialect': 'בבלי, זוהר', 'cat': 'תואר', 'note': 'תנא קמא (התנא הראשון), בבא קמא'},
    'קמיה': {'he': 'לפניו', 'dialect': 'בבלי, זוהר', 'cat': 'מילת יחס', 'note': 'אתא לקמיה דרבא (בא לפני רבא)'},
    'קמ"ל': {'he': 'קא משמע לן — משמיע לנו / בא ללמדנו חידוש', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'חידוש שהתנא או האמורא משמיע'},
    'קא משמע לן': {'he': 'משמיע לנו / מלמדנו חידוש', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: קמ"ל'},
    'קרא': {'he': 'פסוק במקרא', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'מאי קרא? (מהו הפסוק המוכיח זאת)'},
    'קשיא': {'he': 'קשה (קושיה שנותרה בדוחק, קלה מ"תיובתא")', 'dialect': 'בבלי, ירושלמי', 'cat': 'מונח שקלא וטריא', 'note': 'קשיא דרב אדרב'},
    'קתני': {'he': 'שונה התנא במשנה או בברייתא (קא תני)', 'dialect': 'בבלי', 'cat': 'פועל תנאי', 'note': 'תנא היכא קאי דקתני...'},
    'רבא': {'he': 'גדול / רב (וגם שמו של האמורא רבא)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'תואר / שם', 'note': 'גברא רבא, יומא רבא'},
    'רזא': {'he': 'סוד / רז עליון', 'dialect': 'זוהר', 'cat': 'מושג יסוד בזוהר', 'note': 'רזא דמהימנותא (סוד האמונה)'},
    'רחמנא': {'he': 'הרחמן (כינוי להקב"ה ולתורה הקדושה)', 'dialect': 'בבלי, זוהר', 'cat': 'שם עצם', 'note': 'אמר רחמנא (אמרה התורה)'},
    'רישא': {'he': 'החלק הראשון של המשנה או הברייתא (ראש)', 'dialect': 'בבלי, זוהר', 'cat': 'מונח מבנה', 'note': 'רישא וסיפא'},
    'רמי': {'he': 'מטיל סתירה בין שני מקורות (וירמינהו)', 'dialect': 'בבלי', 'cat': 'פועל שקלא וטריא', 'note': 'רמי ליה רב פפא לאביי'},
    'שאני': {'he': 'שונה הדבר! (תירוץ המבדיל בין שני מקרים)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'שאני התם (שונה שם)'},
    'שבק': {'he': 'עזב / הניח / ויתר', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'פועל', 'note': 'שבקיה (הניחו אותו)'},
    'שכיח': {'he': 'מצוי / נפוץ', 'dialect': 'בבלי', 'cat': 'תואר', 'note': 'מילתא דשכיחא גזרו בה רבנן'},
    'שכינתא': {'he': 'השכינה הקדושה', 'dialect': 'זוהר, בבלי', 'cat': 'מושג יסוד', 'note': 'שכינתא קדישא'},
    'שמיא': {'he': 'שמים', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם עצם', 'note': 'מן שמיא, מרי דשמיא'},
    'שמע מינה': {'he': 'למד מכאן / הוכח מכאן', 'dialect': 'בבלי', 'cat': 'מונח הכרעה', 'note': 'ראשי תיבות: ש"מ'},
    'שמעתא': {'he': 'שמועה הלכתית / סוגיה שלמה', 'dialect': 'בבלי', 'cat': 'שם עצם', 'note': 'שמעתתא'},
    'שפיר': {'he': 'יפה / היטב / נכון / מותר', 'dialect': 'בבלי, זוהר', 'cat': 'תואר', 'note': 'שפיר קאמרת, שפיר דמי'},
    'שקיל וטרי': {'he': 'נושא ונותן בהלכה (שקלא וטריא)', 'dialect': 'בבלי, זוהר', 'cat': 'ביטוי תלמודי', 'note': 'משא ומתן הלכתי'},
    'שרי': {'he': 'מותר (לעומת "אסיר" - אסור)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מונח הלכתי', 'note': 'שרי ליה מריה (ימחל לו רבו/אדונו)'},
    'תא חזי': {'he': 'בוא וראה! (פתיחה להבאת ראיה או ביאור עמוק)', 'dialect': 'בבלי, זוהר', 'cat': 'פתיחה תלמודית ובזוהר', 'note': 'ראשי תיבות: ת"ח; נפוץ ביותר בזוהר הקדוש'},
    'תא שמע': {'he': 'בוא ושמע (הבאת ראיה או קושיה ממשנה או ברייתא)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'ראשי תיבות: ת"ש'},
    'תאנא': {'he': 'שנינו (פתיחה למאמר בזוהר, מקביל ל"תניא")', 'dialect': 'זוהר', 'cat': 'פתיחה בזוהר', 'note': 'תאנא בספרא דצניעותא'},
    'תגרא': {'he': 'סוחר (או: מריבה וקטטה)', 'dialect': 'בבלי', 'cat': 'שם עצם', 'note': 'תגרי לוד (סוחרי לוד)'},
    'תו': {'he': 'עוד / שוב / יותר', 'dialect': 'בבלי, זוהר', 'cat': 'תואר הפועל', 'note': 'ותו לא מידי (ויותר אין דבר)'},
    'תיובתא': {'he': 'קושיה מוחצת שאין עליה תירוץ (ובלשון הזוהר: חזרה בתשובה)', 'dialect': 'בבלי, זוהר', 'cat': 'מונח שקלא וטריא', 'note': 'תיובתא דפלוני תיובתא'},
    'תיקו': {'he': 'תעמוד! (השאלה נשארת במקומה ללא הכרעה)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'קיצור של תיקום (משורש קו"ם)'},
    'תמן': {'he': 'שם (מקביל ל"התם" בבבלי)', 'dialect': 'ירושלמי, זוהר', 'cat': 'תואר הפועל', 'note': 'תנינן תמן (שנינו שם במשנה)'},
    'תנא': {'he': 'חכם מתקופת המשנה / שנה ושילש בברייתא', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'מונח תנאי', 'note': 'תנא היכא קאי; תנא דידן'},
    'תנו רבנן': {'he': 'שנו חכמים (פתיחה לברייתא רחבה)', 'dialect': 'בבלי', 'cat': 'מונח תנאי', 'note': 'ראשי תיבות: ת"ר'},
    'תניא': {'he': 'שנינו בברייתא', 'dialect': 'בבלי', 'cat': 'מונח תנאי', 'note': 'מקור תנאי מחוץ למשנה'},
    'תנינן': {'he': 'שנינו במשנה (מקביל ל"תנן" בבבלי)', 'dialect': 'ירושלמי, זוהר', 'cat': 'מונח תנאי', 'note': 'תנינן תמן'},
    'תנן': {'he': 'שנינו במשנה', 'dialect': 'בבלי, ירושלמי', 'cat': 'מונח תנאי', 'note': 'ציטוט מתוך המשנה'},
    'תרוייהו': {'he': 'שניהם יחד', 'dialect': 'בבלי, זוהר', 'cat': 'שם מספר', 'note': 'דאמרי תרוייהו (שאומרים שניהם)'},
    'תרי': {'he': 'שניים (בנקבה: תרתי)', 'dialect': 'בבלי, ירושלמי, זוהר', 'cat': 'שם מספר', 'note': 'תרי ותלתא, תרתי דסתרן'},
    'ת"ש': {'he': 'תא שמע — בוא ושמע (הבאת ראיה או קושיה)', 'dialect': 'בבלי', 'cat': 'מונח שקלא וטריא', 'note': 'פתיחה להבאת ראיה ממשנה או ברייתא'},
    'תתאה': {'he': 'תחתון (לעומת "עילאה" - עליון)', 'dialect': 'זוהר, בבלי', 'cat': 'תואר', 'note': 'עלמא תתאה (העולם התחתון)'}
}

ZOHAR_AUTHENTIC_CORPUS = [
    {
        'book': 'ספר הזוהר - הקדמה',
        'chapter': 'דף א עמוד א',
        'verse': '1',
        'text': 'רַבִּי חִזְקִיָּה פָּתַח, כְּתִיב כְּשׁוֹשַׁנָּה בֵּין הַחוֹחִים. מַאן שׁוֹשַׁנָּה, דָּא כְּנֶסֶת יִשְׂרָאֵל, דְּאִיהִי שְׁכִינְתָּא קַדִּישָׁא דְּקָאֵי קַמֵּי מַלְכָּא. בְּגִין דְּאִית שׁוֹשַׁנָּה וְאִית שׁוֹשַׁנָּה, מַה שּׁוֹשַׁנָּה דְּאִיהִי בֵּין הַחוֹחִים אִית לָהּ סוּמְקָא וְחִוּוּרָא, אַף כְּנֶסֶת יִשְׂרָאֵל אִית לָהּ דִּינָא וְרַחֲמֵי. וְקוּדְשָׁא בְּרִיךְ הוּא בְּגִין רְחִימוּתָא דְּיִשְׂרָאֵל יָהַב לְהוֹן אוֹרַיְיתָא דְּקֻשְׁטָא.'
    },
    {
        'book': 'ספר הזוהר - פרשת בראשית',
        'chapter': 'דף טו עמוד א',
        'verse': '2',
        'text': 'בְּרֵאשִׁית, בְּרֵישׁ הוֹרְמָנוּתָא דְּמַלְכָּא גָּלִיף גְּלִיפוּ בִּטְהִירוּ עִלָּאָה, בּוֹצִינָא דְּקַרְדִּינוּתָא, וְנָפִיק גּוֹ סְתִימָא דִּסְתִימִין מֵרָזָא דְּאֵין סוֹף. וְהַאי נְהוֹרָא עִלָּאָה אִתְפְּשַׁט בְּעַלְמָא עִלָּאָה וּבְעַלְמָא תַּתָּאָה בְּגִין לְאַנְהָרָא לְכָל אִינוּן דְּעָסְקִין בְּאוֹרַיְיתָא יְמָמָא וְלֵילֵי.'
    },
    {
        'book': 'ספר הזוהר - פרשת שמות',
        'chapter': 'דף ב עמוד א',
        'verse': '3',
        'text': 'תָּאנָא, בְּשַׁעְתָּא דְּיִשְׂרָאֵל עָאלִין לְבָתֵּי כְּנֵשִׁיּוֹת וּמְצַלְּאִין צְלוֹתָא דְּעַמּוּדָא, קוּדְשָׁא בְּרִיךְ הוּא וּשְׁכִינְתָּא אִשְׁתְּכַחוּ תַּמָּן. וְהַאי צְלוֹתָא סָלְקָא לְעֵילָּא בְּרָזָא דְּמְהֵימְנוּתָא, וּבְגִין כָּךְ בָּעֵי בַּר נָשׁ לְכַוָּונָא לִבֵּיהּ בִּצְלוֹתֵיהּ קַמֵּי מָרֵיהּ דְּעַלְמָא.'
    },
    {
        'book': 'ספר הזוהר - פרשת ויקרא',
        'chapter': 'דף עג עמוד א',
        'verse': '4',
        'text': 'תָּא חֲזֵי, תְּלַת דַּרְגִּין אִינוּן מִתְקַשְּׁרָן דָּא בְּדָא: קוּדְשָׁא בְּרִיךְ הוּא, אוֹרַיְיתָא, וְיִשְׂרָאֵל. וְכָל פִּקּוּדָא וּפִקּוּדָא דְּאוֹרַיְיתָא אִית בֵּיהּ רָזָא עִלָּאָה וּנְהוֹרָא קַדִּישָׁא, וּמַאן דְּנָטִיר פִּקּוּדֵי אוֹרַיְיתָא מְעַטֵּר לְזְעֵיר אַנְפִּין וּלְעַתִּיקָא קַדִּישָׁא וְדָחֵי לְסִטְרָא אַחֲרָא מִן אַרְעָא וּמִן שְׁמַיָּא.'
    },
    {
        'book': 'ספר הזוהר - פרשת משפטים (סבא דמשפטים)',
        'chapter': 'דף צד עמוד ב',
        'verse': '5',
        'text': 'פָּתַח הַהוּא סָבָא וְאָמַר: יָנוֹקָא, חֲמֵי דִּיוֹקְנָא קַדִּישָׁא דְּשִׁמְשָׁא וְסִיהֲרָא, כַּד סִיהֲרָא מְקַבְּלָא נְהוֹרָא מִן שִׁמְשָׁא. וְאַרְבַּע יְסוֹדִין אִינוּן בְּעַלְמָא: מַיָּא וְנוּרָא רוּחָא וְעַפְרָא, וְכֻלְּהוּ קַיְּימִין בְּרָזָא דְּאוֹרַיְיתָא דְּקֻשְׁטָא בְּגִין יְקָרָא דְּקוּדְשָׁא בְּרִיךְ הוּא.'
    },
    {
        'book': 'ספר הזוהר - פרשת יתרו',
        'chapter': 'דף פה עמוד א',
        'verse': '6',
        'text': 'בְּגִין מָה אִתְיְהִיבַת אוֹרַיְיתָא בְּטוּרָא דְּסִינַי בְּנוּרָא וּבְמַיָּא? בְּגִין דְּאוֹרַיְיתָא אִיהִי כְּלִילָא מִתְּרֵין סִטְרִין, מִימִינָא וּמִשְּׂמָאלָא, וְאִיהוּ רָזָא דְּעַלְמָא עִלָּאָה וְעַלְמָא תַּתָּאָה דְּקָאֵי וְקַיְּימִין בְּקֻשְׁטָא.'
    }
]


def load_learned_aramaic_cache():
    path = os.path.join(settings.BASE_DIR, 'aramaic_learned_cache.json')
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_learned_aramaic_cache(data_dict):
    path = os.path.join(settings.BASE_DIR, 'aramaic_learned_cache.json')
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data_dict, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def aramaic_translator_view(request):
    def heb_sort_key(item):
        clean_term = re.sub(r'[^א-ת]', '', item['term'])
        return clean_term or item['term']

    bavli_list = sorted(
        [{'term': k, 'first_letter': re.sub(r'[^א-ת]', '', k)[:1], **v} for k, v in CORE_ARAMAIC_LEXICON.items() if 'בבלי' in v['dialect']],
        key=heb_sort_key
    )
    yerushalmi_list = sorted(
        [{'term': k, 'first_letter': re.sub(r'[^א-ת]', '', k)[:1], **v} for k, v in CORE_ARAMAIC_LEXICON.items() if 'ירושלמי' in v['dialect']],
        key=heb_sort_key
    )
    zohar_list = sorted(
        [{'term': k, 'first_letter': re.sub(r'[^א-ת]', '', k)[:1], **v} for k, v in CORE_ARAMAIC_LEXICON.items() if 'זוהר' in v['dialect']],
        key=heb_sort_key
    )

    return render(request, 'articles/aramaic_translator.html', {
        'current_page': 'aramaic_translator',
        'bavli_lexicon': bavli_list,
        'yerushalmi_lexicon': yerushalmi_list,
        'zohar_lexicon': zohar_list
    })


def _extract_senses_recursively(senses_list):
    defs = []
    if not isinstance(senses_list, list):
        return defs
    for s in senses_list:
        if isinstance(s, dict):
            d = strip_tags(s.get('definition', '')).strip()
            if d:
                defs.append(d)
            sub_senses = s.get('senses', [])
            if sub_senses:
                defs.extend(_extract_senses_recursively(sub_senses))
    return defs


def _query_sefaria_lexicon(word_to_query, depth=0):
    if depth > 1 or not word_to_query:
        return None
    try:
        sef_url = f"https://www.sefaria.org/api/words/{urllib.parse.quote(word_to_query)}"
        req = urllib.request.Request(sef_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=4) as resp:
            sef_data = json.loads(resp.read().decode('utf-8'))
            if not isinstance(sef_data, list) or not sef_data:
                return None

            collected_defs = []
            lex_names = []
            redirect_roots = []

            for entry in sef_data:
                lex_name = entry.get('parent_lexicon', '')
                content = entry.get('content', {})
                entry_defs = _extract_senses_recursively(content.get('senses', []))
                for ed in entry_defs:
                    clean_ed = re.sub(r'\s+', ' ', ed).strip()
                    ref_match = re.search(r'^(?:see|v\.|cmp\.|=)\s*([א-ת\u0591-\u05C7]+)', clean_ed, flags=re.IGNORECASE)
                    if ref_match and len(clean_ed) < 35:
                        ref_heb = re.sub(r'[^א-ת]', '', ref_match.group(1))
                        if ref_heb and ref_heb != word_to_query:
                            redirect_roots.append(ref_heb)
                    elif len(clean_ed) > 2:
                        collected_defs.append(clean_ed)
                        if lex_name and lex_name not in lex_names:
                            lex_names.append(lex_name)

            if not collected_defs and redirect_roots:
                target_root = redirect_roots[0]
                if target_root in CORE_ARAMAIC_LEXICON:
                    e = CORE_ARAMAIC_LEXICON[target_root]
                    return {
                        'detected_direction': 'ארמית ⬅ עברית (נטייה משורש)',
                        'main_translation': e['he'],
                        'bavli_variant': f"{word_to_query} (שורש: {target_root} — {e['he']})",
                        'yerushalmi_variant': e['he'],
                        'zohar_variant': e['he'],
                        'grammar_breakdown': f"הטיה מן השורש הארמי \"{target_root}\" ({e['cat']})",
                        'usage_example': e['note']
                    }
                return _query_sefaria_lexicon(target_root, depth=depth + 1)

            if collected_defs:
                raw_eng = " ; ".join(collected_defs[:3])
                clean_eng_for_trans = re.sub(r'\b(ch\.|pl\.|m\.|f\.|q\.?\s*v\.?|cmp\.|Targ\.|Y\.|Bab\.|preced\.|art\.)\b', '', raw_eng, flags=re.IGNORECASE)
                he_trans = clean_eng_for_trans
                try:
                    gt_url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=en&tl=iw&dt=t&q={urllib.parse.quote(clean_eng_for_trans[:320])}"
                    gt_req = urllib.request.Request(gt_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(gt_req, timeout=3) as gt_resp:
                        gt_json = json.loads(gt_resp.read().decode('utf-8'))
                        he_trans = "".join([part[0] for part in gt_json[0] if part[0]]).strip()
                except Exception:
                    pass

                lex_label = ", ".join(lex_names[:2]) or "מילון הערוך וגסטרוב"
                return {
                    'detected_direction': 'ארמית ⬅ עברית',
                    'main_translation': he_trans,
                    'bavli_variant': f"{word_to_query} — {he_trans}",
                    'yerushalmi_variant': he_trans,
                    'zohar_variant': he_trans,
                    'grammar_breakdown': f"מקור לקסיקלי: {lex_label} ({raw_eng[:130]})",
                    'usage_example': f"התיבה \"{word_to_query}\" מתבארת במילוני הארמית במשמעות: {he_trans}"
                }
    except Exception:
        pass
    return None


def _analyze_aramaic_morphology_and_lookup(clean_q):
    if clean_q in CORE_ARAMAIC_LEXICON:
        e = CORE_ARAMAIC_LEXICON[clean_q]
        return {
            'detected_direction': 'ארמית ⬅ עברית',
            'main_translation': e['he'],
            'bavli_variant': f"{clean_q} — {e['he']}" if 'בבלי' in e['dialect'] else e['he'],
            'yerushalmi_variant': f"{clean_q} — {e['he']}" if 'ירושלמי' in e['dialect'] else e['he'],
            'zohar_variant': f"{clean_q} — {e['he']}" if 'זוהר' in e['dialect'] else e['he'],
            'grammar_breakdown': f"{e['cat']} (נפוץ ב: {e['dialect']})",
            'usage_example': e['note']
        }

    tts_dict = load_tts_dictionary()
    if clean_q in tts_dict:
        val = re.sub(r'[\u0591-\u05C7]', '', tts_dict[clean_q])
        if val != clean_q:
            return {
                'detected_direction': 'ארמית / ראשי תיבות ⬅ עברית',
                'main_translation': tts_dict[clean_q],
                'bavli_variant': f"{clean_q} ({tts_dict[clean_q]})",
                'yerushalmi_variant': tts_dict[clean_q],
                'zohar_variant': tts_dict[clean_q],
                'grammar_breakdown': 'מונח תלמודי / ראשי תיבות',
                'usage_example': f"{clean_q} = {tts_dict[clean_q]}"
            }

    heb_matches = {'בבלי': [], 'ירושלמי': [], 'זוהר': []}
    for k, v in CORE_ARAMAIC_LEXICON.items():
        he_words = [w.strip() for w in re.split(r'[/,()—\-!?]', v['he']) if w.strip()]
        if clean_q in he_words or any(clean_q == hw for hw in he_words) or (len(clean_q) >= 3 and clean_q in v['he']):
            for d_name in ['בבלי', 'ירושלמי', 'זוהר']:
                if d_name in v['dialect']:
                    heb_matches[d_name].append(f"{k} ({v['he']})")

    if any(heb_matches.values()):
        all_ar = []
        for lst in heb_matches.values():
            for item in lst:
                if item not in all_ar:
                    all_ar.append(item)
        return {
            'detected_direction': 'עברית ⬅ ארמית',
            'main_translation': " | ".join(all_ar[:4]),
            'bavli_variant': ", ".join(heb_matches['בבלי'][:3]) or all_ar[0],
            'yerushalmi_variant': ", ".join(heb_matches['ירושלמי'][:3]) or all_ar[0],
            'zohar_variant': ", ".join(heb_matches['זוהר'][:3]) or all_ar[0],
            'grammar_breakdown': f"תרגום מעברית לארמית עבור \"{clean_q}\"",
            'usage_example': all_ar[0]
        }

    prefixes = [
        ('דקא', 'שעומד ו... (ד + קא)'),
        ('בגין', 'בשביל / מפני'),
        ('קא', 'הווה מתמשך (עומד ו...)'),
        ('ד', 'ש... / של (תחילית זיקה בארמית)'),
        ('ב', 'ב... (תחילית יחס)'),
        ('ל', 'ל... / אל (תחילית יחס)'),
        ('מ', 'מן / מתוך (תחילית)'),
        ('ו', 'ו... (ו\' החיבור)'),
        ('כ', 'כמו / כפי')
    ]
    for pref, pref_meaning in prefixes:
        if clean_q.startswith(pref) and len(clean_q) - len(pref) >= 2:
            stem = clean_q[len(pref):]
            if stem in CORE_ARAMAIC_LEXICON:
                e = CORE_ARAMAIC_LEXICON[stem]
                return {
                    'detected_direction': 'ארמית ⬅ עברית (פירוק דקדוקי)',
                    'main_translation': f"{pref_meaning.split('(')[0].strip()} + {e['he']}",
                    'bavli_variant': f"{clean_q} (שורש: {stem} = {e['he']})",
                    'yerushalmi_variant': e['he'],
                    'zohar_variant': e['he'],
                    'grammar_breakdown': f"תחילית \"{pref}-\" ({pref_meaning}) + המילה \"{stem}\" ({e['he']})",
                    'usage_example': e['note']
                }

    sef_res = _query_sefaria_lexicon(clean_q)
    if sef_res:
        return sef_res

    for pref, pref_meaning in prefixes:
        if clean_q.startswith(pref) and len(clean_q) - len(pref) >= 2:
            stem = clean_q[len(pref):]
            sef_stem = _query_sefaria_lexicon(stem)
            if sef_stem:
                sef_stem['main_translation'] = f"{pref_meaning.split('(')[0].strip()} + {sef_stem['main_translation']}"
                sef_stem['grammar_breakdown'] = f"תחילית \"{pref}-\" + שורש \"{stem}\" ({sef_stem['grammar_breakdown']})"
                return sef_stem

    return None


@ratelimit(rate=30, timeout=60)
def aramaic_translate_api(request):
    q = request.GET.get('q', '').strip()
    direction = request.GET.get('dir', 'auto').strip()
    dialect = request.GET.get('dialect', 'bavli').strip()

    if not q:
        return JsonResponse({'error': 'נא להזין מילה, ביטוי או משפט לתרגום.'}, status=400)

    clean_q = re.sub(r'[^\w\sא-ת"״\'׳\-]', '', q).strip()
    cache_key = f"aramaic_trans_v8_{direction}_{dialect}_{clean_q}"
    cached_res = cache.get(cache_key)
    if cached_res:
        return JsonResponse(cached_res, json_dumps_params={'ensure_ascii': False})

    WORD_TOKEN_RE = re.compile(r'[א-ת\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]+')
    NON_HEB_RE = re.compile(r'[^א-ת]+')

    def find_talmud_examples(search_term, target_dialect):
        heb_words = [w for w in re.findall(r'[א-ת]+', search_term) if len(w) >= 2]
        if not heb_words:
            return []
        target_w = heb_words[0]
        examples = []

        if target_dialect == 'zohar':
            for z_item in ZOHAR_AUTHENTIC_CORPUS:
                raw_t = z_item['text']
                toks = list(WORD_TOKEN_RE.finditer(raw_t))
                spans = [t.span() for t in toks if target_w in NON_HEB_RE.sub('', t.group(0))]
                if spans:
                    s0, e0 = spans[0]
                    marked = (
                        raw_t[:s0] +
                        f'<mark style="background-color: #fde047; color: #000; padding: 0 4px; border-radius: 4px; font-weight: bold;">{raw_t[s0:e0]}</mark>' +
                        raw_t[e0:]
                    )
                    examples.append({
                        'book': z_item['book'],
                        'chapter': z_item['chapter'],
                        'verse': z_item['verse'],
                        'ref': f"{z_item['book']} ({z_item['chapter']})",
                        'dialect_tag': 'ספר הזוהר',
                        'text': format_divine_name(marked),
                        'full_text': format_divine_name(marked)
                    })
            if not examples:
                entry_note = CORE_ARAMAIC_LEXICON.get(clean_q, {}).get('note', f'התיבה "{clean_q}" בלשון ספר הזוהר הקדוש')
                examples.append({
                    'book': 'ספר הזוהר הקדוש',
                    'chapter': 'לשון הזוהר',
                    'verse': '1',
                    'ref': 'ספר הזוהר הקדוש (מאגר לשון הזוהר)',
                    'dialect_tag': 'ספר הזוהר',
                    'text': format_divine_name(f'בספר הזוהר: <mark style="background-color: #fde047; color: #000; padding: 0 4px; border-radius: 4px; font-weight: bold;">{clean_q}</mark> — {entry_note}'),
                    'full_text': format_divine_name(f'מקור מלשון ספר הזוהר הקדוש עבור "{clean_q}":\n\n{entry_note}')
                })
            return examples[:3]

        if target_dialect == 'yerushalmi':
            qs = TorahText.objects.filter(book__startswith='ירושלמי ')
        else:
            qs = TorahText.objects.filter(chapter__startswith='דף').exclude(book__startswith='ירושלמי ')

        for hw in heb_words[:2]:
            qs = qs.filter(clean_text__icontains=hw)

        rows = list(qs.values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')[:25])
        for r in rows:
            raw_t = r.get('text_with_nikkud') or r.get('clean_text') or ''
            toks = list(WORD_TOKEN_RE.finditer(raw_t))
            spans = [t.span() for t in toks if target_w in NON_HEB_RE.sub('', t.group(0))]
            if spans:
                s0, e0 = spans[0]
                win_s = max(0, s0 - 90)
                win_e = min(len(raw_t), e0 + 90)
                snippet = (
                    ("... " if win_s > 0 else "") +
                    raw_t[win_s:s0] +
                    f'<mark style="background-color: #fde047; color: #000; padding: 0 4px; border-radius: 4px; font-weight: bold;">{raw_t[s0:e0]}</mark>' +
                    raw_t[e0:win_e] +
                    (" ..." if win_e < len(raw_t) else "")
                )
                examples.append({
                    'book': r['book'],
                    'chapter': r['chapter'],
                    'verse': r['verse'],
                    'ref': f"{r['book']} ({r['chapter']}, {r['verse']})",
                    'dialect_tag': 'ירושלמי' if r['book'].startswith('ירושלמי ') else 'בבלי',
                    'text': format_divine_name(snippet),
                    'full_text': ''
                })
                if len(examples) >= 3:
                    break
        return examples

    talmud_examples = find_talmud_examples(clean_q, dialect)
    learned_db = load_learned_aramaic_cache()
    learned_key = f"{direction}|{dialect}|{clean_q}"

    if learned_key in learned_db:
        saved = learned_db[learned_key]
        saved['talmud_examples'] = talmud_examples
        cache.set(cache_key, saved, 3600 * 24)
        return JsonResponse(saved, json_dumps_params={'ensure_ascii': False})

    resolved_data = _analyze_aramaic_morphology_and_lookup(clean_q)

    if not resolved_data:
        words_in_phrase = [w for w in clean_q.split() if len(w) >= 2]
        if len(words_in_phrase) > 1:
            word_translations = []
            for w in words_in_phrase:
                sub_res = _analyze_aramaic_morphology_and_lookup(w)
                if sub_res:
                    word_translations.append(f"{w} = {sub_res['main_translation']}")
            if word_translations:
                joined_tr = " | ".join(word_translations)
                resolved_data = {
                    'detected_direction': 'ארמית ⇄ עברית (פירוק ביטוי)',
                    'main_translation': joined_tr,
                    'bavli_variant': joined_tr,
                    'yerushalmi_variant': joined_tr,
                    'zohar_variant': joined_tr,
                    'grammar_breakdown': 'פירוק מילות הביטוי מתוך המילון התלמודי',
                    'usage_example': talmud_examples[0]['text'] if talmud_examples else ''
                }

    if not resolved_data:
        acr_hit = Acronym.objects.filter(Q(short=clean_q) | Q(short__icontains=clean_q)).first()
        if acr_hit:
            resolved_data = {
                'detected_direction': 'ראשי תיבות ומונחים ⬅ עברית',
                'main_translation': acr_hit.meaning,
                'bavli_variant': f"{acr_hit.short} = {acr_hit.meaning}",
                'yerushalmi_variant': acr_hit.meaning,
                'zohar_variant': acr_hit.meaning,
                'grammar_breakdown': 'נמצא במילון ראשי התיבות והמונחים של הספרייה',
                'usage_example': f"{acr_hit.short}: {acr_hit.meaning}"
            }

    if not resolved_data:
        api_key = os.environ.get('GEMINI_API_KEY', '').strip() or getattr(settings, 'GEMINI_API_KEY', '').strip()
        if api_key:
            prompt = (
                f"תרגם את המילה או הביטוי בארמית/עברית: \"{clean_q}\" (ניב מבוקש: {dialect}).\n"
                f"החזר אך ורק JSON תקני עם המפתחות: detected_direction, main_translation, bavli_variant, yerushalmi_variant, zohar_variant, grammar_breakdown, usage_example."
            )
            for m_name in ['gemini-2.5-flash', 'gemini-2.0-flash']:
                try:
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
                    req = urllib.request.Request(url, data=json.dumps({"contents": [{"parts": [{"text": prompt}]}]}, ensure_ascii=False).encode('utf-8'), headers={'Content-Type': 'application/json'})
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        raw_ans = json.loads(resp.read().decode('utf-8')).get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                        m_brace = re.search(r'\{.*\}', raw_ans, flags=re.DOTALL)
                        if m_brace:
                            resolved_data = json.loads(m_brace.group(0))
                            learned_db[learned_key] = resolved_data
                            save_learned_aramaic_cache(learned_db)
                            break
                except Exception:
                    continue

    if not resolved_data:
        resolved_data = {
            'detected_direction': 'ארמית ⇄ עברית',
            'main_translation': f'ראה הקשר הסוגיה עבור "{clean_q}" בדוגמאות להלן',
            'bavli_variant': clean_q,
            'yerushalmi_variant': clean_q,
            'zohar_variant': clean_q,
            'grammar_breakdown': 'תיבה מתוך מאגר הש"ס והזוהר',
            'usage_example': talmud_examples[0]['text'] if talmud_examples else ''
        }

    result_payload = {
        'query': clean_q,
        'selected_dialect': dialect,
        'detected_direction': resolved_data.get('detected_direction', 'ארמית ⇄ עברית'),
        'main_translation': format_divine_name(resolved_data.get('main_translation', '')),
        'bavli_variant': format_divine_name(resolved_data.get('bavli_variant', '')),
        'yerushalmi_variant': format_divine_name(resolved_data.get('yerushalmi_variant', '')),
        'zohar_variant': format_divine_name(resolved_data.get('zohar_variant', '')),
        'grammar_breakdown': format_divine_name(resolved_data.get('grammar_breakdown', '')),
        'usage_example': format_divine_name(resolved_data.get('usage_example', '')),
        'talmud_examples': talmud_examples
    }

    cache.set(cache_key, result_payload, 3600 * 24)
    return JsonResponse(result_payload, json_dumps_params={'ensure_ascii': False})