"""Bilingual (zh/en) date phrase extraction for `when`/`deadline` (SPEC section F).

Pure functions. `now` is always passed in as a naive local datetime.
Matching runs on a normalised copy of the text that keeps every character position
(full-width digits -> ASCII, lower case), so spans map 1:1 back to the original for `remaining`.
"""

import calendar
import re
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

WHEN_VOCAB = ("today", "tomorrow", "evening", "anytime", "someday")  # plus yyyy-mm-dd[@HH:MM]
EVENING_TIME = "18:00"
EOD_TIME = "18:00"

_CJK_RANGES = ((0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x3000, 0x303F), (0xFF00, 0xFFEF))
_FULLWIDTH = {chr(0xFF10 + i): str(i) for i in range(10)}
_FULLWIDTH.update({"：": ":", "／": "/", "－": "-", "＋": "+", "＠": "@"})

_CN_DIGITS = {"零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_NUM = r"(?:\d{1,4}|[零〇一二两三四五六七八九十]{1,4})"
_YEAR = r"(?:\d{4}|[零〇一二三四五六七八九]{4})"
_EN_SMALL = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
             "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10}
_CN_WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
_EN_WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1, "wednesday": 2, "wed": 2,
                "thursday": 3, "thurs": 3, "thur": 3, "thu": 3, "friday": 4, "fri": 4,
                "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}
_EN_WEEKDAY_RE = "monday|mon|tuesday|tues|tue|wednesday|wed|thursday|thurs|thur|thu|friday|fri|saturday|sat|sunday|sun"
_EN_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
              "sep": 9, "oct": 10, "nov": 11, "dec": 12}
_EN_MONTH_RE = ("january|jan|february|feb|march|mar|april|apr|may|june|jun|july|jul|august|aug|"
                "september|sept|sep|october|oct|november|nov|december|dec")


def detect_language(text: str) -> str:
    """"zh" when any character falls in the CJK ranges of R16, else "en"."""
    for char in text:
        code = ord(char)
        for low, high in _CJK_RANGES:
            if low <= code <= high:
                return "zh"
    return "en"


def _normalise(text: str) -> str:
    """Same-length normalisation: full-width digits/punctuation to ASCII, lower case."""
    out = []
    for char in text:
        char = _FULLWIDTH.get(char, char)
        lowered = char.lower()
        out.append(lowered if len(lowered) == 1 else char)
    return "".join(out)


def _num(token: str) -> int:
    """Parse ASCII digits or Chinese numerals (一, 十一, 二十三, 两, 二零二六)."""
    if token.isdigit():
        return int(token)
    total = 0
    current = 0
    for char in token:
        if char == "十":
            total += (current or 1) * 10
            current = 0
        elif char in _CN_DIGITS:
            current = current * 10 + _CN_DIGITS[char]
        else:
            raise ValueError(f"not a number: {token}")
    return total + current


def add_offset(day: date, spec: str) -> date:
    """"+3d" -> +3 days, "+2w" -> +14 days, "-1d" -> -1 day. Anything else raises ValueError.

    Strict: surrounding whitespace is an error too (callers strip their own input).
    """
    match = re.match(r"^([+-])(\d+)([dw])$", spec)
    if not match:
        raise ValueError(f"invalid offset '{spec}'; expected +Nd or +Nw")
    amount = int(match.group(2)) * (7 if match.group(3) == "w" else 1)
    if match.group(1) == "-":
        amount = -amount
    return day + timedelta(days=amount)


def _add_months(day: date, months: int) -> date:
    month_index = day.month - 1 + months
    year = day.year + month_index // 12
    month = month_index % 12 + 1
    last = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last))


def _month_end(day: date) -> date:
    return date(day.year, day.month, calendar.monthrange(day.year, day.month)[1])


class _Piece:
    """One matched fragment: a date, a time, a period word, or a special word."""

    __slots__ = ("start", "end", "date", "special", "hour", "minute", "period", "evening", "eod", "marker")

    def __init__(self, date_value: Any = None, special: Optional[str] = None, hour: Optional[int] = None,
                 minute: int = 0, period: Optional[str] = None, evening: bool = False,
                 eod: bool = False, marker: bool = False) -> None:
        self.start = 0
        self.end = 0
        self.date = date_value          # None | "today" | "tomorrow" | datetime.date
        self.special = special          # None | "anytime" | "someday"
        self.hour = hour
        self.minute = minute
        self.period = period            # None | "am" | "pm" | "noon" | "keep"
        self.evening = evening
        self.eod = eod
        self.marker = marker            # a bare period word (上午/下午/morning) with no time of its own

    @property
    def has_time(self) -> bool:
        return self.hour is not None or self.eod or self.period == "noon"


def _weekday_after(today: date, weekday: int) -> date:
    """Next occurrence strictly after today (R3)."""
    delta = (weekday - today.weekday()) % 7 or 7
    return today + timedelta(days=delta)


def _week_monday(today: date, weeks_ahead: int) -> date:
    return today - timedelta(days=today.weekday()) + timedelta(days=7 * weeks_ahead)


def _weekday_with_prefix(today: date, weekday: int, prefix: str) -> date:
    """prefix: "" (bare, R3), "this" (R4 this week), "next" / "next2" (R4 next weeks)."""
    if prefix == "next":
        return _week_monday(today, 1) + timedelta(days=weekday)
    if prefix == "next2":
        return _week_monday(today, 2) + timedelta(days=weekday)
    if prefix == "this":
        candidate = _week_monday(today, 0) + timedelta(days=weekday)
        return candidate if candidate >= today else _weekday_after(today, weekday)
    return _weekday_after(today, weekday)


def _weekend(today: date, prefix: str) -> date:
    if prefix == "next":
        return _week_monday(today, 1) + timedelta(days=5)
    if prefix == "next2":
        return _week_monday(today, 2) + timedelta(days=5)
    saturday = _week_monday(today, 0) + timedelta(days=5)
    return saturday if saturday >= today else saturday + timedelta(days=7)


def _cn_prefix(text: Optional[str]) -> str:
    if not text:
        return ""
    if text.startswith("下下"):
        return "next2"
    if text.startswith("下"):
        return "next"
    return "this"


def _en_prefix(text: Optional[str]) -> str:
    if not text:
        return ""
    return "next" if text.strip() == "next" else "this"


def _month_day(today: date, month: int, day: int, year: Optional[int]) -> Optional[date]:
    """Resolve a month/day, choosing this year unless the date already passed (R8)."""
    if not 1 <= month <= 12 or not 1 <= day <= 31:
        return None
    years = [year] if year else [today.year, today.year + 1]
    for candidate_year in years:
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        if year or candidate >= today:
            return candidate
    return None


def _period_of(word: Optional[str]) -> Optional[str]:
    if not word:
        return None
    if word in ("上午", "早上", "早晨", "清晨", "morning", "am", "a.m."):
        return "am"
    if word in ("凌晨",):
        return "keep"
    if word in ("中午", "noon", "midday"):
        return "noon"
    if word in ("下午", "afternoon", "pm", "p.m."):
        return "pm"
    return "evening"  # 晚上 傍晚 今晚 明晚 晚 evening tonight night


# --- pattern handlers: each takes (match, today) and returns a _Piece or None ----------------

def _h_ymd(match: "re.Match", today: date) -> Optional[_Piece]:
    try:
        return _Piece(date(_num(match.group(1)), _num(match.group(2)), _num(match.group(3))))
    except ValueError:
        return None


def _h_md(match: "re.Match", today: date) -> Optional[_Piece]:
    try:
        resolved = _month_day(today, _num(match.group(1)), _num(match.group(2)), None)
    except ValueError:
        return None
    return _Piece(resolved) if resolved else None


def _h_en_month_first(match: "re.Match", today: date) -> Optional[_Piece]:
    month = _EN_MONTHS[match.group(1)[:3]]
    year = int(match.group(3)) if match.group(3) else None
    resolved = _month_day(today, month, int(match.group(2)), year)
    return _Piece(resolved) if resolved else None


def _h_en_day_first(match: "re.Match", today: date) -> Optional[_Piece]:
    month = _EN_MONTHS[match.group(2)[:3]]
    year = int(match.group(3)) if match.group(3) else None
    resolved = _month_day(today, month, int(match.group(1)), year)
    return _Piece(resolved) if resolved else None


def _h_relative_day(match: "re.Match", today: date) -> Optional[_Piece]:
    word = match.group(0)
    if word in ("今天", "今日", "today"):
        return _Piece("today")
    if word in ("明天", "明日", "tomorrow", "tmr", "tmrw"):
        return _Piece("tomorrow")
    if word == "大后天":
        return _Piece(today + timedelta(days=3))
    if word == "后天" or word.endswith("day after tomorrow"):
        return _Piece(today + timedelta(days=2))
    if word in ("今晚", "tonight", "this evening"):
        return _Piece("today", evening=True, period="evening")
    if word == "明晚":
        return _Piece("tomorrow", evening=True, period="evening")
    return None


def _is_past(prefix: Optional[str]) -> bool:
    """上周X / last X name a past day: not a date, left in `remaining` (the whole phrase is consumed
    by one match so the bare weekday inside it cannot re-match)."""
    return bool(prefix) and (prefix.startswith("上") or prefix.strip() == "last")


def _h_cn_weekend(match: "re.Match", today: date) -> Optional[_Piece]:
    if _is_past(match.group(1)):
        return None
    return _Piece(_weekend(today, _cn_prefix(match.group(1))))


def _h_en_weekend(match: "re.Match", today: date) -> Optional[_Piece]:
    if _is_past(match.group(1)):
        return None
    return _Piece(_weekend(today, _en_prefix(match.group(1))))


def _weekday_piece(today: date, weekday: int, prefix: str) -> _Piece:
    """R4: 这周X / this X naming today's weekday is `today`, not an ISO date."""
    resolved = _weekday_with_prefix(today, weekday, prefix)
    if prefix == "this" and resolved == today:
        return _Piece("today")
    return _Piece(resolved)


def _h_cn_weekday(match: "re.Match", today: date) -> Optional[_Piece]:
    if _is_past(match.group(1)):
        return None
    return _weekday_piece(today, _CN_WEEKDAYS[match.group(2)], _cn_prefix(match.group(1)))


def _h_en_weekday(match: "re.Match", today: date) -> Optional[_Piece]:
    if _is_past(match.group(1)):
        return None
    return _weekday_piece(today, _EN_WEEKDAYS[match.group(2)], _en_prefix(match.group(1)))


def _h_next_week(match: "re.Match", today: date) -> Optional[_Piece]:
    weeks = 2 if match.group(0).startswith("下下") else 1
    return _Piece(_week_monday(today, weeks))


def _h_month_phrase(match: "re.Match", today: date) -> Optional[_Piece]:
    word = match.group(0)
    first_of_next = _add_months(today.replace(day=1), 1)
    this_end = word in ("月底", "月末", "本月底", "本月末", "这月底", "这个月底", "eom")
    if this_end or (word.startswith("end of") and "next" not in word):
        return _Piece(_month_end(today))
    next_end = word in ("下月底", "下个月底", "下月末", "下个月末")
    if next_end or (word.startswith("end of") and "next" in word):
        return _Piece(_month_end(first_of_next))
    if word == "月初":
        return _Piece("today") if today.day == 1 else _Piece(first_of_next)
    # 下月初 / 下个月初 / early|beginning of|start of next month / 下个月 / 下月 / next month
    return _Piece(first_of_next)


def _month_part(today: date, month: int, part: str) -> Optional[_Piece]:
    """N月底/N月末/end of <month> -> last day of that month; N月初 -> its 1st. R8 year choice is applied
    to the day emitted (the END day for 底/末), so 9月底 on 2026-09-09 stays 2026-09-30."""
    if not 1 <= month <= 12:
        return None
    if part == "初":
        resolved = _month_day(today, month, 1, None)
        if resolved is None:
            return None
        return _Piece("today") if resolved == today else _Piece(resolved)
    end = _month_end(date(today.year, month, 1))
    if end < today:
        end = _month_end(date(today.year + 1, month, 1))
    return _Piece(end)


def _h_cn_month_part(match: "re.Match", today: date) -> Optional[_Piece]:
    try:
        return _month_part(today, _num(match.group(1)), match.group(2))
    except ValueError:
        return None


def _h_en_month_end(match: "re.Match", today: date) -> Optional[_Piece]:
    return _month_part(today, _EN_MONTHS[match.group(1)[:3]], "底")


def _h_next_month_day(match: "re.Match", today: date) -> Optional[_Piece]:
    """下个月5号 / 下月5日 -> that day of next month."""
    first_of_next = _add_months(today.replace(day=1), 1)
    try:
        return _Piece(first_of_next.replace(day=_num(match.group(1))))
    except ValueError:
        return None


def _h_cn_offset_days(match: "re.Match", today: date) -> Optional[_Piece]:
    try:
        return _Piece(today + timedelta(days=_num(match.group(1))))
    except ValueError:
        return None


def _h_cn_offset_weeks(match: "re.Match", today: date) -> Optional[_Piece]:
    try:
        return _Piece(today + timedelta(days=7 * _num(match.group(1))))
    except ValueError:
        return None


def _h_cn_offset_months(match: "re.Match", today: date) -> Optional[_Piece]:
    try:
        return _Piece(_add_months(today, _num(match.group(1))))
    except ValueError:
        return None


def _h_en_offset(match: "re.Match", today: date) -> Optional[_Piece]:
    raw = match.group(1)
    amount = int(raw) if raw.isdigit() else _EN_SMALL.get(raw)
    if amount is None:
        return None
    unit = match.group(2)
    if unit.startswith("d"):
        return _Piece(today + timedelta(days=amount))
    if unit.startswith("w"):
        return _Piece(today + timedelta(days=7 * amount))
    return _Piece(_add_months(today, amount))


def _h_plus_offset(match: "re.Match", today: date) -> Optional[_Piece]:
    amount = int(match.group(1))
    unit = match.group(2)
    if unit == "d":
        return _Piece(today + timedelta(days=amount))
    if unit == "w":
        return _Piece(today + timedelta(days=7 * amount))
    return _Piece(_add_months(today, amount))


def _h_cn_time(match: "re.Match", today: date) -> Optional[_Piece]:
    period_word = match.group(1)
    try:
        hour = _num(match.group(2))
        minute = 0
        if match.group(3):
            minute = 30
        elif match.group(4):
            minute = _num(match.group(4))     # M分 (digits or Chinese numerals)
        elif match.group(5):
            minute = int(match.group(5))      # bare two digits: 3点15
    except ValueError:
        return None
    if hour > 24 or minute > 59:
        return None
    piece = _Piece(hour=hour, minute=minute, period=_period_of(period_word) or "keep")
    if period_word in ("今晚",):
        piece.date = "today"
    elif period_word in ("明晚",):
        piece.date = "tomorrow"
    piece.evening = piece.period == "evening"
    return piece


def _h_en_time(match: "re.Match", today: date) -> Optional[_Piece]:
    hour = int(match.group(1))
    minute = int(match.group(2)) if match.group(2) else 0
    suffix = (match.group(3) or "").replace(".", "")
    if hour > 24 or minute > 59:
        return None
    period = "keep" if not suffix else ("am" if suffix == "am" else "pm")
    return _Piece(hour=hour, minute=minute, period=period)


def _h_eod(match: "re.Match", today: date) -> Optional[_Piece]:
    return _Piece(eod=True)


def _h_evening_word(match: "re.Match", today: date) -> Optional[_Piece]:
    return _Piece(evening=True, period="evening")


def _h_period_word(match: "re.Match", today: date) -> Optional[_Piece]:
    period = _period_of(match.group(0))
    return _Piece(period=period, marker=(period != "noon"))


def _h_anytime(match: "re.Match", today: date) -> Optional[_Piece]:
    return _Piece(special="anytime")


def _h_someday(match: "re.Match", today: date) -> Optional[_Piece]:
    return _Piece(special="someday")


_CN_PERIOD = "上午|早上|早晨|清晨|凌晨|中午|下午|傍晚|晚上|今晚|明晚|晚"
_EN = r"(?<![a-z])"          # start of an English word (the text is lower-cased already)
_END = r"(?![a-z])"          # end of an English word
_PATTERNS: List[Tuple["re.Pattern", Callable[["re.Match", date], Optional[_Piece]]]] = [
    # explicit dates with a year (R8)
    (re.compile(r"(?<![\d/.-])(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?![\d/.])"), _h_ymd),
    (re.compile(_YEAR + r"年(" + _NUM + r")月(" + _NUM + r")(?:日|号)?"), lambda m, t: _h_ymd(_Y(m), t)),
    # month + day (R8)
    (re.compile(r"(?<![\d/])(" + _NUM + r")月(" + _NUM + r")(?:日|号)"), _h_md),
    (re.compile(r"(?<![\d/])(\d{1,2})/(\d{1,2})(?![\d/])"), _h_md),
    (re.compile(_EN + r"(" + _EN_MONTH_RE + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?!\d)(?:,?\s+(\d{4})(?!\d))?"), _h_en_month_first),
    (re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _EN_MONTH_RE + r")" + _END + r"\.?(?:,?\s+(\d{4})(?!\d))?"), _h_en_day_first),
    # times (R9); Chinese times carry their period word so 今晚8点 is one piece
    # minutes: 半, then M分 (so 分 joins the span), then bare two digits (3点15)
    (re.compile(r"(" + _CN_PERIOD + r")?\s*(" + _NUM + r")\s*(?:点|时|時)(?!间|候|期|儿)(?:(半)|\s*(" + _NUM + r")分|(\d{2})(?!\d))?"), _h_cn_time),
    (re.compile(r"(?<![\d:])(\d{1,2})(?::(\d{2}))?\s*(a\.m\.|p\.m\.|am|pm)" + _END), _h_en_time),
    (re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])()"), _h_en_time),
    (re.compile(_EN + r"(?:eod|cob|end of (?:the )?day|close of business)" + _END + r"|下班"), _h_eod),
    # relative days (R2, R11)
    (re.compile(r"大后天|后天|明天|明日|今天|今日|今晚|明晚|" + _EN + r"(?:(?:the\s+)?day after tomorrow|tomorrow|tmrw|tmr|today|tonight|this evening)" + _END), _h_relative_day),
    # weekends and weekdays (R3, R4, R5)
    # 上/last is matched so the whole past phrase is consumed; its handler returns None (not a date)
    (re.compile(r"(上个?|下下个?|下个?|这个?|本)?(?:周|星期|礼拜|週|禮拜)末"), _h_cn_weekend),
    (re.compile(_EN + r"(?:(last|next|this)\s+)?weekend" + _END), _h_en_weekend),
    (re.compile(r"(上个?|下下个?|下个?|这个?|本)?(?:周|星期|礼拜|週|禮拜)([一二三四五六日天])"), _h_cn_weekday),
    (re.compile(_EN + r"(?:(last|next|this)\s+)?(" + _EN_WEEKDAY_RE + r")" + _END + r"\.?"), _h_en_weekday),
    # next week (R7)
    (re.compile(r"下下个?(?:周|星期|礼拜|週)|下个?(?:周|星期|礼拜|週)|" + _EN + r"next week" + _END), _h_next_week),
    # N月底 / N月初 / 下个月N号 / end of <month> must claim their digits before the bare 月底/月初/下个月 row
    (re.compile(r"(?<![\d/])(" + _NUM + r")月(底|末|初)"), _h_cn_month_part),
    (re.compile(r"下个?月(" + _NUM + r")(?:日|号)"), _h_next_month_day),
    (re.compile(_EN + r"end of (?:the )?(" + _EN_MONTH_RE + r")" + _END), _h_en_month_end),
    # month phrases (R6)
    (re.compile(r"下个?月底|下个?月末|本月底|本月末|这个?月底|月底|月末|下个?月初|月初|下个?月|"
                + _EN + r"(?:end of (?:the )?next month|end of (?:the )?(?:this )?month|eom|"
                + r"(?:early|beginning of|start of) (?:the )?next month|next month)" + _END), _h_month_phrase),
    # offsets (R7)
    (re.compile(r"(" + _NUM + r")\s*个?(?:天|日)(?:以|之)?后"), _h_cn_offset_days),
    (re.compile(r"(" + _NUM + r")\s*个?(?:周|星期|礼拜|週)(?:以|之)?后"), _h_cn_offset_weeks),
    (re.compile(r"(" + _NUM + r")\s*个月(?:以|之)?后"), _h_cn_offset_months),
    (re.compile(_EN + r"in\s+(\d+|a|an|one|two|three|four|five|six|seven|eight|nine|ten)\s+(days?|weeks?|months?)" + _END), _h_en_offset),
    (re.compile(r"\+(\d+)\s*([dwm])" + _END), _h_plus_offset),
    # bare period words (R9/R11)
    (re.compile(r"晚上|傍晚|晚间|夜里|夜晚|" + _EN + r"(?:evening|tonight|night)" + _END), _h_evening_word),
    (re.compile(r"上午|早上|早晨|清晨|凌晨|中午|下午|" + _EN + r"(?:morning|afternoon|noon|midday)" + _END), _h_period_word),
    # anytime / someday (R12)
    # 有空 is not the 有空 of 有空调/有空间/有空位; 'later today/this week/on' is ordinary text, not someday
    (re.compile(r"随便什么时候|什么时候都行|什么时候都可以|有空的时候|有空再|有空(?![调间位格隙缺档])|"
                + _EN + r"(?:anytime|any time|whenever|no rush)" + _END), _h_anytime),
    (re.compile(r"以后再说|有时间再说|改天再说|改天|以后有空|以后|"
                + _EN + r"(?:someday|some day|later(?!\s+(?:today|tonight|this|on|in|at))|eventually)" + _END), _h_someday),
]


class _Y:
    """Adapter so the 年月日 handler can reuse _h_ymd (groups 1..3 = year, month, day)."""

    def __init__(self, match: "re.Match") -> None:
        self._groups = (match.group(0)[: match.group(0).index("年")], match.group(1), match.group(2))

    def group(self, index: int) -> str:
        return self._groups[index - 1]


_MULTIWORD_KEYWORDS = re.compile(_EN + r"(?:no|not) later than" + _END)
# 'by' after a phrasal verb (drop by / stop by / come by / swing by / pass by) is not a deadline keyword;
# Python re needs one fixed-width lookbehind per verb.
_BEFORE_KEYWORD = re.compile(
    r"(?:(?<![a-z])(?:deadline|ddl|due(?: on| by| date)?|(?<!drop )(?<!stop )(?<!come )(?<!swing )(?<!pass )by|"
    r"before|until|no later than|not later than)|"
    r"截止日期|截止日|截止到|截止于|截止|截至|最晚|到期日|到期)"
    r"\s*[:：]?\s*(?:(?:the|on|at)\s+|到|于|是|在)?\s*$"
)
_AFTER_KEYWORD = re.compile(
    r"^\s*(?:之前|以前|为止|到期|截止|截至|"
    r"前(?![往面后台方进天年夕门线辈景途端程沿锋所者列排置缀奏言兆驱身世夜文人额臂胸轮脚腿脸头部边]))"
)
_REMINDER = re.compile(r"提醒我|提醒|" + _EN + r"(?:remind me to|remind me|reminder|remind)" + _END)
_JOIN_GAP = re.compile(r"^[\s，,、]*(?:at|@|的|在)?[\s，,、]*$")   # "tomorrow, at 3pm" / "明天，下午3点"
# A joiner that ends the ordinary words between an absorbed date and its time (`tomorrow call mom at 3pm`,
# `明天开会，在下午3点`) belongs to the time phrase: without it `remaining` would end in a dangling "at".
_JOINER_TAIL = re.compile(r"(?<![a-z])(?:at|@|的|在)[\s，,、]*$")
_TRIM = "\t\n\r ，,、"


class _Cluster:
    """Adjacent pieces that describe one moment: at most one date, one hour, plus period words."""

    def __init__(self, piece: _Piece) -> None:
        self.pieces = [piece]
        self.start = piece.start
        self.end = piece.end
        self.spans: List[Tuple[int, int]] = []   # absorbed time-only clusters that sit later in the text

    @property
    def has_time(self) -> bool:
        return self.hour is not None or self.eod or self.period == "noon"

    @property
    def last_end(self) -> int:
        return self.spans[-1][1] if self.spans else self.end

    def can_absorb(self, other: "_Cluster") -> bool:
        """A date-only cluster takes the next time-only cluster even across ordinary words:
        `明天开会，下午3点` / `tomorrow before 5pm` describe one moment."""
        if self.spans or self.special is not None or other.special is not None:
            return False
        if self.date is None or self.has_time or self.evening:
            return False
        return other.date is None and other.has_time

    def absorb(self, other: "_Cluster", norm: str) -> None:
        self.pieces.extend(other.pieces)
        start = other.start
        joiner = _JOINER_TAIL.search(norm[self.end:other.start])
        if joiner:
            start = self.end + joiner.start()   # take the trailing at/@/的/在 (plus its punctuation) with the time
        self.spans.append((start, other.end))

    def can_join(self, piece: _Piece, norm: str) -> bool:
        if not _JOIN_GAP.match(norm[self.end:piece.start]):
            return False
        if piece.special or self.special:
            return False
        if piece.date is not None and self.date is not None:
            return False
        if piece.hour is not None and self.hour is not None:
            return False
        if piece.eod and (self.eod or self.hour is not None):
            return False
        return True

    def add(self, piece: _Piece) -> None:
        self.pieces.append(piece)
        self.end = piece.end

    @property
    def special(self) -> Optional[str]:
        return next((p.special for p in self.pieces if p.special), None)

    @property
    def date(self) -> Any:
        return next((p.date for p in self.pieces if p.date is not None), None)

    @property
    def hour(self) -> Optional[int]:
        return next((p.hour for p in self.pieces if p.hour is not None), None)

    @property
    def minute(self) -> int:
        return next((p.minute for p in self.pieces if p.hour is not None), 0)

    @property
    def eod(self) -> bool:
        return any(p.eod for p in self.pieces)

    @property
    def evening(self) -> bool:
        return any(p.evening for p in self.pieces)

    @property
    def period(self) -> Optional[str]:
        hour_piece = next((p for p in self.pieces if p.hour is not None), None)
        if hour_piece is not None and hour_piece.period not in (None, "keep"):
            return hour_piece.period
        other = next((p.period for p in self.pieces if p.period not in (None, "keep")), None)
        return other or "keep"

    @property
    def marker_only(self) -> bool:
        return all(p.marker for p in self.pieces)

    def time(self) -> Optional[Tuple[int, int]]:
        """Resolved (hour, minute) after applying the period word (R9), or None."""
        if self.hour is not None:
            hour, minute, period = self.hour, self.minute, self.period
            if period in ("pm", "evening") and 1 <= hour <= 11:
                hour += 12
            elif period == "am" and hour == 12:
                hour = 0
            elif period == "noon" and hour < 6:
                hour += 12
            if hour == 24:
                hour = 0
            return hour, minute
        if self.eod:
            return 18, 0
        if self.period == "noon":
            return 12, 0
        return None

    def resolve_date(self, now: datetime, time: Optional[Tuple[int, int]]) -> "Optional[date]":
        # String annotation: the class body defines a `date` property above, which would shadow the
        # datetime.date type while Python 3.9/3.10 evaluate this annotation eagerly (TypeError at import).
        today = now.date()
        if self.date == "today":
            return today
        if self.date == "tomorrow":
            return today + timedelta(days=1)
        if isinstance(self.date, date):
            return self.date
        if time is not None:  # time with no date: today if still ahead, else tomorrow (R10)
            return today if time > (now.hour, now.minute) else today + timedelta(days=1)
        return None


def _fmt_time(time: Tuple[int, int]) -> str:
    return f"{time[0]:02d}:{time[1]:02d}"


def _when_value(cluster: _Cluster, now: datetime) -> Tuple[Optional[str], Optional[str]]:
    """(when, reminder) for a non-deadline cluster; (None, None) when it carries no date."""
    if cluster.special:
        return cluster.special, None
    time = cluster.time()
    if time is not None:
        resolved = cluster.resolve_date(now, time)
        return f"{resolved.isoformat()}@{_fmt_time(time)}", _fmt_time(time)
    if cluster.evening:
        if cluster.date in (None, "today"):
            return "evening", None
        resolved = cluster.resolve_date(now, None)
        return f"{resolved.isoformat()}@{EVENING_TIME}", EVENING_TIME
    if cluster.date == "today":
        return "today", None
    if cluster.date == "tomorrow":
        return "tomorrow", None
    if isinstance(cluster.date, date):
        return cluster.date.isoformat(), None
    return None, None


def _deadline_value(cluster: _Cluster, now: datetime) -> Tuple[Optional[str], Optional[str]]:
    """(deadline, reminder) for a cluster adjacent to a deadline keyword; evening/anytime/someday never qualify."""
    if cluster.special:
        return None, None
    time = cluster.time()
    if cluster.evening and time is None:
        if cluster.date in (None, "today"):
            return None, None
        time = (18, 0)
    resolved = cluster.resolve_date(now, time)
    if resolved is None:
        return None, None
    return resolved.isoformat(), (_fmt_time(time) if time else None)


def _scan(norm: str, today: date) -> List[_Piece]:
    # "no later than" is a deadline keyword (R13); claim it first so R12 never reads its "later" as someday.
    claimed: List[Tuple[int, int]] = [m.span() for m in _MULTIWORD_KEYWORDS.finditer(norm)]
    pieces: List[_Piece] = []
    for regex, handler in _PATTERNS:
        for match in regex.finditer(norm):
            start, end = match.span()
            if end == start or any(start < c_end and end > c_start for c_start, c_end in claimed):
                continue
            piece = handler(match, today)
            if piece is None:
                continue
            piece.start, piece.end = start, end
            claimed.append((start, end))
            pieces.append(piece)
    pieces.sort(key=lambda p: p.start)
    return pieces


def _cluster(pieces: List[_Piece], norm: str) -> List[_Cluster]:
    clusters: List[_Cluster] = []
    for piece in pieces:
        if clusters and clusters[-1].can_join(piece, norm):
            clusters[-1].add(piece)
        else:
            clusters.append(_Cluster(piece))
    return clusters


def _remove_spans(text: str, spans: List[Tuple[int, int]]) -> str:
    """R15: drop spans plus adjacent `，,、`/whitespace, collapse whitespace, strip."""
    if not spans:
        return text.strip()
    merged: List[List[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out: List[str] = []
    pos = 0
    for start, end in merged:
        while start > pos and text[start - 1] in _TRIM:
            start -= 1
        while end < len(text) and text[end] in _TRIM:
            end += 1
        out.append(text[pos:max(start, pos)])
        out.append(" ")
        pos = max(end, pos)
    out.append(text[pos:])
    return " ".join("".join(out).split())


def extract_dates(text: str, now: datetime, default_reminder_time: str = "09:00") -> Dict[str, Optional[str]]:
    """Return {"when", "deadline", "reminder", "remaining", "language"} for `text` (section F)."""
    norm = _normalise(text)
    clusters: List[_Cluster] = []
    for cluster in _cluster(_scan(norm, now.date()), norm):
        if cluster.marker_only:
            continue
        if clusters and clusters[-1].can_absorb(cluster):
            clusters[-1].absorb(cluster, norm)
        else:
            clusters.append(cluster)
    removals: List[Tuple[int, int]] = []
    when: Optional[str] = None
    deadline: Optional[str] = None
    when_reminder: Optional[str] = None
    deadline_reminder: Optional[str] = None
    for cluster in clusters:
        spans = [(cluster.start, cluster.end)] + cluster.spans
        before = _BEFORE_KEYWORD.search(norm[:cluster.start])
        after = _AFTER_KEYWORD.match(norm[cluster.last_end:])
        # keywords between an absorbed date and its time: `tomorrow before 5pm`, `周五前下午5点`
        between = _BEFORE_KEYWORD.search(norm[cluster.end:cluster.spans[0][0]]) if cluster.spans else None
        mid_after = _AFTER_KEYWORD.match(norm[cluster.end:]) if cluster.spans else None
        handled = False
        if before or after or between or mid_after:
            value, reminder = _deadline_value(cluster, now)
            if value is not None:
                handled = True
                if deadline is None:
                    deadline, deadline_reminder = value, reminder
                removals.extend(spans)
                if before:
                    removals.append((before.start(), cluster.start))
                if after:
                    removals.append((cluster.last_end, cluster.last_end + after.end()))
                if between:
                    removals.append((cluster.end + between.start(), cluster.spans[0][0]))
                if mid_after:
                    removals.append((cluster.end, cluster.end + mid_after.end()))
        if not handled:
            value, reminder = _when_value(cluster, now)
            if value is None:
                continue
            if when is None:
                when, when_reminder = value, reminder
            removals.extend(spans)
    if when is not None or deadline is not None:
        reminder_words = list(_REMINDER.finditer(norm))
        if reminder_words:
            removals.extend(m.span() for m in reminder_words)
            if when in ("today", "tomorrow") or (when and re.match(r"^\d{4}-\d{2}-\d{2}$", when)):
                day = now.date() if when == "today" else now.date() + timedelta(days=1) if when == "tomorrow" else when
                when = f"{day.isoformat() if isinstance(day, date) else day}@{default_reminder_time}"
                when_reminder = default_reminder_time
    return {
        "when": when,
        "deadline": deadline,
        "reminder": when_reminder or deadline_reminder,
        "remaining": _remove_spans(text, removals),
        "language": detect_language(text),
    }


def parse_when(text: str, now: datetime, default_reminder_time: str = "09:00") -> Optional[str]:
    return extract_dates(text, now, default_reminder_time)["when"]


def parse_deadline(text: str, now: datetime) -> Optional[str]:
    return extract_dates(text, now)["deadline"]
