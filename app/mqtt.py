"""Optionale MQTT-Anbindung mit Home-Assistant-Auto-Discovery.

Ist ``POOL_MQTT_ENABLED`` nicht gesetzt, sind alle Funktionen No-Ops –
die App läuft dann ganz normal als Standalone-Web-App.

Über denselben MQTT-Weg können später die geplanten ESP32-Sonden ihre
Mess­werte einspeisen.
"""

from __future__ import annotations

import json
import logging

from .config import settings
from .models import Measurement

logger = logging.getLogger("poolsurveylance.mqtt")

try:  # paho ist nur nötig, wenn MQTT aktiv ist
    import paho.mqtt.client as mqtt
except Exception:  # pragma: no cover
    mqtt = None  # type: ignore[assignment]


# Sensoren, die in Home Assistant angelegt werden.
# key -> (Anzeigename, Einheit, device_class, icon)
_SENSORS = {
    "ph": ("Pool pH", None, None, "mdi:ph"),
    "free_cl": ("Pool Freies Chlor", "mg/l", None, "mdi:flask"),
    "total_cl": ("Pool Gesamtchlor", "mg/l", None, "mdi:flask-outline"),
    "ta": ("Pool Alkalinität", "mg/l", None, "mdi:beaker"),
    "cya": ("Pool Cyanursäure", "mg/l", None, "mdi:shield-sun"),
    "temperature": ("Pool Wassertemperatur", "°C", "temperature", "mdi:thermometer"),
}


class PoolMqtt:
    """Schlanker MQTT-Client-Wrapper für Home Assistant."""

    def __init__(self) -> None:
        self._client = None
        self._connected = False

    @property
    def enabled(self) -> bool:
        return settings.mqtt_enabled and mqtt is not None

    @property
    def _state_topic(self) -> str:
        return f"{settings.mqtt_base_topic}/state"

    @property
    def _avail_topic(self) -> str:
        return f"{settings.mqtt_base_topic}/availability"

    @property
    def _ingest_topic(self) -> str:
        # Sonden veröffentlichen hier ihre Messwerte als JSON.
        return f"{settings.mqtt_base_topic}/ingest"

    # --- Lifecycle --------------------------------------------------------

    def start(self) -> None:
        if not self.enabled:
            logger.info("MQTT deaktiviert – überspringe Verbindung.")
            return
        try:
            client = mqtt.Client(
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                client_id=settings.device_id,
            )
            if settings.mqtt_username:
                client.username_pw_set(settings.mqtt_username, settings.mqtt_password or "")
            client.will_set(self._avail_topic, "offline", retain=True)
            client.on_connect = self._on_connect
            client.connect(settings.mqtt_host, settings.mqtt_port, keepalive=60)
            client.loop_start()
            self._client = client
        except Exception as exc:  # Broker nicht erreichbar o. Ä. – nicht abstürzen
            logger.warning("MQTT-Verbindung fehlgeschlagen: %s", exc)

    def stop(self) -> None:
        if self._client is not None:
            try:
                self._client.publish(self._avail_topic, "offline", retain=True)
                self._client.loop_stop()
                self._client.disconnect()
            except Exception:  # pragma: no cover
                pass

    # --- Callbacks --------------------------------------------------------

    def _on_connect(self, client, userdata, flags, reason_code, properties=None) -> None:
        if getattr(reason_code, "is_failure", False):
            logger.warning("MQTT-Connect abgelehnt: %s", reason_code)
            return
        self._connected = True
        logger.info("Mit MQTT-Broker verbunden.")
        client.publish(self._avail_topic, "online", retain=True)
        self._publish_discovery()
        # Auf Sensor-Eingang lauschen (ESP32-Sonden o. Ä.)
        client.on_message = self._on_message
        client.subscribe(self._ingest_topic, qos=0)
        logger.info("Lausche auf Sensor-Eingang: %s", self._ingest_topic)

    def _on_message(self, client, userdata, msg) -> None:
        """Verarbeitet eingehende Sensor-Messwerte (JSON-Payload)."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning("MQTT-Ingest: ungültiges JSON (%s).", exc)
            return
        if not isinstance(payload, dict):
            logger.warning("MQTT-Ingest: JSON-Objekt erwartet.")
            return
        # Lazy-Import vermeidet Zirkelbezüge.
        from . import crud
        from .database import SessionLocal
        db = SessionLocal()
        try:
            measurement = crud.ingest_measurement(db, payload)
            if measurement is None:
                logger.warning("MQTT-Ingest: kein gültiger Messwert im Payload.")
                return
            self.publish_measurement(measurement)
            logger.info("MQTT-Ingest: Messung #%s gespeichert (Quelle %s).",
                        measurement.id, measurement.source)
        except Exception as exc:  # pragma: no cover - defensiv
            logger.warning("MQTT-Ingest fehlgeschlagen: %s", exc)
        finally:
            db.close()

    # --- Home-Assistant-Discovery ----------------------------------------

    def _device_block(self) -> dict:
        return {
            "identifiers": [settings.device_id],
            "name": settings.app_name,
            "manufacturer": "PoolSurveylance",
            "model": "Pool-Pflege-Assistent",
        }

    def _publish_discovery(self) -> None:
        if self._client is None:
            return
        prefix = settings.mqtt_discovery_prefix
        for key, (name, unit, device_class, icon) in _SENSORS.items():
            uid = f"{settings.device_id}_{key}"
            config = {
                "name": name,
                "unique_id": uid,
                "object_id": uid,
                "state_topic": self._state_topic,
                "value_template": f"{{{{ value_json.{key} }}}}",
                "availability_topic": self._avail_topic,
                "device": self._device_block(),
            }
            if unit:
                config["unit_of_measurement"] = unit
            if device_class:
                config["device_class"] = device_class
            if icon:
                config["icon"] = icon
            topic = f"{prefix}/sensor/{uid}/config"
            self._client.publish(topic, json.dumps(config), retain=True)
        logger.info("Home-Assistant-Discovery veröffentlicht (%d Sensoren).", len(_SENSORS))

    # --- Zustände ---------------------------------------------------------

    def publish_measurement(self, m: Measurement) -> None:
        """Veröffentlicht die aktuellen Messwerte als JSON-State."""
        if not self.enabled or self._client is None:
            return
        payload = {key: getattr(m, key) for key in _SENSORS}
        try:
            self._client.publish(self._state_topic, json.dumps(payload), retain=True)
        except Exception as exc:  # pragma: no cover
            logger.warning("MQTT-Publish fehlgeschlagen: %s", exc)


# Singleton, das die App nutzt.
pool_mqtt = PoolMqtt()
