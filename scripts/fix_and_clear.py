import os
import django
import re

# הגדרת סביבת דג'נגו
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from articles.models import Book
from django.core.cache import cache

def fix_book_footnotes_and_cache():
    print("מתחיל בתיקון עמוק ומדויק של ההפניות בספר 84...")
    
    try:
        book = Book.objects.get(id=84)
    except Book.DoesNotExist:
        print("שגיאה: ספר 84 לא נמצא!")
        return

    fixed_count = 0

    for chapter in book.chapters.all():
        for section in chapter.sections.all():
            if not section.content:
                continue
                
            content = section.content
            original_content = content

            # התאמה מדויקת לפורמט של שאר הספרים שעובדים אצלנו:
            # 1. המרת מעטפת ה-sup והקישור לפורמט של א-הפניה מסורתי עם name ו-href בדיוק כמו בספר השני
            def replace_ref(match):
                num = match.group(1)
                return f'<a style="color:#2f6dbb;" href="#_ftn{num}" name="_ftnref{num}" title=""><u>[{num}]</u></a>'

            # חיפוש כל סוגי ההפניות האפשריות שנוצרו בספר הזה (עם סאפ או בלי)
            content = re.sub(r'<sup[^>]*>\s*<a[^>]*href="#fn-(\d+)"[^>]*>.*?</a>\s*</sup>', replace_ref, content, flags=re.DOTALL)
            content = re.sub(r'<a[^>]*href="#fn-(\d+)"[^>]*>\[?(\d+)\]?</a>', replace_ref, content, flags=re.DOTALL)
            content = re.sub(r'href="#fnref-(\d+)"', r'href="#_ftnref\1"', content, flags=re.DOTALL)

            # 2. המרת רשימת ההערות בסוף לפורמט _ftn{num}
            def replace_fn_item(match):
                num = match.group(1)
                return f'<li id="_ftn{num}">'

            content = re.sub(r'<li id="fn-(\d+)">', replace_fn_item, content, flags=re.DOTALL)

            if content != original_content:
                section.content = content
                section.save()
                fixed_count += 1

    # ניקוי מוחלט של כל קאש השרת כדי שהשינוי יופיע מיד באתר
    cache.clear()
    print("קאש השרתנוקה בהצלחה!")
    print(f"התיקון הושלם! עודכנו {fixed_count} סעיפים.")

if __name__ == '__main__':
    fix_book_footnotes_and_cache()