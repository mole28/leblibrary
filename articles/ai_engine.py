import json
import urllib.request
import re
import os
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q, Case, When, Value, IntegerField
from django.urls import reverse

from .models import Article, Chapter, Section, TorahText, QA, Acronym
from .vector_store import search_similar_articles
from .torah_engine import (
    TANAKH_NAMES, TORAH_NAMES, TORAH_CORE_CONCEPTS,
    calculate_gematria, format_divine_name, ratelimit,
    format_verse_hebrew, generate_word_variations,
    _resolve_torah_book_in_db, _resolve_torah_verse_obj, _IPV4_OPENER
)


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
    score_expr += Case(
        When(**{f"{search_fields[0]}__icontains": query}, then=Value(50)),
        default=Value(0),
        output_field=IntegerField()
    )
    for word in words:
        for var in generate_word_variations(word):
            score_expr += Case(
                When(**{f"{search_fields[0]}__icontains": var}, then=Value(10)),
                default=Value(0),
                output_field=IntegerField()
            )
            if len(search_fields) > 1:
                score_expr += Case(
                    When(**{f"{search_fields[1]}__icontains": var}, then=Value(2)),
                    default=Value(0),
                    output_field=IntegerField()
                )

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
            sections = item.sections.all() if hasattr(item, 'sections') else (item.section_set.all() if hasattr(item, 'section_set') else None)
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
        full_text = (get_item_title(item) + " " + get_item_text(item)).lower()
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
    return [c for c in candidates if get_score(c) > 0][:limit]


def get_smart_content(text, query_words, max_chars=40000):
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    if not query_words:
        return text[:max_chars]

    best_idx = 0
    max_score = -1
    step = max_chars // 2
    text_lower = text.lower()

    for i in range(0, len(text), step):
        chunk = text_lower[i : i + max_chars]
        score = sum(chunk.count(w.lower()) for w in query_words)
        if score > max_score:
            max_score = score
            best_idx = i

    start = max(0, best_idx)
    end = min(len(text), start + max_chars)
    return ("... " if start > 0 else "") + text[start:end] + (" ..." if end < len(text) else "")


@csrf_exempt
@ratelimit(rate=20, timeout=86400)
def ai_chat_endpoint(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Invalid method'}, status=400)

    try:
        API_KEY = os.environ.get('GEMINI_API_KEY', '').strip()
        if not API_KEY:
            return JsonResponse({'answer': 'Error: Missing API key.'})

        data = json.loads(request.body)
        user_question = data.get('question', '')
        mode = data.get('mode', 'content')

        if not user_question:
            return JsonResponse({'answer': 'Please provide a question.'})

        unique_relevant_items = []

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
            words = [w for w in clean_question.split() if len(w) > 1 and w not in stop_words] or [w for w in clean_question.split() if len(w) > 1]

            semantic_results = []
            try:
                semantic_results = search_similar_articles(user_question, top_k=2)
            except Exception:
                pass

            db_articles = ai_document_search(Article.objects.filter(is_published=True), clean_question, get_text_fields(Article), words, limit=2)
            db_chapters = ai_document_search(Chapter.objects.all(), clean_question, get_text_fields(Chapter), words, limit=3)
            db_sections = ai_document_search(Section.objects.all(), clean_question, get_text_fields(Section), words, limit=2)
            db_qas = ai_document_search(QA.objects.all(), clean_question, get_text_fields(QA), words, limit=2)

            acronym_matches = []
            try:
                acronym_matches = list(Acronym.objects.filter(Q(short__icontains=user_question) | Q(meaning__icontains=user_question))[:5])
            except Exception:
                pass

            context_text = ""
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

            for item in semantic_results:
                add_to_context(item.get('title', ''), item.get('url', ''), item.get('content_snippet', ''))

            for a in db_articles:
                add_to_context(get_item_title(a), request.build_absolute_uri(reverse('articles:detail', args=[a.slug])), get_smart_content(get_item_text(a), words, max_chars=8000))

            for c in db_chapters:
                try:
                    book_id = getattr(c, 'book_id', None) or (c.book.id if hasattr(c, 'book') else None)
                    if book_id:
                        url = f"{request.build_absolute_uri(reverse('articles:book_detail', args=[book_id]))}#chapter-{c.id}"
                        title = f"{get_item_title(c.book) if hasattr(c, 'book') else 'ספר'} - {get_item_title(c)}"
                        add_to_context(title, url, get_smart_content(get_item_text(c), words, max_chars=8000))
                except Exception:
                    pass

            for s in db_sections:
                try:
                    chapter = getattr(s, 'chapter', None)
                    if chapter:
                        book_id = getattr(chapter, 'book_id', None) or (chapter.book.id if hasattr(chapter, 'book') else None)
                        if book_id:
                            url = f"{request.build_absolute_uri(reverse('articles:book_detail', args=[book_id]))}#chapter-{chapter.id}"
                            title = f"{get_item_title(chapter.book) if hasattr(chapter, 'book') else 'ספר'} - {get_item_title(chapter)}"
                            add_to_context(title, url, get_smart_content(get_item_text(s), words, max_chars=8000))
                except Exception:
                    pass

            for qa_item in db_qas:
                try:
                    add_to_context(f"שו\"ת - {get_item_title(qa_item)}", request.build_absolute_uri(reverse('articles:qa')), get_smart_content(get_item_text(qa_item), words, max_chars=8000))
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
            KNOWN_GOOD_MODELS = ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-flash-latest', 'gemini-pro-latest']
            data_bytes = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}, ensure_ascii=False).encode('utf-8')
            response = None
            last_error = ""

            for model in KNOWN_GOOD_MODELS:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={API_KEY}"
                req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
                try:
                    response = _IPV4_OPENER.open(req, timeout=25)
                    break
                except Exception as e:
                    last_error = str(e)

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
                                link_color = "#2575fc" if mode == 'nav' else "#d4af37"
                                target_attr = "_self" if mode == 'nav' else "_blank"
                                text_chunk = re.sub(
                                    r'\[([^\]]+)\]\(([^)]+)\)',
                                    rf'<a href="\2" target="{target_attr}" style="color: {link_color}; font-weight: bold; text-decoration: underline;">\1</a>',
                                    text_chunk
                                ).replace('*', '')
                                yield text_chunk
                        except json.JSONDecodeError:
                            continue

                if mode != 'nav' and unique_relevant_items and "לא מצאתי לכך התייחסות מפורשת" not in full_generated_text:
                    sources_list_html = ""
                    for item in unique_relevant_items:
                        title, url = item.get('title', ''), item.get('url', '')
                        if title and url:
                            title_part = title.split('-')[-1].strip()
                            if title in full_generated_text or (len(title_part) >= 4 and title_part in full_generated_text):
                                sources_list_html += f"<li style='margin-bottom: 5px;'><a href='{url}' target='_blank' style='color: #d4af37; font-weight: bold; text-decoration: underline;'>{title}</a></li>"
                    if sources_list_html:
                        yield (
                            "<br><br><div style='margin-top: 15px; padding-top: 10px; border-top: 1px solid #e0e0e0; font-size: 0.95em;'>"
                            "<strong>📚 מקורות מהספרייה (לחיץ):</strong>"
                            f"<ul style='margin-top: 8px; padding-right: 20px; list-style-type: square;'>{sources_list_html}</ul></div>"
                        )
            except Exception as e:
                yield f"\n\n[החיבור נקטע: {str(e)}]"
            finally:
                response.close()

        return StreamingHttpResponse(stream_google_response(), content_type='text/plain')
    except Exception as e:
        return JsonResponse({'answer': f'שגיאת שרת פנימית: {str(e)}'})


@ratelimit(rate=30, timeout=60)
def torah_ai_insights_api(request):
    mode = request.GET.get('mode', 'code_finder').strip()
    query = request.GET.get('q', '').strip()
    book = _resolve_torah_book_in_db(request.GET.get('book', '').strip())
    chapter = request.GET.get('chapter', '').strip()
    verse = request.GET.get('verse', '').strip()

    cache_key = f"torah_ai_v10_{mode}_{book}_{chapter}_{verse}_{query}"
    cached_resp = cache.get(cache_key)
    if cached_resp:
        return JsonResponse(cached_resp, json_dumps_params={'ensure_ascii': False})

    FINAL_TO_REGULAR = str.maketrans({'ך': 'כ', 'ם': 'מ', 'ן': 'נ', 'ף': 'פ', 'ץ': 'צ'})
    REGULAR_TO_FINAL = {'כ': 'ך', 'מ': 'ם', 'נ': 'ן', 'פ': 'ף', 'צ': 'ץ'}
    NON_HEB_RE = re.compile(r'[^א-ת]+')
    WORD_TOKEN_RE = re.compile(r'[א-ת\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]+')
    HEB_LETTER_CLUSTER_RE = re.compile(r'[א-ת][\u0591-\u05bd\u05bf\u05c1\u05c2\u05c4\u05c5\u05c7]*')

    norm_heb = lambda s: s.translate(FINAL_TO_REGULAR)

    def reverse_heb_word(w):
        rev = w[::-1]
        if len(rev) <= 1:
            return rev
        return norm_heb(rev[:-1]) + REGULAR_TO_FINAL.get(norm_heb(rev[-1]), norm_heb(rev[-1]))

    def call_gemini_fast(prompt_text):
        api_key = os.environ.get('GEMINI_API_KEY', '').strip() or getattr(settings, 'GEMINI_API_KEY', '').strip()
        if not api_key:
            return ""
        data_bytes = json.dumps({"contents": [{"parts": [{"text": prompt_text}]}]}, ensure_ascii=False).encode('utf-8')
        for m_name in ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash-latest']:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{m_name}:generateContent?key={api_key}"
            req = urllib.request.Request(url, data=data_bytes, headers={'Content-Type': 'application/json'})
            try:
                with _IPV4_OPENER.open(req, timeout=4.5) as resp:
                    resp_data = json.loads(resp.read().decode('utf-8'))
                    ans = resp_data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
                    if ans and len(ans.strip()) > 20:
                        return format_divine_name(re.sub(r'[*#]+', '', ans).strip())
            except Exception:
                continue
        return ""

    def extract_highlighted_snippet(raw_text, matched_spans, max_len=340):
        if not raw_text:
            return ""
        if not matched_spans:
            return format_divine_name(raw_text[:max_len] + ("..." if len(raw_text) > max_len else ""))
        first_s, first_e = matched_spans[0]
        if len(raw_text) > max_len:
            half = max_len // 2
            win_start, win_end = max(0, first_s - half), min(len(raw_text), first_e + half)
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

        out = ["... "] if win_start > 0 else []
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

    torah_set, tanakh_set = set(TORAH_NAMES), set(TANAKH_NAMES)

    def analyze_concept_deeply(raw_query):
        clean_q = re.sub(r'[^א-ת\s]', '', raw_query.replace('י-ה-ו-ה', 'יהוה')).strip()
        search_core = re.sub(r'^(פרשת|הלכות|מסכת|מצוות|מצות|עניין|דיני)\s+', '', clean_q).strip() or clean_q
        q_words = [w for w in search_core.split() if len(w) >= 1]
        q_gem = calculate_gematria(search_core)
        q_norm = norm_heb(NON_HEB_RE.sub('', search_core))

        base_qs = TorahText.objects.all()
        for w in q_words:
            base_qs = base_qs.filter(Q(clean_text__icontains=w) | Q(text_with_nikkud__icontains=w))

        candidates = (
            list(base_qs.filter(book__in=TANAKH_NAMES).exclude(chapter__startswith='דף').values('id', 'book', 'chapter', 'verse', 'clean_text', 'text_with_nikkud', 'verse_gematria')[:800]) +
            list(base_qs.exclude(book__in=TANAKH_NAMES).values('id', 'book', 'chapter', 'verse', 'clean_text', 'text_with_nikkud', 'verse_gematria')[:1200]) +
            list(base_qs.filter(book__in=TANAKH_NAMES, chapter__startswith='דף').values('id', 'book', 'chapter', 'verse', 'clean_text', 'text_with_nikkud', 'verse_gematria')[:400])
        )

        corpus_counts = {'torah': 0, 'nach': 0, 'mishnah_tosefta': 0, 'talmud': 0, 'halacha': 0}
        book_freq, chapter_freq, valid_records = {}, {}, []
        num_q_words = len(q_words)

        for row in candidates:
            raw_txt = row.get('text_with_nikkud') or row.get('clean_text') or ''
            if not raw_txt:
                continue
            tok_words, tok_spans = [], []
            for tok in WORD_TOKEN_RE.finditer(raw_txt):
                w_heb = NON_HEB_RE.sub('', tok.group(0))
                if w_heb:
                    tok_words.append(w_heb)
                    tok_spans.append(tok.span())
            if len(tok_words) < num_q_words:
                continue

            exact_spans, prefix_spans = [], []
            if num_q_words == 1:
                tw = q_words[0]
                for idx_t, vw in enumerate(tok_words):
                    if vw == tw:
                        exact_spans.append(tok_spans[idx_t])
                    elif len(vw) == len(tw) + 1 and vw[0] in 'משהוכלב' and vw[1:] == tw:
                        prefix_spans.append(tok_spans[idx_t])
            else:
                for i in range(len(tok_words) - num_q_words + 1):
                    is_ex, is_pr = True, True
                    for j in range(num_q_words):
                        tw, vw = q_words[j], tok_words[i + j]
                        if vw != tw:
                            is_ex = False
                            if not (len(vw) == len(tw) + 1 and vw[0] in 'משהוכלב' and vw[1:] == tw):
                                is_pr = False
                                break
                    if is_ex:
                        exact_spans.extend(tok_spans[i : i + num_q_words])
                    elif is_pr:
                        prefix_spans.extend(tok_spans[i : i + num_q_words])

            if not exact_spans and not prefix_spans:
                continue

            b_name, c_name = row['book'], row['chapter']
            if b_name in torah_set and not str(c_name).startswith('דף'):
                cat = 'torah'
            elif b_name in tanakh_set and not str(c_name).startswith('דף'):
                cat = 'nach'
            elif b_name.startswith(('רמב"ם ', 'שולחן ערוך ')):
                cat = 'halacha'
            elif str(c_name).startswith('דף') or b_name.startswith('ירושלמי '):
                cat = 'talmud'
            else:
                cat = 'mishnah_tosefta'

            corpus_counts[cat] += 1
            book_freq[b_name] = book_freq.get(b_name, 0) + 1
            chapter_freq[(b_name, c_name)] = chapter_freq.get((b_name, c_name), 0) + 1

            row.update({
                '_cat': cat, '_exact_count': len(exact_spans),
                '_weight': len(exact_spans) * 5 + len(prefix_spans),
                '_spans': exact_spans or prefix_spans, '_raw_txt': raw_txt
            })
            valid_records.append(row)

        for row in valid_records:
            b_name, c_name = row['book'], row['chapter']
            row['_score'] = (
                (1000 if row['_exact_count'] > 0 else 100) +
                row['_weight'] * 20 +
                chapter_freq.get((b_name, c_name), 0) * 15 +
                min(book_freq.get(b_name, 0), 30) * 5 +
                (800 if search_core in b_name else 0) +
                (50 if not b_name.startswith('ירושלמי ') else 0)
            )

        valid_records.sort(key=lambda x: x['_score'], reverse=True)

        def pick_top_sources(records_subset, limit=3):
            picked, seen_ch = [], set()
            for r in records_subset:
                key = (r['book'], r['chapter'])
                if key not in seen_ch:
                    seen_ch.add(key)
                    v_heb_str = format_verse_hebrew(r['verse'])
                    picked.append({
                        'book': r['book'], 'chapter': r['chapter'], 'verse': v_heb_str,
                        'ref': f"{r['book']} {r['chapter']}:{v_heb_str}",
                        'text': extract_highlighted_snippet(r['_raw_txt'], r['_spans'])
                    })
                    if len(picked) >= limit:
                        break
            return picked

        top_tanakh = pick_top_sources([r for r in valid_records if r['_cat'] in ('torah', 'nach')], limit=3)
        top_chazal = pick_top_sources([r for r in valid_records if r['_cat'] in ('talmud', 'mishnah_tosefta')], limit=3)
        top_halacha = pick_top_sources([r for r in valid_records if r['_cat'] == 'halacha'], limit=2)
        dominant_books = [{'book': b, 'score': s} for b, s in sorted(book_freq.items(), key=lambda x: x[1], reverse=True)[:5]]

        gem_concepts = [c for c in TORAH_CORE_CONCEPTS if c != search_core and calculate_gematria(c) == q_gem]
        gem_tanakh_verses, gem_word_verses = [], []

        if q_gem > 0:
            for gv in TorahText.objects.filter(book__in=TANAKH_NAMES, verse_gematria=q_gem).exclude(chapter__startswith='דף').values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')[:2]:
                gem_tanakh_verses.append({
                    'ref': f"{gv['book']} {gv['chapter']}:{format_verse_hebrew(gv['verse'])}",
                    'text': format_divine_name(gv['text_with_nikkud'] or gv['clean_text'])
                })
            seen_gem_words = set()
            for gw in TorahText.objects.filter(book__in=TORAH_NAMES, words_gematria__contains=f",{q_gem},").exclude(chapter__startswith='דף').values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')[:25]:
                raw_t = gw.get('text_with_nikkud') or gw.get('clean_text') or ''
                for tok in WORD_TOKEN_RE.finditer(raw_t):
                    w_clean = NON_HEB_RE.sub('', tok.group(0))
                    if len(w_clean) >= 2 and w_clean != search_core and calculate_gematria(w_clean) == q_gem:
                        if w_clean not in gem_concepts and len(gem_concepts) < 6:
                            gem_concepts.append(w_clean)
                        if w_clean not in seen_gem_words and len(gem_word_verses) < 2:
                            seen_gem_words.add(w_clean)
                            gem_word_verses.append({
                                'word': w_clean,
                                'ref': f"{gw['book']} {gw['chapter']}:{format_verse_hebrew(gw['verse'])}",
                                'text': extract_highlighted_snippet(raw_t, [tok.span()])
                            })

        rev_str = " ".join([reverse_heb_word(w) for w in q_words])
        rev_matches = []
        if rev_str and rev_str != search_core and len(q_words) == 1 and len(q_words[0]) >= 2:
            for rm in TorahText.objects.filter(book__in=TANAKH_NAMES, clean_text__icontains=rev_str).exclude(chapter__startswith='דף').values('book', 'chapter', 'verse', 'text_with_nikkud', 'clean_text')[:50]:
                raw_t = rm.get('text_with_nikkud') or rm.get('clean_text') or ''
                hit_spans = [t.span() for t in WORD_TOKEN_RE.finditer(raw_t) if NON_HEB_RE.sub('', t.group(0)) == rev_str]
                if hit_spans:
                    rev_matches.append({
                        'word': rev_str,
                        'ref': f"{rm['book']} {rm['chapter']}:{format_verse_hebrew(rm['verse'])}",
                        'text': extract_highlighted_snippet(raw_t, hit_spans)
                    })
                    if len(rev_matches) >= 2:
                        break

        rashei_matches, sofei_matches, els_matches = [], [], []
        if 2 <= len(q_norm) <= 6:
            k_len = len(q_norm)
            for item in TorahText.objects.filter(book__in=TORAH_NAMES).exclude(chapter__startswith='דף').values('book', 'chapter', 'verse', 'clean_text', 'text_with_nikkud')[:600]:
                raw_t = item.get('text_with_nikkud') or item.get('clean_text') or ''
                t_words, t_spans = [], []
                for t in WORD_TOKEN_RE.finditer(raw_t):
                    wh = NON_HEB_RE.sub('', t.group(0))
                    if wh:
                        t_words.append(norm_heb(wh))
                        t_spans.append(t.span())
                v_heb_item = format_verse_hebrew(item['verse'])
                if len(t_words) >= k_len:
                    if len(rashei_matches) < 2:
                        pos_r = "".join([w[0] for w in t_words]).find(q_norm)
                        if pos_r != -1:
                            spans_r = t_spans[pos_r : pos_r + k_len]
                            rashei_matches.append({
                                'ref': f"{item['book']} {item['chapter']}:{v_heb_item}",
                                'phrase': " ".join([NON_HEB_RE.sub('', raw_t[s:e]) for s, e in spans_r]),
                                'text': extract_highlighted_snippet(raw_t, spans_r)
                            })
                    if len(sofei_matches) < 2:
                        pos_s = "".join([w[-1] for w in t_words]).find(q_norm)
                        if pos_s != -1:
                            spans_s = t_spans[pos_s : pos_s + k_len]
                            sofei_matches.append({
                                'ref': f"{item['book']} {item['chapter']}:{v_heb_item}",
                                'phrase': " ".join([NON_HEB_RE.sub('', raw_t[s:e]) for s, e in spans_s]),
                                'text': extract_highlighted_snippet(raw_t, spans_s)
                            })
                if len(els_matches) < 2:
                    letters_only = NON_HEB_RE.sub('', item.get('clean_text') or '').translate(FINAL_TO_REGULAR)
                    n_l = len(letters_only)
                    if n_l >= k_len:
                        for p0 in range(n_l):
                            if letters_only[p0] != q_norm[0]:
                                continue
                            found_els = False
                            for st in range(2, min(12, (n_l - 1 - p0) // (k_len - 1)) + 1):
                                if letters_only[p0 : p0 + k_len * st : st] == q_norm:
                                    target_positions = {p0 + idx * st for idx in range(k_len)}
                                    g_idx = [-1]
                                    def mark_els_char(c_m):
                                        g_idx[0] += 1
                                        cl = c_m.group(0)
                                        return f'<mark style="background-color: #fde047; color: #000; padding: 0 3px; border-radius: 3px; font-weight: bold; border-bottom: 2px solid #b8860b;">{cl}</mark>' if g_idx[0] in target_positions else cl
                                    els_matches.append({
                                        'ref': f"{item['book']} {item['chapter']}:{v_heb_item}",
                                        'skip': st - 1,
                                        'text': format_divine_name(HEB_LETTER_CLUSTER_RE.sub(mark_els_char, raw_t))
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
                t_str, c_str = art.title or '', re.sub(r'<[^>]+>', ' ', art.content or '')
                toks_t = [NON_HEB_RE.sub('', m.group(0)) for m in WORD_TOKEN_RE.finditer(t_str)]
                in_title = any(w in toks_t for w in q_words if len(w) >= 2)
                toks_c = [m for m in WORD_TOKEN_RE.finditer(c_str) if NON_HEB_RE.sub('', m.group(0)) in q_words]
                if in_title or len(toks_c) >= 5:
                    verified_articles.append({
                        'title': t_str.strip(),
                        'url': reverse('articles:detail', args=[art.slug]),
                        'snippet': extract_highlighted_snippet(c_str, [m.span() for m in toks_c], max_len=240),
                        'score': (100 if in_title else 0) + len(toks_c)
                    })
            verified_articles.sort(key=lambda x: x['score'], reverse=True)
            verified_articles = verified_articles[:2]
        except Exception:
            verified_articles = []

        return {
            'query': raw_query, 'search_core': search_core, 'gematria': q_gem,
            'total_matches': sum(corpus_counts.values()), 'corpus_counts': corpus_counts,
            'dominant_books': dominant_books, 'top_tanakh': top_tanakh,
            'top_chazal': top_chazal, 'top_halacha': top_halacha,
            'gem_concepts': gem_concepts, 'gem_tanakh_verses': gem_tanakh_verses,
            'gem_word_verses': gem_word_verses, 'rashei_matches': rashei_matches,
            'sofei_matches': sofei_matches, 'els_matches': els_matches,
            'reversed_word': rev_str if rev_str != search_core else '',
            'rev_matches': rev_matches, 'verified_articles': verified_articles
        }

    try:
        if mode == 'code_finder':
            verse_obj = _resolve_torah_verse_obj(book, chapter, verse) if (book and chapter and verse) else (
                TorahText.objects.filter(clean_text__icontains=re.sub(r'[^א-ת\s]', '', query).strip()).first() if query else None
            )
            if not verse_obj:
                return JsonResponse({'error': 'לא נמצא פסוק או מקור לניתוח.'}, status=404)

            v_heb_disp = format_verse_hebrew(verse_obj.verse)
            raw_text = format_divine_name(verse_obj.text_with_nikkud or verse_obj.clean_text)
            clean_words = [w for w in [NON_HEB_RE.sub('', m.group(0)) for m in WORD_TOKEN_RE.finditer(raw_text)] if len(w) >= 2]
            v_gem = verse_obj.verse_gematria or calculate_gematria(verse_obj.clean_text or '')

            equal_verses = [
                {'ref': f"{ev.book} {ev.chapter}:{format_verse_hebrew(ev.verse)}", 'text': format_divine_name(ev.text_with_nikkud or ev.clean_text)}
                for ev in TorahText.objects.filter(book__in=TANAKH_NAMES, verse_gematria=v_gem).exclude(id=verse_obj.id).exclude(chapter__startswith='דף')[:4]
            ]

            word_gem_matches, seen_words = [], set()
            for w in clean_words:
                if w not in seen_words:
                    seen_words.add(w)
                    w_val = calculate_gematria(w)
                    for concept in TORAH_CORE_CONCEPTS:
                        if concept != w and calculate_gematria(concept) == w_val:
                            word_gem_matches.append({'word': w, 'concept': concept, 'val': w_val})
                    if len(word_gem_matches) >= 6:
                        break

            letters_seq = NON_HEB_RE.sub('', raw_text).translate(FINAL_TO_REGULAR)
            els_findings, n_len = [], len(letters_seq)
            for concept in TORAH_CORE_CONCEPTS:
                c_norm = norm_heb(concept)
                k = len(c_norm)
                if k < 3 or n_len < k:
                    continue
                found_c = False
                for pos0 in range(n_len):
                    if letters_seq[pos0] != c_norm[0]:
                        continue
                    for step in range(2, min(15, (n_len - 1 - pos0) // (k - 1)) + 1):
                        if letters_seq[pos0 : pos0 + k * step : step] == c_norm:
                            els_findings.append({'word': concept, 'skip': step - 1})
                            found_c = True
                            break
                    if found_c:
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
                        acronym_findings.append({'type': 'ראשי תיבות', 'word': concept, 'phrase': " ".join(clean_words[idx_r : idx_r + len(c_norm)])})
                    idx_s = sofei_seq.find(c_norm)
                    if idx_s != -1:
                        acronym_findings.append({'type': 'סופי תיבות', 'word': concept, 'phrase': " ".join(clean_words[idx_s : idx_s + len(c_norm)])})

            summary_parts = [f"המקור ב{verse_obj.book} ({verse_obj.chapter}, {v_heb_disp}) מחזיק {len(clean_words)} תיבות וערכו הגימטרי הכולל הוא {v_gem}."]
            if equal_verses:
                summary_parts.append(f"במאגר התנ\"ך נמצאה הקבלה גימטרית מדויקת ({v_gem}) לפסוק ב{equal_verses[0]['ref']}: \"{equal_verses[0]['text']}\".")
            if word_gem_matches:
                summary_parts.append("הקבלות גימטריה במילות המקור: " + ", ".join([f"התיבה \"{m['word']}\" שווה בגימטריה ({m['val']}) למושג \"{m['concept']}\"" for m in word_gem_matches[:3]]) + ".")
            if els_findings:
                summary_parts.append("בסריקת מרווחי אותיות (ELS) לאורך המקור אותרו המושגים: " + ", ".join([f"\"{e['word']}\" (דילוג {e['skip']})" for e in els_findings[:3]]) + ".")
            if acronym_findings:
                summary_parts.append("ממצאי ראשי וסופי תיבות: " + ", ".join([f"{a['type']} \"{a['word']}\" בתיבות \"{a['phrase']}\"" for a in acronym_findings[:2]]) + ".")

            resp_payload = {
                'source_ref': f"{verse_obj.book} | {verse_obj.chapter} | {v_heb_disp}",
                'text': raw_text, 'verse_gematria': v_gem, 'equal_verses': equal_verses,
                'word_gematria_matches': word_gem_matches, 'els_findings': els_findings,
                'acronym_findings': acronym_findings, 'ai_commentary': " ".join(summary_parts)
            }
            cache.set(cache_key, resp_payload, 3600 * 12)
            return JsonResponse(resp_payload, json_dumps_params={'ensure_ascii': False})

        elif mode == 'concept_map':
            if not query:
                return JsonResponse({'error': 'יש להזין מושג למיפוי.'}, status=400)
            analysis = analyze_concept_deeply(query)
            q_gem, cc, core = analysis['gematria'], analysis['corpus_counts'], analysis['search_core']

            nodes = [{
                'id': 'root', 'label': f"{core}\n(גימטריה: {q_gem})", 'group': 'center', 'url': '',
                'snippet': (
                    f"<b>מושג המפתח: \"{core}\"</b> (גימטריה: <b>{q_gem}</b>) | "
                    f"נמצאו <b>{analysis['total_matches']}</b> מקורות במאגרי האתר "
                    f"(תורה: {cc['torah']}, נ\"ך: {cc['nach']}, משנה ותוספתא: {cc['mishnah_tosefta']}, תלמודים: {cc['talmud']}, הלכה: {cc['halacha']})."
                )
            }]
            edges = []

            for idx, th in enumerate(analysis['top_tanakh']):
                nid = f"tanakh_{idx}"
                nodes.append({'id': nid, 'label': f"📖 תנ\"ך\n{th['ref']}", 'group': 'tanakh', 'snippet': f"<b>מקור במקרא ({th['ref']}):</b><br>{th['text']}", 'url': ''})
                edges.append({'from': 'root', 'to': nid, 'label': 'הופעה במקרא'})

            for idx, ch in enumerate(analysis['top_chazal'][:2]):
                nid = f"chazal_{idx}"
                nodes.append({'id': nid, 'label': f"🏛️ חז\"ל\n{ch['book']} ({ch['chapter']})", 'group': 'talmud', 'snippet': f"<b>מקור בדברי חז\"ל ({ch['book']} {ch['chapter']}, {ch['verse']}):</b><br>{ch['text']}", 'url': ''})
                edges.append({'from': 'root', 'to': nid, 'label': 'הופעה בחז"ל'})

            for idx, hh in enumerate(analysis['top_halacha'][:2]):
                nid = f"halacha_{idx}"
                nodes.append({'id': nid, 'label': f"👑 הלכה\n{hh['book']} ({hh['chapter']})", 'group': 'halacha', 'snippet': f"<b>פסיקת הלכה ({hh['book']} {hh['chapter']}, {hh['verse']}):</b><br>{hh['text']}", 'url': ''})
                edges.append({'from': 'root', 'to': nid, 'label': 'פסיקת הלכה'})

            if analysis['gem_concepts'] or analysis['gem_word_verses'] or analysis['gem_tanakh_verses']:
                gem_parts = []
                if analysis['gem_concepts']:
                    gem_parts.append(f"<b>מילים ומושגים בתנ\"ך בעלי גימטריה זהה ({q_gem}):</b> {', '.join(analysis['gem_concepts'])}")
                for gwv in analysis['gem_word_verses']:
                    gem_parts.append(f"<b>מקור בתורה למילה שווה בגימטריה (\"{gwv['word']}\" = {q_gem}) — {gwv['ref']}:</b> {gwv['text']}")
                for gtv in analysis['gem_tanakh_verses']:
                    gem_parts.append(f"<b>פסוק שלם שערכו הגימטרי {q_gem} — {gtv['ref']}:</b> {gtv['text']}")
                nodes.append({'id': 'gem_node', 'label': f"🔢 הקבלות גימטריה ({q_gem})\n{', '.join(analysis['gem_concepts'][:3]) or 'פסוקים מקבילים'}", 'group': 'gematria', 'snippet': "<br><br>".join(gem_parts), 'url': ''})
                edges.append({'from': 'root', 'to': 'gem_node', 'label': f'שווה בגימטריה ({q_gem})'})

            if analysis['rev_matches']:
                rv0 = analysis['rev_matches'][0]
                nodes.append({'id': 'rev_node', 'label': f"🔄 היפוך אותיות: \"{rv0['word']}\"\n{rv0['ref']}", 'group': 'trends', 'snippet': f"<b>היפוך האותיות של \"{core}\" הוא \"{rv0['word']}\" (גימטריה: {q_gem}) — מופיע ב{rv0['ref']}:</b><br>{rv0['text']}", 'url': ''})
                edges.append({'from': 'root', 'to': 'rev_node', 'label': 'היפוך אותיות'})

            if analysis['rashei_matches'] or analysis['sofei_matches']:
                acr_parts = [f"<b>ראשי תיבות (ר\"ת) של \"{core}\" ב{rm['ref']}:</b><br>{rm['text']}" for rm in analysis['rashei_matches']] + [f"<b>סופי תיבות (ס\"ת) של \"{core}\" ב{sm['ref']}:</b><br>{sm['text']}" for sm in analysis['sofei_matches']]
                nodes.append({'id': 'acr_node', 'label': "🔠 ראשי וסופי תיבות\nבפסוקי התורה", 'group': 'trends', 'snippet': "<br><br>".join(acr_parts), 'url': ''})
                edges.append({'from': 'root', 'to': 'acr_node', 'label': 'ר"ת / ס"ת בתורה'})

            if analysis['els_matches']:
                el0 = analysis['els_matches'][0]
                nodes.append({'id': 'els_node', 'label': f"⚡ דילוג אותיות ({el0['skip']})\n{el0['ref']}", 'group': 'gematria', 'snippet': f"<b>דילוג אותיות שווה במרווח {el0['skip']} של האותיות \"{core}\" ב{el0['ref']}:</b><br>{el0['text']}", 'url': ''})
                edges.append({'from': 'root', 'to': 'els_node', 'label': f"דילוג אותיות ({el0['skip']})"})

            for idx, art in enumerate(analysis['verified_articles']):
                nid = f"article_{idx}"
                nodes.append({'id': nid, 'label': f"✍️ מאמר בספרייה\n{art['title'][:28]}", 'group': 'site_content', 'snippet': f"<b>מאמר באתר ספריית לייבוביץ ({art['title']}):</b><br>{art['snippet']}", 'url': art['url']})
                edges.append({'from': 'root', 'to': nid, 'label': 'מאמר רלוונטי באתר'})

            resp_payload = {'query': query, 'gematria': q_gem, 'nodes': nodes, 'edges': edges}
            cache.set(cache_key, resp_payload, 3600 * 12)
            return JsonResponse(resp_payload, json_dumps_params={'ensure_ascii': False})

        elif mode == 'sermon_generator':
            if not query:
                return JsonResponse({'error': 'יש להזין נושא או מושג לניתוח.'}, status=400)
            analysis = analyze_concept_deeply(query)
            q_gem, cc, core = analysis['gematria'], analysis['corpus_counts'], analysis['search_core']

            dom_b = ", ".join([f"<b>{b['book']}</b> ({b['score']} מופעים)" for b in analysis['dominant_books'][:5]]) or "ללא מוקד בודד"
            html_sections = [
                f"<div class='mb-4'><h6 class='fw-bold mb-2' style='color: #8c6239; border-bottom: 1px solid #e2d9c5; padding-bottom: 6px;'>א. ניתוח תפוצה ומוקדי הסוגיה במאגרי התורה</h6>"
                f"<div>בסריקת כלל מאגרי האתר עבור <b>\"{core}\"</b> אותרו <b>{analysis['total_matches']}</b> מקורות: "
                f"בתורה: <b>{cc['torah']}</b> | בנביאים וכתובים: <b>{cc['nach']}</b> | במשנה ובתוספתא: <b>{cc['mishnah_tosefta']}</b> | "
                f"בתלמוד הבבלי והירושלמי: <b>{cc['talmud']}</b> | ברמב\"ם ובשולחן ערוך: <b>{cc['halacha']}</b>.<br>"
                f"הספרים והמסכתות שבהם מתרכז עיקר הדיון במאגר: {dom_b}.</div></div>"
            ]

            sources_html_list = [f"<li class='mb-2'><b>מקרא ({x['ref']}):</b> {x['text']}</li>" for x in analysis['top_tanakh']] or [f"<li class='mb-2 text-muted'>התיבה המדויקת \"{core}\" אינה מופיעה כתיבה עצמאית במקרא.</li>"]
            sources_html_list += [f"<li class='mb-2'><b>חז\"ל ({x['book']} {x['chapter']}, {x['verse']}):</b> {x['text']}</li>" for x in analysis['top_chazal'][:2]]
            sources_html_list += [f"<li class='mb-2'><b>הלכה ({x['book']} {x['chapter']}, {x['verse']}):</b> {x['text']}</li>" for x in analysis['top_halacha'][:2]]

            html_sections.append(
                f"<div class='mb-4'><h6 class='fw-bold mb-2' style='color: #8c6239; border-bottom: 1px solid #e2d9c5; padding-bottom: 6px;'>ב. מקורות היסוד במקרא, בחז\"ל ובהלכה</h6>"
                f"<ul class='mb-0 ps-3'>{''.join(sources_html_list)}</ul></div>"
            )

            gem_tail = f" מילים ומושגים בתנ\"ך בעלי ערך גימטרי זהה (<b>{q_gem}</b>): <b>{', '.join(analysis['gem_concepts'])}</b>." if analysis['gem_concepts'] else ""
            crypto_items = [f"<li class='mb-2'><b>ערך גימטרי מדויק:</b> המילה <b>\"{core}\"</b> עולה בגימטריה <b>{q_gem}</b>.{gem_tail}</li>"]
            crypto_items += [f"<li class='mb-2'><b>הקבלה גימטרית בתורה (\"{gwv['word']}\" = {q_gem}) ב{gwv['ref']}:</b> {gwv['text']}</li>" for gwv in analysis['gem_word_verses']]
            crypto_items += [f"<li class='mb-2'><b>פסוק שלם במקרא שערכו הגימטרי {q_gem} ({gtv['ref']}):</b> {gtv['text']}</li>" for gtv in analysis['gem_tanakh_verses']]
            crypto_items += [f"<li class='mb-2'><b>היפוך אותיות מדויק (\"{core}\" ⬅ \"{rv['word']}\", גימטריה {q_gem}) ב{rv['ref']}:</b> {rv['text']}</li>" for rv in analysis['rev_matches']]
            crypto_items += [f"<li class='mb-2'><b>ראשי תיבות (ר\"ת) של \"{core}\" בתורה ({rm['ref']}):</b> {rm['text']}</li>" for rm in analysis['rashei_matches']]
            crypto_items += [f"<li class='mb-2'><b>סופי תיבות (ס\"ת) של \"{core}\" בתורה ({sm['ref']}):</b> {sm['text']}</li>" for sm in analysis['sofei_matches']]
            crypto_items += [f"<li class='mb-2'><b>דילוג אותיות שווה (ELS במרווח {el['skip']}) בתורה ({el['ref']}):</b> {el['text']}</li>" for el in analysis['els_matches']]

            html_sections.append(
                f"<div class='mb-4'><h6 class='fw-bold mb-2' style='color: #8c6239; border-bottom: 1px solid #e2d9c5; padding-bottom: 6px;'>ג. הצלבת גימטריאות, היפוך אותיות, ראשי/סופי תיבות ודילוגים</h6>"
                f"<ul class='mb-0 ps-3'>{''.join(crypto_items)}</ul></div>"
            )

            plain_summary_for_ai = (
                f"מושג: {core} (גימטריה: {q_gem}). תפוצה: תורה {cc['torah']}, נ\"ך {cc['nach']}, חז\"ל {cc['mishnah_tosefta'] + cc['talmud']}, הלכה {cc['halacha']}. "
                f"מקורות תנ\"ך: {', '.join([x['ref'] for x in analysis['top_tanakh']]) or 'ללא'}. "
                f"מילים שוות בגימטריה ({q_gem}): {', '.join(analysis['gem_concepts'])}."
            )
            ai_synthesis = call_gemini_fast(
                f"אתה חוקר תורני באתר 'ספריית לייבוביץ'. להלן נתוני אמת שנשלפו ממסד הנתונים על המושג '{core}':\n{plain_summary_for_ai}\n"
                f"כתוב פסקה מסכמת אחת או שתיים (ללא כותרות וללא כוכביות) המחברת באופן ענייני ומדויק בין המקורות וההקבלות הגימטריות/לשוניות שעלו בנתונים אלו לרעיון תורני משותף. "
                f"אל תמציא שום נתון שלא מופיע כאן, וכתוב את שם ה' אך ורק כ-י-ה-ו-ה."
            )
            if not ai_synthesis:
                synth_parts = [f"בחינה משולבת של כלל הממצאים עבור \"{core}\" (גימטריה: {q_gem}) מצביעה על חוט שני המחבר בין הרבדים השונים במאגר:"]
                if analysis['top_tanakh']:
                    synth_parts.append(f"במקרא מופיעה התיבה במפורש ב{', '.join([x['ref'] for x in analysis['top_tanakh']])}.")
                if analysis['top_chazal'] or analysis['top_halacha']:
                    synth_parts.append(f"בדברי חז\"ל ובהלכה מתבררים ההקשרים המעשיים ב{', '.join([x['book'] + ' (' + str(x['chapter']) + ')' for x in (analysis['top_chazal'][:2] + analysis['top_halacha'][:1])])}.")
                if analysis['gem_concepts']:
                    synth_parts.append(f"במישור הגימטרי ({q_gem}), המושג מתקשר בערכו המדויק לתיבות {', '.join(analysis['gem_concepts'][:4])}.")
                ai_synthesis = " ".join(synth_parts)

            html_sections.append(
                f"<div class='p-3 rounded-3' style='background-color: #fff8dc; border-right: 4px solid #d4af37;'>"
                f"<h6 class='fw-bold mb-2' style='color: #1e293b;'><i class='bi bi-layers-half ms-1' style='color: #b8860b;'></i>ד. חיבור הנתונים לרעיון משותף</h6>"
                f"<div style='line-height: 1.8;'>{ai_synthesis}</div></div>"
            )

            top_art = analysis['verified_articles'][0] if analysis['verified_articles'] else None
            resp_payload = {
                'topic': query, 'gematria': q_gem, 'total_matches': analysis['total_matches'],
                'corpus_counts': cc, 'dominant_books': analysis['dominant_books'],
                'article_link': top_art['url'] if top_art else '',
                'article_title': top_art['title'] if top_art else '',
                'sermon_html': "".join(html_sections)
            }
            cache.set(cache_key, resp_payload, 3600 * 12)
            return JsonResponse(resp_payload, json_dumps_params={'ensure_ascii': False})

        return JsonResponse({'error': 'מצב פעולה לא חוקי.'}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=400)