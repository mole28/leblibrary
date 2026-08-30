import os
import django
import re
import sys

# בדיקה שהספרייה לקריאת וורד מותקנת
try:
    import mammoth
except ImportError:
    print("שגיאה: חבילת mammoth לא מותקנת. אנא הרץ בטרמינל: pip install mammoth")
    sys.exit(1)

from bs4 import BeautifulSoup

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_meyuchadut_book():
    book_title = "מיוחדות המילה בישראל"
    
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
    
    # הגדרת שם המחבר
    for field in ['author', 'writer', 'creator']:
        if hasattr(book, field):
            setattr(book, field, "משה לייבוביץ")
            book.save()
            break

    docx_path = "meyuhad.docx"
    if not os.path.exists(docx_path):
        print(f"שגיאה: הקובץ {docx_path} לא נמצא בתיקייה!")
        return

    print("ממיר את קובץ ה-Word לנתונים נקיים...")
    
    with open(docx_path, "rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
        raw_html = result.value

    soup = BeautifulSoup(raw_html, 'html.parser')
    
    footnotes_dict = {}
    for li in soup.find_all('li', id=re.compile(r'^footnote-')):
        fn_id = li['id']
        for back_link in li.find_all('a', string='↑'):
            back_link.decompose()
        footnotes_dict[fn_id] = li
        li.extract()
        
    for ol in soup.find_all('ol'):
        if not ol.get_text(strip=True):
            ol.extract()

    chapters_data = []
    current_title = "הקדמה"
    current_content = []
    
    def is_heading(text_to_check):
        t = text_to_check.strip()
        if t == "פתח דבר": return True
        if re.match(r'^סוגיא\s+[א-ת]{1,2}\s*[-–]', t): return True
        if re.match(r'^(?:נספחים|נפחים)\s+לסוגיא\s+[א-ת]', t): return True
        if re.match(r'^סימן\s+[א-ת]{1,2}\s*[-–]', t): return True
        return False

    for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'div', 'ul', 'ol', 'table']):
        text = tag.get_text(strip=True)
        clean_text = re.sub(r'\s+', ' ', text).strip()
        
        if len(clean_text) < 100 and is_heading(clean_text):
            if current_content:
                chapters_data.append((current_title, current_content))
            current_title = clean_text
            current_content = [tag]
        else:
            current_content.append(tag)
            
    if current_content:
        chapters_data.append((current_title, current_content))

    # עיצוב מתוקן ומדויק - גודל נוח (0.9em), מודגש, ללא שבירת מרווח שורות
    force_large_css = """
    <style>
    sup, sub, .MsoFootnoteReference, a[href*="ftn"], a[href*="footnote"], a[href*="ref"] {
        font-size: 0.9em !important;
        font-weight: bold !important;
        vertical-align: super !important;
        line-height: 0;
    }
    </style>
    """

    ch_order = 1
    for ch_title, ch_tags in chapters_data:
        ch_html = "".join(str(tag) for tag in ch_tags)
        ch_soup = BeautifulSoup(ch_html, 'html.parser')
        
        chapter_footnotes_html = ""
        refs = ch_soup.find_all('a', href=re.compile(r'^#footnote-'))
        if refs:
            chapter_footnotes_html += "<hr class='footnotes-divider'><ol>"
            seen_fns = set()
            for ref in refs:
                fn_target = ref['href'].replace('#', '')
                if fn_target in footnotes_dict and fn_target not in seen_fns:
                    chapter_footnotes_html += str(footnotes_dict[fn_target])
                    seen_fns.add(fn_target)
            chapter_footnotes_html += "</ol>"

        for tag_b in ch_soup.find_all(['strong', 'b']):
            tag_b.unwrap()

        final_content = force_large_css + str(ch_soup) + chapter_footnotes_html

        chapter = Chapter.objects.create(
            book=book,
            title=ch_title[:150],
            order=ch_order
        )

        Section.objects.create(
            chapter=chapter,
            title=ch_title[:150],
            content=final_content,
            order=1
        )
        
        ch_order += 1

    print(f"הספר '{book_title}' יובא בהצלחה עם עיצוב הערות שוליים מתוקן!")

if __name__ == "__main__":
    import_meyuchadut_book()