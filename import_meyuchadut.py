import os
import django
import re
from bs4 import BeautifulSoup

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_meyuchadut_book():
    book_title = "מיוחדות המילה בישראל"
    
    # ניקוי מלא של ספרים קודמים עם אותו שם כדי למנוע כפילויות
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
    
    # הגדרת שם המחבר באופן אוטומטי
    for field in ['author', 'writer', 'creator']:
        if hasattr(book, field):
            setattr(book, field, "משה לייבוביץ")
            book.save()
            break

    print(f"נוצר ספר חדש: {book.title} מאת משה לייבוביץ")

    html_file_path = "meyuchadut_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא! אנא ודא שהקובץ קיים בתיקייה.")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, 'html.parser')
    
    # הסרת סקריפטים וסטיילים גולמיים שמפריעים
    for element in soup(["script", "style", "meta", "link", "form", "input", "button", "textarea", "select"]):
        element.decompose()

    # שיטת חלוקה בטוחה: מעבר על כל הפסקאות וזיהוי כותרות ראשיות
    chapters_data = []
    current_title = "הקדמה"
    current_content = []
    
    # פונקציה לזיהוי כותרות פרקים (סוגיא, פתח דבר, נספחים, סימן)
    def is_heading(text_to_check):
        t = text_to_check.strip()
        if t == "פתח דבר": return True
        if re.match(r'^סוגיא\s+[א-ת]{1,2}\s*[-–]', t): return True
        if re.match(r'^(?:נספחים|נפחים)\s+לסוגיא\s+[א-ת]', t): return True  # מטפל גם בשגיאת הכתיב "נפחים" שהייתה בטקסט
        if re.match(r'^סימן\s+[א-ת]{1,2}\s*[-–]', t): return True
        return False

    for tag in soup.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'div']):
        text = tag.get_text(strip=True)
        clean_text = re.sub(r'\s+', ' ', text).strip()
        
        # אם מצאנו כותרת ראשית, חותכים פרק חדש (מתעלמים מחלוקה לאותיות פנימיות)
        if len(clean_text) < 100 and is_heading(clean_text):
            if current_content:
                chapters_data.append((current_title, "".join(str(e) for e in current_content)))
            current_title = clean_text
            current_content = [tag]
        else:
            current_content.append(tag)
            
    if current_content:
        chapters_data.append((current_title, "".join(str(e) for e in current_content)))

    # הזרקת סגנון CSS להגדלה והדגשה של כל ההפניות והערות השוליים
    force_large_css = """
    <style>
    sup, sub, .MsoFootnoteReference, a[href*="ftn"], a[href*="footnote"], a[href*="ref"] {
        font-size: 1.35em !important;
        font-weight: bold !important;
        vertical-align: baseline !important;
    }
    </style>
    """

    ch_order = 1
    for ch_title, ch_html in chapters_data:
        ch_soup = BeautifulSoup(ch_html, 'html.parser')
        
        # הסרת הדגשות מיותרות מתוך הטקסט לבקשתך
        for tag_b in ch_soup.find_all(['strong', 'b']):
            tag_b.unwrap()

        # איסוף הערות שוליים וצרופן בצורה מסודרת בתחתית הפרק
        all_footnotes = ch_soup.find_all(lambda tag: tag.has_attr('id') and ('ftn' in tag['id'] or 'footnote' in tag['id']))
        cleaned_footnotes = []
        for fn in all_footnotes:
            cleaned_footnotes.append(str(fn))
            fn.decompose()
        footnotes_html = "".join(cleaned_footnotes)

        final_content = force_large_css + str(ch_soup)
        if footnotes_html:
            final_content += "<hr class='footnotes-divider'>" + footnotes_html

        # יצירת הפרק בספר (מה שיופיע בתוכן העניינים)
        chapter = Chapter.objects.create(
            book=book,
            title=ch_title[:150],
            order=ch_order
        )

        # יצירת סעיף יחיד לכל פרק - כך לא יופיעו אותיות בתוכן העניינים
        Section.objects.create(
            chapter=chapter,
            title=ch_title[:150],
            content=final_content,
            order=1
        )
        
        ch_order += 1

    print(f"הספר '{book_title}' יובא בהצלחה בשיטה המנצחת מאתמול!")

if __name__ == "__main__":
    import_meyuchadut_book()