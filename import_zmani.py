import os
import django
import re

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zmani_book():
    book_title = "זמני המילה וברכותיה"
    
    # טיפול בטוח במקרה שיש כפילויות במסד הנתונים
    book = Book.objects.filter(title=book_title).first()
    if book:
        created = False
        print(f"נמצא ספר קיים: {book.title} (מזהה: {book.id})")
    else:
        book = Book.objects.create(title=book_title)
        created = True
        print(f"נוצר ספר חדש: {book.title}")

    html_file_path = "zmani_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא בתיקייה!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # בדיקת השדות האמיתיים במודלים
    print("שדות ב-Chapter:", [f.name for f in Chapter._meta.get_fields() if not f.auto_created])
    print("שדות ב-Section:", [f.name for f in Section._meta.get_fields() if not f.auto_created])

    # ניקוי פרקים קודמים של הספר הנוכחי בלבד
    Chapter.objects.filter(book=book).delete()
    print("נוקו פרקים קודמים של הספר.")

    print("הסקריפט מוכן לשלב החלוקה והיבוא.")

if __name__ == "__main__":
    import_zmani_book()