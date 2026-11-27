import asyncio
import datetime
import hashlib
import json
import logging
import os
import random
import re
import smtplib
import socket
import threading
import time
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr
from html import unescape
import edge_tts
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.html import escape, strip_tags
from django.views.decorators.cache import cache_page
from .ai_engine import (
    _is_same_origin_request,
    ai_chat_endpoint as ai_chat_endpoint,
    ai_document_search as ai_document_search,
    get_item_text,
    get_item_title,
    get_smart_content,
    get_text_fields as get_text_fields,
    smart_hebrew_search,
    torah_ai_insights_api as torah_ai_insights_api,
)
from .aramaic_engine import aramaic_translator_view as _get_aramaic_context, execute_aramaic_translation
from .clusters_engine import ClusterEngine, GRAVITY_CLUSTERS as GRAVITY_CLUSTERS
from .emails import send_order_confirmation
from .forms import ArticleForm
from .models import (
    Acronym,
    Article,
    Book,
    Cart,
    CartItem,
    Chapter,
    ContactMessage,
    Order,
    OrderItem,
    QA,
    Section,
    normalize_article_footnotes_html,
    sanitize_unsafe_links_html,
)
from .torah_engine import (
    BAVLI_TRACTATES_EN as BAVLI_TRACTATES_EN,
    HEBREW_GEMATRIA as HEBREW_GEMATRIA,
    MISHNAH_BOOKS as MISHNAH_BOOKS,
    SHULCHAN_ARUCH_EN as SHULCHAN_ARUCH_EN,
    TANAKH_NAMES as TANAKH_NAMES,
    TORAH_CORE_CONCEPTS as TORAH_CORE_CONCEPTS,
    TORAH_NAMES as TORAH_NAMES,
    YERUSHALMI_TRACTATES_EN as YERUSHALMI_TRACTATES_EN,
    _IPV4_OPENER,
    _extract_sefaria_he_list as _extract_sefaria_he_list,
    _fetch_commentary_for_source as _fetch_commentary_for_source,
    _fetch_sefaria_json_cached as _fetch_sefaria_json_cached,
    _generate_spelling_variants as _generate_spelling_variants,
    _match_comments_by_dibbur_hamatchil as _match_comments_by_dibbur_hamatchil,
    _resolve_torah_book_in_db as _resolve_torah_book_in_db,
    _resolve_torah_verse_obj as _resolve_torah_verse_obj,
    calculate_gematria as calculate_gematria,
    format_divine_name as format_divine_name,
    format_verse_hebrew as format_verse_hebrew,
    generate_word_variations,
    get_book_order as get_book_order,
    int_to_hebrew,
    parse_hebrew_number as parse_hebrew_number,
    ratelimit,
    safe_int as safe_int,
    tanakh_advanced_search_api as tanakh_advanced_search_api,
)
from .vector_store import search_similar_articles

logger = logging.getLogger(__name__)
_BOT_UA_RE = re.compile(r'(?:bot|crawler|spider|slurp|bingpreview|facebookexternalhit|headless|scrapy|curl|wget)', re.IGNORECASE)
_EMAIL_SIMPLE_RE = re.compile(r'^[^\s@\r\n]+@[^\s@\r\n]+\.[^\s@\r\n]{2,}$')

_CONTENT_CACHE_VER_KEY = 'leblibrary_content_cache_ver'
_AUDIO_JOBS_LOCK = threading.Lock()
_AUDIO_JOBS_IN_PROGRESS = set()
_MAX_CONCURRENT_AUDIO_JOBS = 2
_BLOCKED_CART_FETCH_DESTS = {'image', 'script', 'style', 'iframe', 'object', 'embed', 'font', 'audio', 'video'}

def _get_content_cache_version():
    ver = cache.get(_CONTENT_CACHE_VER_KEY)
    if ver is None:
        ver = 1
        cache.set(_CONTENT_CACHE_VER_KEY, ver, None)
    return ver

def _bump_content_cache_version():
    new_ver = int(time.time() * 1000)
    cache.set(_CONTENT_CACHE_VER_KEY, new_ver, None)
    return new_ver

def _sample_queryset_random(qs, count):
    if count <= 0:
        return []
    ids = list(qs.values_list('pk', flat=True))
    if not ids:
        return []
    picked = random.sample(ids, min(count, len(ids)))
    obj_map = {obj.pk: obj for obj in qs.filter(pk__in=picked)}
    return [obj_map[pk] for pk in picked if pk in obj_map]

def _sanitize_header_value(value, max_len=200):
    return re.sub(r'[\r\n]+', ' ', str(value or '')).strip()[:max_len]

def _is_automated_crawler(request):
    ua = (request.META.get('HTTP_USER_AGENT') or '').strip()
    return bool(ua and _BOT_UA_RE.search(ua))

def _is_safe_cart_action_request(request):
    if _is_automated_crawler(request):
        return False
    sec_fetch_dest = (request.META.get('HTTP_SEC_FETCH_DEST') or '').strip().lower()
    if sec_fetch_dest in _BLOCKED_CART_FETCH_DESTS:
        return False
    purpose = ((request.META.get('HTTP_PURPOSE') or '') + ' ' + (request.META.get('HTTP_SEC_PURPOSE') or '')).lower()
    if 'prefetch' in purpose or 'prerender' in purpose:
        return False
    return _is_same_origin_request(request)

def _is_safe_editorial_url(url_value):
    u = str(url_value or '').strip()
    if not u:
        return False
    if u.startswith('/') and not u.startswith('//'):
        return True
    parsed = urllib.parse.urlparse(u)
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)

PARASHA_CANONICAL_NAMES = (
    'בראשית', 'נח', 'לך לך', 'וירא', 'חיי שרה', 'תולדות', 'ויצא', 'וישלח', 'וישב', 'מקץ', 'ויגש', 'ויחי',
    'שמות', 'וארא', 'בא', 'בשלח', 'יתרו', 'משפטים', 'תרומה', 'תצוה', 'כי תשא', 'ויקהל', 'פקודי',
    'ויקרא', 'צו', 'שמיני', 'תזריע', 'מצורע', 'אחרי מות', 'קדושים', 'אמור', 'בהר', 'בחוקתי',
    'במדבר', 'נשא', 'בהעלותך', 'שלח לך', 'קרח', 'חקת', 'בלק', 'פינחס', 'מטות', 'מסעי',
    'דברים', 'ואתחנן', 'עקב', 'ראה', 'שופטים', 'כי תצא', 'כי תבוא', 'ניצבים', 'וילך', 'האזינו', 'וזאת הברכה',
)
_PARASHA_ALIASES = {
    'חוקת': 'חקת',
    'בחוקותי': 'בחוקתי',
    'בחקתי': 'בחוקתי',
    'בחקותי': 'בחוקתי',
    'פנחס': 'פינחס',
    'נצבים': 'ניצבים',
    'תצווה': 'תצוה',
    'בהעלתך': 'בהעלותך',
    'כי תבא': 'כי תבוא',
    'ויתחנן': 'ואתחנן',
    'תולדת': 'תולדות',
    'שלח': 'שלח לך',
    'אחרי': 'אחרי מות',
    'זאת הברכה': 'וזאת הברכה',
}
_PARASHA_SLUG_TO_NAME = {name.replace(' ', '-'): name for name in PARASHA_CANONICAL_NAMES}
_PARASHA_SLUG_TO_NAME.update({name: name for name in PARASHA_CANONICAL_NAMES})
for _alias, _canon in _PARASHA_ALIASES.items():
    _PARASHA_SLUG_TO_NAME[_alias] = _canon
    _PARASHA_SLUG_TO_NAME[_alias.replace(' ', '-')] = _canon

_SECTION_FN_ID_RE = re.compile(r'\bid=(["\'])((?:fn-(?:note|ref)-|footnote-(?:ref-)?)[^"\']+)\1')
_SECTION_FN_HREF_RE = re.compile(r'\bhref=(["\'])#((?:fn-(?:note|ref)-|footnote-(?:ref-)?)[^"\']+)\1')

def _parasha_to_slug(name):
    return re.sub(r'\s+', '-', str(name or '').strip())

def _resolve_parasha_name(raw_value):
    cleaned = re.sub(r'\s+', ' ', str(raw_value or '').replace('-', ' ')).strip()
    cleaned = re.sub(r'^פרשת\s+', '', cleaned).strip()
    if not cleaned:
        return ''
    if cleaned in _PARASHA_SLUG_TO_NAME:
        return _PARASHA_SLUG_TO_NAME[cleaned]
    slug_key = _parasha_to_slug(cleaned)
    return _PARASHA_SLUG_TO_NAME.get(slug_key, cleaned)

def _scope_section_footnotes(html_content, section_pk):
    if not html_content or not section_pk:
        return html_content
    local_ids = {m.group(2) for m in _SECTION_FN_ID_RE.finditer(html_content)}
    if not local_ids:
        return html_content
    local_hrefs = {m.group(2) for m in _SECTION_FN_HREF_RE.finditer(html_content)}
    paired_ids = local_ids & local_hrefs
    if not paired_ids:
        return html_content

    ids_to_scope = set(paired_ids)
    for lid in local_ids:
        m_fn_ref = re.match(r'^fn-ref-(\d+-\d+)(?:-\d+)?$', lid)
        if m_fn_ref and f"fn-note-{m_fn_ref.group(1)}" in paired_ids:
            ids_to_scope.add(lid)
        m_ft_ref = re.match(r'^footnote-ref-(\d+)(?:-\d+)?$', lid)
        if m_ft_ref and f"footnote-{m_ft_ref.group(1)}" in paired_ids:
            ids_to_scope.add(lid)

    prefix_tag = f"s{section_pk}-"

    def _scope_token(tok):
        for pfx in ('fn-note-', 'fn-ref-', 'footnote-ref-', 'footnote-'):
            if tok.startswith(pfx):
                return f"{pfx}{prefix_tag}{tok[len(pfx):]}"
        return tok

    def _repl_id(match):
        q_ch, tok = match.group(1), match.group(2)
        if tok in ids_to_scope:
            return f'id={q_ch}{_scope_token(tok)}{q_ch}'
        return match.group(0)

    def _repl_href(match):
        q_ch, tok = match.group(1), match.group(2)
        if tok in ids_to_scope:
            return f'href={q_ch}#{_scope_token(tok)}{q_ch}'
        return match.group(0)

    scoped = _SECTION_FN_ID_RE.sub(_repl_id, html_content)
    return _SECTION_FN_HREF_RE.sub(_repl_href, scoped)

def _extract_article_parashot(raw_parasha):
    if not raw_parasha:
        return []
    out = []
    seen = set()
    for token in str(raw_parasha).split(','):
        name = re.sub(r'\s+', ' ', token).strip()
        if not name or name.lower() == 'general':
            continue
        canonical = _resolve_parasha_name(name)
        if canonical and canonical not in seen:
            seen.add(canonical)
            out.append((canonical, _parasha_to_slug(canonical)))
    return out

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
        logger.warning("Hebcal calendar fetch failed", exc_info=True)

    return cal_data

_BLOCK_TAG_BOUNDARY_RE = re.compile(r'</?(?:p|div|br|h[1-6]|li|ul|ol|tr|td|th|blockquote|section|article|header|footer|hr)[^>]*>', re.IGNORECASE)

def _build_clean_excerpt(html_content, max_words=25):
    if not html_content:
        return ""
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', str(html_content), flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.IGNORECASE | re.DOTALL)
    text = _BLOCK_TAG_BOUNDARY_RE.sub(' ', text)
    text = text.replace('><', '> <')
    text = strip_tags(text)
    text = unescape(text).replace('\xa0', ' ')
    text = re.sub(r'\s+', ' ', text).strip()
    if not max_words or max_words <= 0:
        return text
    words = text.split(' ')
    if len(words) <= max_words:
        return text
    return ' '.join(words[:max_words]) + '…'

def article_list(request):
    query = request.GET.get('q')

    if query:
        query = query.strip()[:120]
        published_articles = Article.objects.filter(is_published=True).order_by('-created_at')
        articles = smart_hebrew_search(published_articles, query, ['title', 'content'])
        return render(request, 'articles/article_list.html', {
            'articles': articles, 'latest_articles': None, 'reading_books': None, 'sale_books': None,
            'parasha_article': None, 'jewish_cal': None, 'query': query, 'current_page': 'home',
        })

    today_str = str(datetime.date.today())
    content_ver = _get_content_cache_version()
    cache_key = f'home_dynamic_content_v{content_ver}_{today_str}'

    dynamic_content = cache.get(cache_key)

    if not dynamic_content:
        parasha_qs = Article.objects.filter(is_published=True).exclude(
            Q(parasha__isnull=True) |
            Q(parasha__exact='') |
            Q(parasha__exact=',') |
            Q(parasha__exact=',,') |
            Q(parasha__icontains='general')
        )
        parasha_picks = _sample_queryset_random(parasha_qs, 1)
        parasha_article = parasha_picks[0] if parasha_picks else None

        recent_15 = list(Article.objects.filter(is_published=True).order_by('-created_at')[:15])
        if parasha_article and parasha_article in recent_15:
            recent_15.remove(parasha_article)
        latest_articles = random.sample(recent_15, min(2, len(recent_15)))

        reading_books = _sample_queryset_random(Book.objects.filter(is_for_sale=False), 3)
        sale_books = _sample_queryset_random(Book.objects.filter(is_for_sale=True), 3)

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
        logger.warning('Failed loading latest QA preview for home page', exc_info=True)

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
    })

def article_detail(request, slug):
    slug_str = str(slug).strip()
    article = Article.objects.filter(slug=slug_str).first()

    legacy_id = None
    if not article:
        if slug_str.isdigit():
            legacy_id = int(slug_str)
        elif slug_str.startswith('article-') and slug_str.replace('article-', '', 1).isdigit():
            legacy_id = int(slug_str.replace('article-', '', 1))

    if legacy_id is not None:
        article = Article.objects.only('id', 'slug', 'is_published').filter(pk=legacy_id).first()
        if article and article.slug:
            if article.is_published:
                return redirect('articles:detail', slug=article.slug, permanent=True)
            if request.user.is_superuser:
                return redirect('articles:detail', slug=article.slug, permanent=False)
            return redirect('articles:articles_index')
        return redirect('articles:articles_index', permanent=True)

    if article:
        if not article.is_published and not request.user.is_superuser:
            return redirect('articles:articles_index')

        if article.slug and article.slug != slug_str:
            return redirect('articles:detail', slug=article.slug, permanent=True)

        learning_ctx = ClusterEngine.get_learning_context(article)
        admin_choices = ClusterEngine.get_editorial_choices_for_admin() if request.user.is_superuser else None

        return render(request, 'articles/article_detail.html', {
            'article': article,
            'rendered_content': normalize_article_footnotes_html(article.content or ''),
            'article_excerpt': _build_clean_excerpt(article.content, max_words=30),
            'article_parashot': _extract_article_parashot(article.parasha),
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
                    if target_type == 'tools' and isinstance(target_id, str) and target_id.startswith('custom_json:'):
                        tool_cfg = json.loads(target_id[len('custom_json:'):])
                        if not _is_safe_editorial_url(tool_cfg.get('url', '')):
                            return JsonResponse({'ok': False, 'error': 'כתובת קישור לא חוקית.'}, status=400)
                    ClusterEngine.update_editorial_decision(
                        article_pk=art_pk,
                        action=ed_action,
                        target_type=target_type,
                        target_id=target_id,
                        bidirectional=bidirectional,
                    )
                    return JsonResponse({'ok': True})
            except Exception:
                logger.exception("Error in connections_audit_view AJAX action")
                return JsonResponse({'ok': False, 'error': 'אירעה שגיאה בעיבוד הפעולה.'}, status=400)

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
    if not request.user.is_superuser:
        return HttpResponseForbidden('אין הרשאה לבצע פעולה זו.')
    if request.method == 'POST':
        form = ArticleForm(request.POST)
        if form.is_valid():
            article = form.save()
            ping_indexnow(request.build_absolute_uri(reverse('articles:detail', args=[article.slug])))
            return redirect('articles:list')
        return render(request, 'articles/article_form.html', {'form': form, 'current_page': 'articles'})
    return render(request, 'articles/article_form.html', {'form': ArticleForm(), 'current_page': 'articles'})

@login_required
def article_edit(request, slug):
    if not request.user.is_superuser:
        return HttpResponseForbidden('אין הרשאה לבצע פעולה זו.')
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
        return render(request, 'articles/article_form.html', {'form': form, 'current_page': 'articles'})
    return render(request, 'articles/article_form.html', {'form': ArticleForm(instance=article), 'current_page': 'articles'})

@login_required
def article_delete(request, slug):
    if not request.user.is_superuser:
        return HttpResponseForbidden('אין הרשאה לבצע פעולה זו.')
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
    smtp_user = (os.environ.get('EMAIL_HOST_USER') or getattr(settings, 'EMAIL_HOST_USER', '') or '').strip()
    raw_pass = (os.environ.get('EMAIL_HOST_PASSWORD') or getattr(settings, 'EMAIL_HOST_PASSWORD', '') or '').strip()
    smtp_pass = re.sub(r'\s+', '', raw_pass)

    if not smtp_user or not smtp_pass or smtp_pass == 'YOUR_16_LETTER_PASSWORD':
        raise RuntimeError("SMTP credentials are not configured in environment variables.")

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

@ratelimit(rate=5, timeout=300, methods=('POST',))
def contact(request):
    if request.method == 'POST':
        try:
            honeypot = request.POST.get('website_url', '').strip()
            if honeypot:
                messages.success(request, 'תודה רבה! הודעתך נשלחה בהצלחה.')
                return redirect('articles:contact')

            name = _sanitize_header_value(request.POST.get('name', ''), 120) or 'ללא שם'
            phone = _sanitize_header_value(request.POST.get('phone', ''), 40) or 'לא צוין'
            email = _sanitize_header_value(request.POST.get('email', ''), 254) or 'לא צוין'
            subject = _sanitize_header_value(request.POST.get('subject', ''), 200) or 'פנייה כללית מהאתר'
            message = (request.POST.get('message', '') or '').strip()[:5000] or '[הגולש לא כתב תוכן]'

            full_message = (
                f"התקבלה פנייה חדשה מאתר ספריית לייבוביץ:\n\n"
                f"שם: {name}\n"
                f"טלפון: {phone}\n"
                f"אימייל לחזרה: {email}\n"
                f"נושא הפנייה: {subject}\n\n"
                f"תוכן ההודעה:\n{message}"
            )

            contact_record = None
            try:
                contact_record = ContactMessage.objects.create(
                    name=name,
                    phone=phone,
                    email=email,
                    subject=subject,
                    message=message,
                )
            except Exception:
                logger.exception("Failed saving ContactMessage to database")

            recipient = (
                os.environ.get('CONTACT_RECIPIENT_EMAIL', '').strip()
                or os.environ.get('EMAIL_HOST_USER', '').strip()
                or getattr(settings, 'EMAIL_HOST_USER', '').strip()
            )
            if not recipient:
                raise RuntimeError("CONTACT_RECIPIENT_EMAIL / EMAIL_HOST_USER is not configured.")
            valid_reply_to = email if _EMAIL_SIMPLE_RE.match(email) else None
            _send_gmail_ipv4(
                subject=f"פנייה מהאתר: {subject} ({name})",
                body=full_message,
                recipient_list=[recipient],
                reply_to_email=valid_reply_to
            )
            if contact_record is not None:
                contact_record.email_sent = True
                contact_record.save(update_fields=['email_sent'])
            messages.success(request, 'תודה רבה! הודעתך נשלחה בהצלחה ונחזור אליך בהקדם.')
        except Exception:
            logger.exception("Failed sending contact email notification")
            messages.error(request, 'הפנייה נשמרה במערכת, אך אירעה תקלה זמנית בשליחת ההתראה במייל. נחזור אליך בהקדם.')
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
    return books(request)

def qa_list(request, pk=None):
    selected_qa = None
    q = (request.GET.get('q') or '').strip()[:120]
    category = (request.GET.get('category') or '').strip()

    try:
        qs = QA.objects.all()
        try:
            qs = list(qs.order_by('-created_at'))
        except Exception:
            qs = list(qs.order_by('-id'))

        categories = sorted({
            (item.category or '').strip()
            for item in qs
            if (item.category or '').strip()
        })

        if q:
            q_clean = re.sub(r'[\u0591-\u05C7]', '', q).lower()
            q_vars = generate_word_variations(q_clean) if len(q_clean) >= 2 else [q_clean]
            filtered = []
            for item in qs:
                hay = re.sub(r'[\u0591-\u05C7]', '', f"{item.question or ''} {strip_tags(item.answer or '')} {item.category or ''}").lower()
                if any(v in hay for v in q_vars):
                    filtered.append(item)
            questions = filtered
        else:
            questions = qs

        if category:
            questions = [item for item in questions if (item.category or '').strip() == category]

        open_id = pk or request.GET.get('open')
        if open_id and str(open_id).isdigit():
            target_pk = int(open_id)
            selected_qa = next((item for item in qs if item.pk == target_pk), None)

    except Exception:
        questions = []
        categories = []

    context = {
        'questions': questions,
        'categories': categories,
        'selected_qa': selected_qa,
        'query': q,
        'q': q,
        'selected_category': category,
        'current_page': 'qa',
    }

    try:
        return render(request, 'articles/qa_list.html', context)
    except Exception:
        orig_get = request.GET
        clean_get = request.GET.copy()
        clean_get.pop('q', None)
        clean_get.pop('category', None)
        request.GET = clean_get
        resp = render(request, 'articles/qa_list.html', context)
        request.GET = orig_get
        if q:
            try:
                html_str = resp.content.decode('utf-8')
                html_str = html_str.replace('name="q"', f'name="q" value="{escape(q)}"', 1)
                resp.content = html_str.encode('utf-8')
            except Exception:
                logger.warning('Failed preserving QA search query value on fallback render', exc_info=True)
        return resp

def acronyms_view(request):
    query = request.GET.get('q', '').strip()[:120]
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

def parasha_list(request, parasha_name=None):
    query_p = (request.GET.get('p') or '').strip()
    if query_p and not parasha_name:
        resolved_q = _resolve_parasha_name(query_p)
        target_slug = _parasha_to_slug(resolved_q)
        if resolved_q in PARASHA_CANONICAL_NAMES and target_slug:
            return redirect('articles:parasha_detail', parasha_name=target_slug, permanent=True)
        raise Http404(f"הפרשה '{query_p}' לא נמצאה.")

    selected_parasha = None
    selected_parasha_slug = ''
    is_known_parasha = False
    articles = None
    if parasha_name:
        selected_parasha = _resolve_parasha_name(parasha_name)
        selected_parasha_slug = _parasha_to_slug(selected_parasha)
        if parasha_name != selected_parasha_slug and selected_parasha in PARASHA_CANONICAL_NAMES:
            return redirect('articles:parasha_detail', parasha_name=selected_parasha_slug, permanent=True)
        is_known_parasha = selected_parasha in PARASHA_CANONICAL_NAMES
        parasha_q = Q(parasha__icontains=f",{selected_parasha},") | Q(parasha=selected_parasha)
        articles = Article.objects.filter(parasha_q, is_published=True).order_by('-created_at')
        if not is_known_parasha and not articles.exists():
            raise Http404(f"הפרשה '{parasha_name}' לא נמצאה.")

    return render(request, 'articles/parasha_list.html', {
        'current_page': 'parasha',
        'selected_parasha': selected_parasha,
        'selected_parasha_slug': selected_parasha_slug,
        'is_known_parasha': is_known_parasha,
        'articles': articles,
    })

def book_detail(request, pk):
    book = get_object_or_404(
        Book.objects.prefetch_related('chapters__sections'),
        pk=pk
    )
    book_chapters = list(book.chapters.all())
    for chapter in book_chapters:
        chapter_sections = list(chapter.sections.all())
        for sec in chapter_sections:
            raw_sec_html = sanitize_unsafe_links_html(getattr(sec, 'content', '') or '')
            if raw_sec_html:
                norm_html = normalize_article_footnotes_html(raw_sec_html)
                sec.rendered_content = _scope_section_footnotes(norm_html, sec.pk)
            else:
                sec.rendered_content = ''
        chapter.rendered_sections = chapter_sections

    safe_book_summary = sanitize_unsafe_links_html(book.summary or '')
    rendered_book_summary = normalize_article_footnotes_html(safe_book_summary) if (safe_book_summary and not book_chapters) else safe_book_summary
    book_excerpt = _build_clean_excerpt(book.summary or book.title or '', max_words=35)

    return render(request, 'articles/book_detail.html', {
        'book': book,
        'book_chapters': book_chapters,
        'rendered_book_summary': rendered_book_summary,
        'book_excerpt': book_excerpt,
        'current_page': 'books',
    })

def books(request):
    q = (request.GET.get('q') or '').strip()[:120]
    books_ordered = Book.objects.all().order_by('order', 'title')
    return render(request, 'articles/books_list.html', {
        'books': books_ordered,
        'query': q,
        'q': q,
        'current_page': 'books',
    })

@ratelimit(rate=60, timeout=60)
def live_search(request):
    q = request.GET.get('q', '').strip()[:120]
    if len(q) < 2:
        return JsonResponse({'results': []})
    content_ver = _get_content_cache_version()
    cache_key = 'live_search_v' + str(content_ver) + '_' + hashlib.md5(q.encode('utf-8')).hexdigest()
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
    q = request.GET.get('q', '').strip()[:120]
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

@ratelimit(rate=30, timeout=60)
def add_to_cart(request, book_id):
    if not _is_safe_cart_action_request(request):
        return redirect('articles:books')
    book = Book.objects.filter(id=book_id, is_for_sale=True).first()
    if not book:
        return redirect('articles:books', permanent=True)
    if book.stock <= 0:
        messages.error(request, f'הספר "{book.title}" אזל זמנית מהמלאי.')
        return redirect('articles:book_detail', pk=book.pk)
    cart = _get_or_create_cart(request)
    cart_item, created = CartItem.objects.get_or_create(cart=cart, book=book)
    max_qty = min(int(book.stock), 99)
    if not created:
        if cart_item.quantity >= max_qty:
            messages.warning(request, f'לא ניתן להוסיף מעבר למלאי הזמין ({max_qty}) עבור "{book.title}".')
            return redirect('articles:cart_detail')
        cart_item.quantity += 1
        cart_item.save(update_fields=['quantity'])
    messages.success(request, f'הספר "{book.title}" נוסף לעגלת הקניות בהצלחה.')
    return redirect('articles:cart_detail')

@ratelimit(rate=30, timeout=60)
def remove_from_cart(request, item_id):
    if not _is_safe_cart_action_request(request):
        return redirect('articles:books')
    cart = _get_or_create_cart(request)
    item = CartItem.objects.filter(id=item_id, cart=cart).first()
    if item:
        item.delete()
        messages.info(request, 'הפריט הוסר מעגלת הקניות.')
    return redirect('articles:cart_detail')

def cart_detail(request):
    cart = _get_or_create_cart(request)
    items = cart.items.select_related('book').all()
    total_price = sum(item.get_total_price() for item in items)
    return render(request, 'articles/cart_detail.html', {'cart': cart, 'items': items, 'total_price': total_price, 'current_page': 'cart'})

@ratelimit(rate=10, timeout=300, methods=('POST',))
def checkout(request):
    cart = _get_or_create_cart(request)
    items = list(cart.items.select_related('book').all())
    if not items:
        messages.error(request, 'העגלה שלך ריקה. אנא הוסף ספרים לפני המעבר לקופה.')
        return redirect('articles:books')
    total_price = sum(item.get_total_price() for item in items)
    if request.method == 'POST':
        first_name = _sanitize_header_value(request.POST.get('first_name', ''), 50)
        last_name = _sanitize_header_value(request.POST.get('last_name', ''), 50)
        email = _sanitize_header_value(request.POST.get('email', ''), 254)
        phone = _sanitize_header_value(request.POST.get('phone', ''), 20)
        address = _sanitize_header_value(request.POST.get('address', ''), 250)
        city = _sanitize_header_value(request.POST.get('city', ''), 100)
        zip_code = _sanitize_header_value(request.POST.get('zip_code', ''), 20)
        notes = (request.POST.get('notes', '') or '').strip()[:2000]

        if not all([first_name, last_name, phone, address, city]) or not _EMAIL_SIMPLE_RE.match(email):
            messages.error(request, 'נא למלא את כל שדות החובה בצורה תקינה (כולל כתובת אימייל חוקית).')
            return render(request, 'articles/checkout.html', {'items': items, 'total_price': total_price, 'current_page': 'cart'})

        insufficient_book = None
        order = None
        with transaction.atomic():
            locked_items = []
            verified_total = 0
            for item in items:
                locked_book = Book.objects.select_for_update().filter(pk=item.book_id, is_for_sale=True).first()
                if item.quantity <= 0 or not locked_book or locked_book.stock < item.quantity:
                    insufficient_book = item.book.title if item.book else 'אחד הספרים'
                    break
                locked_items.append((locked_book, item.quantity))
                verified_total += locked_book.price * item.quantity

            if not insufficient_book:
                order = Order.objects.create(
                    first_name=first_name, last_name=last_name, email=email, phone=phone,
                    address=address, city=city, zip_code=zip_code, notes=notes,
                    total_paid=verified_total, status='pending'
                )
                for locked_book, qty in locked_items:
                    OrderItem.objects.create(order=order, book=locked_book, price=locked_book.price, quantity=qty)
                    locked_book.stock -= qty
                    locked_book.save(update_fields=['stock'])
                cart.items.all().delete()

        if insufficient_book:
            messages.error(request, f'המלאי הזמין עבור "{insufficient_book}" אינו מספיק להשלמת ההזמנה.')
            return redirect('articles:cart_detail')

        try:
            send_order_confirmation(order)
        except Exception:
            logger.exception("Failed sending order confirmation email for order %s", order.pk)
        return render(request, 'articles/order_success.html', {'order': order})
    return render(request, 'articles/checkout.html', {'items': items, 'total_price': total_price, 'current_page': 'cart'})

def ping_indexnow(article_url):
    host = "leblibrary.co.il"
    key = os.environ.get('INDEXNOW_KEY', '').strip() or getattr(settings, 'INDEXNOW_KEY', '').strip()
    if not key:
        return
    url = f"https://api.indexnow.org/indexnow?url={urllib.parse.quote(article_url)}&key={key}&keyLocation=https://{host}/{key}.txt"
    try:
        _IPV4_OPENER.open(url, timeout=5)
    except Exception:
        logger.warning("IndexNow ping failed for %s", article_url)

@receiver([post_save, post_delete], sender=Article)
@receiver([post_save, post_delete], sender=Book)
@receiver([post_save, post_delete], sender=QA)
def clear_cache_on_db_change(sender, instance, **kwargs):
    _bump_content_cache_version()
    ClusterEngine.clear_memory_cache()

def load_tts_dictionary():
    dict_path = os.path.join(settings.BASE_DIR, 'tts_dictionary.json')
    if not os.path.exists(dict_path):
        dict_path = os.path.join(settings.BASE_DIR, 'articles', 'tts_dictionary.json')

    if os.path.exists(dict_path):
        try:
            with open(dict_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data["או'"] = "אומר"
                data["ואו'"] = "ואומר"
                return data
        except Exception:
            logger.warning('Failed loading TTS dictionary %s', dict_path, exc_info=True)

    return {
        "או'": 'אומר', "ואו'": 'ואומר',
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

    text = re.sub(r"(?<![א-ת])(ו?)או['׳’](?![א-ת])", r"\1אומר", text)

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
    tmp_path = f"{file_path}.{os.getpid()}.{threading.get_ident()}.tmp"

    async def _generate():
        communicate = edge_tts.Communicate(text, "he-IL-AvriNeural")
        await asyncio.wait_for(communicate.save(tmp_path), timeout=90)

    try:
        asyncio.run(_generate())
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            os.replace(tmp_path, file_path)
        else:
            raise OSError("Generated audio file was empty")
    except Exception as e:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                logger.debug('Failed removing temp audio file %s', tmp_path, exc_info=True)
        raise RuntimeError(f"Edge-TTS Error: {str(e)}") from e

def _collect_article_audio_text(article):
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
        logger.warning("Failed collecting linked sections for article audio %s", article.pk)
    return apply_tts_dictionary(raw_text)

def _collect_book_audio_text(book):
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
        logger.warning("Failed collecting chapters for book audio %s", book.pk)
    return apply_tts_dictionary(raw_text)

def _spawn_audio_generation_job(job_key, file_path, text_builder):
    lock_cache_key = f"audio_gen_lock_{job_key}"
    with _AUDIO_JOBS_LOCK:
        if job_key in _AUDIO_JOBS_IN_PROGRESS:
            return False
        if len(_AUDIO_JOBS_IN_PROGRESS) >= _MAX_CONCURRENT_AUDIO_JOBS:
            return False
        if not cache.add(lock_cache_key, 1, 240):
            return False
        _AUDIO_JOBS_IN_PROGRESS.add(job_key)

    def _worker():
        try:
            if not os.path.exists(file_path):
                final_text = text_builder()
                if final_text:
                    generate_audio_sync(final_text, file_path)
        except Exception:
            logger.exception("Background audio generation failed for %s", job_key)
        finally:
            cache.delete(lock_cache_key)
            with _AUDIO_JOBS_LOCK:
                _AUDIO_JOBS_IN_PROGRESS.discard(job_key)

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    return True

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
            _spawn_audio_generation_job(
                f"article_{article.id}",
                file_path,
                lambda: _collect_article_audio_text(Article.objects.get(id=article_id)),
            )
    except Exception:
        logger.warning("Failed scheduling background article audio for %s", article_id)

@receiver(post_save, sender=Article)
def trigger_article_audio_pregeneration(sender, instance, created, **kwargs):
    if instance.is_published:
        base_media = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
        file_path = os.path.join(base_media, 'audio', f"article_{instance.id}.mp3")
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                logger.warning('Failed removing stale audio file %s', file_path, exc_info=True)

        transaction.on_commit(lambda: generate_article_audio_background(instance.id))

@ratelimit(rate=20, timeout=300)
def get_article_audio(request, identifier):
    try:
        if str(identifier).isdigit():
            article = Article.objects.get(id=int(identifier))
        else:
            article = Article.objects.get(slug=identifier)
    except Article.DoesNotExist:
        return JsonResponse({'error': 'Article not found'}, status=404)

    if not article.is_published and not request.user.is_superuser:
        return JsonResponse({'error': 'Article not found'}, status=404)

    base_media = getattr(settings, 'MEDIA_ROOT', os.path.join(settings.BASE_DIR, 'media'))
    audio_dir = os.path.join(base_media, 'audio')
    os.makedirs(audio_dir, exist_ok=True)

    file_name = f"article_{article.id}.mp3"
    file_path = os.path.join(audio_dir, file_name)
    media_url = getattr(settings, 'MEDIA_URL', '/media/')

    if not os.path.exists(file_path):
        art_id = article.id
        _spawn_audio_generation_job(
            f"article_{art_id}",
            file_path,
            lambda: _collect_article_audio_text(Article.objects.get(id=art_id)),
        )
        return JsonResponse({'status': 'generating', 'retry_after': 3}, status=202)

    file_version = int(os.path.getmtime(file_path)) if os.path.exists(file_path) else 1
    audio_url = f"{media_url}audio/{file_name}?v={file_version}"
    return JsonResponse({'audio_url': audio_url})

@ratelimit(rate=20, timeout=300)
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
        b_id = book.id
        _spawn_audio_generation_job(
            f"book_{b_id}",
            file_path,
            lambda: _collect_book_audio_text(Book.objects.get(id=b_id)),
        )
        return JsonResponse({'status': 'generating', 'retry_after': 3}, status=202)

    file_version = int(os.path.getmtime(file_path)) if os.path.exists(file_path) else 1
    audio_url = f"{media_url}audio/{file_name}?v={file_version}"
    return JsonResponse({'audio_url': audio_url})

@ratelimit(rate=60, timeout=60)
def search_acronyms_api(request):
    query = request.GET.get('q', '').strip()[:120]
    search_type = request.GET.get('type', 'short')

    results = []
    if len(query) >= 1:
        query_clean = re.sub(r'["״”“\'׳`]', '', query)
        query_with_gershayim = query_clean
        query_with_geresh = query_clean
        if len(query_clean) > 1:
            query_with_gershayim = query_clean[:-1] + '"' + query_clean[-1]
            query_with_geresh = query_clean[:-1] + "'" + query_clean[-1]

        if search_type == 'meaning':
            matches = Acronym.objects.filter(meaning__icontains=query)[:20]
        else:
            matches = Acronym.objects.filter(
                Q(short__icontains=query) |
                Q(short__icontains=query_clean) |
                Q(short__icontains=query_with_gershayim) |
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

def aramaic_translator_view(request):
    context = _get_aramaic_context(request)
    return render(request, 'articles/aramaic_translator.html', context)

@ratelimit(rate=30, timeout=60)
def aramaic_translate_api(request):
    payload, status_code = execute_aramaic_translation(request)
    return JsonResponse(payload, status=status_code, json_dumps_params={'ensure_ascii': False})