from django.db import models
from django.utils import timezone
from ckeditor.fields import RichTextField
from pyluach import dates
from django.contrib.auth.models import User
from datetime import timedelta

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
    
    content = RichTextField(verbose_name="תוכן המאמר") 
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

class Book(models.Model):
    title = models.CharField(max_length=200, verbose_name="שם הספר")
    author = models.CharField(max_length=100, verbose_name="מחבר")
    cover_image = models.ImageField(upload_to='books/covers/', blank=True, null=True, verbose_name="תמונת כריכה")
    summary = RichTextField(verbose_name="תקציר הספר", blank=True, null=True)
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
    content = RichTextField(verbose_name="תוכן")
    order = models.PositiveIntegerField(verbose_name="סדר")

    def __str__(self):
        return f"{self.chapter.title} - {self.title}"

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