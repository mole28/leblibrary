from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.contrib.sitemaps.views import sitemap
from django.views.generic import TemplateView
from articles.sitemaps import StaticViewSitemap, ArticleSitemap

# איחוד כל מפות האתר למילון אחד
sitemaps = {
    'static': StaticViewSitemap,
    'articles': ArticleSitemap,
}

# פונקציה שמייצרת את קובץ ה-robots.txt ומפנה למפת האתר
def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "",
        "User-agent: Google-Extended",
        "Allow: /",
        "",
        "Sitemap: https://leblibrary.co.il/sitemap.xml"
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # --- נתיבים עבור SEO, PWA ובוטים של AI בשורש הדומיין ---
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', robots_txt, name='robots_file'),
    path('manifest.json', TemplateView.as_view(template_name="articles/manifest.json", content_type="application/json")),
    path('service-worker.js', TemplateView.as_view(template_name="articles/sw.js", content_type="application/javascript")),
    path('sw.js', TemplateView.as_view(template_name="articles/sw.js", content_type="application/javascript")),
    path('.well-known/assetlinks.json', TemplateView.as_view(template_name="assetlinks.json", content_type="application/json")),
    
    # קובץ ה-llms.txt מוגש ישירות עם UTF-8 נקי למניעת ג'יבריש
    path('llms.txt', lambda request: HttpResponse("""# ספריית לייבוביץ

> ספריית לייבוביץ היא ספרייה תורנית מתקדמת המרכזת מאמרים, ספרים, וסוגיות הלכתיות ועיוניות מעמיקות פרי עטו של משה וכותבים נוספים, לצד מחשבוני חז"ל וכלים תורניים.

## עמודים מרכזיים ומאגר התוכן
- [עמוד הבית](https://leblibrary.co.il/): השער הראשי לספרייה, למאמרים האחרונים ולספרים.
- [מאמרים הלכתיים ועיוניים](https://leblibrary.co.il/): אינדקס המאמרים המלא של האתר המתעדכן באופן שוטף.
- [ספריית הספרים](https://leblibrary.co.il/books/): ספרים תורניים מלאים המחולקים לפרקים ולסעיפים, כולל אפשרות רכישה וצפייה מתקדמת.
- [שאלות ותשובות](https://leblibrary.co.il/qa/): מאגר מענה הלכתי ושאלות נפוצות.
- [פרשת השבוע](https://leblibrary.co.il/parasha/): מאמרים ודברי תורה מותאמים לפרשת השבוע.
- [מחשבוני חז"ל](https://leblibrary.co.il/calculator/): כלים לחישובים הלכתיים מדויקים (מידות, שיעורים וכדומה).

## מטרת האתר
האתר נועד להנגיש לימוד תורה מדויק, סוגיות בעיונים הלכתיים, ומקורות תורניים בצורה נקייה ונוחה ללומדים, לחוקרים ולציבור הרחב.""", content_type='text/plain; charset=utf-8')),

    # הכללת כל שאר הניתובים של האפליקציה (מאמרים, ספרים, חנות וכו')
    path('', include('articles.urls')),
]

# הוספת נתיב לטעינת קבצי מדיה (תמונות) בסביבת פיתוח
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)