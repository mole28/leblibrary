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

try:
    import mammoth
except ImportError:
    mammoth = None

# ==========================================
# פונקציית עיבוד גלובלית לייבוא מוורד (Mammoth)
# ==========================================
def process_mammoth_html(raw_html):
    if not raw_html: return ""
    soup = BeautifulSoup(raw_html, 'html.parser')

    # 1. סידור ההפניות בתוך המאמר והוספת סוגריים [1]
    for ref in soup.find_all('a', id=re.compile(r'^footnote-ref-')):
        clean_num = ref.get_text(strip=True).replace('[', '').replace(']', '')
        ref.string = f"[{clean_num}]" # הוספת סוגריים מרובעים מסביב למספר
        ref['class'] = ref.get('class', []) + ['footnote-ref']
        if ref.parent and ref.parent.name != 'sup':
            ref.wrap(soup.new_tag('sup'))

    # 2. חילוץ כל ההערות מהתחתית
    footnotes_dict = {}
    for li in soup.find_all('li', id=re.compile(r'^footnote-')):
        fn_id = li['id']
        # מחיקת החצים לחזרה למעלה
        for back_link in li.find_all('a', href=re.compile(r'^#footnote-ref-')):
            parent = back_link.parent
            back_link.decompose()
            if parent and parent.name == 'sup' and not parent.get_text(strip=True):
                parent.decompose()
        
        # ביטול פסקאות שגורמות לשבירת שורות
        for p in li.find_all('p'):
            p.unwrap()
            
        footnotes_dict[fn_id] = li
        li.extract()
        
    for ol in soup.find_all('ol'):
        if not ol.get_text(strip=True):
            ol.extract()

    # 3. בניה מחדש של תחתית המאמר עם הערות בעיצוב חלק (Flexbox)
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

    # 4. ניקוי פסקאות ריקות
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
    
    # === הוספת שדה העלאת הוורד ===
    word_file = models.FileField(upload_to='word_imports/', blank=True, null=True, verbose_name="ייבוא אוטומטי מוורד (מומלץ למאמרים עם הערות!)")
    
    content = CKEditor5Field(config_name='extends', verbose_name="תוכן המאמר", blank=True, null=True) 
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
        if self.word_file and mammoth:
            try:
                self.word_file.open('rb')
                result = mammoth.convert_to_html(self.word_file.file)
                self.content = process_mammoth_html(result.value)
                self.word_file.close()
                self.word_file = None 
            except Exception as e:
                print(f"Error parsing word: {e}")
                
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
    
    # === הוספת שדה העלאת הוורד גם לסעיפי הספרים ===
    word_file = models.FileField(upload_to='word_imports/', blank=True, null=True, verbose_name="ייבוא אוטומטי מוורד (מומלץ למאמרים עם הערות!)")
    
    content = CKEditor5Field(config_name='extends', verbose_name="תוכן", blank=True, null=True)
    order = models.PositiveIntegerField(verbose_name="סדר")

    def __str__(self):
        return f"{self.chapter.title} - {self.title}"

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