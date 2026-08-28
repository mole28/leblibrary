import os
import django
from bs4 import BeautifulSoup

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zmani_book():
    book_title = "זמני המילה וברכותיה"
    
    book, _ = Book.objects.get_or_create(title=book_title)
    print(f"מעבד את הספר: {book.title}")

    html_file_path = "zmani_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא!")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, 'html.parser')
    
    # ניקוי פרקים וסעיפים קודמים של הספר למניעת כפילויות
    chapters_to_delete = Chapter.objects.filter(book=book)
    Section.objects.filter(chapter__in=chapters_to_delete).delete()
    chapters_to_delete.delete()
    print("נוקו פרקים וסעיפים ישנים.")

    # חלוקה חכמה לפי מציאת כותרות שמתחילות ב-"סימן"
    intro_elements = []
    siman_blocks = []
    current_title = "פתח דבר והקדמה"
    current_content = []
    found_first_siman = False

    # נעבור על כל אלמנט ברמה הכללית ב-HTML
    for element in soup.body.children if soup.body else soup.children:
        if element.name is None:
            continue
        
        text = element.get_text(strip=True)
        
        # זיהוי תחילת סימן חדש על סמך הפלט שראינו
        if text.startswith("סימן") and len(text) < 80:
            if found_first_siman and current_content:
                siman_blocks.append((current_title, "".join(str(e) for e in current_content)))
                current_content = []
            
            current_title = text
            found_first_siman = True
            current_content.append(element)
            continue

        if not found_first_siman:
            intro_elements.append(element)
        else:
            current_content.append(element)

    # הוספת הבלוק האחרון שנשאר
    if current_content:
        siman_blocks.append((current_title, "".join(str(e) for e in current_content)))

    # שמירה במסד הנתונים
    # 1. שמירת ההקדמה/פתח דבר אם קיימת
    if intro_elements:
        intro_ch = Chapter.objects.create(book=book, title="פתח דבר והקדמה", order=1)
        intro_html = "".join(str(e) for e in intro_elements)
        Section.objects.create(chapter=intro_ch, title="פתח דבר", content=intro_html, order=1)
        ch_order = 2
    else:
        ch_order = 1

    # 2. שמירת כל סימן כפרק נפרד (שיופיע מודגש בסרגל הצידי)
    for title, body in siman_blocks:
        chapter = Chapter.objects.create(
            book=book,
            title=title,
            order=ch_order
        )

        # יצירת סעיף תחת הסימן
        Section.objects.create(
            chapter=chapter,
            title=title,
            content=body,
            order=1
        )
        ch_order += 1

    print(f"הספר יובא בהצלחה! נוצרו {len(siman_blocks)} סימנים כפרקים במסד הנתונים.")

if __name__ == "__main__":
    import_zmani_book()