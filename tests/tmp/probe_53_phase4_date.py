import datetime


def test_date():
    print("today", datetime.date.today().isoformat(), datetime.datetime.now(datetime.timezone.utc).isoformat())
