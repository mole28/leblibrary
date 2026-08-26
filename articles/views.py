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
from html import unescape
from functools import wraps

from django.http import JsonResponse, HttpResponse, StreamingHttpResponse
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
# שיפור בטוח מס' 1: הוספת transaction לייבוא
from django.db import models, transaction
from django.utils.html import strip_tags

from .forms import ArticleForm
from .models import Article, Book, Chapter, Section, Cart, CartItem, Order, OrderItem, TorahText, QA, Acronym
from .emails import send_order_confirmation
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .vector_store import search_similar_articles

def get_base_schema_json():
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": "LebLibrary - ספריית לייבוביץ",
        "alternateName": ["ספריית לייבוביץ", "משה לייבוביץ", "משה ליבוביץ"],
        "url": "https://leblibrary.co.il",
        "author": {
            "@type": "Person",
            "name": "משה לייבוביץ",
            "alternateName": "Moshe Leibowitz"
        },
        "founder": {
            "@type": "Person",
            "name": "משה לייבוביץ"
        },
        "description": "ספריית לייבוביץ - מאמרים, ספרים ושיעורים תורניים בעריכת משה לייבוביץ."
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
                        'error': 'Rate limit exceeded. Maximum 30 requests per minute allowed.',
                        'retry_after_seconds': timeout
                    },
                    'results': []
                }, status=429)
            
            history.append(now)
            cache.set(cache_key, history, timeout)
            
            return view_func(request, *args, **kwargs)
        return _wrapped_view
    return decorator

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
            
            if not user_question: return JsonResponse({'answer': 'Please provide a question.'})

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
                - מילון ראשי תיבות: /acronyms/
                """
                prompt = f"אתה עוזר וירטואלי חייכן ומסביר פנים באתר 'ספריית לייבוביץ'. עזור לגולש לנווט באתר.\n{nav_context}\nהגולש שואל אותך: '{user_question}'\nחובה עליך לשלב קישור בפורמט מרקדאון עם הנתיב היחסי."
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
                except Exception: pass
                    
                chapter_fields = get_text_fields(Chapter)
                db_chapters = []
                try:
                    if chapter_fields:
                        db_chapters = ai_document_search(Chapter.objects.all(), clean_question, chapter_fields, words, limit=3)
                except Exception: pass
                
                section_fields = get_text_fields(Section)
                db_sections = []
                try:
                    if section_fields:
                        db_sections = ai_document_search(Section.objects.all(), clean_question, section_fields, words, limit=2)
                except Exception: pass

                # --- חיפוש במאגר שאלות ותשובות (QA) ---
                qa_fields = get_text_fields(QA)
                db_qas = []
                try:
                    if qa_fields:
                        db_qas = ai_document_search(QA.objects.all(), clean_question, qa_fields, words, limit=2)
                except Exception: pass
                # -------------------------------------

                acronym_matches = []
                try:
                    from .models import Acronym
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
                    url = request.build_absolute_uri(reverse('articles:detail', args=[a.id]))
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
                    except Exception: pass
                    
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
                    except Exception: pass

                # --- הזרקת תוצאות השו"ת למוח של הבוט ---
                for qa_item in db_qas:
                    try:
                        url = request.build_absolute_uri(reverse('articles:qa'))
                        title = f"שו\"ת - {get_item_title(qa_item)}"
                        snippet = get_smart_content(get_item_text(qa_item), words, max_chars=8000)
                        add_to_context(title, url, snippet)
                    except Exception: pass
                # --------------------------------------

                if not unique_relevant_items:
                    return JsonResponse({'answer': 'מצטער, לא הצלחתי לאתר חומרים רלוונטיים במאגרי הספרייה לשאלתך. נסה לנסח אחרת.'})

                prompt = f"""אתה רב מומחה ופוסק הלכה באתר 'ספריית לייבוביץ'.
הגולש שואל אותך: '{user_question}'

המערכת ביצעה חיפוש והביאה לך טקסטים מתוך ספרי ומאמרי הספרייה (חלקם עלולים להיות לא רלוונטיים - התעלם מהם לחלוטין).
קרא את המקורות לעומק. אם התשובה לשאלה נמצאת בהם:
1. ענה בצורה מדויקה, מפורטת ומכובדת, ללא צירוף ידע חיצוני.
2. חובה לציין במפורש את שמו של המקור שעליו הסתמכת (מתוך שדה ה'כותרת'). ציון הכותרת הוא קריטי כדי שהמערכת תציג לגולש קישור.
3. אל תציין שהמידע חלקי או שחסר לך רקע - פשוט ענה את ההלכה המצויה במקור.

אם התשובה אינה מופיעה באף אחד מהמקורות (גם לא במרומז), חובה עליך להשיב בדיוק במילים אלו: "מצטער, לא מצאתי לכך התייחסות במקורות שנסרקו בספרייה."

מקורות שנסרקו:
{context_text}"""
            
            def stream_google_response():
                KNOWN_GOOD_MODELS = [
                    'gemini-1.5-flash-latest',
                    'gemini-1.5-pro-latest',
                    'gemini-flash-lite-latest',
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
        'current_page': 'home',
        'schema_json_ld': get_base_schema_json()
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
    return render(request, 'articles/about.html', {'current_page': 'about', 'schema_json_ld': get_base_schema_json()})

@cache_page(60 * 60 * 24)
def terms(request): 
    return render(request, 'articles/terms.html', {'current_page': 'terms'})

def books_list(request): 
    return render(request, 'articles/books_list.html', {'current_page': 'books'})

def qa_list(request): 
    try:
        from .models import QA
        from django.db.models import Q
        
        questions = QA.objects.all().order_by('-created_at')
        
        # משיכת כל הקטגוריות הקיימות במסד הנתונים (ללא כפילויות וללא ריקים)
        categories = QA.objects.exclude(category__isnull=True).exclude(category__exact='').values_list('category', flat=True).distinct()
        
        # טיפול בחיפוש טקסט חופשי (מתיבת החיפוש)
        q = request.GET.get('q')
        if q:
            questions = questions.filter(Q(question__icontains=q) | Q(answer__icontains=q))
            
        # טיפול בסינון לפי קטגוריה (מלחיצה על התפריט בצד)
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
    from .models import Acronym
    query = request.GET.get('q', '').strip()
    
    # === נרמול חיפוש ראשי תיבות ===
    query = re.sub(r'["״”“]', '"', query)
    query = re.sub(r'[\'׳`]', "'", query)
    # ============================
    
    search_type = request.GET.get('type', 'short') # 'short' עבור ראשי תיבות, 'meaning' עבור פירוש/מילים
    acronyms = None
    if query:
        if search_type == 'meaning':
            acronyms = Acronym.objects.filter(meaning__icontains=query).order_by('short')
        else:
            acronyms = Acronym.objects.filter(short__icontains=query).order_by('short')
    else:
        acronyms = Acronym.objects.all().order_by('short')[:100]
    return render(request, 'articles/acronyms.html', {'acronyms': acronyms, 'query': query, 'search_type': search_type, 'current_page': 'acronyms'})

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

@ratelimit(rate=30, timeout=60)
def ai_open_search(request):
    q = request.GET.get('q', '').strip()
    
    if len(q) < 2:
        return JsonResponse({
            'meta': {'error': 'Missing or too short query parameter "q".'}, 
            'results': []
        }, status=400)

    words = [w for w in q.split() if len(w) > 1]
    
    books_qs = Book.objects.all()
    articles_qs = Article.objects.filter(is_published=True)
    
    semantic_results = search_similar_articles(q, top_k=3)
    results = []
    
    if semantic_results:
        for item in semantic_results:
            results.append({
                'title': item['title'],
                'type': 'Article',
                'url': request.build_absolute_uri(item['url']),
                'content_snippet': item['content_snippet']
            })
    else:
        books = smart_hebrew_search(books_qs, q, ['title', 'author', 'summary'])[:3]
        articles = smart_hebrew_search(articles_qs, q, ['title', 'content'])[:3]
        
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
            'provider': 'LebLibrary - ספריית לייבוביץ בניהולו של משה לייבוביץ',
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

        # שיפור בטוח מס' 2: הוספת הגנת מסד נתונים שלמה לתהליך ההזמנה
        with transaction.atomic():
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
        except Exception as e:
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
            raw_text = f"{article.title}. {article.content}"
            final_text = apply_tts_dictionary(raw_text)
            generate_audio_sync(final_text, file_path)
    except Exception:
        pass

@receiver(post_save, sender=Article)
def trigger_article_audio_pregeneration(sender, instance, created, **kwargs):
    if instance.is_published:
        # שיפור בטוח מס' 3: שימוש ב-on_commit כדי למנוע קריסה של תהליכון
        transaction.on_commit(lambda: threading.Thread(target=generate_article_audio_background, args=(instance.id,)).start())

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
        final_text = apply_tts_dictionary(raw_text)
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
            
        final_text = apply_tts_dictionary(raw_text)
        try:
            generate_audio_sync(final_text, file_path)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    return JsonResponse({'audio_url': audio_url})

def search_acronyms_api(request):
    query = request.GET.get('q', '').strip()
    
    # --- התיקון: נרמול החיפוש לראשי תיבות ---
    query = re.sub(r'["״”“]', '"', query)
    query = re.sub(r'[\'׳`]', "'", query)
    # ----------------------------------------
    
    search_type = request.GET.get('type', 'short') # 'short' עבור ראשי תיבות, 'meaning' עבור פירוש/מילים
    
    results = []
    if len(query) >= 1:
        if search_type == 'meaning':
            matches = Acronym.objects.filter(meaning__icontains=query)[:10]
        else:
            matches = Acronym.objects.filter(short__icontains=query)[:10]
            
        for item in matches:
            results.append({
                'short': item.short,
                'meaning': item.meaning
            })
            
    return JsonResponse({'results': results})

# ==========================================
# תצוגת מנוע החיפוש המתקדם (Advanced Search)
# ==========================================
def advanced_search_view(request):
    return render(request, 'articles/advanced_search.html', {'current_page': 'advanced_search'})


# ==========================================
# אלגוריתמי עזר לחיפוש תורני (גימטריה, ראשי תיבות וכו')
# ==========================================
HEBREW_GEMATRIA = {
    'א': 1, 'ב': 2, 'ג': 3, 'ד': 4, 'ה': 5, 'ו': 6, 'ז': 7, 'ח': 8, 'ט': 9,
    'י': 10, 'כ': 20, 'ך': 20, 'ל': 30, 'מ': 40, 'ם': 40, 'נ': 50, 'ן': 50,
    'ס': 60, 'ע': 70, 'פ': 80, 'ף': 80, 'צ': 90, 'ץ': 90,
    'ק': 100, 'ר': 200, 'ש': 300, 'ת': 400
}

def calculate_gematria(text):
    return sum(HEBREW_GEMATRIA.get(char, 0) for char in text)

MISHNAH_BOOKS = [
    'ברכות', 'פאה', 'דמאי', 'כלאים', 'שביעית', 'תרומות', 'מעשרות', 'מעשר שני', 'חלה', 'ערלה', 'ביכורים',
    'שבת', 'עירובין', 'פסחים', 'שקלים', 'יומא', 'סוכה', 'ביצה', 'ראש השנה', 'תענית', 'מגילה', 'מועד קטן', 'חגיגה',
    'יבמות', 'כתובות', 'נדרים', 'נזיר', 'סוטה', 'גיטין', 'קידושין',
    'בבא קמא', 'בבא מציעא', 'בבא בתרא', 'סנהדרין', 'מכות', 'שבועות', 'עדיות', 'עבודה זרה', 'אבות', 'הוריות',
    'זבחים', 'מנחות', 'חולין', 'בכורות', 'ערכין', 'תמורה', 'כריתות', 'מעילה', 'תמיד', 'מדות', 'קינים',
    'כלים', 'אהלות', 'נגעים', 'פרה', 'טהרות', 'מקואות', 'נדה', 'מכשירין', 'זבים', 'טבול יום', 'ידים', 'עוקצין'
]

def get_book_order(book_name):
    BOOK_ORDER = {
        'בראשית': 1, 'שמות': 2, 'ויקרא': 3, 'במדבר': 4, 'דברים': 5,
        'יהושע': 6, 'שופטים': 7, 'שמואל א': 8, 'שמואל ב': 9, 'מלכים א': 10, 'מלכים ב': 11,
        'ישעיהו': 12, 'ירמיהו': 13, 'יחזקאל': 14, 'הושע': 15, 'יואל': 16, 'עמוס': 17, 'עובדיה': 18,
        'יונה': 19, 'מיכה': 20, 'נחום': 21, 'חבקוק': 22, 'צפניה': 23, 'חגי': 24, 'זכריה': 25, 'מלאכי': 26,
        'תהילים': 27, 'משלי': 28, 'איוב': 29, 'שיר השירים': 30, 'רות': 31, 'איכה': 32, 'קהלת': 33,
        'אסתר': 34, 'דניאל': 35, 'עזרא': 36, 'נחמיה': 37, 'דברי הימים א': 38, 'דברי הימים ב': 39,
        # סדר זרעים
        'ברכות': 40, 'פאה': 41, 'דמאי': 42, 'כלאים': 43, 'שביעית': 44, 'תרומות': 45, 'מעשרות': 46, 'מעשר שני': 47, 'חלה': 48, 'ערלה': 49, 'ביכורים': 50,
        # סדר מועד
        'שבת': 51, 'עירובין': 52, 'פסחים': 53, 'שקלים': 54, 'יומא': 55, 'סוכה': 56, 'ביצה': 57, 'ראש השנה': 58, 'תענית': 59, 'מגילה': 60, 'מועד קטן': 61, 'חגיגה': 62,
        # סדר נשים
        'יבמות': 63, 'כתובות': 64, 'נדרים': 65, 'נזיר': 66, 'סוטה': 67, 'גיטין': 68, 'קידושין': 69,
        # סדר נזיקין
        'בבא קמא': 70, 'בבא מציעא': 71, 'בבא בתרא': 72, 'סנהדרין': 73, 'מכות': 74, 'שבועות': 75, 'עדיות': 76, 'עבודה זרה': 77, 'אבות': 78, 'הוריות': 79,
        # סדר קדשים
        'זבחים': 80, 'מנחות': 81, 'חולין': 82, 'בכורות': 83, 'ערכין': 84, 'תמורה': 85, 'כריתות': 86, 'מעילה': 87, 'תמיד': 88, 'מדות': 89, 'קינים': 90,
        # סדר טהרות
        'כלים': 91, 'אהלות': 92, 'נגעים': 93, 'פרה': 94, 'טהרות': 95, 'מקואות': 96, 'נדה': 97, 'מכשירין': 98, 'זבים': 99, 'טבול יום': 100, 'ידים': 101, 'עוקצין': 102
    }
    return BOOK_ORDER.get(book_name.strip(), 999)

def safe_int(v):
    try:
        return int(v)
    except:
        return 0

def highlight_matched_text(text_with_nikkud, query_words, is_exact):
    """מוסיף תגיות הדגשה <mark> למילים שנמצאו בתוך הטקסט המנוקד"""
    highlighted = text_with_nikkud
    
    NIKKUD_CORE = r'\u0591-\u05BD\u05BF\u05C1\u05C2\u05C4\u05C5\u05C7'
    NIKKUD = f'[{NIKKUD_CORE}]'
    
    for w in query_words:
        chars = []
        for char in w:
            chars.append(re.escape(char) + NIKKUD + '*')
        word_with_optional_nikkud = ''.join(chars)
        
        if is_exact:
            pattern_str = rf'(^|[^א-ת{NIKKUD_CORE}])({word_with_optional_nikkud})(?=[^א-ת{NIKKUD_CORE}]|$)'
            try:
                pattern = re.compile(pattern_str, re.UNICODE)
                highlighted = pattern.sub(r'\1<mark>\2</mark>', highlighted)
            except Exception:
                pass
        else:
            pattern_str = rf'[משהוכלבאיתנד]{{0,4}}{word_with_optional_nikkud}{NIKKUD}*[א-ת]{{0,4}}'
            try:
                pattern = re.compile(f'({pattern_str})', re.UNICODE)
                highlighted = pattern.sub(r'<mark>\1</mark>', highlighted)
            except Exception:
                pass
                
    return highlighted

@ratelimit(rate=30, timeout=60)
def tanakh_advanced_search_api(request):
    query_type = request.GET.get('type', 'text')
    query_val = request.GET.get('q', '').strip()
    book_filter = request.GET.get('book', '').strip()
    is_exact = request.GET.get('exact', 'false') == 'true'
    exclude_books_param = request.GET.get('exclude_books', '').strip()
    page = int(request.GET.get('page', 1))
    
    try:
        per_page = int(request.GET.get('per_page', 10))
        if per_page not in [10, 20, 50, 100]:
            per_page = 10
    except ValueError:
        per_page = 10
    
    results = []
    qs = TorahText.objects.all()

    # פתרון מוחלט: סינון מבוסס Q object שבודק את כל שמות מסכתות המשנה במסד הנתונים
    tanakh_names = ['בראשית', 'שמות', 'ויקרא', 'במדבר', 'דברים', 'יהושע', 'שופטים', 'שמואל א', 'שמואל ב', 'מלכים א', 'מלכים ב', 'ישעיהו', 'ירמיהו', 'יחזקאל', 'הושע', 'יואל', 'עמוס', 'עובדיה', 'יונה', 'מיכה', 'נחום', 'חבקוק', 'צפניה', 'חגי', 'זכריה', 'מלאכי', 'תהילים', 'משלי', 'איוב', 'שיר השירים', 'רות', 'איכה', 'קהלת', 'אסתר', 'דניאל', 'עזרא', 'נחמיה', 'דברי הימים א', 'דברי הימים ב']

    if book_filter == 'torah':
        qs = qs.filter(book__in=['בראשית', 'שמות', 'ויקרא', 'במדבר', 'דברים'])
    elif book_filter == 'mishnah':
        mishnah_q = Q()
        for m_name in MISHNAH_BOOKS:
            mishnah_q |= Q(book__icontains=m_name)
        qs = qs.filter(mishnah_q)
    elif book_filter == 'tanakh':
        tanakh_q = Q()
        for t_name in tanakh_names:
            tanakh_q |= Q(book__icontains=t_name)
        qs = qs.filter(tanakh_q)
    elif book_filter == 'all':
        pass 
    elif book_filter:
        qs = qs.filter(book__icontains=book_filter)
        
    if exclude_books_param:
        excluded = [b.strip() for b in exclude_books_param.split(',') if b.strip()]
        for ex in excluded:
            qs = qs.exclude(book__icontains=ex)

    try:
        if query_type == 'text' and query_val:
            q_no_nikkud = re.sub(r'[^א-ת\s]', '', query_val)
            q_words = q_no_nikkud.split()
            
            if q_words:
                num_q_words = len(q_words)
                
                all_verses = qs.values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')
                
                for m in all_verses:
                    t_clean = m.get('clean_text') or ""
                    if not t_clean:
                        t = m.get('text_with_nikkud') or ""
                        t_no_nikkud = re.sub(r'[\u0591-\u05C7]', '', t)
                        t_clean = " ".join(re.sub(r'[^א-ת\s]', ' ', t_no_nikkud).split())
                    
                    v_words = t_clean.split()
                    v_words_clean_only = [re.sub(r'[\u0591-\u05C7]', '', vw) for vw in v_words]
                    is_match = False
                    
                    if num_q_words == 1:
                        target_w = q_words[0]
                        for idx, vw_clean in enumerate(v_words_clean_only):
                            if is_exact:
                                if vw_clean == target_w:
                                    is_match = True
                                    break
                            else:
                                if target_w in vw_clean:
                                    is_match = True
                                    break
                    else:
                        for i in range(len(v_words_clean_only) - num_q_words + 1):
                            matched_sequence = True
                            for j in range(num_q_words):
                                target_w = q_words[j]
                                current_vw = v_words_clean_only[i + j]
                                if is_exact:
                                    if current_vw != target_w:
                                        matched_sequence = False
                                        break
                                else:
                                    if target_w not in current_vw:
                                        matched_sequence = False
                                        break
                            if matched_sequence:
                                is_match = True
                                break
                            
                    if is_match:
                        raw_text = m['text_with_nikkud']
                        highlighted_text = highlight_matched_text(raw_text, q_words, is_exact)
                        is_mishnah_res = not any(t_name in m['book'] for t_name in tanakh_names)
                        
                        results.append({
                            'book': m['book'],
                            'chapter': m['chapter'],
                            'verse': m['verse'],
                            'verse_label': 'משנה' if is_mishnah_res else 'פסוק',
                            'text': highlighted_text,
                            'match_type': 'מילה מדויקת' if is_exact else 'חיפוש רחב'
                        })
                
        elif query_type == 'gematria' and query_val.isdigit():
            target_val = int(query_val)
            all_verses = qs.values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')
            for m in all_verses:
                t = m.get('clean_text') or m.get('text_with_nikkud') or ""
                t_clean = re.sub(r'[^א-ת\s]', ' ', t)
                t_words = t_clean.split()
                
                is_mishnah_res = not any(t_name in m['book'] for t_name in tanakh_names)
                clean_t = "".join(t_words)
                if calculate_gematria(clean_t) == target_val:
                    results.append({
                        'book': m['book'],
                        'chapter': m['chapter'],
                        'verse': m['verse'],
                        'verse_label': 'משנה' if is_mishnah_res else 'פסוק',
                        'text': m['text_with_nikkud'],
                        'match_type': 'גימטריה מלאה לפסוק'
                    })
                else:
                    found_word = False
                    for w in t_words:
                        if calculate_gematria(w) == target_val:
                            found_word = True
                            break
                    if found_word:
                        results.append({
                            'book': m['book'],
                            'chapter': m['chapter'],
                            'verse': m['verse'],
                            'verse_label': 'משנה' if is_mishnah_res else 'פסוק',
                            'text': m['text_with_nikkud'],
                            'match_type': f'גימטריה למילה בפסוק (ערך {target_val})'
                        })
                    
        elif query_type == 'acronym' and query_val:
            target_acr = re.sub(r'[^א-ת]', '', query_val)
            if target_acr:
                all_verses = qs.values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')
                for m in all_verses:
                    t = m.get('clean_text') or m.get('text_with_nikkud') or ""
                    t_clean = re.sub(r'[^א-ת\s]', ' ', t)
                    t_words = t_clean.split()
                    
                    is_mishnah_res = not any(t_name in m['book'] for t_name in tanakh_names)
                    if len(t_words) >= len(target_acr):
                        initials = "".join([w[0] for w in t_words if w])
                        if target_acr in initials:
                            results.append({
                                'book': m['book'],
                                'chapter': m['chapter'],
                                'verse': m['verse'],
                                'verse_label': 'משנה' if is_mishnah_res else 'פסוק',
                                'text': m['text_with_nikkud'],
                                'match_type': 'ראשי תיבות בפסוק'
                            })

        # מיון
        results.sort(key=lambda x: (get_book_order(x['book']), safe_int(x['chapter']), safe_int(x['verse'])))

        total_results = len(results)
        total_pages = (total_results + per_page - 1) // per_page if total_results > 0 else 1
        start_idx = (page - 1) * per_page
        end_idx = start_idx + per_page
        paginated_results = results[start_idx:end_idx]

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)
        
    return JsonResponse({
        'results': paginated_results,
        'total': total_results,
        'page': page,
        'total_pages': total_pages,
        'per_page': per_page
    }, json_dumps_params={'ensure_ascii': False})