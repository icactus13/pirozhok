import json
import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

logger = logging.getLogger(__name__)

OWM_URL = "https://api.openweathermap.org/data/2.5/weather"
OWM_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

_WEEKDAYS_RU = [
    "понедельник", "вторник", "среда", "четверг",
    "пятница", "суббота", "воскресенье",
]


async def get_weather(city: str = "Москва") -> str:
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        return "Ошибка: OPENWEATHER_API_KEY не настроен. Используй web_search как fallback."

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                OWM_URL,
                params={
                    "q": city,
                    "appid": api_key,
                    "units": "metric",
                    "lang": "ru",
                },
            )
    except Exception as exc:
        logger.error("OpenWeather request failed: %s", exc)
        return f"Ошибка сети при запросе погоды: {exc}. Используй web_search как fallback."

    if resp.status_code == 404:
        return f"Город «{city}» не найден в OpenWeather. Используй web_search как fallback."
    if resp.status_code == 401:
        return "Ошибка: ключ OpenWeather невалиден. Используй web_search как fallback."
    if resp.status_code != 200:
        return f"OpenWeather вернул {resp.status_code}. Используй web_search как fallback."

    data = resp.json()
    summary = {
        "city": data.get("name"),
        "country": (data.get("sys") or {}).get("country"),
        "temp_c": round(data["main"]["temp"], 1),
        "feels_like_c": round(data["main"]["feels_like"], 1),
        "description": data["weather"][0]["description"],
        "humidity_pct": data["main"]["humidity"],
        "wind_speed_ms": data.get("wind", {}).get("speed"),
        "pressure_hpa": data["main"].get("pressure"),
    }
    return json.dumps(summary, ensure_ascii=False)


WEATHER_TOOL = {
    "type": "function",
    "function": {
        "name": "weather",
        "description": (
            "Текущая погода ПРЯМО СЕЙЧАС в указанном городе (через OpenWeather). "
            "Используй когда спрашивают «какая погода сейчас», «сколько градусов», "
            "«идёт ли дождь», без упоминания будущего времени. Если город не назван "
            "— Москва (дефолт). Возвращает JSON: temp_c, feels_like_c, description, "
            "humidity_pct, wind_speed_ms. При ошибке — fallback на web_search."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "Название города. Если пользователь не назвал — Москва.",
                    "default": "Москва",
                },
            },
            "required": [],
        },
    },
}


def _most_common(items: list[str]) -> str:
    if not items:
        return ""
    counts: dict[str, int] = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]


async def get_forecast(city: str = "Москва") -> str:
    api_key = os.environ.get("OPENWEATHER_API_KEY")
    if not api_key:
        return "Ошибка: OPENWEATHER_API_KEY не настроен. Используй web_search как fallback."

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                OWM_FORECAST_URL,
                params={
                    "q": city,
                    "appid": api_key,
                    "units": "metric",
                    "lang": "ru",
                },
            )
    except Exception as exc:
        logger.error("OpenWeather forecast request failed: %s", exc)
        return f"Ошибка сети при запросе прогноза: {exc}. Используй web_search."

    if resp.status_code == 404:
        return f"Город «{city}» не найден. Используй web_search."
    if resp.status_code == 401:
        return "Ключ OpenWeather невалиден. Используй web_search."
    if resp.status_code != 200:
        return f"OpenWeather вернул {resp.status_code}. Используй web_search."

    data = resp.json()
    city_info = data.get("city", {}) or {}
    tz_offset_sec = city_info.get("timezone", 0)
    city_tz = timezone(timedelta(seconds=tz_offset_sec))

    by_day: dict[str, list[dict]] = {}
    for item in data.get("list", []):
        local_dt = datetime.fromtimestamp(item["dt"], tz=city_tz)
        date = local_dt.strftime("%Y-%m-%d")
        by_day.setdefault(date, []).append({
            "time": local_dt.strftime("%H:%M"),
            "temp_c": round(item["main"]["temp"], 1),
            "feels_like_c": round(item["main"]["feels_like"], 1),
            "description": item["weather"][0]["description"],
            "wind_speed_ms": item.get("wind", {}).get("speed"),
            "rain_mm": (item.get("rain") or {}).get("3h", 0),
            "snow_mm": (item.get("snow") or {}).get("3h", 0),
        })

    days_payload = []
    for date_str, slots in by_day.items():
        d = datetime.strptime(date_str, "%Y-%m-%d")
        temps = [s["temp_c"] for s in slots]
        descs = [s["description"] for s in slots]
        total_rain = round(sum(s["rain_mm"] for s in slots), 1)
        total_snow = round(sum(s["snow_mm"] for s in slots), 1)
        days_payload.append({
            "date": date_str,
            "weekday": _WEEKDAYS_RU[d.weekday()],
            "summary": {
                "temp_min_c": min(temps),
                "temp_max_c": max(temps),
                "main_description": _most_common(descs),
                "total_rain_mm": total_rain,
                "total_snow_mm": total_snow,
            },
            "slots": slots,
        })

    now_local = datetime.now(city_tz)
    summary = {
        "city": city_info.get("name"),
        "country": city_info.get("country"),
        "city_tz_offset_hours": round(tz_offset_sec / 3600, 1),
        "today_date_local": now_local.strftime("%Y-%m-%d"),
        "today_weekday_local": _WEEKDAYS_RU[now_local.weekday()],
        "note": (
            "Все даты, дни недели и время — в локальной TZ города. "
            "Используй ИМЕННО эти значения, не пересчитывай. "
            "Возвращены все доступные дни (до 5). Выбери из них нужные."
        ),
        "days": days_payload,
    }
    return json.dumps(summary, ensure_ascii=False)


WEATHER_FORECAST_TOOL = {
    "type": "function",
    "function": {
        "name": "weather_forecast",
        "description": (
            "Прогноз погоды на ближайшие 5 дней (шаг 3 часа). "
            "ОБЯЗАТЕЛЬНО используй для любых вопросов про БУДУЩУЮ погоду: "
            "«завтра», «послезавтра», «на выходных», «через X дней», «какая будет», "
            "«потеплеет ли». ЗАПРЕЩЕНО отвечать про будущую погоду без вызова — "
            "никаких догадок «обычно в это время года». "
            "Возвращает JSON: today_date_local, today_weekday_local, days[] "
            "(каждый день — date, weekday, summary с temp_min/max/avg, slots[]). "
            "Все даты и дни недели — уже в локальной TZ города. ИСПОЛЬЗУЙ ИМЕННО "
            "ЭТИ ЗНАЧЕНИЯ, ничего не пересчитывай и не выдумывай. "
            "Если город не назван — Москва. При ошибке — fallback на web_search."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "Название города. По умолчанию — Москва.",
                    "default": "Москва",
                },
            },
            "required": [],
        },
    },
}
