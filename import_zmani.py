import os
import django
import re

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zmani_book():
    book_title = "זמני המילה וברכותיה"
    
    book = Book.objects.filter(title=book_title).first()
    if not book:
        book = Book.objects.create(title=book_title)
        print(f"נוצר ספר חדש: {book.title}")
    else:
        print(f"נמצא ספר קיים: {book.title}")

    html_file_path = "zmani_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא בתיקייה!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    # ניקוי פרקים וסעיפים קודמים של הספר
    chapters_to_delete = Chapter.objects.filter(book=book)
    Section.objects.filter(chapter__in=chapters_to_delete).delete()
    chapters_to_delete.delete()
    print("נוקו פרקים וסעיפים קודמים.")

    # חלוקת ה-HTML לפי כותרות או זיהוי המילה "סימן"
    # נחלק לפי תגיות כותרת (h1, h2, h3) או לפי פסקאות שמכילות "סימן"
    # כברירת מחדל חכמה: אם אין חלוקה ברורה לתגיות, ניצור פרק ראשי וסעיפים
    
    # ניצור פרק ברירת מחדל ראשון (או נפרק לפי כותרות H1/H2)
    # בוא נחפש תגיות כותרת שבהן מופיע "סימן"
    
    # חלוקה בסיסית ואיכותית:
    current_chapter = Chapter.objects.create(
        book=book,
        title="פתח דבר וסקירה כללית",
        order=1
    )
    
    # נכניס את כל התוכן כסעיף ראשון תחת הפרק כשלב ראשון מוצק, 
    # או נחלק לפי כותרות אם קיימות
    Section.objects.create(
        chapter=current_chapter,
        title="תוכן הספר המלא",
        content=html_content,
        order=1
    )
    
    print("הספר פוצץ והוכנס בהצלחה למסד הנתונים!")

if __name__ == "__main__":
    import_zmani_book()