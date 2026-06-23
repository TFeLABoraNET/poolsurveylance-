# Automatische pH-Minus-Dosierung (Schwefelsäure) per ESP32

Diese Anleitung beschreibt eine **autonome, sicherheits­orientierte**
pH-Senkung mit **verdünnter Schwefelsäure** über eine **Quetschschlauch­pumpe**
(Peristaltikpumpe), gesteuert vom ESP32 mit ESPHome. PoolSurveylance liefert
die Sollwerte, protokolliert jede Dosierung und begrenzt die Tagesmenge.

> ⚠️ **Sicherheitshinweis vorweg.** Schwefelsäure ist ätzend. Diese Anleitung
> richtet sich an Personen, die mit Poolchemie und Niederspannungselektronik
> vertraut sind. Eine fehlerhafte Dosieranlage kann Wasser stark übersäuern.
> Die Logik ist bewusst **konservativ und mehrfach verriegelt** – ändere die
> Schutzgrenzen nur mit Bedacht. **Im Zweifel manuell dosieren.**

## 0. Grundprinzip: „Pulsen & warten"

Säure mischt sich nicht sofort. Wer kontinuierlich nachregelt, **überdosiert
garantiert**, weil der Effekt erst Minuten später an der Sonde ankommt. Daher:

1. pH messen.
2. Liegt pH über `Ziel + Totband` **und** sind **alle** Verriegelungen frei →
   **einen kleinen, festen Stoß** dosieren (z. B. 100 ml).
3. **Wartezeit** (z. B. 15 min, mehrere Umwälzungen) – in dieser Zeit **nicht**
   dosieren, damit sich alles durchmischt.
4. Erneut messen, ggf. nächsten Stoß. So nähert man sich dem Ziel ohne
   Überschwingen.

## 1. Hardware

| Komponente | Aufgabe | Hinweis |
|---|---|---|
| ESP32 | Steuerung | ADC1-Pins für Sonden (siehe Sensor-Doku) |
| pH-Frontend + Elektrode | pH messen | `GPIO34` |
| ORP-Frontend + Elektrode | Desinfektion messen (optional) | `GPIO35` |
| **Quetschschlauchpumpe** | Säure fördern | Förderleistung kennen (ml/min)! |
| **Relais- oder MOSFET-Modul** | Pumpe schalten | passend zur Pumpenspannung |
| **Strömungswächter** | Beweist Umwälzung | **Pflicht** – Verriegelung |
| Niveauschalter (Schwimmer) im Säurekanister | „leer"-Erkennung | optional, empfohlen |
| DS18B20 | Wassertemperatur | optional |

**Schlauch & Material:** Pumpenschlauch und Dosierleitung müssen **säurefest**
sein (z. B. **Viton/FKM**). Silikon ist für viele Säuren **nicht** geeignet.
Die Säure wird **nach** Filter/Heizung in die Rücklaufleitung dosiert, damit
sie sofort verdünnt im Becken ankommt – nie direkt ins stehende Wasser.

**Verdünnung:** Eine **verdünnte** Lösung (z. B. ~15 %) ist deutlich gutmütiger
zu regeln und sicherer zu handhaben als konzentrierte (~37–38 %). Säure **immer
ins Wasser** geben, nie Wasser in die Säure. Schutzbrille und -handschuhe.

## 2. Die Verriegelungen (warum dosiert wird – oder eben nicht)

Ein Stoß wird **nur** ausgelöst, wenn **alle** Bedingungen gleichzeitig erfüllt
sind. Jede einzelne ist ein „Nein"-Veto:

1. **Freigabe aktiv** – `dosing_enabled` (Schalter in der App / am Gerät).
2. **Strömung vorhanden** – Strömungswächter meldet laufende Umwälzung.
   Ohne Strömung **niemals** dosieren (lokale Übersäuerung!).
3. **pH-Messwert frisch** – letzte Aktualisierung < 90 s. Eingefrorener Wert =
   Sondenfehler → kein Dosieren.
4. **pH-Messwert plausibel** – zwischen 4,0 und 9,0. Werte außerhalb deuten auf
   abgezogene/defekte Sonde (ADC am Anschlag) → kein Dosieren.
5. **pH über Schwelle** – `pH > Ziel + Totband` (Totband verhindert Pendeln).
6. **Sicherheitsboden** – `pH > ph_dose_floor` (z. B. 6,8). Darunter **nie**
   dosieren, egal was sonst gilt.
7. **Tagesbudget frei** – `dosed_ml_today < dose_max_ml_day` (harte Obergrenze).
8. **Keine Wartezeit aktiv** – seit dem letzten Stoß ist `dose_wait_minutes`
   vergangen.
9. **Kanister nicht leer** – Niveauschalter (falls vorhanden).

Zusätzliche Schutzmechanismen:

- **Stoß-Zeitbegrenzung:** Die Pumpe läuft pro Stoß maximal die berechnete
  Dauer; das `script` ist `mode: single` (kein paralleler/„hängender" Lauf).
- **Sicherer Bootzustand:** Pumpe nach Neustart **aus**, Freigabe nicht
  automatisch „an" (Schalter `restore_mode` konservativ).
- **Tagesreset:** `dosed_ml_today` wird um Mitternacht auf 0 gesetzt.
- **„Kein Effekt"-Wächter:** Sinkt der pH trotz mehrerer Stöße nicht, wird die
  Automatik gestoppt und gemeldet (leerer Kanister, Luft im Schlauch, falsche
  Konzentration, blockierte Sonde).

## 3. ESPHome-Konfiguration

Ergänzt die Sensor-Konfiguration aus `docs/esp32-ph-sensor.md` (pH auf
`GPIO34`). Die Sollwerte stehen als `substitutions` oben – sie spiegeln die
Werte aus den App-Einstellungen. (Alternativ können sie per
`GET /api/dosing-config` zyklisch geholt werden, siehe Abschnitt 5.)

```yaml
substitutions:
  ph_target: "7.2"
  ph_deadband: "0.1"        # erst dosieren über 7.3
  ph_floor: "6.8"           # harte Untergrenze
  ml_per_shot: "100"        # ml pro Dosierstoß
  pump_ml_per_min: "60"     # Förderleistung der Pumpe
  max_ml_day: "1000"        # harte Tagesobergrenze
  wait_minutes: "15"        # Durchmisch-Pause nach jedem Stoß
  ingest_host: "http://<raspberry-pi-ip>:8000"

globals:
  - id: dosed_ml_today
    type: float
    restore_value: yes
    initial_value: "0"
  - id: last_dose_ms
    type: uint32
    restore_value: no
    initial_value: "0"
  - id: no_effect_count       # zählt Stöße ohne pH-Wirkung
    type: int
    restore_value: no
    initial_value: "0"
  - id: ph_at_last_dose
    type: float
    restore_value: no
    initial_value: "0"

# Säurepumpe als schaltbarer Ausgang (Relais/MOSFET an z. B. GPIO25)
output:
  - platform: gpio
    pin: GPIO25
    id: pump_output

switch:
  # Physischer Pumpenschalter (wird vom Skript bedient; manuell nur zum Testen)
  - platform: output
    name: "Säurepumpe"
    id: acid_pump
    output: pump_output
    restore_mode: ALWAYS_OFF

  # Freigabe der Automatik (App spiegelt diesen Zustand; Not-Aus = ausschalten)
  - platform: template
    name: "Dosier-Automatik freigegeben"
    id: dosing_enabled
    optimistic: true
    restore_mode: ALWAYS_OFF      # nach Stromausfall NICHT automatisch dosieren

binary_sensor:
  # Strömungswächter: schließt bei laufender Umwälzung (INPUT_PULLUP-Logik anpassen)
  - platform: gpio
    name: "Umwälz-Strömung"
    id: flow_ok
    pin:
      number: GPIO27
      mode: INPUT_PULLUP
      inverted: true

  # Säurekanister-Niveau: "an" = noch Säure vorhanden (optional)
  - platform: gpio
    name: "Säure vorhanden"
    id: acid_present
    pin:
      number: GPIO14
      mode: INPUT_PULLUP
      inverted: true

# Komfort-Sensor: heute dosierte Menge (in der App/HA sichtbar)
sensor:
  - platform: template
    name: "Säure heute dosiert"
    id: dosed_today_sensor
    unit_of_measurement: "ml"
    accuracy_decimals: 0
    lambda: 'return id(dosed_ml_today);'
    update_interval: 60s

# Tagesreset um Mitternacht
time:
  - platform: sntp
    id: sntp_time
    on_time:
      - seconds: 0
        minutes: 0
        hours: 0
        then:
          - lambda: 'id(dosed_ml_today) = 0;'

# Ein Dosierstoß: prüft NICHTS mehr (das macht das interval) – fährt nur sicher
script:
  - id: do_dose
    mode: single                 # nie zwei Stöße parallel
    then:
      - logger.log: "Dosierstoß startet"
      - switch.turn_on: acid_pump
      # Pumpe exakt für die berechnete Dauer laufen lassen:
      - delay: !lambda 'return (int)(${ml_per_shot} / ${pump_ml_per_min} * 60000.0);'
      - switch.turn_off: acid_pump
      - lambda: |-
          id(dosed_ml_today) += ${ml_per_shot};
          id(last_dose_ms) = millis();
          // "Kein Effekt"-Erkennung: hat der vorige Stoß den pH gesenkt?
          if (id(ph_at_last_dose) > 0 && id(ph_value).state >= id(ph_at_last_dose) - 0.02) {
            id(no_effect_count) += 1;
          } else {
            id(no_effect_count) = 0;
          }
          id(ph_at_last_dose) = id(ph_value).state;
      # Stoß an die App melden (Protokoll + Tagesmengen-Abgleich)
      - http_request.post:
          url: ${ingest_host}/api/dose-events
          headers:
            Content-Type: application/json
            X-API-Key: !secret pool_ingest_token
          json: |-
            root["ml"] = ${ml_per_shot};
            root["pump_seconds"] = ${ml_per_shot} / ${pump_ml_per_min} * 60.0;
            root["ph_before"] = id(ph_value).state;
            root["ph_target"] = ${ph_target};
            root["trigger"] = "auto";
            root["source"] = "esp32";
      # "Kein Effekt" nach 3 Stößen -> Automatik stoppen und Alarm melden
      - if:
          condition:
            lambda: 'return id(no_effect_count) >= 3;'
          then:
            - switch.turn_off: dosing_enabled
            - logger.log:
                level: WARN
                format: "Kein pH-Effekt nach 3 Stoessen - Automatik gestoppt!"
            - http_request.post:
                url: ${ingest_host}/api/dose-events
                headers:
                  Content-Type: application/json
                  X-API-Key: !secret pool_ingest_token
                json: |-
                  root["ml"] = 0;
                  root["trigger"] = "fault";
                  root["source"] = "esp32";
                  root["note"] = "Kein pH-Effekt nach 3 Stoessen - Automatik gestoppt";

# Der Regler: prüft jede Minute ALLE Verriegelungen
interval:
  - interval: 60s
    then:
      - if:
          condition:
            and:
              - switch.is_on: dosing_enabled
              - binary_sensor.is_on: flow_ok
              - binary_sensor.is_on: acid_present
              - lambda: 'return !isnan(id(ph_value).state);'
              # Messwert plausibel (Sonde nicht abgezogen):
              - lambda: 'return id(ph_value).state > 4.0 && id(ph_value).state < 9.0;'
              # Über Ziel + Totband:
              - lambda: 'return id(ph_value).state > ${ph_target} + ${ph_deadband};'
              # Über hartem Sicherheitsboden:
              - lambda: 'return id(ph_value).state > ${ph_floor};'
              # Tagesbudget noch frei:
              - lambda: 'return id(dosed_ml_today) + ${ml_per_shot} <= ${max_ml_day};'
              # Wartezeit seit letztem Stoß abgelaufen (oder noch nie dosiert):
              - lambda: |-
                  return id(last_dose_ms) == 0 ||
                         (millis() - id(last_dose_ms)) > (uint32_t)(${wait_minutes} * 60000.0);
          then:
            - script.execute: do_dose
```

> **`http_request`** und **`mqtt`** müssen wie in der Sensor-Doku konfiguriert
> sein. Den Token legst du in `secrets.yaml` als `pool_ingest_token` ab und
> setzt in der App `POOL_INGEST_TOKEN` auf denselben Wert.

## 4. Inbetriebnahme (Schritt für Schritt)

1. **Trocken testen, ohne Säure.** Schlauch in einen Wasserbehälter, Becher
   unterstellen. In der App pH-Sonde kalibrieren (siehe Sensor-Doku).
2. **Pumpenleistung messen:** Pumpe 60 s laufen lassen, geförderte ml messen →
   `pump_ml_per_min` eintragen. Davon hängt die korrekte Dosiermenge ab.
3. **Strömungswächter prüfen:** Umwälzpumpe aus → `flow_ok` muss „aus" sein.
   Vergewissere dich, dass **ohne Strömung nicht dosiert** wird.
4. **Budget klein anfangen:** `dose_max_ml_day` zunächst niedrig (z. B. auf eine
   pH-Senkung von ~0,1–0,2 begrenzt) und beobachten. Lieber zu wenig.
5. **Erst dann Säure anschließen** und die Automatik in der App freigeben
   (Tab **Dosierung → „Dosierung freigeben"**).
6. **Mitlaufen lassen** und das **Dosier-Protokoll** in der App prüfen:
   Stöße, pH davor, Tagesmenge. Bei Auffälligkeiten **Not-Aus**.

## 5. Zusammenspiel mit der App

- **Messwerte** (`ph`, `orp`) kommen über `POST /api/measurements` bzw. MQTT
  `poolsurveylance/ingest` (siehe Sensor-Doku) und erscheinen in **Messung**,
  **Trends** und im **Wasserstatus**.
- **Dosier-Stöße** meldet der ESP32 an `POST /api/dose-events` (oder MQTT
  `poolsurveylance/dose`). Die App protokolliert sie, zieht den Verbrauch vom
  **Säure-Lagerbestand** ab und summiert die **Tagesmenge**.
- **Sollwerte/Freigabe** pflegst du in **Einstellungen → Automatische
  pH-Minus-Dosierung**; bei aktivem MQTT spiegelt die App sie nach
  `poolsurveylance/command` (retained).
- **Tagesbudget abfragen:** `GET /api/dosing-config` liefert Sollwerte **und**
  `budget_remaining_ml` – so kennt der ESP32 die Obergrenze auch nach einem
  Neustart. (Optionaler Pull statt fester `substitutions`.)
- **Not-Aus:** Tab **Dosierung → „NOT-AUS / Stoppen"** setzt `dosing_enabled`
  sofort auf 0 (und spiegelt das per MQTT an den ESP32).

## 6. Grenzen & Hinweise

- Diese Logik ist eine **robuste Bastel-/DIY-Lösung**, kein zertifizierter
  Dosierregler. Für unbeaufsichtigten Dauerbetrieb in öffentlichen Becken sind
  geprüfte Anlagen vorgeschrieben.
- **TA beeinflusst alles:** Bei hoher Gesamtalkalinität braucht es viel mehr
  Säure pro pH-Schritt, bei niedriger TA kippt der pH schnell. Halte die TA im
  Sollbereich – die App warnt und rechnet dafür.
- **Redundanz:** Der `ph_dose_floor` und das `dose_max_ml_day` sind die
  wichtigsten „letzten Netze". Setze sie konservativ.
- Prüfe Schlauch, Verschraubungen und Sondenkalibrierung **regelmäßig**.
  Quetschschläuche sind Verschleißteile.
