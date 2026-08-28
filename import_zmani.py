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
    
    book, _ = Book.objects.get_or_create(title=book_title)
    print(f"מעבד את הספר: {book.title}")

    html_file_path = "zmani_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, 'html.parser')
    
    # הסרת אלמנטים מסוכנים בלבד (שומרים על מזהים ותקינות התפריט)
    for element in soup(["script", "style", "meta", "link", "form", "input", "button", "textarea", "select"]):
        element.decompose()

    # שומרים id, name ו-href כדי שהתפריט והניווט יוכלו להתחבר לתוכן
    for tag in soup.find_all(True):
        allowed_attrs = {}
        if 'id' in tag.attrs:
            allowed_attrs['id'] = tag['id']
        if 'name' in tag.attrs:
            allowed_attrs['name'] = tag['name']
        if 'href' in tag.attrs:
            allowed_attrs['href'] = tag['href']
        tag.attrs = allowed_attrs

    # ניקוי פרקים וסעיפים קודמים למניעת כפילויות
    chapters_to_delete = Chapter.objects.filter(book=book)
    Section.objects.filter(chapter__in=chapters_to_delete).delete()
    chapters_to_delete.delete()
    print("נוקו פרקים וסעיפים ישנים.")

    full_text = str(soup)

    # פיצול לפי סימנים
    parts = re.split(r'(?i)(סימן\s+[א-ת]+(?:\s*–\s*[^<\n]+)?)', full_text)

    if len(parts) <= 1:
        ch = Chapter.objects.create(book=book, title="זמני המילה וברכותיה", order=1)
        Section.objects.create(chapter=ch, title="תוכן הספר", content=full_text, order=1)
    else:
        intro_content = parts[0]
        if intro_content.strip():
            intro_ch = Chapter.objects.create(book=book, title="פתח דבר והקדמה", order=1)
            Section.objects.create(chapter=intro_ch, title="פתח דבר", content=intro_content, order=1)

        ch_order = 2
        for i in range(1, len(parts), 2):
            siman_title = parts[i].strip()
            siman_body = parts[i+1] if i+1 < len(parts) else ""

            # יצירת פרק (סימן) שיופיע מודגש בתפריט הצד
            chapter = Chapter.objects.create(
                book=book,
                title=siman_title,
                order=ch_order
            )

            # יצירת סעיף תחתיו
            Section.objects.create(
                chapter=chapter,
                title=siman_title,
                content=siman_body,
                order=1
            )
            ch_order += 1

    print("הספר יובא בהצלחה עם שמירת מזהי הניווט!")

if __name__ == "__main__":
    import_zmani_book()