import os
import django
import re
from bs4 import BeautifulSoup

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zariz_zariz2():
    book_title = "זריזין מקדימין למילה"
    
    # ניקוי מהיר של גרסאות קודמות מהמסד
    existing_books = Book.objects.filter(title=book_title)
    if existing_books.exists():
        for b in existing_books:
            for ch in b.chapters.all():
                Section.objects.filter(chapter=ch).delete()
            b.chapters.all().delete()
        existing_books.delete()
        print("נמחקה הגרסה הישנה של הספר.")

    # יצירת הספר מחדש
    book = Book.objects.create(title=book_title)
    for field in ['author', 'writer', 'creator']:
        if hasattr(book, field):
            setattr(book, field, "משה לייבוביץ")
            book.save()
            break

    html_file_path = "zariz2_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        soup = BeautifulSoup(f.read(), 'html.parser')
        
    for el in soup(["script", "style", "meta", "link"]):
        el.decompose()

    body_tag = soup.find('body') or soup
    elements = body_tag.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'div'], recursive=True)

    # יצירת פרק ראשון עבור פתח דבר
    current_chapter = Chapter.objects.create(book=book, title="פתח דבר והקדמה", order=1)
    ch_order = 2
    sec_order = 1
    
    current_sec_title = "פתח דבר"
    current_sec_content = []

    def save_section():
        nonlocal sec_order, current_sec_content, current_sec_title
        if current_sec_content and current_chapter:
            css = "<style>sup, sub, a[href*=\"fnref\"], a[href*=\"footnote\"] { font-size: 1.35em !important; font-weight: bold !important; }</style>"
            content_html = css + "".join([str(t) for t in current_sec_content])
            
            Section.objects.create(
                chapter=current_chapter,
                title=current_sec_title,
                content=content_html,
                order=sec_order
            )
            sec_order += 1
            current_sec_content = []

    # תבניות לזיהוי סעיפים (א., ב., ג' וכו') ומעבר למאמר שלום זכר
    halacha_pattern = re.compile(r'^([א-ת]{1,2})\.\s+')
    shalom_zachar_pattern = re.compile(r'^(שלום זכר|מאמר של מנהג)', re.IGNORECASE)

    for el in elements:
        text = el.get_text(strip=True)
        if not text:
            continue

        # מעבר אוטומטי לפרק "שלום זכר" כשמגיעים אליו בקובץ
        if shalom_zachar_pattern.search(text) and len(text) < 50:
            save_section()
            current_chapter = Chapter.objects.create(book=book, title="מאמר של מנהג שלום זכר", order=ch_order)
            ch_order += 1
            sec_order = 1
            current_sec_title = "מקור המנהג וטעמיו"
            continue

        # זיהוי תחילת סעיף/הלכה חדשה לפי האותיות (א., ב., ג'...)
        if halacha_pattern.match(text) and len(text) < 120:
            save_section()
            current_sec_title = text[:60] + "..." if len(text) > 60 else text
            # עיצוב בולט לכותרת הסעיף באתר
            current_sec_content.append(f"<h3 style='color:#004085; border-bottom:1px solid #ccc; padding-bottom:5px; margin-top:20px;'>{text}</h3>")
            continue

        current_sec_content.append(el)

    save_section()
    print("הספר מורכב ויובא בהצלחה עם כל הביאורים והסעיפים במסודר!")

if __name__ == "__main__":
    import_zariz_zariz2()