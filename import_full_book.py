import os
import django
import mammoth
from bs4 import BeautifulSoup
import re

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

# 1. שליפה או יצירת הספר בכתובת 84
book, _ = Book.objects.get_or_create(
    id=84,
    defaults={
        'title': 'זמני המילה וברכותיה',
        'author': 'משה לייבוביץ',
        'price': 50,
        'stock': 100,
        'is_for_sale': True,
        'order': 1
    }
)

# ניקוי כל הפרקים והסעיפים הקודמים כדי להתחיל נקי לחלוטין
Chapter.objects.filter(book=book).delete()

docx_path = 'zmani.docx'
if not os.path.exists(docx_path):
    print(f"שגיאה: הקובץ {docx_path} לא נמצא בתיקיית הפרויקט!")
else:
    print("מעבד את קובץ הוורד בדיוק לפי כותרת 2 (מודגש) וכותרת 3 (לא מודגש)...")
    with open(docx_path, "rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
        html = result.value

    soup = BeautifulSoup(html, 'html.parser')
    
    # חילוץ הערות שוליים
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

    for tag_b in soup.find_all(['strong', 'b']):
        tag_b.unwrap()

    ch_order = 0
    sec_order = 0
    current_chapter = None
    current_section = None
    section_content = []

    # רשימת כל האלמנטים בגוף המסמך
    elements = soup.find_all(['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'table'])

    # יצירת פרק ברירת מחדל התחלתי למקרה שהטקסט מתחיל לפני כותרת
    ch_order += 1
    current_chapter = Chapter.objects.create(book=book, title='פתח דבר והקדמה', order=ch_order)
    sec_order += 1
    current_section = Section.objects.create(chapter=current_chapter, title='פתח דבר', content='', order=sec_order)

    for el in elements:
        text = el.get_text(strip=True)
        
        if el.name == 'h2':  # כותרת 2 בוורד -> פרק חדש (Chapter - מודגש בתוכן העניינים)
            # שמירת התוכן של הסעיף הקודם
            if current_section and section_content:
                current_section.content = force_large_css + ''.join(section_content)
                current_section.save()
                section_content = []

            ch_order += 1
            sec_order = 0
            current_chapter = Chapter.objects.create(
                book=book,
                title=text if text else f"פרק {ch_order}",
                order=ch_order
            )
            sec_order += 1
            current_section = Section.objects.create(
                chapter=current_chapter,
                title=text if text else f"סעיף {sec_order}",
                content='',
                order=sec_order
            )
            
        elif el.name == 'h3':  # כותרת 3 בוורד -> סעיף חדש תחת הפרק הנוכחי (Section - לא מודגש בתוכן העניינים)
            # שמירת התוכן של הסעיף הקודם
            if current_section and section_content:
                current_section.content = force_large_css + ''.join(section_content)
                current_section.save()
                section_content = []

            if not current_chapter:
                ch_order += 1
                current_chapter = Chapter.objects.create(book=book, title='כללי', order=ch_order)
            
            sec_order += 1
            current_section = Section.objects.create(
                chapter=current_chapter,
                title=text if text else f"סעיף {sec_order}",
                content='',
                order=sec_order
            )
        else:
            if not current_chapter:
                ch_order += 1
                current_chapter = Chapter.objects.create(book=book, title='פתח דבר', order=ch_order)
                sec_order += 1
                current_section = Section.objects.create(chapter=current_chapter, title='פתח דבר', content='', order=sec_order)
            
            if text or el.name == 'table':
                section_content.append(str(el))

    # שמירת הסעיף האחרון
    if current_section and section_content:
        current_section.content = force_large_css + ''.join(section_content)
        current_section.save()

    # הוספת אזור ההערות בסוף הסעיף האחרון
    if current_section and footnotes_dict:
        separator_html = "<hr style='border: 0; border-top: 5px solid #2c3e50; margin: 50px 0 30px 0; opacity: 1;'>"
        title_html = "<h3 style='text-align: center; color: #d4af37; margin-bottom: 20px; font-weight: bold;'>הערות</h3>"
        all_fns_html = "<ol style='font-size: 1.1em; line-height: 1.8;'>"
        for fn_id, li_tag in footnotes_dict.items():
            all_fns_html += str(li_tag)
        all_fns_html += "</ol>"
        current_section.content += separator_html + title_html + all_fns_html
        current_section.save()

    print("הספר יובא במלואו בדיוק מושלם לפי כותרת 2 וכותרת 3 בוורד!")