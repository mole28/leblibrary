from django.db import models
from django.utils import timezone
from django.utils.text import slugify
from django.urls import reverse

import re
from html import unescape
from bs4 import BeautifulSoup
from django.utils.html import strip_tags
from django_ckeditor_5.fields import CKEditor5Field

from pyluach import dates
from django.contrib.auth.models import User
from datetime import timedelta

try:
    import mammoth
except ImportError:
    mammoth = None

_EXCERPT_BLOCK_TAG_RE = re.compile(
    r'</?(?:p|div|br|h[1-6]|li|ul|ol|tr|td|th|blockquote|section|article|header|footer|hr)[^>]*>',
    re.IGNORECASE,
)

def build_clean_excerpt(html_content, max_words=25):
    if not html_content:
        return ""
    text = re.sub(r'<style[^>]*>.*?</style>', ' ', str(html_content), flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r'<script[^>]*>.*?</script>', ' ', text, flags=re.IGNORECASE | re.DOTALL)
    text = _EXCERPT_BLOCK_TAG_RE.sub(' ', text)
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

def normalize_article_footnotes_html(html_content):
    if not html_content:
        return html_content
    if '_ftn' not in html_content and '_edn' not in html_content and 'footnote' not in html_content:
        return html_content

    soup = BeautifulSoup(html_content, 'html.parser')

    ftn_ref_re = re.compile(r'^_?(?:ftnref|ednref)(\d+)$', re.IGNORECASE)
    ftn_def_re = re.compile(r'^_?(?:ftn|edn)(\d+)$', re.IGNORECASE)

    tokens = []
    for a in soup.find_all('a'):
        name_attr = (a.get('name') or '').strip()
        id_attr = (a.get('id') or '').strip()
        href_attr = (a.get('href') or '').strip()

        m_ref = ftn_ref_re.match(name_attr) or ftn_ref_re.match(id_attr)
        m_def = ftn_def_re.match(name_attr) or ftn_def_re.match(id_attr)

        if not m_ref and not m_def and href_attr.startswith('#'):
            target_part = href_attr[1:]
            if ftn_def_re.match(target_part):
                m_ref = ftn_def_re.match(target_part)
            elif ftn_ref_re.match(target_part):
                m_def = ftn_ref_re.match(target_part)

        if m_ref:
            tokens.append(('ref', int(m_ref.group(1)), a))
        elif m_def:
            tokens.append(('def', int(m_def.group(1)), a))

    if tokens:
        open_ref_runs = []
        current_ref_run = None
        current_def_run = None
        next_group_id = 1

        def finalize_def_run(def_run):
            nonlocal next_group_id
            if not def_run or not open_ref_runs:
                return
            def_nums = {n for n, _ in def_run}

            chosen_idx = None
            for idx in range(len(open_ref_runs) - 1, -1, -1):
                if open_ref_runs[idx]['nums'] == def_nums:
                    chosen_idx = idx
                    break
            if chosen_idx is None:
                for idx in range(len(open_ref_runs) - 1, -1, -1):
                    r_nums = open_ref_runs[idx]['nums']
                    if def_nums.issubset(r_nums) or r_nums.issubset(def_nums):
                        chosen_idx = idx
                        break
            if chosen_idx is None:
                best_overlap = 0
                for idx in range(len(open_ref_runs) - 1, -1, -1):
                    ov = len(open_ref_runs[idx]['nums'] & def_nums)
                    if ov > best_overlap:
                        best_overlap = ov
                        chosen_idx = idx
            if chosen_idx is None:
                return

            ref_run = open_ref_runs.pop(chosen_idx)
            gid = next_group_id
            next_group_id += 1

            seen_ref_nums = {}
            for num, a_tag in ref_run['items']:
                count = seen_ref_nums.get(num, 0) + 1
                seen_ref_nums[num] = count
                ref_id = f"fn-ref-{gid}-{num}" if count == 1 else f"fn-ref-{gid}-{num}-{count}"
                a_tag['id'] = ref_id
                a_tag['href'] = f"#fn-note-{gid}-{num}"
                a_tag['data-fn-group'] = str(gid)
                a_tag['data-fn-num'] = str(num)
                a_tag['aria-label'] = f"הערת שוליים {num}"
                if a_tag.has_attr('name'):
                    del a_tag['name']
                classes = [c for c in (a_tag.get('class') or []) if c not in ('footnote-ref', 'footnote-backref')]
                classes.append('footnote-ref')
                a_tag['class'] = classes

            seen_def_nums = set()
            for num, a_tag in def_run:
                if num in seen_def_nums:
                    continue
                seen_def_nums.add(num)
                a_tag['id'] = f"fn-note-{gid}-{num}"
                a_tag['href'] = f"#fn-ref-{gid}-{num}"
                a_tag['data-fn-group'] = str(gid)
                a_tag['data-fn-num'] = str(num)
                a_tag['title'] = "חזרה למקום הקריאה בטקסט"
                a_tag['aria-label'] = f"חזרה להפניה {num} בטקסט"
                if a_tag.has_attr('name'):
                    del a_tag['name']
                classes = [c for c in (a_tag.get('class') or []) if c not in ('footnote-ref', 'footnote-backref')]
                classes.append('footnote-backref')
                a_tag['class'] = classes
                parent_el = a_tag.find_parent(['div', 'p', 'li'])
                if parent_el and parent_el.has_attr('id') and ftn_def_re.match(parent_el['id']):
                    del parent_el['id']

        for kind, num, a_tag in tokens:
            if kind == 'ref':
                if current_def_run is not None:
                    finalize_def_run(current_def_run)
                    current_def_run = None
                if current_ref_run is None or (num == 1 and len(current_ref_run['items']) > 0):
                    current_ref_run = {'nums': set(), 'items': []}
                    open_ref_runs.append(current_ref_run)
                current_ref_run['nums'].add(num)
                current_ref_run['items'].append((num, a_tag))
            else:
                current_ref_run = None
                if current_def_run is None:
                    current_def_run = [(num, a_tag)]
                else:
                    def_nums_so_far = {n for n, _ in current_def_run}
                    if num in def_nums_so_far or (num == 1 and any(n > 1 for n in def_nums_so_far)):
                        finalize_def_run(current_def_run)
                        current_def_run = [(num, a_tag)]
                    else:
                        current_def_run.append((num, a_tag))

        if current_def_run is not None:
            finalize_def_run(current_def_run)

    for a in soup.find_all('a'):
        classes = a.get('class')
        if classes and len(classes) != len(set(classes)):
            a['class'] = list(dict.fromkeys(classes))

    fn_target_divs = {}
    for el in soup.find_all(id=re.compile(r'^footnote-\d+$')):
        fn_target_divs[el['id']] = el

    if fn_target_divs:
        seen_fn_refs = {}
        for a in soup.find_all('a', href=re.compile(r'^#footnote-\d+$')):
            target_id = a['href'][1:]
            if target_id in fn_target_divs:
                num = target_id.replace('footnote-', '')
                if not a.get('id'):
                    cnt = seen_fn_refs.get(num, 0) + 1
                    seen_fn_refs[num] = cnt
                    a['id'] = f"footnote-ref-{num}" if cnt == 1 else f"footnote-ref-{num}-{cnt}"
                classes = list(dict.fromkeys([c for c in (a.get('class') or []) if c != 'footnote-backref'] + ['footnote-ref']))
                a['class'] = classes
                target_el = fn_target_divs[target_id]
                if not target_el.find('a', class_='footnote-backref'):
                    back_a = soup.new_tag(
                        'a',
                        href=f"#{a['id']}",
                        attrs={
                            'class': 'footnote-backref ms-2',
                            'title': 'חזרה למקום הקריאה בטקסט',
                            'aria-label': f'חזרה להפניה {num} בטקסט',
                        },
                    )
                    back_a.string = '↩'
                    target_el.append(back_a)

    return str(soup)

def process_mammoth_html(raw_html):
    if not raw_html: return ""
    soup = BeautifulSoup(raw_html, 'html.parser')

    for ref in soup.find_all('a', id=re.compile(r'^footnote-ref-')):
        clean_num = ref.get_text(strip=True).replace('[', '').replace(']', '')
        ref.string = f"[{clean_num}]"
        ref['class'] = ref.get('class', []) + ['footnote-ref']
        if ref.parent and ref.parent.name != 'sup':
            ref.wrap(soup.new_tag('sup'))

    footnotes_dict = {}
    for li in soup.find_all('li', id=re.compile(r'^footnote-')):
        fn_id = li['id']
        for back_link in li.find_all('a', href=re.compile(r'^#footnote-ref-')):
            parent = back_link.parent
            back_link.decompose()
            if parent and parent.name == 'sup' and not parent.get_text(strip=True):
                parent.decompose()
        
        for p in li.find_all('p'):
            p.unwrap()
            
        footnotes_dict[fn_id] = li
        li.extract()
        
    for ol in soup.find_all('ol'):
        if not ol.get_text(strip=True):
            ol.extract()

    if footnotes_dict:
        hr = soup.new_tag('hr', style='border: 0; border-top: 5px solid #2c3e50; margin: 60px 0 40px 0; opacity: 1;')
        h2 = soup.new_tag('h2', style='text-align: center; color: #d4af37; margin-bottom: 30px; font-weight: bold;')
        h2.string = "הערות שוליים"
        container = soup.new_tag('div', class_='custom-footnotes-container', style='font-size: 1.1em; line-height: 1.8; margin-right: 10px;')

        for fn_id, li_tag in footnotes_dict.items():
            num = fn_id.replace('footnote-', '')
            div = soup.new_tag('div', style='margin-bottom: 15px; display: flex; align-items: flex-start;')
            div['id'] = fn_id
            
            num_span = soup.new_tag('span', style='font-weight:bold; color:#d4af37; min-width: 35px; flex-shrink: 0;')
            num_span.string = f"{num}."
            
            content_span = soup.new_tag('span', style='flex-grow: 1;')
            for child in list(li_tag.contents):
                content_span.append(child)
            
            div.append(num_span)
            div.append(content_span)
            container.append(div)

        soup.append(hr)
        soup.append(h2)
        soup.append(container)

    for p in soup.find_all('p'):
        if not p.get_text(strip=True) and not p.find(['img', 'iframe']):
            p.decompose()

    return str(soup)

def clean_word_html(html_content):
    if not html_content: return html_content
    html_content = html_content.replace('^', '').replace('↑', '').replace('ˆ', '')
    soup = BeautifulSoup(html_content, 'html.parser')

    for el in soup.find_all('div', class_='custom-footnotes-container'): el.decompose()
    for el in soup.find_all('h2', string="הערות שוליים"):
        prev_hr = el.find_previous_sibling('hr')
        if prev_hr: prev_hr.decompose()
        el.decompose()

    paragraphs = soup.find_all(['p', 'div'])
    footnote_start_idx = -1
    for i, p in enumerate(paragraphs):
        text = p.get_text(strip=True)
        if re.match(r'^[\.\[\]\(\)]*\s*1\s*[\.\[\]\(\)]*$', text):
            found_2 = False
            for j in range(i+1, min(i+6, len(paragraphs))):
                if re.match(r'^[\.\[\]\(\)]*\s*2\s*[\.\[\]\(\)]*$', paragraphs[j].get_text(strip=True)):
                    found_2 = True
                    break
            if found_2 or i >= len(paragraphs) - 5:
                footnote_start_idx = i
                break

    built_footnotes = []
    if footnote_start_idx != -1:
        current_fn = None
        for p in paragraphs[footnote_start_idx:]:
            text = p.get_text(strip=True)
            if not text:
                p.decompose()
                continue
            
            match_standalone = re.match(r'^[\.\[\]\(\)]*\s*(\d+)\s*[\.\[\]\(\)]*$', text)
            if match_standalone:
                num = match_standalone.group(1)
                current_fn = {'num': num, 'elements': []}
                built_footnotes.append(current_fn)
                p.decompose()
                continue
                
            match_inline = re.match(r'^[\.\[\]\(\)]*\s*(\d+)[\.\[\]\(\)\-\:]*\s+(.*)$', text)
            if match_inline:
                num = match_inline.group(1)
                expected_num = str(len(built_footnotes) + 1)
                if num == expected_num or num == str(len(built_footnotes)):
                    current_fn = {'num': num, 'elements': []}
                    built_footnotes.append(current_fn)
                    for text_node in p.find_all(string=True):
                        if num in text_node:
                            new_val = re.sub(r'^[\s\.\[\]\(\)]*' + num + r'[\s\.\[\]\(\)\-\:]*', '', text_node, count=1)
                            text_node.replace_with(new_val)
                            break
                    current_fn['elements'].append(p.extract())
                    continue
                    
            if current_fn:
                current_fn['elements'].append(p.extract())

    word_anchor_re = re.compile(r'^(?:_?(?:ftn|edn)(?:ref)?|fn-(?:ref|note)-)', re.IGNORECASE)
    for a in soup.find_all('a'):
        href = a.get('href', '')
        a_name = a.get('name', '')
        a_id = a.get('id', '')
        if word_anchor_re.match(a_name) or word_anchor_re.match(a_id) or (href.startswith('#') and word_anchor_re.match(href[1:])):
            continue
        if href.startswith('#'):
            text = a.get_text(strip=True)
            clean_num = re.sub(r'\D', '', text)
            if clean_num and clean_num.isdigit():
                a.string = f"[{clean_num}]"
                a['href'] = f"#footnote-{clean_num}"
                a['class'] = list(dict.fromkeys((a.get('class') or []) + ['footnote-ref']))
                if a.parent and a.parent.name != 'sup':
                    a.wrap(soup.new_tag('sup'))
                    
    for sup in soup.find_all('sup'):
        if not sup.find('a'):
            text = sup.get_text(strip=True)
            clean_num = re.sub(r'\D', '', text)
            if clean_num and clean_num.isdigit():
                a = soup.new_tag('a', href=f"#footnote-{clean_num}", class_="footnote-ref")
                a.string = f"[{clean_num}]"
                sup.string = ''
                sup.append(a)

    if built_footnotes:
        max_fn = len(built_footnotes)
        for text_node in soup.find_all(string=re.compile(r'\[\d+\]')):
            if text_node.find_parent(['sup', 'a']): continue
            new_html = re.sub(
                r'\[(\d+)\]', 
                lambda m: f'<sup><a href="#footnote-{m.group(1)}" class="footnote-ref">[{m.group(1)}]</a></sup>' if int(m.group(1)) <= max_fn else m.group(0), 
                text_node
            )
            if new_html != text_node:
                new_soup = BeautifulSoup(new_html, 'html.parser')
                text_node.replace_with(new_soup)

    if built_footnotes:
        hr_new = soup.new_tag('hr', style='border: 0; border-top: 5px solid #2c3e50; margin: 60px 0 40px 0; opacity: 1;')
        h2 = soup.new_tag('h2', style='text-align: center; color: #d4af37; margin-bottom: 30px; font-weight: bold;')
        h2.string = "הערות שוליים"
        container = soup.new_tag('div', class_='custom-footnotes-container', style='font-size: 1.1em; line-height: 1.8; margin-right: 10px;')

        for fn in built_footnotes:
            div = soup.new_tag('div', style='margin-bottom: 15px; display: flex; align-items: flex-start;')
            div['id'] = f"footnote-{fn['num']}"
            num_span = soup.new_tag('span', style='font-weight:bold; color:#d4af37; min-width: 35px; flex-shrink: 0;')
            num_span.string = f"{fn['num']}."
            content_span = soup.new_tag('span', style='flex-grow: 1;')
            for el in fn['elements']:
                if el.name == 'p': el.unwrap()
                content_span.append(el)
                content_span.append(soup.new_string(" ")) 
            div.append(num_span)
            div.append(content_span)
            container.append(div)

        soup.append(hr_new)
        soup.append(h2)
        soup.append(container)

    for p in soup.find_all('p'):
        if not p.get_text(strip=True) and not p.find(['img', 'iframe']): p.decompose()

    return normalize_article_footnotes_html(str(soup))

PARASHA_CHOICES = [
    ('general', 'מאמר כללי (לא קשור לפרשה)'),
    ('ספר בראשית', (
        ('בראשית', 'בראשית'), ('נח', 'נח'), ('לך לך', 'לך לך'), ('וירא', 'וירא'),
        ('חיי שרה', 'חיי שרה'), ('תולדות', 'תולדות'), ('ויצא', 'ויצא'), ('וישלח', 'וישלח'),
        ('וישב', 'וישב'), ('מקץ', 'מקץ'), ('ויגש', 'ויגש'), ('ויחי', 'ויחי'),
    )),
    ('ספר שמות', (
        ('שמות', 'שמות'), ('וארא', 'וארא'), ('בא', 'בא'), ('בשלח', 'בשלח'),
        ('יתרו', 'יתרו'), ('משפטים', 'משפטים'), ('תרומה', 'תרומה'), ('תצוה', 'תצוה'),
        ('כי תשא', 'כי תשא'), ('ויקהל', 'ויקהל'), ('פקודי', 'פקודי'),
    )),
    ('ספר ויקרא', (
        ('ויקרא', 'ויקרא'), ('צו', 'צו'), ('שמיני', 'שמיני'), ('תזריע', 'תזריע'),
        ('מצורע', 'מצורע'), ('אחרי מות', 'אחרי מות'), ('קדושים', 'קדושים'),
        ('אמור', 'אמור'), ('בהר', 'בהר'), ('בחוקתי', 'בחוקתי'),
    )),
    ('ספר במדבר', (
        ('במדבר', 'במדבר'), ('נשא', 'נשא'), ('בהעלותך', 'בהעלותך'), ('שלח לך', 'שלח לך'),
        ('קרח', 'קרח'), ('חקת', 'חקת'), ('בלק', 'בלק'), ('פינחס', 'פינחס'),
        ('מטות', 'מטות'), ('מסעי', 'מסעי'),
    )),
    ('ספר דברים', (
        ('דברים', 'דברים'), ('ואתחנן', 'ואתחנן'), ('עקב', 'עקב'), ('ראה', 'ראה'),
        ('שופטים', 'שופטים'), ('כי תצא', 'כי תצא'), ('כי תבוא', 'כי תבוא'),
        ('ניצבים', 'ניצבים'), ('וילך', 'וילך'), ('האזינו', 'האזינו'), ('וזאת הברכה', 'וזאת הברכה'),
    )),
]

class Article(models.Model):
    title = models.CharField(max_length=200, verbose_name="כותרת המאמר")
    slug = models.SlugField(max_length=255, unique=True, allow_unicode=True, verbose_name="קישור (Slug)", blank=True, null=True)
    parasha = models.CharField(max_length=500, default=',general,', verbose_name="שיוך לפרשות שבוע", blank=True)
    word_file = models.FileField(upload_to='word_imports/', blank=True, null=True, verbose_name="ייבוא אוטומטי מוורד (מומלץ למאמרים עם הערות!)")
    content = CKEditor5Field(config_name='extends', verbose_name="תוכן המאמר", blank=True, null=True) 
    hebrew_date = models.CharField(max_length=100, verbose_name="תאריך עברי", blank=True)
    created_at = models.DateTimeField(default=timezone.now, verbose_name="תאריך יצירה")
    is_published = models.BooleanField(default=True, verbose_name="מפורסם")

    @property
    def hebrew_date_auto(self):
        if self.created_at:
            try:
                local_dt = timezone.localtime(self.created_at) if timezone.is_aware(self.created_at) else self.created_at
                heb_date = dates.HebrewDate.from_pydate(local_dt.date())
                return heb_date.hebrew_date_string()
            except Exception:
                return ""
        return ""

    @property
    def display_hebrew_date(self):
        manual = (self.hebrew_date or "").strip()
        if manual:
            return manual
        return self.hebrew_date_auto

    @property
    def display_gregorian_date(self):
        if self.created_at:
            try:
                local_dt = timezone.localtime(self.created_at) if timezone.is_aware(self.created_at) else self.created_at
                return local_dt.strftime('%d.%m.%Y')
            except Exception:
                return ""
        return ""

    @property
    def display_full_date(self):
        heb = self.display_hebrew_date
        greg = self.display_gregorian_date
        if heb and greg:
            return f"{heb} ({greg})"
        return heb or greg

    @property
    def clean_excerpt(self):
        return build_clean_excerpt(self.content, max_words=25)

    @property
    def short_excerpt(self):
        return build_clean_excerpt(self.content, max_words=20)

    @property
    def meta_excerpt(self):
        return build_clean_excerpt(self.content, max_words=30)

    @property
    def is_new(self):
        if not self.created_at: return False
        return self.created_at >= timezone.now() - timedelta(days=7)

    def __str__(self): return self.title

    def get_absolute_url(self):
        return reverse('articles:detail', kwargs={'slug': self.slug})

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title, allow_unicode=True)
            if not self.slug:
                self.slug = f"article-{timezone.now().strftime('%Y%m%d%H%M%S')}"
            
            original_slug = self.slug
            counter = 1
            while Article.objects.filter(slug=self.slug).exclude(pk=self.pk).exists():
                self.slug = f"{original_slug}-{counter}"
                counter += 1

        if self.word_file and mammoth:
            try:
                self.word_file.open('rb')
                result = mammoth.convert_to_html(self.word_file.file)
                self.content = process_mammoth_html(result.value)
                self.word_file.close()
                self.word_file = None 
            except Exception as e:
                print(f"Error parsing word: {e}")
        else:
            self.content = clean_word_html(self.content)

        if not (self.hebrew_date or "").strip() and self.created_at:
            self.hebrew_date = self.hebrew_date_auto

        super().save(*args, **kwargs)

class Book(models.Model):
    title = models.CharField(max_length=200, verbose_name="שם הספר")
    author = models.CharField(max_length=100, verbose_name="מחבר")
    cover_image = models.ImageField(upload_to='books/covers/', blank=True, null=True, verbose_name="תמונת כריכה")
    pdf_file = models.FileField(upload_to='books/pdfs/', blank=True, null=True, verbose_name="קובץ PDF להורדה")
    summary = CKEditor5Field(config_name='extends', verbose_name="תקציר הספר", blank=True, null=True)
    price = models.DecimalField(max_digits=6, decimal_places=2, default=0.00, verbose_name="מחיר הספר")
    is_for_sale = models.BooleanField(default=False, verbose_name="זמין לרכישה")
    stock = models.PositiveIntegerField(default=0, verbose_name="מלאי זמין")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="תאריך הוספה")
    order = models.PositiveIntegerField(default=0, verbose_name="סדר תצוגה (1 יופיע ראשון)")
    
    @property
    def is_new(self):
        if not self.created_at: return False
        return self.created_at >= timezone.now() - timedelta(days=7)
    
    class Meta:
        ordering = ['order', 'title']

    def __str__(self): return self.title

class Chapter(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='chapters', verbose_name="ספר")
    title = models.CharField(max_length=200, verbose_name="כותרת (למשל: סימן א)")
    order = models.PositiveIntegerField(verbose_name="סדר")

    def __str__(self): return f"{self.book.title} | {self.title}"

class Section(models.Model):
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name='sections', verbose_name="פרק")
    title = models.CharField(max_length=200, verbose_name="כותרת הסעיף")
    word_file = models.FileField(upload_to='word_imports/', blank=True, null=True, verbose_name="ייבוא אוטומטי מוורד (מומלץ למאמרים עם הערות!)")
    content = CKEditor5Field(config_name='extends', verbose_name="תוכן", blank=True, null=True)
    order = models.PositiveIntegerField(verbose_name="סדר")

    def __str__(self): return f"{self.chapter.title} | {self.title}"

    def save(self, *args, **kwargs):
        if self.word_file and mammoth:
            try:
                self.word_file.open('rb')
                result = mammoth.convert_to_html(self.word_file.file)
                self.content = process_mammoth_html(result.value)
                self.word_file.close()
                self.word_file = None
            except Exception as e:
                print(f"Error parsing word: {e}")
        else:
            self.content = clean_word_html(self.content)
                
        super().save(*args, **kwargs)

class Acronym(models.Model):
    short = models.CharField(max_length=100, db_index=True, verbose_name="ראשי תיבות")
    meaning = models.TextField(verbose_name="פירוש / פיתוח ראשי תיבות")

    class Meta:
        verbose_name = "ראשי תיבות"
        verbose_name_plural = "מילון ראשי תיבות"
        ordering = ['short']

    def __str__(self): return f"{self.short} | {self.meaning[:40]}..."

class Cart(models.Model):
    session_id = models.CharField(max_length=255, blank=True, null=True, verbose_name="מזהה סשן")
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="משתמש (אם מחובר)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="נוצר בתאריך")
    def __str__(self): return f"עגלה {self.id}"

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    book = models.ForeignKey(Book, on_delete=models.CASCADE, verbose_name="ספר")
    quantity = models.PositiveIntegerField(default=1, verbose_name="כמות")
    def __str__(self): return f"{self.quantity} x {self.book.title}"
    def get_total_price(self): return self.quantity * self.book.price

class Order(models.Model):
    STATUS_CHOICES = (
        ('pending', 'ממתין לתשלום (ביט/העברה בנקאית)'),
        ('paid', 'שולם - ממתין למשלוח'),
        ('shipped', 'נשלח ללקוח'),
        ('cancelled', 'בוטל'),
    )
    first_name = models.CharField(max_length=50, verbose_name="שם פרטי")
    last_name = models.CharField(max_length=50, verbose_name="שם משפחה")
    email = models.EmailField(verbose_name="אימייל")
    phone = models.CharField(max_length=20, verbose_name="טלפון")
    address = models.CharField(max_length=250, verbose_name="כתובת למשלוח")
    city = models.CharField(max_length=100, verbose_name="עיר")
    zip_code = models.CharField(max_length=20, blank=True, verbose_name="מיקוד (אופציונלי)")
    tracking_number = models.CharField(max_length=100, blank=True, null=True, verbose_name="מספר מעקב דואר")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="תאריך הזמנה")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="עודכן לאחרונה")
    total_paid = models.DecimalField(max_digits=8, decimal_places=2, verbose_name="סך הכל לתשלום")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="סטטוס הזמנה")
    notes = models.TextField(blank=True, verbose_name="הערות להזמנה")
    def __str__(self): return f"הזמנה #{self.id} | {self.first_name} {self.last_name}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    book = models.ForeignKey(Book, on_delete=models.SET_NULL, null=True, verbose_name="ספר")
    price = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="מחיר בעת הרכישה")
    quantity = models.PositiveIntegerField(default=1, verbose_name="כמות")
    def __str__(self): return f"{self.quantity} x {self.book.title if self.book else 'ספר שנמחק'}"
    def get_cost(self): return self.price * self.quantity

from django.db.models.signals import pre_save
from django.dispatch import receiver

@receiver(pre_save, sender=Order)
def check_order_status_change(sender, instance, **kwargs):
    if instance.id:
        try:
            old_order = Order.objects.get(id=instance.id)
            if old_order.status != 'shipped' and instance.status == 'shipped':
                from .emails import send_shipping_update
                send_shipping_update(instance)
        except Order.DoesNotExist: pass

class QA(models.Model):
    question = models.CharField(max_length=255, verbose_name="שאלה")
    answer = models.TextField(verbose_name="תשובה")
    category = models.CharField(max_length=100, verbose_name="קטגוריה", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="תאריך הוספה")
    class Meta:
        verbose_name = "שאלה ותשובה"
        verbose_name_plural = "שאלות ותשובות"
    def __str__(self): return self.question

class VisitorLog(models.Model):
    ip_address = models.GenericIPAddressField(null=True, blank=True, verbose_name="כתובת IP")
    path = models.CharField(max_length=500, verbose_name="נתיב שביקר בו")
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name="זמן ביקור")
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="משתמש")
    user_agent = models.TextField(blank=True, verbose_name="דפדפן / מכשיר")
    class Meta:
        verbose_name = "לוג ביקור"
        verbose_name_plural = "לוגים של מבקרים"
        ordering = ['-timestamp']
    def __str__(self): return f"{self.ip_address} | {self.path} ({self.timestamp})"

class TorahText(models.Model):
    book = models.CharField(max_length=100, db_index=True, verbose_name="ספר")
    chapter = models.CharField(max_length=50, db_index=True, verbose_name="פרק")
    verse = models.CharField(max_length=10, verbose_name="פסוק")
    text_with_nikkud = models.TextField(verbose_name="טקסט מנוקד")
    clean_text = models.TextField(verbose_name="טקסט נקי (ללא ניקוד ורווחים)", blank=True)
    
    verse_gematria = models.IntegerField(default=0, db_index=True)
    words_gematria = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "טקסט תורני"
        verbose_name_plural = "טקסטים תורניים"
        indexes = [
            models.Index(fields=['clean_text']),
            models.Index(fields=['book', 'chapter']),
        ]
    def __str__(self): return f"{self.book} {self.chapter} {self.verse}"

class TorahTextFTS(models.Model):
    book = models.TextField(verbose_name="ספר")
    chapter = models.TextField(verbose_name="פרק")
    verse = models.TextField(verbose_name="פסוק")
    text_with_nikkud = models.TextField(verbose_name="טקסט מנוקד")
    class Meta:
        managed = False 
        db_table = 'articles_torahtext_fts'