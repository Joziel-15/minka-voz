#!/usr/bin/env python3
"""
MINKA VOZ — Traductor de voz Kogui <-> Español (versión Raspberry Pi)
Escucha continua con detección de voz (VAD), botón físico para cambiar
de idioma y pantalla OLED SSD1306 mostrando el modo activo.
Traducción 100% local vía diccionario SQLite (sin APIs externas).
"""

import os
import time
import tempfile
import threading
import numpy as np
import sounddevice as sd
import soundfile as sf
import webrtcvad
import whisper
from gtts import gTTS
import pygame
import RPi.GPIO as GPIO
from luma.core.interface.serial import i2c
from luma.core.render import canvas
from luma.oled.device import ssd1306
import database as db

# ── Configuración general ────────────────────────────────────────────────
SAMPLE_RATE = 16000
FRAME_MS = 30                                   # duración de cada bloque de audio analizado
FRAME_SAMPLES = int(SAMPLE_RATE * FRAME_MS / 1000)
SILENCIO_MAX_FRAMES = int(1000 / FRAME_MS)      # ~1 segundo de silencio corta la frase
VAD_AGRESIVIDAD = 2                             # 0 (permisivo) - 3 (estricto)

# ── Pines GPIO (BCM) ─────────────────────────────────────────────────────
PIN_BOTON_IDIOMA = 27   # botón para alternar Kogui<->Español
# El botón de "encendido" es el encendido físico de la Pi: al arrancar,
# este script corre solo (via systemd) y entra directo a escucha continua.

# ── Pantalla OLED SSD1306 (I2C) ──────────────────────────────────────────
serial = i2c(port=1, address=0x3C)
oled = ssd1306(serial)

# ── Estado global ─────────────────────────────────────────────────────────
modo = "k2e"          # "k2e" = Kogui->Español | "e2k" = Español->Kogui
modelo_whisper = None
procesando = False

# ── Pantalla OLED ─────────────────────────────────────────────────────────
def mostrar_oled(estado="Escuchando..."):
    etiqueta = "Kogui -> Español" if modo == "k2e" else "Español -> Kogui"
    with canvas(oled) as draw:
        draw.text((0, 0), "MINKA VOZ", fill="white")
        draw.text((0, 20), etiqueta, fill="white")
        draw.text((0, 45), estado, fill="white")

# ── Botón de idioma ───────────────────────────────────────────────────────
def _cambiar_idioma(channel):
    global modo
    if procesando:
        return
    modo = "e2k" if modo == "k2e" else "k2e"
    print(f"\n  🌐 Modo cambiado: {'Kogui→Español' if modo == 'k2e' else 'Español→Kogui'}")
    mostrar_oled()

def configurar_boton():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PIN_BOTON_IDIOMA, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(PIN_BOTON_IDIOMA, GPIO.FALLING,
                           callback=_cambiar_idioma, bouncetime=400)

# ── Cargar modelo ─────────────────────────────────────────────────────────
def cargar_modelos():
    global modelo_whisper
    print("⏳ Cargando modelo de voz Whisper...")
    modelo_whisper = whisper.load_model("base")
    print("✓ Whisper listo")

# ── Síntesis de voz ───────────────────────────────────────────────────────
def hablar(texto):
    try:
        tts = gTTS(text=texto, lang='es', slow=False)
        mp3 = tempfile.NamedTemporaryFile(suffix='.mp3', delete=False)
        tts.save(mp3.name)
        pygame.mixer.init()
        pygame.mixer.music.load(mp3.name)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            time.sleep(0.05)
        pygame.mixer.quit()
        os.unlink(mp3.name)
    except Exception as e:
        print(f"Error audio: {e}")

# ── Traducción solo diccionario (igual que la versión original) ─────────
def traducir_inteligente(texto, direccion):
    encontradas = db.buscar_en_diccionario(texto, direccion)
    if encontradas:
        palabras = texto.split()
        resultado = []
        todas = True
        for p in palabras:
            p_limpia = p.strip(".,!?;:")
            if p_limpia in encontradas:
                resultado.append(encontradas[p_limpia])
            else:
                todas = False
                resultado.append(f"[{p_limpia}]")
        return " ".join(resultado), ("diccionario" if todas else "diccionario_parcial")
    return None, "no_encontrado"

# ── Procesar un segmento de audio ya capturado ──────────────────────────
def procesar_audio(audio_int16):
    global procesando
    procesando = True
    mostrar_oled("Transcribiendo...")
    try:
        tmp = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        sf.write(tmp.name, audio_int16, SAMPLE_RATE)

        lang = "es" if modo == "e2k" else None
        texto = modelo_whisper.transcribe(tmp.name, language=lang)["text"].strip()
        os.unlink(tmp.name)

        if not texto:
            print("⚠ No se entendió, intenta de nuevo")
            mostrar_oled("No entendí")
            time.sleep(1)
            return

        origen = "Kogui" if modo == "k2e" else "Español"
        destino = "Español" if modo == "k2e" else "Kogui"
        print(f"\n[{origen}] {texto}")

        mostrar_oled("Traduciendo...")
        traduccion, fuente = traducir_inteligente(texto, modo)

        if fuente == "no_encontrado":
            print(f"⚠ Palabra no encontrada en el diccionario ({destino})")
            mostrar_oled("No en diccionario")
            time.sleep(1)
            return

        print(f"[{destino}] {traduccion}  ({fuente})")
        db.guardar_conversacion(texto, traduccion, modo, fuente)

        mostrar_oled("Hablando...")
        hablar(traduccion)

    except Exception as e:
        print(f"✗ Error: {e}")
    finally:
        procesando = False
        mostrar_oled()

# ── Loop de escucha continua con VAD ─────────────────────────────────────
def escucha_continua():
    vad = webrtcvad.Vad(VAD_AGRESIVIDAD)
    mostrar_oled()
    print("🎤 Escucha continua activa — habla cuando quieras (Ctrl+C para salir)")

    buffer_audio = []
    en_habla = False
    silencio_contador = 0

    def callback(indata, frames, time_info, status):
        nonlocal buffer_audio, en_habla, silencio_contador

        if procesando:
            return  # no seguir capturando mientras se procesa lo anterior

        frame_bytes = indata.tobytes()
        try:
            es_habla = vad.is_speech(frame_bytes, SAMPLE_RATE)
        except Exception:
            es_habla = False

        if es_habla:
            buffer_audio.append(indata.copy())
            en_habla = True
            silencio_contador = 0
        elif en_habla:
            buffer_audio.append(indata.copy())
            silencio_contador += 1
            if silencio_contador > SILENCIO_MAX_FRAMES:
                audio_completo = np.concatenate(buffer_audio, axis=0)
                buffer_audio = []
                en_habla = False
                silencio_contador = 0
                threading.Thread(target=procesar_audio, args=(audio_completo,),
                                  daemon=True).start()

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype='int16',
                         blocksize=FRAME_SAMPLES, callback=callback):
        try:
            while True:
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\nSaliendo...")

# ── Main ──────────────────────────────────────────────────────────────────
def main():
    db.inicializar_db()
    configurar_boton()
    cargar_modelos()
    try:
        escucha_continua()
    finally:
        GPIO.cleanup()

if __name__ == "__main__":
    main()
