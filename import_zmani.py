import os
import django
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
    
    # הסרה מוחלטת וקשוחה של כל אלמנט שיכול לשבור את ה-DOM או ליצור התנגשות טפסים
    for element in soup(["script", "style", "meta", "link", "form", "input", "button", "select", "textarea", "iframe"]):
        element.decompose()

    # הסרת כל ה-IDs וה-Classes מכל התגיות כדי שלא יהיו שום כפילויות ID באתר
    for tag in soup.find_all(True):
        allowed_attrs = {}
        # נשמור אך ורק קישורים תקינים (href) ונתעלם מכל השאר
        if tag.name == 'a' and 'href' in tag.attrs:
            allowed_attrs['href'] = tag['href']
        tag.attrs = allowed_attrs

    cleaned_html = str(soup.body if soup.body else soup)

    # ניקוי פרקים וסעיפים קודמים
    chapters_to_delete = Chapter.objects.filter(book=book)
    Section.objects.filter(chapter__in=chapters_to_delete).delete()
    chapters_to_delete.delete()
    print("נוקו פרקים וסעיפים ישנים.")

    # יצירת פרק יחיד נקי לחלוטין ובטוח
    chapter = Chapter.objects.create(
        book=book,
        title="פתח דבר וסקירה כללית",
        order=1
    )
    
    Section.objects.create(
        chapter=chapter,
        title="תוכן הספר הנקי",
        content=cleaned_html,
        order=1
    )

    print("הספר עבר ניקוי מלא מכל הטפסים וה-IDs והוכנס בהצלחה!")

if __name__ == "__main__":
    import_zmani_book()