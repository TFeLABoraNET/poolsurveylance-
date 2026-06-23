"""Anwendungs-Einstellungen (aus Umgebungsvariablen / .env / HA-Add-on)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("poolsurveylance.config")

# Home-Assistant-Add-ons stellen ihre Benutzeroptionen hier bereit.
HA_OPTIONS_PATH = Path("/data/options.json")


class Settings(BaseSettings):
    """Globale Einstellungen.

    Werte können über Umgebungsvariablen (Docker) oder eine .env-Datei
    gesetzt werden. Alle MQTT-Optionen sind optional – ohne Broker läuft
    die App ganz normal als Standalone-Web-App weiter.
    """

    model_config = SettingsConfigDict(env_prefix="POOL_", env_file=".env", extra="ignore")

    # --- Allgemein ---
    app_name: str = "PoolSurveylance"
    database_url: str = "sqlite:////data/pool.db"
    timezone: str = "Europe/Berlin"

    # --- MQTT / Home Assistant (optional) ---
    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    # Basis-Topic für die App-Zustände
    mqtt_base_topic: str = "poolsurveylance"
    # Prefix für Home-Assistant-MQTT-Discovery (HA-Standard: "homeassistant")
    mqtt_discovery_prefix: str = "homeassistant"
    # Eindeutige Geräte-ID in Home Assistant
    device_id: str = "poolsurveylance"

    # --- Sensor-Eingang (ESP32 / externe Sonden) ---
    # Optionaler Token: ist er gesetzt, müssen HTTP-POSTs an /api/measurements
    # den Header "X-API-Key: <token>" mitschicken. Leer = ungesichert (nur im
    # vertrauenswürdigen Heimnetz empfohlen).
    ingest_token: str = ""


# Optionen, die ein Home-Assistant-Add-on über /data/options.json setzen kann.
# Schlüssel = Name in der Add-on-Konfiguration, Wert = Attribut in Settings.
_HA_OPTION_MAP = {
    "mqtt_enabled": "mqtt_enabled",
    "mqtt_host": "mqtt_host",
    "mqtt_port": "mqtt_port",
    "mqtt_username": "mqtt_username",
    "mqtt_password": "mqtt_password",
    "mqtt_base_topic": "mqtt_base_topic",
    "mqtt_discovery_prefix": "mqtt_discovery_prefix",
    "device_id": "device_id",
    "ingest_token": "ingest_token",
}


def _apply_ha_addon_options(s: Settings) -> Settings:
    """Übernimmt Optionen aus einem Home-Assistant-Add-on, falls vorhanden.

    Leere Strings (z. B. nicht gesetzter Benutzername) werden ignoriert,
    damit sie sinnvolle Standardwerte nicht überschreiben.
    """
    if not HA_OPTIONS_PATH.is_file():
        return s
    try:
        options = json.loads(HA_OPTIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:  # pragma: no cover - defensiv
        logger.warning("HA-Add-on-Optionen konnten nicht gelesen werden: %s", exc)
        return s
    for key, attr in _HA_OPTION_MAP.items():
        if key in options and options[key] not in (None, ""):
            setattr(s, attr, options[key])
    logger.info("Home-Assistant-Add-on-Optionen übernommen.")
    return s


settings = _apply_ha_addon_options(Settings())
