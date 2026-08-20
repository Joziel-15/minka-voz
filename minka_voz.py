#!/usr/bin/env python3
"""
MINKA VOZ — Traductor de voz Kogui <-> Español
PORT Raspberry Pi 4 · Micrófono I2S INMP441 · Amplificador I2S MAX98357A

Escucha continua con detección de voz (VAD), botón físico opcional para
cambiar de idioma y pantalla OLED SSD1306 opcional.
Traducción 100% local vía diccionario SQLite. TTS 100% offline.

Optimizaciones frente a la versión anterior:
  - faster-whisper (CTranslate2) con cuantización int8: ~3-4x más rápido
    que openai-whisper en CPU ARM.
  - Transcripción directa desde memoria (sin escribir WAV temporal a disco).
  - Pre-roll de audio: no se corta el inicio de cada frase.
  - TTS local (Piper/espeak-ng) con caché: frases repetidas suenan al instante.
  - Detección automática de las tarjetas I2S (INMP441 / MAX98357A).

Variables de entorno opcionales:
  MINKA_MODEL   Modelo whisper: tiny | base (defecto) | small
  MINKA_VAD     Agresividad VAD 0-3 (defecto 2)
  MINKA_BTN     Pin BCM del botón de idioma (defecto 27; -1 desactiva)
  MINKA_DB      Ruta de la base de datos (defecto ~/minka/minka.db)
  MINKA_PIPER_VOICE  Ruta del modelo .onnx de Piper (defecto ~/piper-voices/...)
"""

import os
import sys
import time
import shutil
import hashlib
import tempfile
import threading
import subprocess
from collections import deque

import numpy as np

# ── Configuración general ────────────────────────────────────────────────
SAMPLE_RATE = 16000
FRAME_MS = 30                                    # duración de cada bloque analizado por el VAD
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)
SILENCIO_MAX_FRAMES = int(1000 / FRAME_MS)       # ~1 s de silencio corta la frase
HABLA_MIN_FRAMES = 2                             # frames consecutivos de voz para iniciar frase
PREROLL_FRAMES = 5                               # ~150 ms previos que se conservan
DURACION_MIN_S = 0.4                             # descarta ruidos muy cortos
DURACION_MAX_MS = 12000                          # fuerza procesamiento en frases largas

MODELO_WHISPER = os.environ.get("MINKA_MODEL", "base")
VAD_AGRESIVIDAD = int(os.environ.get("MINKA_VAD", "2"))
PIN_BOTON_IDIOMA = int(os.environ.get("MINKA_BTN", "27"))
DIR_TTS_CACHE = os.path.expanduser("~/.cache/minka-tts")

# ── Hardware opcional: OLED SSD1306 (I2C) ─────────────────────────────────
try:
    from luma.core.interface.serial import i2c
    from luma.core.render import canvas
    from luma.oled.device import ssd1306
    _oled = ssd1306(i2c(port=1, address=0x3C))
except Exception:
    _oled = None

# ── Hardware opcional: botón GPIO ──────────────────────────────────────────
GPIO = None
if PIN_BOTON_IDIOMA >= 0:
    try:
        import RPi.GPIO as GPIO
    except Exception:
        GPIO = None

# ── Estado global ──────────────────────────────────────────────────────────
modo = "k2e"          # "k2e" = Kogui->Español | "e2k" = Español->Kogui
modelo_whisper = None
procesando = False
disp_captura_sd = None     # índice sounddevice del INMP441
disp_playback_aplay = None # cadena hw:X,0 del MAX98357A para aplay


# ── Pantalla OLED (no-op si no está conectada) ────────────────────────────
def mostrar_oled(estado="Escuchando..."):
    if not _oled:
        return
    etiqueta = "Kogui -> Español" if modo == "k2e" else "Español -> Kogui"
    try:
        with canvas(_oled) as draw:
            draw.text((0, 0), "MINKA VOZ", fill="white")
            draw.text((0, 20), etiqueta, fill="white")
            draw.text((0, 45), estado[:21], fill="white")
    except Exception:
        pass


# ── Botón de idioma (opcional) ─────────────────────────────────────────────
def _cambiar_idioma(channel):
    global modo
    if procesando:
        return
    modo = "e2k" if modo == "k2e" else "k2e"
    print(f"\n  🌐 Modo cambiado: {'Kogui→Español' if modo == 'k2e' else 'Español→Kogui'}")
    mostrar_oled()


def configurar_boton():
    if GPIO is None:
        return
    try:
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(PIN_BOTON_IDIOMA, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(PIN_BOTON_IDIOMA, GPIO.FALLING,
                              callback=_cambiar_idioma, bouncetime=400)
        print(f"🔘 Botón de idioma en GPIO{PIN_BOTON_IDIOMA} activo")
    except Exception as e:
        print(f"⚠ Botón GPIO no disponible: {e}")


# ── Detección automática de tarjetas I2S ───────────────────────────────────
def detectar_tarjetas_alsa():
    """Devuelve (captura, reproduccion) como 'hw:X,0' escaneando /proc/asound."""
    cap = rep = None
    try:
        with open("/proc/asound/cards") as f:
            lineas = f.read().splitlines()
    except OSError:
        return None, None

    for i, linea in enumerate(lineas):
        if not linea or not linea[0].isdigit() or i + 1 >= len(lineas):
            continue
        cid = linea.split()[0]
        desc = lineas[i + 1].lower()
        es_i2s = any(k in desc for k in ("hifiberry", "max98357", "inmp",
                                         "voicehat", "i2s", "adc", "dac"))
        if not es_i2s or cid == "0":
            continue
        tiene_cap = os.path.isdir(f"/proc/asound/card{cid}/pcm0c")
        tiene_rep = os.path.isdir(f"/proc/asound/card{cid}/pcm0p")
        if tiene_cap and cap is None:
            cap = f"hw:{cid},0"
        if tiene_rep and rep is None:
            rep = f"hw:{cid},0"
    return cap, rep


def indice_captura_sounddevice(hw_cap):
    """Traduce la tarjeta ALSA a un índice de sounddevice (PortAudio)."""
    if not hw_cap:
        return None
    try:
        import sounddevice as sd
        dispositivos = sd.query_devices()
    except Exception:
        return None
    palabras_clave = [p.strip().lower() for p in
                      ("hifiberry", "max98357", "inmp", "voicehat", "adc", "i2s")]
    for idx, d in enumerate(dispositivos):
        try:
            nombre = str(d["name"]).lower()
            if d.get("max_input_channels", 0) > 0 and any(k in nombre for k in palabras_clave):
                return idx
        except Exception:
            continue
    return None


def configurar_audio():
    global disp_captura_sd, disp_playback_aplay
    cap, rep = detectar_tarjetas_alsa()
    disp_captura_sd = indice_captura_sounddevice(cap)
    disp_playback_aplay = rep

    if disp_captura_sd is not None:
        print(f"🎤 INMP441 detectado en {cap}")
    else:
        print("⚠ INMP441 no detectado — usando micrófono por defecto")
    if disp_playback_aplay is not None:
        print(f"🔊 MAX98357A detectado en {rep}")
    else:
        print("⚠ MAX98357A no detectado — usando salida por defecto")


# ── Cargar modelo Whisper (faster-whisper, int8) ──────────────────────────
def cargar_modelos():
    global modelo_whisper
    from faster_whisper import WhisperModel
    print(f"⏳ Cargando modelo Whisper '{MODELO_WHISPER}' (int8)...")
    modelo_whisper = WhisperModel(
        MODELO_WHISPER,
        device="cpu",
        compute_type="int8",
        cpu_threads=os.cpu_count() or 4,
        num_workers=1,
    )
    # Calentamiento: la primera inferencia es más lenta (inicialización interna)
    modelo_whisper.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32),
                              language="es", beam_size=1)
    print("✓ Whisper listo")


# ── Síntesis de voz 100% offline con caché ─────────────────────────────────
def _ruta_cache(texto):
    clave = hashlib.sha1(f"{modo}|{texto.lower()}".encode()).hexdigest()
    return os.path.join(DIR_TTS_CACHE, f"{clave}.wav")


def _sintetizar_piper(texto, wav_out):
    voz = os.environ.get(
        "MINKA_PIPER_VOICE",
        os.path.expanduser("~/piper-voices/es_ES-mls_10246-low.onnx"),
    )
    binario = shutil.which("piper") or os.path.expanduser("~/minka-voz/venv/bin/piper")
    if not (voz.endswith(".onnx") and os.path.exists(voz)):
        return False
    if not (binario and os.path.exists(binario)):
        return False
    p = subprocess.run([binario, "-m", voz, "-f", wav_out],
                       input=texto.encode(), capture_output=True, timeout=30)
    return p.returncode == 0 and os.path.exists(wav_out)


def _sintetizar_espeak(texto, wav_out):
    binario = shutil.which("espeak-ng") or shutil.which("espeak")
    if not binario:
        return False
    p = subprocess.run([binario, "-v", "es", "-s", "155", "-w", wav_out, texto],
                       capture_output=True, timeout=30)
    return p.returncode == 0 and os.path.exists(wav_out)


def hablar(texto):
    os.makedirs(DIR_TTS_CACHE, exist_ok=True)
    wav = _ruta_cache(texto)

    # Caché: frases ya sintetizadas se reproducen al instante
    if not os.path.exists(wav):
        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False,
                                          dir=DIR_TTS_CACHE)
        tmp.close()
        ok = _sintetizar_piper(texto, tmp.name) or _sintetizar_espeak(texto, tmp.name)
        if not ok:
            os.unlink(tmp.name)
            print("⚠ Sin motor TTS disponible (instala piper o espeak-ng)")
            return
        os.replace(tmp.name, wav)

    dispositivo = ["-D", disp_playback_aplay] if disp_playback_aplay else []
    subprocess.run(["aplay", "-q"] + dispositivo + [wav],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ── Traducción: primero frases completas, luego palabra por palabra ───────
def traducir_inteligente(texto, direccion):
    texto_limpio = texto.strip().strip(".,!?;:").lower()
    if not texto_limpio:
        return None, "no_encontrado"

    frase_resultado = db.buscar_frase_en_diccionario(texto_limpio, direccion)
    if frase_resultado:
        traducciones = [r["traduccion"] for r in frase_resultado]
        sin_traducir = [r for r in frase_resultado if r["traduccion"].startswith("[")]
        traduccion_completa = " ".join(traducciones)
        if not sin_traducir:
            return traduccion_completa, "diccionario"
        elif len(sin_traducir) < len(frase_resultado):
            return traduccion_completa, "diccionario_parcial"

    encontradas = db.buscar_en_diccionario(texto_limpio, direccion)
    if encontradas:
        palabras = texto_limpio.split()
        resultado = []
        todas = True
        for p in palabras:
            p_limpia = p.strip(".,!?;:")
            if p_limpia in encontradas:
                resultado.append(encontradas[p_limpia])
            else:
                todas = False
                resultado.append(f"[{p_limpia}]")
        if todas:
            return " ".join(resultado), "diccionario"
        else:
            return " ".join(resultado), "diccionario_parcial"
    return None, "no_encontrado"


# ── Procesar un segmento de audio ya capturado ───────────────────────────
def procesar_audio(audio_int16):
    global procesando
    procesando = True
    t_total = time.perf_counter()
    mostrar_oled("Transcribiendo...")
    try:
        # faster-whisper acepta float32 directamente: sin WAV temporal en disco
        audio_f32 = audio_int16.astype(np.float32) / 32768.0
        lang = "es" if modo == "e2k" else None
        t0 = time.perf_counter()
        segmentos, _info = modelo_whisper.transcribe(
            audio_f32,
            language=lang,
            beam_size=1,                      # greedy: máximo velocidad
            temperature=0.0,
            condition_on_previous_text=False,
            no_speech_threshold=0.6,
            compression_ratio_threshold=2.4,
        )
        texto = " ".join(s.text for s in segmentos).strip()
        t_stt = time.perf_counter() - t0

        if not texto:
            print("⚠ No se entendió, intenta de nuevo")
            mostrar_oled("No entendí")
            time.sleep(1)
            return

        origen = "Kogui" if modo == "k2e" else "Español"
        destino = "Español" if modo == "k2e" else "Kogui"
        print(f"\n[{origen}] {texto}")

        mostrar_oled("Traduciendo...")
        t0 = time.perf_counter()
        traduccion, fuente = traducir_inteligente(texto, modo)
        t_trad = time.perf_counter() - t0

        if fuente == "no_encontrado":
            print(f"⚠ Palabra no encontrada en el diccionario ({destino})")
            mostrar_oled("No en diccionario")
            time.sleep(1)
            return

        print(f"[{destino}] {traduccion}  ({fuente})")
        db.guardar_conversacion(texto, traduccion, modo, fuente)

        mostrar_oled("Hablando...")
        t0 = time.perf_counter()
        hablar(traduccion)
        t_tts = time.perf_counter() - t0

        print(f"⏱ STT {t_stt:.1f}s | Trad {t_trad:.2f}s | TTS {t_tts:.1f}s "
              f"| Total {time.perf_counter() - t_total:.1f}s")
    except Exception as e:
        print(f"✗ Error: {e}")
    finally:
        procesando = False
        mostrar_oled()


# ── Loop de escucha continua con VAD + pre-roll ───────────────────────────
def escucha_continua():
    import webrtcvad
    import sounddevice as sd

    vad = webrtcvad.Vad(VAD_AGRESIVIDAD)
    mostrar_oled()
    print("🎤 Escucha continua activa — habla cuando quieras (Ctrl+C para salir)")

    preroll = deque(maxlen=PREROLL_FRAMES)
    buffer_audio = []
    en_habla = False
    silencio_contador = 0
    habla_consecutiva = 0

    def callback(indata, frames, time_info, status):
        nonlocal buffer_audio, en_habla, silencio_contador, habla_consecutiva

        if procesando:
            return  # no seguir capturando mientras se procesa lo anterior

        marco = indata.copy()
        try:
            es_habla = vad.is_speech(marco.tobytes(), SAMPLE_RATE)
        except Exception:
            es_habla = False

        if not en_habla:
            preroll.append(marco)
            habla_consecutiva = habla_consecutiva + 1 if es_habla else 0
            if habla_consecutiva >= HABLA_MIN_FRAMES:
                buffer_audio = list(preroll)   # conserva el inicio de la frase
                preroll.clear()
                en_habla = True
                silencio_contador = 0
        else:
            buffer_audio.append(marco)
            if es_habla:
                silencio_contador = 0
            else:
                silencio_contador += 1
                excede = len(buffer_audio) * FRAME_MS > DURACION_MAX_MS
                if silencio_contador > SILENCIO_MAX_FRAMES or excede:
                    audio_completo = np.concatenate(buffer_audio, axis=0)
                    buffer_audio = []
                    en_habla = False
                    silencio_contador = 0
                    threading.Thread(target=procesar_audio, args=(audio_completo,),
                                     daemon=True).start()

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16',
                        blocksize=FRAME_SAMPLES, device=disp_captura_sd,
                        callback=callback):
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nSaliendo...")


# ── Main ──────────────────────────────────────────────────────────────────
def main():
    db.inicializar_db()
    configurar_boton()
    configurar_audio()
    cargar_modelos()
    try:
        escucha_continua()
    finally:
        if GPIO is not None:
            GPIO.cleanup()


if __name__ == "__main__":
    main()
