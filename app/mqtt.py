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
    "orp": ("Pool Redox/ORP", "mV", "voltage", "mdi:flash"),
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

    @property
    def _dose_topic(self) -> str:
        # Der Dosiercontroller meldet hier ausgeführte Dosier-Stöße als JSON.
        return f"{settings.mqtt_base_topic}/dose"

    @property
    def _command_topic(self) -> str:
        # Hierüber spiegelt die App Sollwerte/Freigaben an den ESP32-Controller.
        return f"{settings.mqtt_base_topic}/command"

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
        # Auf Sensor-Eingang und Dosier-Meldungen lauschen (ESP32 o. Ä.)
        client.on_message = self._on_message
        client.subscribe(self._ingest_topic, qos=0)
        client.subscribe(self._dose_topic, qos=0)
        logger.info("Lausche auf Sensor-Eingang: %s und Dosier-Meldungen: %s",
                    self._ingest_topic, self._dose_topic)

    def _on_message(self, client, userdata, msg) -> None:
        """Verarbeitet eingehende JSON-Nachrichten (Messwerte oder Dosier-Stöße)."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            logger.warning("MQTT-Ingest: ungültiges JSON (%s).", exc)
            return
        if not isinstance(payload, dict):
            logger.warning("MQTT-Ingest: JSON-Objekt erwartet.")
            return
        if msg.topic == self._dose_topic:
            self._handle_dose(payload)
        else:
            self._handle_measurement(payload)

    def _handle_measurement(self, payload: dict) -> None:
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

    def _handle_dose(self, payload: dict) -> None:
        from . import crud
        from .database import SessionLocal
        db = SessionLocal()
        try:
            ev = crud.ingest_dose_event(db, payload)
            if ev is None:
                logger.warning("MQTT-Dose: kein gültiger Dosier-Stoß im Payload.")
                return
            logger.info("MQTT-Dose: %.1f ml protokolliert (Stoß #%s, %s).",
                        ev.ml, ev.id, ev.trigger)
        except Exception as exc:  # pragma: no cover - defensiv
            logger.warning("MQTT-Dose fehlgeschlagen: %s", exc)
        finally:
            db.close()

    def publish_dose_command(self, payload: dict) -> None:
        """Spiegelt Sollwerte/Freigaben (retained) an den ESP32-Controller."""
        if not self.enabled or self._client is None:
            return
        try:
            self._client.publish(self._command_topic, json.dumps(payload), retain=True)
        except Exception as exc:  # pragma: no cover
            logger.warning("MQTT-Command-Publish fehlgeschlagen: %s", exc)

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
