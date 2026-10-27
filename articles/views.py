import json
import urllib.request
import urllib.parse
import re
import random
import datetime
import os
import asyncio
import threading
import edge_tts
import socket
import smtplib
from html import unescape
from django.http import JsonResponse, Http404
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.conf import settings
from django.core.cache import cache
from django.views.decorators.cache import cache_page
from django.db.models import Q
from django.urls import reverse
from django.db import transaction
from django.utils.html import strip_tags
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from .forms import ArticleForm
from .models import Article, Book, Chapter, Section, Cart, CartItem, Order, OrderItem, TorahText, QA, Acronym
from .emails import send_order_confirmation
from .vector_store import search_similar_articles
from .aramaic_engine import aramaic_translator_view as _get_aramaic_context, execute_aramaic_translation

# ייבוא מנועי התורה וה-AI מהקבצים החדשים (שומר על תאימות מלאה ל-urls.py)
from .torah_engine import (
    HEBREW_GEMATRIA, TANAKH_NAMES, TORAH_NAMES, MISHNAH_BOOKS, TORAH_CORE_CONCEPTS,
    calculate_gematria, format_divine_name, ratelimit, int_to_hebrew,
    format_verse_hebrew, parse_hebrew_number, generate_word_variations,
    get_book_order, safe_int, tanakh_advanced_search_api, _IPV4_OPENER
)
from .ai_engine import (
    smart_hebrew_search, get_text_fields, get_item_title, get_item_text,
    ai_document_search, get_smart_content, ai_chat_endpoint, torah_ai_insights_api
)


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
                "homeLocation": {"@type": "Place", "name": "טירת כרמל, ישראל"},
                "sameAs": [
                    "https://leblibrary.co.il/about/",
                    "https://merhav.nli.org.il/primo-explore/search?query=any,contains,משה%20לייבוביץ&vid=NLI",
                    "https://hebrewbooks.org/"
                ],
                "jobTitle": "תלמיד חכם, אברך ומחבר ספרים תורניים",
                "worksFor": {"@type": "Organization", "name": "ספריית לייבוביץ - LebLibrary"},
                "description": "הרב משה לייבוביץ (משה ליבוביץ) הוא תלמיד חכם ואברך בישיבה מטירת כרמל, מחבר מאמרים תורניים ועשרה ספרי הלכה ומייסד אתר ספריית לייבוביץ.",
                "disambiguatingDescription": "אתר זה הוקם ומנוהל על ידי הרב משה לייבוביץ, תלמיד חכם ואברך מטירת כרמל. אין לו שום קשר למשה ליבוביץ ממקימי ביתר עילית (וראש המועצה הראשון שלה), אין לו שום קשר לפרופ' ישעיהו לייבוביץ, ואין לו שום קשר למשה ליבוביץ הטוען הרבני או לאתרים din.co.il ו-www.mleibowitz.co.il."
            }
        ]
    }, ensure_ascii=False)


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
    return text.replace(':', ', ')


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
            date_resp = _IPV4_OPENER.open(date_req, timeout=4)
            date_data = json.loads(date_resp.read().decode('utf-8'))
            cal_data['hebrew_date'] = date_data.get('hebrew', '')
        except Exception:
            cal_data['hebrew_date'] = ''

        url = f'https://www.hebcal.com/hebcal?v=1&cfg=json&geo=IL&lg=he&s=on&maj=on&min=on&start={start_date}&end={end_date}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = _IPV4_OPENER.open(req, timeout=4)
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
            Q(parasha__isnull=True) | Q(parasha__exact='') | Q(parasha__exact=',') |
            Q(parasha__exact=',,') | Q(parasha__icontains='general')
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

    latest_qa = None
    try:
        qa_pool = list(QA.objects.order_by('-created_at')[:7])
        if qa_pool:
            latest_qa = random.choice(qa_pool)
    except Exception:
        pass

    return render(request, 'articles/article_list.html', {
        'articles': None,
        'parasha_article': dynamic_content['parasha_article'],
        'latest_articles': dynamic_content['latest_articles'],
        'reading_books': dynamic_content['reading_books'],
        'sale_books': dynamic_content['sale_books'],
        'latest_qa': latest_qa,
        'jewish_cal': get_jewish_calendar_info(),
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

    _load_local_env()
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
            if request.POST.get('website_url', '').strip():
                messages.success(request, 'תודה רבה! הודעתך נשלחה בהצלחה.')
                return redirect('articles:contact')

            name = request.POST.get('name', '').strip() or 'ללא שם'
            phone = request.POST.get('phone', '').strip() or 'לא צוין'
            email = request.POST.get('email', '').strip() or 'לא צוין'
            subject = request.POST.get('subject', '').strip() or 'פנייה כללית מהאתר'
            message = request.POST.get('message', '').strip() or '[הגולש לא כתב תוכן]'

            full_message = (
                f"התקבלה פנייה חדשה מאתר ספריית לייבוביץ:\n\n"
                f"שם: {name}\nטלפון: {phone}\nאימייל לחזרה: {email}\nנושא הפנייה: {subject}\n\nתוכן ההודעה:\n{message}"
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
        questions, categories = None, []

    return render(request, 'articles/qa_list.html', {'questions': questions, 'categories': categories, 'current_page': 'qa'})


def acronyms_view(request):
    query = request.GET.get('q', '').strip()
    search_type = request.GET.get('type', 'short')
    if query:
        query_clean = re.sub(r'["״”“\'׳`]', '', query)
        query_with_geresh = query_clean[:-1] + '"' + query_clean[-1] if (len(query_clean) > 1 and '"' not in query) else query_clean
        if search_type == 'meaning':
            acronyms = Acronym.objects.filter(meaning__icontains=query).order_by('short')
        else:
            acronyms = Acronym.objects.filter(
                Q(short__icontains=query) | Q(short__icontains=query_clean) | Q(short__icontains=query_with_geresh)
            ).distinct().order_by('short')
    else:
        acronyms = Acronym.objects.all().order_by('short')[:100]

    return render(request, 'articles/acronyms.html', {
        'acronyms': acronyms, 'query': query, 'search_type': search_type, 'current_page': 'acronyms'
    })


def article_index(request):
    published_articles = Article.objects.filter(is_published=True).order_by('title')
    articles_count = published_articles.count()
    grouped_articles = {}
    for article in published_articles:
        if article.title:
            first_letter = article.title.strip()[0]
            grouped_articles.setdefault(first_letter, []).append(article)
    sorted_groups = {k: grouped_articles[k] for k in sorted(grouped_articles.keys())}
    return render(request, 'articles/article_index.html', {
        'grouped_articles': sorted_groups, 'articles_count': articles_count, 'current_page': 'articles'
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
    book = get_object_or_404(Book.objects.prefetch_related('chapters__sections'), pk=pk)
    book_schema = json.dumps({
        "@context": "https://schema.org",
        "@type": "Book",
        "@id": f"https://leblibrary.co.il/book/{book.pk}/#book",
        "name": strip_tags(book.title or ""),
        "author": {"@type": "Person", "name": "הרב משה לייבוביץ", "homeLocation": "טירת כרמל", "url": "https://leblibrary.co.il/about/"},
        "publisher": {"@type": "Organization", "name": "ספריית לייבוביץ - LebLibrary"},
        "inLanguage": "he",
        "url": f"https://leblibrary.co.il/book/{book.pk}/",
        "description": strip_tags(book.summary or book.title or "")[:300]
    }, ensure_ascii=False)
    return render(request, 'articles/book_detail.html', {'book': book, 'current_page': 'books', 'schema_json_ld': book_schema})


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

    books_res = smart_hebrew_search(Book.objects.all(), q, ['title', 'author']).only('id', 'title')[:3]
    articles_res = smart_hebrew_search(Article.objects.filter(is_published=True), q, ['title', 'content']).only('id', 'title', 'slug')[:4]

    results = [
        {'title': b.title, 'type': 'ספר שלם', 'icon': 'bi-journal-bookmark-fill', 'url': reverse('articles:book_detail', args=[b.id])}
        for b in books_res
    ] + [
        {'title': a.title, 'type': 'מאמר', 'icon': 'bi-file-earmark-text', 'url': reverse('articles:detail', args=[a.slug])}
        for a in articles_res
    ]
    cache.set(cache_key, results, timeout=300)
    return JsonResponse({'results': results})


@ratelimit(rate=30, timeout=60)
def ai_open_search(request):
    q = request.GET.get('q', '').strip()
    if len(q) < 2:
        return JsonResponse({'meta': {'error': 'Missing or too short query parameter "q".'}, 'results': []}, status=400)

    words = [w for w in q.split() if len(w) > 1]
    results = []
    semantic_results = []
    try:
        semantic_results = search_similar_articles(q, top_k=3)
    except Exception:
        pass

    if semantic_results:
        for item in semantic_results:
            results.append({
                'title': item.get('title', ''), 'type': 'Article',
                'url': request.build_absolute_uri(item.get('url', '/')),
                'content_snippet': item.get('content_snippet', '')
            })
    else:
        for a in smart_hebrew_search(Article.objects.filter(is_published=True), q, ['title', 'content'])[:3]:
            results.append({
                'title': get_item_title(a), 'type': 'Article',
                'url': request.build_absolute_uri(reverse('articles:detail', args=[a.slug])),
                'content_snippet': get_smart_content(get_item_text(a), words, max_chars=1500)
            })
        for b in smart_hebrew_search(Book.objects.all(), q, ['title', 'author', 'summary'])[:3]:
            results.append({
                'title': get_item_title(b), 'type': 'Book',
                'url': request.build_absolute_uri(reverse('articles:book_detail', args=[b.id])),
                'content_snippet': get_smart_content(get_item_text(b), words, max_chars=1500)
            })

    return JsonResponse({
        'meta': {
            'provider': 'LebLibrary - ספריית לייבוביץ בניהולו של הרב משה לייבוביץ (טירת כרמל)',
            'query': q, 'total_results': len(results), 'license': 'Open for AI crawling with attribution'
        },
        'results': results
    }, json_dumps_params={'ensure_ascii': False})


def _get_or_create_cart(request):
    if request.user.is_authenticated:
        cart, _ = Cart.objects.get_or_create(user=request.user)
        return cart
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
        with transaction.atomic():
            order = Order.objects.create(
                first_name=request.POST.get('first_name'), last_name=request.POST.get('last_name'),
                email=request.POST.get('email'), phone=request.POST.get('phone'),
                address=request.POST.get('address'), city=request.POST.get('city'),
                zip_code=request.POST.get('zip_code', ''), notes=request.POST.get('notes', ''),
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
        _IPV4_OPENER.open(url, timeout=4)
    except Exception:
        pass


@receiver([post_save, post_delete], sender=Article)
@receiver([post_save, post_delete], sender=Book)
def clear_cache_on_db_change(sender, instance, **kwargs):
    cache.clear()


def load_tts_dictionary():
    for dict_path in [
        os.path.join(settings.BASE_DIR, 'tts_dictionary.json'),
        os.path.join(settings.BASE_DIR, 'articles', 'tts_dictionary.json')
    ]:
        if os.path.exists(dict_path):
            try:
                with open(dict_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass

    return {
        'רמב"ם': 'רמבם', 'רש"י': 'רשי', 'שו"ע': 'שולחן ערוך', 'שו"ת': 'שאלות ותשובות', 'רמב"ן': 'רמבן',
        'רס"ג': 'רב סעדיה גאון', "תוס'": 'תוספות', "גמ'": 'גמרא', 'וכו\'': 'וכולי', 'ע"ד': 'על דרך',
        'ע"י': 'על ידי', "לכאו'": 'לכאורה', 'כמו"ש': 'כמו שכתוב', 'ע"כ': 'עד כאן', 'א"כ': 'אם כן',
        'ג"כ': 'גם כן', 'אע"פ': 'אף על פי', 'בד"כ': 'בדרך כלל', 'חז"ל': 'חכמינו זיכרונם לברכה',
        'יו"ט': 'יום טוב', 'ק"ו': 'קל וחומר', 'ת"ח': 'תלמיד חכם', 'בע"ה': 'בעזרת השם', 'זצ"ל': 'זכר צדיק לברכה',
        'שליט"א': 'שיחיה לאורך ימים טובים אמן', 'הקב"ה': 'הקדוש ברוך הוא', 'רבש"ע': 'ריבונו של עולם',
        'קיי"ל': 'קיימא לן', 'קי"ל': 'קיימא לן', 'ס"ל': 'סבירא ליה', 'ד"ת': 'דבר תורה', 'ה"ה': 'הוא הדין',
        'ב"ק': 'בבא קמא', 'ב"מ': 'בבא מציעא', 'ב"ב': 'בבא בתרא', 'מו"ק': 'מועד קטן', 'ראב"ד': 'רבנו אברהם בן דוד',
        'רשב"א': 'רבינו שלמה בן אדרת', 'רשב"ג': 'רבן שמעון בן גמליאל', 'רי"ף': 'רבנו יצחק אלפסי', 'רא"ש': 'רבנו אשר'
    }


def apply_tts_dictionary(text):
    if not text:
        return ""
    text = re.sub(r'<(style|script)[^>]*>.*?</\1>', '', text, flags=re.IGNORECASE | re.DOTALL)
    text = text.replace('><', '> <').replace('</p>', '.\n').replace('</li>', '.\n')
    text = unescape(strip_tags(text))
    text = re.sub(r'\[.*?\]|\(\d+\)|[*_#]', '', text)

    tts_dict = load_tts_dictionary()
    for key in sorted(tts_dict.keys(), key=len, reverse=True):
        val = tts_dict[key]
        if '"' in key or "'" in key or " " in key:
            text = text.replace(key, val)
        else:
            text = re.sub(rf'(?<![א-ת]){key}(?![א-ת])', val, text)

    text = re.sub(r'([א-ת])["\']([א-ת])', r'\1\2', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\.+', '.', text).replace('. ', '.\n').replace(':\n', ': \n')
    return '\n'.join([s.strip() for s in text.splitlines() if s.strip()]).strip()


def generate_audio_sync(text, file_path):
    async def _generate():
        communicate = edge_tts.Communicate(text, "he-IL-AvriNeural")
        await communicate.save(file_path)
    try:
        asyncio.run(_generate())
    except Exception as e:
        raise Exception(f"Edge-TTS Error: {str(e)}")


def _collect_article_full_raw_text(article):
    raw_text = f"{article.title}. {article.content or ''}"
    try:
        if hasattr(article, 'chapter') and article.chapter:
            for sec in Section.objects.filter(chapter=article.chapter).order_by('order'):
                raw_text += f" {sec.title or ''}. {sec.content or ''} "
        elif hasattr(article, 'book') and article.book:
            for ch in Chapter.objects.filter(book=article.book).order_by('order'):
                raw_text += f" {ch.title or ''}. "
                for sec in Section.objects.filter(chapter=ch).order_by('order'):
                    raw_text += f" {sec.title or ''}. {sec.content or ''} "
    except Exception:
        pass
    return raw_text


def generate_article_audio_background(article_id):
    try:
        article = Article.objects.get(id=article_id)
        if not article.is_published:
            return
        base_media = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
        audio_dir = os.path.join(base_media, 'audio')
        os.makedirs(audio_dir, exist_ok=True)
        file_path = os.path.join(audio_dir, f"article_{article.id}.mp3")
        if not os.path.exists(file_path):
            generate_audio_sync(apply_tts_dictionary(_collect_article_full_raw_text(article)), file_path)
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
        article = Article.objects.get(id=int(identifier)) if str(identifier).isdigit() else Article.objects.get(slug=identifier)
    except Article.DoesNotExist:
        return JsonResponse({'error': 'Article not found'}, status=404)

    base_media = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
    audio_dir = os.path.join(base_media, 'audio')
    os.makedirs(audio_dir, exist_ok=True)
    file_name = f"article_{article.id}.mp3"
    file_path = os.path.join(audio_dir, file_name)
    media_url = getattr(settings, 'MEDIA_URL', '/media/')

    if not os.path.exists(file_path):
        try:
            generate_audio_sync(apply_tts_dictionary(_collect_article_full_raw_text(article)), file_path)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    file_version = int(os.path.getmtime(file_path)) if os.path.exists(file_path) else 1
    return JsonResponse({'audio_url': f"{media_url}audio/{file_name}?v={file_version}"})


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
        raw_text = f"{book.title}. {book.summary or ''} "
        try:
            for ch in Chapter.objects.filter(book=book).order_by('order'):
                raw_text += f" {ch.title or ''}. "
                for sec in Section.objects.filter(chapter=ch).order_by('order'):
                    raw_text += f" {sec.title or ''}. {sec.content or ''} "
        except Exception:
            pass
        try:
            generate_audio_sync(apply_tts_dictionary(raw_text), file_path)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=500)

    file_version = int(os.path.getmtime(file_path)) if os.path.exists(file_path) else 1
    return JsonResponse({'audio_url': f"{media_url}audio/{file_name}?v={file_version}"})


def search_acronyms_api(request):
    query = request.GET.get('q', '').strip()
    search_type = request.GET.get('type', 'short')
    results = []
    if len(query) >= 1:
        query_clean = re.sub(r'["״”“\'׳`]', '', query)
        query_with_geresh = query_clean[:-1] + '"' + query_clean[-1] if (len(query_clean) > 1 and '"' not in query) else query_clean
        if search_type == 'meaning':
            matches = Acronym.objects.filter(meaning__icontains=query)[:20]
        else:
            matches = Acronym.objects.filter(
                Q(short__icontains=query) | Q(short__icontains=query_clean) | Q(short__icontains=query_with_geresh)
            ).distinct()[:20]
        results = [{'short': item.short, 'meaning': item.meaning} for item in matches]
    return JsonResponse({'results': results})


def advanced_search_view(request):
    return render(request, 'articles/advanced_search.html', {'current_page': 'advanced_search'})


def or_hacarmel_view(request):
    return render(request, 'articles/or_hacarmel.html')


def aramaic_translator_view(request):
    context = _get_aramaic_context(request)
    return render(request, 'articles/aramaic_translator.html', context)


@ratelimit(rate=30, timeout=60)
def aramaic_translate_api(request):
    payload, status_code = execute_aramaic_translation(request)
    return JsonResponse(payload, status=status_code, json_dumps_params={'ensure_ascii': False})