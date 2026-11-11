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
from .clusters_engine import ClusterEngine, GRAVITY_CLUSTERS
from .torah_engine import (
    HEBREW_GEMATRIA,
    TANAKH_NAMES,
    TORAH_NAMES,
    MISHNAH_BOOKS,
    BAVLI_TRACTATES_EN,
    YERUSHALMI_TRACTATES_EN,
    SHULCHAN_ARUCH_EN,
    TORAH_CORE_CONCEPTS,
    calculate_gematria,
    format_divine_name,
    ratelimit,
    int_to_hebrew,
    format_verse_hebrew,
    parse_hebrew_number,
    generate_word_variations,
    get_book_order,
    safe_int,
    _resolve_torah_book_in_db,
    _resolve_torah_verse_obj,
    _generate_spelling_variants,
    _extract_sefaria_he_list,
    _match_comments_by_dibbur_hamatchil,
    _fetch_sefaria_json_cached,
    _fetch_commentary_for_source,
    tanakh_advanced_search_api,
    _IPV4_OPENER,
)
from .ai_engine import (
    smart_hebrew_search,
    get_text_fields,
    get_item_title,
    get_item_text,
    ai_document_search,
    get_smart_content,
    ai_chat_endpoint,
    torah_ai_insights_api,
)
from .aramaic_engine import aramaic_translator_view as _get_aramaic_context, execute_aramaic_translation


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
            date_resp = _IPV4_OPENER.open(date_req, timeout=5)
            date_data = json.loads(date_resp.read().decode('utf-8'))
            cal_data['hebrew_date'] = date_data.get('hebrew', '')
        except Exception:
            cal_data['hebrew_date'] = ''

        url = f'https://www.hebcal.com/hebcal?v=1&cfg=json&geo=IL&lg=he&s=on&maj=on&min=on&start={start_date}&end={end_date}'
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        response = _IPV4_OPENER.open(req, timeout=5)
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
        article = Article.objects.only('id', 'slug').filter(pk=int(slug_str)).first()
        if article and article.slug:
            return redirect('articles:detail', slug=article.slug, permanent=True)

    if article:
        if not article.is_published and not request.user.is_superuser:
            raise Http404("המאמר מוקפא כעת ואינו מפורסם לציבור.")

        if article.slug and article.slug != slug_str:
            return redirect('articles:detail', slug=article.slug, permanent=True)

        learning_ctx = ClusterEngine.get_learning_context(article)
        admin_choices = ClusterEngine.get_editorial_choices_for_admin() if request.user.is_superuser else None

        return render(request, 'articles/article_detail.html', {
            'article': article,
            'learning': learning_ctx,
            'admin_choices': admin_choices,
            'current_page': 'articles',
        })

    raise Http404(f"העמוד '{slug_str}' לא נמצא.")


@login_required
def connections_audit_view(request):
    if not request.user.is_superuser:
        return redirect('articles:list')

    if request.method == 'POST':
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            try:
                payload = json.loads(request.body.decode('utf-8'))
                art_pk = int(payload.get('article_pk', 0))
                ed_action = payload.get('ed_action', '')
                target_type = payload.get('target_type', '')
                target_id = payload.get('target_id', '')
                bidirectional = bool(payload.get('bidirectional', True))

                if ed_action == 'approve_all_pending':
                    ClusterEngine.approve_all_pending_articles()
                    return JsonResponse({'ok': True})

                if art_pk > 0 and ed_action == 'toggle_article_publish':
                    art_obj = get_object_or_404(Article, pk=art_pk)
                    art_obj.is_published = not art_obj.is_published
                    art_obj.save(update_fields=['is_published'])
                    ClusterEngine.clear_memory_cache()
                    return JsonResponse({'ok': True, 'is_published': art_obj.is_published})

                if art_pk > 0 and ed_action in ('approve_all_ai_for_article', 'reject_all_ai_for_article'):
                    ClusterEngine.batch_article_ai_decision(article_pk=art_pk, mode=ed_action)
                    return JsonResponse({'ok': True})

                if art_pk > 0 and ed_action:
                    ClusterEngine.update_editorial_decision(
                        article_pk=art_pk,
                        action=ed_action,
                        target_type=target_type,
                        target_id=target_id,
                        bidirectional=bidirectional,
                    )
                    return JsonResponse({'ok': True})
            except Exception as e:
                return JsonResponse({'ok': False, 'error': str(e)}, status=400)

        cfg = ClusterEngine.get_runtime_config()
        new_score = request.POST.get('min_connection_score', cfg['min_connection_score'])
        action = request.POST.get('action', 'save_score')

        if action == 'approve_all_pending':
            ClusterEngine.approve_all_pending_articles()
            return redirect('articles:connections_audit')

        public_enabled = cfg['public_enabled']
        if action == 'enable_public':
            public_enabled = True
        elif action == 'disable_public':
            public_enabled = False

        ClusterEngine.save_runtime_config(new_score, public_enabled)
        return redirect('articles:connections_audit')

    preview_score = request.GET.get('min_score')
    report = ClusterEngine.generate_admin_audit_report(min_score_override=preview_score if preview_score else None)
    return render(request, 'articles/connections_audit.html', {
        'report': report,
        'current_page': 'articles',
    })

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

def qa_list(request, pk=None):
    selected_qa = None
    try:
        questions = QA.objects.all().order_by('-created_at')
        categories = QA.objects.exclude(category__isnull=True).exclude(category__exact='').values_list('category', flat=True).distinct()

        q = request.GET.get('q')
        if q:
            questions = questions.filter(Q(question__icontains=q) | Q(answer__icontains=q))

        category = request.GET.get('category')
        if category:
            questions = questions.filter(category=category)

        open_id = pk or request.GET.get('open')
        if open_id and str(open_id).isdigit():
            selected_qa = QA.objects.filter(pk=int(open_id)).first()

    except Exception:
        questions = None
        categories = []

    return render(request, 'articles/qa_list.html', {
        'questions': questions,
        'categories': categories,
        'selected_qa': selected_qa,
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
    selected_cluster_id = request.GET.get('cluster', '').strip()
    clusters_data = ClusterEngine.get_public_index_clusters(
        is_superuser=request.user.is_superuser,
        selected_cluster_id=selected_cluster_id
    )

    published_articles = Article.objects.filter(is_published=True).only('id', 'title', 'slug', 'created_at').order_by('title')
    articles_count = published_articles.count()

    if clusters_data['selected_cluster']:
        allowed_pks = {a['pk'] for a in clusters_data['selected_cluster']['articles']}
        filtered_articles = [a for a in published_articles if a.pk in allowed_pks]
    else:
        filtered_articles = list(published_articles)

    grouped_articles = {}
    for article in filtered_articles:
        if article.title:
            first_letter = article.title.strip()[0]
            if first_letter not in grouped_articles:
                grouped_articles[first_letter] = []
            grouped_articles[first_letter].append(article)
    sorted_groups = {k: grouped_articles[k] for k in sorted(grouped_articles.keys())}

    return render(request, 'articles/article_index.html', {
        'grouped_articles': sorted_groups,
        'articles_count': articles_count,
        'topic_clusters': clusters_data['clusters'],
        'selected_cluster': clusters_data['selected_cluster'],
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
        _IPV4_OPENER.open(url, timeout=5)
    except Exception:
        pass

@receiver([post_save, post_delete], sender=Article)
@receiver([post_save, post_delete], sender=Book)
def clear_cache_on_db_change(sender, instance, **kwargs):
    cache.clear()
    ClusterEngine.clear_memory_cache()

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
    response = render(request, 'articles/advanced_search.html', {'current_page': 'advanced_search'})
    sync_script = """
<script>
(function() {
    const initParams = new URLSearchParams(window.location.search);
    const initBook = (initParams.get('book') || '').trim();
    const initType = (initParams.get('type') || '').trim();
    const initExact = (initParams.get('exact') || '').trim();
    const initExclude = (initParams.get('exclude_books') || '').trim();
    const initSkip = (initParams.get('skip') || '').trim();
    const initQ = (initParams.get('q') || '').trim();

    let initialUrlOverrideActive = Boolean(initBook || initType || initExclude || initSkip);
    let initialSearchExecuted = false;
    window.__currentSearchShareUrl = window.location.href;

    const origReplaceState = window.history.replaceState;
    const origPushState = window.history.pushState;

    function enrichHistoryUrl(urlArg) {
        if (!urlArg || !window.__currentSearchShareUrl) return urlArg;
        try {
            const u = new URL(urlArg, window.location.origin);
            if (u.pathname.includes('advanced-search') && u.searchParams.get('q') && !u.searchParams.get('book')) {
                return window.__currentSearchShareUrl;
            }
        } catch (e) {}
        return urlArg;
    }

    window.history.replaceState = function(state, title, url) {
        return origReplaceState.call(this, state, title, enrichHistoryUrl(url));
    };

    window.history.pushState = function(state, title, url) {
        return origPushState.call(this, state, title, enrichHistoryUrl(url));
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
        const origWriteText = navigator.clipboard.writeText.bind(navigator.clipboard);
        navigator.clipboard.writeText = function(text) {
            if (typeof text === 'string' && text.includes('/advanced-search/?q=') && !text.includes('&book=') && window.__currentSearchShareUrl) {
                text = text.replace(/https?:\\/\\/[^\\s]+\\/advanced-search\\/\\?q=[^\\s&]+/, window.__currentSearchShareUrl);
            }
            return origWriteText(text);
        };
    }

    if (navigator.share) {
        const origShare = navigator.share.bind(navigator);
        navigator.share = function(shareData) {
            if (shareData && typeof shareData === 'object' && window.__currentSearchShareUrl) {
                if (shareData.url && shareData.url.includes('/advanced-search/') && !shareData.url.includes('book=')) {
                    shareData.url = window.__currentSearchShareUrl;
                }
                if (shareData.text && shareData.text.includes('/advanced-search/?q=') && !shareData.text.includes('&book=')) {
                    shareData.text = shareData.text.replace(/https?:\\/\\/[^\\s]+\\/advanced-search\\/\\?q=[^\\s&]+/, window.__currentSearchShareUrl);
                }
            }
            return origShare(shareData);
        };
    }

    const origFetch = window.fetch;
    window.fetch = function(input, init) {
        if (typeof input === 'string' && input.includes('/api/tanakh-search/')) {
            try {
                const u = new URL(input, window.location.origin);
                const reqType = u.searchParams.get('type') || 'text';
                const isUtilityCall = ['book_chapters', 'commentary', 'chapter_context', 'quick_open'].includes(reqType);

                if (!isUtilityCall) {
                    if (initialUrlOverrideActive) {
                        if (initBook) u.searchParams.set('book', initBook);
                        if (initExclude) u.searchParams.set('exclude_books', initExclude);
                        if (initSkip) u.searchParams.set('skip', initSkip);
                        if (initType) {
                            if (initType === 'text' || initType === 'text_broad') {
                                u.searchParams.set('type', 'text_broad');
                                u.searchParams.set('exact', 'false');
                            } else if (initType === 'text_exact') {
                                u.searchParams.set('type', 'text_exact');
                                u.searchParams.set('exact', 'true');
                            } else {
                                u.searchParams.set('type', initType);
                            }
                        } else if (initExact) {
                            u.searchParams.set('exact', initExact);
                        }
                        input = u.pathname + u.search;
                        initialSearchExecuted = true;
                    }

                    const finalQ = (u.searchParams.get('q') || '').trim();
                    const finalBook = (u.searchParams.get('book') || '').trim();
                    const finalType = (u.searchParams.get('type') || 'text').trim();
                    const finalExact = (u.searchParams.get('exact') || '').trim();
                    const finalExclude = (u.searchParams.get('exclude_books') || '').trim();
                    const finalSkip = (u.searchParams.get('skip') || '').trim();

                    if (finalQ) {
                        const shareParams = new URLSearchParams();
                        shareParams.set('q', finalQ);
                        if (finalType === 'text') {
                            shareParams.set('type', finalExact === 'true' ? 'text_exact' : 'text_broad');
                        } else {
                            shareParams.set('type', finalType);
                        }
                        if (finalBook) shareParams.set('book', finalBook);
                        if (finalExclude) shareParams.set('exclude_books', finalExclude);
                        if (finalSkip) shareParams.set('skip', finalSkip);

                        const fullUrl = window.location.origin + window.location.pathname + '?' + shareParams.toString();
                        window.__currentSearchShareUrl = fullUrl;
                        origReplaceState.call(window.history, null, '', fullUrl);
                        setTimeout(function() {
                            origReplaceState.call(window.history, null, '', window.__currentSearchShareUrl);
                        }, 80);
                    }
                }
            } catch (e) {}
        }
        return origFetch.call(this, input, init);
    };

    function getSettingsSidebar() {
        const els = Array.from(document.querySelectorAll('h1, h2, h3, h4, h5, h6, div, span, label'));
        const h = els.find(el => el.children.length <= 2 && (el.innerText || '').trim().includes('הגדרות חיפוש'));
        if (h) {
            let curr = h.parentElement;
            while (curr && curr !== document.body) {
                const txt = curr.innerText || '';
                if (txt.includes('בחר מאגרי חיפוש') && txt.includes('בחר סוג פעולה')) {
                    return curr;
                }
                curr = curr.parentElement;
            }
        }
        return document;
    }

    function isCorpusBtnActive(btn) {
        if (!btn) return false;
        if (btn.querySelector('.bi-check-circle-fill, .bi-check-circle, .bi-check2-circle, input:checked')) return true;
        if (btn.querySelector('.bi-circle')) return false;
        return btn.classList.contains('active') || btn.classList.contains('selected');
    }

    function findSidebarCorpusBtn(sidebar, key) {
        const icons = Array.from(sidebar.querySelectorAll('i.bi-circle, i.bi-check-circle-fill, i.bi-check-circle, [data-corpus], [data-book]'));
        const candidates = [];
        icons.forEach(ic => {
            const btn = ic.closest('[onclick], button, [data-corpus], [data-book], .btn, .card') || ic.parentElement;
            if (btn && !candidates.includes(btn)) candidates.push(btn);
        });

        return candidates.find(el => {
            const dc = el.getAttribute('data-corpus') || el.getAttribute('data-book') || '';
            const oc = el.getAttribute('onclick') || '';
            if (dc === key || oc.includes("'" + key + "'") || oc.includes('"' + key + '"')) return true;
            const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
            if (!t || t.length > 40) return false;
            if (key === 'all') return t.includes('כל המאגרים');
            if (key === 'torah') return t === 'תורה' || (t.includes('תורה') && !t.includes('רמב') && !t.includes('משנה'));
            if (key === 'tanakh') return t.includes('תנ"ך') || t.includes('תנ״ך');
            if (key === 'mishnah') return t === 'משנה' || (t.includes('משנה') && !t.includes('רמב') && !t.includes('תורה'));
            if (key === 'tosefta') return t.includes('תוספתא');
            if (key === 'talmud') return t.includes('תלמוד בבלי');
            if (key === 'yerushalmi') return t.includes('תלמוד ירושלמי');
            if (key === 'rambam') return t.includes('רמב"ם') || t.includes('רמב״ם');
            if (key === 'shulchan_aruch') return t.includes('שולחן ערוך');
            return false;
        });
    }

    function findSidebarTypeBtn(sidebar, urlTypeVal, urlExactVal) {
        let effectiveType = urlTypeVal;
        if (effectiveType === 'text') {
            effectiveType = (urlExactVal === 'true') ? 'text_exact' : 'text_broad';
        }
        const typeTextMap = {
            'text_broad': 'חיפוש חופשי',
            'text_exact': 'מילה מדויקת',
            'text_fuzzy': 'כתיב מלא',
            'gematria': 'גימטריה',
            'rashei_tevot': 'ראשי תיבות',
            'acronym': 'ראשי תיבות',
            'sofei_tevot': 'סופי תיבות',
            'suffix': 'סופי תיבות',
            'reverse': 'מילים הפוכות',
            'palindrome': 'מילים הפוכות',
            'els': 'דילוגים במילה',
            'skip': 'דילוגים במילה',
            'dilugim': 'דילוגים במילה',
            'els_verse': 'דילוגים בפסוק'
        };
        const targetLabel = typeTextMap[effectiveType];
        if (!targetLabel) return null;

        const allEls = Array.from(sidebar.querySelectorAll('[onclick], [data-type], button, .btn, .card, div'));
        const matches = allEls.filter(el => {
            const dt = el.getAttribute('data-type') || el.getAttribute('onclick') || '';
            if (dt && (dt.includes("'" + effectiveType + "'") || dt.includes('"' + effectiveType + '"'))) return true;
            const t = (el.innerText || '').replace(/\\s+/g, ' ').trim();
            return t.length > 0 && t.length < 55 && t.includes(targetLabel);
        });
        return matches.length ? matches[matches.length - 1] : null;
    }

    function applyUrlStateToUi(triggerSearchIfNeeded) {
        if (!initialUrlOverrideActive) return;
        const sidebar = getSettingsSidebar();

        if (initBook) {
            const targetBooks = initBook.split(',').map(s => s.trim()).filter(Boolean);
            const allKeys = ['torah', 'tanakh', 'mishnah', 'tosefta', 'talmud', 'yerushalmi', 'rambam', 'shulchan_aruch'];

            if (targetBooks.includes('all')) {
                const bAll = findSidebarCorpusBtn(sidebar, 'all');
                if (bAll && !isCorpusBtnActive(bAll)) bAll.click();
            } else {
                // First activate all desired corpora so the list is never empty
                targetBooks.forEach(k => {
                    const b = findSidebarCorpusBtn(sidebar, k);
                    if (b && !isCorpusBtnActive(b)) b.click();
                });
                // Then deactivate any corpus not in targetBooks (e.g. default 'torah')
                allKeys.forEach(k => {
                    if (!targetBooks.includes(k)) {
                        const b = findSidebarCorpusBtn(sidebar, k);
                        if (b && isCorpusBtnActive(b)) b.click();
                    }
                });
            }
        }

        if (initType) {
            const tBtn = findSidebarTypeBtn(sidebar, initType, initExact);
            if (tBtn) tBtn.click();
        }

        if (initQ) {
            const qInput = sidebar.querySelector('input[type="text"], input[type="search"], input:not([type="hidden"]):not([type="checkbox"])');
            if (qInput && qInput.value !== initQ) {
                qInput.value = initQ;
            }
            if (triggerSearchIfNeeded && !initialSearchExecuted) {
                const allBtns = Array.from(sidebar.querySelectorAll('button, [onclick], .btn'));
                const searchBtn = allBtns.find(el => (el.innerText || '').includes('בצע חיפוש'));
                if (searchBtn) searchBtn.click();
            }
        }
    }

    document.addEventListener('DOMContentLoaded', function() {
        applyUrlStateToUi(false);
        setTimeout(function() {
            applyUrlStateToUi(true);
        }, 120);
        setTimeout(function() {
            initialUrlOverrideActive = false;
        }, 1800);
    });
})();
</script>
"""
    try:
        html_str = response.content.decode('utf-8')
        if '<head>' in html_str:
            html_str = html_str.replace('<head>', '<head>\n' + sync_script, 1)
        elif '</body>' in html_str:
            html_str = html_str.replace('</body>', sync_script + '\n</body>', 1)
        else:
            html_str += sync_script
        response.content = html_str.encode('utf-8')
    except Exception:
        pass
    return response

def aramaic_translator_view(request):
    context = _get_aramaic_context(request)
    return render(request, 'articles/aramaic_translator.html', context)


@ratelimit(rate=30, timeout=60)
def aramaic_translate_api(request):
    payload, status_code = execute_aramaic_translation(request)
    return JsonResponse(payload, status=status_code, json_dumps_params={'ensure_ascii': False})