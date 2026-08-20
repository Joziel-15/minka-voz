# 🌿 MINKA VOZ — Port Raspberry Pi 4

Traductor de voz **Kogui ↔ Español** 100% offline para Raspberry Pi 4, con
micrófono digital I2S **INMP441** y amplificador de audio I2S **MAX98357A**.

> Este repositorio es el port embebido de MINKA VOZ (las versiones de escritorio
> Windows y Android viven en `minka-voz-main`). Traducción por diccionario
> SQLite local (~108 palabras base incluidas), sin APIs externas ni internet.

---

## ✨ Qué incluye este port

| Componente | Implementación |
|---|---|
| Reconocimiento de voz | **faster-whisper** (CTranslate2) cuantizado **int8** — 3-4× más rápido que openai-whisper en CPU ARM |
| Transcripción | Directa desde memoria (sin WAV temporales en disco) |
| Detección de voz | webrtcvad + pre-roll de 150 ms (no corta el inicio de las frases) |
| Síntesis de voz | **100% offline**: Piper (recomendado) → espeak-ng, con caché de frases |
| Reproducción | `aplay` directo a la tarjeta MAX98357A (sin SDL/pygame) |
| Detección de hardware | Autodetección de tarjetas I2S INMP441 / MAX98357A |
| Extras opcionales | Botón físico GPIO27 (cambiar idioma) y pantalla OLED SSD1306 |
| Arranque automático | Servicio systemd |

## 🔌 Cableado

### Micrófono INMP441 → GPIO (overlay `hifiberry-adc`)

| INMP441 | Raspberry Pi 4 | Pin físico |
|---|---|---|
| VDD | 3.3V | 1 |
| GND | GND | 6 |
| SCK (BCLK) | **GPIO18** | 12 |
| WS (LRCLK) | **GPIO19** | 35 |
| SD (datos) | **GPIO20** | 38 |
| L/R | GND (canal izquierdo) | 9 |

### Amplificador MAX98357A → GPIO (overlay `hifiberry-dac`)

| MAX98357A | Raspberry Pi 4 | Pin físico |
|---|---|---|
| VIN | 5V | 2 o 4 |
| GND | GND | 14 |
| BCLK | **GPIO18** | 12 (compartido con el mic) |
| LRC (LRCLK) | **GPIO19** | 35 (compartido con el mic) |
| DIN | **GPIO21** | 40 |
| GAIN | sin conectar = 9 dB | — |
| SD | sin conectar (modo activo) | — |

> Ambos módulos comparten los relojes I2S (GPIO18/19); las líneas de datos son
> independientes (entrada GPIO20, salida GPIO21), por lo que funcionan
> simultáneamente como dos tarjetas ALSA separadas.

### Opcionales

- **Botón de idioma**: entre GPIO27 y GND (`MINKA_BTN=-1` lo desactiva).
- **OLED SSD1306**: I2C — SDA→GPIO2, SCL→GPIO3, VCC→3.3V, GND→GND.

## ⚙️ Configuración I2S

`instalar.sh` añade esto automáticamente al final de `/boot/firmware/config.txt`:

```
dtparam=i2s=on
dtoverlay=hifiberry-adc   # INMP441 (captura)
dtoverlay=hifiberry-dac   # MAX98357A (salida)
```

## 🚀 Instalación

Requiere **Raspberry Pi OS de 64 bits** (obligatorio para faster-whisper).

```bash
git clone https://github.com/Joziel-15/minka-voz.git
cd minka-voz
bash instalar.sh
sudo reboot
```

El instalador: dependencias del sistema → overlays I2S → entorno virtual →
librerías Python → voz offline Piper (opcional, recomendada) → servicio systemd
(opcional).

Tras reiniciar, MINKA arranca solo en escucha continua. Manualmente:

```bash
cd minka-voz && source venv/bin/activate && python3 minka_voz.py
```

## 🗣 Uso

- Habla con normalidad: al detectar ~1 s de silencio transcribe, traduce y responde por el altavoz.
- **Botón GPIO27** (si está conectado): alterna Kogui→Español / Español→Kogui.
- El diccionario se comparte con el bot de Telegram en `~/minka/minka.db` (configurable con `MINKA_DB`).
- La primera ejecución descarga el modelo Whisper una única vez; después todo funciona sin internet.

## ⚡ Rendimiento (Raspberry Pi 4, frases de ~3 s)

| Modelo (`MINKA_MODEL`) | Latencia STT aprox. | Precisión |
|---|---|---|
| `tiny` | ~1–2 s | Básica |
| `base` *(defecto)* | ~2–4 s | Buena |
| `small` | ~8–15 s | Alta |

Optimizaciones ya aplicadas: cuantización int8, `beam_size=1`, multihilo CPU,
transcripción en memoria, caché TTS y traducción por frases (*longest-match*)
antes que palabra por palabra.

Consejos extra:
```bash
# Máxima velocidad (menor precisión):
echo 'Environment=MINKA_MODEL=tiny' | sudo tee -a /etc/systemd/system/minka-voz.service
# Liberar RAM no usando escritorio:
sudo systemctl set-default multi-user.target
```

## 🔧 Variables de entorno

| Variable | Defecto | Descripción |
|---|---|---|
| `MINKA_MODEL` | `base` | Modelo whisper: tiny/base/small |
| `MINKA_VAD` | `2` | Agresividad del VAD (0 permisivo – 3 estricto) |
| `MINKA_BTN` | `27` | Pin BCM del botón (-1 desactiva) |
| `MINKA_DB` | `~/minka/minka.db` | Ruta de la base de datos |
| `MINKA_PIPER_VOICE` | `~/piper-voices/es_ES-mls_10246-low.onnx` | Modelo Piper |

## 🛠 Solución de problemas

| Problema | Solución |
|---|---|
| No aparece la tarjeta ADC/DAC en `arecord -l` / `aplay -l` | Verifica el cableado y que `config.txt` tenga los overlays; reinicia |
| Grabación silenciosa o ruido blanco | Revisa SD→GPIO20 y L/R→GND del INMP441; prueba `MINKA_VAD=3` |
| Sin sonido en el altavoz | Comprueba DIN→GPIO21, VIN→5V y el altavoz (4–8 Ω, 3 W máx.) |
| "Sin motor TTS disponible" | Ejecuta `instalar.sh` (instala espeak-ng) o descarga Piper |
| Primera respuesta lenta | Es la descarga/carga inicial del modelo; las siguientes son rápidas |
| Error ctranslate2 al instalar | Confirma sistema de 64 bits: `uname -m` debe mostrar `aarch64` |

## 📁 Estructura

```
minka_voz.py        # Aplicación principal (escucha continua + traducción + TTS)
database.py         # Diccionario SQLite compartido + historial
instalar.sh         # Instalador completo (I2S, dependencias, servicio)
requirements.txt    # Dependencias Python
minka-voz.service   # Plantilla systemd (referencia)
```
