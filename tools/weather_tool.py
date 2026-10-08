import requests
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("weather_tool")


class WeatherTool:
    """Fetches real-time weather analytics and forecasts for any city worldwide."""

    def __init__(self):
        pass

    def get_weather(self, location: Optional[str] = None) -> Dict[str, Any]:
        """Fetches current temperature, humidity, wind, and forecast for a specified city or user location."""
        loc = location.strip() if location else ""
        url = f"https://wttr.in/{loc}?format=j1" if loc else "https://wttr.in/?format=j1"

        logger.info(f"Fetching weather data from {url}...")
        try:
            resp = requests.get(url, timeout=10, headers={"User-Agent": "curl/7.68.0"})
            if resp.status_code != 200:
                return {"success": False, "error": f"Weather service responded with status {resp.status_code}"}

            data = resp.json()
            curr = data.get("current_condition", [{}])[0]
            nearest_area = data.get("nearest_area", [{}])[0]

            city_name = loc or nearest_area.get("areaName", [{}])[0].get("value", "Current Location")
            country = nearest_area.get("country", [{}])[0].get("value", "")

            temp_c = curr.get("temp_C", "N/A")
            temp_f = curr.get("temp_F", "N/A")
            feels_like_c = curr.get("FeelsLikeC", "N/A")
            condition = curr.get("weatherDesc", [{}])[0].get("value", "Clear")
            humidity = curr.get("humidity", "N/A")
            wind_kmph = curr.get("windspeedKmph", "N/A")
            wind_dir = curr.get("winddir16Point", "")

            # Forecast for today
            today_weather = data.get("weather", [{}])[0]
            max_c = today_weather.get("maxtempC", "N/A")
            min_c = today_weather.get("mintempC", "N/A")

            summary = (
                f"**Weather Report for {city_name}, {country}:**\n"
                f"• **Condition:** {condition}\n"
                f"• **Temperature:** {temp_c}°C ({temp_f}°F) (Feels like {feels_like_c}°C)\n"
                f"• **Today's Range:** High {max_c}°C / Low {min_c}°C\n"
                f"• **Humidity:** {humidity}%\n"
                f"• **Wind:** {wind_kmph} km/h {wind_dir}"
            )

            logger.info(f"Weather fetched for {city_name}: {condition}, {temp_c}°C")
            return {
                "success": True,
                "city": city_name,
                "country": country,
                "temp_c": temp_c,
                "temp_f": temp_f,
                "condition": condition,
                "humidity": humidity,
                "wind_kmph": wind_kmph,
                "summary": summary,
            }

        except Exception as e:
            logger.error(f"Weather lookup error: {e}")
            return {"success": False, "error": f"Weather lookup failed: {str(e)}"}
