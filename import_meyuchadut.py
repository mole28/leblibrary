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

    print("ממיר את קובץ ה-Word ומייצר היררכיית תוכן עניינים...")
    
    with open(docx_path, "rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
        raw_html = result.value

    soup = BeautifulSoup(raw_html, 'html.parser')
    
    # חילוץ כל הערות השוליים למילון ושמירתן לסוף הספר
    footnotes_dict = {}
    for li in soup.find_all('li', id=re.compile(r'^footnote-')):
        fn_id = li['id']
        # הסרת חץ החזרה כדי לשמור על טקסט נקי
        for back_link in li.find_all('a', string='↑'):
            back_link.decompose()
        footnotes_dict[fn_id] = li
        li.extract() # מוציא את ההערה מהטקסט כדי שלא תופיע באמצע
        
    for ol in soup.find_all('ol'):
        if not ol.get_text(strip=True):
            ol.extract()

    # היררכיה כפולה לתוכן העניינים
    chapters_data = []
    current_chapter = None
    current_section = None
    
    def is_chapter(t):
        if t == "פתח דבר": return True
        if re.match(r'^סוגיא\s+[א-ת]{1,2}\s*[-–]', t): return True
        if re.match(r'^(?:נספחים|נפחים)\s+לסוגיא\s+[א-ת]', t): return True
        if re.match(r'^סימן\s+[א-ת]{1,2}\s*[-–]', t): return True
        return False

    def is_section(t):
        if re.match(r'^אות\s+[א-ת]{1,2}\s*[-–]', t): return True
        return False

    for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'div', 'ul', 'ol', 'table']):
        text = tag.get_text(strip=True)
        clean_text = re.sub(r'\s+', ' ', text).strip()
        
        # זיהוי פרק ראשי (יופיע מודגש)
        if len(clean_text) < 150 and is_chapter(clean_text):
            current_chapter = {'title': clean_text, 'sections': []}
            chapters_data.append(current_chapter)
            current_section = {'title': 'פתיחה', 'tags': [tag], 'is_intro': True}
            current_chapter['sections'].append(current_section)
            
        # זיהוי סעיף פנימי - אותיות (יופיע רגיל, לא מודגש)
        elif len(clean_text) < 150 and is_section(clean_text):
            if not current_chapter:
                current_chapter = {'title': "הקדמה", 'sections': []}
                chapters_data.append(current_chapter)
            current_section = {'title': clean_text, 'tags': [tag], 'is_intro': False}
            current_chapter['sections'].append(current_section)
            
        # טקסט רגיל
        else:
            if not current_section:
                current_chapter = {'title': "הקדמה", 'sections': []}
                chapters_data.append(current_chapter)
                current_section = {'title': 'פתיחה', 'tags': [], 'is_intro': True}
                current_chapter['sections'].append(current_section)
            current_section['tags'].append(tag)

    # סידור הסעיפים
    for ch in chapters_data:
        valid_sections = []
        for i, sec in enumerate(ch['sections']):
            if sec.get('is_intro'):
                text_content = "".join(t.get_text(strip=True) for t in sec['tags'][1:])
                if not text_content.strip():
                    if i + 1 < len(ch['sections']):
                        ch['sections'][i+1]['tags'] = sec['tags'] + ch['sections'][i+1]['tags']
                    else:
                        valid_sections.append(sec)
                else:
                    valid_sections.append(sec)
            else:
                valid_sections.append(sec)
        
        if len(valid_sections) == 1:
            valid_sections[0]['title'] = ch['title']
            
        ch['sections'] = valid_sections

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
    # יצירת כל הפרקים והסעיפים של הספר
    for ch_data in chapters_data:
        chapter = Chapter.objects.create(
            book=book,
            title=ch_data['title'][:150],
            order=ch_order
        )
        
        sec_order = 1
        for sec_data in ch_data['sections']:
            sec_html = "".join(str(tag) for tag in sec_data['tags'])
            sec_soup = BeautifulSoup(sec_html, 'html.parser')

            for tag_b in sec_soup.find_all(['strong', 'b']):
                tag_b.unwrap()

            # הערות השוליים כבר לא מוזרקות לכאן! רק הטקסט הרגיל.
            final_content = force_large_css + str(sec_soup)

            Section.objects.create(
                chapter=chapter,
                title=sec_data['title'][:150],
                content=final_content,
                order=sec_order
            )
            sec_order += 1
            
        ch_order += 1

    # ==========================================
    # יצירת פרק מיוחד בסוף הספר לרכז את כל ההערות
    # ==========================================
    if footnotes_dict:
        # קו עבה, מודגש וברור המפריד בין הספר להערות
        separator_html = "<hr style='border: 0; border-top: 5px solid #2c3e50; margin: 60px 0 40px 0; opacity: 1;'>"
        title_html = "<h2 style='text-align: center; color: #d4af37; margin-bottom: 30px; font-weight: bold;'>הערות שוליים</h2>"

        all_fns_html = "<ol style='font-size: 1.1em; line-height: 1.8;'>"
        # הוספת כל ההערות לפי הסדר שלהן
        for fn_id, li_tag in footnotes_dict.items():
            all_fns_html += str(li_tag)
        all_fns_html += "</ol>"

        fn_final_content = force_large_css + separator_html + title_html + all_fns_html

        fn_chapter = Chapter.objects.create(
            book=book,
            title="הערות שוליים",
            order=ch_order
        )

        Section.objects.create(
            chapter=fn_chapter,
            title="ריכוז הערות",
            content=fn_final_content,
            order=1
        )

    print(f"הספר '{book_title}' יובא בהצלחה! כל הערות השוליים רוכזו בסוף הספר.")

if __name__ == "__main__":
    import_meyuchadut_book()