from django.contrib.sitemaps import Sitemap
from django.urls import reverse, NoReverseMatch
from articles.models import Article, Book  # הוספתי כאן את מודל הספרים

class BaseSitemap(Sitemap):
    """
    מחלקה בסיסית שפותרת את בעיית ה-example.com של ג'נגו
    וכופה את הדומיין והפרוטוקול האמיתיים של האתר על כל המפות
    """
    protocol = 'https'
    
    def get_urls(self, page=1, site=None, protocol=None):
        class SiteMock:
            domain = 'leblibrary.co.il'
            name = 'leblibrary.co.il'
        return super().get_urls(page, site=SiteMock(), protocol=self.protocol)

class StaticViewSitemap(BaseSitemap):
    """מפת אתר לעמודים רגילים שאין להם מודל במסד הנתונים"""
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return ['about', 'contact', 'terms', 'calculator', 'volume_calculator', 'weight_calculator']

    def location(self, item):
        try:
            return reverse(item)
        except NoReverseMatch:
            return reverse(f'articles:{item}')

class ArticleSitemap(BaseSitemap):
    """מפת אתר דינמית ששולפת אוטומטית את כל המאמרים המפורסמים ממסד הנתונים"""
    priority = 0.9  
    changefreq = 'daily'

    def items(self):
        # תיקון: שולף אך ורק מאמרים מפורסמים כדי לא לחשוף טיוטות לזוחלים
        return Article.objects.filter(is_published=True)

    def location(self, item):
        try:
            return reverse('detail', kwargs={'pk': item.pk})
        except NoReverseMatch:
            return reverse('articles:detail', kwargs={'pk': item.pk})

    def lastmod(self, obj):
        if hasattr(obj, 'updated_at'):
            return obj.updated_at
        elif hasattr(obj, 'created_at'):
            return obj.created_at
        return None

class BookSitemap(BaseSitemap):
    """מפת אתר דינמית ששולפת אוטומטית את כל הספרים ממסד הנתונים"""
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return Book.objects.all()

    def location(self, item):
        try:
            # ודא שהשם 'book_detail' תואם לשם ה-URL ב-urls.py שלך
            return reverse('book_detail', kwargs={'pk': item.pk})
        except NoReverseMatch:
            return reverse('articles:book_detail', kwargs={'pk': item.pk})

    def lastmod(self, obj):
        if hasattr(obj, 'updated_at'):
            return obj.updated_at
        elif hasattr(obj, 'created_at'):
            return obj.created_at
        return None

# =====================================
# המילון שמאגד את כל מפות האתר
# =====================================
sitemaps = {
    'static': StaticViewSitemap,
    'articles': ArticleSitemap,
    'books': BookSitemap,
}