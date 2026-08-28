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
    
    # הסרת סקריפטים וסטיילים גולמיים בלבד
    for element in soup(["script", "style", "meta", "link", "form", "input", "button", "textarea", "select"]):
        element.decompose()

    # טיפול רדיקלי בשורות סוררות כמו "סימן רכט - רל" שמתחזות לכותרות
    for tag in soup.find_all(True):
        text_content = tag.get_text(strip=True)
        if text_content.startswith("סימן") and ("הכורת הברית" in text_content or "אות ברית" in text_content or len(text_content) > 35):
            # הפיכת התגית לפסקה רגילה וניקוי כל סטייל שגורם לה להיראות כמו כותרת
            tag.name = 'p'
            tag.attrs = {} # מחיקת כל ה-classes וה-styles המעוותים

    full_text = str(soup)

    # דילוג על תוכן העניינים בתחילת המסמך ומציאת הפתח דבר האמיתי
    matches_pd = [m.start() for m in re.finditer(r'פתח\s+דבר', full_text, re.IGNORECASE)]
    if len(matches_pd) > 1:
        target_idx = matches_pd[1]
        for idx in matches_pd[1:]:
            snippet = full_text[idx:idx+500]
            if "ספר זה" in snippet or "עוסק בעיקר" in snippet:
                target_idx = idx
                break
        full_text = full_text[target_idx:]
    elif len(matches_pd) == 1:
        full_text = full_text[matches_pd[0]:]

    # חילוץ ההקדמה שמתחילה מ"פתח דבר" ועד הסימן האמיתי הראשון
    siman_start_match = re.search(r'(סימן\s+[א-ת]{1,3}\s*[–-]\s*[^<\n]+)', full_text, re.IGNORECASE)
    
    if siman_start_match:
        intro_end_idx = siman_start_match.start()
        intro_content = full_text[:intro_end_idx]
        simans_text = full_text[intro_end_idx:]
    else:
        intro_content = full_text
        simans_text = ""

    # ניקוי הדגשות מפרק המבוא
    intro_soup = BeautifulSoup(intro_content, 'html.parser')
    for tag_b in intro_soup.find_all(['strong', 'b']):
        tag_b.unwrap()

    # יצירת פרק מבוא
    intro_ch = Chapter.objects.create(book=book, title="פתח דבר והקדמה", order=1)
    Section.objects.create(
        chapter=intro_ch,
        title="פתח דבר",
        content=str(intro_soup),
        order=1
    )

    # זיהוי הסימנים האמיתיים בלבד: חייבים להתחיל במילה סימן, אות קצרה, מקף אמיתי וכותרת קצרה (ללא אזכור של הכורת הברית וכדומה)
    siman_pattern = re.compile(r'(סימן\s+[א-ת]{1,3}\s*[–-]\s*[^<\n]{2,30})', re.IGNORECASE)
    matches = list(siman_pattern.finditer(simans_text))

    ch_order = 2
    for idx, match in enumerate(matches):
        siman_title = match.group(1).strip()
        
        # הגנה נוספת: אם בטעות נפלה שורה שקרית, נדלג עליה מיד
        if "הכורת הברית" in siman_title or "אות ברית" in siman_title:
            continue

        start_pos = match.start()
        end_pos = matches[idx + 1].start() if idx + 1 < len(matches) else len(simans_text)
        siman_body_html = simans_text[start_pos:end_pos]

        chapter = Chapter.objects.create(
            book=book,
            title=siman_title,
            order=ch_order
        )

        siman_soup = BeautifulSoup(siman_body_html, 'html.parser')

        # איסוף הערות שוליים
        all_footnotes = siman_soup.find_all(lambda tag: tag.has_attr('id') and ('ftn' in tag['id'] or 'footnote' in tag['id']))
        
        cleaned_footnotes = []
        for fn in all_footnotes:
            for b_tag in fn.find_all(['strong', 'b']):
                b_tag.unwrap()
            cleaned_footnotes.append(str(fn))
            fn.decompose()

        footnotes_html = "".join(cleaned_footnotes)

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
            sections_data.append((siman_title, str(siman_soup)))

        for sec_order, (sec_title, sec_content) in enumerate(sections_data, start=1):
            sec_soup_obj = BeautifulSoup(sec_content, 'html.parser')
            
            for tag_b in sec_soup_obj.find_all(['strong', 'b']):
                tag_b.unwrap()

            final_sec_content = str(sec_soup_obj) + "<hr class='footnotes-divider'>" + footnotes_html
            
            Section.objects.create(
                chapter=chapter,
                title=sec_title[:150],
                content=final_sec_content,
                order=sec_order
            )

        ch_order += 1

    print("הספר יובא בהצלחה: שורות הערה שגויות נוקו לחלוטין מהכותרות ומהתוכן!")

if __name__ == "__main__":
    import_zmani_book()