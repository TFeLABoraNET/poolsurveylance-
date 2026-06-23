# pH- & ORP-Sonde per ESP32 anbinden (ESPHome)

Diese Anleitung bindet eine **analoge pH-Elektrode** (BNC) und – optional auf
demselben ESP32 – eine **ORP/Redox-Elektrode** (BNC) über je ein
**Frontend-Board** an PoolSurveylance an.

> **ORP/Redox** misst die Desinfektionskraft (mV) und korreliert mit dem
> freien Chlor. Echte Freichlor-Sensorik ist teuer; ORP ist der bezahlbare
> Standard. Soll zusätzlich **automatisch Säure dosiert** werden (pH-Minus per
> Quetschschlauchpumpe), siehe **`docs/esp32-dosing-controller.md`** – die
> dortige Sicherheitslogik baut direkt auf dieser Sensoranbindung auf.

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
| pH `V+` / `VCC` | `3V3` (oder `5V`, je nach Board) |
| pH `GND` | `GND` |
| pH `Po` / `A0` (Analog-Ausgang) | `GPIO34` (ADC1, nur Eingang) |
| ORP `V+` / `VCC` | `3V3` / `5V` |
| ORP `GND` | `GND` |
| ORP `Po` / `A0` | `GPIO35` (ADC1, nur Eingang) |

Die jeweilige Elektrode kommt per BNC ans zugehörige Frontend-Board.
**Wichtig:** ADC1-Pins (GPIO32–39) verwenden – ADC2 ist bei aktivem WLAN
blockiert.

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

  # --- ORP/Redox über zweiten Analog-Eingang (optional) ---
  - platform: adc
    pin: GPIO35
    name: "Pool ORP (Rohspannung)"
    id: orp_voltage
    attenuation: 11db
    update_interval: 30s
    filters:
      - median:
          window_size: 7
          send_every: 7
      - calibrate_linear:
          # gemessene_Spannung -> ORP (mV); mit 468-mV-Prüflösung kalibrieren.
          - 1.50 -> 0       # <- Spannung bei 0 mV (Kurzschluss/Nulllösung)
          - 2.07 -> 468     # <- Spannung in 468-mV-Pufferlösung

  - platform: template
    name: "Pool ORP"
    id: orp_value
    unit_of_measurement: "mV"
    accuracy_decimals: 0
    lambda: 'return id(orp_voltage).state;'
    update_interval: 300s

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
              root["orp"] = id(orp_value).state;
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
              root["orp"] = id(orp_value).state;
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
- **Felder:** Erlaubt sind `ph`, `free_cl`, `total_cl`, `ta`, `cya`, `orp`,
  `temperature` (plus `source`, `note`, `measured_at`). Es muss mindestens ein
  Messwert enthalten sein.
- **ORP-Kalibrierung:** Mit einer **ORP-Prüflösung** (z. B. 468 mV) die
  Rohspannung ablesen und bei `calibrate_linear` eintragen. ORP driftet
  weniger als pH, sollte aber gelegentlich geprüft werden.
- **Temperaturkompensation:** Die Apera 201-C hat keinen Temperaturfühler.
  Für höhere Genauigkeit einen Wassertemperatur-Sensor (z. B. DS18B20)
  ergänzen und `temperature` mitsenden.
- **Sicherheit:** Im offenen Netz `POOL_INGEST_TOKEN` setzen.
