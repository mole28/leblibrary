import re
import mammoth
from bs4 import BeautifulSoup
from django import forms
from django.contrib import admin
from .models import Article, Book, Chapter, Section, Cart, CartItem, Order, OrderItem, QA, VisitorLog

_MAX_DOCX_BYTES = 25 * 1024 * 1024
_BLOCKED_IMPORT_TAGS = ('script', 'iframe', 'object', 'embed', 'form', 'input', 'textarea', 'select', 'meta', 'base')


def process_word_file(word_file):
    result = mammoth.convert_to_html(word_file)
    html = result.value

    soup = BeautifulSoup(html, 'html.parser')

    for bad_tag in soup.find_all(_BLOCKED_IMPORT_TAGS):
        bad_tag.decompose()
    for el in soup.find_all(True):
        for attr in list(el.attrs.keys()):
            if attr.lower().startswith('on'):
                del el.attrs[attr]
            elif attr.lower() in ('href', 'src'):
                val = str(el.attrs.get(attr) or '').strip().lower()
                if val.startswith(('javascript:', 'vbscript:', 'data:text/html')):
                    del el.attrs[attr]

    footnotes_dict = {}
    for li in soup.find_all('li', id=re.compile(r'^footnote-')):
        fn_id = li['id']
        for back_link in li.find_all('a', string='↑'):
            back_link.decompose()
        footnotes_dict[fn_id] = li
        li.extract()

    for ol in soup.find_all('ol'):
        if not ol.get_text(strip=True):
            ol.extract()

    force_large_css = """
    <style>
    sup, sub, .MsoFootnoteReference, a[href*="ftn"], a[href*="footnote"], a[href*="ref"] {
        font-size: 0.9em !important;
        font-weight: bold !important;
        vertical-align: super !important;
        line-height: 0;
    }
    </style>
    """

    for tag_b in soup.find_all(['strong', 'b']):
        tag_b.unwrap()

    final_content = force_large_css + str(soup)

    if footnotes_dict:
        separator_html = "<hr style='border: 0; border-top: 5px solid #2c3e50; margin: 50px 0 30px 0; opacity: 1;'>"
        title_html = "<h3 style='text-align: center; color: #d4af37; margin-bottom: 20px; font-weight: bold;'>הערות</h3>"

        all_fns_html = "<ol style='font-size: 1.1em; line-height: 1.8;'>"
        for fn_id, li_tag in footnotes_dict.items():
            all_fns_html += str(li_tag)
        all_fns_html += "</ol>"

        final_content += separator_html + title_html + all_fns_html

    return final_content


class SmartImportForm(forms.ModelForm):
    word_import = forms.FileField(
        required=False,
        label='ייבוא מהיר מקובץ וורד (docx) - מומלץ!',
        help_text='בחר קובץ וורד, השאר את עורך הטקסט ריק, ולחץ "שמור". המערכת תשאב את התוכן והערות השוליים בצורה מושלמת!'
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in ['content', 'description']:
            if field in self.fields:
                self.fields[field].required = False

    def clean_word_import(self):
        word_file = self.cleaned_data.get('word_import')
        if not word_file:
            return word_file
        name_lower = str(getattr(word_file, 'name', '') or '').lower()
        if not name_lower.endswith('.docx'):
            raise forms.ValidationError('יש להעלות קובץ Word תקני בסיומת .docx בלבד.')
        if getattr(word_file, 'size', 0) > _MAX_DOCX_BYTES:
            raise forms.ValidationError('גודל קובץ ה-Word חורג מהמותר (עד 25MB).')
        return word_file

    def clean(self):
        cleaned_data = super().clean()
        word_file = cleaned_data.get('word_import')

        if word_file:
            word_file.seek(0)
            final_html = process_word_file(word_file)

            if 'content' in self.fields:
                cleaned_data['content'] = final_html
                self.instance.content = final_html
            elif 'description' in self.fields:
                cleaned_data['description'] = final_html
                self.instance.description = final_html

        return cleaned_data


class ArticleAdminForm(SmartImportForm):
    class Meta:
        model = Article
        fields = '__all__'


class BookAdminForm(SmartImportForm):
    class Meta:
        model = Book
        fields = '__all__'


class SectionAdminForm(SmartImportForm):
    class Meta:
        model = Section
        fields = '__all__'


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    form = ArticleAdminForm
    list_display = ('title', 'parasha', 'is_published', 'created_at')
    list_filter = ('is_published', 'created_at')
    search_fields = ('title', 'content', 'parasha')
    prepopulated_fields = {'slug': ('title',)}


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    form = BookAdminForm
    list_display = ('title', 'author', 'order', 'price', 'stock', 'is_for_sale')
    list_editable = ('order', 'price', 'stock', 'is_for_sale')
    list_filter = ('is_for_sale',)
    search_fields = ('title', 'author')


@admin.register(Chapter)
class ChapterAdmin(admin.ModelAdmin):
    list_display = ('title', 'book', 'order')
    list_filter = ('book',)
    search_fields = ('title',)
    list_editable = ('order',)


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    form = SectionAdminForm
    list_display = ('title', 'chapter', 'order')
    list_filter = ('chapter__book',)
    search_fields = ('title', 'content')
    list_editable = ('order',)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ('price',)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'first_name', 'last_name', 'status', 'total_paid', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('first_name', 'last_name', 'email', 'phone', 'id')
    list_editable = ('status',)
    inlines = [OrderItemInline]


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at')


@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('cart', 'book', 'quantity')


@admin.register(QA)
class QAAdmin(admin.ModelAdmin):
    list_display = ('question', 'category', 'created_at')
    search_fields = ('question', 'answer', 'category')
    list_filter = ('category', 'created_at')


@admin.register(VisitorLog)
class VisitorLogAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'path', 'user', 'timestamp')
    list_filter = ('timestamp', 'user')
    search_fields = ('ip_address', 'path', 'user__username', 'user_agent')
    readonly_fields = ('ip_address', 'path', 'user', 'user_agent', 'timestamp')

    def has_add_permission(self, request):
        return False