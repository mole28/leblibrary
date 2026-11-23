import re
from django.contrib.sitemaps import Sitemap
from django.db.models import Q
from django.urls import NoReverseMatch, reverse
from articles.models import Article, Book, QA
from articles.views import PARASHA_CANONICAL_NAMES, _parasha_to_slug


class BaseSitemap(Sitemap):
    protocol = 'https'

    def get_urls(self, page=1, site=None, protocol=None):
        class SiteMock:
            domain = 'leblibrary.co.il'
            name = 'leblibrary.co.il'
        return super().get_urls(page, site=SiteMock(), protocol=self.protocol)

    def lastmod(self, obj):
        if hasattr(obj, 'updated_at') and obj.updated_at:
            return obj.updated_at
        if hasattr(obj, 'created_at') and obj.created_at:
            return obj.created_at
        return None


class StaticViewSitemap(BaseSitemap):
    priority = 0.9
    changefreq = 'weekly'

    def items(self):
        return [
            'list',
            'articles_index',
            'books',
            'qa',
            'parasha',
            'recently_added',
            'advanced_search',
            'aramaic_translator',
            'calculator',
            'volume_calculator',
            'weight_calculator',
            'about',
            'contact',
            'terms',
        ]

    def location(self, item):
        try:
            return reverse(item)
        except NoReverseMatch:
            try:
                return reverse(f'articles:{item}')
            except NoReverseMatch:
                fallback_paths = {
                    'list': '/',
                    'articles_index': '/index/',
                    'books': '/books/',
                    'qa': '/qa/',
                    'parasha': '/parasha/',
                    'recently_added': '/recently-added/',
                    'advanced_search': '/advanced-search/',
                    'aramaic_translator': '/aramaic-translator/',
                    'calculator': '/calculator/',
                    'volume_calculator': '/volume-calculator/',
                    'weight_calculator': '/weight-calculator/',
                    'about': '/about/',
                    'contact': '/contact/',
                    'terms': '/terms/',
                }
                return fallback_paths.get(item, '/')


class ArticleSitemap(BaseSitemap):
    priority = 0.9
    changefreq = 'daily'

    def items(self):
        return Article.objects.filter(is_published=True).order_by('-id')

    def location(self, item):
        try:
            return reverse('detail', kwargs={'slug': item.slug})
        except NoReverseMatch:
            return reverse('articles:detail', kwargs={'slug': item.slug})


class BookSitemap(BaseSitemap):
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return Book.objects.all().order_by('-pk')

    def location(self, item):
        try:
            return reverse('book_detail', kwargs={'pk': item.pk})
        except NoReverseMatch:
            return reverse('articles:book_detail', kwargs={'pk': item.pk})


class QASitemap(BaseSitemap):
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        return QA.objects.all().order_by('-pk')

    def location(self, item):
        try:
            return reverse('articles:qa_detail', kwargs={'pk': item.pk})
        except NoReverseMatch:
            return f'/qa/{item.pk}/'


class ParashaSitemap(BaseSitemap):
    priority = 0.8
    changefreq = 'weekly'

    def items(self):
        published = list(
            Article.objects.filter(is_published=True)
            .exclude(Q(parasha__isnull=True) | Q(parasha__exact=''))
            .values_list('parasha', 'created_at')
        )
        latest_by_parasha = {}
        for raw_parasha, created_at in published:
            for token in str(raw_parasha or '').split(','):
                name = re.sub(r'\s+', ' ', token).strip()
                if name in PARASHA_CANONICAL_NAMES:
                    prev = latest_by_parasha.get(name)
                    if created_at and (prev is None or created_at > prev):
                        latest_by_parasha[name] = created_at
                    elif name not in latest_by_parasha:
                        latest_by_parasha[name] = None
        return [
            {'name': p, 'slug': _parasha_to_slug(p), 'lastmod': latest_by_parasha[p]}
            for p in PARASHA_CANONICAL_NAMES
            if p in latest_by_parasha
        ]

    def location(self, item):
        try:
            return reverse('articles:parasha_detail', kwargs={'parasha_name': item['slug']})
        except NoReverseMatch:
            return f"/parasha/{item['slug']}/"

    def lastmod(self, item):
        return item.get('lastmod')


sitemaps = {
    'static': StaticViewSitemap,
    'articles': ArticleSitemap,
    'books': BookSitemap,
    'qas': QASitemap,
    'parashot': ParashaSitemap,
}