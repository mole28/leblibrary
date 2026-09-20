from django.contrib.sitemaps import Sitemap
from django.urls import reverse, NoReverseMatch
from articles.models import Article, Book

class BaseSitemap(Sitemap):
    """
    מחלקת בסיס שפותרת את בעיית ה-example.com של ג'אנגו
    וכופה את הדומיין והפרוטוקול האמיתיים של האתר על כל המפות
    """
    protocol = 'https'
    
    def get_urls(self, page=1, site=None, protocol=None):
        class SiteMock:
            domain = 'leblibrary.co.il'
            name = 'leblibrary.co.il'
        return super().get_urls(page, site=SiteMock(), protocol=self.protocol)

    def lastmod(self, obj):
        """פונקציית lastmod מרכזית שמשמשת את כל המפות באופן אוטומטי"""
        if hasattr(obj, 'updated_at') and obj.updated_at:
            return obj.updated_at
        elif hasattr(obj, 'created_at') and obj.created_at:
            return obj.created_at
        return None

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
        # שדרוג: שליפת שדות נדרשים בלבד + מיון מובטח למניעת בעיות פג'ינציה
        return Article.objects.filter(is_published=True).only('slug', 'updated_at', 'created_at').order_by('-id')

    def location(self, item):
        try:
            return reverse('detail', kwargs={'slug': item.slug})
        except NoReverseMatch:
            return reverse('articles:detail', kwargs={'slug': item.slug})

class BookSitemap(BaseSitemap):
    """מפת אתר דינמית ששולפת אוטומטית את כל הספרים ממסד הנתונים"""
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        # שדרוג: שליפת שדות נדרשים בלבד + מיון מובטח
        return Book.objects.all().only('pk', 'updated_at', 'created_at').order_by('-pk')

    def location(self, item):
        try:
            return reverse('book_detail', kwargs={'pk': item.pk})
        except NoReverseMatch:
            return reverse('articles:book_detail', kwargs={'pk': item.pk})

# =====================================
# המילון שמאגד את כל מפות האתר
# =====================================
sitemaps = {
    'static': StaticViewSitemap,
    'articles': ArticleSitemap,
    'books': BookSitemap,
}