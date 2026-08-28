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
    
    # עדכון שם המחבר במסד הנתונים
    for field in ['author', 'writer', 'creator']:
        if hasattr(book, field):
            setattr(book, field, "משה לייבוביץ")
            book.save()
            break

    print(f"נוצר ספר חדש: {book.title} מאת משה לייבוביץ")

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
    if len(matches_pd) > 1:
        target_idx = matches_pd[1]
        for idx in matches_pd[1:]:
            snippet = full_text[idx:idx+500]
            if "ספר זה" in snippet or "עוסק בעיקר" in snippet:
                target_idx = idx
                break
        book_content_html = full_text[target_idx:]
    else:
        book_content_html = full_text

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

    # חלוקה לסימנים בלבד
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

        siman_soup = BeautifulSoup(siman_body_html, 'html.parser')

        # הסרת הדגשות מיותרות בגוף הטקסט
        for tag_b in siman_soup.find_all(['strong', 'b']):
            tag_b.unwrap()

        # איסוף הערות שוליים וצרופן בסוף הסימן
        all_footnotes = siman_soup.find_all(lambda tag: tag.has_attr('id') and ('ftn' in tag['id'] or 'footnote' in tag['id']))
        cleaned_footnotes = []
        for fn in all_footnotes:
            cleaned_footnotes.append(str(fn))
            fn.decompose()
        footnotes_html = "".join(cleaned_footnotes)

        # הזרקת סגנון CSS עוצמתי ש מכריח את כל ההפניות להיות גדולות, מודגשות וברורות בלי לפגוע בקישורים
        force_large_css = """
        <style>
        sup, sub, .MsoFootnoteReference, a[href*="ftn"], a[href*="footnote"], a[href*="ref"] {
            font-size: 1.35em !important;
            font-weight: bold !important;
            vertical-align: baseline !important;
        }
        </style>
        """

        final_siman_content = force_large_css + str(siman_soup)
        if footnotes_html:
            final_siman_content += "<hr class='footnotes-divider'>" + footnotes_html

        # יצירת פרק (סימן) יחיד
        chapter = Chapter.objects.create(
            book=book,
            title=siman_title,
            order=ch_order
        )

        # יצירת סעיף יחיד תחת הסימן
        Section.objects.create(
            chapter=chapter,
            title=siman_title,
            content=final_siman_content,
            order=1
        )

        ch_order += 1

    print("הספר יובא בהצלחה: ההפניות הוגדלו באופן מוחלט ושם המחבר עודכן!")

if __name__ == "__main__":
    import_zmani_book()