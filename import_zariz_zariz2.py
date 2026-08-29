import os
import django
import re
from bs4 import BeautifulSoup

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zariz_final_perfect():
    book_title = "זריזין מקדימין למילה"
    
    existing_books = Book.objects.filter(title=book_title)
    if existing_books.exists():
        for b in existing_books:
            for ch in b.chapters.all():
                Section.objects.filter(chapter=ch).delete()
            b.chapters.all().delete()
        existing_books.delete()

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
    elements = body_tag.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'div', 'hr', 'li'], recursive=True)

    # רשימת כותרות מדויקות בלבד (מונע ממשפטים רגילים להפוך לפרקים)
    exact_chapters = [
        "כללי זריזין מקדימין במצוות מילה",
        "דיני זריזין מקדימין במצוות מילה",
        "זריזין או הידור מצוה",
        "הקדמת מילה למצוות אחרות",
        "זמני הברית מילה",
        "אכילה ועשיית מלאכה קודם הברית מילה",
        "מילה במועדים",
        "מילה עם סוגי מוהלים שונים",
        "מאמר של מנהג 'שלום זכר'",
        "מאמר של מנהג שלום זכר",
        "שלום זכר"
    ]

    current_chapter = Chapter.objects.create(book=book, title="פתח דבר", order=1)
    ch_order = 2
    sec_order = 1
    
    current_sec_title = "פתח דבר"
    current_sec_content = []
    hr_added_in_section = False

    def save_section():
        nonlocal sec_order, current_sec_content, current_sec_title, hr_added_in_section
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
            hr_added_in_section = False

    halacha_pattern = re.compile(r'^\s*([א-ת]{1,4})[\.\,\׳״]\s+')

    for el in elements:
        text = el.get_text(strip=True)
        clean_text = text.replace('\xa0', ' ')
        if not clean_text:
            continue

        # בדיקה האם זו כותרת פרק אמיתית ומדויקת בלבד
        if clean_text in exact_chapters:
            save_section()
            current_chapter = Chapter.objects.create(book=book, title=clean_text, order=ch_order)
            ch_order += 1
            sec_order = 1
            current_sec_title = "מבוא"
            continue

        # הוספת פס שחור עבה ומובהק אוטומטית לפני אזור ההערות והמקורות (שמכילים את סימן ה-↩)
        if not hr_added_in_section and ('↩' in clean_text or 'fnref' in str(el)):
            current_sec_content.append('<hr style="border: 2px solid black; margin: 30px 0; width: 100%;" />')
            hr_added_in_section = True

        if halacha_pattern.match(clean_text) and len(clean_text) < 1500:
            save_section()
            current_sec_title = clean_text[:60] + "..." if len(clean_text) > 60 else clean_text
            current_sec_content.append(f"<h3 style='color:#004085; border-bottom:1px solid #ccc; padding-bottom:5px; margin-top:20px;'>{clean_text}</h3>")
            continue

        current_sec_content.append(el)

    save_section()
    print("הספר עודכן בהצלחה עם הפס השחור להערות ותיקון הכותרות!")

if __name__ == "__main__":
    import_zariz_final_perfect()