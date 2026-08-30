from django.db import models
from django.utils import timezone

import re
from bs4 import BeautifulSoup
# ------------------------------------------
# ייבוא מעודכן עבור CKEditor 5
# ------------------------------------------
from django_ckeditor_5.fields import CKEditor5Field

from pyluach import dates
from django.contrib.auth.models import User
from datetime import timedelta

# ==========================================
# פונקציית ניקוי גלובלית להעתקות מוורד
# ==========================================
def clean_word_html(html_content):
    if not html_content:
        return html_content
        
    # השמדה מוחלטת של כל סוגי החצים כבר ברמת המחרוזת הבסיסית!
    html_content = html_content.replace('^', '').replace('↑', '').replace('ˆ', '')
    soup = BeautifulSoup(html_content, 'html.parser')

    # === 0. מחיקת עיצוב קודם שלנו (כדי ששמירה חוזרת לא תשכפל) ===
    for el in soup.find_all('div', class_='custom-footnotes-container'):
        el.decompose()
    for el in soup.find_all('h2', string="הערות שוליים"):
        prev_hr = el.find_previous_sibling('hr')
        if prev_hr: prev_hr.decompose()
        el.decompose()

    paragraphs = soup.find_all(['p', 'div'])
    
    # === 1. איתור חכם של אזור ההערות בתחתית הדף ===
    footnote_start_idx = -1
    for i, p in enumerate(paragraphs):
        text = p.get_text(strip=True)
        # מחפש פסקה שמכילה רק מספר הערה ראשון (למשל: "1", "1.", ".1", "[1]")
        if re.match(r'^[\.\[\]\(\)]*\s*1\s*[\.\[\]\(\)]*$', text):
            # מוודא שזה באמת אזור ההערות (בודק אם יש "2" קרוב או שזה סוף המסמך)
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
            
            # מצב א': פסקה שהיא רק מספר (כמו שקרה לך בצילום מסך)
            match_standalone = re.match(r'^[\.\[\]\(\)]*\s*(\d+)\s*[\.\[\]\(\)]*$', text)
            if match_standalone:
                num = match_standalone.group(1)
                current_fn = {'num': num, 'elements': []}
                built_footnotes.append(current_fn)
                p.decompose()
                continue
                
            # מצב ב': פסקה שמתחילה במספר ואז טקסט (כמו 1. ירושלמי...)
            match_inline = re.match(r'^[\.\[\]\(\)]*\s*(\d+)[\.\[\]\(\)\-\:]*\s+(.*)$', text)
            if match_inline:
                num = match_inline.group(1)
                expected_num = str(len(built_footnotes) + 1)
                # וידוא שזה באמת המספר הבא ברצף
                if num == expected_num or num == str(len(built_footnotes)):
                    current_fn = {'num': num, 'elements': []}
                    built_footnotes.append(current_fn)
                    # מחיקת המספר מתחילת הטקסט ויזואלית (ללא איבוד תגיות HTML)
                    for text_node in p.find_all(string=True):
                        if num in text_node:
                            new_val = re.sub(r'^[\s\.\[\]\(\)]*' + num + r'[\s\.\[\]\(\)\-\:]*', '', text_node, count=1)
                            text_node.replace_with(new_val)
                            break
                    current_fn['elements'].append(p.extract())
                    continue
                    
            # מצב ג': המשך של הערה קיימת שירדה שורה
            if current_fn:
                current_fn['elements'].append(p.extract())

    # === 2. שחזור וסידור ההפניות (המספרים הקטנים) בגוף המאמר ===
    
    # א. אם וורד שמר על תגיות הקישור
    for a in soup.find_all('a'):
        href = a.get('href', '')
        if href.startswith('#'):
            text = a.get_text(strip=True)
            clean_num = re.sub(r'\D', '', text)
            if clean_num and clean_num.isdigit():
                a.string = clean_num
                a['href'] = f"#footnote-{clean_num}"
                a['class'] = a.get('class', []) + ['footnote-ref']
                if a.parent and a.parent.name != 'sup':
                    a.wrap(soup.new_tag('sup'))
                    
    # ב. אם נשארו רק תגיות <sup> ללא קישור
    for sup in soup.find_all('sup'):
        if not sup.find('a'):
            text = sup.get_text(strip=True)
            clean_num = re.sub(r'\D', '', text)
            if clean_num and clean_num.isdigit():
                a = soup.new_tag('a', href=f"#footnote-{clean_num}", class_="footnote-ref")
                a.string = clean_num
                sup.string = ''
                sup.append(a)

    # ג. מנגנון חילוץ עמוק: אם וורד הפך את ההפניה לטקסט רגיל לגמרי כמו [1]
    if built_footnotes:
        max_fn = len(built_footnotes)
        for text_node in soup.find_all(string=re.compile(r'\[\d+\]')):
            new_html = re.sub(
                r'\[(\d+)\]', 
                lambda m: f'<sup><a href="#footnote-{m.group(1)}" class="footnote-ref">{m.group(1)}</a></sup>' if int(m.group(1)) <= max_fn else m.group(0), 
                text_node
            )
            if new_html != text_node:
                new_soup = BeautifulSoup(new_html, 'html.parser')
                text_node.replace_with(new_soup)

    # === 3. הזרקת אזור ההערות המעוצב בסוף המאמר (Flexbox לעימוד מושלם) ===
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
                # הסרת פסקאות פנימיות כדי שהטקסט לא יישבר לשורה חדשה וישב צמוד למספר
                if el.name == 'p':
                    el.unwrap()
                content_span.append(el)
                content_span.append(soup.new_string(" ")) 
                
            div.append(num_span)
            div.append(content_span)
            container.append(div)

        soup.append(hr_new)
        soup.append(h2)
        soup.append(container)

    # ניקוי סופי של פסקאות ריקות שעושות רווחים
    for p in soup.find_all('p'):
        if not p.get_text(strip=True) and not p.find(['img', 'iframe']):
            p.decompose()

    return str(soup)


# ==========================================
# רשימת פרשות השבוע (מסודרת לפי חומשים)
# ==========================================
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
    parasha = models.CharField(max_length=500, default=',general,', verbose_name="שיוך לפרשות שבוע", blank=True)
    content = CKEditor5Field(config_name='extends', verbose_name="תוכן המאמר") 
    hebrew_date = models.CharField(max_length=100, verbose_name="תאריך עברי", blank=True)
    created_at = models.DateTimeField(default=timezone.now, verbose_name="תאריך יצירה")
    is_published = models.BooleanField(default=True, verbose_name="מפורסם")

    @property
    def hebrew_date_auto(self):
        if self.created_at: 
            heb_date = dates.HebrewDate.from_pydate(self.created_at.date())
            return heb_date.hebrew_date_string() 
        return ""

    @property
    def is_new(self):
        if not self.created_at:
            return False
        return self.created_at >= timezone.now() - timedelta(days=7)

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.content = clean_word_html(self.content)
        super().save(*args, **kwargs)


class Book(models.Model):
    title = models.CharField(max_length=200, verbose_name="שם הספר")
    author = models.CharField(max_length=100, verbose_name="מחבר")
    cover_image = models.ImageField(upload_to='books/covers/', blank=True, null=True, verbose_name="תמונת כריכה")
    summary = CKEditor5Field(config_name='extends', verbose_name="תקציר הספר", blank=True, null=True)
    price = models.DecimalField(max_digits=6, decimal_places=2, default=0.00, verbose_name="מחיר הספר")
    is_for_sale = models.BooleanField(default=False, verbose_name="זמין לרכישה")
    stock = models.PositiveIntegerField(default=0, verbose_name="מלאי זמין")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="תאריך הוספה")
    order = models.PositiveIntegerField(default=0, verbose_name="סדר תצוגה (1 יופיע ראשון)")
    
    @property
    def is_new(self):
        if not self.created_at:
            return False
        return self.created_at >= timezone.now() - timedelta(days=7)
    
    class Meta:
        ordering = ['order', 'title']

    def __str__(self):
        return self.title


class Chapter(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='chapters', verbose_name="ספר")
    title = models.CharField(max_length=200, verbose_name="כותרת (למשל: סימן א)")
    order = models.PositiveIntegerField(verbose_name="סדר")

    def __str__(self):
        return f"{self.book.title} - {self.title}"


class Section(models.Model):
    chapter = models.ForeignKey(Chapter, on_delete=models.CASCADE, related_name='sections', verbose_name="פרק")
    title = models.CharField(max_length=200, verbose_name="כותרת הסעיף")
    content = CKEditor5Field(config_name='extends', verbose_name="תוכן")
    order = models.PositiveIntegerField(verbose_name="סדר")

    def __str__(self):
        return f"{self.chapter.title} - {self.title}"

    def save(self, *args, **kwargs):
        self.content = clean_word_html(self.content)
        super().save(*args, **kwargs)


class Acronym(models.Model):
    short = models.CharField(max_length=100, db_index=True, verbose_name="ראשי תיבות")
    meaning = models.TextField(verbose_name="פירוש / פיתוח ראשי תיבות")

    class Meta:
        verbose_name = "ראשי תיבות"
        verbose_name_plural = "מילון ראשי תיבות"
        ordering = ['short']

    def __str__(self):
        return f"{self.short} - {self.meaning[:40]}..."

class Cart(models.Model):
    session_id = models.CharField(max_length=255, blank=True, null=True, verbose_name="מזהה סשן")
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, verbose_name="משתמש (אם מחובר)")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="נוצר בתאריך")

    def __str__(self):
        return f"עגלה {self.id}"

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name='items', on_delete=models.CASCADE)
    book = models.ForeignKey(Book, on_delete=models.CASCADE, verbose_name="ספר")
    quantity = models.PositiveIntegerField(default=1, verbose_name="כמות")

    def __str__(self):
        return f"{self.quantity} x {self.book.title}"

    def get_total_price(self):
        return self.quantity * self.book.price

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

    def __str__(self):
        return f"הזמנה #{self.id} - {self.first_name} {self.last_name}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    book = models.ForeignKey(Book, on_delete=models.SET_NULL, null=True, verbose_name="ספר")
    price = models.DecimalField(max_digits=6, decimal_places=2, verbose_name="מחיר בעת הרכישה")
    quantity = models.PositiveIntegerField(default=1, verbose_name="כמות")

    def __str__(self):
        return f"{self.quantity} x {self.book.title if self.book else 'ספר שנמחק'}"

    def get_cost(self):
        return self.price * self.quantity

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
        except Order.DoesNotExist:
            pass

class QA(models.Model):
    question = models.CharField(max_length=255, verbose_name="שאלה")
    answer = models.TextField(verbose_name="תשובה")
    category = models.CharField(max_length=100, verbose_name="קטגוריה", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="תאריך הוספה")

    class Meta:
        verbose_name = "שאלה ותשובה"
        verbose_name_plural = "שאלות ותשובות"

    def __str__(self):
        return self.question

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

    def __str__(self):
        return f"{self.ip_address} - {self.path} ({self.timestamp})"

class TorahText(models.Model):
    book = models.CharField(max_length=100, verbose_name="ספר")
    chapter = models.CharField(max_length=10, verbose_name="פרק")
    verse = models.CharField(max_length=10, verbose_name="פסוק")
    text_with_nikkud = models.TextField(verbose_name="טקסט מנוקד")
    clean_text = models.TextField(verbose_name="טקסט נקי (ללא ניקוד ורווחים)", blank=True)

    class Meta:
        verbose_name = "טקסט תורני"
        verbose_name_plural = "טקסטים תורניים"
        indexes = [
            models.Index(fields=['clean_text']),
        ]

    def __str__(self):
        return f"{self.book} {self.chapter} {self.verse}"


class TorahTextFTS(models.Model):
    book = models.TextField(verbose_name="ספר")
    chapter = models.TextField(verbose_name="פרק")
    verse = models.TextField(verbose_name="פסוק")
    text_with_nikkud = models.TextField(verbose_name="טקסט מנוקד")

    class Meta:
        managed = False  
        db_table = 'articles_torahtext_fts'