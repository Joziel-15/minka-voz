#!/usr/bin/env python3
"""
database.py — MINKA VOZ
Usa la base de datos compartida ~/minka/minka.db
Tablas: dictionary, conversations
"""

import sqlite3
import os
from datetime import datetime

# Base de datos compartida con el bot de Telegram
DB_PATH = os.path.expanduser("~/minka/minka.db")

def conectar():
    return sqlite3.connect(DB_PATH)

def inicializar_db():
    """Verifica que las tablas existen y tienen las columnas necesarias"""
    con = conectar()
    cur = con.cursor()

    # Crear dictionary si no existe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS dictionary (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            kogui     TEXT,
            spanish   TEXT,
            categoria TEXT DEFAULT 'general',
            notas     TEXT DEFAULT '',
            fecha     TEXT DEFAULT ''
        )
    """)

    # Crear conversations si no existe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS conversations (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            user            TEXT DEFAULT 'minka_voz',
            message         TEXT DEFAULT '',
            texto_traducido TEXT DEFAULT '',
            direccion       TEXT DEFAULT 'k2e',
            fuente          TEXT DEFAULT 'api',
            fecha           TEXT DEFAULT ''
        )
    """)

    con.commit()
    con.close()

# ── Palabras ────────────────────────────────────────────────────────────────────

def agregar_palabra(kogui, espanol, categoria="general", notas=""):
    con = conectar()
    cur = con.cursor()

    cur.execute("SELECT id FROM dictionary WHERE LOWER(kogui) = LOWER(?)", (kogui,))
    if cur.fetchone():
        con.close()
        return False, "ya existe"

    cur.execute("""
        INSERT INTO dictionary (kogui, spanish, categoria, notas, fecha)
        VALUES (?, ?, ?, ?, ?)
    """, (kogui.strip(), espanol.strip(), categoria.strip(), notas.strip(),
          datetime.now().strftime("%Y-%m-%d %H:%M")))

    con.commit()
    con.close()
    return True, "agregada"

def buscar_en_diccionario(texto, direccion="k2e"):
    con = conectar()
    cur = con.cursor()

    palabras = texto.strip().split()
    encontradas = {}

    for palabra in palabras:
        p = palabra.strip(".,!?;:")
        if direccion == "k2e":
            cur.execute("SELECT spanish FROM dictionary WHERE LOWER(kogui) = LOWER(?)", (p,))
        else:
            cur.execute("SELECT kogui FROM dictionary WHERE LOWER(spanish) = LOWER(?)", (p,))
        resultado = cur.fetchone()
        if resultado:
            encontradas[palabra] = resultado[0]

    con.close()
    return encontradas

def obtener_todas_palabras():
    con = conectar()
    cur = con.cursor()
    cur.execute("""
        SELECT id, kogui, spanish, categoria, notas, fecha
        FROM dictionary
        ORDER BY spanish ASC
    """)
    palabras = cur.fetchall()
    con.close()
    return palabras

def buscar_palabra(termino):
    con = conectar()
    cur = con.cursor()
    cur.execute("""
        SELECT id, kogui, spanish, categoria, notas, fecha
        FROM dictionary
        WHERE LOWER(kogui) LIKE LOWER(?)
           OR LOWER(spanish) LIKE LOWER(?)
        ORDER BY kogui
    """, (f"%{termino}%", f"%{termino}%"))
    palabras = cur.fetchall()
    con.close()
    return palabras

def eliminar_palabra(palabra_id):
    con = conectar()
    cur = con.cursor()
    cur.execute("DELETE FROM dictionary WHERE id = ?", (palabra_id,))
    eliminada = cur.rowcount > 0
    con.commit()
    con.close()
    return eliminada

# ── Historial ───────────────────────────────────────────────────────────────────

def guardar_conversacion(original, traducido, direccion, fuente="api"):
    con = conectar()
    cur = con.cursor()
    cur.execute("""
        INSERT INTO conversations (user, message, texto_traducido, direccion, fuente, fecha)
        VALUES (?, ?, ?, ?, ?, ?)
    """, ("minka_voz", original, traducido, direccion, fuente,
          datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    con.commit()
    con.close()

def obtener_historial(limite=20):
    con = conectar()
    cur = con.cursor()
    cur.execute("""
        SELECT id, message, texto_traducido, direccion, fuente, fecha
        FROM conversations
        WHERE user = 'minka_voz'
        ORDER BY fecha DESC
        LIMIT ?
    """, (limite,))
    historial = cur.fetchall()
    con.close()
    return historial

def buscar_historial(termino):
    con = conectar()
    cur = con.cursor()
    cur.execute("""
        SELECT id, message, texto_traducido, direccion, fuente, fecha
        FROM conversations
        WHERE user = 'minka_voz'
          AND (LOWER(message) LIKE LOWER(?)
           OR LOWER(texto_traducido) LIKE LOWER(?))
        ORDER BY fecha DESC
    """, (f"%{termino}%", f"%{termino}%"))
    resultados = cur.fetchall()
    con.close()
    return resultados

def estadisticas():
    con = conectar()
    cur = con.cursor()

    cur.execute("SELECT COUNT(*) FROM dictionary")
    total_palabras = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM conversations WHERE user = 'minka_voz'")
    total_conv = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM conversations WHERE user = 'minka_voz' AND direccion = 'k2e'")
    kogui_a_esp = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM conversations WHERE user = 'minka_voz' AND direccion = 'e2k'")
    esp_a_kogui = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM conversations WHERE user = 'minka_voz' AND fuente = 'diccionario'")
    desde_dic = cur.fetchone()[0]

    con.close()
    return {
        "palabras": total_palabras,
        "conversaciones": total_conv,
        "kogui_a_esp": kogui_a_esp,
        "esp_a_kogui": esp_a_kogui,
        "desde_diccionario": desde_dic
    }
