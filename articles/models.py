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

    # === 0. מחיקת עיצוב קודם שלנו (כדי ששמירה חוזרת לא תשכפל) ===
    for old_h2 in soup.find_all('h2', string="הערות שוליים"):
        old_hr = old_h2.find_previous_sibling('hr')
        if old_hr:
            old_hr.decompose()
        old_ol = old_h2.find_next_sibling('ol', class_='custom-footnotes-list')
        if old_ol:
            old_ol.unwrap() 
        old_h2.decompose()

    # === 1. עיצוב הפניות להערות שוליים בתוך הטקסט (המספרים הקטנים) ===
    for a in soup.find_all('a', href=True):
        href = a['href']
        # זיהוי לינקים שמפנים למטה להערות (כמו #_ftn1 או #footnote1)
        if re.match(r'^#(_ftn|ftn|footnote)\d+', href) and not re.match(r'^#(_ftnref|ftnref|footnote-ref)', href):
            text = a.get_text(strip=True)
            clean_num = text.replace('[', '').replace(']', '') # הורדת סוגריים מרובעים
            if clean_num.isdigit():
                a.string = clean_num
                a['class'] = a.get('class', []) + ['footnote-ref'] # מחלקה מיוחדת לעיצוב
                
        # מחיקת לינקים שמפנים חזרה למעלה (החצים)
        elif re.match(r'^#(_ftnref|ftnref|footnote-ref)', href):
            a.decompose()

    # מחיקת חצים (↑ או ^) שנשארו כטקסט רגיל
    for text_node in soup.find_all(string=re.compile(r'[↑^]')):
        text_node.replace_with(text_node.replace('↑', '').replace('^', '').strip())

    # === 2. איסוף כל ההערות מהתחתית (כפי שהועתקו מוורד) ===
    footnotes_to_move = []
    
    # חיפוש תגיות שיש להן מאפיין name של הערה
    for a_tag in soup.find_all('a', attrs={"name": re.compile(r'^(_ftn|ftn|footnote)\d+')}):
        parent_block = a_tag.find_parent(['p', 'div', 'li'])
        if parent_block and parent_block not in footnotes_to_move:
            footnotes_to_move.append(parent_block)
    
    # חיפוש תגיות עם id של הערה
    for tag in soup.find_all(['p', 'div', 'li'], id=re.compile(r'^(_ftn|ftn|footnote)\d+')):
        if tag not in footnotes_to_move:
            footnotes_to_move.append(tag)

    # === 3. בניית אזור ההערות המעוצב בסוף ===
    if footnotes_to_move:
        # הקו העבה המפריד
        hr = soup.new_tag('hr', style='border: 0; border-top: 5px solid #2c3e50; margin: 60px 0 40px 0; opacity: 1;')
        # כותרת ההערות
        h2 = soup.new_tag('h2', style='text-align: center; color: #d4af37; margin-bottom: 30px; font-weight: bold;')
        h2.string = "הערות שוליים"
        # רשימת ההערות המסודרת
        ol = soup.new_tag('ol', class_='custom-footnotes-list', style='font-size: 1.1em; line-height: 1.8; margin-right: 20px; padding-right: 20px;')

        for fn_block in footnotes_to_move:
            li = soup.new_tag('li', style='margin-bottom: 15px;')
            
            # העברת ה-ID אל הפריט החדש כדי שהקישור מהטקסט יעבוד במדויק!
            fn_id = fn_block.get('id')
            if not fn_id:
                anchor = fn_block.find('a', attrs={"name": re.compile(r'^(_ftn|ftn|footnote)\d+')})
                if anchor:
                    fn_id = anchor.get('name')
                    anchor.decompose()
            if fn_id:
                li['id'] = fn_id

            # ביטול פסקאות פנימיות שגורמות לריווח ענק
            for p in fn_block.find_all('p'):
                p.unwrap()
                
            # מחיקת מספרים כפולים בהתחלה ("1. ") כדי שהרשימה תמספר לבד
            for child in fn_block.contents:
                if isinstance(child, str):
                    stripped = re.sub(r'^\s*\d+[\.\)\]]*\s*', '', child)
                    child.replace_with(stripped)
                    break
                    
            for child in list(fn_block.contents):
                li.append(child)
                
            ol.append(li)
            fn_block.extract() # מחיקת ההערה המבולגנת מהמיקום המקורי

        soup.append(hr)
        soup.append(h2)
        soup.append(ol)

    # === 4. ניקוי שאריות ורווחים מיותרים ===
    for tag in soup.find_all(['p', 'div', 'ol', 'ul']):
        if not tag.get_text(strip=True) and not tag.find(['img', 'iframe']):
            tag.decompose()

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
    
    # הגדלנו את השדה כדי שיוכל להכיל מספר פרשות יחד כמו "בא,ואתחנן"
    parasha = models.CharField(max_length=500, default=',general,', verbose_name="שיוך לפרשות שבוע", blank=True)
    
    # תוקן: הוסרה המילה 'Text'
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
        """מחזיר אמת אם המאמר נוצר ב-7 הימים האחרונים"""
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
    
    # תוקן: הוסרה המילה 'Text'
    summary = CKEditor5Field(config_name='extends', verbose_name="תקציר הספר", blank=True, null=True)
    
    price = models.DecimalField(max_digits=6, decimal_places=2, default=0.00, verbose_name="מחיר הספר")
    is_for_sale = models.BooleanField(default=False, verbose_name="זמין לרכישה")
    stock = models.PositiveIntegerField(default=0, verbose_name="מלאי זמין")
    created_at = models.DateTimeField(default=timezone.now, verbose_name="תאריך הוספה")
    
    # השדה שמאפשר שליטה על סדר התצוגה בעמוד הספרים
    order = models.PositiveIntegerField(default=0, verbose_name="סדר תצוגה (1 יופיע ראשון)")
    
    @property
    def is_new(self):
        """מחזיר אמת אם הספר נוסף ב-7 הימים האחרונים"""
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
    
    # תוקן: הוסרה המילה 'Text'
    content = CKEditor5Field(config_name='extends', verbose_name="תוכן")
    
    order = models.PositiveIntegerField(verbose_name="סדר")

    def __str__(self):
        return f"{self.chapter.title} - {self.title}"

    def save(self, *args, **kwargs):
        self.content = clean_word_html(self.content)
        super().save(*args, **kwargs)


# ==========================================
# מודל מילון ראשי תיבות (הנתונים החדשים)
# ==========================================
class Acronym(models.Model):
    short = models.CharField(max_length=100, db_index=True, verbose_name="ראשי תיבות")
    meaning = models.TextField(verbose_name="פירוש / פיתוח ראשי תיבות")

    class Meta:
        verbose_name = "ראשי תיבות"
        verbose_name_plural = "מילון ראשי תיבות"
        ordering = ['short']

    def __str__(self):
        return f"{self.short} - {self.meaning[:40]}..."

# ==========================================
# מודלים לעגלת קניות והזמנות
# ==========================================
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

# ==========================================
# Signals (האזנה לאירועים במסד הנתונים)
# ==========================================
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

# ==========================================
# מודל מעקב מבקרים (לצרכי סקרים ובדיקות)
# ==========================================
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

# ==========================================
# מודל טקסט תורני לחיפוש מתקדם (גימטריות / ELS)
# ==========================================
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


# ==========================================
# מודל וירטואלי עבור מנוע חיפוש מהיר (SQLite FTS5)
# ==========================================
class TorahTextFTS(models.Model):
    """מודל וירטואלי הממפה את טבלת ה-FTS5 המובנית במסד הנתונים לשליפות מהירות ברמת C"""
    book = models.TextField(verbose_name="ספר")
    chapter = models.TextField(verbose_name="פרק")
    verse = models.TextField(verbose_name="פסוק")
    text_with_nikkud = models.TextField(verbose_name="טקסט מנוקד")

    class Meta:
        managed = False  # מונע מ-Django לנסות ליצור או לשנות את הטבלה הזו דרך migrations רגילים
        db_table = 'articles_torahtext_fts'