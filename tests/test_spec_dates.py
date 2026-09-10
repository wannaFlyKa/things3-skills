"""Adversarial date-parsing tests written from SPEC.md section F (rules R1-R16, table F.3).

Every expected value below is derived by hand from the F.2 rules with the stated `now`; the module is
only called, never consulted. Every non-None output is also checked against the C.4 vocabulary regexes.
"""

import re
from datetime import date, datetime

import pytest

from things_lib import dates
from things_lib.dates import add_offset, detect_language, extract_dates, parse_deadline, parse_when

NOW = datetime(2026, 9, 9, 10, 0)  # Wednesday, ISO week 37
SPEC_VALID_WHEN = re.compile(r"^(today|tomorrow|evening|anytime|someday|\d{4}-\d{2}-\d{2}(@\d{2}:\d{2})?)$")
SPEC_VALID_DEADLINE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SPEC_VALID_REMINDER = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
RESULT_KEYS = ["when", "deadline", "reminder", "remaining", "language"]


def check_vocabulary(result):
    """R1: when in WHEN_VOCAB, deadline yyyy-mm-dd, reminder HH:MM; every date must be a real calendar date."""
    assert sorted(result) == sorted(RESULT_KEYS)
    assert result["language"] in ("zh", "en")
    assert isinstance(result["remaining"], str)
    when, deadline, reminder = result["when"], result["deadline"], result["reminder"]
    if when is not None:
        assert SPEC_VALID_WHEN.match(when), when
        if when[:1].isdigit():
            date.fromisoformat(when[:10])
            if "@" in when:
                assert SPEC_VALID_REMINDER.match(when[11:]), when
    if deadline is not None:
        assert SPEC_VALID_DEADLINE.match(deadline), deadline
        date.fromisoformat(deadline)
    if reminder is not None:
        assert SPEC_VALID_REMINDER.match(reminder), reminder


def run(text, now=NOW, **kwargs):
    result = extract_dates(text, now, **kwargs)
    check_vocabulary(result)
    return result


# ---- F.3: all 66 rows ---------------------------------------------------------------------------------
# (input, when, deadline, reminder, language)
ZH_ROWS = set(range(1, 26)) | {47, 48, 51, 53, 54, 55, 60, 61, 63, 64, 65}
F3 = [
    (1, "今天", "today", None, None), (2, "明天", "tomorrow", None, None), (3, "后天", "2026-09-11", None, None),
    (4, "今晚", "evening", None, None), (5, "明晚", "2026-09-10@18:00", None, "18:00"),
    (6, "周五", "2026-09-11", None, None), (7, "周五晚上", "2026-09-11@18:00", None, "18:00"),
    (8, "下周三", "2026-09-16", None, None), (9, "下周一", "2026-09-14", None, None),
    (10, "这周末", "2026-09-12", None, None), (11, "周末", "2026-09-12", None, None),
    (12, "月底", "2026-09-30", None, None), (13, "下月初", "2026-10-01", None, None),
    (14, "下个月", "2026-10-01", None, None), (15, "明天上午9点", "2026-09-10@09:00", None, "09:00"),
    (16, "下午3点", "2026-09-09@15:00", None, "15:00"), (17, "晚上8点", "2026-09-09@20:00", None, "20:00"),
    (18, "上午9点", "2026-09-10@09:00", None, "09:00"), (19, "三天后", "2026-09-12", None, None),
    (20, "两周后", "2026-09-23", None, None), (21, "下周", "2026-09-14", None, None),
    (22, "随便什么时候", "anytime", None, None), (23, "以后再说", "someday", None, None),
    (24, "10月1日", "2026-10-01", None, None), (25, "十月一日", "2026-10-01", None, None),
    (26, "today", "today", None, None), (27, "tomorrow", "tomorrow", None, None),
    (28, "tonight", "evening", None, None), (29, "this evening", "evening", None, None),
    (30, "next Tue", "2026-09-15", None, None), (31, "next Monday", "2026-09-14", None, None),
    (32, "Friday", "2026-09-11", None, None), (33, "fri", "2026-09-11", None, None),
    (34, "EOD Friday", "2026-09-11@18:00", None, "18:00"), (35, "end of month", "2026-09-30", None, None),
    (36, "in 2 weeks", "2026-09-23", None, None), (37, "in 3 days", "2026-09-12", None, None),
    (38, "next week", "2026-09-14", None, None), (39, "someday", "someday", None, None),
    (40, "anytime", "anytime", None, None), (41, "2026-10-01", "2026-10-01", None, None),
    (42, "10/1", "2026-10-01", None, None), (43, "1/10", "2027-01-10", None, None),
    (44, "+3d", "2026-09-12", None, None), (45, "+1w", "2026-09-16", None, None),
    (46, "Wednesday", "2026-09-16", None, None), (47, "下下周三", "2026-09-23", None, None),
    (48, "1月5日", "2027-01-05", None, None), (49, "tomorrow evening", "2026-09-10@18:00", None, "18:00"),
    (50, "Friday night", "2026-09-11@18:00", None, "18:00"), (51, "中午", "2026-09-09@12:00", None, "12:00"),
    (52, "EOD", "2026-09-09@18:00", None, "18:00"), (53, "截止周五", None, "2026-09-11", None),
    (54, "周五前", None, "2026-09-11", None), (55, "周五之前", None, "2026-09-11", None),
    (56, "due Friday", None, "2026-09-11", None), (57, "by next Monday", None, "2026-09-14", None),
    (58, "before 10/1", None, "2026-10-01", None), (59, "deadline 2026-10-01", None, "2026-10-01", None),
    (60, "DDL 月底", None, "2026-09-30", None), (61, "截止明天", None, "2026-09-10", None),
    (62, "by EOD Friday", None, "2026-09-11", "18:00"), (63, "下班前", None, "2026-09-09", "18:00"),
    (64, "下周一开始，周五前完成", "2026-09-14", "2026-09-11", None),
    (65, "提醒我明天交房租", "2026-09-10@09:00", None, "09:00"), (66, "Call the dentist", None, None, None),
]


@pytest.mark.parametrize("row,text,when,deadline,reminder", F3, ids=["row%02d" % r[0] for r in F3])
def test_f3_table(row, text, when, deadline, reminder):
    result = run(text)
    assert result["when"] == when, (row, text, result)
    assert result["deadline"] == deadline, (row, text, result)
    assert result["reminder"] == reminder, (row, text, result)
    assert result["language"] == ("zh" if row in ZH_ROWS else "en"), (row, text)
    assert parse_when(text, NOW) == when
    assert parse_deadline(text, NOW) == deadline


@pytest.mark.parametrize("text,remaining", [
    ("明天下午3点给妈妈打电话", "给妈妈打电话"),
    ("Submit expense report by Friday", "Submit expense report"),
    ("周五前把周报发出去", "把周报发出去"),
    ("提醒我明天交房租", "交房租"),
    ("Call the dentist", "Call the dentist"),
    ("下周一开始，周五前完成", "开始 完成"),
])
def test_remaining_examples(text, remaining):
    assert run(text)["remaining"] == remaining


def test_row_18_time_already_past_rolls_to_tomorrow_but_same_time_later_stays_today():
    assert run("上午9点")["when"] == "2026-09-10@09:00"
    assert run("上午9点", now=datetime(2026, 9, 9, 8, 0))["when"] == "2026-09-09@09:00"
    assert run("9am", now=datetime(2026, 9, 9, 8, 59))["when"] == "2026-09-09@09:00"
    assert run("9am", now=datetime(2026, 9, 9, 9, 0))["when"] == "2026-09-10@09:00"  # 'later than now' is strict


# ---- adversarial: normalisation (R16) --------------------------------------------------------------

@pytest.mark.parametrize("text,when", [
    ("１０月１日", "2026-10-01"),
    ("１０/１", "2026-10-01"),
    ("２０２６-１０-０１", "2026-10-01"),
    ("十一月二十号", "2026-11-20"),
    ("十月十五日", "2026-10-15"),
    ("十二月三十一日", "2026-12-31"),
    ("三月一日", "2027-03-01"),
    ("十天后", "2026-09-19"),
    ("二十天后", "2026-09-29"),
    ("十五天后", "2026-09-24"),
    ("一周后", "2026-09-16"),
    ("两个星期后", "2026-09-23"),
    ("3个礼拜后", "2026-09-30"),
    ("一个月后", "2026-10-09"),
    ("两个月后", "2026-11-09"),
    ("5天以后", "2026-09-14"),
    ("大后天", "2026-09-12"),
])
def test_chinese_and_fullwidth_numerals(text, when):
    result = run(text)
    assert result["when"] == when
    assert result["deadline"] is None
    assert result["language"] == "zh"


@pytest.mark.parametrize("text,when,reminder", [
    ("两点半", "2026-09-10@02:30", "02:30"),          # bare H点半 keeps H; 02:30 is past at 10:00 -> tomorrow
    ("下午两点半", "2026-09-09@14:30", "14:30"),
    ("上午9点半", "2026-09-10@09:30", "09:30"),
    ("下午3点15分", "2026-09-09@15:15", "15:15"),
    ("9时", "2026-09-10@09:00", "09:00"),
    ("下午13点", "2026-09-09@13:00", "13:00"),         # 13 is outside 1..11, so pm adds nothing
    ("中午12点", "2026-09-09@12:00", "12:00"),
    ("凌晨3点", "2026-09-10@03:00", "03:00"),
    ("0点", "2026-09-10@00:00", "00:00"),
    ("12pm", "2026-09-09@12:00", "12:00"),
    ("3:45pm", "2026-09-09@15:45", "15:45"),
    ("3 pm", "2026-09-09@15:00", "15:00"),
    ("3PM", "2026-09-09@15:00", "15:00"),
    ("15:00", "2026-09-09@15:00", "15:00"),
    ("noon", "2026-09-09@12:00", "12:00"),
    ("tomorrow noon", "2026-09-10@12:00", "12:00"),
    ("tomorrow at 3pm", "2026-09-10@15:00", "15:00"),
    ("Friday at 9am", "2026-09-11@09:00", "09:00"),
    ("周五 5pm", "2026-09-11@17:00", "17:00"),
    ("明天晚上", "2026-09-10@18:00", "18:00"),
    ("tonight 9pm", "2026-09-09@21:00", "21:00"),
    ("今晚9点", "2026-09-09@21:00", "21:00"),
    ("eod friday", "2026-09-11@18:00", "18:00"),
    ("end of day", "2026-09-09@18:00", "18:00"),
])
def test_times_and_periods(text, when, reminder):
    result = run(text)
    assert result["when"] == when, result
    assert result["reminder"] == reminder, result
    assert result["deadline"] is None


# ---- adversarial: calendar edges with a shifted `now` -----------------------------------------------

SUNDAY = datetime(2026, 9, 13, 10, 0)
MONDAY = datetime(2026, 9, 14, 10, 0)


@pytest.mark.parametrize("now,text,when", [
    (datetime(2026, 9, 30, 10, 0), "月底", "2026-09-30"),            # R6: may equal today
    (datetime(2026, 9, 30, 10, 0), "end of month", "2026-09-30"),
    (datetime(2026, 9, 30, 10, 0), "EOM", "2026-09-30"),
    (datetime(2026, 12, 15, 10, 0), "下月初", "2027-01-01"),          # year rollover
    (datetime(2026, 12, 15, 10, 0), "下个月", "2027-01-01"),
    (datetime(2026, 12, 15, 10, 0), "next month", "2027-01-01"),
    (datetime(2026, 12, 15, 10, 0), "early next month", "2027-01-01"),
    (datetime(2026, 12, 15, 10, 0), "beginning of next month", "2027-01-01"),
    (datetime(2026, 12, 15, 10, 0), "月底", "2026-12-31"),
    (datetime(2026, 12, 15, 10, 0), "下月底", "2027-01-31"),
    (datetime(2026, 12, 15, 10, 0), "end of next month", "2027-01-31"),
    (datetime(2026, 12, 31, 23, 0), "明天", "tomorrow"),
    (datetime(2026, 12, 31, 23, 0), "后天", "2027-01-02"),
    (datetime(2026, 12, 31, 23, 0), "下周", "2027-01-04"),
    (datetime(2026, 12, 31, 23, 0), "1月5日", "2027-01-05"),          # >= today -> next year is the first hit
    (datetime(2028, 2, 28, 10, 0), "明天", "tomorrow"),               # leap day
    (datetime(2028, 2, 28, 10, 0), "后天", "2028-03-01"),
    (datetime(2028, 2, 28, 10, 0), "月底", "2028-02-29"),
    (datetime(2028, 2, 28, 10, 0), "end of month", "2028-02-29"),
    (datetime(2028, 1, 31, 10, 0), "一个月后", "2028-02-29"),          # clamp to month end
    (datetime(2028, 1, 31, 10, 0), "in 1 month", "2028-02-29"),
    (datetime(2026, 1, 31, 10, 0), "in 1 month", "2026-02-28"),
    (datetime(2026, 8, 31, 10, 0), "in 6 months", "2027-02-28"),
    (SUNDAY, "下周", "2026-09-14"),                                    # Sunday belongs to the current ISO week
    (SUNDAY, "next week", "2026-09-14"),
    (SUNDAY, "下周一", "2026-09-14"),
    (SUNDAY, "周一", "2026-09-14"),
    (SUNDAY, "周日", "2026-09-20"),                                    # R3 strictly after today
    (SUNDAY, "Sunday", "2026-09-20"),
    (SUNDAY, "周末", "2026-09-19"),                                    # this Saturday is past -> next Saturday
    (SUNDAY, "weekend", "2026-09-19"),
    (MONDAY, "下周", "2026-09-21"),
    (MONDAY, "next week", "2026-09-21"),
    (MONDAY, "下周一", "2026-09-21"),
    (MONDAY, "next Monday", "2026-09-21"),
    (MONDAY, "周一", "2026-09-21"),
    (MONDAY, "Monday", "2026-09-21"),
    (MONDAY, "Mon.", "2026-09-21"),
    (MONDAY, "这周一", "today"),                                       # R4 DECISION: this week's X that IS today -> today
    (MONDAY, "本周五", "2026-09-18"),
    (datetime(2026, 9, 12, 10, 0), "周末", "2026-09-12"),              # Saturday: this week's Saturday == today
    (datetime(2026, 9, 12, 10, 0), "this weekend", "2026-09-12"),
])
def test_calendar_edges(now, text, when):
    result = run(text, now=now)
    assert result["when"] == when, result
    assert result["deadline"] is None


@pytest.mark.parametrize("text", ["周三", "星期三", "礼拜三", "週三", "Wednesday", "wed", "Wed.", "WEDNESDAY"])
def test_weekday_equal_to_today_means_plus_seven(text):
    assert run(text)["when"] == "2026-09-16"


@pytest.mark.parametrize("text,when", [
    ("这周三", "2026-09-09"), ("本周三", "2026-09-09"), ("this Wednesday", "2026-09-09"),
])
def test_this_weekday_equal_to_today_is_today(text, when):
    assert run(text)["when"] in (when, "today")


@pytest.mark.parametrize("text,when", [
    ("这周一", "2026-09-14"), ("this Monday", "2026-09-14"),        # already past this week -> R3
    ("这周五", "2026-09-11"), ("this Friday", "2026-09-11"), ("本周末", "2026-09-12"),
    ("下周末", "2026-09-19"), ("next weekend", "2026-09-19"),
    ("下下周一", "2026-09-21"), ("下周日", "2026-09-20"), ("下周天", "2026-09-20"), ("next Sunday", "2026-09-20"),
    ("next sat", "2026-09-19"), ("Thurs", "2026-09-10"), ("thur", "2026-09-10"), ("Tues", "2026-09-15"), ("Tue.", "2026-09-15"),
    ("Sun", "2026-09-13"), ("sat.", "2026-09-12"),
    ("月初", "2026-10-01"), ("下个月初", "2026-10-01"), ("本月底", "2026-09-30"), ("下月底", "2026-10-31"),
    ("11月底", "2026-11-30"), ("9月底", "2026-09-30"), ("3月初", "2027-03-01"), ("下个月5号", "2026-10-05"),
    ("end of October", "2026-10-31"),
    ("2026/10/01", "2026-10-01"), ("2026年10月1日", "2026-10-01"), ("10月1号", "2026-10-01"),
    ("Oct 1", "2026-10-01"), ("October 1st", "2026-10-01"), ("1 Oct", "2026-10-01"), ("1st October", "2026-10-01"),
    ("Sep 5", "2027-09-05"), ("9月9日", "2026-09-09"), ("12/31", "2026-12-31"), ("in 10 days", "2026-09-19"),
    ("in a week", "2026-09-16"), ("in 2 months", "2026-11-09"), ("+2w", "2026-09-23"), ("in two weeks", "2026-09-23"),
    ("TOMORROW", "tomorrow"), ("Next Tue", "2026-09-15"), ("SOMEDAY", "someday"), ("Anytime", "anytime"),
])
def test_more_r3_to_r8_phrases(text, when):
    assert run(text)["when"] == when


# ---- adversarial: deadline keywords (R13) ------------------------------------------------------------

@pytest.mark.parametrize("text,deadline,reminder", [
    ("截至周五", "2026-09-11", None), ("最晚周五", "2026-09-11", None), ("ddl 周五", "2026-09-11", None),
    ("DDL周五", "2026-09-11", None), ("until Friday", "2026-09-11", None), ("no later than Friday", "2026-09-11", None),
    ("deadline Friday", "2026-09-11", None), ("due 10/1", "2026-10-01", None), ("by tomorrow", "2026-09-10", None),
    ("by today", "2026-09-09", None), ("due tomorrow", "2026-09-10", None), ("截止今天", "2026-09-09", None),
    ("明天前", "2026-09-10", None), ("月底前", "2026-09-30", None), ("下周一之前", "2026-09-14", None),
    ("by EOD", "2026-09-09", "18:00"), ("by 5pm Friday", "2026-09-11", "17:00"), ("by Friday 5pm", "2026-09-11", "17:00"),
    ("before tomorrow evening", "2026-09-10", "18:00"), ("周五下午5点前", "2026-09-11", "17:00"),
    ("due Sept 30", "2026-09-30", None), ("Due FRIDAY", "2026-09-11", None), ("截止10月1日", "2026-10-01", None),
    ("周五到期", "2026-09-11", None), ("11月底前", "2026-11-30", None),
    # R13: date phrase, keyword, then the time of that same moment -> one deadline, never a start today
    ("tomorrow before 5pm", "2026-09-10", "17:00"), ("Friday by 5pm", "2026-09-11", "17:00"),
    ("tomorrow by noon", "2026-09-10", "12:00"), ("周五前下午5点", "2026-09-11", "17:00"),
    ("下周三之前交报告，下午5点", "2026-09-16", "17:00"),
])
def test_deadline_keywords(text, deadline, reminder):
    result = run(text)
    assert result["deadline"] == deadline, result
    assert result["when"] is None, result
    assert result["reminder"] == reminder, result


@pytest.mark.parametrize("text,when,deadline", [
    ("周五前完成，下周一开始", "2026-09-14", "2026-09-11"),
    ("start next Monday, due Friday", "2026-09-14", "2026-09-11"),
    ("due Friday, start next Monday", "2026-09-14", "2026-09-11"),
    ("明天开始，截止月底", "tomorrow", "2026-09-30"),
    ("截止月底，明天开始", "tomorrow", "2026-09-30"),
    ("tomorrow, by 10/1", "tomorrow", "2026-10-01"),
])
def test_when_and_deadline_in_one_sentence_both_orders(text, when, deadline):
    result = run(text)
    assert result["when"] == when, result
    assert result["deadline"] == deadline, result


@pytest.mark.parametrize("text", ["提前准备周五的会议", "周五提前完成", "提前一天周五", "提前把周五的东西弄好"])
def test_tiqian_is_not_a_deadline_keyword(text):
    result = run(text)
    assert result["deadline"] is None, result
    assert result["when"] == "2026-09-11", result


@pytest.mark.parametrize("text", ["3天前发的邮件", "三天前的会议", "回复三天前的邮件", "2周前",
                                  "上周五", "上个周五", "上周末", "last Friday", "last weekend", "整理上周五会议纪要",
                                  "找一个有空调的会议室", "订一个有空位的餐厅"])
def test_past_references_and_lookalikes_are_not_dates(text):
    result = run(text)
    assert result["when"] is None and result["deadline"] is None, result
    assert result["remaining"] == text.strip()


@pytest.mark.parametrize("text,when,reminder,remaining", [
    # R10 extended: a date-only phrase and a later time-only phrase are one moment even with words between
    ("明天开会，下午3点", "2026-09-10@15:00", "15:00", "开会"),
    ("tomorrow call mom at 3pm", "2026-09-10@15:00", "15:00", "call mom"),
    ("Friday dentist 2pm", "2026-09-11@14:00", "14:00", "dentist"),
    ("Friday dentist at 2pm", "2026-09-11@14:00", "14:00", "dentist"),
    ("明天开会，在下午3点", "2026-09-10@15:00", "15:00", "开会"),
    ("上周五的会议纪要今天整理", "today", None, "上周五的会议纪要 整理"),
    ("Call John later today", "today", None, "Call John later"),
    ("Drop by tomorrow", "tomorrow", None, "Drop by"),
    ("afternoon 3:30", "2026-09-09@15:30", "15:30", ""),
    ("下午3点15分开会", "2026-09-09@15:15", "15:15", "开会"),
])
def test_when_with_words_between_date_and_time(text, when, reminder, remaining):
    result = run(text)
    assert result["when"] == when, result
    assert result["deadline"] is None, result
    assert result["reminder"] == reminder, result
    assert result["remaining"] == remaining, result


@pytest.mark.parametrize("text,when", [("baby shower Friday", "2026-09-11"), ("Buy baby food tomorrow", "tomorrow"),
                                       ("standby Friday", "2026-09-11"), ("lobby meeting Friday", "2026-09-11")])
def test_by_inside_a_word_is_not_a_keyword(text, when):
    result = run(text)
    assert result["deadline"] is None, result
    assert result["when"] == when, result
    assert "baby" in result["remaining"] or "standby" in result["remaining"] or "lobby" in result["remaining"]


@pytest.mark.parametrize("text", ["Read Somedays by Tolkien", "somedays", "anytimer", "eventuality report", "lateral move", "whenevers"])
def test_english_keywords_respect_word_boundaries(text):
    result = run(text)
    assert result["when"] is None, result
    assert result["deadline"] is None, result


@pytest.mark.parametrize("text", ["", "   ", "\n\t", "，，。", "...", "---", "！？", "🎉🎉", "____"])
def test_degenerate_inputs_do_not_crash_and_match_nothing(text):
    result = run(text)
    assert result["when"] is None and result["deadline"] is None and result["reminder"] is None
    assert result["remaining"] == text.strip()


def test_very_long_text():
    long = "a" * 5000
    result = run(long + " 明天 " + "b" * 5000)
    assert result["when"] == "tomorrow"
    assert result["remaining"] == long + " " + "b" * 5000
    plain = ("word " * 4000).strip()
    assert run(plain)["remaining"] == plain


@pytest.mark.parametrize("text", ["Q3 报告", "2026年报告", "Call 911", "v2.0 release", "Room 101", "Order #45", "3 apples",
                                  "2026年的计划", "买3斤苹果", "iPhone 17", "第3章", "3人会议", "50%"])
def test_numbers_without_date_meaning(text):
    result = run(text)
    assert result["when"] is None and result["deadline"] is None and result["reminder"] is None, result
    assert result["remaining"] == text


@pytest.mark.parametrize("text", ["2/29", "13/1", "2026-02-30", "10月32日", "25点", "24:00", "13pm", "0/0", "2026-13-01",
                                  "31/12", "99天后", "第五十三周", "下下下周三", "2月30日", "Feb 30", "0点0分", "12:60", "in 0 days",
                                  "+0d", "-3d", "in -2 days", "in 99999 days", "9999年12月31日", "1月0日"])
def test_invalid_or_odd_dates_never_crash_and_never_emit_garbage(text):
    """Whatever the interpretation, the output must be None or a real date/time in the F.1 vocabulary (R1)."""
    result = run(text)   # run() asserts the vocabulary and that every date is a real calendar date
    assert isinstance(result["remaining"], str)


def test_next_mixed_with_cjk_weekday_is_friday_of_this_or_next_week():
    result = run("next 周五")
    assert result["when"] in ("2026-09-11", "2026-09-18"), result
    assert result["deadline"] is None


# ---- R14 reminders ------------------------------------------------------------------------------------

def test_remind_me_with_explicit_time_keeps_that_time():
    result = run("提醒我明天下午3点开会")
    assert result["when"] == "2026-09-10@15:00" and result["reminder"] == "15:00"
    assert result["remaining"] == "开会"
    result = run("remind me tomorrow at 3pm to call mom")
    assert result["when"] == "2026-09-10@15:00" and result["reminder"] == "15:00"
    assert "remind" not in result["remaining"] and "3pm" not in result["remaining"]


def test_remind_me_uses_default_reminder_time_when_no_time_given():
    assert run("提醒我明天交房租", default_reminder_time="08:30")["when"] == "2026-09-10@08:30"
    result = run("remind me on Friday to submit the report")
    assert result["when"] == "2026-09-11@09:00" and result["reminder"] == "09:00"
    assert "remind" not in result["remaining"].casefold() and "Friday" not in result["remaining"]
    result = run("提醒我周五交周报")
    assert result["when"] == "2026-09-11@09:00" and result["remaining"] == "交周报"


def test_remind_me_without_any_date_adds_no_date():
    result = run("提醒我交房租")
    assert result["when"] is None and result["deadline"] is None


# ---- R15 remaining ------------------------------------------------------------------------------------

@pytest.mark.parametrize("text,remaining", [
    ("周五 5pm 交报告", "交报告"),
    ("Submit report by Friday 5pm please", "Submit report please"),
    ("明天，给妈妈打电话", "给妈妈打电话"),
    ("给妈妈打电话，明天", "给妈妈打电话"),
    ("Call mom, tomorrow, at 3pm", "Call mom"),
    ("  Call   the dentist  ", "Call   the dentist"),           # nothing matched -> text.strip() only
    ("买牛奶、明天、鸡蛋", "买牛奶 鸡蛋"),
    ("tomorrow tomorrow", ""),
])
def test_remaining_cleanup(text, remaining):
    assert run(text)["remaining"] == remaining


# ---- R16 / F.1 detect_language -----------------------------------------------------------------------

@pytest.mark.parametrize("text,lang", [
    ("买牛奶", "zh"), ("Call", "en"), ("", "en"), ("，", "zh"), ("。", "zh"), ("１０", "zh"), ("ａ", "zh"), ("㐀", "zh"),
    ("🎉", "en"), ("こんにちは", "en"), ("カタカナ", "en"), ("안녕", "en"), ("Call 妈妈", "zh"), ("123 !?", "en"),
    ("é", "en"), ("　", "zh"), ("〇", "zh"), ("龥", "zh"), ("鿿", "zh"),
])
def test_detect_language_ranges_are_exactly_the_spec_ranges(text, lang):
    assert detect_language(text) == lang


def test_extract_dates_language_matches_detect_language():
    for text in ["明天", "tomorrow", "Call 妈妈 tomorrow", "こんにちは", ""]:
        assert run(text)["language"] == detect_language(text)


# ---- add_offset --------------------------------------------------------------------------------------

@pytest.mark.parametrize("spec,expected", [("+3d", date(2026, 9, 12)), ("+2w", date(2026, 9, 23)), ("-1d", date(2026, 9, 8)),
                                           ("+0d", date(2026, 9, 9)), ("-2w", date(2026, 8, 26)), ("+30d", date(2026, 10, 9)),
                                           ("+52w", date(2027, 9, 8))])
def test_add_offset_valid(spec, expected):
    assert add_offset(date(2026, 9, 9), spec) == expected


@pytest.mark.parametrize("spec", ["3d", "+3", "+1m", "", "+1.5d", "++3d", "+3D", "+ 3d", "+3d ", "3天", "+1y", "+3h", "d", "+"])
def test_add_offset_invalid_raises_value_error(spec):
    with pytest.raises(ValueError):
        add_offset(date(2026, 9, 9), spec)


def test_add_offset_leap_day():
    assert add_offset(date(2028, 2, 28), "+1d") == date(2028, 2, 29)
    assert add_offset(date(2027, 2, 28), "+1d") == date(2027, 3, 1)


def test_parse_when_and_parse_deadline_are_projections_of_extract_dates():
    for text in ["明天下午3点", "截止周五", "下周一开始，周五前完成", "Call the dentist", "tonight"]:
        full = run(text)
        assert parse_when(text, NOW) == full["when"]
        assert parse_deadline(text, NOW) == full["deadline"]
    assert dates.WHEN_VOCAB  # exported per F.1
