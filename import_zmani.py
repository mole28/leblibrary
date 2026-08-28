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
    
    # ניקוי מלא של ספרים קודמים
    existing_books = Book.objects.filter(title=book_title)
    if existing_books.exists():
        for b in existing_books:
            chapters = b.chapters.all()
            for ch in chapters:
                Section.objects.filter(chapter=ch).delete()
            chapters.delete()
        existing_books.delete()
        print("נמחקו ספרים קודמים.")

    book = Book.objects.create(title=book_title)
    print(f"נוצר ספר חדש: {book.title}")

    html_file_path = "zmani_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, 'html.parser')
    
    # הסרת סקריפטים וסטיילים
    for element in soup(["script", "style", "meta", "link", "form", "input", "button", "textarea", "select"]):
        element.decompose()

    full_text = str(soup)

    # מציאת הפתח דבר האמיתי ותחילת הספר
    matches_pd = [m.start() for m in re.finditer(r'פתח\s+דבר', full_text, re.IGNORECASE)]
    toc_html = ""
    book_content_html = full_text

    if len(matches_pd) > 1:
        target_idx = matches_pd[1]
        for idx in matches_pd[1:]:
            snippet = full_text[idx:idx+500]
            if "ספר זה" in snippet or "עוסק בעיקר" in snippet:
                target_idx = idx
                break
        toc_html = full_text[:target_idx]
        book_content_html = full_text[target_idx:]

    # חילוץ ההקדמה שעד הסימן הראשון
    siman_start_match = re.search(r'(סימן\s+[א-ת]{1,3}\s*[–-]\s*[^<\n]+)', book_content_html, re.IGNORECASE)
    if siman_start_match:
        intro_end_idx = siman_start_match.start()
        intro_content = book_content_html[:intro_end_idx]
        simans_text = book_content_html[intro_end_idx:]
    else:
        intro_content = book_content_html
        simans_text = ""

    # יצירת פרק מבוא (פתח דבר)
    intro_soup = BeautifulSoup(intro_content, 'html.parser')
    for tag_b in intro_soup.find_all(['strong', 'b']):
        tag_b.unwrap()

    intro_ch = Chapter.objects.create(book=book, title="פתח דבר והקדמה", order=1)
    Section.objects.create(
        chapter=intro_ch,
        title="פתח דבר",
        content=str(intro_soup),
        order=1
    )

    # חלוקה לסימנים מתוך גוף הספר
    siman_pattern = re.compile(r'(סימן\s+[א-ת]{1,3}\s*[–-]\s*[^<\n]{2,40})', re.IGNORECASE)
    matches = list(siman_pattern.finditer(simans_text))

    ch_order = 2
    for idx, match in enumerate(matches):
        siman_title = match.group(1).strip()
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

        # זיהוי מדויק של כל האותיות האמיתיות בגוף הטקסט מתחילת האות "א" השנייה או לפי רצף כותרות הסעיפים
        sec_heading_regex = re.compile(r'^\s*([א-ת]{1,3})\.\s+(.*)$')
        paragraphs = siman_soup.find_all(['p', 'div', 'h2', 'h3', 'h4'], recursive=True)
        if not paragraphs:
            paragraphs = [siman_soup]

        # איסוף כל כותרות הסעיפים הקיימות בסימן הזה בפועל
        all_headings = []
        for p_idx, p in enumerate(paragraphs):
            text = p.get_text(strip=True)
            m = sec_heading_regex.match(text)
            if m and len(text) < 150 and not text.startswith("סימן"):
                all_headings.append((p_idx, m.group(1), text, p))

        # נזהה איפה מתחיל גוף הטקסט האמיתי (נבטל את רשימת הסיכום הראשונית אם ישנה ע"י מעבר אל מופע האותיות שאחרי הסיכום)
        body_start_p_idx = 0
        if len(all_headings) > 3:
            seen_letters = set()
            for h in all_headings:
                let = h[1]
                if let in seen_letters:
                    body_start_p_idx = h[0]
                    break
                seen_letters.add(let)

        sections_data = []
        current_sec_title = None
        current_sec_content = []

        for p_idx, p in enumerate(paragraphs):
            text = p.get_text(strip=True)
            match_sec = sec_heading_regex.match(text)
            
            is_valid = (match_sec and len(text) < 150 and not text.startswith("סימן") and p_idx >= body_start_p_idx)
            if match_sec and ("הדינים העולים" in text or "סיכום" in text) and p_idx > body_start_p_idx / 2:
                is_valid = True

            if is_valid:
                if current_sec_title:
                    sections_data.append((current_sec_title, "".join(str(e) for e in current_sec_content)))
                    current_sec_content = []
                current_sec_title = text
                current_sec_content.append(p)
            else:
                if current_sec_title:
                    current_sec_content.append(p)

        if current_sec_title and current_sec_content:
            sections_data.append((current_sec_title, "".join(str(e) for e in current_sec_content)))

        # אם לא נמצאו סעיפים, ניקח את כל גוף הסימן כסעיף יחיד
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

    print("הספר יובא בהצלחה מרבית!")

if __name__ == "__main__":
    import_zmani_book()