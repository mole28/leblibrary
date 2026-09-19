import os
import django
import mammoth
from bs4 import BeautifulSoup
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from articles.models import Section

def clean_for_match(text):
    if not text: return ""
    text = re.sub(r'\[\d+\]', '', text)
    text = re.sub(r'\W+', '', text)
    return text

def is_match(t1, t2):
    if not t1 or not t2: return False
    if t1 in t2 or t2 in t1: return True
    if len(t1) >= 20 and len(t2) >= 20 and t1[:20] == t2[:20]: return True
    if len(t1) >= 20 and len(t2) >= 20 and t1[-20:] == t2[-20:]: return True
    return False

def inject_by_text_matching():
    docx_path = 'gidrei_2.docx'
    if not os.path.exists(docx_path):
        print(f"שגיאה: הקובץ {docx_path} לא נמצא.")
        return

    print("שואב תוכן והערות שוליים מקובץ הוורד המלא...")
    with open(docx_path, "rb") as docx_file:
        result = mammoth.convert_to_html(docx_file)
        html = result.value

    soup = BeautifulSoup(html, 'html.parser')
    
    footnotes_dict = {}
    for li in soup.find_all('li', id=re.compile(r'^footnote-')):
        fn_id = li['id']
        for back_link in li.find_all('a', string='↑'):
            back_link.decompose()
        # ביטול פסקאות שגורמות לשבירת שורות
        for p in li.find_all('p'):
            p.unwrap()
        footnotes_dict[fn_id] = li
        li.extract()

    for ol in soup.find_all('ol'):
        if not ol.get_text(strip=True):
            ol.extract()
            
    mammoth_elements = soup.find_all(['p', 'h1', 'h2', 'h3', 'ul', 'ol', 'table'])
    
    db_sections = Section.objects.filter(chapter__book_id=45).order_by('chapter__order', 'order')

    force_large_css = "<style>sup, sub, .footnote-ref { font-size: 0.9em !important; font-weight: bold !important; }</style>"
    
    mammoth_index = 0
    updated_count = 0
    
    for db_sec in db_sections:
        db_soup = BeautifulSoup(db_sec.content, 'html.parser')
        new_content_elements = []
        used_fns = {}
        
        for db_el in db_soup.find_all(['p', 'div', 'ul', 'ol', 'table']):
            raw_db_text = db_el.get_text()
            clean_db = clean_for_match(raw_db_text)
            
            if len(clean_db) < 5:
                new_content_elements.append(str(db_el))
                continue
                
            match_found = False
            for i in range(mammoth_index, min(mammoth_index + 40, len(mammoth_elements))):
                mam_el = mammoth_elements[i]
                clean_mam = clean_for_match(mam_el.get_text())
                
                if is_match(clean_db, clean_mam):
                    for a in mam_el.find_all('a', id=re.compile(r'^footnote-ref-')):
                        clean_num = a.get_text(strip=True).replace('[', '').replace(']', '')
                        a.string = f"[{clean_num}]"
                        a['class'] = a.get('class', []) + ['footnote-ref']
                        fn_id = f"footnote-{clean_num}"
                        if fn_id in footnotes_dict:
                            used_fns[fn_id] = footnotes_dict[fn_id]
                            
                    new_content_elements.append(str(mam_el))
                    mammoth_index = i + 1
                    match_found = True
                    break
            
            if not match_found:
                new_content_elements.append(str(db_el))

        html_content = force_large_css + "".join(new_content_elements)
        
        if used_fns:
            separator = "<hr style='border: 0; border-top: 3px solid #2c3e50; margin: 40px 0 30px 0;'>"
            title = "<h3 style='text-align: center; color: #d4af37; margin-bottom: 20px; font-weight: bold;'>הערות</h3>"
            
            # יצירת הקונטיינר בעיצוב המדויק של האתר שלך (שומר על המספור המקורי!)
            container = "<div class='custom-footnotes-container' style='font-size: 1.1em; line-height: 1.8; margin-right: 10px;'>"
            
            for fn_id in sorted(used_fns.keys(), key=lambda x: int(x.replace('footnote-', ''))):
                clean_num = fn_id.replace('footnote-', '')
                li_tag = used_fns[fn_id]
                inner_html = "".join([str(c) for c in li_tag.contents])
                
                container += f"""
                <div id="{fn_id}" style="margin-bottom: 15px; display: flex; align-items: flex-start;">
                    <span style="font-weight:bold; color:#d4af37; min-width: 35px; flex-shrink: 0;">{clean_num}.</span>
                    <span style="flex-grow: 1;">{inner_html}</span>
                </div>
                """
            
            container += "</div>"
            html_content += separator + title + container
            
        db_sec.content = html_content
        db_sec.save()
        updated_count += 1

    print(f"\nסיום בהצלחה! {updated_count} סעיפים נסרקו ועודכנו עם הערות שוליים במספור מדויק, ללא פגיעה בקישורים.")

if __name__ == '__main__':
    inject_by_text_matching()