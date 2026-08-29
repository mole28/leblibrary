import os
import django
import re
from bs4 import BeautifulSoup

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zariz_final_absolute():
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
    elements = body_tag.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'div', 'hr', 'li', 'ol', 'ul'], recursive=True)

    exact_chapters = [
        "כללי זריזין מקדימין במצוות מילה",
        "דיני זריזין מקדימין במצוות מילה",
        "זריזין או הידור מצוה",
        "הקדמת מילה למצוות אחרות",
        "זמני הברית מילה",
        "אכילה ועשיית מלאכה קודם הברית מילה",
        "מילה במועדים",
        "מילה עם סוגי מוהלים שונים",
        "שלום זכר"
    ]

    current_chapter = Chapter.objects.create(book=book, title="פתח דבר", order=1)
    ch_order = 2
    sec_order = 1
    
    current_sec_title = "פתח דבר"
    current_sec_content = []
    in_footnotes = False

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

    halacha_pattern = re.compile(r'^\s*([א-ת]{1,4})[\.\,\׳״]\s+')
    shalom_zachar_main_pattern = re.compile(r'^[א-ח]\.\s+(מקור המנהג|טעמי המנהג|זמן השמחה|באיזה ליל|כשהתינוק|השמחה רק|שם השמחה|איזה סעודה)')

    for el in elements:
        text = el.get_text(strip=True)
        clean_text = text.replace('\xa0', ' ')
        if not clean_text:
            continue

        # מעבר לפרק שלום זכר
        if clean_text in ["שלום זכר", "מאמר של מנהג 'שלום זכר'", "מאמר של מנהג שלום זכר"]:
            save_section()
            current_chapter = Chapter.objects.create(book=book, title="שלום זכר", order=ch_order)
            ch_order += 1
            sec_order = 1
            current_sec_title = "מבוא"
            in_footnotes = False
            continue

        # בדיקה האם זו כותרת פרק ראשית רגילה
        matched_chapter_title = None
        for kw in exact_chapters:
            if kw == clean_text:
                matched_chapter_title = clean_text
                break

        if matched_chapter_title:
            save_section()
            current_chapter = Chapter.objects.create(book=book, title=matched_chapter_title, order=ch_order)
            ch_order += 1
            sec_order = 1
            current_sec_title = "מבוא"
            in_footnotes = False
            continue

        # זיהוי מובהק של תחילת אזור ההערות (מכיל את סימן החזרה ↩ או רשימת מקורות בסוף סעיף)
        if not in_footnotes and ('↩' in clean_text or el.name == 'li' and ('רמב"ם' in clean_text or 'בראשית' in clean_text or 'שבת' in clean_text) and len(current_sec_content) > 5):
            current_sec_content.append('<hr style="border: 3px solid black; margin: 40px 0; width: 100%;" />')
            in_footnotes = True

        # זיהוי תחילת סעיף ראשי (א., ב., ג'...)
        if (halacha_pattern.match(clean_text) or shalom_zachar_main_pattern.match(clean_text)) and len(clean_text) < 1500 and not in_footnotes:
            save_section()
            current_sec_title = clean_text[:60] + "..." if len(clean_text) > 60 else clean_text
            current_sec_content.append(f"<h3 style='color:#004085; border-bottom:1px solid #ccc; padding-bottom:5px; margin-top:20px;'>{clean_text}</h3>")
            in_footnotes = False
            continue

        current_sec_content.append(el)

    save_section()
    print("הספר סודר בצורה מוחלטת עם קו ההערות ותוכן עניינים מדויק לשלום זכר!")

if __name__ == "__main__":
    import_zariz_final_absolute()