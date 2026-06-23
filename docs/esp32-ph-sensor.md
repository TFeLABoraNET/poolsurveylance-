# pH-Sonde per ESP32 anbinden (ESPHome)

Diese Anleitung bindet eine **analoge pH-Elektrode** (z. B. Apera 201-C, BNC)
über ein **pH-Frontend-Board** und einen **ESP32** an PoolSurveylance an.

```
pH-Elektrode (BNC)  ──►  pH-Frontend-Board  ──►  ESP32 (ADC)  ──►  WLAN
   Apera 201-C            DFRobot isoliert /         │                │
                          PH4502C                    │                ▼
                                                     │      MQTT  oder  HTTP-POST
                                                     ▼                │
                                              ESPHome-Firmware        ▼
                                                              PoolSurveylance
```

> Die Elektrode liefert nur ein hochohmiges mV-Signal – sie braucht **zwingend**
> ein Frontend-Board mit BNC-Buchse. Empfohlen: ein **galvanisch isoliertes**
> Board (DFRobot Gravity), weil Umwälzpumpe/Salzelektrolyse sonst Störungen
> einkoppeln.

## 1. Verdrahtung

| Frontend-Board | ESP32 |
|---|---|
| `V+` / `VCC` | `3V3` (oder `5V`, je nach Board) |
| `GND` | `GND` |
| `Po` / `A0` (Analog-Ausgang) | `GPIO34` (ADC1, nur Eingang) |

Die Elektrode kommt per BNC ans Frontend-Board.

## 2. ESPHome-Konfiguration

Datei `pool-ph.yaml` (in Home Assistant → ESPHome → neues Gerät):

```yaml
esphome:
  name: pool-ph
  friendly_name: Pool pH

esp32:
  board: esp32dev

wifi:
  ssid: !secret wifi_ssid
  password: !secret wifi_password

logger:
api:                # Home-Assistant-API (optional, für Live-Anzeige in HA)
ota:

# --- pH-Messung über den Analog-Eingang ---
sensor:
  - platform: adc
    pin: GPIO34
    name: "Pool pH (Rohspannung)"
    id: ph_voltage
    attenuation: 11db        # Messbereich bis ~3,1 V
    update_interval: 30s
    # 2-Punkt-Kalibrierung: mit Pufferlösung pH 7,00 und pH 4,01 die
    # gemessenen Spannungen eintragen (Logger zeigt die Rohspannung an).
    filters:
      - median:              # glättet Rauschen
          window_size: 7
          send_every: 7
      - calibrate_linear:
          # gemessene_Spannung -> pH-Wert
          - 1.50 -> 7.00     # <- hier deine pH-7-Spannung eintragen
          - 1.80 -> 4.01     # <- hier deine pH-4-Spannung eintragen

  - platform: template
    name: "Pool pH"
    id: ph_value
    unit_of_measurement: "pH"
    accuracy_decimals: 2
    lambda: 'return id(ph_voltage).state;'
    update_interval: 300s     # alle 5 Min an die App melden (nicht zu oft!)
    on_value:
      then:
        # ===== Variante A: MQTT (App lauscht auf poolsurveylance/ingest) =====
        - mqtt.publish_json:
            topic: poolsurveylance/ingest
            payload: |
              root["ph"] = id(ph_value).state;
              root["source"] = "esp32";

        # ===== Variante B: HTTP-POST direkt an die App =====
        # (eine der beiden Varianten genügt – die andere auskommentieren)
        - http_request.post:
            url: http://<raspberry-pi-ip>:8000/api/measurements
            headers:
              Content-Type: application/json
              X-API-Key: !secret pool_ingest_token   # nur falls Token gesetzt
            json: |
              root["ph"] = id(ph_value).state;
              root["source"] = "esp32";

# Für Variante A:
mqtt:
  broker: <broker-ip>          # z. B. core-mosquitto / homeassistant.local
  username: !secret mqtt_user
  password: !secret mqtt_pass

# Für Variante B:
http_request:
  useragent: esphome/pool-ph
  timeout: 10s
```

> **Nur eine Variante nötig.** MQTT ist am saubersten, wenn du den Broker
> ohnehin nutzt; HTTP-POST ist unabhängig von Home Assistant.

## 3. Kalibrierung

1. Firmware flashen, ESP in **pH-7-Pufferlösung** halten, im ESPHome-Logger die
   **Rohspannung** (`ph_voltage`) ablesen → bei `calibrate_linear` als
   `… -> 7.00` eintragen.
2. Elektrode abspülen, in **pH-4-Pufferlösung** halten, Spannung ablesen →
   als `… -> 4.01` eintragen.
3. Neu flashen. Fertig. **Regelmäßig nachkalibrieren** (Elektroden driften).

## 4. Test ohne Hardware

Den App-Eingang kannst du sofort mit `curl` prüfen:

```bash
# HTTP-POST (ohne Token)
curl -X POST http://<raspberry-pi-ip>:8000/api/measurements \
  -H "Content-Type: application/json" \
  -d '{"ph": 7.21, "temperature": 26.4, "source": "esp32"}'

# Mit Token (POOL_INGEST_TOKEN gesetzt)
curl -X POST http://<raspberry-pi-ip>:8000/api/measurements \
  -H "Content-Type: application/json" \
  -H "X-API-Key: DEIN_TOKEN" \
  -d '{"ph": 7.21}'

# MQTT
mosquitto_pub -h <broker> -t poolsurveylance/ingest \
  -m '{"ph": 7.21, "source": "esp32"}'
```

Die Werte erscheinen anschließend mit Quelle `esp32` in **Messung**, **Verlauf**
und **Trends**.

## 5. Hinweise

- **Throttling:** Schicke Werte nicht im Sekundentakt – sonst wächst die
  Datenbank stark. Alle 5–15 Minuten reicht für die pH-Überwachung.
- **Felder:** Erlaubt sind `ph`, `free_cl`, `total_cl`, `ta`, `cya`,
  `temperature` (plus `source`, `note`, `measured_at`). Es muss mindestens ein
  Messwert enthalten sein.
- **Temperaturkompensation:** Die Apera 201-C hat keinen Temperaturfühler.
  Für höhere Genauigkeit einen Wassertemperatur-Sensor (z. B. DS18B20)
  ergänzen und `temperature` mitsenden.
- **Sicherheit:** Im offenen Netz `POOL_INGEST_TOKEN` setzen.
