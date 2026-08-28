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

    # 1. חיתוך אגרסיבי: הסרת כל מה שמופיע לפני המילים "פתח דבר" (מוחק עמודי שער ומכתבי ברכה קודמים)
    pesah_davar_match = re.search(r'פתח\s+דבר', full_text, re.IGNORECASE)
    if pesah_davar_match:
        full_text = full_text[pesah_davar_match.start():]

    # 2. חילוץ ההקדמה שמתחילה בדיוק מ"פתח דבר" ועד הסימן הראשון
    siman_start_match = re.search(r'(סימן\s+[א-ת]{1,3}\s*[–-]\s*[^<\n]+)', full_text, re.IGNORECASE)
    
    if siman_start_match:
        intro_end_idx = siman_start_match.start()
        intro_content = full_text[:intro_end_idx]
        simans_text = full_text[intro_end_idx:]
    else:
        intro_content = full_text
        simans_text = ""

    # יצירת פרק מבוא שמתחיל נקי מ"פתח דבר"
    intro_ch = Chapter.objects.create(book=book, title="פתח דבר והקדמה", order=1)
    Section.objects.create(
        chapter=intro_ch,
        title="פתח דבר",
        content=intro_content,
        order=1
    )

    # 3. זיהוי מדויק של הסימנים (לדוגמה: סימן א – ...)
    siman_pattern = re.compile(r'(סימן\s+[א-ת]{1,3}\s*[–-]\s*[^<\n]+)', re.IGNORECASE)
    matches = list(siman_pattern.finditer(simans_text))

    ch_order = 2
    for idx, match in enumerate(matches):
        siman_title = match.group(1).strip()
        start_pos = match.start()
        end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(simans_text)
        siman_body_html = simans_text[start_pos:end_pos]

        # יצירת פרק עבור כל סימן
        chapter = Chapter.objects.create(
            book=book,
            title=siman_title,
            order=ch_order
        )

        # 4. ניתוח חכם של הסעיפים (האותיות א., ב., ג. וכו') תחת הסימן
        siman_soup = BeautifulSoup(siman_body_html, 'html.parser')
        sections_data = []
        current_sec_title = "הקדמה לסימן"
        current_sec_content = []

        sec_heading_regex = re.compile(r'^\s*([א-טכסרקדשת]{1,3})\.\s+(.*)$')

        paragraphs = siman_soup.find_all(['p', 'div', 'h2', 'h3', 'h4'], recursive=True)
        if not paragraphs:
            paragraphs = [siman_soup]

        found_first_section = False
        intro_to_siman_content = []

        for p in paragraphs:
            text = p.get_text(strip=True)
            match_sec = sec_heading_regex.match(text)
            
            if match_sec and len(text) < 100 and not text.startswith("סימן"):
                if found_first_section:
                    sections_data.append((current_sec_title, "".join(str(e) for e in current_sec_content)))
                    current_sec_content = []
                else:
                    if intro_to_siman_content:
                        sections_data.append(("הקדמה לסימן", "".join(str(e) for e in intro_to_siman_content)))
                        intro_to_siman_content = []
                
                current_sec_title = text
                found_first_section = True
                current_sec_content.append(p)
            else:
                if not found_first_section:
                    intro_to_siman_content.append(p)
                else:
                    current_sec_content.append(p)

        if current_sec_content:
            sections_data.append((current_sec_title, "".join(str(e) for e in current_sec_content)))
        elif intro_to_siman_content:
            sections_data.append((siman_title, "".join(str(e) for e in intro_to_siman_content)))

        if not sections_data:
            sections_data.append((siman_title, siman_body_html))

        # שמירת הסעיפים תחת הפרק
        for sec_order, (sec_title, sec_content) in enumerate(sections_data, start=1):
            Section.objects.create(
                chapter=chapter,
                title=sec_title[:150],
                content=sec_content,
                order=sec_order
            )

        ch_order += 1

    print("הספר יובא בהצלחה החל מפתח דבר ועד הסוף!")

if __name__ == "__main__":
    import_zmani_book()