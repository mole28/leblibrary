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


def get_book_order(book_name, chapter_name=""):
    name = str(book_name or '').strip()
    chap = str(chapter_name or '').strip()
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
    if chap.startswith('דף') and not name.startswith('ירושלמי '):
        return 230 + BOOK_ORDER.get(name, 90)
    if name.startswith('ירושלמי '):
        base = name.replace('ירושלמי ', '', 1).strip()
        return 350 + BOOK_ORDER.get(base, 90)
    if name.startswith('רמב"ם ') or name.startswith('רמב״ם '):
        return 500
    if name.startswith('שולחן ערוך '):
        sa_order = {
            'שולחן ערוך אורח חיים': 601,
            'שולחן ערוך יורה דעה': 602,
            'שולחן ערוך אבן העזר': 603,
            'שולחן ערוך חושן משפט': 604
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
    s_clean = re.sub(r'^(פרק|סימן|דף|הלכה|משנה|סעיף)\s+', '', s)
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


def _fetch_commentary_for_source(book_name, chapter_name, verse_num):
    b_str = str(book_name or '').strip().replace('״', '"')
    c_str = str(chapter_name or '').strip()
    v_str = str(verse_num or '').strip()

    cache_key = f"torah_comm_v2_{b_str}_{c_str}_{v_str}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    ch_clean = re.sub(r'^(פרק|סימן|דף)\s+', '', c_str).strip()
    ch_clean = re.sub(r'["\'׳״]', '', ch_clean)
    v_clean = int_to_hebrew(int(v_str)) if v_str.isdigit() else re.sub(r'["\'׳״]', '', v_str)

    target_commentator = 'רש"י'
    he_refs_to_try = []

    if b_str.startswith('רמב"ם '):
        target_commentator = 'מגיד משנה'
        hilchot = b_str.replace('רמב"ם ', '', 1).strip()
        he_refs_to_try.append(f"מגיד משנה על משנה תורה, {hilchot} {ch_clean}:{v_clean}")
        he_refs_to_try.append(f"כסף משנה על משנה תורה, {hilchot} {ch_clean}:{v_clean}")
    elif b_str.startswith('שולחן ערוך '):
        target_commentator = 'באר היטב'
        chelek = b_str.replace('שולחן ערוך ', '', 1).strip()
        he_refs_to_try.append(f"באר היטב על שולחן ערוך, {chelek} {ch_clean}:{v_clean}")
    elif c_str.startswith('דף') and not b_str.startswith('ירושלמי '):
        target_commentator = 'רש"י'
        daf_parts = ch_clean.split()
        daf_let = daf_parts[0] if daf_parts else ch_clean
        amud_let = 'ב' if ('עמוד ב' in c_str or ':' in c_str) else 'א'
        he_refs_to_try.append(f'רש"י על {b_str} {daf_let} {amud_let}:{v_str}')
        he_refs_to_try.append(f'רש"י על {b_str} {daf_let} {amud_let}')
    elif b_str in TANAKH_NAMES:
        target_commentator = 'רש"י'
        he_refs_to_try.append(f'רש"י על {b_str} {ch_clean}:{v_clean}')
    elif b_str in MISHNAH_BOOKS:
        target_commentator = 'רבינו עובדיה מברטנורא'
        he_refs_to_try.append(f'ברטנורא על משנה {b_str} {ch_clean}:{v_clean}')

    comments_out = []
    used_commentator = target_commentator

    for ref_try in he_refs_to_try:
        try:
            url = f"https://www.sefaria.org/api/texts/{urllib.parse.quote(ref_try)}?context=0&pad=0"
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                he_data = data.get('he', [])
                if isinstance(he_data, str) and he_data.strip():
                    comments_out = [format_divine_name(he_data.strip())]
                elif isinstance(he_data, list):
                    flat = []
                    for item in he_data:
                        if isinstance(item, str) and item.strip():
                            flat.append(format_divine_name(item.strip()))
                        elif isinstance(item, list):
                            for sub in item:
                                if isinstance(sub, str) and sub.strip():
                                    flat.append(format_divine_name(sub.strip()))
                    if flat:
                        comments_out = flat[:6]
                if comments_out:
                    if 'כסף משנה' in ref_try:
                        used_commentator = 'כסף משנה (לא נמצא מגיד משנה להלכה זו)'
                    break
        except Exception:
            continue

    payload = {'commentator': used_commentator, 'comments': comments_out}
    cache.set(cache_key, payload, 3600 * 24)
    return payload


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
        elif b_str.startswith('רמב"ם ') or b_str.startswith('רמב״ם ') or b_str.startswith('ירושלמי ') or b_str.startswith('תוספתא '):
            return 'הלכה'
        elif c_str.startswith('דף'):
            return 'שורה'
        elif b_str not in TANAKH_NAMES:
            return 'משנה'
        return 'פסוק'

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
                        'verse': v['verse'],
                        'text': format_divine_name(v['text_with_nikkud'] or v['clean_text'] or '')
                    }
                    for v in ch_verses
                ]
            }, json_dumps_params={'ensure_ascii': False})
        return JsonResponse({'verses': []})

    if query_type == 'quick_open':
        explicit_book = request.GET.get('target_book', '').strip()
        explicit_chapter = request.GET.get('target_chapter', '').strip()
        ref_str = request.GET.get('ref', '').strip()

        all_books = cache.get('torah_all_distinct_books_v2')
        if not all_books:
            all_books = list(TorahText.objects.values_list('book', flat=True).distinct())
            cache.set('torah_all_distinct_books_v2', all_books, 3600 * 24)

        def norm_quotes(s):
            return re.sub(r'[״”″]', '"', re.sub(r"[׳’']", "", str(s or ''))).strip()

        matched_book = None
        want_bavli = False
        want_mishnah = False
        chapter_hint = explicit_chapter

        if explicit_book:
            matched_book = _resolve_torah_book_in_db(explicit_book)
            if explicit_chapter.startswith('דף'):
                want_bavli = True
        elif ref_str:
            q_work = norm_quotes(ref_str)
            q_work = re.sub(r'^שו"ע\s+', 'שולחן ערוך ', q_work)
            q_work = re.sub(r'^רמבם\s+', 'רמב"ם ', q_work)
            if q_work.startswith('הלכות '):
                q_work = 'רמב"ם ' + q_work

            if re.match(r'^(תלמוד בבלי|בבלי|גמרא)\s+', q_work):
                want_bavli = True
                q_work = re.sub(r'^(תלמוד בבלי|בבלי|גמרא)\s+', '', q_work).strip()
            elif q_work.startswith('משנה '):
                want_mishnah = True
                q_work = q_work.replace('משנה ', '', 1).strip()

            sorted_books = sorted(all_books, key=lambda b: len(str(b)), reverse=True)
            for b_candidate in sorted_books:
                b_norm = norm_quotes(b_candidate)
                if q_work == b_norm or q_work.startswith(b_norm + ' '):
                    matched_book = b_candidate
                    chapter_hint = q_work[len(b_norm):].strip()
                    break

            if not matched_book:
                for b_candidate in sorted_books:
                    b_norm = norm_quotes(b_candidate)
                    if b_norm in q_work:
                        matched_book = b_candidate
                        chapter_hint = q_work.replace(b_norm, '', 1).strip()
                        break

            if 'דף ' in ref_str and not str(matched_book or '').startswith('ירושלמי '):
                want_bavli = True

        if not matched_book:
            return JsonResponse({'error': 'לא זוהה שם הספר במאגר. נסה לכתוב למשל: רמב"ם הלכות ברכות פרק ג'})

        ch_qs = TorahText.objects.filter(book=matched_book)
        if matched_book in MISHNAH_BOOKS:
            if want_bavli:
                ch_qs = ch_qs.filter(chapter__startswith='דף')
            elif want_mishnah or not str(chapter_hint).startswith('דף'):
                ch_qs = ch_qs.exclude(chapter__startswith='דף')

        raw_chapters = list(ch_qs.values_list('chapter', flat=True).distinct())
        if not raw_chapters:
            raw_chapters = list(TorahText.objects.filter(book=matched_book).values_list('chapter', flat=True).distinct())

        raw_chapters.sort(key=safe_int)
        if not raw_chapters:
            return JsonResponse({'error': f'לא נמצאו פרקים עבור "{matched_book}".'})

        chosen_chapter = raw_chapters[0]
        if chapter_hint:
            h_clean = re.sub(r'^(פרק|סימן|הלכה)\s+', '', chapter_hint).strip()
            h_no_daf = re.sub(r'^דף\s+', '', h_clean).strip()

            found_ch = None
            for c_opt in raw_chapters:
                c_str = str(c_opt).strip()
                c_stripped = re.sub(r'^(פרק|סימן|דף)\s+', '', c_str).strip()
                if c_str == chapter_hint or c_str == h_clean or c_stripped == h_clean or c_stripped == h_no_daf:
                    found_ch = c_opt
                    break
            if not found_ch:
                for c_opt in raw_chapters:
                    c_str = str(c_opt).strip()
                    if h_no_daf and (c_str.startswith(f"דף {h_no_daf} ") or c_str == f"דף {h_no_daf}"):
                        found_ch = c_opt
                        break
            if not found_ch:
                target_num = safe_int(chapter_hint)
                if target_num > 0:
                    for c_opt in raw_chapters:
                        if safe_int(c_opt) == target_num:
                            found_ch = c_opt
                            break
            if found_ch:
                chosen_chapter = found_ch

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
                    'verse': v['verse'],
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

    search_cache_key = f"tanakh_srch_v4_{query_type}_{query_val}_{book_filter}_{is_exact}_{exclude_books_param}_{skip_param}_{page}_{per_page}"
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
                            'verse': m['verse'],
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

        results.sort(key=lambda x: (get_book_order(x['book'], x.get('chapter', '')), safe_int(x['chapter']), safe_int(x['verse'])))

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

    cache_key = f"torah_ai_v7_{mode}_{book}_{chapter}_{verse}_{query}"
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


from .aramaic_engine import aramaic_translator_view as _get_aramaic_context, execute_aramaic_translation


def aramaic_translator_view(request):
    context = _get_aramaic_context(request)
    return render(request, 'articles/aramaic_translator.html', context)


@ratelimit(rate=30, timeout=60)
def aramaic_translate_api(request):
    payload, status_code = execute_aramaic_translation(request)
    return JsonResponse(payload, status=status_code, json_dumps_params={'ensure_ascii': False})