from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.http import HttpResponse
from django.contrib.sitemaps.views import sitemap
from core.sitemaps import StaticViewSitemap, ArticleSitemap
from django.views.generic import TemplateView

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
    path('', include('articles.urls')),
    
    # --- נתיבים עבור SEO ובוטים של AI ---
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('robots.txt', robots_txt, name='robots_file'),
    path('manifest.json', TemplateView.as_view(template_name="articles/manifest.json", content_type="application/json")),
    path('service-worker.js', TemplateView.as_view(template_name="articles/sw.js", content_type="application/javascript")),
    path('.well-known/assetlinks.json', TemplateView.as_view(template_name="assetlinks.json", content_type="application/json")),
]

# הוספת נתיב לטעינת קבצי מדיה (תמונות) בסביבת פיתוח
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)