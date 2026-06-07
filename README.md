# 💧 PoolSurveylance

Ein kleiner, selbst gehosteter Pool-Pflege-Assistent für den Raspberry Pi.
Du trägst deine Wasser-Messwerte ein und bekommst – anhand deiner eigenen
Chemikalien – einen konkreten Dosiervorschlag (wie viel wovon zugeben).

Läuft als Docker-Container und lässt sich optional per MQTT in **Home
Assistant** einbinden. Der MQTT-Weg ist gleichzeitig die Grundlage für die
geplanten Ausbaustufen (ESP32-Sonden, automatische pH-Dosierung).

> ⚠️ **Hinweis:** Die Dosiermengen sind Schätzwerte auf Basis der von dir
> hinterlegten Produktangaben. Gib lieber etwas weniger zu, lass die
> Umwälzpumpe laufen und miss anschließend nach.

---

## Funktionen (Schritt 1)

- **Konfigurationsseite**
  - Beckenvolumen, Pumpen-Durchfluss
  - Zielwerte (Min/Soll/Max) für pH, freies Chlor, Alkalinität (TA), Cyanursäure
  - Verwaltung deiner Chemikalien – die Dosierung wird so eingetragen, wie sie
    **auf der Verpackung** steht („*Menge pro Volumen ändert den Wert um …*").
- **Messung & Dosiervorschlag**
  - Messwerte manuell eintragen (pH, freies/gesamtes Chlor, TA, Cyanursäure, Temperatur)
  - farbiger Wasserstatus (im Soll / zu niedrig / zu hoch)
  - konkrete Dosierempfehlung je Chemikalie inkl. Erklärung
  - Hinweise (Reihenfolge TA → pH → Chlor, Chloramine/Stoßchlorung usw.)
- **Verlauf** aller Messungen
- **Home Assistant** (optional) via MQTT-Auto-Discovery
- **REST-API** (`/api/latest`) als Alternative für HA-RESTful-Sensoren

---

## Schnellstart (Docker auf dem Raspberry Pi)

```bash
git clone <dieses-repo> poolsurveylance
cd poolsurveylance
docker compose up -d --build
```

Danach im Browser öffnen: `http://<raspberry-pi-ip>:8000`

Beim ersten Start werden eine Beispiel-Konfiguration und typische
Standard-Chemikalien angelegt. **Bitte zuerst auf der Seite *Konfiguration*
dein Beckenvolumen und deine Chemikalien an deine Produkte anpassen.**

Die SQLite-Datenbank liegt im Volume `./data` und bleibt über Updates erhalten.

### Ohne Docker (Entwicklung)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
POOL_DATABASE_URL="sqlite:///./data/pool.db" uvicorn app.main:app --reload
```

---

## Home-Assistant-Integration (optional)

In der `docker-compose.yml` (oder per `.env`) MQTT aktivieren:

```yaml
environment:
  POOL_MQTT_ENABLED: "true"
  POOL_MQTT_HOST: "homeassistant.local"   # Adresse deines MQTT-Brokers (z. B. Mosquitto-Add-on)
  POOL_MQTT_PORT: "1883"
  POOL_MQTT_USERNAME: "dein_mqtt_user"
  POOL_MQTT_PASSWORD: "dein_mqtt_passwort"
```

Voraussetzung ist ein MQTT-Broker (z. B. das **Mosquitto**-Add-on) und die
**MQTT-Integration** in Home Assistant. PoolSurveylance meldet sich dann per
Auto-Discovery selbstständig an; die Sensoren (pH, freies Chlor, Gesamtchlor,
Alkalinität, Cyanursäure, Temperatur) erscheinen automatisch als Gerät
**PoolSurveylance**. Nach jeder neuen Messung werden die Werte aktualisiert.

Ist kein Broker erreichbar, läuft die App ohne Fehler einfach als
Standalone-Web-App weiter.

### Alternative: REST-Sensor (ohne MQTT)

```yaml
# configuration.yaml in Home Assistant
rest:
  - resource: http://<raspberry-pi-ip>:8000/api/latest
    scan_interval: 300
    sensor:
      - name: "Pool pH"
        value_template: "{{ value_json.ph }}"
      - name: "Pool Freies Chlor"
        unit_of_measurement: "mg/l"
        value_template: "{{ value_json.free_cl }}"
```

---

## Deployment auf den Raspberry Pi mit Home Assistant OS

Auf **HA OS** kannst du keine eigenen `docker`-Befehle ausführen – Container
laufen dort ausschließlich als **Add-ons**. PoolSurveylance bringt daher ein
fertiges Add-on mit, das ein per GitHub Actions vorgebautes Image aus der
GitHub Container Registry (GHCR) zieht. Auf dem Pi muss also **nichts gebaut**
werden.

### Schritt 1 – Image per GitHub Actions veröffentlichen

Der Workflow `.github/workflows/docker-publish.yml` baut die Images
automatisch. Er läuft bei jedem Push auf den Branch und bei Versions-Tags.

**Erstes Release erzeugen** (legt die Image-Tags `0.1.0` an, passend zur
Add-on-Version):

```bash
git tag v0.1.0
git push origin v0.1.0
```

Unter *GitHub → Actions* siehst du den Build. Ergebnis sind u. a.:

- `ghcr.io/<dein-user>/aarch64-poolsurveylance:0.1.0`  ← für den Pi (64-bit)
- `ghcr.io/<dein-user>/amd64-poolsurveylance:0.1.0`
- `ghcr.io/<dein-user>/poolsurveylance:0.1.0` (kombiniertes Multi-Arch-Image)

### Schritt 2 – GHCR-Paket öffentlich schalten

Damit der HA-Supervisor das Image ohne Login ziehen kann:
*GitHub → dein Profil/Org → Packages →* das Paket
`aarch64-poolsurveylance` (und `amd64-poolsurveylance`) öffnen →
*Package settings → Change visibility → Public*.

> **Achtung Groß-/Kleinschreibung:** GHCR verlangt einen klein geschriebenen
> Owner-Namen. In `addon/config.yaml` ist der Owner bereits als
> `tfelaboranet` hinterlegt – passe ihn an, falls dein GitHub-Benutzer anders
> heißt.

### Schritt 3 – Add-on in Home Assistant installieren

1. **Einstellungen → Add-ons → Add-on Store → ⋮ (oben rechts) → Repositories**
   und die Repo-URL hinzufügen:
   `https://github.com/TFeLABoraNET/poolsurveylance-`
2. Im Store erscheint **PoolSurveylance** → *Installieren*.
3. *Starten*. Die App tauct als **Pool** in der Seitenleiste auf (Ingress,
   inkl. HA-Login – kein offener Port nötig).

Im Tab *Konfiguration* des Add-ons trägst du bei Bedarf deine MQTT-Daten ein
(`mqtt_host: core-mosquitto`, falls du das Mosquitto-Add-on nutzt). Details
siehe [`addon/DOCS.md`](addon/DOCS.md).

> **Updates:** Neue Version taggen (`git tag v0.1.1 && git push origin v0.1.1`),
> in `addon/config.yaml` die `version` auf `0.1.1` setzen und pushen – Home
> Assistant bietet dann ein Update an.

### Alternative ohne HA OS

Läuft Home Assistant bei dir als Container (HA Container) oder hast du eine
separate Maschine, kannst du PoolSurveylance einfach per
`docker compose up -d` betreiben (siehe oben) und HA per MQTT oder
REST-Sensor anbinden.

---

## Wie wird die Dosis berechnet?

Jede Chemikalie speichert ihre Referenz-Dosierung in der Form
**„*X Einheit pro Y m³ ändert den Wert um Z*"** – genau so, wie es auf der
Verpackung steht. Die App rechnet daraus die Menge für dein Becken hoch:

```
Menge = (gewünschte_Änderung / Z) × (Beckenvolumen / Y) × X
```

**Beispiel:** pH-Minus mit „100 g pro 10 m³ senken den pH um 0,1". Dein
Becken hat 10 m³, der pH soll von 7,8 auf 7,2 (= 0,6) sinken:
`(0,6 / 0,1) × (10 / 10) × 100 g = 600 g`.

Die Reihenfolge der Empfehlungen folgt der gängigen Praxis: **erst die
Alkalinität (TA), dann der pH-Wert, dann das Chlor.**

---

## Projektstruktur

```
app/
  main.py        – FastAPI-App, Routen, Templates
  config.py      – Einstellungen (Umgebungsvariablen)
  database.py    – SQLite/SQLAlchemy-Setup
  models.py      – Datenmodelle (PoolConfig, Chemical, Measurement)
  crud.py        – DB-Zugriffe + Standard-Chemikalien (Seed)
  chemistry.py   – Bewertung & Dosier-Logik (Kernstück)
  mqtt.py        – optionale Home-Assistant-Anbindung
  templates/     – HTML-Oberfläche (Jinja2)
  static/        – CSS
tests/           – Tests der Dosier-Logik
addon/           – Home-Assistant-Add-on (config.yaml, Doku)
repository.yaml  – macht das Repo zu einem HA-Add-on-Repository
.github/workflows/docker-publish.yml – Multi-Arch-Build nach GHCR
Dockerfile, docker-compose.yml
```

---

## Roadmap (offen gehaltene Ausbaustufen)

- [x] **Schritt 1:** Manuelle Messwerte + Dosiervorschlag, Docker, HA-Anbindung
- [ ] **Schritt 2:** ESP32 mit pH-/Chlor-Sonden – Werte automatisch per MQTT
      einspeisen (Quelle `esp32` ist im Datenmodell bereits vorgesehen).
- [ ] **Schritt 3:** Automatische pH-Dosierung (Dosierpumpe über ESP32/HA).

Die Architektur ist darauf ausgelegt: Die Mess-Quelle ist bereits
parametrisiert, die Chemie-Logik ist von der Eingabe getrennt, und MQTT
bildet den gemeinsamen Datenbus für App, Home Assistant und künftige Sonden.

---

## Tests

```bash
pip install pytest
pytest -q
```

## Konfigurations-Referenz (Umgebungsvariablen)

| Variable | Standard | Beschreibung |
|---|---|---|
| `POOL_DATABASE_URL` | `sqlite:////data/pool.db` | Datenbank-URL |
| `POOL_MQTT_ENABLED` | `false` | MQTT/Home-Assistant aktivieren |
| `POOL_MQTT_HOST` | `localhost` | MQTT-Broker-Adresse |
| `POOL_MQTT_PORT` | `1883` | MQTT-Port |
| `POOL_MQTT_USERNAME` / `POOL_MQTT_PASSWORD` | – | MQTT-Zugang |
| `POOL_MQTT_BASE_TOPIC` | `poolsurveylance` | Basis-Topic der Zustände |
| `POOL_MQTT_DISCOVERY_PREFIX` | `homeassistant` | HA-Discovery-Prefix |
| `POOL_DEVICE_ID` | `poolsurveylance` | Geräte-ID in Home Assistant |
