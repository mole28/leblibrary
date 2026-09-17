import os
import django
import mammoth
from bs4 import BeautifulSoup
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from articles.models import Section

def inject_footnotes():
    docx_path = 'gidrei_2.docx'
    if not os.path.exists(docx_path):
        print(f"שגיאה: הקובץ {docx_path} לא נמצא.")
        return

    print("שואב הערות שוליים מקובץ הוורד המלא...")
    with open(docx_path, "rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
        html = result.value

    soup = BeautifulSoup(html, 'html.parser')
    
    # מילון לשמירת ההערות
    footnotes_dict = {}
    for li in soup.find_all('li', id=re.compile(r'^footnote-')):
        fn_id = li['id']
        for back_link in li.find_all('a', string='↑'):
            back_link.decompose()
        footnotes_dict[fn_id] = li

    if not footnotes_dict:
        print("לא נמצאו הערות שוליים בקובץ הוורד. ודא שזהו הקובץ הנכון עם ההערות.")
        return
        
    print(f"נשאבו {len(footnotes_dict)} הערות שוליים מקובץ הוורד.")
    print("מתחיל הזרקה זהירה לסעיפים הקיימים באתר (ללא שינוי מבנה או קישורים)...")

    # שליפת כל 58 הסעיפים הקיימים מספר 45 (גדרי החופה)
    db_sections = Section.objects.filter(chapter__book_id=45).order_by('chapter__order', 'order')
    
    force_large_css = "<style>sup, sub, .footnote-ref { font-size: 0.9em !important; font-weight: bold !important; }</style>"
    
    updated_count = 0

    for db_sec in db_sections:
        # בדיקה האם הסעיף מכיל ציון להערת שוליים בתבנית [מספר]
        matches = set(re.findall(r'\[(\d+)\]', db_sec.content))
        
        if matches:
            sec_soup = BeautifulSoup(db_sec.content, 'html.parser')
            used_fns = {}
            
            # הפיכת המספרים הטקסטואליים לקישורים לחיצים בסעיף
            for text_node in sec_soup.find_all(string=re.compile(r'\[\d+\]')):
                # אל תיגע אם זה כבר בתוך קישור או סופרסקריפט
                if text_node.find_parent(['sup', 'a']): continue
                
                new_html = re.sub(
                    r'\[(\d+)\]', 
                    lambda m: f'<sup><a href="#footnote-{m.group(1)}" class="footnote-ref">[{m.group(1)}]</a></sup>', 
                    text_node
                )
                if new_html != text_node:
                    new_soup = BeautifulSoup(new_html, 'html.parser')
                    text_node.replace_with(new_soup)
            
            # איסוף תוכן ההערות השייכות לסעיף זה בלבד
            for match in matches:
                fn_id = f"footnote-{match}"
                if fn_id in footnotes_dict:
                    used_fns[match] = footnotes_dict[fn_id]

            html_content = force_large_css + str(sec_soup)

            # הוספת בלוק ההערות בתחתית הסעיף (רק אם יש הערות)
            if used_fns:
                separator = "<hr style='border: 0; border-top: 3px solid #2c3e50; margin: 40px 0 30px 0;'>"
                title = "<h3 style='text-align: center; color: #d4af37; margin-bottom: 20px; font-weight: bold;'>הערות</h3>"
                fn_list = "<ol style='font-size: 1.1em; line-height: 1.8;'>"
                
                # מיון ההערות לפי המספר שלהן בסעיף
                for num in sorted(used_fns.keys(), key=int):
                    fn_list += str(used_fns[num])
                fn_list += "</ol>"
                
                html_content += separator + title + fn_list

            db_sec.content = html_content
            db_sec.save()
            updated_count += 1
            print(f"הוזרקו הערות לסעיף: {db_sec.title}")

    print(f"\nסיום בהצלחה! {updated_count} סעיפים עודכנו עם הערות שוליים, ללא שינוי במספרי ה-ID של האתר.")

if __name__ == '__main__':
    inject_footnotes()