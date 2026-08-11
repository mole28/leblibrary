import re
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse, JsonResponse
from django.contrib.sitemaps.views import sitemap
from django.views.generic import TemplateView
from articles.sitemaps import StaticViewSitemap, ArticleSitemap, BookSitemap
from articles.models import Article, Book

# איחוד כל מפות האתר למילון אחד (כולל מפת הספרים)
sitemaps = {
    'static': StaticViewSitemap,
    'articles': ArticleSitemap,
    'books': BookSitemap,
}

# פונקציה שמייצרת את קובץ ה-robots.txt
def robots_txt(request):
    lines = [
        "User-agent: *",
        "Disallow: /api/",
        "Allow: /",
        "",
        "User-agent: GPTBot",
        "Allow: /",
        "",

        "User-agent: ChatGPT-User",
        "Allow: /",
        "",
        "User-agent: PerplexityBot",
        "Allow: /",
        "",
        "User-agent: ClaudeBot",
        "Allow: /",
        "",
        "User-agent: Google-Extended",
        "Allow: /",

        "Sitemap: https://leblibrary.co.il/sitemap.xml"
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")

# פונקציה שמייצרת את קובץ ה-llms-full.txt
def llms_full_txt(request):
    articles = Article.objects.filter(is_published=True).order_by('-created_at')[:50]
    books = Book.objects.all()
    
    content = "# ספריית לייבוביץ - מאגר תוכן מלא לבינה מלאכותית\n\n"
    
    content += "## ספרים בספרייה:\n"
    for book in books:
        content += f"- **{book.title}** (מחבר: {getattr(book, 'author', 'לא צוין')})\n"
        
    content += "\n## מאמרים אחרונים:\n"
    for article in articles:
        content += f"### {article.title}\n"
        clean_text = re.sub(r'<[^>]+>', '', article.content)[:300] if article.content else ""
        content += f"{clean_text}...\n\n"
        
    return HttpResponse(content, content_type='text/plain; charset=utf-8')

# פונקציה שמייצרת את סכמת ה-OpenAPI
def openapi_schema(request):
    schema = {
        "openapi": "3.1.0",
        "info": {
            "title": "ספריית לייבוביץ - API חיפוש תורני",
            "description": "ממשק חיפוש פתוח למאמרים, סוגיות וספרים תורניים מתוך ספריית לייבוביץ.",
            "version": "1.0.0"
        },
        "servers": [{"url": "https://leblibrary.co.il"}],
        "paths": {
            "/api/ai-search/": {
                "get": {
                    "summary": "חיפוש במאגרי הספרייה",
                    "description": "מחזיר מקורות, מאמרים וקטעי טקסט רלוונטיים מתוך ספריית לייבוביץ לפי שאילתה בעברית.",
                    "operationId": "aiSearch",
                    "parameters": [
                        {
                            "name": "q",
                            "in": "query",
                            "required": True,
                            "description": "שאילתת החיפוש או הנושא ההלכתי בעברית",
                            "schema": {"type": "string"}
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "תוצאות החיפוש חזרו בהצלחה",
                            "content": {
                                "application/json": {
                                    "schema": {"type": "object"}
                                }
                            }
                        }
                    }
                }
            }
        },
        "components": {"schemas": {}}
    }
    return JsonResponse(schema, json_dumps_params={'ensure_ascii': False, 'indent': 2})

# הפונקציה החדשה שתפתור את השגיאה של ה-manifest.json
def manifest_json(request):
    manifest = {
      "name": "ספריית לייבוביץ",
      "short_name": "לייבוביץ",
      "description": "ספרייה תורנית מתקדמת המרכזת מאמרים, ספרים, וסוגיות הלכתיות.",
      "id": "/",
      "categories": ["books", "education", "utilities"],
      "start_url": "/",
      "display": "standalone",
      "background_color": "#ffffff",
      "theme_color": "#3f4050",
      "orientation": "portrait-primary",
      "icons": [
        {
          "src": "/static/images/icon-192x192.png",
          "sizes": "192x192",
          "type": "image/png"
        },
        {
          "src": "/static/images/icon-512x512.png",
          "sizes": "512x512",
          "type": "image/png"
        }
      ],
      "related_applications": [],
      "prefer_related_applications": False,
      "shortcuts": [],
      "wakelock": False,
      "display_override": ["window-controls-overlay"],
      "handle_links": "preferred",
      "dir": "rtl",
      "lang": "he",
      "iarc_rating_id": "",
      "serviceworker": {
        "src": "/sw.js",
        "scope": "/"
      },
      "android_package_name": "il.co.leblibrary.v2"
    }
    return JsonResponse(manifest, json_dumps_params={'ensure_ascii': False, 'indent': 2})

urlpatterns = [
    path('admin/', admin.site.urls),
    
    # --- הוספת נתיב ה-CKEditor לפתרון שגיאת האדמין ---
    path("ckeditor5/", include('django_ckeditor_5.urls')),
    
    # --- נתיבים עבור SEO, PWA ובוטים של AI בשורש הדומיין ---
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', robots_txt, name='robots_file'),
    
    # קובץ האימות של IndexNow לבינג ול-AI
    path('mosheleibowitzkey123.txt', lambda request: HttpResponse('mosheleibowitzkey123', content_type='text/plain')),
    
    # קובץ ה-OpenAPI המוגדר עבור Custom GPT
    path('openapi.json', openapi_schema, name='openapi_schema'),
    
    # קובץ התוכן המלא לבוטים של AI
    path('llms-full.txt', llms_full_txt, name='llms_full_txt'),
    
    # === התיקון שלנו: עוקפים את התבניות ומגישים את המניפסט ישירות ===
    path('manifest.json', manifest_json, name='manifest_json'),
    
    path('service-worker.js', TemplateView.as_view(template_name="sw.js", content_type="application/javascript")),
    path('sw.js', TemplateView.as_view(template_name="sw.js", content_type="application/javascript")),
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

    # קובץ ה-humans.txt הפיזי מתוך תיקיית ה-templates
    path('humans.txt', TemplateView.as_view(template_name='humans.txt', content_type='text/plain; charset=utf-8')),

    # הכללת כל שאר הניתובים של האפליקציה (מאמרים, ספרים, חנות וכו')
    path('', include('articles.urls')),
]

# הוספת נתיב לטעינת קבצי מדיה (תמונות) בסביבת פיתוח
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)