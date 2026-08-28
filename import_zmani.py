import os
import django
import re
from bs4 import BeautifulSoup

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
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, 'html.parser')
    for element in soup(["script", "style", "meta", "link"]):
        element.decompose()

    # ניקוי פרקים וסעיפים קודמים כדי למנוע כפילויות
    chapters_to_delete = Chapter.objects.filter(book=book)
    Section.objects.filter(chapter__in=chapters_to_delete).delete()
    chapters_to_delete.delete()
    print("נוקו פרקים וסעיפים ישנים.")

    # חלוקה חכמה לפי כותרות או זיהוי "סימן" בטקסט
    # נחפש את כל האלמנטים שמכילים את המילה "סימן" או כותרות
    full_text = str(soup)
    
    # פיצול לפי מילת המפתח "סימן" (למשל "סימן א", "סימן ב" וכו')
    parts = re.split(r'(סימן\s+[א-ת]+(?:\s*–\s*[^<\n]+)?)', full_text)

    if len(parts) <= 1:
        # אם לא נמצאו סימנים לפי הרגולר, ניצור פרק כללי
        ch = Chapter.objects.create(book=book, title="זמני המילה וברכותיה - תוכן מלא", order=1)
        Section.objects.create(chapter=ch, title="הספר המלא", content=full_text, order=1)
    else:
        # טיפול במה שמופיע לפני הסימן הראשון (הקדמות, פפתח דבר)
        intro_content = parts[0]
        if intro_content.strip():
            intro_ch = Chapter.objects.create(book=book, title="הקדמה ופתח דבר", order=1)
            Section.objects.create(chapter=intro_ch, title="פתח דבר", content=intro_content, order=1)

        # מעבר על כל סימן שנמצא ויצירת פרק נפרד עבורו (שיופיע מודגש בתפריט)
        ch_order = 2
        for i in range(1, len(parts), 2):
            siman_title = parts[i].strip()
            siman_body = parts[i+1] if i+1 < len(parts) else ""

            chapter = Chapter.objects.create(
                book=book,
                title=siman_title,
                order=ch_order
            )

            # יצירת סעיף תחת הסימן (שיופיע רגיל מתחתיו בתפריט)
            Section.objects.create(
                chapter=chapter,
                title=f"עיונים ב{siman_title}",
                content=siman_body,
                order=1
            )
            ch_order += 1

    print("הספר פוצץ והוכנס לפרקים וסעיפים בהצלחה מלאה!")

if __name__ == "__main__":
    import_zmani_book()