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
        
    soup = BeautifulSoup(html_content, 'html.parser')

    # === 1. סידור ההפניות בגוף הטקסט (המספרים הקטנים) ===
    # טיפול במספרים שהם קישורים (וורד סטנדרטי)
    for a in soup.find_all('a'):
        text = a.get_text(strip=True)
        # זיהוי אם הקישור מכיל רק מספרים וסוגריים
        num = re.sub(r'\D', '', text)
        if num and re.sub(r'[\d\[\]\(\)]', '', text) == '':
            a.string = num
            a['href'] = f"#footnote-{num}"
            a['class'] = a.get('class', []) + ['footnote-ref']
            # עוטף ב-SUP כדי שיופיע בקטן למעלה
            if a.parent and a.parent.name != 'sup':
                a.wrap(soup.new_tag('sup'))
                
    # טיפול במספרים עיליים רגילים ללא קישור (במידה ו-CKEditor מחק להם את הלינק)
    for sup in soup.find_all('sup'):
        if not sup.find('a'):
            text = sup.get_text(strip=True)
            num = re.sub(r'\D', '', text)
            if num and re.sub(r'[\d\[\]\(\)]', '', text) == '':
                a = soup.new_tag('a', href=f"#footnote-{num}", class_="footnote-ref")
                a.string = num
                sup.string = ''
                sup.append(a)

    # === 2. איתור תחילת אזור ההערות בתחתית הדף ===
    first_fn_node = None
    for p in soup.find_all(['p', 'div', 'li']):
        text = p.get_text(strip=True)
        # זיהוי שורה שמתחילה במספר כלשהו + חץ, למשל: "1. ^ ירושלמי..."
        if re.match(r'^[\s\[\]\(\)]*\d+[\.\)\]\-]*\s*\^', text):
            first_fn_node = p
            break

    # === 3. חילוץ וסידור ההערות ===
    if first_fn_node:
        # מחיקת אזור הערות שנוצר בעבר (כדי ששמירה חוזרת לא תשכפל)
        for h2 in soup.find_all('h2', string="הערות שוליים"):
            hr = h2.find_previous_sibling('hr')
            if hr: hr.decompose()
            container = h2.find_next_sibling('div', class_='custom-footnotes-container')
            if container: container.decompose()
            old_ol = h2.find_next_sibling('ol', class_='custom-footnotes-list')
            if old_ol: old_ol.decompose()
            h2.decompose()

        # איסוף כל האלמנטים מאזור ההערות ועד הסוף
        raw_elements = []
        curr = first_fn_node
        while curr:
            next_node = curr.next_sibling
            raw_elements.append(curr.extract())
            curr = next_node

        built_footnotes = []
        current_fn = None

        for el in raw_elements:
            if not hasattr(el, 'get_text'): continue
            text = el.get_text(strip=True)
            if not text: continue
            
            # העלמת כל החצים
            for text_node in el.find_all(string=re.compile(r'[↑^]')):
                text_node.replace_with(text_node.replace('↑', '').replace('^', ''))
                
            # הסרת כל הקישורים הפנימיים המיותרים בתוך ההערה
            for a in el.find_all('a'):
                a.decompose()
                
            # זיהוי האם זו תחילת הערה חדשה
            match = re.match(r'^[\s\[\]\(\)]*(\d+)[\.\)\]\-]*\s*(.*)', el.get_text(strip=True))
            if match:
                num = match.group(1)
                
                # הסרת המספר מתחילת הטקסט כדי למנוע כפילות בתצוגה
                for text_node in el.find_all(string=True):
                    if num in text_node:
                        new_text = re.sub(r'^[\s\[\]\(\)]*' + num + r'[\.\)\]\-]*\s*', '', text_node, count=1)
                        text_node.replace_with(new_text)
                        break
                        
                for p in el.find_all('p'): p.unwrap() # ביטול שבירת שורות מיותרות
                
                current_fn = {'num': num, 'elements': [el]}
                built_footnotes.append(current_fn)
            elif current_fn:
                for p in el.find_all('p'): p.unwrap()
                current_fn['elements'].append(el)

        # === 4. הזרקת ההערות חזרה למסמך בעיצוב נקי ===
        if built_footnotes:
            hr_new = soup.new_tag('hr', style='border: 0; border-top: 5px solid #2c3e50; margin: 60px 0 40px 0; opacity: 1;')
            h2 = soup.new_tag('h2', style='text-align: center; color: #d4af37; margin-bottom: 30px; font-weight: bold;')
            h2.string = "הערות שוליים"
            container = soup.new_tag('div', class_='custom-footnotes-container', style='font-size: 1.1em; line-height: 1.8; margin-right: 10px;')

            for fn in built_footnotes:
                # שימוש ב-flexbox פותר לחלוטין את בעיית שבירת השורות של וורד
                div = soup.new_tag('div', style='margin-bottom: 15px; display: flex; align-items: flex-start;')
                div['id'] = f"footnote-{fn['num']}"
                
                num_span = soup.new_tag('span', style='font-weight:bold; color:#d4af37; min-width: 35px; flex-shrink: 0;')
                num_span.string = f"{fn['num']}."
                
                content_span = soup.new_tag('span', style='flex-grow: 1;')
                for el in fn['elements']:
                    content_span.append(el)
                    
                div.append(num_span)
                div.append(content_span)
                container.append(div)

            soup.append(hr_new)
            soup.append(h2)
            soup.append(container)

    # מחיקת פסקאות ריקות
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