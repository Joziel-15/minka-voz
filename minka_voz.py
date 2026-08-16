#!/usr/bin/env python3
"""
MINKA VOZ — Traductor de voz Kogui <-> Español
Con diccionario propio, historial y push-to-talk con ESPACIO
Usa Google Gemini para traducción (gratis)
"""

import os
import sys
import time
import tempfile
import threading
import numpy as np
import sounddevice as sd
import soundfile as sf
import whisper
from gtts import gTTS
import pygame
from pynput import keyboard
import database as db

# ── Configuración ───────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000

KOGUI_CONTEXTO = """
Eres un traductor especializado en la lengua Kogui (Kággaba),
lengua indígena de la Sierra Nevada de Santa Marta, Colombia.
Responde ÚNICAMENTE con la traducción, sin explicaciones.
Si no conoces una palabra exacta, usa la más cercana e indícalo entre paréntesis.
Lengua SOV, sin género gramatical.
"""

# ── Colores ─────────────────────────────────────────────────────────────────────
R  = "\033[0m"
G  = "\033[92m"
B  = "\033[94m"
Y  = "\033[93m"
RD = "\033[91m"
GR = "\033[90m"
CY = "\033[96m"
BO = "\033[1m"
MG = "\033[95m"

# ── Estado global ────────────────────────────────────────────────────────────────
grabando       = False
audio_chunks   = []
modo           = "k2e"
procesando     = False
espacio_activo = False
modelo_whisper = None

# ── UI ───────────────────────────────────────────────────────────────────────────
def cls():
    os.system('clear')

def banner():
    cls()
    print(f"""
{G}{BO}  ╔══════════════════════════════════════════╗
  ║   🌿  M I N K A  V O Z  🌿            ║
  ║   Traductor  Kogui ↔ Español           ║
  ╚══════════════════════════════════════════╝{R}
""")

def linea(t=""):
    print(f"  {t}")

def separador():
    linea(f"{GR}──────────────────────────────────────────{R}")

def esperar_enter():
    input(f"\n  {GR}Presiona ENTER para continuar...{R}")

# ── Cargar modelos ────────────────────────────────────────────────────────────────
def cargar_modelos():
    global modelo_whisper
    linea(f"{Y}⏳ Cargando modelo de voz Whisper...{R}")
    modelo_whisper = whisper.load_model("base")
    linea(f"{G}✓ Whisper listo{R}")

# ── Grabación ────────────────────────────────────────────────────────────────────
def _hilo_grabacion():
    global audio_chunks
    audio_chunks = []

    def callback(indata, frames, time_info, status):
        if grabando:
            audio_chunks.append(indata.copy())

    with sd.InputStream(samplerate=SAMPLE_RATE, channels=1,
                        dtype='float32', callback=callback):
        while grabando:
            time.sleep(0.02)

hilo_grab = None

def iniciar_grabacion():
    global grabando, hilo_grab, audio_chunks
    if grabando:
        return
    grabando = True
    audio_chunks = []
    hilo_grab = threading.Thread(target=_hilo_grabacion, daemon=True)
    hilo_grab.start()
    print(f"\r  {RD}● GRABANDO...{R}  suelta ESPACIO para traducir        ",
          end="", flush=True)

def detener_grabacion():
    global grabando, hilo_grab
    if not grabando:
        return
    grabando = False
    if hilo_grab:
        hilo_grab.join(timeout=1)

# ── Síntesis de voz ──────────────────────────────────────────────────────────────
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
        linea(f"{RD}Error audio: {e}{R}")

# ── Traducción solo diccionario ───────────────────────────────────────────────────
def traducir_inteligente(texto, direccion):
    """Solo usa el diccionario. Si no encuentra, avisa."""
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

        if todas:
            return " ".join(resultado), "diccionario"
        else:
            return " ".join(resultado), "diccionario_parcial"

    return None, "no_encontrado"

# ── Procesar audio ────────────────────────────────────────────────────────────────
def procesar():
    global procesando
    if procesando:
        return
    procesando = True

    try:
        if not audio_chunks:
            print(f"\r  {Y}⚠ No se grabó audio{R}                          ")
            return

        audio = np.concatenate(audio_chunks, axis=0)
        tmp   = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
        sf.write(tmp.name, audio, SAMPLE_RATE)

        print(f"\r  {B}📝 Transcribiendo...{R}                              ",
              end="", flush=True)
        lang  = "es" if modo == "e2k" else None
        texto = modelo_whisper.transcribe(tmp.name, language=lang)["text"].strip()
        os.unlink(tmp.name)

        if not texto:
            print(f"\r  {Y}⚠ No se entendió, intenta de nuevo{R}           ")
            return

        origen  = "Kogui"   if modo == "k2e" else "Español"
        destino = "Español" if modo == "k2e" else "Kogui"

        print(f"\r                                                    ")
        print()
        linea(f"{GR}┌─ {origen}{R}")
        linea(f"{GR}│{R}  {texto}")
        linea(f"{GR}│{R}")

        print(f"  {B}🌐 Traduciendo...{R}", flush=True)
        traduccion, fuente = traducir_inteligente(texto, modo)

        if fuente == "no_encontrado":
            linea(f"{GR}└─ {destino}{R}")
            linea(f"{Y}   ⚠ Palabra no encontrada en el diccionario{R}")
            linea(f"{GR}   Agrégala en [2] Diccionario{R}")
            print()
            return

        fuente_label = f"{G}[diccionario]{R}" if fuente == "diccionario" \
                  else f"{Y}[diccionario parcial]{R}"

        linea(f"{GR}└─ {destino} {fuente_label}{R}")
        linea(f"{G}{BO}   {traduccion}{R}")
        print()

        db.guardar_conversacion(texto, traduccion, modo, fuente)

        linea(f"{B}🔊 Reproduciendo...{R}")
        hablar(traduccion)
        print()
        linea(f"{G}✓ Listo — mantén {BO}ESPACIO{R}{G} para grabar de nuevo{R}")
        print()

    except Exception as e:
        print()
        linea(f"{RD}✗ Error: {e}{R}")
        print()
    finally:
        procesando = False

# ── Pantalla traducir ─────────────────────────────────────────────────────────────
def pantalla_traducir():
    global modo, espacio_activo

    def mostrar():
        banner()
        etiqueta = f"Kogui {BO}→{R} Español" if modo == "k2e" else f"Español {BO}→{R} Kogui"
        linea(f"{CY}Modo:{R}  {etiqueta}")
        print()
        separador()
        print()
        linea(f"  {BO}[ESPACIO]{R}  Mantén presionado para grabar")
        linea(f"  {BO}[M]{R}        Cambiar idioma")
        linea(f"  {BO}[B]{R}        Volver al menú")
        print()
        separador()
        print()
        linea(f"{G}● Listo — esperando...{R}")
        print()

    mostrar()
    en_pantalla = True

    def on_press(key):
        global espacio_activo
        if key == keyboard.Key.space and not espacio_activo and not procesando:
            espacio_activo = True
            iniciar_grabacion()

    def on_release(key):
        global espacio_activo, modo, en_pantalla
        if key == keyboard.Key.space and espacio_activo:
            espacio_activo = False
            detener_grabacion()
            threading.Thread(target=procesar, daemon=True).start()
        if hasattr(key, 'char'):
            if key.char == 'm' and not grabando and not procesando:
                modo = "e2k" if modo == "k2e" else "k2e"
                mostrar()
            if key.char == 'b':
                en_pantalla = False
                return False

    listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    listener.start()
    while en_pantalla:
        time.sleep(0.1)
    listener.stop()

# ── Diccionario ───────────────────────────────────────────────────────────────────
def pantalla_diccionario():
    while True:
        banner()
        linea(f"{MG}{BO}📖 Diccionario Kogui{R}")
        print()
        linea(f"  {BO}[1]{R}  Ver todas las palabras")
        linea(f"  {BO}[2]{R}  Buscar palabra")
        linea(f"  {BO}[3]{R}  Agregar palabra nueva")
        linea(f"  {BO}[4]{R}  Eliminar palabra")
        linea(f"  {BO}[B]{R}  Volver")
        print()
        op = input("  › ").strip().lower()
        if op == 'b':
            break
        elif op == '1':
            _ver_palabras()
        elif op == '2':
            _buscar_palabra()
        elif op == '3':
            _agregar_palabra()
        elif op == '4':
            _eliminar_palabra()

def _ver_palabras():
    banner()
    linea(f"{MG}{BO}📖 Palabras registradas{R}")
    print()
    palabras = db.obtener_todas_palabras()
    if not palabras:
        linea(f"{Y}Diccionario vacío — usa [3] para agregar palabras{R}")
    else:
        cat_actual = None
        for pid, kogui, espanol, categoria, notas, fecha in palabras:
            if categoria != cat_actual:
                cat_actual = categoria
                print()
                linea(f"{CY}{BO}▸ {categoria.upper()}{R}")
            nota = f"  {GR}({notas}){R}" if notas else ""
            linea(f"   {G}{BO}{espanol:<22}{R} →  {kogui}{nota}  {GR}#{pid}{R}")
        print()
        linea(f"{GR}Total: {len(palabras)} palabras{R}")
    esperar_enter()

def _buscar_palabra():
    banner()
    linea(f"{MG}{BO}🔍 Buscar{R}")
    print()
    termino = input("  Kogui o Español: ").strip()
    if not termino:
        return
    resultados = db.buscar_palabra(termino)
    print()
    if not resultados:
        linea(f"{Y}No se encontró '{termino}'{R}")
    else:
        for pid, kogui, espanol, categoria, notas, fecha in resultados:
            linea(f"  {G}{BO}{espanol:<22}{R} →  {kogui}  {GR}[{categoria}] #{pid}{R}")
            if notas:
                linea(f"     {GR}Nota: {notas}{R}")
    esperar_enter()

def _agregar_palabra():
    banner()
    linea(f"{MG}{BO}➕ Agregar palabra{R}")
    print()
    kogui = input("  Palabra en Kogui:    ").strip()
    if not kogui:
        return
    espanol = input("  Traducción Español:  ").strip()
    if not espanol:
        return
    print()
    linea(f"{GR}Categorías: saludo, familia, naturaleza, animal, accion, numero, general{R}")
    categoria = input("  Categoría [general]: ").strip() or "general"
    notas     = input("  Notas (opcional):    ").strip()
    print()
    linea(f"  {CY}Kogui:{R}     {kogui}")
    linea(f"  {CY}Español:{R}   {espanol}")
    linea(f"  {CY}Categoría:{R} {categoria}")
    print()
    if input(f"  {Y}¿Agregar? [s/n]: {R}").strip().lower() == 's':
        ok, msg = db.agregar_palabra(kogui, espanol, categoria, notas)
        linea(f"\n  {G}✓ Agregada{R}" if ok else f"\n  {Y}⚠ La palabra '{kogui}' {msg}{R}")
    else:
        linea(f"\n  {GR}Cancelado{R}")
    esperar_enter()

def _eliminar_palabra():
    banner()
    linea(f"{MG}{BO}🗑 Eliminar palabra{R}")
    print()
    termino = input("  Buscar palabra a eliminar: ").strip()
    if not termino:
        return
    resultados = db.buscar_palabra(termino)
    print()
    if not resultados:
        linea(f"{Y}No se encontró '{termino}'{R}")
        esperar_enter()
        return
    for pid, kogui, espanol, categoria, notas, fecha in resultados:
        linea(f"  {G}#{pid}{R}  {BO}{espanol:<22}{R} →  {kogui}  {GR}[{categoria}]{R}")
    print()
    try:
        pid_del = int(input("  ID a eliminar (0 cancelar): ").strip())
        if pid_del == 0:
            return
        if input(f"  {RD}¿Eliminar #{pid_del}? [s/n]: {R}").strip().lower() == 's':
            ok = db.eliminar_palabra(pid_del)
            linea(f"\n  {G}✓ Eliminada{R}" if ok else f"\n  {Y}⚠ ID no encontrado{R}")
    except ValueError:
        linea(f"  {RD}ID inválido{R}")
    esperar_enter()

# ── Historial ─────────────────────────────────────────────────────────────────────
def pantalla_historial():
    while True:
        banner()
        linea(f"{B}{BO}📜 Historial{R}")
        print()
        linea(f"  {BO}[1]{R}  Ver últimas 20 traducciones")
        linea(f"  {BO}[2]{R}  Buscar en historial")
        linea(f"  {BO}[B]{R}  Volver")
        print()
        op = input("  › ").strip().lower()
        if op == 'b':
            break
        elif op == '1':
            _ver_historial()
        elif op == '2':
            _buscar_historial()

def _ver_historial():
    banner()
    linea(f"{B}{BO}📜 Últimas traducciones{R}")
    print()
    historial = db.obtener_historial(20)
    if not historial:
        linea(f"{Y}No hay conversaciones aún{R}")
    else:
        for hid, original, traducido, direccion, fuente, fecha in historial:
            flecha = "Kogui→Esp" if direccion == "k2e" else "Esp→Kogui"
            fc = G if fuente == "diccionario" else CY
            print()
            linea(f"{GR}{fecha}  [{flecha}]  {fc}[{fuente}]{R}")
            linea(f"  {GR}›{R} {original}")
            linea(f"  {G}›{R} {traducido}")
        print()
        linea(f"{GR}Total: {len(historial)}{R}")
    esperar_enter()

def _buscar_historial():
    banner()
    linea(f"{B}{BO}🔍 Buscar en historial{R}")
    print()
    termino = input("  Buscar: ").strip()
    if not termino:
        return
    resultados = db.buscar_historial(termino)
    print()
    if not resultados:
        linea(f"{Y}No se encontró '{termino}'{R}")
    else:
        for hid, original, traducido, direccion, fuente, fecha in resultados:
            flecha = "Kogui→Esp" if direccion == "k2e" else "Esp→Kogui"
            print()
            linea(f"{GR}{fecha}  [{flecha}]{R}")
            linea(f"  {GR}›{R} {original}")
            linea(f"  {G}›{R} {traducido}")
        linea(f"\n{GR}Encontradas: {len(resultados)}{R}")
    esperar_enter()

# ── Estadísticas ──────────────────────────────────────────────────────────────────
def pantalla_estadisticas():
    banner()
    linea(f"{CY}{BO}📊 Estadísticas{R}")
    print()
    s = db.estadisticas()
    linea(f"  {BO}Diccionario{R}")
    linea(f"  {G}●{R} Palabras Kogui:           {BO}{s['palabras']}{R}")
    print()
    linea(f"  {BO}Traducciones{R}")
    linea(f"  {G}●{R} Total:                    {BO}{s['conversaciones']}{R}")
    linea(f"  {G}●{R} Kogui → Español:          {BO}{s['kogui_a_esp']}{R}")
    linea(f"  {G}●{R} Español → Kogui:          {BO}{s['esp_a_kogui']}{R}")
    linea(f"  {G}●{R} Desde diccionario propio: {BO}{s['desde_diccionario']}{R}")
    if s['conversaciones'] > 0:
        pct = round(s['desde_diccionario'] / s['conversaciones'] * 100)
        print()
        linea(f"  {GR}El {pct}% de traducciones usaron el diccionario propio{R}")
    esperar_enter()

# ── Menú principal ────────────────────────────────────────────────────────────────
def menu_principal():
    while True:
        banner()
        s = db.estadisticas()
        linea(f"{GR}Palabras: {s['palabras']}  |  Traducciones: {s['conversaciones']}{R}")
        print()
        separador()
        print()
        linea(f"  {BO}[1]{R}  🎤  Traducir")
        linea(f"  {BO}[2]{R}  📖  Diccionario Kogui")
        linea(f"  {BO}[3]{R}  📜  Historial")
        linea(f"  {BO}[4]{R}  📊  Estadísticas")
        linea(f"  {BO}[Q]{R}  Salir")
        print()
        separador()
        print()

        op = input("  › ").strip().lower()
        if op == 'q':
            banner()
            linea(f"{G}Hasta pronto 🌿{R}\n")
            break
        elif op == '1':
            pantalla_traducir()
        elif op == '2':
            pantalla_diccionario()
        elif op == '3':
            pantalla_historial()
        elif op == '4':
            pantalla_estadisticas()

# ── Main ──────────────────────────────────────────────────────────────────────────
def main():
    db.inicializar_db()
    banner()
    cargar_modelos()
    time.sleep(1)
    menu_principal()

if __name__ == "__main__":
    main()
