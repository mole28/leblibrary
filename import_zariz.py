import os
import django
import re
from bs4 import BeautifulSoup

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book, Chapter, Section

def import_zariz_book():
    book_title = "זריזין מקדימין למילה"
    
    # ניקוי מלא של ספרים קודמים בעלי אותו שם (כדי למנוע כפילויות אם מריצים כמה פעמים)
    existing_books = Book.objects.filter(title=book_title)
    if existing_books.exists():
        for b in existing_books:
            chapters = b.chapters.all()
            for ch in chapters:
                Section.objects.filter(chapter=ch).delete()
            chapters.delete()
        existing_books.delete()
        print("נמחקו נסיונות קודמים של הספר החדש.")

    # יצירת הספר החדש במסד הנתונים
    book = Book.objects.create(title=book_title)
    
    # עדכון שם המחבר במסד הנתונים (מוסיף "משה לייבוביץ" לאחד מהשדות הקיימים)
    for field in ['author', 'writer', 'creator']:
        if hasattr(book, field):
            setattr(book, field, "משה לייבוביץ")
            book.save()
            break

    print(f"נוצר ספר חדש: {book.title} מאת משה לייבוביץ")

    # קריאת קובץ ה-HTML של הספר החדש
    html_file_path = "zariz_clean.html"
    if not os.path.exists(html_file_path):
        print(f"שגיאה: הקובץ {html_file_path} לא נמצא! ודא שהקובץ קיים בתיקייה.")
        return

    with open(html_file_path, "r", encoding="utf-8") as f:
        raw_html = f.read()

    soup = BeautifulSoup(raw_html, 'html.parser')
    
    # הסרת סקריפטים וסטיילים (כדי לשמור על אתר נקי)
    for element in soup(["script", "style", "meta", "link", "form", "input", "button", "textarea", "select"]):
        element.decompose()

    # שליפת כל גוף התוכן (בתוך ה-body)
    body_tag = soup.find('body')
    if not body_tag:
        body_tag = soup

    # --- פיצול לפרקים לפי כותרות H1 ---
    # בקובץ שלך (zariz_clean.html), הכותרות הראשיות מסומנות ב-H1
    
    elements = body_tag.find_all(True, recursive=False)
    
    current_chapter_title = "פתח דבר"
    current_chapter_content = []
    
    chapters_data = [] # ישמור רשימה של אובייקטים {title: "...", content: "..."}
    
    for element in elements:
        if element.name == 'h1':
            # שומרים את הפרק הקודם אם יש בו תוכן
            if current_chapter_content:
                chapters_data.append({
                    "title": current_chapter_title,
                    "content": "".join([str(tag) for tag in current_chapter_content])
                })
            # מתחילים פרק חדש
            current_chapter_title = element.get_text(strip=True)
            current_chapter_content = []
        elif element.name == 'section' and element.get('id') == 'footnotes':
            # אם הגענו להערות השוליים בסוף הקובץ, אנחנו מכניסים אותן לפרק האחרון
            current_chapter_content.append(element)
        else:
            current_chapter_content.append(element)

    # שמירת הפרק האחרון
    if current_chapter_content:
        chapters_data.append({
            "title": current_chapter_title,
            "content": "".join([str(tag) for tag in current_chapter_content])
        })

    # --- יצירת הפרקים והסעיפים במסד הנתונים ---
    ch_order = 1
    for ch_data in chapters_data:
        chapter_soup = BeautifulSoup(ch_data['content'], 'html.parser')
        
        # הסרת הדגשות (bold) מיותרות מכל התוכן כדי שייראה נקי, פרט להערות שוליים
        for tag_b in chapter_soup.find_all(['strong', 'b']):
            # אפשר לשמור הדגשות בסעיפים, אבל בסקריפט הקודם הסרת הכל
            tag_b.unwrap()

        # הזרקת ה-CSS להגדלת הפניות הערות השוליים (כמו בסקריפט הקודם)
        force_large_css = """
        <style>
        sup, sub, .MsoFootnoteReference, a[href*="fnref"], a[href*="footnote"], a[href*="ref"] {
            font-size: 1.35em !important;
            font-weight: bold !important;
            vertical-align: baseline !important;
        }
        </style>
        """
        
        final_content = force_large_css + str(chapter_soup)

        # יצירת פרק
        chapter = Chapter.objects.create(
            book=book,
            title=ch_data['title'],
            order=ch_order
        )

        # יצירת סעיף (בינתיים סעיף אחד לכל פרק)
        Section.objects.create(
            chapter=chapter,
            title=ch_data['title'],
            content=final_content,
            order=1
        )

        ch_order += 1

    print("הספר 'זריזין מקדימין למילה' יובא בהצלחה!")

if __name__ == "__main__":
    import_zariz_book()