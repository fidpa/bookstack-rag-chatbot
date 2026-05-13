"""
Timezone Utilities für einheitliche Zeitanzeige
Alle Zeiten werden in Europe/Berlin (MESZ/MEZ) mit automatischer Umstellung angezeigt
"""

import pytz
from datetime import datetime
from typing import Union

# Zentrale Zeitzone für die Anwendung
APP_TIMEZONE = pytz.timezone("Europe/Berlin")


def now_local() -> datetime:
    """
    Aktuelle Zeit in lokaler Zeitzone (Europe/Berlin)

    Returns:
        datetime: Aktuelle Zeit mit Zeitzone
    """
    return datetime.now(APP_TIMEZONE)


def now_local_str() -> str:
    """
    Aktuelle Zeit als formatierter String

    Returns:
        str: Zeit im Format "2025-09-22 14:12:06 CEST"
    """
    return now_local().strftime("%Y-%m-%d %H:%M:%S %Z")


def format_time_local(
    time_input: Union[str, datetime], include_timezone: bool = True
) -> str:
    """
    Konvertiert verschiedene Zeit-Formate zu lokaler Zeit-Anzeige

    Args:
        time_input: Zeit als String (ISO format) oder datetime Objekt
        include_timezone: Ob Zeitzone-Kürzel angezeigt werden soll

    Returns:
        str: Formatierte lokale Zeit

    Examples:
        >>> format_time_local("2025-09-22T11:49:21.000000Z")
        "2025-09-22 13:49:21 CEST"

        >>> format_time_local("2025-09-22 12:12:06")  # UTC ohne Z
        "2025-09-22 14:12:06 CEST"
    """
    if time_input is None:
        return "N/A"

    try:
        if isinstance(time_input, str):
            # Parse verschiedene String-Formate
            if time_input.endswith("Z"):
                # UTC Format mit Z (BookStack API)
                dt = datetime.fromisoformat(time_input.replace("Z", "+00:00"))
            elif "+" in time_input or time_input.endswith("+00:00"):
                # ISO Format mit Zeitzone
                dt = datetime.fromisoformat(time_input)
            else:
                # Assume UTC if no timezone info (SQLite default)
                dt = datetime.fromisoformat(time_input).replace(tzinfo=pytz.UTC)
        elif isinstance(time_input, datetime):
            dt = time_input
            # Wenn keine Zeitzone, assume UTC
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=pytz.UTC)
        else:
            return str(time_input)

        # Konvertiere zu lokaler Zeit
        local_time = dt.astimezone(APP_TIMEZONE)

        # Format
        if include_timezone:
            return local_time.strftime("%Y-%m-%d %H:%M:%S %Z")
        else:
            return local_time.strftime("%Y-%m-%d %H:%M:%S")

    except Exception as e:
        # Fallback bei Parse-Fehlern
        return f"{time_input} (Parse Error: {str(e)})"


def utc_to_local(utc_time: Union[str, datetime]) -> datetime:
    """
    Konvertiert UTC Zeit zu lokaler Zeit (datetime Objekt)

    Args:
        utc_time: UTC Zeit als String oder datetime

    Returns:
        datetime: Lokale Zeit mit Zeitzone
    """
    if isinstance(utc_time, str):
        if utc_time.endswith("Z"):
            dt = datetime.fromisoformat(utc_time.replace("Z", "+00:00"))
        else:
            dt = datetime.fromisoformat(utc_time).replace(tzinfo=pytz.UTC)
    else:
        dt = utc_time
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=pytz.UTC)

    return dt.astimezone(APP_TIMEZONE)


def local_to_utc(local_time: Union[str, datetime]) -> datetime:
    """
    Konvertiert lokale Zeit zu UTC

    Args:
        local_time: Lokale Zeit

    Returns:
        datetime: UTC Zeit
    """
    if isinstance(local_time, str):
        dt = APP_TIMEZONE.localize(datetime.fromisoformat(local_time))
    elif isinstance(local_time, datetime):
        if local_time.tzinfo is None:
            dt = APP_TIMEZONE.localize(local_time)
        else:
            dt = local_time

    return dt.astimezone(pytz.UTC)


def format_for_database() -> str:
    """
    Aktuelle Zeit formatiert für Datenbank-Speicherung (mit Zeitzone)

    Returns:
        str: ISO Format mit Zeitzone "2025-09-22T14:12:06+02:00"
    """
    return now_local().isoformat()


def format_for_logs() -> str:
    """
    Aktuelle Zeit formatiert für Log-Ausgaben

    Returns:
        str: Format für Logs "2025-09-22 14:12:06 CEST"
    """
    return now_local_str()


class TimezoneFormatter:
    """
    Helper-Klasse für einheitliche Zeit-Formatierung in verschiedenen Kontexten
    """

    @staticmethod
    def bookstack_api_time(api_time: str) -> str:
        """Formatiert BookStack API Zeit (Z-Format) für Anzeige"""
        return format_time_local(api_time)

    @staticmethod
    def sqlite_time(sqlite_time: str) -> str:
        """Formatiert SQLite Zeit (UTC ohne TZ) für Anzeige"""
        return format_time_local(sqlite_time)

    @staticmethod
    def webhook_time(webhook_time: str) -> str:
        """Formatiert Webhook Zeitstempel für Anzeige"""
        return format_time_local(webhook_time)


# Convenience Funktionen für häufige Use Cases
def format_webhook_time(webhook_data: dict) -> dict:
    """
    Fügt formatierte Zeit-Felder zu Webhook-Daten hinzu

    Args:
        webhook_data: Dict mit triggered_at Feld

    Returns:
        dict: Webhook-Daten mit zusätzlichen Zeit-Feldern
    """
    if "triggered_at" in webhook_data:
        webhook_data["triggered_at_local"] = format_time_local(
            webhook_data["triggered_at"]
        )

    return webhook_data


# Test-Funktion für Entwicklung
def test_timezone_conversion():
    """Test verschiedene Zeit-Konvertierungen"""
    test_times = [
        "2025-09-22T11:49:21.000000Z",  # BookStack API
        "2025-09-22 12:12:06",  # SQLite UTC
        "2025-09-22T14:12:06+02:00",  # ISO mit Zeitzone
    ]

    print("Timezone Conversion Tests:")
    print(f"Aktuelle Zeit: {now_local_str()}")
    print()

    for test_time in test_times:
        print(f"Input:  {test_time}")
        print(f"Output: {format_time_local(test_time)}")
        print()


if __name__ == "__main__":
    test_timezone_conversion()
