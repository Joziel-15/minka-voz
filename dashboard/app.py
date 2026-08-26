#!/usr/bin/env python3
"""
app.py — Dashboard MINKA VOZ
Flask web app para profesores, aprendices y comunidad de la lengua Kogui.
Comparte la base de datos ~/minka/minka.db con el traductor de voz.
"""

import os
import database as db
from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify, session
)
from flask_login import (
    LoginManager, UserMixin, login_user,
    logout_user, login_required, current_user
)
from werkzeug.security import check_password_hash
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "minka-voz-dashboard-dev-key")

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Inicia sesión para continuar"


# ── User class for Flask-Login ─────────────────────────────────────────────
class User(UserMixin):
    def __init__(self, data):
        self.id = data["id"]
        self.username = data["username"]
        self.email = data["email"]
        self.role = data["role"]
        self.active = data["active"]

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def is_profesor(self):
        return self.role in ("admin", "profesor")


@login_manager.user_loader
def load_user(user_id):
    data = db.obtener_usuario_por_id(int(user_id))
    if data and data["active"]:
        return User(data)
    return None


# ── Role decorators ────────────────────────────────────────────────────────
def roles_required(*roles):
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            if current_user.role not in roles:
                flash("No tienes permiso para acceder a esta seccion", "danger")
                return redirect(url_for("dashboard"))
            return f(*args, **kwargs)
        return wrapped
    return decorator


# ── Init DB ────────────────────────────────────────────────────────────────
@app.before_request
def ensure_db():
    if not hasattr(app, "_db_initialized"):
        db.inicializar_db()
        app._db_initialized = True


# ════════════════════════════════════════════════════════════════════════════
#  AUTH
# ════════════════════════════════════════════════════════════════════════════
@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user_data = db.obtener_usuario(username)
        if user_data and check_password_hash(user_data["password_hash"], password):
            if not user_data["active"]:
                flash("Tu cuenta esta desactivada", "warning")
                return render_template("login.html")
            login_user(User(user_data), remember=True)
            flash(f"Bienvenido, {username}", "success")
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Usuario o contrasena incorrectos", "danger")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Sesion cerrada", "info")
    return redirect(url_for("login"))


@app.route("/cambiar-contrasena", methods=["GET", "POST"])
@login_required
def cambiar_contrasena():
    if request.method == "POST":
        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        user_data = db.obtener_usuario_por_id(current_user.id)
        if not check_password_hash(user_data["password_hash"], actual):
            flash("Contrasena actual incorrecta", "danger")
        elif len(nueva) < 4:
            flash("La nueva contrasena debe tener al menos 4 caracteres", "warning")
        else:
            db.cambiar_contrasena(current_user.id, nueva)
            flash("Contrasena actualizada", "success")
            return redirect(url_for("dashboard"))
    return render_template("cambiar_contrasena.html")


# ════════════════════════════════════════════════════════════════════════════
#  DASHBOARD HOME
# ════════════════════════════════════════════════════════════════════════════
@app.route("/")
@login_required
def dashboard():
    stats = db.estadisticas_generales()
    recientes, _ = db.buscar_historial(limite=10)
    return render_template("dashboard.html", stats=stats, recientes=recientes)


# ════════════════════════════════════════════════════════════════════════════
#  DICCIONARIO
# ════════════════════════════════════════════════════════════════════════════
@app.route("/dictionary")
@login_required
def diccionario():
    termino = request.args.get("q", "")
    categoria = request.args.get("cat", "")
    palabras = db.buscar_diccionario(termino, categoria)
    categorias = ["general", "saludo", "familia", "naturaleza", "animal",
                  "accion", "numero", "cuerpo"]
    return render_template("dictionary.html", palabras=palabras,
                           termino=termino, categoria=categoria,
                           categorias=categorias)


@app.route("/dictionary/add", methods=["POST"])
@login_required
@roles_required("admin", "profesor")
def agregar_palabra():
    ok, msg = db.agregar_palabra(
        request.form["kogui"], request.form["spanish"],
        request.form.get("categoria", "general"),
        request.form.get("notas", ""),
    )
    flash(f"Palabra agregada" if ok else msg, "success" if ok else "warning")
    return redirect(url_for("diccionario"))


@app.route("/dictionary/edit/<int:pid>", methods=["POST"])
@login_required
@roles_required("admin", "profesor")
def editar_palabra(pid):
    db.actualizar_palabra(
        pid, request.form["kogui"], request.form["spanish"],
        request.form.get("categoria", "general"),
        request.form.get("notas", ""),
    )
    flash("Palabra actualizada", "success")
    return redirect(url_for("diccionario"))


@app.route("/dictionary/delete/<int:pid>", methods=["POST"])
@login_required
@roles_required("admin")
def borrar_palabra(pid):
    db.eliminar_palabra(pid)
    flash("Palabra eliminada", "info")
    return redirect(url_for("diccionario"))


# ════════════════════════════════════════════════════════════════════════════
#  HISTORIAL
# ════════════════════════════════════════════════════════════════════════════
@app.route("/history")
@login_required
def historial():
    pagina = max(int(request.args.get("p", 1)), 1)
    por_pagina = 25
    historial, total = db.buscar_historial(
        termino=request.args.get("q", ""),
        direccion=request.args.get("dir", ""),
        fuente=request.args.get("src", ""),
        limite=por_pagina,
        offset=(pagina - 1) * por_pagina,
    )
    total_paginas = max(1, -(-total // por_pagina))
    return render_template("history.html", historial=historial,
                           total=total, pagina=pagina,
                           total_paginas=total_paginas)


@app.route("/history/delete/<int:cid>", methods=["POST"])
@login_required
@roles_required("admin")
def borrar_historial(cid):
    db.eliminar_conversacion(cid)
    flash("Registro eliminado", "info")
    return redirect(url_for("historial"))


# ════════════════════════════════════════════════════════════════════════════
#  ESTADISTICAS
# ════════════════════════════════════════════════════════════════════════════
@app.route("/stats")
@login_required
def estadisticas():
    general = db.estadisticas_generales()
    categorias = db.estadisticas_por_categoria()
    return render_template("stats.html", stats=general, categorias=categorias)


@app.route("/api/stats")
@login_required
def api_stats():
    return jsonify({
        "por_dia": db.estadisticas_por_dia(),
        "por_direccion": db.estadisticas_por_direccion(),
        "por_fuente": db.estadisticas_por_fuente(),
        "por_categoria": db.estadisticas_por_categoria(),
        "mas_traducidas": db.palabras_mas_traducidas(),
    })


# ════════════════════════════════════════════════════════════════════════════
#  GESTION DE USUARIOS (admin)
# ════════════════════════════════════════════════════════════════════════════
@app.route("/users")
@login_required
@roles_required("admin")
def usuarios():
    usuarios = db.listar_usuarios()
    return render_template("users.html", usuarios=usuarios)


@app.route("/users/add", methods=["POST"])
@login_required
@roles_required("admin")
def agregar_usuario():
    username = request.form.get("username", "").strip()
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    role = request.form.get("role", "alumno")
    if not username or not email or not password:
        flash("Todos los campos son obligatorios", "danger")
    elif len(password) < 4:
        flash("La contrasena debe tener al menos 4 caracteres", "warning")
    else:
        ok, msg = db.crear_usuario(username, email, password, role)
        flash("Usuario creado" if ok else msg, "success" if ok else "warning")
    return redirect(url_for("usuarios"))


@app.route("/users/edit/<int:uid>", methods=["POST"])
@login_required
@roles_required("admin")
def editar_usuario(uid):
    db.actualizar_usuario(uid, request.form["email"],
                         request.form["role"],
                         1 if request.form.get("active") else 0)
    flash("Usuario actualizado", "success")
    return redirect(url_for("usuarios"))


@app.route("/users/toggle/<int:uid>", methods=["POST"])
@login_required
@roles_required("admin")
def toggle_usuario(uid):
    u = db.obtener_usuario_por_id(uid)
    if u:
        db.actualizar_usuario(uid, u["email"], u["role"], 0 if u["active"] else 1)
        flash(f"Usuario {'activado' if not u['active'] else 'desactivado'}", "info")
    return redirect(url_for("usuarios"))


# ════════════════════════════════════════════════════════════════════════════
#  TEMA OSCURO
# ════════════════════════════════════════════════════════════════════════════
@app.route("/toggle-theme")
def toggle_theme():
    theme = request.args.get("theme", "light")
    session["theme"] = theme if theme in ("light", "dark") else "light"
    return ""


# ── Main ───────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    db.inicializar_db()
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    print(f"\n🌿 MINKA VOZ Dashboard — http://0.0.0.0:{port}")
    print("   Usuario por defecto: admin / admin  (cambialo despues)\n")
    app.run(host="0.0.0.0", port=port, debug=debug)
