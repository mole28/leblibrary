from django.contrib.sitemaps import Sitemap
from django.urls import reverse
from articles.models import Article

# (שחרר מהערה את השורה הבאה אם מודל הספרים גם נמצא באפליקציית articles)
# from articles.models import Book


class StaticViewSitemap(Sitemap):
    """מפת אתר לעמודים רגילים שאין להם מודל במסד הנתונים"""
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return ['about', 'contact', 'terms', 'calculator', 'volume_calculator', 'weight_calculator']

    def location(self, item):
        return reverse(item)


class ArticleSitemap(Sitemap):
    """מפת אתר דינמית ששולפת אוטומטית את כל המאמרים ממסד הנתונים"""
    priority = 0.9  # עדיפות גבוהה יותר לתוכן האמיתי של האתר
    changefreq = 'daily'

    def items(self):
        return Article.objects.all()

    def location(self, item):
        # מניח ששם הנתיב של מאמר ב-urls.py שלך הוא 'detail' והוא מקבל pk
        return reverse('detail', kwargs={'pk': item.pk})


# class BookSitemap(Sitemap):
#     """מפת אתר דינמית לספרים (אופציונלי)"""
#     priority = 0.9
#     changefreq = 'daily'
#
#     def items(self):
#         return Book.objects.all()
#
#     def location(self, item):
#         # מניח ששם הנתיב ב-urls.py הוא 'book_detail'
#         return reverse('book_detail', kwargs={'pk': item.pk})