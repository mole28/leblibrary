import datetime
import logging

logger = logging.getLogger(__name__)

_CACHED_YEAR_BY_DATE = (None, '')

_HEBREW_NUMERALS = (
    (400, 'ת'), (300, 'ש'), (200, 'ר'), (100, 'ק'),
    (90, 'צ'), (80, 'פ'), (70, 'ע'), (60, 'ס'), (50, 'נ'), (40, 'מ'), (30, 'ל'), (20, 'כ'), (10, 'י'),
    (9, 'ט'), (8, 'ח'), (7, 'ז'), (6, 'ו'), (5, 'ה'), (4, 'ד'), (3, 'ג'), (2, 'ב'), (1, 'א'),
)


def _format_hebrew_year_letters(year_num: int) -> str:
    n = int(year_num) % 1000
    if n <= 0:
        return ''
    chars = []
    while n >= 400:
        chars.append('ת')
        n -= 400
    for val, letter in _HEBREW_NUMERALS:
        if n == 15:
            chars.extend(('ט', 'ו'))
            n = 0
            break
        if n == 16:
            chars.extend(('ט', 'ז'))
            n = 0
            break
        if n >= val:
            chars.append(letter)
            n -= val
    if len(chars) >= 2:
        return ''.join(chars[:-1]) + '״' + chars[-1]
    return ''.join(chars) + '׳'


def _is_hebrew_leap_year(heb_year: int) -> bool:
    return (7 * heb_year + 1) % 19 < 7


def _hebrew_elapsed_days(heb_year: int) -> int:
    months_elapsed = (235 * ((heb_year - 1) // 19)) + (12 * ((heb_year - 1) % 19)) + ((((heb_year - 1) % 19) * 7 + 1) // 19)
    parts_elapsed = 204 + 793 * (months_elapsed % 1080)
    hours_elapsed = 5 + 12 * months_elapsed + 793 * (months_elapsed // 1080) + (parts_elapsed // 1080)
    day = 1 + 29 * months_elapsed + (hours_elapsed // 24)
    parts = 1080 * (hours_elapsed % 24) + (parts_elapsed % 1080)
    if (
        (parts >= 19440)
        or ((day % 7 == 2) and (parts >= 9924) and not _is_hebrew_leap_year(heb_year))
        or ((day % 7 == 1) and (parts >= 16789) and _is_hebrew_leap_year(heb_year - 1))
    ):
        alt_day = day + 1
    else:
        alt_day = day
    if alt_day % 7 in (0, 3, 5):
        alt_day += 1
    return alt_day


def _hebrew_year_start_ordinal(heb_year: int) -> int:
    return _hebrew_elapsed_days(heb_year) - 1373428


def _gregorian_to_hebrew_year_num(g_date: datetime.date) -> int:
    try:
        from pyluach import dates as pyluach_dates
        h_date = pyluach_dates.GregorianDate(g_date.year, g_date.month, g_date.day).to_heb()
        return int(h_date.year)
    except ImportError:
        logger.debug('pyluach unavailable; using built-in Hebrew calendar calculation')
    except Exception:
        logger.warning('pyluach conversion failed; using built-in fallback', exc_info=True)
    ord_day = g_date.toordinal()
    approx = g_date.year + 3760
    while _hebrew_year_start_ordinal(approx + 1) <= ord_day:
        approx += 1
    while _hebrew_year_start_ordinal(approx) > ord_day:
        approx -= 1
    return approx


def get_current_hebrew_year(g_date=None) -> str:
    global _CACHED_YEAR_BY_DATE
    target_date = g_date or datetime.date.today()
    if g_date is None and _CACHED_YEAR_BY_DATE[0] == target_date and _CACHED_YEAR_BY_DATE[1]:
        return _CACHED_YEAR_BY_DATE[1]
    heb_year_str = _format_hebrew_year_letters(_gregorian_to_hebrew_year_num(target_date))
    if g_date is None:
        _CACHED_YEAR_BY_DATE = (target_date, heb_year_str)
    return heb_year_str


def hebrew_year(request):
    heb_year = get_current_hebrew_year()
    return {
        'current_year': heb_year,
        'current_hebrew_year': heb_year,
    }