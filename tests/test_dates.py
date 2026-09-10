"""Date extraction (SPEC section F): all 66 rows of F.3 plus the `remaining` examples."""

from datetime import date, datetime

import pytest

from things_lib import dates
from things_lib.dates import add_offset, detect_language, extract_dates, parse_deadline, parse_when

# (row, input, when, deadline, reminder)
TABLE = [
    (1, "今天", "today", None, None),
    (2, "明天", "tomorrow", None, None),
    (3, "后天", "2026-09-11", None, None),
    (4, "今晚", "evening", None, None),
    (5, "明晚", "2026-09-10@18:00", None, "18:00"),
    (6, "周五", "2026-09-11", None, None),
    (7, "周五晚上", "2026-09-11@18:00", None, "18:00"),
    (8, "下周三", "2026-09-16", None, None),
    (9, "下周一", "2026-09-14", None, None),
    (10, "这周末", "2026-09-12", None, None),
    (11, "周末", "2026-09-12", None, None),
    (12, "月底", "2026-09-30", None, None),
    (13, "下月初", "2026-10-01", None, None),
    (14, "下个月", "2026-10-01", None, None),
    (15, "明天上午9点", "2026-09-10@09:00", None, "09:00"),
    (16, "下午3点", "2026-09-09@15:00", None, "15:00"),
    (17, "晚上8点", "2026-09-09@20:00", None, "20:00"),
    (18, "上午9点", "2026-09-10@09:00", None, "09:00"),
    (19, "三天后", "2026-09-12", None, None),
    (20, "两周后", "2026-09-23", None, None),
    (21, "下周", "2026-09-14", None, None),
    (22, "随便什么时候", "anytime", None, None),
    (23, "以后再说", "someday", None, None),
    (24, "10月1日", "2026-10-01", None, None),
    (25, "十月一日", "2026-10-01", None, None),
    (26, "today", "today", None, None),
    (27, "tomorrow", "tomorrow", None, None),
    (28, "tonight", "evening", None, None),
    (29, "this evening", "evening", None, None),
    (30, "next Tue", "2026-09-15", None, None),
    (31, "next Monday", "2026-09-14", None, None),
    (32, "Friday", "2026-09-11", None, None),
    (33, "fri", "2026-09-11", None, None),
    (34, "EOD Friday", "2026-09-11@18:00", None, "18:00"),
    (35, "end of month", "2026-09-30", None, None),
    (36, "in 2 weeks", "2026-09-23", None, None),
    (37, "in 3 days", "2026-09-12", None, None),
    (38, "next week", "2026-09-14", None, None),
    (39, "someday", "someday", None, None),
    (40, "anytime", "anytime", None, None),
    (41, "2026-10-01", "2026-10-01", None, None),
    (42, "10/1", "2026-10-01", None, None),
    (43, "1/10", "2027-01-10", None, None),
    (44, "+3d", "2026-09-12", None, None),
    (45, "+1w", "2026-09-16", None, None),
    (46, "Wednesday", "2026-09-16", None, None),
    (47, "下下周三", "2026-09-23", None, None),
    (48, "1月5日", "2027-01-05", None, None),
    (49, "tomorrow evening", "2026-09-10@18:00", None, "18:00"),
    (50, "Friday night", "2026-09-11@18:00", None, "18:00"),
    (51, "中午", "2026-09-09@12:00", None, "12:00"),
    (52, "EOD", "2026-09-09@18:00", None, "18:00"),
    (53, "截止周五", None, "2026-09-11", None),
    (54, "周五前", None, "2026-09-11", None),
    (55, "周五之前", None, "2026-09-11", None),
    (56, "due Friday", None, "2026-09-11", None),
    (57, "by next Monday", None, "2026-09-14", None),
    (58, "before 10/1", None, "2026-10-01", None),
    (59, "deadline 2026-10-01", None, "2026-10-01", None),
    (60, "DDL 月底", None, "2026-09-30", None),
    (61, "截止明天", None, "2026-09-10", None),
    (62, "by EOD Friday", None, "2026-09-11", "18:00"),
    (63, "下班前", None, "2026-09-09", "18:00"),
    (64, "下周一开始，周五前完成", "2026-09-14", "2026-09-11", None),
    (65, "提醒我明天交房租", "2026-09-10@09:00", None, "09:00"),
    (66, "Call the dentist", None, None, None),
]
# SPEC F.3 lists row 51 (中午) under "en"; it is CJK text, so detect_language must say "zh" (R16).
ZH_ROWS = set(range(1, 26)) | {47, 48, 51, 53, 54, 55, 60, 61, 63, 64, 65}


def test_table_has_66_rows():
    assert [row[0] for row in TABLE] == list(range(1, 67))


@pytest.mark.parametrize("row,text,when,deadline,reminder", TABLE, ids=[f"row{r[0]}" for r in TABLE])
def test_f3_table(row, text, when, deadline, reminder, now):
    result = extract_dates(text, now)
    assert (result["when"], result["deadline"], result["reminder"]) == (when, deadline, reminder)
    assert result["language"] == ("zh" if row in ZH_ROWS else "en")
    assert parse_when(text, now) == when
    assert parse_deadline(text, now) == deadline


@pytest.mark.parametrize("text,remaining", [
    ("明天下午3点给妈妈打电话", "给妈妈打电话"),
    ("Submit expense report by Friday", "Submit expense report"),
    ("周五前把周报发出去", "把周报发出去"),
    ("提醒我明天交房租", "交房租"),
    ("Call the dentist", "Call the dentist"),
    ("下周一开始，周五前完成", "开始 完成"),
    ("  Call the dentist  ", "Call the dentist"),
])
def test_remaining_examples(text, remaining, now):
    assert extract_dates(text, now)["remaining"] == remaining


def test_remaining_keeps_unattached_keywords(now):
    result = extract_dates("Stop by the store tomorrow", now)
    assert result["when"] == "tomorrow" and result["deadline"] is None
    assert result["remaining"] == "Stop by the store"
    result = extract_dates("三天前的会议纪要", now)
    assert result["when"] is None and result["deadline"] is None
    assert result["remaining"] == "三天前的会议纪要"


def test_combined_when_and_time_and_deadline(now):
    result = extract_dates("下周五晚上8点前交周报", now)
    assert result == {"when": None, "deadline": "2026-09-18", "reminder": "20:00", "remaining": "交周报", "language": "zh"}


def test_reminder_fills_default_time(now):
    assert extract_dates("remind me Friday", now, "08:30")["when"] == "2026-09-11@08:30"
    assert extract_dates("提醒我今天", now)["when"] == "2026-09-09@09:00"


def test_fullwidth_and_chinese_numerals(now):
    assert extract_dates("１０月１日", now)["when"] == "2026-10-01"
    assert extract_dates("十二月三十一日", now)["when"] == "2026-12-31"
    assert extract_dates("二十天后", now)["when"] == "2026-09-29"
    assert extract_dates("下午３点", now)["when"] == "2026-09-09@15:00"


@pytest.mark.parametrize("text,lang", [("买牛奶", "zh"), ("Buy milk", "en"), ("buy 牛奶", "zh"), ("", "en"),
                                       ("，", "zh"), ("１２", "zh"), ("123", "en")])
def test_detect_language(text, lang):
    assert detect_language(text) == lang


def test_add_offset():
    day = date(2026, 9, 9)
    assert add_offset(day, "+3d") == date(2026, 9, 12)
    assert add_offset(day, "+2w") == date(2026, 9, 23)
    assert add_offset(day, "-1d") == date(2026, 9, 8)
    for bad in ("3d", "+3", "+1m", "tomorrow", "", "+d"):
        with pytest.raises(ValueError):
            add_offset(day, bad)


def test_month_end_clamp_and_year_rollover():
    jan31 = datetime(2026, 1, 31, 10, 0)
    assert extract_dates("一个月后", jan31)["when"] == "2026-02-28"
    assert extract_dates("in 1 month", jan31)["when"] == "2026-02-28"
    dec = datetime(2026, 12, 15, 10, 0)
    assert extract_dates("下个月", dec)["when"] == "2027-01-01"
    assert extract_dates("月底", dec)["when"] == "2026-12-31"
    assert extract_dates("下月底", dec)["when"] == "2027-01-31"
    assert extract_dates("1月5日", dec)["when"] == "2027-01-05"
    assert extract_dates("下周", datetime(2026, 12, 30, 9, 0))["when"] == "2027-01-04"
    assert dates._add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_weekday_rules(now):
    # bare weekday strictly after today; this-week variants; next week is the next ISO week
    assert extract_dates("周三", now)["when"] == "2026-09-16"
    assert extract_dates("本周三", now)["when"] == "today"  # R4: this week's X that IS today -> today
    assert extract_dates("这周五", now)["when"] == "2026-09-11"
    assert extract_dates("本周一", now)["when"] == "2026-09-14"  # already passed this week -> next occurrence
    assert extract_dates("this Friday", now)["when"] == "2026-09-11"
    assert extract_dates("next Sunday", now)["when"] == "2026-09-20"
    assert extract_dates("星期日", now)["when"] == "2026-09-13"
    assert extract_dates("下周末", now)["when"] == "2026-09-19"
    assert extract_dates("next weekend", now)["when"] == "2026-09-19"


def test_time_rules(now):
    assert extract_dates("8点半", now)["when"] == "2026-09-10@08:30"
    assert extract_dates("下午3点15分", now)["when"] == "2026-09-09@15:15"
    assert extract_dates("下午3点15分", now)["remaining"] == ""          # 分 belongs to the time span
    assert extract_dates("afternoon 3:30", now)["when"] == "2026-09-09@15:30"
    assert extract_dates("tomorrow afternoon 3:30", now)["when"] == "2026-09-10@15:30"
    assert extract_dates("3pm", now)["when"] == "2026-09-09@15:00"
    assert extract_dates("9 am", now)["when"] == "2026-09-10@09:00"
    assert extract_dates("14:30", now)["when"] == "2026-09-09@14:30"
    assert extract_dates("tomorrow 7:15pm", now)["when"] == "2026-09-10@19:15"
    assert extract_dates("凌晨2点", now)["when"] == "2026-09-10@02:00"
    assert extract_dates("今晚8点", now)["when"] == "2026-09-09@20:00"
    assert extract_dates("noon", now)["reminder"] == "12:00"


# Audit regressions (pre-release review). (text, when, deadline, reminder, remaining)
AUDIT_ROWS = [
    # N月底 / N月初 / 下个月N号 used to fall back to the bare 月底/月初/下个月 rule and leak the digits
    ("11月底前交", None, "2026-11-30", None, "交"),
    ("11月底", "2026-11-30", None, None, ""),
    ("十一月底", "2026-11-30", None, None, ""),
    ("9月底", "2026-09-30", None, None, ""),            # R8 applied to the end day: not next year
    ("3月初", "2027-03-01", None, None, ""),
    ("10月初开工", "2026-10-01", None, None, "开工"),
    ("下个月5号", "2026-10-05", None, None, ""),
    ("下月5日交房租", "2026-10-05", None, None, "交房租"),
    ("Pay by end of October", None, "2026-10-31", None, "Pay"),
    # 'afternoon' is pm, not am
    ("afternoon 3:30", "2026-09-09@15:30", None, "15:30", ""),
    # H点M分: 分 is part of the time span
    ("下午3点15分开会", "2026-09-09@15:15", None, "15:15", "开会"),
    ("晚上8点二十分开会", "2026-09-09@20:20", None, "20:20", "开会"),
    ("下午3点15", "2026-09-09@15:15", None, "15:15", ""),
    # 上周X / last X are past references, never dates; a later real date still wins
    ("上周五", None, None, None, "上周五"),
    ("last Friday", None, None, None, "last Friday"),
    ("上周末", None, None, None, "上周末"),
    ("整理上周五会议纪要", None, None, None, "整理上周五会议纪要"),
    ("上周五的会议纪要今天整理", "today", None, None, "上周五的会议纪要 整理"),
    ("follow up on last Monday's call tomorrow", "tomorrow", None, None, "follow up on last Monday's call"),
    # a date-only phrase absorbs the following time-only phrase, deadline keyword in between or not
    ("tomorrow before 5pm", None, "2026-09-10", "17:00", ""),
    ("Friday by 5pm", None, "2026-09-11", "17:00", ""),
    ("tomorrow by noon", None, "2026-09-10", "12:00", ""),
    ("周五前下午5点", None, "2026-09-11", "17:00", ""),
    ("下周三之前交报告，下午5点", None, "2026-09-16", "17:00", "交报告"),
    ("明天开会，下午3点", "2026-09-10@15:00", None, "15:00", "开会"),
    ("tomorrow call mom at 3pm", "2026-09-10@15:00", None, "15:00", "call mom"),
    ("Friday dentist 2pm", "2026-09-11@14:00", None, "14:00", "dentist"),
    # finding 2020: the joiner between the ordinary words and the absorbed time goes with the time
    ("Friday dentist at 2pm", "2026-09-11@14:00", None, "14:00", "dentist"),
    ("明天开会，在下午3点", "2026-09-10@15:00", None, "15:00", "开会"),
    ("明天开会的下午3点", "2026-09-10@15:00", None, "15:00", "开会"),
    ("tomorrow chat 3pm", "2026-09-10@15:00", None, "15:00", "chat"),                  # 'at' inside a word stays
    ("tomorrow due at 5pm", None, "2026-09-10", "17:00", ""),                           # keyword before the joiner
    ("tomorrow or Friday", "tomorrow", None, None, "or"),                    # two dates: first wins (unchanged)
    ("today 3pm tomorrow 4pm", "2026-09-09@15:00", None, "15:00", ""),
    # 有空 inside 有空调/有空间/有空位; 'later today' is today, not someday
    ("找一个有空调的会议室", None, None, None, "找一个有空调的会议室"),
    ("有空看看", "anytime", None, None, "看看"),
    ("Call John later today", "today", None, None, "Call John later"),
    ("Finish later", "someday", None, None, "Finish"),
    # phrasal 'drop/stop/come/swing/pass by' is not a deadline keyword
    ("Drop by tomorrow", "tomorrow", None, None, "Drop by"),
    ("Swing by Friday", "2026-09-11", None, None, "Swing by"),
    ("Submit report by tomorrow", None, "2026-09-10", None, "Submit report"),
]


@pytest.mark.parametrize("text,when,deadline,reminder,remaining", AUDIT_ROWS, ids=[r[0] for r in AUDIT_ROWS])
def test_audit_regressions(text, when, deadline, reminder, remaining, now):
    result = extract_dates(text, now)
    assert (result["when"], result["deadline"], result["reminder"], result["remaining"]) == (when, deadline, reminder, remaining)


def test_specials_never_carry_time_or_deadline(now):
    assert extract_dates("有空 whenever", now)["when"] == "anytime"
    assert extract_dates("截止 someday", now) == {"when": "someday", "deadline": None, "reminder": None,
                                                  "remaining": "截止", "language": "zh"}


def test_explicit_date_formats(now):
    assert extract_dates("2026/10/01", now)["when"] == "2026-10-01"
    assert extract_dates("2026年10月1日", now)["when"] == "2026-10-01"
    assert extract_dates("Oct 1", now)["when"] == "2026-10-01"
    assert extract_dates("October 1st", now)["when"] == "2026-10-01"
    assert extract_dates("1 Oct", now)["when"] == "2026-10-01"
    assert extract_dates("1st October", now)["when"] == "2026-10-01"
    assert extract_dates("3月5号", now)["when"] == "2027-03-05"
    # two-digit years are unsupported and stay in remaining
    result = extract_dates("10/1/26", now)
    assert result["when"] is None and result["remaining"] == "10/1/26"
