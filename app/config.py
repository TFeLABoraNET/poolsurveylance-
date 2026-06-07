"""Anwendungs-Einstellungen (aus Umgebungsvariablen / .env)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


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


settings = Settings()
