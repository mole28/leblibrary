import mammoth
from bs4 import BeautifulSoup
import re

print("מעבד את קובץ הוורד המלא...")
with open("zmani.docx", "rb") as docx_file:
    result = mammoth.convert_to_html(docx_file)
    html = result.value

soup = BeautifulSoup(html, 'html.parser')

# חילוץ הערות שוליים בצורה מושלמת בסוף הקובץ
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

# הוספת אזור ההערות בסוף ה-HTML אם קיימות
if footnotes_dict:
    separator_html = "<hr style='border: 0; border-top: 5px solid #2c3e50; margin: 50px 0 30px 0; opacity: 1;'>"
    title_html = "<h3 style='text-align: center; color: #d4af37; margin-bottom: 20px; font-weight: bold;'>הערות</h3>"
    all_fns_html = "<ol style='font-size: 1.1em; line-height: 1.8;'>"
    for fn_id, li_tag in footnotes_dict.items():
        all_fns_html += str(li_tag)
    all_fns_html += "</ol>"
    
    footer_div = soup.new_tag("div")
    footer_div.append(BeautifulSoup(separator_html + title_html + all_fns_html, 'html.parser'))
    soup.append(footer_div)

# שמירת כל הספר המלא כקובץ HTML אחד מושלם
with open("full_book_output.html", "w", encoding="utf-8") as f:
    f.write(str(soup))

print("קובץ ה-HTML המלא נוצר בהצלחה בשם full_book_output.html!")