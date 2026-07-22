from django.contrib.sitemaps import Sitemap
from django.urls import reverse, NoReverseMatch
from articles.models import Article

class StaticViewSitemap(Sitemap):
    """מפת אתר לעמודים רגילים שאין להם מודל במסד הנתונים"""
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return ['about', 'contact', 'terms', 'calculator', 'volume_calculator', 'weight_calculator']

    def location(self, item):
        try:
            # מנסה לאתר את הקישור ללא קידומת
            return reverse(item)
        except NoReverseMatch:
            # אם יש Namespace (כמו app_name='articles'), הוא יוסיף את הקידומת אוטומטית
            return reverse(f'articles:{item}')


class ArticleSitemap(Sitemap):
    """מפת אתר דינמית ששולפת אוטומטית את כל המאמרים ממסד הנתונים"""
    priority = 0.9  
    changefreq = 'daily'

    def items(self):
        return Article.objects.all()

    def location(self, item):
        try:
            # מנסה לאתר את קישור המאמר ללא קידומת
            return reverse('detail', kwargs={'pk': item.pk})
        except NoReverseMatch:
            # עם קידומת
            return reverse('articles:detail', kwargs={'pk': item.pk})