import json
import os
import re
from django.conf import settings
from django.core.cache import cache
from django.utils.html import strip_tags
from .models import Article, Book, Chapter, Section, QA

DEFAULT_MIN_CONNECTION_SCORE = 24
TITLE_WEIGHT = 10
BODY_WEIGHT = 1
MAX_BODY_HITS = 6
CACHE_TIMEOUT = 60 * 60 * 24
ENGINE_VERSION = "v8_controlled"

RUNTIME_CONFIG_PATH = os.path.join(settings.BASE_DIR, 'clusters_runtime_config.json')

MANUAL_ARTICLE_OVERRIDES = {
    # Optional manual overrides by article.slug or article.id:
    # 'example-slug': {'cluster_id': 'brachot'}
}

GRAVITY_CLUSTERS = [
    {
        'id': 'brachot',
        'title': 'ברכות ותפילה',
        'icon': 'bi-stars',
        'description': 'סוגיות ובירורי הלכה בברכות הנהנין, ברכות הריח, שהחיינו, ברכות הראייה והשבח והלכות תפילה.',
        'phrases': [
            'ברכת הריח', 'ברכות הריח', 'בגדים מבושמים', 'שמן אפרסמון', 'ריח טוב',
            'ברכת שהחיינו', 'הטוב והמטיב', 'ברכת הזמן', 'חכם הרזים', 'שישים ריבוא',
            'מחיה המתים', 'ברכת הקשת', 'קשת בענן', 'ברכת הגומל', 'ברכת האורח',
            'שמונה עשרה', 'קריאת שמע', 'ברכות השחר', 'ברכת כהנים', 'ברכת המזון',
            'בשם ומלכות', 'ספק ברכות'
        ],
        'keywords': [
            'ברכה', 'ברכות', 'ברכת', 'מברך', 'לברך', 'שהחיינו', 'בשמים', 'מבושמים',
            'אפרסמון', 'מוגמר', 'להריח', 'הקשת', 'הגומל', 'תפילה', 'תפילת', 'עמידה',
            'ציצית', 'תפילין'
        ]
    },
    {
        'id': 'moadim',
        'title': 'שבת ומועדי ישראל',
        'icon': 'bi-calendar-heart',
        'description': 'עיונים והלכות בשבת, חנוכה, סוכה וארבעת המינים, פסח, פורים ומועדי השנה.',
        'phrases': [
            'נר חנוכה', 'נרות חנוכה', 'הדלקת נרות', 'פרסומי ניסא', 'כבתה אין זקוק לה',
            'ארבעת המינים', 'נטילת לולב', 'תשבו כעין תדורו', 'ליל הסדר', 'חמץ ומצה',
            'בדיקת חמץ', 'מקרא מגילה', 'משלוח מנות', 'ראש השנה', 'תקיעת שופר',
            'יום הכיפורים', 'יום טוב', 'עונג שבת', 'תחום שבת'
        ],
        'keywords': [
            'שבת', 'מועד', 'מועדים', 'חנוכה', 'הדלקה', 'חנוכיה', 'סוכה', 'סוכות',
            'סכך', 'דפנות', 'לולב', 'אתרוג', 'הדס', 'ערבה', 'פסח', 'חמץ', 'מצה',
            'פורים', 'מגילה', 'שופר', 'מוקצה', 'עירוב', 'עירובין', 'קידוש', 'הבדלה'
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
            'פירות ארץ ישראל', 'ישוב ארץ ישראל', 'מצוות התלויות בארץ', 'שביעית',
            'שנת השמיטה', 'על שהנחלת'
        ],
        'keywords': [
            'מעשר', 'מעשרות', 'תרומות', 'תרומה', 'טבל', 'דמאי', 'שמיטה', 'שביעית',
            'שהנחלת', 'נחלה', 'גורל', 'ירושלים', 'מקדש'
        ]
    },
    {
        'id': 'mishpacha_mila',
        'title': 'משפחה, חופה וברית מילה',
        'icon': 'bi-people-fill',
        'description': 'הלכות ברית מילה וברכותיה, זמני המילה, גדרי החופה וברכות הנישואין, קידושין ואבן העזר.',
        'phrases': [
            'ברית מילה', 'זמני המילה', 'זריזין מקדימין למילה', 'מילה שלא בזמנה',
            'אבי הבן', 'ברית אברהם', 'גדרי החופה', 'חופה וקידושין', 'שבע ברכות',
            'ברכת חתנים', 'פנים חדשות', 'חדר ייחוד', 'פדיון הבן'
        ],
        'keywords': [
            'מילה', 'מוהל', 'סנדק', 'נימול', 'פריעה', 'מציצה', 'חופה', 'נישואין',
            'קידושין', 'אירוסין', 'חתן', 'כלה', 'כתובה', 'ייחוד'
        ]
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
        'keywords': [
            'טומאה', 'טהרה', 'טמא', 'טהור', 'מקווה', 'מקוואות', 'טבילה', 'חציצה',
            'אמה', 'טפח', 'טפחים', 'אצבע', 'זרת', 'מיל', 'רביעית', 'לוג', 'כזית',
            'כביצה', 'סלע', 'שקל', 'שיעור', 'שיעורים', 'מידות'
        ]
    },
    {
        'id': 'choshen_iyun',
        'title': 'חושן משפט, חזקות ועיונים',
        'icon': 'bi-journal-bookmark-fill',
        'description': 'דיני חזקות, ריבית, ממונות, קניינים, ספקות, מנהגים וכללי פסיקה בעיון הש"ס והפוסקים.',
        'phrases': [
            'דיני חזקות', 'חזקת מרא קמא', 'המוציא מחברו', 'היתר עסקה', 'איסור ריבית',
            'דיני ממונות', 'ספק ספיקא', 'מנהג ישראל', 'כללי פסיקה'
        ],
        'keywords': [
            'חזקה', 'חזקות', 'חזקת', 'מוחזק', 'ריבית', 'ממון', 'ממונות', 'קניין',
            'בעלות', 'רוב', 'מנהג', 'מנהגים', 'שטר', 'עדים', 'שבועה', 'נדר', 'נדרים'
        ]
    },
]

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
    'למעשה', 'בזמן', 'הזה', 'חלק', 'ספר', 'מאמר', 'הרב', 'משה', 'לייבוביץ'
}


class ClusterEngine:
    _regex_cache = {}

    @classmethod
    def get_runtime_config(cls):
        default_cfg = {
            'min_connection_score': getattr(settings, 'CLUSTER_MIN_CONNECTION_SCORE', DEFAULT_MIN_CONNECTION_SCORE),
            'public_enabled': False,
        }
        if os.path.exists(RUNTIME_CONFIG_PATH):
            try:
                with open(RUNTIME_CONFIG_PATH, 'r', encoding='utf-8') as f:
                    saved = json.load(f)
                    default_cfg['min_connection_score'] = int(saved.get('min_connection_score', default_cfg['min_connection_score']))
                    default_cfg['public_enabled'] = bool(saved.get('public_enabled', False))
            except Exception:
                pass
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
        cache.clear()
        return cfg

    @classmethod
    def _get_kw_regex(cls, keyword: str):
        kw_lower = keyword.lower().strip()
        if kw_lower not in cls._regex_cache:
            pattern = rf'(?<![א-תa-z0-9])(?:ו?[הבכלמש])?{re.escape(kw_lower)}(?![א-תa-z0-9])'
            cls._regex_cache[kw_lower] = re.compile(pattern)
        return cls._regex_cache[kw_lower]

    @staticmethod
    def clean_text(html_content: str) -> str:
        if not html_content:
            return ""
        txt = strip_tags(str(html_content))
        txt = re.sub(r'הערות שוליים.*$', '', txt, flags=re.DOTALL)
        return re.sub(r'\s+', ' ', txt).strip()

    @classmethod
    def _count_matches(cls, text_lower: str, keyword: str) -> int:
        if not text_lower or not keyword:
            return 0
        return len(cls._get_kw_regex(keyword).findall(text_lower))

    @classmethod
    def _extract_distinctive_signature(cls, title: str, body: str):
        title_clean = cls.clean_text(title).lower()
        body_clean = cls.clean_text(body).lower()

        matched_phrases = set()
        matched_keywords = set()
        cluster_scores = {}
        keyword_breakdown = {}

        for cluster in GRAVITY_CLUSTERS:
            c_score = 0
            for phrase in cluster['phrases']:
                t_hits = cls._count_matches(title_clean, phrase)
                b_hits = min(MAX_BODY_HITS, cls._count_matches(body_clean, phrase))
                if t_hits > 0 or b_hits > 0:
                    pts = (t_hits * TITLE_WEIGHT * 1.8) + (b_hits * BODY_WEIGHT * 2.5)
                    c_score += pts
                    matched_phrases.add(phrase)
                    keyword_breakdown[phrase] = keyword_breakdown.get(phrase, 0) + round(pts, 1)

            for kw in cluster['keywords']:
                t_hits = cls._count_matches(title_clean, kw)
                b_hits = min(MAX_BODY_HITS, cls._count_matches(body_clean, kw))
                if t_hits > 0 or b_hits >= 2:
                    pts = (t_hits * TITLE_WEIGHT) + (b_hits * BODY_WEIGHT)
                    c_score += pts
                    matched_keywords.add(kw)
                    keyword_breakdown[kw] = keyword_breakdown.get(kw, 0) + round(pts, 1)

            cluster_scores[cluster['id']] = round(c_score, 1)

        raw_title_words = re.findall(r'[א-ת]{3,}', title_clean)
        title_specific_stems = set()
        for w in raw_title_words:
            if w in GENERIC_NOISE_WORDS:
                continue
            stem = w[1:] if (len(w) >= 5 and w[0] in 'הבכלמשו') else w
            if stem not in GENERIC_NOISE_WORDS and len(stem) >= 3:
                title_specific_stems.add(stem)

        raw_body_words = re.findall(r'[א-ת]{4,}', body_clean[:2500])
        body_freq = {}
        for w in raw_body_words:
            if w in GENERIC_NOISE_WORDS:
                continue
            stem = w[1:] if (len(w) >= 5 and w[0] in 'הבכלמשו') else w
            if stem not in GENERIC_NOISE_WORDS and len(stem) >= 3:
                body_freq[stem] = body_freq.get(stem, 0) + 1

        dominant_body_stems = {st for st, cnt in body_freq.items() if cnt >= 2 or st in title_specific_stems}

        best_cluster_id = max(cluster_scores.items(), key=lambda x: x[1])[0] if cluster_scores else 'choshen_iyun'
        best_score = cluster_scores.get(best_cluster_id, 0)
        if best_score <= 0:
            best_cluster_id = 'choshen_iyun'

        best_cluster_obj = next((c for c in GRAVITY_CLUSTERS if c['id'] == best_cluster_id), GRAVITY_CLUSTERS[-1])
        sorted_breakdown = sorted(keyword_breakdown.items(), key=lambda x: -x[1])[:6]

        return {
            'cluster': best_cluster_obj,
            'cluster_score': best_score,
            'phrases': matched_phrases,
            'keywords': matched_keywords,
            'title_stems': title_specific_stems,
            'body_stems': dominant_body_stems,
            'breakdown': sorted_breakdown,
        }

    @classmethod
    def _calculate_pair_similarity(cls, sig_a, sig_b, parasha_a="", parasha_b="") -> tuple:
        shared_phrases = sig_a['phrases'] & sig_b['phrases']
        shared_keywords = sig_a['keywords'] & sig_b['keywords']
        shared_title_stems = sig_a['title_stems'] & sig_b['title_stems']
        title_to_body_stems = (sig_a['title_stems'] & sig_b['body_stems']) | (sig_b['title_stems'] & sig_a['body_stems'])

        score = 0
        reasons = []

        if shared_phrases:
            score += len(shared_phrases) * 35
            reasons.extend(list(shared_phrases)[:3])

        if shared_title_stems:
            score += len(shared_title_stems) * 26
            for st in list(shared_title_stems)[:2]:
                if st not in reasons:
                    reasons.append(st)

        if shared_keywords:
            score += len(shared_keywords) * 14
            for kw in list(shared_keywords)[:2]:
                if kw not in reasons:
                    reasons.append(kw)

        if title_to_body_stems:
            score += len(title_to_body_stems) * 10

        if sig_a['cluster']['id'] == sig_b['cluster']['id'] and score >= 14:
            score += 10

        if parasha_a and parasha_b and parasha_a == parasha_b and 'general' not in parasha_a:
            score += 18
            reasons.append(f"פרשת {parasha_a.strip(',')}")

        return score, reasons[:3]

    @classmethod
    def classify(cls, article):
        cache_key = f"bm_classify_{ENGINE_VERSION}_{article.pk}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        override = MANUAL_ARTICLE_OVERRIDES.get(article.slug) or MANUAL_ARTICLE_OVERRIDES.get(article.pk) or {}
        sig = cls._extract_distinctive_signature(article.title or '', article.content or '')
        cluster_obj = sig['cluster']

        if override.get('cluster_id'):
            cluster_obj = next((c for c in GRAVITY_CLUSTERS if c['id'] == override['cluster_id']), cluster_obj)

        result = {
            'cluster_id': cluster_obj['id'],
            'cluster_title': cluster_obj['title'],
            'icon': cluster_obj['icon'],
            'description': cluster_obj['description'],
            'score': sig['cluster_score'],
            'breakdown': sig['breakdown'],
            'signature': sig,
        }
        cache.set(cache_key, result, CACHE_TIMEOUT)
        return result

    @classmethod
    def get_smart_tools_for_article(cls, article, sig):
        text_combined = f"{article.title or ''} {cls.clean_text(article.content or '')[:1500]}"
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
            clean_t = re.sub(r'[^א-ת\s]', '', article.title or '').strip()
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
    def _get_indexed_book_units(cls):
        cache_key = f"bm_book_units_{ENGINE_VERSION}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        units = []
        books = Book.objects.prefetch_related('chapters__sections').all()

        for book in books:
            chapters = list(book.chapters.all().order_by('order', 'id'))
            if chapters:
                for ch in chapters:
                    sections = list(ch.sections.all().order_by('order', 'id'))
                    if sections:
                        for sec in sections:
                            full_title = f"{book.title} {ch.title} {sec.title}"
                            sig = cls._extract_distinctive_signature(full_title, sec.content or '')
                            preview = cls.clean_text(sec.content or '')[:150]
                            if len(preview) == 150:
                                preview = preview.rsplit(' ', 1)[0] + '...'
                            units.append({
                                'unit_type': 'section',
                                'book_id': book.pk,
                                'book_title': book.title,
                                'chapter_id': ch.pk,
                                'chapter_title': ch.title,
                                'section_id': sec.pk,
                                'title': f"{ch.title} – {sec.title}",
                                'badge': f'מתוך הספר "{book.title}"',
                                'preview': preview,
                                'url': f"/book/{book.pk}/?chapter={ch.pk}&section={sec.pk}#section-{sec.pk}",
                                'signature': sig,
                            })
                    else:
                        full_title = f"{book.title} {ch.title}"
                        sig = cls._extract_distinctive_signature(full_title, book.summary or '')
                        units.append({
                            'unit_type': 'chapter',
                            'book_id': book.pk,
                            'book_title': book.title,
                            'chapter_id': ch.pk,
                            'chapter_title': ch.title,
                            'section_id': None,
                            'title': ch.title,
                            'badge': f'מתוך הספר "{book.title}"',
                            'preview': cls.clean_text(book.summary or '')[:140],
                            'url': f"/book/{book.pk}/?chapter={ch.pk}#chapter-{ch.pk}",
                            'signature': sig,
                        })
            else:
                sig = cls._extract_distinctive_signature(book.title or '', book.summary or '')
                preview = cls.clean_text(book.summary or '')[:150]
                if len(preview) == 150:
                    preview = preview.rsplit(' ', 1)[0] + '...'
                units.append({
                    'unit_type': 'book',
                    'book_id': book.pk,
                    'book_title': book.title,
                    'chapter_id': None,
                    'chapter_title': '',
                    'section_id': None,
                    'title': f'הספר "{book.title}"',
                    'badge': 'ספר שלם בספרייה',
                    'preview': preview,
                    'url': f"/book/{book.pk}/",
                    'signature': sig,
                })

        cache.set(cache_key, units, CACHE_TIMEOUT)
        return units

    @classmethod
    def _get_indexed_qa_units(cls):
        cache_key = f"bm_qa_units_{ENGINE_VERSION}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        qa_units = []
        for qa in QA.objects.all():
            sig = cls._extract_distinctive_signature(
                f"{qa.question or ''} {qa.category or ''}",
                qa.answer or ''
            )
            preview = cls.clean_text(qa.answer or '')[:140]
            if len(preview) == 140:
                preview = preview.rsplit(' ', 1)[0] + '...'
            qa_units.append({
                'qa_id': qa.pk,
                'question': qa.question,
                'category': qa.category or 'שו"ת הלכתי',
                'preview': preview,
                'url': f"/qa/?open={qa.pk}#qa-{qa.pk}",
                'signature': sig,
            })

        cache.set(cache_key, qa_units, CACHE_TIMEOUT)
        return qa_units

    @classmethod
    def _pedagogical_sort_key(cls, article):
        title = str(getattr(article, 'title', '') or '')
        info = cls.classify(article)
        foundational = ('גדר', 'גדרי', 'יסוד', 'יסודות', 'מהות', 'כלל', 'כללי', 'מבוא', 'מקור', 'חיוב', 'מצוות')
        specific = ('ספק', 'בדיעבד', 'האם', 'מתי', 'כיצד', 'איך', 'מנהג', 'בזמן הזה')

        if any(t in title for t in foundational):
            stage = 1
        elif any(t in title for t in specific):
            stage = 3
        else:
            stage = 2
        return (stage, -info['score'], article.pk)

    @classmethod
    def get_cluster_path_articles(cls, cluster_id: str, all_articles):
        filtered = [art for art in all_articles if cls.classify(art)['cluster_id'] == cluster_id]
        filtered.sort(key=cls._pedagogical_sort_key)
        return filtered

    @classmethod
    def get_learning_context(cls, article, all_articles=None, min_score_override=None):
        if all_articles is None:
            all_articles = list(Article.objects.filter(is_published=True))

        runtime_cfg = cls.get_runtime_config()
        active_min_score = int(min_score_override) if min_score_override is not None else runtime_cfg['min_connection_score']
        public_enabled = runtime_cfg['public_enabled']

        cache_key = f"bm_learning_ctx_{ENGINE_VERSION}_{article.pk}_{len(all_articles)}_{active_min_score}_{public_enabled}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        curr_info = cls.classify(article)
        curr_sig = curr_info['signature']
        path_articles = cls.get_cluster_path_articles(curr_info['cluster_id'], all_articles)

        total_in_path = len(path_articles)
        position = 1
        prev_article = None
        next_article = None

        for idx, item in enumerate(path_articles):
            if item.pk == article.pk:
                position = idx + 1
                if idx > 0:
                    prev_article = path_articles[idx - 1]
                if idx < total_in_path - 1:
                    next_article = path_articles[idx + 1]
                break

        stage_num, _, _ = cls._pedagogical_sort_key(article)
        stage_labels = {
            1: 'שלב א׳: יסודות וגדרים',
            2: 'שלב ב׳: עיקרי ההלכה',
            3: 'שלב ג׳: הלכה למעשה ופרטי דינים'
        }

        scored_articles = []
        for cand in all_articles:
            if cand.pk == article.pk:
                continue
            cand_info = cls.classify(cand)
            sim_score, reasons = cls._calculate_pair_similarity(
                curr_sig, cand_info['signature'],
                getattr(article, 'parasha', ''), getattr(cand, 'parasha', '')
            )
            if sim_score >= active_min_score:
                scored_articles.append({
                    'article': cand,
                    'score': sim_score,
                    'reasons': reasons,
                })

        scored_articles.sort(key=lambda x: (-x['score'], -x['article'].pk))
        strong_related_articles = scored_articles[:3]
        has_strong_article_match = len(strong_related_articles) > 0

        if not strong_related_articles:
            for p_art in path_articles:
                if p_art.pk != article.pk:
                    strong_related_articles.append({
                        'article': p_art,
                        'score': 10,
                        'reasons': [curr_info['cluster_title']],
                    })
                if len(strong_related_articles) >= 2:
                    break

        scored_books = []
        seen_book_chapters = set()
        for b_unit in cls._get_indexed_book_units():
            sim_score, reasons = cls._calculate_pair_similarity(curr_sig, b_unit['signature'])
            if sim_score >= active_min_score:
                dedup_key = (b_unit['book_id'], b_unit['chapter_id'] or 0)
                if dedup_key not in seen_book_chapters:
                    seen_book_chapters.add(dedup_key)
                    unit_copy = dict(b_unit)
                    unit_copy['match_score'] = sim_score
                    unit_copy['reasons'] = reasons
                    scored_books.append(unit_copy)

        scored_books.sort(key=lambda x: -x['match_score'])
        matched_book_units = scored_books[:3]

        scored_qas = []
        for q_unit in cls._get_indexed_qa_units():
            sim_score, reasons = cls._calculate_pair_similarity(curr_sig, q_unit['signature'])
            if sim_score >= active_min_score:
                q_copy = dict(q_unit)
                q_copy['match_score'] = sim_score
                q_copy['reasons'] = reasons
                scored_qas.append(q_copy)

        scored_qas.sort(key=lambda x: -x['match_score'])
        matched_qas = scored_qas[:3]

        smart_tools = cls.get_smart_tools_for_article(article, curr_sig)

        is_orphan_or_weak = (
            curr_info['score'] < 15 and
            not has_strong_article_match and
            not matched_book_units and
            not matched_qas
        )

        payload = {
            'public_enabled': public_enabled,
            'min_connection_score': active_min_score,
            'cluster': {
                'cluster_id': curr_info['cluster_id'],
                'cluster_title': curr_info['cluster_title'],
                'icon': curr_info['icon'],
                'description': curr_info['description'],
                'score': curr_info['score'],
                'breakdown': curr_info['breakdown'],
            },
            'navigation': {
                'position': position,
                'total_in_path': total_in_path,
                'stage_label': stage_labels.get(stage_num, 'עיונים בסוגיה'),
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
        cache.set(cache_key, payload, CACHE_TIMEOUT)
        return payload

    @classmethod
    def generate_admin_audit_report(cls, min_score_override=None):
        runtime_cfg = cls.get_runtime_config()
        active_min_score = int(min_score_override) if min_score_override is not None else runtime_cfg['min_connection_score']

        all_articles = list(Article.objects.filter(is_published=True).order_by('title'))
        rows = []
        weak_articles = []

        for art in all_articles:
            ctx = cls.get_learning_context(art, all_articles, min_score_override=active_min_score)
            row = {
                'article': art,
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
            'total_articles': len(all_articles),
            'weak_count': len(weak_articles),
            'strong_count': len(all_articles) - len(weak_articles),
            'weak_articles': weak_articles,
            'rows': rows,
            'cluster_summary': cluster_summary,
            'active_min_score': active_min_score,
            'saved_min_score': runtime_cfg['min_connection_score'],
            'public_enabled': runtime_cfg['public_enabled'],
        }