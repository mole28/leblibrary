import os
import django
import mammoth
from bs4 import BeautifulSoup
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from articles.models import Section

def update_from_word():
    docx_path = 'gidrei_2.docx'
    if not os.path.exists(docx_path):
        print(f"שגיאה: הקובץ {docx_path} לא נמצא.")
        return

    print("שואב תוכן והערות שוליים מקובץ הוורד המלא...")
    with open(docx_path, "rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
        html = result.value

    soup = BeautifulSoup(html, 'html.parser')
    
    # חילוץ כל ההערות מהתחתית
    footnotes_dict = {}
    for li in soup.find_all('li', id=re.compile(r'^footnote-')):
        fn_id = li['id']
        for back_link in li.find_all('a', string='↑'):
            back_link.decompose()
        footnotes_dict[fn_id] = li
        li.extract() # הסרה מהטקסט הכללי

    for ol in soup.find_all('ol'):
        if not ol.get_text(strip=True):
            ol.extract()
            
    force_large_css = "<style>sup, sub, .footnote-ref { font-size: 0.9em !important; font-weight: bold !important; }</style>"
    for tag_b in soup.find_all(['strong', 'b']):
        tag_b.unwrap()

    # פירוק הוורד לסעיפים לפי אותם תנאים של הסקריפט המקורי
    section_pattern = re.compile(r'^([א-ת]{1,2})\.\s+(.*)')
    excluded_substrings = [
        "משכ שמזה שהשווה", "הוא כתב שאין התלמוד", "לדבריו עולה שאנו", "לא מובן מה הראיה", 
        "שברכת חתנים שייכת", "שפח נקראים דווקא", "תוקף הפח שייך", "במקום שאנו אומרים", 
        "כפי שראינו יש הרבה", "הכלל שאין אומרים סבל", "אם דעתו שרק כשמברכים", "למה כאשר אין יין", 
        "האם במקום שנוהגים לברך", "השוע כתב הדברים", "בבי ובשוע לא הוסיף", "בשביל הפח מספיק", 
        "דווקא אדם חדש", "אצ שהחתן ירבה", "ניתן לברך אף", "האדם נחשב פח", "בשבת, יוט (אף יוט", 
        "כפי שהתבאר למעלה", "מניין לחדש שיש", "דווקא פנים חדשות הגורמים", "בשבת וביוט מברכים", 
        "מספיק אדם אחד בשביל", "לנישואי אלמנה או גרושה", "אסור מדרבנן לשאת אישה"
    ]

    word_sections = []
    current_section_html = []
    is_in_intro = False
    
    for el in soup.find_all(['h1', 'h2', 'h3', 'p', 'ul', 'ol', 'table']):
        text = el.get_text(strip=True)
        clean_text = text.replace('"', '').replace("'", "").replace("״", "").replace("׳", "")
        
        if text.startswith("סימן ") or text in ["פתח דבר", "הקדמה", "קונטרס ראשון גדרי שליחות", "קונטרס שני גדר בפני נכתב ובפני נחתם", "דינים העולים מהספר"]:
            if current_section_html:
                word_sections.append(current_section_html)
                current_section_html = []
            is_in_intro = True
            continue
            
        match = section_pattern.match(text)
        is_explicitly_excluded = any(sub in clean_text for sub in excluded_substrings)
        words_count = len(text.split())
        is_valid_heading = match and (words_count <= 14) and not is_explicitly_excluded

        if is_valid_heading:
            if current_section_html:
                word_sections.append(current_section_html)
            current_section_html = [str(el)]
            is_in_intro = False
        else:
            if is_in_intro and not current_section_html:
                current_section_html = [str(el)]
            else:
                current_section_html.append(str(el))

    if current_section_html:
        word_sections.append(current_section_html)

    print(f"נמצאו {len(word_sections)} סעיפים בוורד.")

    # שליפת 58 הסעיפים מהמסד 
    db_sections = list(Section.objects.filter(chapter__book_id=45).order_by('chapter__order', 'order'))
    print(f"נמצאו {len(db_sections)} סעיפים במסד הנתונים.")

    if len(word_sections) != len(db_sections):
         print("אזהרה: מספר הסעיפים בוורד לא תואם למספר הסעיפים באתר! התהליך נעצר כדי לא לשבור קישורים.")
         return

    print("מתחיל עדכון: מזריק את תוכן הוורד עם ההערות לתוך המסד הקיים...")
    
    updated_count = 0
    for i, db_sec in enumerate(db_sections):
        # המרת התוכן של הסעיף הספציפי ל-HTML מעוצב
        raw_html = "".join(word_sections[i])
        sec_soup = BeautifulSoup(raw_html, 'html.parser')
        
        used_fns = {}
        
        # סידור ההפניות (המספרים הלחיצים בתוך הטקסט)
        for a in sec_soup.find_all('a', id=re.compile(r'^footnote-ref-')):
            clean_num = a.get_text(strip=True).replace('[', '').replace(']', '')
            a.string = f"[{clean_num}]"
            a['class'] = a.get('class', []) + ['footnote-ref']
            
            fn_id = f"footnote-{clean_num}"
            if fn_id in footnotes_dict:
                used_fns[fn_id] = footnotes_dict[fn_id]

        html_content = force_large_css + str(sec_soup)

        # הוספת בלוק ההערות רק אם הסעיף מכיל הערות
        if used_fns:
            separator = "<hr style='border: 0; border-top: 3px solid #2c3e50; margin: 40px 0 30px 0;'>"
            title = "<h3 style='text-align: center; color: #d4af37; margin-bottom: 20px; font-weight: bold;'>הערות</h3>"
            fn_list = "<ol style='font-size: 1.1em; line-height: 1.8;'>"
            
            # מיון לפי המספר כדי שיודפסו לפי הסדר
            for fn_id in sorted(used_fns.keys(), key=lambda x: int(x.replace('footnote-', ''))):
                 fn_list += str(used_fns[fn_id])
            fn_list += "</ol>"
            
            html_content += separator + title + fn_list
            
        db_sec.content = html_content
        db_sec.save()
        updated_count += 1
        
    print(f"\nסיום בהצלחה! {updated_count} סעיפים עודכנו, וה-ID שלהם נשמר.")

if __name__ == '__main__':
    update_from_word()