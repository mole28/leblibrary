import json
import os
import re
from django.conf import settings
from .models import Article, Book, Chapter, QA

DEFAULT_MIN_CONNECTION_SCORE = 26
TITLE_WEIGHT = 10
BODY_WEIGHT = 1
MAX_BODY_HITS = 5
ENGINE_VERSION = "v14_full_control"

RUNTIME_CONFIG_PATH = os.path.join(settings.BASE_DIR, 'clusters_runtime_config.json')
EDITORIAL_DB_PATH = os.path.join(settings.BASE_DIR, 'editorial_connections.json')

_MEM_CACHE = {}
_WORD_RX_CACHE = {}

UNCLASSIFIED_CLUSTER = {
    'id': 'general_iyun',
    'title': 'עיונים כלליים (לבדיקה)',
    'icon': 'bi-book-half',
    'emoji': '🔍',
    'description': 'מאמרים הממתינים לשיוך נושאי ידני על ידי העורך (אינו מוצג לציבור כקטגוריה).',
}

TOOLS_CATALOG = [
    {
        'tool_key': 'aramaic_translator',
        'title': 'מתרגם ארמי ⇄ עברי לש"ס',
        'subtitle': 'פענוח ותרגום מונחי התלמוד הבבלי, הירושלמי והזוהר',
        'url': '/aramaic-translator/',
        'icon': 'bi-translate',
    },
    {
        'tool_key': 'calc_length',
        'title': 'מחשבון מידות אורך בתורה',
        'subtitle': 'המרת אמה, טפח, זרת ואצבע לסנטימטרים לפי שיטות הפוסקים',
        'url': '/calculator/',
        'icon': 'bi-rulers',
    },
    {
        'tool_key': 'calc_volume',
        'title': 'מחשבון מידות נפח הלכתי',
        'subtitle': 'חישוב כזית, כביצה, רביעית, לוג ומקווה בסמ"ק',
        'url': '/volume-calculator/',
        'icon': 'bi-cup-straw',
    },
    {
        'tool_key': 'calc_weight',
        'title': 'מחשבון משקל ומטבעות חז"ל',
        'subtitle': 'חישוב משקלי התורה ומטבעות ההלכה בגרמים',
        'url': '/weight-calculator/',
        'icon': 'bi-coin',
    },
    {
        'tool_key': 'torah_search_general',
        'title': 'מנוע החיפוש התורני המתקדם',
        'subtitle': 'חיפוש בתנ"ך, משנה, תוספתא, בבלי, ירושלמי, רמב"ם ושולחן ערוך',
        'url': '/advanced-search/',
        'icon': 'bi-search',
    },
]

TOOLS_BY_KEY = {t['tool_key']: t for t in TOOLS_CATALOG}

GRAVITY_CLUSTERS = [
    {
        'id': 'brachot',
        'title': 'ברכות ותפילה',
        'icon': 'bi-stars',
        'emoji': '📖',
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
        'id': 'eretz_yisrael',
        'title': 'ארץ ישראל ומצוותיה',
        'icon': 'bi-geo-alt-fill',
        'emoji': '🌍',
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
        'id': 'moadim',
        'title': 'שבת ומועדי ישראל',
        'icon': 'bi-calendar-heart',
        'emoji': '🕯',
        'description': 'עיונים והלכות בשבת, חנוכה, סוכה וארבעת המינים, פסח, פורים ומועדי השנה.',
        'phrases': [
            'נר חנוכה', 'נרות חנוכה', 'הדלקת נרות', 'פרסומי ניסא', 'כבתה אין זקוק לה',
            'ארבעת המינים', 'נטילת לולב', 'תשבו כעין תדורו', 'שמיני עצרת', 'שמחת תורה',
            'ליל הסדר', 'חמץ ומצה', 'בדיקת חמץ', 'מקרא מגילה', 'משלוח מנות',
            'ראש השנה', 'תקיעת שופר', 'יום הכיפורים', 'יום טוב', 'יו"ט שני', 'פסח שני',
            'עונג שבת', 'תחום שבת', 'תשעה באב', 'בין המצרים', 'ראש חודש'
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
        'id': 'mishpacha_mila',
        'title': 'משפחה, חופה וברית מילה',
        'icon': 'bi-people-fill',
        'emoji': '👨‍👩‍👦',
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
        'emoji': '📏',
        'description': 'סוגיות בהלכות טומאה וטהרה, מקוואות, נטילת ידיים, ומידות ושיעורי חז"ל.',
        'phrases': [
            'טומאה וטהרה', 'נטילת ידיים', 'מידות חז"ל', 'שיעורי תורה', 'טומאת אהל',
            'טומאת מת', 'ארבעים סאה', 'מי מקווה', 'טהרת כלים', 'שיעור כזית', 'שיעור רביעית'
        ],
        'specific_keywords': [
            'טומאה', 'טהרה', 'טמא', 'טהור', 'מקווה', 'מקוואות', 'טבילה', 'חציצה',
            'אמה', 'טפח', 'טפחים', 'אצבע', 'זרת', 'רביעית', 'לוג', 'כזית',
            'כביצה', 'סלע', 'שקל', 'מידות'
        ],
        'broad_classify_only': [
            'שיעור', 'שיעורים', 'כלים'
        ]
    },
    {
        'id': 'choshen_iyun',
        'title': 'חושן משפט, חזקות ועיונים',
        'icon': 'bi-journal-bookmark-fill',
        'emoji': '⚖️',
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

ALL_CLUSTERS_LIST = GRAVITY_CLUSTERS + [UNCLASSIFIED_CLUSTER]

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
    'ברכה', 'ברכות', 'ברכת', 'מברך', 'לברך', 'ברכותיה', 'וברכותיה', 'הברכה', 'הברכות',
    'תפילה', 'תפילת', 'התפילה', 'זמן', 'זמני', 'הזמן', 'הקדמה', 'מבוא', 'פתיחה',
    'סימנים', 'הערות', 'נספח', 'תוכן', 'עניינים', 'כלל', 'כללים', 'אופן', 'אמירת',
    'קריאת', 'מקורה', 'וטעמיה', 'בעולמו', 'החודש', 'נחם', 'האם', 'מתי', 'כיצד',
    'מיל', 'כלי', 'חג', 'שני', 'אחד', 'ביאור'
}


class ClusterEngine:

    @classmethod
    def _count_whole_word(cls, text: str, term: str) -> int:
        if not text or not term or term not in text:
            return 0
        rx = _WORD_RX_CACHE.get(term)
        if rx is None:
            rx = re.compile(rf'(?<![א-תa-z0-9])(?:ו?[הבכלמש])?{re.escape(term)}(?![א-תa-z0-9])')
            _WORD_RX_CACHE[term] = rx
        return len(rx.findall(text))

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

    @classmethod
    def get_editorial_db(cls) -> dict:
        if 'editorial_db' in _MEM_CACHE:
            return _MEM_CACHE['editorial_db']

        data = {}
        if os.path.exists(EDITORIAL_DB_PATH):
            try:
                with open(EDITORIAL_DB_PATH, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        data = loaded
            except Exception:
                data = {}
        _MEM_CACHE['editorial_db'] = data
        return data

    @classmethod
    def save_editorial_db(cls, data: dict):
        try:
            with open(EDITORIAL_DB_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        _MEM_CACHE.clear()

    @classmethod
    def get_article_editorial_record(cls, article_pk: int) -> dict:
        db = cls.get_editorial_db()
        key = str(article_pk)
        rec = db.get(key, {})
        return {
            'status': rec.get('status', 'pending'),
            'cluster_id': rec.get('cluster_id', ''),
            'articles': {
                'approved': [int(x) for x in rec.get('articles', {}).get('approved', []) if str(x).isdigit()],
                'rejected': [int(x) for x in rec.get('articles', {}).get('rejected', []) if str(x).isdigit()],
                'manual_added': [int(x) for x in rec.get('articles', {}).get('manual_added', []) if str(x).isdigit()],
            },
            'books': {
                'approved': list(rec.get('books', {}).get('approved', [])),
                'rejected': list(rec.get('books', {}).get('rejected', [])),
                'manual_added': list(rec.get('books', {}).get('manual_added', [])),
            },
            'qas': {
                'approved': [int(x) for x in rec.get('qas', {}).get('approved', []) if str(x).isdigit()],
                'rejected': [int(x) for x in rec.get('qas', {}).get('rejected', []) if str(x).isdigit()],
                'manual_added': [int(x) for x in rec.get('qas', {}).get('manual_added', []) if str(x).isdigit()],
            },
            'tools': {
                'approved': list(rec.get('tools', {}).get('approved', [])),
                'rejected': list(rec.get('tools', {}).get('rejected', [])),
                'manual_added': list(rec.get('tools', {}).get('manual_added', [])),
            }
        }

    @classmethod
    def update_editorial_decision(cls, article_pk: int, action: str, target_type: str = '', target_id='', bidirectional: bool = True):
        db = cls.get_editorial_db()
        key = str(article_pk)
        rec = cls.get_article_editorial_record(article_pk)

        if action in ('set_approved', 'set_pending', 'set_rejected'):
            rec['status'] = action.replace('set_', '')

        elif action == 'set_cluster':
            rec['cluster_id'] = str(target_id).strip()
            if rec['cluster_id'] and rec['cluster_id'] != 'general_iyun' and rec['status'] == 'pending':
                rec['status'] = 'approved'

        elif action == 'reset_cluster_to_ai':
            rec['cluster_id'] = ''

        elif target_type in ('articles', 'books', 'qas', 'tools') and target_id != '':
            t_val = int(target_id) if target_type in ('articles', 'qas') and str(target_id).isdigit() else str(target_id)
            bucket = rec[target_type]

            if action == 'item_approve':
                if t_val in bucket['rejected']:
                    bucket['rejected'].remove(t_val)
                if t_val not in bucket['approved'] and t_val not in bucket['manual_added']:
                    bucket['approved'].append(t_val)

            elif action == 'item_reject':
                if t_val in bucket['approved']:
                    bucket['approved'].remove(t_val)
                if t_val in bucket['manual_added']:
                    bucket['manual_added'].remove(t_val)
                if t_val not in bucket['rejected']:
                    bucket['rejected'].append(t_val)

            elif action == 'item_unreject':
                if t_val in bucket['rejected']:
                    bucket['rejected'].remove(t_val)

            elif action == 'item_add_manual':
                if t_val in bucket['rejected']:
                    bucket['rejected'].remove(t_val)
                if t_val not in bucket['manual_added']:
                    bucket['manual_added'].append(t_val)

                if target_type == 'articles' and bidirectional and isinstance(t_val, int) and t_val != int(article_pk):
                    other_rec = cls.get_article_editorial_record(t_val)
                    src_pk = int(article_pk)
                    if src_pk in other_rec['articles']['rejected']:
                        other_rec['articles']['rejected'].remove(src_pk)
                    if src_pk not in other_rec['articles']['manual_added']:
                        other_rec['articles']['manual_added'].append(src_pk)
                    db[str(t_val)] = other_rec

        db[key] = rec
        cls.save_editorial_db(db)
        return rec

    @classmethod
    def batch_article_ai_decision(cls, article_pk: int, mode: str):
        class _DummyArt:
            def __init__(self, pk):
                self.pk = pk
                self.title = ""
                self.slug = ""
                self.parasha = ""
                self.content = ""

        ctx = cls.get_learning_context(_DummyArt(int(article_pk)))
        db = cls.get_editorial_db()
        rec = cls.get_article_editorial_record(int(article_pk))

        if mode == 'approve_all_ai_for_article':
            for rel in ctx.get('related_articles', []):
                if rel.get('editorial_state') == 'ai_suggested':
                    tid = int(rel['article']['pk'])
                    if tid not in rec['articles']['approved'] and tid not in rec['articles']['manual_added']:
                        rec['articles']['approved'].append(tid)
            for b in ctx.get('book_units', []):
                if b.get('editorial_state') == 'ai_suggested':
                    ukey = str(b['unit_key'])
                    if ukey not in rec['books']['approved'] and ukey not in rec['books']['manual_added']:
                        rec['books']['approved'].append(ukey)
            for q in ctx.get('related_qas', []):
                if q.get('editorial_state') == 'ai_suggested':
                    qid = int(q['qa_id'])
                    if qid not in rec['qas']['approved'] and qid not in rec['qas']['manual_added']:
                        rec['qas']['approved'].append(qid)
            for t in ctx.get('smart_tools', []):
                if t.get('editorial_state') == 'ai_suggested':
                    tkey = str(t['tool_key'])
                    if tkey not in rec['tools']['approved'] and tkey not in rec['tools']['manual_added']:
                        rec['tools']['approved'].append(tkey)
            rec['status'] = 'approved'

        elif mode == 'reject_all_ai_for_article':
            for rel in ctx.get('related_articles', []):
                if rel.get('editorial_state') == 'ai_suggested':
                    tid = int(rel['article']['pk'])
                    if tid not in rec['articles']['rejected']:
                        rec['articles']['rejected'].append(tid)
            for b in ctx.get('book_units', []):
                if b.get('editorial_state') == 'ai_suggested':
                    ukey = str(b['unit_key'])
                    if ukey not in rec['books']['rejected']:
                        rec['books']['rejected'].append(ukey)
            for q in ctx.get('related_qas', []):
                if q.get('editorial_state') == 'ai_suggested':
                    qid = int(q['qa_id'])
                    if qid not in rec['qas']['rejected']:
                        rec['qas']['rejected'].append(qid)

        db[str(article_pk)] = rec
        cls.save_editorial_db(db)
        return rec

    @classmethod
    def approve_all_pending_articles(cls):
        db = cls.get_editorial_db()
        indexed = cls._get_all_indexed_articles()
        for item in indexed:
            pk_str = str(item['pk'])
            rec = cls.get_article_editorial_record(item['pk'])
            if rec['status'] == 'pending' and item['cluster_id'] != 'general_iyun':
                rec['status'] = 'approved'
                db[pk_str] = rec
        cls.save_editorial_db(db)

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

            for phrase in cluster['phrases']:
                t_hits = cls._count_whole_word(title_clean, phrase)
                b_hits = min(MAX_BODY_HITS, cls._count_whole_word(body_clean, phrase))
                if t_hits > 0 or b_hits > 0:
                    pts = (t_hits * TITLE_WEIGHT * 2.0) + (b_hits * BODY_WEIGHT * 3.0)
                    c_score += pts
                    matched_phrases.add(phrase)
                    keyword_breakdown[phrase] = keyword_breakdown.get(phrase, 0) + round(pts, 1)

            for kw in cluster['specific_keywords']:
                t_hits = cls._count_whole_word(title_clean, kw)
                b_hits = min(MAX_BODY_HITS, cls._count_whole_word(body_clean, kw))
                if t_hits > 0 or b_hits >= 2:
                    pts = (t_hits * TITLE_WEIGHT) + (b_hits * BODY_WEIGHT)
                    c_score += pts
                    matched_specific_keywords.add(kw)
                    keyword_breakdown[kw] = keyword_breakdown.get(kw, 0) + round(pts, 1)

            for b_kw in cluster.get('broad_classify_only', []):
                t_hits = cls._count_whole_word(title_clean, b_kw)
                b_hits = min(3, cls._count_whole_word(body_clean, b_kw))
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
            if stem not in GENERIC_NOISE_WORDS and len(stem) >= 4:
                title_specific_stems.add(stem)
            elif w not in GENERIC_NOISE_WORDS and len(w) >= 3:
                title_specific_stems.add(w)

        raw_body_words = re.findall(r'[א-ת]{4,}', body_clean)
        body_freq = {}
        for w in raw_body_words:
            if w in GENERIC_NOISE_WORDS:
                continue
            stem = w[1:] if (len(w) >= 5 and w[0] in 'הבכלמשו') else w
            if stem not in GENERIC_NOISE_WORDS and len(stem) >= 4:
                body_freq[stem] = body_freq.get(stem, 0) + 1

        dominant_body_stems = {st for st, cnt in body_freq.items() if cnt >= 2 or st in title_specific_stems}

        best_cluster_id, best_score = max(cluster_scores.items(), key=lambda x: x[1]) if cluster_scores else ('general_iyun', 0)

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

        editorial_db = cls.get_editorial_db()
        articles_index = []
        qs = Article.objects.filter(is_published=True).only('id', 'title', 'slug', 'parasha', 'content')

        for art in qs:
            snippet = cls.clean_text_fast(art.content or '', 900)
            sig = cls._extract_distinctive_signature(art.title or '', snippet)
            ed_rec = editorial_db.get(str(art.pk), {})

            ai_cluster_obj = sig['cluster']
            manual_cl_id = ed_rec.get('cluster_id', '').strip()

            if manual_cl_id:
                effective_cluster_obj = next((c for c in ALL_CLUSTERS_LIST if c['id'] == manual_cl_id), ai_cluster_obj)
                is_cluster_overridden = True
                editor_cluster_title = effective_cluster_obj['title']
            else:
                effective_cluster_obj = ai_cluster_obj
                is_cluster_overridden = False
                editor_cluster_title = None

            sig_with_override = dict(sig)
            sig_with_override['cluster'] = effective_cluster_obj

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
                'cluster_id': effective_cluster_obj['id'],
                'cluster_title': effective_cluster_obj['title'],
                'ai_cluster_id': ai_cluster_obj['id'],
                'ai_cluster_title': ai_cluster_obj['title'],
                'is_cluster_overridden': is_cluster_overridden,
                'editor_cluster_title': editor_cluster_title,
                'icon': effective_cluster_obj['icon'],
                'emoji': effective_cluster_obj.get('emoji', '📖'),
                'description': effective_cluster_obj['description'],
                'score': sig['cluster_score'],
                'breakdown': sig['breakdown'],
                'signature': sig_with_override,
                'stage': stage,
                'sort_key': (stage, -sig['cluster_score'], art.pk),
            })

        _MEM_CACHE['indexed_articles'] = articles_index
        return articles_index

    @classmethod
    def get_public_index_clusters(cls, is_superuser: bool = False, selected_cluster_id: str = None):
        runtime_cfg = cls.get_runtime_config()
        public_enabled = runtime_cfg['public_enabled']
        indexed_articles = cls._get_all_indexed_articles()

        clusters_map = {c['id']: [] for c in GRAVITY_CLUSTERS}

        for item in indexed_articles:
            c_id = item['cluster_id']
            if c_id == 'general_iyun' or c_id not in clusters_map:
                continue

            ed_rec = cls.get_article_editorial_record(item['pk'])
            st = ed_rec['status']
            if st == 'rejected':
                continue

            is_article_approved = (st == 'approved') or item['is_cluster_overridden'] or public_enabled or is_superuser
            if is_article_approved:
                clusters_map[c_id].append(item)

        public_clusters = []
        selected_cluster_obj = None

        for c_def in GRAVITY_CLUSTERS:
            c_id = c_def['id']
            art_list = clusters_map.get(c_id, [])
            if not art_list:
                continue
            art_list.sort(key=lambda x: x['sort_key'])
            c_payload = {
                'id': c_id,
                'title': c_def['title'],
                'icon': c_def['icon'],
                'emoji': c_def.get('emoji', '📖'),
                'description': c_def['description'],
                'count': len(art_list),
                'articles': art_list,
            }
            public_clusters.append(c_payload)
            if selected_cluster_id and selected_cluster_id == c_id:
                selected_cluster_obj = c_payload

        return {
            'clusters': public_clusters,
            'selected_cluster': selected_cluster_obj,
            'public_enabled': public_enabled,
        }

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

            dedup_title_key = (clean_b_title, clean_ch_title)
            if dedup_title_key in seen_book_chapter_titles:
                continue
            seen_book_chapter_titles.add(dedup_title_key)

            if clean_ch_title in ('הקדמה', 'מבוא', 'תוכן עניינים', 'הסכמות', 'פתח דבר'):
                continue

            book_subject_title = clean_b_title.replace('וברכותיה', '').replace('וברכותיו', '')
            sig = cls._extract_distinctive_signature(f"{book_subject_title} {clean_ch_title}", "")
            b_summary = cls.clean_text_fast(book.summary or '', 260)

            units.append({
                'unit_key': f"ch_{ch.pk}",
                'unit_type': 'chapter',
                'book_id': book.pk,
                'book_title': clean_b_title,
                'chapter_id': ch.pk,
                'chapter_title': clean_ch_title,
                'title': clean_ch_title,
                'display_label': f"{clean_b_title} – {clean_ch_title}",
                'badge': f'מתוך הספר "{clean_b_title}"',
                'preview': b_summary[:130],
                'url': f"/book/{book.pk}/?chapter={ch.pk}#chapter-{ch.pk}",
                'signature': sig,
            })

        for b_id, book in books.items():
            clean_b_title = re.sub(r'\s+', ' ', (book.title or '').strip())
            b_summary = cls.clean_text_fast(book.summary or '', 400)
            book_subject_title = clean_b_title.replace('וברכותיה', '').replace('וברכותיו', '')
            sig = cls._extract_distinctive_signature(book_subject_title, b_summary)
            units.append({
                'unit_key': f"bk_{book.pk}",
                'unit_type': 'book',
                'book_id': book.pk,
                'book_title': clean_b_title,
                'chapter_id': None,
                'chapter_title': '',
                'title': f'הספר "{clean_b_title}"',
                'display_label': f'הספר "{clean_b_title}" (ספר שלם)',
                'badge': 'ספר שלם בספרייה',
                'preview': b_summary[:140],
                'url': f"/book/{book.pk}/",
                'signature': sig,
                'has_subchapters': b_id in books_with_chapters,
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
    def _build_tool_object(cls, tool_key: str, default_search_term: str, editorial_state: str):
        if tool_key.startswith('search:'):
            custom_q = tool_key.split(':', 1)[1].strip() or default_search_term
            return {
                'tool_key': tool_key,
                'title': f'חיפוש "{custom_q}" במאגר התורני',
                'subtitle': 'סריקה בתנ"ך, משנה, תוספתא, בבלי, ירושלמי, רמב"ם ושולחן ערוך',
                'url': f'/advanced-search/?q={custom_q}',
                'icon': 'bi-search',
                'editorial_state': editorial_state,
            }
        if tool_key == 'torah_search_auto':
            return {
                'tool_key': 'torah_search_auto',
                'title': f'חיפוש "{default_search_term}" במאגר התורני',
                'subtitle': 'סריקה בתנ"ך, משנה, תוספתא, בבלי, ירושלמי, רמב"ם ושולחן ערוך',
                'url': f'/advanced-search/?q={default_search_term}',
                'icon': 'bi-search',
                'editorial_state': editorial_state,
            }
        base_tool = TOOLS_BY_KEY.get(tool_key)
        if not base_tool:
            return None
        t_copy = dict(base_tool)
        t_copy['editorial_state'] = editorial_state
        return t_copy

    @classmethod
    def get_smart_tools_for_article(cls, title: str, snippet: str, sig, ed_tools_rec: dict):
        text_combined = f"{title} {snippet}".lower()

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

        ai_candidate_keys = []
        if any(cls._count_whole_word(text_combined, w) > 0 for w in ('אמה', 'טפח', 'טפחים', 'אצבע', 'זרת', 'תחום שבת', 'גובה סוכה', 'גובה חופה')):
            ai_candidate_keys.append('calc_length')
        if any(cls._count_whole_word(text_combined, w) > 0 for w in ('רביעית', 'לוג', 'כזית', 'כביצה', 'סאה', 'ארבעים סאה', 'מקווה', 'נפח')):
            ai_candidate_keys.append('calc_volume')
        if any(cls._count_whole_word(text_combined, w) > 0 for w in ('שקל', 'סלע', 'דינר', 'פרוטה', 'פדיון הבן', 'חומש', 'מטבע', 'משקל')):
            ai_candidate_keys.append('calc_weight')
        if any(cls._count_whole_word(text_combined, w) > 0 for w in ('בגמרא', 'בבלי', 'ירושלמי', 'איתמר', 'תא שמע', 'מאי טעמא', 'נפקא מינה')):
            ai_candidate_keys.append('aramaic_translator')

        ai_candidate_keys.append('torah_search_auto')

        rejected_keys = set(ed_tools_rec.get('rejected', []))
        final_tools = []
        seen_keys = set()

        for m_key in ed_tools_rec.get('manual_added', []):
            if m_key not in seen_keys and m_key not in rejected_keys:
                t_obj = cls._build_tool_object(m_key, search_term, 'manual')
                if t_obj:
                    final_tools.append(t_obj)
                    seen_keys.add(m_key)

        for a_key in ed_tools_rec.get('approved', []):
            if a_key not in seen_keys and a_key not in rejected_keys:
                t_obj = cls._build_tool_object(a_key, search_term, 'approved')
                if t_obj:
                    final_tools.append(t_obj)
                    seen_keys.add(a_key)

        for ai_key in ai_candidate_keys:
            if ai_key not in seen_keys and ai_key not in rejected_keys:
                t_obj = cls._build_tool_object(ai_key, search_term, 'ai_suggested')
                if t_obj:
                    final_tools.append(t_obj)
                    seen_keys.add(ai_key)

        rejected_tools_objs = []
        for r_key in rejected_keys:
            r_obj = cls._build_tool_object(r_key, search_term, 'rejected')
            if r_obj:
                rejected_tools_objs.append(r_obj)

        return final_tools, rejected_tools_objs

    @classmethod
    def get_learning_context(cls, article, all_articles=None, min_score_override=None):
        runtime_cfg = cls.get_runtime_config()
        active_min_score = int(min_score_override) if min_score_override is not None else runtime_cfg['min_connection_score']
        public_enabled = runtime_cfg['public_enabled']

        mem_key = f"ctx_{ENGINE_VERSION}_{article.pk}_{active_min_score}_{public_enabled}"
        if mem_key in _MEM_CACHE:
            return _MEM_CACHE[mem_key]

        ed_rec = cls.get_article_editorial_record(article.pk)
        connections_status = ed_rec['status']

        indexed_articles = cls._get_all_indexed_articles()
        articles_by_pk = {a['pk']: a for a in indexed_articles}
        curr_entry = articles_by_pk.get(article.pk)

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
                'ai_cluster_id': sig['cluster']['id'],
                'ai_cluster_title': sig['cluster']['title'],
                'is_cluster_overridden': False,
                'editor_cluster_title': None,
                'icon': sig['cluster']['icon'],
                'description': sig['cluster']['description'],
                'score': sig['cluster_score'],
                'breakdown': sig['breakdown'],
                'signature': sig,
                'stage': 2,
                'sort_key': (2, -sig['cluster_score'], article.pk),
            }

        curr_sig = curr_entry['signature']
        path_articles = [
            a for a in indexed_articles
            if a['cluster_id'] == curr_entry['cluster_id']
            and cls.get_article_editorial_record(a['pk'])['status'] != 'rejected'
        ]
        path_articles.sort(key=lambda x: x['sort_key'])

        total_in_path = max(1, len(path_articles))
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

        # 1. Related Articles (No hard limit of 4 - keeps all suggestions!)
        art_ed = ed_rec['articles']
        rejected_art_ids = set(art_ed['rejected'])
        final_related_articles = []
        seen_art_ids = {article.pk}

        for m_id in art_ed['manual_added']:
            if m_id not in seen_art_ids and m_id in articles_by_pk and m_id not in rejected_art_ids:
                cand = articles_by_pk[m_id]
                final_related_articles.append({
                    'article': {'pk': cand['pk'], 'title': cand['title'], 'slug': cand['slug']},
                    'score': 100,
                    'reasons': ['קשר ידני'],
                    'editorial_state': 'manual',
                })
                seen_art_ids.add(m_id)

        for a_id in art_ed['approved']:
            if a_id not in seen_art_ids and a_id in articles_by_pk and a_id not in rejected_art_ids:
                cand = articles_by_pk[a_id]
                sim_score, reasons = cls._calculate_pair_similarity(
                    curr_sig, cand['signature'], curr_entry['parasha'], cand['parasha']
                )
                final_related_articles.append({
                    'article': {'pk': cand['pk'], 'title': cand['title'], 'slug': cand['slug']},
                    'score': sim_score or 50,
                    'reasons': reasons or ['מאושר'],
                    'editorial_state': 'approved',
                })
                seen_art_ids.add(a_id)

        ai_scored_articles = []
        extra_candidate_articles = []
        for cand in indexed_articles:
            if cand['pk'] in seen_art_ids or cand['pk'] in rejected_art_ids:
                continue
            sim_score, reasons = cls._calculate_pair_similarity(
                curr_sig, cand['signature'],
                curr_entry['parasha'], cand['parasha'],
                is_book_target=False
            )
            item_obj = {
                'article': {'pk': cand['pk'], 'title': cand['title'], 'slug': cand['slug']},
                'score': sim_score,
                'reasons': reasons,
                'editorial_state': 'ai_suggested',
            }
            if sim_score >= active_min_score:
                ai_scored_articles.append(item_obj)
            elif sim_score >= 8:
                extra_candidate_articles.append(item_obj)

        ai_scored_articles.sort(key=lambda x: (-x['score'], -x['article']['pk']))
        extra_candidate_articles.sort(key=lambda x: (-x['score'], -x['article']['pk']))

        final_related_articles.extend(ai_scored_articles)

        rejected_article_objs = [
            {'pk': r_id, 'title': articles_by_pk[r_id]['title']}
            for r_id in art_ed['rejected'] if r_id in articles_by_pk
        ]

        # 2. Book Chapters & Books (All matching chapters preserved)
        book_ed = ed_rec['books']
        rejected_book_keys = set(book_ed['rejected'])
        all_book_units = cls._get_indexed_book_units()
        book_units_by_key = {u['unit_key']: u for u in all_book_units}

        final_book_units = []
        seen_book_keys = set()

        for m_key in book_ed['manual_added']:
            if m_key not in seen_book_keys and m_key in book_units_by_key and m_key not in rejected_book_keys:
                u_copy = {k: v for k, v in book_units_by_key[m_key].items() if k != 'signature'}
                u_copy['match_score'] = 100
                u_copy['reasons'] = ['קשר ידני']
                u_copy['editorial_state'] = 'manual'
                final_book_units.append(u_copy)
                seen_book_keys.add(m_key)

        for a_key in book_ed['approved']:
            if a_key not in seen_book_keys and a_key in book_units_by_key and a_key not in rejected_book_keys:
                u_orig = book_units_by_key[a_key]
                sim_score, reasons = cls._calculate_pair_similarity(curr_sig, u_orig['signature'], is_book_target=True)
                u_copy = {k: v for k, v in u_orig.items() if k != 'signature'}
                u_copy['match_score'] = sim_score or 50
                u_copy['reasons'] = reasons or ['מאושר']
                u_copy['editorial_state'] = 'approved'
                final_book_units.append(u_copy)
                seen_book_keys.add(a_key)

        raw_scored_books = []
        extra_candidate_books = []
        for b_unit in all_book_units:
            u_key = b_unit['unit_key']
            if u_key in seen_book_keys or u_key in rejected_book_keys:
                continue
            if b_unit.get('has_subchapters'):
                continue
            sim_score, reasons = cls._calculate_pair_similarity(
                curr_sig, b_unit['signature'], is_book_target=True
            )
            unit_copy = {k: v for k, v in b_unit.items() if k != 'signature'}
            unit_copy['match_score'] = sim_score
            unit_copy['reasons'] = reasons
            unit_copy['editorial_state'] = 'ai_suggested'
            if sim_score >= active_min_score:
                raw_scored_books.append(unit_copy)
            elif sim_score >= 10:
                extra_candidate_books.append(unit_copy)

        raw_scored_books.sort(key=lambda x: -x['match_score'])
        extra_candidate_books.sort(key=lambda x: -x['match_score'])
        final_book_units.extend(raw_scored_books)

        rejected_book_objs = [
            {'unit_key': r_key, 'label': book_units_by_key[r_key]['display_label']}
            for r_key in book_ed['rejected'] if r_key in book_units_by_key
        ]

        # 3. Q&As
        qa_ed = ed_rec['qas']
        rejected_qa_ids = set(qa_ed['rejected'])
        all_qa_units = cls._get_indexed_qa_units()
        qas_by_id = {q['qa_id']: q for q in all_qa_units}

        final_qas = []
        seen_qa_ids = set()

        for m_qid in qa_ed['manual_added']:
            if m_qid not in seen_qa_ids and m_qid in qas_by_id and m_qid not in rejected_qa_ids:
                q_copy = {k: v for k, v in qas_by_id[m_qid].items() if k != 'signature'}
                q_copy['match_score'] = 100
                q_copy['reasons'] = ['קשר ידני']
                q_copy['editorial_state'] = 'manual'
                final_qas.append(q_copy)
                seen_qa_ids.add(m_qid)

        for a_qid in qa_ed['approved']:
            if a_qid not in seen_qa_ids and a_qid in qas_by_id and a_qid not in rejected_qa_ids:
                q_orig = qas_by_id[a_qid]
                sim_score, reasons = cls._calculate_pair_similarity(curr_sig, q_orig['signature'])
                q_copy = {k: v for k, v in q_orig.items() if k != 'signature'}
                q_copy['match_score'] = sim_score or 50
                q_copy['reasons'] = reasons or ['מאושר']
                q_copy['editorial_state'] = 'approved'
                final_qas.append(q_copy)
                seen_qa_ids.add(a_qid)

        ai_scored_qas = []
        for q_unit in all_qa_units:
            qid = q_unit['qa_id']
            if qid in seen_qa_ids or qid in rejected_qa_ids:
                continue
            sim_score, reasons = cls._calculate_pair_similarity(curr_sig, q_unit['signature'])
            if sim_score >= active_min_score:
                q_copy = {k: v for k, v in q_unit.items() if k != 'signature'}
                q_copy['match_score'] = sim_score
                q_copy['reasons'] = reasons
                q_copy['editorial_state'] = 'ai_suggested'
                ai_scored_qas.append(q_copy)

        ai_scored_qas.sort(key=lambda x: -x['match_score'])
        final_qas.extend(ai_scored_qas)

        rejected_qa_objs = [
            {'qa_id': r_qid, 'question': qas_by_id[r_qid]['question']}
            for r_qid in qa_ed['rejected'] if r_qid in qas_by_id
        ]

        # 4. Smart Tools (with full editorial control)
        smart_tools, rejected_tools_objs = cls.get_smart_tools_for_article(
            curr_entry['title'], curr_entry['snippet'], curr_sig, ed_rec['tools']
        )

        has_any_content = bool(final_related_articles or final_book_units or final_qas)
        is_orphan_or_weak = (
            connections_status == 'pending' and (
                curr_entry['cluster_id'] == 'general_iyun' or
                not has_any_content
            )
        )

        is_visible_to_public = (connections_status != 'rejected') and (
            connections_status == 'approved' or curr_entry['is_cluster_overridden'] or public_enabled
        )

        payload = {
            'public_enabled': public_enabled,
            'is_visible_to_public': is_visible_to_public,
            'connections_status': connections_status,
            'min_connection_score': active_min_score,
            'cluster': {
                'cluster_id': curr_entry['cluster_id'],
                'cluster_title': curr_entry['cluster_title'],
                'ai_cluster_id': curr_entry['ai_cluster_id'],
                'ai_cluster_title': curr_entry['ai_cluster_title'],
                'is_cluster_overridden': curr_entry['is_cluster_overridden'],
                'editor_cluster_title': curr_entry['editor_cluster_title'],
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
            'related_articles': final_related_articles,
            'extra_candidate_articles': extra_candidate_articles[:10],
            'rejected_articles': rejected_article_objs,
            'book_units': final_book_units,
            'extra_candidate_books': extra_candidate_books[:10],
            'rejected_books': rejected_book_objs,
            'related_qas': final_qas,
            'rejected_qas': rejected_qa_objs,
            'smart_tools': smart_tools,
            'rejected_tools': rejected_tools_objs,
            'has_strong_matches': has_any_content,
            'is_orphan_or_weak': is_orphan_or_weak,
        }
        _MEM_CACHE[mem_key] = payload
        return payload

    @classmethod
    def generate_admin_audit_report(cls, min_score_override=None):
        runtime_cfg = cls.get_runtime_config()
        active_min_score = int(min_score_override) if min_score_override is not None else runtime_cfg['min_connection_score']

        indexed_articles = sorted(cls._get_all_indexed_articles(), key=lambda x: x['title'])
        all_book_units = cls._get_indexed_book_units()
        all_qa_units = cls._get_indexed_qa_units()

        rows = []
        weak_articles = []
        approved_count = 0
        rejected_count = 0
        pending_count = 0

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
            st = ctx['connections_status']
            if st == 'approved':
                approved_count += 1
            elif st == 'rejected':
                rejected_count += 1
            else:
                pending_count += 1

            has_ai_suggestions = (
                any(x.get('editorial_state') == 'ai_suggested' for x in ctx['related_articles']) or
                any(x.get('editorial_state') == 'ai_suggested' for x in ctx['book_units']) or
                any(x.get('editorial_state') == 'ai_suggested' for x in ctx['related_qas'])
            )

            row = {
                'article': light_art,
                'connections_status': st,
                'has_ai_suggestions': has_ai_suggestions,
                'cluster_id': ctx['cluster']['cluster_id'],
                'cluster_title': ctx['cluster']['cluster_title'],
                'ai_cluster_id': ctx['cluster']['ai_cluster_id'],
                'ai_cluster_title': ctx['cluster']['ai_cluster_title'],
                'is_cluster_overridden': ctx['cluster']['is_cluster_overridden'],
                'editor_cluster_title': ctx['cluster']['editor_cluster_title'],
                'cluster_score': ctx['cluster']['score'],
                'breakdown': ctx['cluster']['breakdown'],
                'related_articles': ctx['related_articles'],
                'extra_candidate_articles': ctx['extra_candidate_articles'],
                'rejected_articles': ctx['rejected_articles'],
                'book_units': ctx['book_units'],
                'extra_candidate_books': ctx['extra_candidate_books'],
                'rejected_books': ctx['rejected_books'],
                'related_qas': ctx['related_qas'],
                'rejected_qas': ctx['rejected_qas'],
                'smart_tools': ctx['smart_tools'],
                'rejected_tools': ctx['rejected_tools'],
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
            'approved_count': approved_count,
            'rejected_count': rejected_count,
            'pending_count': pending_count,
            'weak_count': len(weak_articles),
            'weak_articles': weak_articles,
            'rows': rows,
            'cluster_summary': cluster_summary,
            'all_clusters': ALL_CLUSTERS_LIST,
            'all_articles_choices': [{'pk': a['pk'], 'title': a['title']} for a in indexed_articles],
            'all_books_choices': [{'unit_key': b['unit_key'], 'label': b['display_label']} for b in all_book_units],
            'all_qas_choices': [{'qa_id': q['qa_id'], 'question': q['question']} for q in all_qa_units],
            'all_tools_choices': TOOLS_CATALOG,
            'active_min_score': active_min_score,
            'saved_min_score': runtime_cfg['min_connection_score'],
            'public_enabled': runtime_cfg['public_enabled'],
        }