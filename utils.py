from datetime import datetime, timedelta


def format_pretty_timestamp(timestamp_str):
    # Convert string to datetime object
    timestamp = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

    # Get current datetime
    now = datetime.now()

    # Calculate difference in days
    delta_days = (now - timestamp).days

    # Format time
    time_str = timestamp.strftime("%H:%M")

    if delta_days == 0:
        return f"today at {time_str}"
    elif delta_days == 1:
        return f"yesterday at {time_str}"
    else:
        date_str = timestamp.strftime("%d %b %Y")
        return f"on {date_str} at {time_str}"
