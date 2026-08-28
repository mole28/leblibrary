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
    
    # ניקוי מלא של ספרים כפולים קודמים
    existing_books = Book.objects.filter(title=book_title)
    if existing_books.exists():
        for b in existing_books:
            chapters = b.chapters.all()
            for ch in chapters:
                Section.objects.filter(chapter=ch).delete()
            chapters.delete()
        existing_books.delete()
        print("נמחקו ספרים כפולים קודמים.")

    # יצירת ספר נקי ויחיד
    book = Book.objects.create(title=book_title)
    print(f"נוצר ספר נקי חדש: {book.title} (מזהה: {book.id})")

    html_file_path = "zmani_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, 'html.parser')
    
    # הסרת אלמנטים מסוכנים
    for element in soup(["script", "style", "meta", "link", "form", "input", "button", "textarea", "select"]):
        element.decompose()

    # שמירת מזהים ועוגנים לניווט
    for tag in soup.find_all(True):
        allowed_attrs = {}
        if 'id' in tag.attrs:
            allowed_attrs['id'] = tag['id']
        if 'name' in tag.attrs:
            allowed_attrs['name'] = tag['name']
        if 'href' in tag.attrs:
            allowed_attrs['href'] = tag['href']
        tag.attrs = allowed_attrs

    full_text = str(soup)

    # 1. חילוץ ההקדמה ופתח דבר שמופיעים לפני הסימן הראשון
    siman_start_match = re.search(r'(סימן\s+א\s*[–-]\s*[^<\n]+)', full_text, re.IGNORECASE)
    
    if siman_start_match:
        intro_end_idx = siman_start_match.start()
        intro_content = full_text[:intro_end_idx]
        simans_text = full_text[intro_end_idx:]
    else:
        intro_content = full_text
        simans_text = ""

    # יצירת פרק מבוא (פתח דבר והקדמה)
    intro_ch = Chapter.objects.create(book=book, title="פתח דבר והקדמה", order=1)
    Section.objects.create(
        chapter=intro_ch,
        title="פתח דבר",
        content=intro_content,
        order=1
    )

    # 2. זיהוי מדויק של הסימנים (לדוגמה: סימן א – ...)
    siman_pattern = re.compile(r'(סימן\s+[א-ת\']{1,4}\s*[–-]\s*[^<\n]+)', re.IGNORECASE)
    matches = list(siman_pattern.finditer(simans_text))

    ch_order = 2
    for idx, match in enumerate(matches):
        siman_title = match.group(1).strip()
        start_pos = match.start()
        end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(simans_text)
        siman_body = simans_text[start_pos:end_pos]

        # יצירת פרק עבור כל סימן
        chapter = Chapter.objects.create(
            book=book,
            title=siman_title,
            order=ch_order
        )

        # 3. פיצול פנימי של הסימן לסעיפים לפי אותיות (א., ב., ג. וכו')
        sub_pattern = re.compile(r'((?:<[^>]+>)*\s*([א-ת])\.\s+([^<\n]+)(?:</[^>]+>)*)', re.UNICODE)
        sub_matches = list(sub_pattern.finditer(siman_body))

        if not sub_matches:
            # אם אין אותיות פנימיות, נכניס את כל הסימן כסעיף יחיד
            Section.objects.create(
                chapter=chapter,
                title=siman_title,
                content=siman_body,
                order=1
            )
        else:
            first_sub_start = sub_matches[0].start()
            siman_intro = siman_body[:first_sub_start]
            
            sec_order = 1
            if siman_intro.strip():
                Section.objects.create(
                    chapter=chapter,
                    title="הקדמה לסימן",
                    content=siman_intro,
                    order=sec_order
                )
                sec_order += 1

            for sub_idx, sub_match in enumerate(sub_matches):
                sub_start = sub_match.start()
                sub_end = sub_matches[sub_idx + 1].start() if sub_idx + 1 < len(sub_matches) else len(siman_body)
                sub_body = siman_body[sub_start:sub_end]
                
                letter = sub_match.group(2)
                desc = sub_match.group(3).strip()
                sec_title = f"{letter}. {desc}"[:120]

                Section.objects.create(
                    chapter=chapter,
                    title=sec_title,
                    content=sub_body,
                    order=sec_order
                )
                sec_order += 1

        ch_order += 1

    print("הספר יובא בהצלחה מלאה ובמבנה מדויק!")

if __name__ == "__main__":
    import_zmani_book()