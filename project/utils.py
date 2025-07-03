from datetime import datetime as dt, timedelta


def format_pretty_timestamp(timestamp_str):
    """
    Formats a timestamp string (YYYY-MM-DD HH:MM:SS) into a user-friendly string.
    e.g., "today at 14:30", "yesterday at 09:15", "on 15 Jan 2023 at 10:00"
    """
    if not timestamp_str:
        return "N/A"
    try:
        timestamp = dt.strptime(str(timestamp_str), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        if isinstance(timestamp_str, dt):  # Check if it's already a datetime object
            timestamp = timestamp_str
        else:
            # Consider logging this error if current_app logger is available/passed
            # For now, return a simple error indicator.
            # from flask import current_app
            # if current_app:
            #    current_app.logger.warning(f"Invalid timestamp format received: {timestamp_str}")
            return "Invalid date"

    now = dt.now()
    delta_days = (now.date() - timestamp.date()).days
    time_str = timestamp.strftime("%H:%M")

    if delta_days == 0:
        return f"today at {time_str}"
    elif delta_days == 1:
        return f"yesterday at {time_str}"
    else:
        date_str = timestamp.strftime("%d %b %Y")
        return f"on {date_str} at {time_str}"


if __name__ == "__main__":
    # Basic test cases
    print(f"'2023-10-27 10:00:00' -> {format_pretty_timestamp('2023-10-27 10:00:00')}")

    now = dt.now()
    one_day_ago = now - timedelta(days=1, hours=2)
    one_day_ago_str = one_day_ago.strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"One day ago ({one_day_ago_str}) -> "
        f"{format_pretty_timestamp(one_day_ago_str)}"
    )

    today_early = now - timedelta(hours=5)
    today_early_str = today_early.strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"Today early ({today_early_str}) -> "
        f"{format_pretty_timestamp(today_early_str)}"
    )

    two_days_ago = now - timedelta(days=2, hours=3)
    two_days_ago_str = two_days_ago.strftime("%Y-%m-%d %H:%M:%S")
    print(
        f"Two days ago ({two_days_ago_str}) -> "
        f"{format_pretty_timestamp(two_days_ago_str)}"
    )

    print(f"None input -> {format_pretty_timestamp(None)}")
    print(f"Empty string input -> {format_pretty_timestamp('')}")
    print(f"Malformed string input -> {format_pretty_timestamp('invalid-date-string')}")
    print(f"Datetime object input -> {format_pretty_timestamp(now)}")
