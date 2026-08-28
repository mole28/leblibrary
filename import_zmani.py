import os
import django
import re

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zmani_book():
    book_title = "זמני המילה וברכותיה"
    book, created = Book.objects.get_or_create(title=book_title)
    print(f"ספר מטופל: {book.title} (נוצר חדש: {created})")

    html_file_path = "zmani_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא בתיקייה!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # הדפסת שדות המודלים לצורך מעקב ובדיקה
    print("שדות ב-Chapter:", [f.name for f in Chapter._meta.get_fields() if not f.auto_created])
    print("שדות ב-Section:", [f.name for f in Section._meta.get_fields() if not f.auto_created])

    # מחיקת תוכן קודם של הספר כדי למנוע כפילויות בהרצה חוזרת
    Chapter.objects.filter(book=book).delete()
    print("נוקו פרקים קודמים של הספר.")

    # חלוקה ראשונית לפי מילת המפתח "סימן" בטקסט או בכותרות
    # נחלק את ה-HTML לפי תגיות כותרת או טקסט שמכיל "סימן"
    
    # לצורך התאמה מדויקת למבנה HTML של פאנדוק, נראה איך הכותרות בנויות:
    # נחפש ביטויים כמו "סימן א", "סימן ב" וכו'
    
    print("הסקריפט מוכן לניתוח ה-HTML.")

if __name__ == "__main__":
    import_zmani_book()