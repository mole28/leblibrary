import zipfile
import xml.etree.ElementTree as ET

ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

with zipfile.ZipFile('zmani.docx', 'r') as z:
    doc_xml = z.read('word/document.xml')
    fn_xml = z.read('word/footnotes.xml')
    fn_root = ET.fromstring(fn_xml)

footnotes = {}
for fn in fn_root.findall('.//w:footnote', ns):
    fn_id = fn.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
    texts = [t.text for t in fn.findall('.//w:t', ns) if t.text]
    footnotes[fn_id] = ''.join(texts)

root = ET.fromstring(doc_xml)
body = root.find('w:body', ns)

html_parts = []
fn_counter = 1
collected_footnotes = {}

for child in body:
    if child.tag.endswith('p'):
        pPr = child.find('w:pPr', ns)
        style = ''
        if pPr is not None:
            pStyle = pPr.find('w:pStyle', ns)
            if pStyle is not None:
                style = pStyle.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val', '')
        
        p_runs = []
        for run in child.findall('.//w:r', ns):
            rPr = run.find('w:rPr', ns)
            is_bold = rPr is not None and rPr.find('w:b', ns) is not None
            is_italic = rPr is not None and rPr.find('w:i', ns) is not None
            
            run_text = ''.join([t.text for t in run.findall('w:t', ns) if t.text])
            fn_ref = run.find('w:footnoteReference', ns)
            
            if is_bold and run_text:
                run_text = f"<strong>{run_text}</strong>"
            if is_italic and run_text:
                run_text = f"<em>{run_text}</em>"
            
            if fn_ref is not None:
                orig_id = fn_ref.get('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}id')
                if orig_id in footnotes:
                    collected_footnotes[fn_counter] = footnotes[orig_id]
                    run_text += f' <sup id="fnref-{fn_counter}"><a href="#fn-{fn_counter}">[{fn_counter}]</a></sup>'
                    fn_counter += 1
            
            if run_text:
                p_runs.append(run_text)
        
        p_content = ''.join(p_runs)
        if not p_content.strip():
            continue
            
        if style == '2':
            html_parts.append(f"<h2>{p_content}</h2>")
        elif style == '3':
            html_parts.append(f"<h3>{p_content}</h3>")
        else:
            html_parts.append(f"<p>{p_content}</p>")

if collected_footnotes:
    html_parts.append("<hr style='border: 0; border-top: 5px solid #2c3e50; margin: 50px 0 30px 0; opacity: 1;'>")
    html_parts.append("<h3 style='text-align: center; color: #d4af37; margin-bottom: 20px; font-weight: bold;'>הערות</h3>")
    html_parts.append("<ol style='font-size: 1.1em; line-height: 1.8;'>")
    for num, text in collected_footnotes.items():
        html_parts.append(f'<li id="fn-{num}"><span>{text}</span> <a href="#fnref-{num}">↑</a></li>')
    html_parts.append("</ol>")

with open('my_book_final.html', 'w', encoding='utf-8') as f:
    f.write('\n'.join(html_parts))

print("הקובץ my_book_final.html נוצר בהצלחה בתיקייה שלך במחשב!")