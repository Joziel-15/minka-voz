#!/usr/bin/env python3
"""
database.py — MINKA VOZ (Raspberry Pi)
Usa la base de datos compartida ~/minka/minka.db (configurable con $MINKA_DB).
Tablas: dictionary, conversations
Incluye búsqueda por frases (longest-match) e inyección del diccionario base.
"""

import sqlite3
import os
from datetime import datetime

# Base de datos compartida con el bot de Telegram (o ruta personalizada)
DB_PATH = os.environ.get("MINKA_DB", os.path.expanduser("~/minka/minka.db"))

def conectar():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
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

    # Si el diccionario tiene pocas palabras, inyectar las base
    cur.execute("SELECT COUNT(*) FROM dictionary")
    total = cur.fetchone()[0]
    if total < 50:
        _inyectar_palabras_base(cur, total)
        con.commit()

    con.close()

def _inyectar_palabras_base(cur, total_existente):
    """Inyecta diccionario base Kogui-Espanol (solo palabras que no existan)"""
    palabras = [
        # Saludos
        ("mari", "hola", "saludo", "Saludo comun"),
        ("akua", "gracias", "saludo", "Agradecimiento"),
        ("mari akua", "buenos dias", "saludo", ""),
        ("mari sey", "buenas tardes", "saludo", "Literal: hola sol"),
        ("namu", "adios", "saludo", ""),
        ("akua tayra", "de nada", "saludo", ""),
        ("neisa", "bienvenido", "saludo", ""),

        # Familia
        ("mama", "madre", "familia", ""),
        ("tata", "padre", "familia", ""),
        ("yama", "hermano", "familia", ""),
        ("yaku", "hermana", "familia", ""),
        ("gunmu", "hijo", "familia", ""),
        ("nunu", "hija", "familia", ""),
        ("senenu", "abuelo", "familia", ""),
        ("nunulu", "abuela", "familia", ""),
        ("mauna", "tio", "familia", ""),
        ("naula", "tia", "familia", ""),
        ("kenu", "esposo", "familia", ""),
        ("kenua", "esposa", "familia", ""),
        ("guamnu", "familia", "familia", ""),
        ("guamunu", "nino", "familia", ""),
        ("guamu", "mayor / anciano", "familia", ""),

        # Naturaleza
        ("sey", "sol", "naturaleza", ""),
        ("kunka", "luna", "naturaleza", ""),
        ("guni", "estrella", "naturaleza", ""),
        ("gwa", "agua", "naturaleza", ""),
        ("tayra", "tierra", "naturaleza", "Tambien: territorio"),
        ("uri", "fuego", "naturaleza", ""),
        ("sianku", "viento", "naturaleza", ""),
        ("kan", "rio", "naturaleza", ""),
        ("sia", "lluvia", "naturaleza", ""),
        ("kasku", "montaña", "naturaleza", ""),
        ("kuamu", "bosque", "naturaleza", ""),
        ("kamuku", "selva", "naturaleza", ""),
        ("sierra", "sierra nevada", "naturaleza", ""),
        ("dugumu", "rio grande", "naturaleza", ""),
        ("nabusikua", "bahia sin fin", "naturaleza", ""),
        ("tukunu", "laguna", "naturaleza", ""),

        # Animales
        ("duga", "perro", "animal", ""),
        ("kumina", "tortuga", "animal", ""),
        ("tuli", "pez", "animal", ""),
        ("kuamu", "jaguar", "animal", "Tambien: felino grande"),
        ("gawa", "pajaro", "animal", ""),
        ("kuse", "mono", "animal", ""),
        ("sugu", "serpiente", "animal", ""),
        ("tikuku", "rana", "animal", ""),
        ("nusku", "cangrejo", "animal", ""),
        ("uwa", "venado", "animal", ""),
        ("kakua", "cocodrilo", "animal", ""),
        ("nui", "lapa", "animal", ""),

        # Cuerpo
        ("kui", "cabeza", "cuerpo", ""),
        ("tui", "ojo", "cuerpo", ""),
        ("nuaka", "boca", "cuerpo", ""),
        ("tuku", "mano", "cuerpo", ""),
        ("guta", "pie", "cuerpo", ""),
        ("siwa", "pecho", "cuerpo", ""),
        ("duga", "pierna", "cuerpo", ""),

        # Acciones
        ("kunu", "comer", "accion", ""),
        ("wina", "beber", "accion", ""),
        ("kua", "ir", "accion", ""),
        ("dama", "hablar", "accion", ""),
        ("nua", "ver", "accion", ""),
        ("kama", "trabajar", "accion", ""),
        ("sama", "dormir", "accion", ""),
        ("bua", "caminar", "accion", ""),
        ("gana", "cantar", "accion", ""),
        ("tama", "bailar", "accion", ""),
        ("kuka", "sembrar", "accion", ""),
        ("nuaka", "cocinar", "accion", ""),
        ("kaku", "pescar", "accion", ""),
        ("siwa", "curar", "accion", ""),
        ("gwa", "cargar", "accion", ""),

        # Numeros
        ("musi", "uno", "numero", ""),
        ("maka", "dos", "numero", ""),
        ("tsaipku", "tres", "numero", ""),
        ("tsaink", "cuatro", "numero", ""),
        ("tsaimu", "cinco", "numero", ""),
        ("saiqa", "seis", "numero", ""),
        ("tukusaiqa", "siete", "numero", ""),
        ("musikusa", "diez", "numero", ""),

        # General
        ("bunsi", "bueno", "general", ""),
        ("bunsiaku", "muy bueno", "general", ""),
        ("karu", "grande", "general", ""),
        ("uri", "pequeno", "general", ""),
        ("nusu", "yo", "general", ""),
        ("maku", "tu", "general", ""),
        ("gunu", "el / ella", "general", ""),
        ("namu", "nosotros", "general", ""),
        ("makui", "ustedes", "general", ""),
        ("gunu", "ellos", "general", ""),
        ("sia", "si", "general", ""),
        ("nia", "no", "general", ""),
        ("neisa", "verdad", "general", ""),
        ("kama", "asi es", "general", ""),
        ("teku", "lugar", "general", ""),
        ("guamu", "tiempo", "general", ""),
        ("sia", "ver", "general", "Tambien: si"),
        ("tukui", "mujer", "general", ""),
        ("tuku", "hombre", "general", ""),
        ("daku", "palabra", "general", ""),
        ("kunsamuna", "pensamiento", "general", ""),
        ("gunuku", "camino", "general", ""),
        ("tukunu", "escuela", "general", ""),
        ("kanuku", "gobierno", "general", ""),
    ]
    cur.executemany(
        "INSERT OR IGNORE INTO dictionary (kogui, spanish, categoria, notas, fecha) VALUES (?, ?, ?, ?, '')",
        [(k, e, c, n) for k, e, c, n in palabras]
    )

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
        if not p:
            continue
        if direccion == "k2e":
            cur.execute("SELECT spanish FROM dictionary WHERE LOWER(kogui) = LOWER(?)", (p,))
        else:
            cur.execute("SELECT kogui FROM dictionary WHERE LOWER(spanish) = LOWER(?)", (p,))
        resultado = cur.fetchone()
        if resultado:
            encontradas[p] = resultado[0]

    con.close()
    return encontradas


def buscar_frase_en_diccionario(texto, direccion="k2e"):
    """Busca frases completas en el diccionario. Intenta desde la frase completa
    hacia abajo (longest match first)."""
    con = conectar()
    cur = con.cursor()
    texto_limpio = texto.strip().lower().strip(".,!?;:")
    palabras = texto_limpio.split()
    resultado = []
    i = 0

    while i < len(palabras):
        encontrado = False
        # Intentar frases de mayor a menor longitud
        for longitud in range(min(5, len(palabras) - i), 0, -1):
            frase = " ".join(palabras[i:i+longitud])
            if direccion == "k2e":
                cur.execute("SELECT spanish FROM dictionary WHERE LOWER(kogui) = LOWER(?)", (frase,))
            else:
                cur.execute("SELECT kogui FROM dictionary WHERE LOWER(spanish) = LOWER(?)", (frase,))
            res = cur.fetchone()
            if res:
                resultado.append({"frase": frase, "traduccion": res[0], "longitud": longitud})
                i += longitud
                encontrado = True
                break
        if not encontrado:
            # Palabra no encontrada, agregar como [no encontrada]
            resultado.append({"frase": palabras[i], "traduccion": f"[{palabras[i]}]", "longitud": 1})
            i += 1

    con.close()
    return resultado

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

def actualizar_palabra(palabra_id, kogui, espanol, categoria, notas):
    con = conectar()
    cur = con.cursor()
    # Verificar duplicado (excluyendo el mismo ID)
    cur.execute("SELECT id FROM dictionary WHERE LOWER(kogui) = LOWER(?) AND id != ?", (kogui, palabra_id))
    if cur.fetchone():
        con.close()
        return False, "ya existe"
    cur.execute("""
        UPDATE dictionary SET kogui=?, spanish=?, categoria=?, notas=?
        WHERE id=?
    """, (kogui.strip(), espanol.strip(), categoria.strip(), notas.strip(), palabra_id))
    con.commit()
    actualizada = cur.rowcount > 0
    con.close()
    return actualizada, "actualizada"

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
