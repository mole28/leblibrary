import json
import os
import re
from django.conf import settings
from .models import Article, Book, Chapter, QA

DEFAULT_MIN_CONNECTION_SCORE = 26
TITLE_WEIGHT = 10
BODY_WEIGHT = 1
MAX_BODY_HITS = 5
ENGINE_VERSION = "v10_precision"

RUNTIME_CONFIG_PATH = os.path.join(settings.BASE_DIR, 'clusters_runtime_config.json')

_MEM_CACHE = {}

MANUAL_ARTICLE_OVERRIDES = {}

UNCLASSIFIED_CLUSTER = {
    'id': 'general_iyun',
    'title': 'עיונים כלליים (לבדיקה)',
    'icon': 'bi-book-half',
    'description': 'מאמרים ועיונים תורניים והלכתיים במגוון מקצועות התורה.',
}

GRAVITY_CLUSTERS = [
    {
        'id': 'brachot',
        'title': 'ברכות ותפילה',
        'icon': 'bi-stars',
        'description': 'סוגיות ובירורי הלכה בברכות הנהנין, ברכות הריח, שהחיינו, ברכות הראייה והשבח, תפילה וקריאת התורה.',
        'phrases': [
            'ברכת הריח', 'ברכות הריח', 'בגדים מבושמים', 'שמן אפרסמון', 'ריח טוב',
            'ברכת שהחיינו', 'הטוב והמטיב', 'ברכת הזמן', 'חכם הרזים', 'שישים ריבוא',
            'מחיה המתים', 'ברכת הקשת', 'קשת בענן', 'ברכת הגומל', 'ברכת האורח',
            'שמונה עשרה', 'קריאת שמע', 'ברכות השחר', 'ברכת כהנים', 'ברכת המזון',
            'בשם ומלכות', 'ספק ברכות', 'ותן טל ומטר', 'טל ומטר', 'משיב הרוח',
            'גבורות גשמים', 'ברכת השנים', 'ברכת נחם', 'ברכת החודש', 'קידוש לבנה',
            'ברכת הלבנה', 'שככה לו בעולמו', 'הים התיכון', 'הים הגדול', 'מעשה בראשית',
            'קריאת התורה', 'עשרת הדברות', 'פרשת הקללות', 'פרשיית הקללות'
        ],
        'specific_keywords': [
            'שהחיינו', 'בשמים', 'מבושמים', 'אפרסמון', 'מוגמר', 'להריח', 'הקשת',
            'הגומל', 'ציצית', 'תפילין', 'תחנון', 'הלל', 'מפטיר', 'הפטרה'
        ],
        'broad_classify_only': [
            'ברכה', 'ברכות', 'ברכת', 'מברך', 'לברך', 'תפילה', 'תפילת', 'עמידה'
        ]
    },
    {
        'id': 'moadim',
        'title': 'שבת ומועדי ישראל',
        'icon': 'bi-calendar-heart',
        'description': 'עיונים והלכות בשבת, חנוכה, סוכה וארבעת המינים, פסח, פורים ומועדי השנה.',
        'phrases': [
            'נר חנוכה', 'נרות חנוכה', 'הדלקת נרות', 'פרסומי ניסא', 'כבתה אין זקוק לה',
            'ארבעת המינים', 'נטילת לולב', 'תשבו כעין תדורו', 'שמיני עצרת', 'שמחת תורה',
            'ליל הסדר', 'חמץ ומצה', 'בדיקת חמץ', 'מקרא מגילה', 'משלוח מנות',
            'ראש השנה', 'תקיעת שופר', 'יום הכיפורים', 'יום טוב', 'עונג שבת',
            'תחום שבת', 'תשעה באב', 'בין המצרים', 'ראש חודש'
        ],
        'specific_keywords': [
            'שבת', 'חנוכה', 'חנוכיה', 'סוכה', 'סוכות', 'סכך', 'דפנות', 'לולב',
            'אתרוג', 'הדס', 'ערבה', 'פסח', 'חמץ', 'מצה', 'פורים', 'מגילה',
            'שופר', 'מוקצה', 'עירוב', 'עירובין', 'קידוש', 'הבדלה'
        ],
        'broad_classify_only': [
            'מועד', 'מועדים', 'הדלקה', 'הדלקת', 'חג'
        ]
    },
    {
        'id': 'eretz_yisrael',
        'title': 'ארץ ישראל ומצוותיה',
        'icon': 'bi-geo-alt-fill',
        'description': 'מצוות התלויות בארץ, תרומות ומעשרות, מעשר שני, קדושת הארץ, גבולותיה ומעלתה.',
        'phrases': [
            'ארץ ישראל', 'תרומות ומעשרות', 'מעשר שני', 'מעשר עני', 'שנת מעשר',
            'ביעור מעשרות', 'מציב גבול אלמנה', 'חלוקת הארץ', 'כיבוש הארץ',
            'פירות ארץ ישראל', 'ישוב ארץ ישראל', 'מצוות התלויות בארץ',
            'שנת השמיטה', 'על שהנחלת'
        ],
        'specific_keywords': [
            'מעשר', 'מעשרות', 'תרומות', 'תרומה', 'טבל', 'דמאי', 'שמיטה', 'שביעית',
            'שהנחלת', 'נחלה', 'גורל', 'ירושלים', 'מקדש'
        ],
        'broad_classify_only': []
    },
    {
        'id': 'mishpacha_mila',
        'title': 'משפחה, חופה וברית מילה',
        'icon': 'bi-people-fill',
        'description': 'הלכות ברית מילה וברכותיה, זמני המילה, גדרי החופה וברכות הנישואין, קידושין ואבן העזר.',
        'phrases': [
            'ברית מילה', 'זמני המילה', 'זריזין מקדימין למילה', 'מילה שלא בזמנה',
            'אבי הבן', 'ברית אברהם', 'גדרי החופה', 'חופה וקידושין', 'שבע ברכות',
            'ברכת חתנים', 'פנים חדשות', 'חדר ייחוד', 'פדיון הבן', 'כבוד המת'
        ],
        'specific_keywords': [
            'מילה', 'מוהל', 'סנדק', 'נימול', 'פריעה', 'מציצה', 'חופה', 'נישואין',
            'קידושין', 'אירוסין', 'חתן', 'כלה', 'כתובה', 'ייחוד', 'קבורה', 'אבלות'
        ],
        'broad_classify_only': []
    },
    {
        'id': 'taharah_shiurim',
        'title': 'טהרה, מידות ושיעורי תורה',
        'icon': 'bi-rulers',
        'description': 'סוגיות בהלכות טומאה וטהרה, מקוואות, נטילת ידיים, ומידות ושיעורי חז"ל.',
        'phrases': [
            'טומאה וטהרה', 'נטילת ידיים', 'מידות חז"ל', 'שיעורי תורה', 'טומאת אהל',
            'טומאת מת', 'ארבעים סאה', 'מי מקווה', 'טהרת כלים', 'שיעור כזית', 'שיעור רביעית'
        ],
        'specific_keywords': [
            'טומאה', 'טהרה', 'טמא', 'טהור', 'מקווה', 'מקוואות', 'טבילה', 'חציצה',
            'אמה', 'טפח', 'טפחים', 'אצבע', 'זרת', 'מיל', 'רביעית', 'לוג', 'כזית',
            'כביצה', 'סלע', 'שקל', 'מידות'
        ],
        'broad_classify_only': [
            'שיעור', 'שיעורים', 'כלי', 'כלים'
        ]
    },
    {
        'id': 'choshen_iyun',
        'title': 'חושן משפט, חזקות ועיונים',
        'icon': 'bi-journal-bookmark-fill',
        'description': 'דיני חזקות, ריבית, ממונות, קניינים, ספקות, מנהגים וכללי פסיקה בעיון הש"ס והפוסקים.',
        'phrases': [
            'דיני חזקות', 'חזקת מרא קמא', 'המוציא מחברו', 'היתר עסקה', 'איסור ריבית',
            'דיני ממונות', 'ספק ספיקא', 'מנהג ישראל', 'כללי פסיקה', 'עד אחד באיסורים',
            'עד אחד נאמן'
        ],
        'specific_keywords': [
            'חזקה', 'חזקות', 'חזקת', 'מוחזק', 'ריבית', 'ממון', 'ממונות', 'קניין',
            'בעלות', 'מנהג', 'מנהגים', 'שטר', 'עדים', 'שבועה', 'נדר', 'נדרים'
        ],
        'broad_classify_only': [
            'רוב', 'ספק', 'ספקות'
        ]
    },
]

# Words that must NEVER trigger similarity links between articles/books on their own
GENERIC_NOISE_WORDS = {
    'אבל', 'או', 'אולי', 'אותו', 'אותה', 'אותם', 'אחר', 'אחרי', 'אחת', 'איך', 'אין',
    'אלא', 'אלה', 'אלו', 'אם', 'אנחנו', 'אני', 'אף', 'אפשר', 'אשר', 'את', 'אתה',
    'בין', 'בכל', 'בלי', 'בעל', 'בשביל', 'גם', 'דבר', 'דברי', 'הוא', 'היא', 'היה',
    'היתה', 'היו', 'הזה', 'הזאת', 'הכל', 'הם', 'הן', 'הנה', 'הרי', 'וזה', 'וכן',
    'ולא', 'זאת', 'זה', 'זו', 'כדי', 'כמו', 'כן', 'כפי', 'כל', 'כך', 'לא', 'לו',
    'לפי', 'לכן', 'לפני', 'מאוד', 'מה', 'ממנו', 'מן', 'מעל', 'מצד', 'משום', 'נגד',
    'עוד', 'על', 'עם', 'עצמו', 'פה', 'רק', 'שוב', 'של', 'שלו', 'שלה', 'שלהם', 'שם',
    'הלכה', 'הלכות', 'רמבם', 'רמב"ם', 'שולחן', 'ערוך', 'שו"ע', 'גמרא', 'משנה',
    'בבלי', 'ירושלמי', 'תורה', 'מצווה', 'מצוות', 'מצות', 'ספק', 'ספקות', 'מותר',
    'אסור', 'חייב', 'פטור', 'שיטת', 'שיטות', 'דעת', 'נראה', 'אמנם', 'לכאורה',
    'רש"י', 'תוספות', 'סימן', 'סעיף', 'פרק', 'דף', 'עמוד', 'ישראל', 'אדם', 'בעניין',
    'בדין', 'גדרי', 'גדר', 'דין', 'דיני', 'שאלה', 'תשובה', 'שו"ת', 'מקור', 'טעם',
    'ביאור', 'עניין', 'דברים', 'הראשונים', 'האחרונים', 'הפוסקים', 'פסק', 'כתב',
    'כתבו', 'אומר', 'אמרו', 'מבואר', 'איתא', 'שנינו', 'נאמר', 'פסוק', 'להלכה',
    'למעשה', 'בזמן', 'הזה', 'חלק', 'ספר', 'מאמר', 'הרב', 'משה', 'לייבוביץ',
    # Generic liturgical/structural words that caused false links to "Zmanei HaMilah U'Birchoteha":
    'ברכה', 'ברכות', 'ברכת', 'מברך', 'לברך', 'ברכותיה', 'וברכותיה', 'הברכה', 'הברכות',
    'תפילה', 'תפילת', 'התפילה', 'זמן', 'זמני', 'הזמן', 'הקדמה', 'מבוא', 'פתיחה',
    'סימנים', 'הערות', 'נספח', 'תוכן', 'עניינים', 'כלל', 'כללים', 'אופן', 'אמירת',
    'קריאת', 'מקורה', 'וטעמיה', 'בעולמו', 'החודש', 'נחם'
}


class ClusterEngine:

    @classmethod
    def clear_memory_cache(cls):
        _MEM_CACHE.clear()

    @classmethod
    def get_runtime_config(cls):
        if 'runtime_cfg' in _MEM_CACHE:
            return _MEM_CACHE['runtime_cfg']

        default_cfg = {
            'min_connection_score': DEFAULT_MIN_CONNECTION_SCORE,
            'public_enabled': False,
        }
        if os.path.exists(RUNTIME_CONFIG_PATH):
            try:
                with open(RUNTIME_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    default_cfg['min_connection_score'] = int(saved.get('min_connection_score', DEFAULT_MIN_CONNECTION_SCORE))
                    default_cfg['public_enabled'] = bool(saved.get('public_enabled', False))
            except Exception:
                pass
        _MEM_CACHE['runtime_cfg'] = default_cfg
        return default_cfg

    @classmethod
    def save_runtime_config(cls, min_connection_score: int, public_enabled: bool):
        cfg = {
            'min_connection_score': max(8, min(80, int(min_connection_score))),
            'public_enabled': bool(public_enabled),
        }
        try:
            with open(RUNTIME_CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        _MEM_CACHE.clear()
        return cfg

    @staticmethod
    def clean_text_fast(html_content: str, max_len: int = 1200) -> str:
        if not html_content:
            return ""
        raw_slice = str(html_content)[:max_len * 3]
        txt = re.sub(r'<[^>]+>', ' ', raw_slice)
        return re.sub(r'\s+', ' ', txt).strip()[:max_len]

    @classmethod
    def _extract_distinctive_signature(cls, title: str, body_snippet: str):
        title_clean = cls.clean_text_fast(title, 300).lower()
        body_clean = cls.clean_text_fast(body_snippet, 1000).lower()

        matched_phrases = set()
        matched_specific_keywords = set()
        cluster_scores = {}
        keyword_breakdown = {}

        for cluster in GRAVITY_CLUSTERS:
            c_score = 0

            # 1. Exact multi-word phrases (strongest signal for both classification and similarity)
            for phrase in cluster['phrases']:
                t_hits = 1 if phrase in title_clean else 0
                b_hits = min(MAX_BODY_HITS, body_clean.count(phrase)) if phrase in body_clean else 0
                if t_hits > 0 or b_hits > 0:
                    pts = (t_hits * TITLE_WEIGHT * 2.0) + (b_hits * BODY_WEIGHT * 3.0)
                    c_score += pts
                    matched_phrases.add(phrase)
                    keyword_breakdown[phrase] = keyword_breakdown.get(phrase, 0) + round(pts, 1)

            # 2. Specific subject keywords (used for both classification and similarity)
            for kw in cluster['specific_keywords']:
                t_hits = 1 if kw in title_clean else 0
                b_hits = min(MAX_BODY_HITS, body_clean.count(kw)) if kw in body_clean else 0
                if t_hits > 0 or b_hits >= 2:
                    pts = (t_hits * TITLE_WEIGHT) + (b_hits * BODY_WEIGHT)
                    c_score += pts
                    matched_specific_keywords.add(kw)
                    keyword_breakdown[kw] = keyword_breakdown.get(kw, 0) + round(pts, 1)

            # 3. Broad classification words (e.g. 'ברכה', 'תפילה') - ONLY for cluster classification, NEVER for similarity!
            for b_kw in cluster.get('broad_classify_only', []):
                t_hits = 1 if b_kw in title_clean else 0
                b_hits = min(3, body_clean.count(b_kw)) if b_kw in body_clean else 0
                if t_hits > 0 or b_hits >= 2:
                    pts = (t_hits * 6) + (b_hits * 0.5)
                    c_score += pts
                    keyword_breakdown[b_kw] = keyword_breakdown.get(b_kw, 0) + round(pts, 1)

            cluster_scores[cluster['id']] = round(c_score, 1)

        raw_title_words = re.findall(r'[א-ת]{3,}', title_clean)
        title_specific_stems = set()
        for w in raw_title_words:
            if w in GENERIC_NOISE_WORDS:
                continue
            stem = w[1:] if (len(w) >= 5 and w[0] in 'הבכלמשו') else w
            if stem not in GENERIC_NOISE_WORDS and len(stem) >= 3:
                title_specific_stems.add(stem)

        raw_body_words = re.findall(r'[א-ת]{4,}', body_clean)
        body_freq = {}
        for w in raw_body_words:
            if w in GENERIC_NOISE_WORDS:
                continue
            stem = w[1:] if (len(w) >= 5 and w[0] in 'הבכלמשו') else w
            if stem not in GENERIC_NOISE_WORDS and len(stem) >= 3:
                body_freq[stem] = body_freq.get(stem, 0) + 1

        dominant_body_stems = {st for st, cnt in body_freq.items() if cnt >= 2 or st in title_specific_stems}

        best_cluster_id, best_score = max(cluster_scores.items(), key=lambda x: x[1]) if cluster_scores else ('general_iyun', 0)

        # Fix 3: Never default to Choshen Mishpat when score is 0!
        if best_score <= 0:
            best_cluster_obj = UNCLASSIFIED_CLUSTER
        else:
            best_cluster_obj = next((c for c in GRAVITY_CLUSTERS if c['id'] == best_cluster_id), UNCLASSIFIED_CLUSTER)

        sorted_breakdown = sorted(keyword_breakdown.items(), key=lambda x: -x[1])[:6]

        return {
            'cluster': best_cluster_obj,
            'cluster_score': best_score,
            'phrases': matched_phrases,
            'keywords': matched_specific_keywords,
            'title_stems': title_specific_stems,
            'body_stems': dominant_body_stems,
            'breakdown': sorted_breakdown,
        }

    @classmethod
    def _calculate_pair_similarity(cls, sig_a, sig_b, parasha_a="", parasha_b="", is_book_target=False) -> tuple:
        shared_phrases = sig_a['phrases'] & sig_b['phrases']
        shared_keywords = sig_a['keywords'] & sig_b['keywords']
        shared_title_stems = sig_a['title_stems'] & sig_b['title_stems']
        title_to_body_stems = (sig_a['title_stems'] & sig_b['body_stems']) | (sig_b['title_stems'] & sig_a['body_stems'])

        # Fix 1: Prevent cross-cluster false book matches (e.g. general Brachot article matching Mila book)
        if is_book_target and sig_a['cluster']['id'] != sig_b['cluster']['id']:
            if not shared_phrases and not shared_keywords:
                return 0, []

        score = 0
        reasons = []

        if shared_phrases:
            score += len(shared_phrases) * 38
            reasons.extend(list(shared_phrases)[:3])

        if shared_keywords:
            score += len(shared_keywords) * 20
            for kw in list(shared_keywords)[:2]:
                if kw not in reasons:
                    reasons.append(kw)

        if shared_title_stems:
            score += len(shared_title_stems) * 24
            for st in list(shared_title_stems)[:2]:
                if st not in reasons:
                    reasons.append(st)

        if title_to_body_stems:
            score += len(title_to_body_stems) * 8

        if sig_a['cluster']['id'] == sig_b['cluster']['id'] and sig_a['cluster']['id'] != 'general_iyun' and score >= 18:
            score += 8

        if parasha_a and parasha_b and parasha_a == parasha_b and 'general' not in parasha_a:
            score += 18
            reasons.append(f"פרשת {parasha_a.strip(',')}")

        return score, reasons[:3]

    @classmethod
    def _get_all_indexed_articles(cls):
        if 'indexed_articles' in _MEM_CACHE:
            return _MEM_CACHE['indexed_articles']

        articles_index = []
        qs = Article.objects.filter(is_published=True).only('id', 'title', 'slug', 'parasha', 'content')
        for art in qs:
            snippet = cls.clean_text_fast(art.content or '', 900)
            sig = cls._extract_distinctive_signature(art.title or '', snippet)
            override = MANUAL_ARTICLE_OVERRIDES.get(art.slug) or MANUAL_ARTICLE_OVERRIDES.get(art.pk) or {}
            cluster_obj = sig['cluster']
            if override.get('cluster_id'):
                cluster_obj = next((c for c in GRAVITY_CLUSTERS if c['id'] == override['cluster_id']), cluster_obj)

            title_str = art.title or ''
            foundational = ('גדר', 'גדרי', 'יסוד', 'יסודות', 'מהות', 'כלל', 'כללי', 'מבוא', 'מקור', 'חיוב', 'מצוות')
            specific = ('ספק', 'בדיעבד', 'האם', 'מתי', 'כיצד', 'איך', 'מנהג', 'בזמן הזה')
            stage = 1 if any(t in title_str for t in foundational) else (3 if any(t in title_str for t in specific) else 2)

            articles_index.append({
                'pk': art.pk,
                'title': title_str,
                'slug': art.slug,
                'parasha': art.parasha or '',
                'snippet': snippet,
                'cluster_id': cluster_obj['id'],
                'cluster_title': cluster_obj['title'],
                'icon': cluster_obj['icon'],
                'description': cluster_obj['description'],
                'score': sig['cluster_score'],
                'breakdown': sig['breakdown'],
                'signature': sig,
                'stage': stage,
                'sort_key': (stage, -sig['cluster_score'], art.pk),
            })

        _MEM_CACHE['indexed_articles'] = articles_index
        return articles_index

    @classmethod
    def _get_indexed_book_units(cls):
        if 'book_units' in _MEM_CACHE:
            return _MEM_CACHE['book_units']

        units = []
        books = {b.pk: b for b in Book.objects.only('id', 'title', 'summary').all()}
        chapters = list(Chapter.objects.only('id', 'book_id', 'title', 'order').order_by('book_id', 'order', 'id'))

        books_with_chapters = set()
        seen_book_chapter_titles = set()

        for ch in chapters:
            book = books.get(ch.book_id)
            if not book:
                continue
            books_with_chapters.add(book.pk)

            clean_b_title = re.sub(r'\s+', ' ', (book.title or '').strip())
            clean_ch_title = re.sub(r'\s+', ' ', (ch.title or '').strip())

            # Fix 2: Strict deduplication of identical chapter titles within the same book
            dedup_title_key = (clean_b_title, clean_ch_title)
            if dedup_title_key in seen_book_chapter_titles:
                continue
            seen_book_chapter_titles.add(dedup_title_key)

            # Skip generic "הקדמה" / "תוכן עניינים" chapters from being matched as subject chapters
            if clean_ch_title in ('הקדמה', 'מבוא', 'תוכן עניינים', 'הסכמות', 'פתח דבר'):
                continue

            # Important: Extract signature primarily from the chapter title + book's core subject (excluding generic 'וברכותיה')
            book_subject_title = clean_b_title.replace('וברכותיה', '').replace('וברכותיו', '')
            sig = cls._extract_distinctive_signature(f"{book_subject_title} {clean_ch_title}", "")
            b_summary = cls.clean_text_fast(book.summary or '', 260)

            units.append({
                'unit_type': 'chapter',
                'book_id': book.pk,
                'book_title': clean_b_title,
                'chapter_id': ch.pk,
                'chapter_title': clean_ch_title,
                'title': clean_ch_title,
                'badge': f'מתוך הספר "{clean_b_title}"',
                'preview': b_summary[:130],
                'url': f"/book/{book.pk}/?chapter={ch.pk}#chapter-{ch.pk}",
                'signature': sig,
            })

        for b_id, book in books.items():
            if b_id in books_with_chapters:
                continue
            clean_b_title = re.sub(r'\s+', ' ', (book.title or '').strip())
            b_summary = cls.clean_text_fast(book.summary or '', 400)
            book_subject_title = clean_b_title.replace('וברכותיה', '').replace('וברכותיו', '')
            sig = cls._extract_distinctive_signature(book_subject_title, b_summary)
            units.append({
                'unit_type': 'book',
                'book_id': book.pk,
                'book_title': clean_b_title,
                'chapter_id': None,
                'chapter_title': '',
                'title': f'הספר "{clean_b_title}"',
                'badge': 'ספר שלם בספרייה',
                'preview': b_summary[:140],
                'url': f"/book/{book.pk}/",
                'signature': sig,
            })

        _MEM_CACHE['book_units'] = units
        return units

    @classmethod
    def _get_indexed_qa_units(cls):
        if 'qa_units' in _MEM_CACHE:
            return _MEM_CACHE['qa_units']

        qa_units = []
        for qa in QA.objects.only('id', 'question', 'answer', 'category').all():
            ans_clean = cls.clean_text_fast(qa.answer or '', 500)
            sig = cls._extract_distinctive_signature(f"{qa.question or ''} {qa.category or ''}", ans_clean)
            qa_units.append({
                'qa_id': qa.pk,
                'question': qa.question,
                'category': qa.category or 'שו"ת הלכתי',
                'preview': ans_clean[:130],
                'url': f"/qa/{qa.pk}/",
                'signature': sig,
            })

        _MEM_CACHE['qa_units'] = qa_units
        return qa_units

    @classmethod
    def get_smart_tools_for_article(cls, title: str, snippet: str, sig):
        text_combined = f"{title} {snippet}"
        tools = []

        if any(w in text_combined for w in ('אמה', 'טפח', 'טפחים', 'אצבע', 'זרת', 'מיל', 'תחום שבת', 'גובה')):
            tools.append({
                'title': 'מחשבון מידות אורך בתורה',
                'subtitle': 'המרת אמה, טפח, זרת ואצבע לסנטימטרים לפי שיטות הפוסקים',
                'url': '/calculator/',
                'icon': 'bi-rulers'
            })
        if any(w in text_combined for w in ('רביעית', 'לוג', 'כזית', 'כביצה', 'סאה', 'ארבעים סאה', 'מקווה', 'נפח')):
            tools.append({
                'title': 'מחשבון מידות נפח הלכתי',
                'subtitle': 'חישוב כזית, כביצה, רביעית, לוג ומקווה בסמ"ק',
                'url': '/volume-calculator/',
                'icon': 'bi-cup-straw'
            })
        if any(w in text_combined for w in ('שקל', 'סלע', 'דינר', 'פרוטה', 'פדיון הבן', 'חומש', 'מטבע', 'משקל')):
            tools.append({
                'title': 'מחשבון משקל ומטבעות חז"ל',
                'subtitle': 'חישוב משקלי התורה ומטבעות ההלכה בגרמים',
                'url': '/weight-calculator/',
                'icon': 'bi-coin'
            })
        if any(w in text_combined for w in ('בגמרא', 'בבלי', 'ירושלמי', 'איתמר', 'תא שמע', 'מאי טעמא', 'נפקא מינה')):
            tools.append({
                'title': 'מתרגם ארמי ⇄ עברי לש"ס',
                'subtitle': 'פענוח ותרגום מונחי התלמוד הבבלי, הירושלמי והזוהר',
                'url': '/aramaic-translator/',
                'icon': 'bi-translate'
            })

        search_term = ""
        if sig['phrases']:
            search_term = list(sig['phrases'])[0]
        elif sig['keywords']:
            search_term = list(sig['keywords'])[0]
        elif sig['title_stems']:
            search_term = list(sig['title_stems'])[0]
        else:
            clean_t = re.sub(r'[^א-ת\s]', '', title).strip()
            search_term = " ".join(clean_t.split()[:2])

        tools.append({
            'title': f'חיפוש "{search_term}" במאגר התורני',
            'subtitle': 'סריקה בתנ"ך, משנה, תוספתא, בבלי, ירושלמי, רמב"ם ושולחן ערוך',
            'url': f'/advanced-search/?q={search_term}',
            'icon': 'bi-search',
            'is_primary_search': True,
            'search_term': search_term,
        })

        return tools[:2]

    @classmethod
    def get_learning_context(cls, article, all_articles=None, min_score_override=None):
        runtime_cfg = cls.get_runtime_config()
        active_min_score = int(min_score_override) if min_score_override is not None else runtime_cfg['min_connection_score']
        public_enabled = runtime_cfg['public_enabled']

        mem_key = f"ctx_{ENGINE_VERSION}_{article.pk}_{active_min_score}_{public_enabled}"
        if mem_key in _MEM_CACHE:
            return _MEM_CACHE[mem_key]

        indexed_articles = cls._get_all_indexed_articles()
        curr_entry = next((item for item in indexed_articles if item['pk'] == article.pk), None)

        if not curr_entry:
            snippet = cls.clean_text_fast(article.content or '', 900)
            sig = cls._extract_distinctive_signature(article.title or '', snippet)
            curr_entry = {
                'pk': article.pk,
                'title': article.title or '',
                'slug': article.slug,
                'parasha': article.parasha or '',
                'snippet': snippet,
                'cluster_id': sig['cluster']['id'],
                'cluster_title': sig['cluster']['title'],
                'icon': sig['cluster']['icon'],
                'description': sig['cluster']['description'],
                'score': sig['cluster_score'],
                'breakdown': sig['breakdown'],
                'signature': sig,
                'stage': 2,
                'sort_key': (2, -sig['cluster_score'], article.pk),
            }

        curr_sig = curr_entry['signature']
        path_articles = [a for a in indexed_articles if a['cluster_id'] == curr_entry['cluster_id']]
        path_articles.sort(key=lambda x: x['sort_key'])

        total_in_path = len(path_articles)
        position = 1
        prev_article = None
        next_article = None

        for idx, item in enumerate(path_articles):
            if item['pk'] == article.pk:
                position = idx + 1
                if idx > 0:
                    prev_article = path_articles[idx - 1]
                if idx < total_in_path - 1:
                    next_article = path_articles[idx + 1]
                break

        stage_labels = {
            1: 'שלב א׳: יסודות וגדרים',
            2: 'שלב ב׳: עיקרי ההלכה',
            3: 'שלב ג׳: הלכה למעשה ופרטי דינים'
        }

        scored_articles = []
        for cand in indexed_articles:
            if cand['pk'] == article.pk:
                continue
            sim_score, reasons = cls._calculate_pair_similarity(
                curr_sig, cand['signature'],
                curr_entry['parasha'], cand['parasha'],
                is_book_target=False
            )
            if sim_score >= active_min_score:
                scored_articles.append({
                    'article': {'pk': cand['pk'], 'title': cand['title'], 'slug': cand['slug']},
                    'score': sim_score,
                    'reasons': reasons,
                })

        scored_articles.sort(key=lambda x: (-x['score'], -x['article']['pk']))
        strong_related_articles = scored_articles[:3]
        has_strong_article_match = len(strong_related_articles) > 0

        if not strong_related_articles:
            for p_art in path_articles:
                if p_art['pk'] != article.pk:
                    strong_related_articles.append({
                        'article': {'pk': p_art['pk'], 'title': p_art['title'], 'slug': p_art['slug']},
                        'score': 10,
                        'reasons': [curr_entry['cluster_title']],
                    })
                if len(strong_related_articles) >= 2:
                    break

        # Book matching with strict deduplication by title and max 2 chapters per book
        raw_scored_books = []
        for b_unit in cls._get_indexed_book_units():
            sim_score, reasons = cls._calculate_pair_similarity(
                curr_sig, b_unit['signature'], is_book_target=True
            )
            if sim_score >= active_min_score:
                unit_copy = {k: v for k, v in b_unit.items() if k != 'signature'}
                unit_copy['match_score'] = sim_score
                unit_copy['reasons'] = reasons
                raw_scored_books.append(unit_copy)

        raw_scored_books.sort(key=lambda x: -x['match_score'])
        matched_book_units = []
        seen_display_keys = set()
        book_count_per_id = {}

        for b_cand in raw_scored_books:
            disp_key = (b_cand['book_title'].strip(), b_cand['title'].strip())
            if disp_key in seen_display_keys:
                continue
            b_id = b_cand['book_id']
            if book_count_per_id.get(b_id, 0) >= 2:
                continue
            seen_display_keys.add(disp_key)
            book_count_per_id[b_id] = book_count_per_id.get(b_id, 0) + 1
            matched_book_units.append(b_cand)
            if len(matched_book_units) >= 3:
                break

        scored_qas = []
        seen_qa_questions = set()
        for q_unit in cls._get_indexed_qa_units():
            sim_score, reasons = cls._calculate_pair_similarity(
                curr_sig, q_unit['signature'], is_book_target=False
            )
            if sim_score >= active_min_score:
                q_norm = q_unit['question'].strip()
                if q_norm in seen_qa_questions:
                    continue
                seen_qa_questions.add(q_norm)
                q_copy = {k: v for k, v in q_unit.items() if k != 'signature'}
                q_copy['match_score'] = sim_score
                q_copy['reasons'] = reasons
                scored_qas.append(q_copy)

        scored_qas.sort(key=lambda x: -x['match_score'])
        matched_qas = scored_qas[:3]

        smart_tools = cls.get_smart_tools_for_article(curr_entry['title'], curr_entry['snippet'], curr_sig)

        is_orphan_or_weak = (
            curr_entry['cluster_id'] == 'general_iyun' or
            curr_entry['score'] < 12 or
            (not has_strong_article_match and not matched_book_units and not matched_qas)
        )

        payload = {
            'public_enabled': public_enabled,
            'min_connection_score': active_min_score,
            'cluster': {
                'cluster_id': curr_entry['cluster_id'],
                'cluster_title': curr_entry['cluster_title'],
                'icon': curr_entry['icon'],
                'description': curr_entry['description'],
                'score': curr_entry['score'],
                'breakdown': curr_entry['breakdown'],
            },
            'navigation': {
                'position': position,
                'total_in_path': total_in_path,
                'stage_label': stage_labels.get(curr_entry['stage'], 'עיונים בסוגיה'),
                'prev_article': prev_article,
                'next_article': next_article,
            },
            'related_articles': strong_related_articles,
            'book_units': matched_book_units,
            'related_qas': matched_qas,
            'smart_tools': smart_tools,
            'has_strong_matches': has_strong_article_match or bool(matched_book_units) or bool(matched_qas),
            'is_orphan_or_weak': is_orphan_or_weak,
        }
        _MEM_CACHE[mem_key] = payload
        return payload

    @classmethod
    def generate_admin_audit_report(cls, min_score_override=None):
        runtime_cfg = cls.get_runtime_config()
        active_min_score = int(min_score_override) if min_score_override is not None else runtime_cfg['min_connection_score']

        indexed_articles = sorted(cls._get_all_indexed_articles(), key=lambda x: x['title'])
        rows = []
        weak_articles = []

        class _LightArticleObj:
            def __init__(self, pk, title, slug, parasha):
                self.pk = pk
                self.title = title
                self.slug = slug
                self.parasha = parasha
                self.content = ""

        for item in indexed_articles:
            light_art = _LightArticleObj(item['pk'], item['title'], item['slug'], item['parasha'])
            ctx = cls.get_learning_context(light_art, min_score_override=active_min_score)
            row = {
                'article': light_art,
                'cluster_title': ctx['cluster']['cluster_title'],
                'cluster_score': ctx['cluster']['score'],
                'breakdown': ctx['cluster']['breakdown'],
                'related_articles': ctx['related_articles'],
                'book_units': ctx['book_units'],
                'related_qas': ctx['related_qas'],
                'smart_tools': ctx['smart_tools'],
                'is_weak': ctx['is_orphan_or_weak'],
            }
            rows.append(row)
            if ctx['is_orphan_or_weak']:
                weak_articles.append(row)

        cluster_summary = {}
        for r in rows:
            c_name = r['cluster_title']
            cluster_summary[c_name] = cluster_summary.get(c_name, 0) + 1

        return {
            'total_articles': len(indexed_articles),
            'weak_count': len(weak_articles),
            'strong_count': len(indexed_articles) - len(weak_articles),
            'weak_articles': weak_articles,
            'rows': rows,
            'cluster_summary': cluster_summary,
            'active_min_score': active_min_score,
            'saved_min_score': runtime_cfg['min_connection_score'],
            'public_enabled': runtime_cfg['public_enabled'],
        }