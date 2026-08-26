#!/usr/bin/env python3
"""
database.py — Capa de datos del Dashboard MINKA VOZ
Usa la misma BD compartida ~/minka/minka.db que el traductor de voz.
Añade tabla 'users' para autenticación del dashboard.
"""

import sqlite3
import os
from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.environ.get("MINKA_DB", os.path.expanduser("~/minka/minka.db"))


def conectar():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def inicializar_db():
    con = conectar()
    cur = con.cursor()

    # ── Tablas compartidas (mismas que el traductor de voz) ─────────────
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

    # ── Tablas del dashboard ────────────────────────────────────────────
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            username      TEXT UNIQUE NOT NULL,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            role          TEXT DEFAULT 'alumno',
            active        INTEGER DEFAULT 1,
            created_at    TEXT DEFAULT ''
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS student_progress (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id      INTEGER,
            word_id         INTEGER,
            known           INTEGER DEFAULT 0,
            last_practiced  TEXT DEFAULT '',
            FOREIGN KEY (student_id) REFERENCES users(id),
            FOREIGN KEY (word_id)    REFERENCES dictionary(id)
        )
    """)

    con.commit()

    # Admin por defecto si no existe ninguno
    cur.execute("SELECT COUNT(*) FROM users WHERE role='admin'")
    if cur.fetchone()[0] == 0:
        cur.execute(
            "INSERT INTO users (username, email, password_hash, role, active, created_at) "
            "VALUES (?, ?, ?, 'admin', 1, ?)",
            ("admin", "admin@minkavoz.local",
             generate_password_hash("admin"),
             datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        con.commit()

    con.close()


# ── Usuarios ──────────────────────────────────────────────────────────────
def crear_usuario(username, email, password, role="alumno"):
    con = conectar()
    try:
        con.execute(
            "INSERT INTO users (username, email, password_hash, role, active, created_at) "
            "VALUES (?, ?, ?, ?, 1, ?)",
            (username.strip(), email.strip().lower(),
             generate_password_hash(password), role,
             datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        con.commit()
        return True, "creado"
    except sqlite3.IntegrityError as e:
        msg = "ya existe el usuario" if "username" in str(e) else "ya existe el email"
        return False, msg
    finally:
        con.close()


def obtener_usuario(username):
    con = conectar()
    row = con.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    con.close()
    return dict(row) if row else None


def obtener_usuario_por_id(uid):
    con = conectar()
    row = con.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    con.close()
    return dict(row) if row else None


def listar_usuarios():
    con = conectar()
    rows = con.execute("SELECT id,username,email,role,active,created_at FROM users ORDER BY username").fetchall()
    con.close()
    return [dict(r) for r in rows]


def actualizar_usuario(uid, email, role, active):
    con = conectar()
    con.execute("UPDATE users SET email=?, role=?, active=? WHERE id=?",
                (email.strip().lower(), role, active, uid))
    con.commit()
    con.close()


def cambiar_contrasena(uid, nueva_password):
    con = conectar()
    con.execute("UPDATE users SET password_hash=? WHERE id=?",
                (generate_password_hash(nueva_password), uid))
    con.commit()
    con.close()


def eliminar_usuario(uid):
    con = conectar()
    con.execute("DELETE FROM users WHERE id=? AND role != 'admin'", (uid,))
    con.commit()
    con.close()


# ── Diccionario (CRUD) ────────────────────────────────────────────────────
def buscar_diccionario(termino="", categoria=""):
    con = conectar()
    sql = "SELECT * FROM dictionary WHERE 1=1"
    params = []
    if termino:
        sql += " AND (LOWER(kogui) LIKE ? OR LOWER(spanish) LIKE ?)"
        params += [f"%{termino.lower()}%", f"%{termino.lower()}%"]
    if categoria:
        sql += " AND categoria = ?"
        params.append(categoria)
    sql += " ORDER BY spanish ASC"
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows]


def obtener_palabra(pid):
    con = conectar()
    row = con.execute("SELECT * FROM dictionary WHERE id=?", (pid,)).fetchone()
    con.close()
    return dict(row) if row else None


def agregar_palabra(kogui, spanish, categoria="general", notas=""):
    con = conectar()
    try:
        con.execute(
            "INSERT INTO dictionary (kogui,spanish,categoria,notas,fecha) VALUES (?,?,?,?,?)",
            (kogui.strip(), spanish.strip(), categoria.strip(), notas.strip(),
             datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        con.commit()
        return True, "agregada"
    except sqlite3.IntegrityError:
        return False, "ya existe"


def actualizar_palabra(pid, kogui, spanish, categoria, notas):
    con = conectar()
    con.execute(
        "UPDATE dictionary SET kogui=?,spanish=?,categoria=?,notas=? WHERE id=?",
        (kogui.strip(), spanish.strip(), categoria.strip(), notas.strip(), pid)
    )
    con.commit()
    con.close()
    return True, "actualizada"


def eliminar_palabra(pid):
    con = conectar()
    con.execute("DELETE FROM dictionary WHERE id=?", (pid,))
    con.commit()
    con.close()


# ── Historial ─────────────────────────────────────────────────────────────
def buscar_historial(termino="", direccion="", fuente="", limite=100, offset=0):
    con = conectar()
    sql = "SELECT * FROM conversations WHERE 1=1"
    params = []
    if termino:
        sql += " AND (LOWER(message) LIKE ? OR LOWER(texto_traducido) LIKE ?)"
        params += [f"%{termino.lower()}%", f"%{termino.lower()}%"]
    if direccion:
        sql += " AND direccion = ?"
        params.append(direccion)
    if fuente:
        sql += " AND fuente = ?"
        params.append(fuente)
    count_sql = sql.replace("SELECT *", "SELECT COUNT(*)")
    total = con.execute(count_sql, params).fetchone()[0]
    sql += " ORDER BY fecha DESC LIMIT ? OFFSET ?"
    params += [limite, offset]
    rows = con.execute(sql, params).fetchall()
    con.close()
    return [dict(r) for r in rows], total


def eliminar_conversacion(cid):
    con = conectar()
    con.execute("DELETE FROM conversations WHERE id=?", (cid,))
    con.commit()
    con.close()


# ── Estadísticas ──────────────────────────────────────────────────────────
def estadisticas_generales():
    con = conectar()
    r = {}
    r["total_palabras"] = con.execute("SELECT COUNT(*) FROM dictionary").fetchone()[0]
    r["total_conversaciones"] = con.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
    r["hoy"] = con.execute(
        "SELECT COUNT(*) FROM conversations WHERE fecha LIKE ?",
        (datetime.now().strftime("%Y-%m-%d") + "%",)
    ).fetchone()[0]
    r["semana"] = con.execute(
        "SELECT COUNT(*) FROM conversations WHERE fecha >= ?",
        ((datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d"),)
    ).fetchone()[0]
    con.close()
    return r


def estadisticas_por_dia(dias=30):
    con = conectar()
    desde = (datetime.now() - timedelta(days=dias)).strftime("%Y-%m-%d")
    rows = con.execute(
        "SELECT substr(fecha,1,10) as dia, COUNT(*) as total "
        "FROM conversations WHERE fecha >= ? GROUP BY dia ORDER BY dia", (desde,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def estadisticas_por_direccion():
    con = conectar()
    rows = con.execute(
        "SELECT direccion, COUNT(*) as total FROM conversations GROUP BY direccion"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def estadisticas_por_fuente():
    con = conectar()
    rows = con.execute(
        "SELECT fuente, COUNT(*) as total FROM conversations GROUP BY fuente"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def estadisticas_por_categoria():
    con = conectar()
    rows = con.execute(
        "SELECT categoria, COUNT(*) as total FROM dictionary GROUP BY categoria ORDER BY total DESC"
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]


def palabras_mas_traducidas(limite=10):
    con = conectar()
    rows = con.execute(
        "SELECT message, COUNT(*) as total FROM conversations "
        "GROUP BY LOWER(message) ORDER BY total DESC LIMIT ?", (limite,)
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
