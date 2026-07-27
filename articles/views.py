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
import edge_tts
import subprocess
import tempfile
from html import unescape
from functools import wraps

from django.http import JsonResponse, HttpResponse
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
from django.db import models
from django.utils.html import strip_tags
from asgiref.sync import async_to_sync

from .forms import ArticleForm
from .models import Article, Book, Chapter, Section, Cart, CartItem, Order, OrderItem
from .emails import send_order_confirmation
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

# ==========================================
# מנגנון Rate Limiting מבוסס Cache להגנה על ה-API
# ==========================================
def ratelimit(rate=30, timeout=60):
    """
    מגביל קצב בקשות לכתובת IP לפי מטמון (Cache).
    ברירת מחדל: עד 30 בקשות בתוך חלון זמן של 60 שניות.
    """
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
            
            # סינון בקשות ישנות מחוץ לחלון הזמן
            history = [t for t in history if now - t < timeout]
            
            if len(history) >= rate:
                return JsonResponse({
                    'meta': {
                        'error': 'Rate limit exceeded. Maximum 30 requests per minute allowed.',
                        'retry_after_seconds': timeout
                    },
                    'results': []
                }, status=429) # סטטוס 429: Too Many Requests
            
            history.append(now)
            cache.set(cache_key, history, timeout)
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

# ==========================================
# פונקציות לוח שנה עברי (פרשה, הפטרה, מועדים)
# ==========================================
def translate_haftarah(text):
    if not text: return ""
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
    return text

def get_jewish_calendar_info():
    today = datetime.date.today()
    cache_key = f'jewish_cal_data_v3_{today.strftime("%Y_%m_%d")}'
    cached_data = cache.get(cache_key)
    
    if cached_data:
        return cached_data
        
    cal_data = {'parasha': '', 'haftarah': '', 'holidays': []}
    
    try:
        days_ahead = 5 - today.weekday()
        if days_ahead < 0:
            days_ahead += 7
            
        next_saturday = today + datetime.timedelta(days=days_ahead)
        
        start_date = today.strftime('%Y-%m-%d')
        end_date = next_saturday.strftime('%Y-%m-%d')
        
        url = f'https://www.hebcal.com/hebcal?v=1&cfg=json&geo=IL&lg=h&s=on&maj=on&min=on&start={start_date}&end={end_date}'
        
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
    except Exception as e:
        print(f"Hebcal API Error: {e}")
        pass
        
    return cal_data

# ==========================================
# אלגוריתמים לחילוץ וסריקה דינמית מספרי Django Admin
# ==========================================
def generate_word_variations(word):
    variations = set([word])
    if len(word) > 3 and word[0] in 'הבוכשמל':
        variations.add(word[1:])
    if len(word) > 4 and word[:2] in ['וה', 'בה', 'מה', 'שה', 'כה', 'וש', 'ול', 'וכ', 'ומ']:
        variations.add(word[2:])
    return list(variations)

def smart_hebrew_search(queryset, query, search_fields):
    if not query: return queryset
    words = [w for w in query.strip().split() if len(w) > 1]
    if not words:
        fallback_q = Q()
        for field in search_fields: fallback_q |= Q(**{f"{field}__icontains": query})
        return queryset.filter(fallback_q)

    main_q_and = Q()
    main_q_or = Q()
    
    for word in words:
        word_variations = generate_word_variations(word)
        word_q = Q()
        for var in word_variations:
            for field in search_fields: word_q |= Q(**{f"{field}__icontains": var})
        main_q_and &= word_q  
        main_q_or |= word_q   

    results = queryset.filter(main_q_and)
    if not results.exists(): results = queryset.filter(main_q_or)

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
    try: return str(item)
    except: return f"{item.__class__.__name__} {getattr(item, 'pk', '')}"

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
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def ai_document_search(queryset, search_query, search_fields, words, limit=4):
    if not search_fields or not words: return []

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
    
    if not candidates: return []
        
    def get_score(item):
        score = getattr(item, 'match_score', 0) * 1000
        title = get_item_title(item).lower()
        content = get_item_text(item).lower()
        full_text = title + " " + content
        
        if search_query.lower() in full_text: score += 1000000
        
        unique_matches = sum(1 for word in words if word in full_text)
        score += (unique_matches ** 4) * 50000 
        
        for word in words:
            score += full_text.count(word) * 10 
            
        return score
        
    candidates.sort(key=get_score, reverse=True)
    return candidates[:limit]

def get_smart_content(text, query_words, max_chars=40000):
    if not text: return ""
    if len(text) <= max_chars: return text
    if not query_words: return text[:max_chars]
    
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
def ai_chat_endpoint(request):
    if request.method == 'POST':
        try:
            API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
            if not API_KEY:
                return JsonResponse({'answer': 'שגיאה: מפתח ה-API של המודל לא מוגדר בשרת.'})

            data = json.loads(request.body)
            user_question = data.get('question', '')
            mode = data.get('mode', 'content') 
            
            if not user_question: return JsonResponse({'answer': 'אנא כתוב שאלה.'})

            prompt = ""
            relevant_items = []
            
            if mode == 'nav':
                nav_context = """
                להלן מפת הקישורים והפונקציות של האתר שלנו (חובה להשתמש *אך ורק* במידע זה):
                
                **עמודים באתר:**
                - דף הבית: /
                - צור קשר / יצירת קשר: /contact/
                - אודות: /about/
                - שאלות ותשובות (שו"ת): /qa/
                - ספרים / חנות ספרים: /books/
                - מחשבון מידות אורך: /calculator/
                - מחשבון מידות נפח: /volume_calculator/
                - מחשבון מידות משקל: /weight_calculator/
                - עגלת קניות / סל קניות: /cart/
                - קופה / תשלום: /checkout/
                - אינדקס מאמרים: /article_index/
                - פרשת שבוע: /parasha/
                - נוספו לאחרונה: /recently_added/
                - תנאי שימוש: /terms/
                
                **ממשק ופונקציות באתר:**
                - תאורת לילה / מצב לילה / מצב חשוך (Dark Mode): יש באתר כפתור מובנה להחלפה לתאורת לילה. אם הגולש שואל על כך, הסבר לו שהוא יכול פשוט ללחוץ על הכפתור/האייקון של תאורת הלילה שמופיע באתר (בדרך כלל למעלה בסרגל הניווט) ואין צורך בקישור לשם כך.
                """
                prompt = f"אתה עוזר וירטואלי חייכן ומסביר פנים באתר 'ספריית לייבוביץ'. תפקידך לעזור לגולשים לנווט באתר ולהכיר את הפונקציות שלו.\n{nav_context}\nהגולש שואל אותך: '{user_question}'\nחובה עליך לענות בנימוס ולהסביר לגולש, או להפנות לעמוד הנכון מתוך הרשימה. חשוב מאוד: שלב קישור בפורמט מרקדאון רק עם הנתיב היחסי כפי שהוא כתוב (לדוגמה: [טקסט](/contact/)), בשום אופן אל תוסיף http או כתובות דומיין כמו example.com."
            else:
                clean_question = re.sub(r'[^\w\s]', '', user_question)
                words = clean_question.split()
                stopwords = ['מהי', 'מהו', 'האם', 'כיצד', 'איך', 'את', 'על', 'לי', 'תסביר', 'מתי', 'למה', 'מדוע', 'של', 'לו', 'אני', 'רוצה', 'לדעת', 'מה', 'מי', 'הוא', 'היא', 'הם', 'הן', 'יש', 'אין', 'כמו', 'לגבי', 'בבקשה', 'היי', 'שלום', 'כמה', 'זה', 'אילו', 'איזה', 'איזו', 'היכן', 'איפה', 'מאיפה', 'כדי', 'כי', 'גם', 'רק', 'כל', 'כך']
                valid_words = [w for w in words if len(w) > 1 and w not in stopwords]
                
                search_query = " ".join(valid_words)

                if search_query:
                    models_to_search = [Article, Section, Chapter, Book]
                    try:
                        from .models import QA
                        models_to_search.append(QA)
                    except: pass
                        
                    for model in models_to_search:
                        fields = get_text_fields(model)
                        if fields:
                            try:
                                items = ai_document_search(model.objects.all(), search_query, fields, valid_words, limit=4)
                                relevant_items.extend(items)
                            except Exception:
                                pass

                if not relevant_items:
                    return JsonResponse({'answer': 'מצטער, לא הצלחתי לאתר חומרים רלוונטיים במאגרי הספרייה לשאלתך. נסה לנסח אחרת.'})
                    
                context_text = ""
                MAX_CHARS = 40000 
                
                seen_items = set()
                unique_relevant_items = []
                
                def get_global_score(item):
                    score = getattr(item, 'match_score', 0) * 1000
                    full_text = get_item_title(item).lower() + " " + get_item_text(item).lower()
                    if search_query.lower() in full_text: score += 50000
                    unique_matches = sum(1 for word in valid_words if word in full_text)
                    score += (unique_matches ** 4) * 5000 
                    return score

                relevant_items.sort(key=get_global_score, reverse=True)
                
                for item in relevant_items:
                    item_key = f"{item.__class__.__name__}_{item.pk}"
                    if item_key not in seen_items:
                        seen_items.add(item_key)
                        unique_relevant_items.append(item)
                        if len(unique_relevant_items) >= 4: break

                for item in unique_relevant_items: 
                    title = get_item_title(item)
                    content = get_item_text(item)
                    if content:
                        context_text += f"--- מקור: '{title}' ---\n{get_smart_content(content, valid_words, MAX_CHARS)}\n\n"
                    
                prompt = f"""אתה רב וסייע תורני חכם מטעם 'ספריית לייבוביץ'.
הגולש שואל אותך: '{user_question}'

כלל ברזל 1: חובה עליך לענות **אך ורק** על סמך הטקסטים המצורפים מטה (שהם המקורות שאותרו מתוך מאגר הספרייה). 
כלל ברזל 2: אם התשובה לשאלה אינה מופיעה במפורש בטקסטים אלו, אסור לך להמציא פסיקה, אסור לך להסתמך על ידע חיצוני שיש לך, ואסור לך לנתח את המקורות כדי להראות למה הם לא קשורים. עליך לכתוב בדיוק את המשפט הבא בלבד: "מצטער, לא מצאתי לכך התייחסות מפורשת במקורות שנסרקו בספרייה."

אם התשובה כן קיימת במקורות שקיבלת, כתוב אותה בפירוט, בצורה הלכתית ומכובדת (השתמש בפסקאות לסדר את המידע). חובה עליך לציין בגוף התשובה במפורש את השם המדויק של המקור (בדיוק כפי שהוא מופיע בין המקפים בטקסט המקורות) שעליו הסתמכת.

מקורות הספרייה:
{context_text}"""
            
            KNOWN_GOOD_MODELS = [
                'models/gemini-flash-lite-latest',
                'models/gemini-pro-latest'
            ] 
            
            final_response = None
            last_error = ""

            def fetch_from_google(model_name):
                url = f"https://generativelanguage.googleapis.com/v1beta/{model_name}:generateContent?key={API_KEY}"
                payload = {"contents": [{"parts": [{"text": prompt}]}]}
                data_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
                req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
                response = urllib.request.urlopen(req, timeout=25)
                resp_data = json.loads(response.read().decode('utf-8'))
                return resp_data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')

            with concurrent.futures.ThreadPoolExecutor(max_workers=len(KNOWN_GOOD_MODELS)) as executor:
                future_to_model = {executor.submit(fetch_from_google, model): model for model in KNOWN_GOOD_MODELS}
                
                for future in concurrent.futures.as_completed(future_to_model):
                    try:
                        result = future.result()
                        if result:
                            final_response = result
                            break
                    except Exception as e:
                        last_error = str(e)

            if final_response: 
                if mode == 'nav':
                    final_response = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_self" style="color: #2575fc; font-weight: bold; text-decoration: underline;">\1</a>', final_response)
                else:
                    final_response = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'<a href="\2" target="_blank" style="color: #d4af37; font-weight: bold; text-decoration: underline;">\1</a>', final_response)
                
                final_response = final_response.replace('*', '')

                if mode != 'nav' and unique_relevant_items and "לא מצאתי לכך התייחסות מפורשת" not in final_response:
                    sources_added = False
                    sources_list_html = ""
                    
                    for item in unique_relevant_items:
                        title = get_item_title(item)
                        if title and title in final_response:
                            url = "#"
                            try:
                                item_model = item.__class__.__name__
                                if item_model == 'Article':
                                    url = reverse('articles:detail', args=[item.pk])
                                elif item_model == 'Book':
                                    url = reverse('articles:book_detail', args=[item.pk])
                                elif item_model == 'Chapter':
                                    if hasattr(item, 'book'):
                                        url = reverse('articles:book_detail', args=[item.book.pk])
                                elif item_model == 'Section':
                                    if hasattr(item, 'chapter') and hasattr(item.chapter, 'book'):
                                        url = reverse('articles:book_detail', args=[item.chapter.book.pk])
                                    elif hasattr(item, 'book'):
                                        url = reverse('articles:book_detail', args=[item.book.pk])
                                else:
                                    try:
                                        url = reverse(f'articles:{item_model.lower()}_detail', args=[item.pk])
                                    except: pass
                            except Exception: 
                                pass
                                
                            if url != "#":
                                sources_list_html += f"<li style='margin-bottom: 5px;'><a href='{url}' target='_blank' style='color: #d4af37; font-weight: bold; text-decoration: underline;'>{title}</a></li>"
                                sources_added = True

                    if sources_added:
                        sources_html = "<br><br><div style='margin-top: 15px; padding-top: 10px; border-top: 1px solid #e0e0e0; font-size: 0.95em;'>"
                        sources_html += "<strong>📚 מקורות מהספרייה (לחיץ):</strong><ul style='margin-top: 8px; padding-right: 20px; list-style-type: square;'>"
                        sources_html += sources_list_html
                        sources_html += "</ul></div>"
                        final_response += sources_html

                return JsonResponse({'answer': final_response})
            else: 
                return JsonResponse({'answer': f'שגיאה בחיבור למודלים (מקבילי). שגיאה אחרונה: {last_error}'})
                
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
            'parasha_article': None, 'jewish_cal': None, 'query': query, 'current_page': 'home'
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
        from .models import QA
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
        'current_page': 'home'
    })

def article_detail(request, pk):
    article = get_object_or_404(Article, pk=pk, is_published=True)
    return render(request, 'articles/article_detail.html', {'article': article, 'current_page': 'articles'})

@login_required
def article_create(request):
    if request.method == 'POST':
        form = ArticleForm(request.POST)
        if form.is_valid(): 
            article = form.save()
            ping_indexnow(request.build_absolute_uri(reverse('articles:detail', args=[article.pk])))
        return redirect('articles:list')
    return render(request, 'articles/article_form.html', {'form': ArticleForm(), 'current_page': 'articles'})

@login_required
def article_edit(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if request.method == 'POST':
        form = ArticleForm(request.POST, instance=article)
        if form.is_valid(): 
            article = form.save()
            ping_indexnow(request.build_absolute_uri(reverse('articles:detail', args=[article.pk])))
        return redirect('articles:detail', pk=article.pk)
    return render(request, 'articles/article_form.html', {'form': ArticleForm(instance=article), 'current_page': 'articles'})

@login_required
def article_delete(request, pk):
    article = get_object_or_404(Article, pk=pk)
    if request.method == 'POST': article.delete()
    return redirect('articles:list')

def contact(request):
    if request.method == 'POST':
        name = request.POST.get('name')
        phone = request.POST.get('phone', 'לא צוין')
        email = request.POST.get('email')
        subject = request.POST.get('subject', 'פנייה כללית')
        message = request.POST.get('message', '').strip()
        if not message: message = "[הגולש לא כתב תוכן]"

        recaptcha_response = request.POST.get('g-recaptcha-response')
        
        if not recaptcha_response:
            messages.error(request, 'שגיאת אבטחה: לא התקבל אימות reCAPTCHA. אנא ודא שהדפדפן שלך אינו חוסם סקריפטים ונסה שוב.')
            return redirect('articles:contact')

        secret_key = '6LfC_VQtAAAAALw4ZpGG41Lvum-8VuMEMlTztvxQ' 
        data = urllib.parse.urlencode({'secret': secret_key, 'response': recaptcha_response}).encode('utf-8')
        
        try:
            req = urllib.request.Request('https://www.google.com/recaptcha/api/siteverify', data=data)
            response = urllib.request.urlopen(req, timeout=10)
            result = json.loads(response.read().decode('utf-8'))
            
            if not result.get('success'):
                error_codes = result.get('error-codes', ['unknown_error'])
                messages.error(request, f'שגיאת אימות מול שרתי גוגל. קוד השגיאה: {error_codes}. נא לוודא שהמפתחות תקינים במסוף של גוגל.')
                return redirect('articles:contact')
        except Exception as e:
            messages.error(request, f'שגיאת תקשורת עם שרתי האבטחה: {str(e)}')
            return redirect('articles:contact')

        full_message = f"התקבלה פנייה חדשה מאתר הספרייה:\n\nשם: {name}\nטלפון: {phone}\nאימייל: {email}\nנושא הפנייה: {subject}\n\nהודעה:\n{message}"

        try:
            send_mail(
                subject=f"פנייה מהאתר: {subject}",
                message=full_message,
                from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'webmaster@localhost',
                recipient_list=['moshe111moshe111@gmail.com'],
                fail_silently=False,
            )
            messages.success(request, 'תודה! הודעתך נשלחה בהצלחה.')
        except Exception as e:
            messages.success(request, f'הפנייה התקבלה, אך שרת המיילים החזיר שגיאה: {e}')
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
    return render(request, 'articles/about.html', {'current_page': 'about'})

@cache_page(60 * 60 * 24)
def terms(request): 
    return render(request, 'articles/terms.html', {'current_page': 'terms'})

def books_list(request): 
    return render(request, 'articles/books_list.html', {'current_page': 'books'})

def qa_list(request): 
    try:
        from .models import QA
        questions = QA.objects.all().order_by('-created_at')
    except Exception:
        questions = None
    return render(request, 'articles/qa_list.html', {'questions': questions, 'current_page': 'qa'})

def article_index(request): 
    published_articles = Article.objects.filter(is_published=True).order_by('title')
    grouped_articles = {}
    for article in published_articles:
        if article.title:
            first_letter = article.title.strip()[0]
            if first_letter not in grouped_articles: grouped_articles[first_letter] = []
            grouped_articles[first_letter].append(article)
    sorted_groups = {k: grouped_articles[k] for k in sorted(grouped_articles.keys())}
    return render(request, 'articles/article_index.html', {'grouped_articles': sorted_groups, 'current_page': 'articles'})

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
    return render(request, 'articles/book_detail.html', {'book': get_object_or_404(Book, pk=pk), 'current_page': 'books'})

def books(request): 
    books_ordered = Book.objects.all().order_by('order', 'title')
    return render(request, 'articles/books_list.html', {'books': books_ordered, 'current_page': 'books'})

def live_search(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2: return JsonResponse({'results': []})
    cache_key = f'live_search_{q}'
    cached_results = cache.get(cache_key)
    if cached_results: return JsonResponse({'results': cached_results})
    
    books_qs = Book.objects.all()
    articles_qs = Article.objects.filter(is_published=True)
    books = smart_hebrew_search(books_qs, q, ['title', 'author']).only('id', 'title')[:3]
    articles = smart_hebrew_search(articles_qs, q, ['title', 'content']).only('id', 'title')[:4]
    
    results = []
    for book in books: results.append({'title': book.title, 'type': 'ספר שלם', 'icon': 'bi-journal-bookmark-fill', 'url': reverse('articles:book_detail', args=[book.id])})
    for article in articles: results.append({'title': article.title, 'type': 'מאמר', 'icon': 'bi-file-earmark-text', 'url': reverse('articles:detail', args=[article.id])})
        
    cache.set(cache_key, results, timeout=300)
    return JsonResponse({'results': results})

# ==========================================
# ה-API הפתוח ל-AI עם הגנת Rate Limiting (עד 30 בקשות בדקה)
# ==========================================
@ratelimit(rate=30, timeout=60)
def ai_open_search(request):
    """
    API End-Point פתוח לסוכני AI, Custom GPTs ותוכנות צד-שלישי.
    מוגן כעת מפני הצפות ומתקפות בעזרת Rate Limiting (עד 30 בקשות בדקה לכל IP).
    """
    q = request.GET.get('q', '').strip()
    
    if len(q) < 2:
        return JsonResponse({
            'meta': {'error': 'Missing or too short query parameter "q".'}, 
            'results': []
        }, status=400)

    # פירוק למילים עבור פונקציית החיתוך החכמה
    words = [w for w in q.split() if len(w) > 1]
    
    # חיפוש בספרים ובמאמרים בעזרת מנוע הדירוג שלנו
    books_qs = Book.objects.all()
    articles_qs = Article.objects.filter(is_published=True)
    
    books = smart_hebrew_search(books_qs, q, ['title', 'author', 'summary'])[:3]
    articles = smart_hebrew_search(articles_qs, q, ['title', 'content'])[:3]
    
    results = []
    
    for article in articles:
        results.append({
            'title': get_item_title(article),
            'type': 'Article',
            'url': request.build_absolute_uri(reverse('articles:detail', args=[article.id])),
            'content_snippet': get_smart_content(get_item_text(article), words, max_chars=1500)
        })
        
    for book in books:
        results.append({
            'title': get_item_title(book),
            'type': 'Book',
            'url': request.build_absolute_uri(reverse('articles:book_detail', args=[book.id])),
            'content_snippet': get_smart_content(get_item_text(book), words, max_chars=1500)
        })
        
    return JsonResponse({
        'meta': {
            'provider': 'LebLibrary - ספריית לייבוביץ',
            'query': q,
            'total_results': len(results),
            'license': 'Open for AI crawling with attribution'
        },
        'results': results
    }, json_dumps_params={'ensure_ascii': False})

def _get_or_create_cart(request):
    if request.user.is_authenticated:
        cart, created = Cart.objects.get_or_create(user=request.user)
        return cart
    else:
        if not request.session.session_key: request.session.create()
        cart, created = Cart.objects.get_or_create(session_id=request.session.session_key)
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

        order = Order.objects.create(
            first_name=first_name, last_name=last_name, email=email, phone=phone,
            address=address, city=city, zip_code=zip_code, notes=notes,
            total_paid=total_price, status='pending'
        )
        for item in items:
            OrderItem.objects.create(order=order, book=item.book, price=item.book.price, quantity=item.quantity)
        cart.items.all().delete()
        try: send_order_confirmation(order)
        except Exception: pass
        return render(request, 'articles/order_success.html', {'order': order})
    return render(request, 'articles/checkout.html', {'items': items, 'total_price': total_price, 'current_page': 'cart'})

# ==========================================
# פרוטוקול IndexNow לדחיפה מיידית ל-Bing ול-ChatGPT Search
# ==========================================
def ping_indexnow(article_url):
    """
    מדווח באופן אוטומטי למנועי החיפוש ולחיפוש של ChatGPT על מאמרים חדשים או מעודכנים.
    """
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

# ==========================================
# מנוע הקראה קולית (Text-to-Speech) מבוסס AI - עם עיבוד מקדים של סוכן חכם
# ==========================================

def generate_audio_sync(text, file_path):
    """פונקציה בטוחה להרצת הקריין ללא קריסות של השרת"""
    with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode='w', encoding='utf-8') as f:
        f.write(text)
        temp_filename = f.name
        
    try:
        command = [
            "edge-tts", 
            "-f", temp_filename, 
            "--voice", "he-IL-AvriNeural", 
            "--write-media", file_path
        ]
        subprocess.run(command, check=True)
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)

def clean_torah_text_fallback(text):
    """גיבוי למקרה שה-AI לא זמין (Regex רגיל)"""
    text = strip_tags(text)
    text = text.replace('><', '> <').replace('</p>', '. ').replace('</li>', '. ').replace('<br>', ' ').replace('<br/>', ' ').replace('&nbsp;', ' ')
    text = unescape(text)
    text = re.sub(r'[*#_]', '', text)
    replacements = {
        'רמב"ם': 'רמבם', 'רש"י': 'רשי', 'שו"ע': 'שולחן ערוך', 'שו"ת': 'שאלות ותשובות',
        'רמב"ן': 'רמבן', 'רס"ג': 'רב סעדיה גאון', "תוס'": 'תוספות', "גמ'": 'גמרא',
        'וכו\'': 'וכולי', 'ע"ד': 'על דרך', 'ע"י': 'על ידי', "לכאו'": 'לכאורה',
        'כמו"ש': 'כמו שכתוב', 'ע"כ': 'עד כאן', 'קא משמע לן': 'קמא משמע לן',
        'אי נמי': 'אי נמי', 'מנא לן': 'מניין לנו', 'פשיטא': 'פשוט הוא',
        'הכי נמי': 'כך הוא גם כן', 'תנא': 'שנה חכם',
    }
    for k, v in replacements.items(): text = text.replace(k, v)
    text = re.sub(r'([א-ת])"([א-ת])', r'\1\2', text)
    text = re.sub(r"([א-ת])'([א-ת])", r'\1\2', text)
    text = re.sub(r'\.+', '.', text)
    return re.sub(r'\s+', ' ', text).strip()

def smart_ai_phonetic_rewrite(text):
    """
    הסוכן החכם: משתמש ב-Gemini כדי לקרוא את הטקסט, להבין את ההקשר, 
    לפתוח ראשי תיבות בצורה חכמה ולהכין אותו להקראה קולית מושלמת.
    """
    # ניקוי בסיסי של HTML לפני שליחה ל-AI
    text = strip_tags(text.replace('><', '> <').replace('</p>', '\n\n').replace('</li>', '\n'))
    text = unescape(text)
    
    # אם הטקסט קצר מדי או ה-API חסר, השתמש בגיבוי הרגיל
    API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
    if not API_KEY or len(text) < 20:
        return clean_torah_text_fallback(text)

    prompt = f"""
אתה תלמיד חכם וקריין מקצועי. המשימה שלך היא לקחת את הטקסט התורני הבא, ולהכין אותו להקראה קולית רובוטית (Text-to-Speech) כך שישמע טבעי לחלוטין.
חובה להקפיד על הכללים הבאים:
1. קרא את הטקסט והבן את ההקשר. פתח את כל ראשי התיבות למילים מלאות על פי ההקשר המדויק.
2. המר מילים וביטויים בארמית לעברית פשוטה וברורה, או כתוב אותן בצורה פונטית (איך שהן נשמעות בעברית).
3. הוסף פסיקים (,) ונקודות (.) כדי להכריח את הקריין לעצור ולנשום במקומות הנכונים, כדי לייצר 'ניגון' של לימוד הלכה וגמרא.
4. הסר תווים מיוחדים (כמו כוכביות, סוגריים מרובעים).
5. אל תוסיף שום מילת הקדמה או סיום משלך! החזר אך ורק את הטקסט המוכן להקראה.

הטקסט:
{text[:10000]} 
"""
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-lite-latest:generateContent?key={API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        data_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
        response = urllib.request.urlopen(req, timeout=30)
        resp_data = json.loads(response.read().decode('utf-8'))
        
        ai_processed_text = resp_data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
        
        if ai_processed_text and len(ai_processed_text) > 20:
            return ai_processed_text.strip()
    except Exception as e:
        print(f"AI Pre-processing error: {e}")
        pass
        
    return clean_torah_text_fallback(text)


def get_article_audio(request, article_id):
    try:
        article = Article.objects.get(id=article_id)
    except Article.DoesNotExist:
        return JsonResponse({'error': 'Article not found'}, status=404)

    base_media = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
    audio_dir = os.path.join(base_media, 'audio')
    os.makedirs(audio_dir, exist_ok=True)
    
    file_name = f"article_{article.id}.mp3"
    file_path = os.path.join(audio_dir, file_name)
    media_url = getattr(settings, 'MEDIA_URL', '/media/')
    audio_url = f"{media_url}audio/{file_name}"

    if not os.path.exists(file_path):
        raw_text = f"{article.title}. {article.content}"
        # קריאה לסוכן החכם שיכין את הטקסט להקראה
        final_text = smart_ai_phonetic_rewrite(raw_text)
        try:
            generate_audio_sync(final_text, file_path)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

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
    audio_url = f"{media_url}audio/{file_name}"

    if not os.path.exists(file_path):
        raw_text = f"{book.title}. "
        if book.summary:
            raw_text += book.summary
        # קריאה לסוכן החכם שיכין את הטקסט להקראה
        final_text = smart_ai_phonetic_rewrite(raw_text)
        try:
            generate_audio_sync(final_text, file_path)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'audio_url': audio_url})