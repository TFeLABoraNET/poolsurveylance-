# PoolSurveylance – Add-on-Dokumentation

## Voraussetzungen

- Home Assistant OS (oder Supervised) – z. B. auf einem Raspberry Pi.
- Das Docker-Image muss in der GHCR veröffentlicht sein (siehe Haupt-README,
  Abschnitt „Deployment auf den Raspberry Pi mit HA OS"). Insbesondere muss
  das GHCR-Paket **öffentlich** sein, damit der Supervisor es ohne Login ziehen
  kann.

## Installation

1. **Add-on-Repository hinzufügen**
   Einstellungen → Add-ons → Add-on Store → Menü (⋮ oben rechts) →
   *Repositories* → URL des GitHub-Repos eintragen:
   `https://github.com/TFeLABoraNET/poolsurveylance-`
2. **Add-on installieren**
   Im Add-on Store erscheint nun „PoolSurveylance". Anklicken → *Installieren*.
3. **Starten**
   Nach der Installation auf *Starten* klicken. Anschließend taucht in der
   linken Seitenleiste der Eintrag **Pool** auf.

## Konfiguration

Im Tab *Konfiguration* des Add-ons:

| Option | Bedeutung |
|---|---|
| `mqtt_enabled` | MQTT/Home-Assistant-Sensoren aktivieren (an/aus). |
| `mqtt_host` | Broker-Adresse. Bei Nutzung des Mosquitto-Add-ons: `core-mosquitto`. |
| `mqtt_port` | MQTT-Port (Standard `1883`). |
| `mqtt_username` / `mqtt_password` | Zugangsdaten des MQTT-Brokers. |

> Bei aktivem MQTT meldet sich PoolSurveylance per Auto-Discovery selbst als
> Gerät an; die Sensoren (pH, Chlor, Alkalinität, Cyanursäure, Temperatur)
> erscheinen automatisch in Home Assistant.

## Datenspeicher

Die SQLite-Datenbank liegt im persistenten Add-on-Verzeichnis `/data` und
bleibt über Neustarts und Updates hinweg erhalten.

## Aktualisieren

Sobald eine neue Version veröffentlicht ist (siehe Haupt-README,
Release-Schritt), erscheint im Add-on ein *Update*-Button.
