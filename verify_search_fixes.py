import pytest
from django.core.cache import cache
from django.db import connection
from django.urls import reverse

import articles.models as articles_models
import articles.torah_engine as torah_engine
from articles.models import TorahText
from articles.torah_engine import (
    _fast_extract_clean_words,
    _get_verified_fts_table,
    build_hebrew_fuzzy_morph_patterns,
    build_hebrew_fuzzy_patterns,
    ensure_clean_fts5_index,
)


def _reset_search_state():
    cache.clear()
    torah_engine._FTS5_STATE['checked'] = False
    torah_engine._FTS5_STATE['table'] = None
    torah_engine._SPECIAL_HTML_IDS_CACHE = None


def _drop_fts5_if_sqlite():
    if connection.vendor != 'sqlite':
        return
    with connection.cursor() as cur:
        cur.execute("DROP TRIGGER IF EXISTS articles_torahtext_clean_fts_ai")
        cur.execute("DROP TRIGGER IF EXISTS articles_torahtext_clean_fts_ad")
        cur.execute("DROP TRIGGER IF EXISTS articles_torahtext_clean_fts_au")
        cur.execute("DROP TABLE IF EXISTS articles_torahtext_clean_fts")


@pytest.fixture(autouse=True)
def clean_search_env(request):
    _reset_search_state()
    yield
    if request.node.get_closest_marker('django_db'):
        _drop_fts5_if_sqlite()
    _reset_search_state()


def test_models_cleanup_removed_legacy_fts_and_clean_text_btree_index():
    assert not hasattr(articles_models, 'TorahTextFTS')
    index_field_lists = [list(idx.fields) for idx in TorahText._meta.indexes]
    assert ['clean_text'] not in index_field_lists
    assert ['book', 'chapter'] in index_field_lists


def test_fast_extract_clean_words_handles_html_nikkud_and_parasha_markers():
    bereshit = '<big>בְּ</big>רֵאשִׁ֖ית בָּרָ֣א אֱלֹהִ֑ים אֵ֥ת הַשָּׁמַ֖יִם וְאֵ֥ת הָאָֽרֶץ׃'
    assert _fast_extract_clean_words(bereshit) == ['בראשית', 'ברא', 'אלהים', 'את', 'השמים', 'ואת', 'הארץ']

    with_pe = 'וַֽיְהִי־בֹ֖קֶר י֥וֹם שֵׁנִֽי׃&nbsp;<span class="mam-spi-pe">{פ}</span><br>'
    words = _fast_extract_clean_words(with_pe)
    assert words == ['ויהי', 'בקר', 'יום', 'שני']
    assert words[-1] != 'פ'


def test_fuzzy_regex_factors_prefix_without_duplicate_branches():
    _, rx_basic = build_hebrew_fuzzy_patterns('היום')
    _, rx_morph = build_hebrew_fuzzy_morph_patterns('היום')
    assert rx_basic is not None and rx_morph is not None
    assert rx_basic.pattern.count(torah_engine._VALID_HEB_PREFIX_RX) == 1
    assert rx_morph.pattern.count(torah_engine._VALID_HEB_PREFIX_RX) == 1
    assert rx_basic.match('היום')
    assert rx_basic.match('והיום')
    assert rx_morph.match('היומים')


@pytest.mark.django_db(transaction=True)
def test_fts5_probe_passes_with_spaced_tanakh_and_rejects_spaceless_tanakh():
    TorahText.objects.create(
        book='בראשית',
        chapter='1',
        verse='1',
        text_with_nikkud='<big>בְּ</big>רֵאשִׁ֖ית בָּרָ֣א אֱלֹהִ֑ים',
        clean_text='בראשית ברא אלהים',
    )
    TorahText.objects.create(
        book='ברכות',
        chapter='1',
        verse='1',
        text_with_nikkud='מאימתי קורין את שמע בערבית',
        clean_text='מאימתי קורין את שמע בערבית',
    )

    res_ok = ensure_clean_fts5_index()
    assert res_ok['ok'] is True
    assert _get_verified_fts_table(force_recheck=True) == 'articles_torahtext_clean_fts'

    # Simulate old spaceless Tanakh regression: probe must reject FTS5
    TorahText.objects.filter(book='בראשית').update(clean_text='בראשיתבראאלהים')
    res_bad = ensure_clean_fts5_index()
    assert res_bad['ok'] is False
    assert _get_verified_fts_table(force_recheck=True) is None


@pytest.mark.django_db(transaction=True)
def test_exact_search_in_torah_with_fts5_finds_hayom_bereshit_and_phrase(client):
    TorahText.objects.create(
        book='בראשית',
        chapter='1',
        verse='1',
        text_with_nikkud='<big>בְּ</big>רֵאשִׁ֖ית בָּרָ֣א אֱלֹהִ֑ים אֵ֥ת הַשָּׁמַ֖יִם וְאֵ֥ת הָאָֽרֶץ׃',
        clean_text='בראשית ברא אלהים את השמים ואת הארץ',
    )
    TorahText.objects.create(
        book='בראשית',
        chapter='1',
        verse='14',
        text_with_nikkud='לְהַבְדִּ֕יל בֵּ֥ין הַיּ֖וֹם וּבֵ֣ין הַלָּ֑יְלָה',
        clean_text='להבדיל בין היום ובין הלילה',
    )
    TorahText.objects.create(
        book='בראשית',
        chapter='1',
        verse='15',
        text_with_nikkud='וְהַיּוֹם הַזֶּה גָּדוֹל',
        clean_text='והיום הזה גדול',
    )
    TorahText.objects.create(
        book='דברים',
        chapter='6',
        verse='4',
        text_with_nikkud='שְׁמַ֖ע יִשְׂרָאֵ֑ל',
        clean_text='שמע ישראל',
    )

    assert ensure_clean_fts5_index()['ok'] is True
    url = reverse('articles:tanakh_advanced_search_api')

    # Single exact word in Torah: must find 1:14 and NOT 1:15 ('והיום')
    resp = client.get(url, {'type': 'text_exact', 'q': 'היום', 'book': 'torah', 'exact': 'true'}, secure=True)
    assert resp.status_code == 200
    data = resp.json()
    assert data['total'] == 1
    assert data['results'][0]['raw_verse'] == '14'
    assert '<mark' in data['results'][0]['text']

    # Multi-word exact phrase
    resp_phrase = client.get(url, {'type': 'text_exact', 'q': 'בין היום', 'book': 'torah', 'exact': 'true'}, secure=True)
    assert resp_phrase.status_code == 200
    data_phrase = resp_phrase.json()
    assert data_phrase['total'] == 1
    assert '<mark' in data_phrase['results'][0]['text']

    # Bereshit with <big> tag in nikkud
    resp_bereshit = client.get(url, {'type': 'text_exact', 'q': 'בראשית', 'book': 'torah', 'exact': 'true'}, secure=True)
    assert resp_bereshit.status_code == 200
    data_bereshit = resp_bereshit.json()
    assert data_bereshit['total'] == 1
    assert '<mark' in data_bereshit['results'][0]['text']


@pytest.mark.django_db(transaction=True)
def test_broad_fuzzy_and_fuzzy_morph_search_modes(client):
    TorahText.objects.create(
        book='בראשית',
        chapter='1',
        verse='14',
        text_with_nikkud='בֵּ֥ין הַיּ֖וֹם וּבֵ֣ין הַלָּ֑יְלָה',
        clean_text='בין היום ובין הלילה',
    )
    TorahText.objects.create(
        book='בראשית',
        chapter='1',
        verse='15',
        text_with_nikkud='וְהַיּוֹם הַזֶּה',
        clean_text='והיום הזה',
    )
    TorahText.objects.create(
        book='בראשית',
        chapter='1',
        verse='16',
        text_with_nikkud='כָּל הַיּוֹמִים הָאֵלֶּה',
        clean_text='כל היומים האלה',
    )
    TorahText.objects.create(
        book='בראשית',
        chapter='1',
        verse='17',
        text_with_nikkud='מִלָּה אַחֶרֶת לְגַמְרֵי',
        clean_text='מלה אחרת לגמרי',
    )

    url = reverse('articles:tanakh_advanced_search_api')

    resp_broad = client.get(url, {'type': 'text_broad', 'q': 'היום', 'book': 'torah', 'exact': 'false'}, secure=True)
    assert resp_broad.status_code == 200
    assert resp_broad.json()['total'] == 2

    resp_fuzzy = client.get(url, {'type': 'text_fuzzy', 'q': 'היום', 'book': 'torah'}, secure=True)
    assert resp_fuzzy.status_code == 200
    assert resp_fuzzy.json()['total'] == 2

    resp_morph = client.get(url, {'type': 'text_fuzzy', 'q': 'היום', 'book': 'torah', 'include_plural': 'true'}, secure=True)
    assert resp_morph.status_code == 200
    morph_data = resp_morph.json()
    assert morph_data['total'] == 3
    assert all('<mark' in r['text'] for r in morph_data['results'])


@pytest.mark.django_db(transaction=True)
def test_two_phase_pagination_and_id_cache_across_pages(client):
    TorahText.objects.create(
        book='בראשית', chapter='1', verse='1',
        text_with_nikkud='בְּרֵאשִׁית בָּרָא אֱלֹהִים', clean_text='בראשית ברא אלהים',
    )
    TorahText.objects.create(
        book='דברים', chapter='6', verse='4',
        text_with_nikkud='שְׁמַע יִשְׂרָאֵל', clean_text='שמע ישראל',
    )
    for v_num in range(1, 13):
        TorahText.objects.create(
            book='בראשית',
            chapter='2',
            verse=str(v_num),
            text_with_nikkud=f'פָּסוּק הַיּוֹם מִסְפָּר {v_num}',
            clean_text='פסוק היום מספר',
        )

    assert ensure_clean_fts5_index()['ok'] is True
    url = reverse('articles:tanakh_advanced_search_api')

    p1 = client.get(url, {'type': 'text_exact', 'q': 'היום', 'book': 'torah', 'exact': 'true', 'page': '1', 'per_page': '10'}, secure=True).json()
    p2 = client.get(url, {'type': 'text_exact', 'q': 'היום', 'book': 'torah', 'exact': 'true', 'page': '2', 'per_page': '10'}, secure=True).json()

    assert p1['total'] == 12 and p1['total_pages'] == 2 and len(p1['results']) == 10
    assert p2['total'] == 12 and p2['total_pages'] == 2 and len(p2['results']) == 2

    p1_verses = {r['raw_verse'] for r in p1['results']}
    p2_verses = {r['raw_verse'] for r in p2['results']}
    assert p1_verses.isdisjoint(p2_verses)
    assert all('<mark' in r['text'] for r in p1['results'] + p2['results'])