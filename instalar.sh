#!/bin/bash
# ============================================================================
# MINKA VOZ — Instalador para Raspberry Pi 4
# Micrófono I2S: INMP441 · Amplificador I2S: MAX98357A
# Uso:  bash instalar.sh
# ============================================================================
set -e

SUDO=""; [ "$(id -u)" -ne 0 ] && SUDO="sudo"
DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "🌿 MINKA VOZ — Port Raspberry Pi 4"
echo "   Micrófono INMP441 (I2S) + Altavoz MAX98357A (I2S)"
echo ""

# ── 1. Verificar arquitectura de 64 bits ────────────────────────────────────
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    echo "⚠ Tu sistema es $ARCH. faster-whisper necesita Raspberry Pi OS de 64 bits."
    echo "  El instalador continúa, pero el rendimiento será limitado."
    read -r -p "¿Continuar? [s/N] " RESP
    [ "$RESP" = "s" ] || exit 1
fi

# ── 2. Dependencias del sistema ─────────────────────────────────────────────
echo "📦 Instalando dependencias del sistema..."
$SUDO apt update -q
$SUDO apt install -y -q python3-venv python3-pip python3-dev build-essential \
    libportaudio2 espeak-ng alsa-utils git

# ── 3. Configurar overlays I2S en config.txt ────────────────────────────────
CFG="/boot/firmware/config.txt"
[ -f "$CFG" ] || CFG="/boot/config.txt"

echo "🔧 Configurando I2S en $CFG..."
config_add() {
    # Añade la línea solo si no existe ya
    grep -qsE "^\s*$1\s*$" "$CFG" || echo "$1" | $SUDO tee -a "$CFG" >/dev/null
}
config_add "dtparam=i2s=on"
config_add "dtoverlay=hifiberry-adc"   # INMP441  -> captura (GPIO18/19/20)
config_add "dtoverlay=hifiberry-dac"   # MAX98357A -> salida  (GPIO18/19/21)

# ── 4. Entorno virtual y librerías Python ───────────────────────────────────
if [ ! -d "$DIR/venv" ]; then
    echo "🐍 Creando entorno virtual..."
    python3 -m venv "$DIR/venv"
fi
source "$DIR/venv/bin/activate"
pip install --upgrade pip -q
echo "📚 Instalando librerías Python (esto tarda varios minutos)..."
pip install -r "$DIR/requirements.txt"

# ── 5. TTS offline opcional: Piper (voz española, ~64 MB) ───────────────────
echo ""
read -r -p "🗣 ¿Descargar voz offline Piper para español (~64 MB, recomendado)? [S/n] " RESP
if [ "${RESP,,}" != "n" ]; then
    pip install piper-tts -q || echo "⚠ No se pudo instalar piper-tts (se usará espeak-ng)"
    VOZ_DIR="$HOME/piper-voices"
    mkdir -p "$VOZ_DIR"
    BASE="https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/es/es/es_ES/mls_10246/low"
    if [ ! -f "$VOZ_DIR/es_ES-mls_10246-low.onnx" ]; then
        wget -q --show-progress -O "$VOZ_DIR/es_ES-mls_10246-low.onnx" \
            "$BASE/es_ES-mls_10246-low.onnx?download=true" \
            || echo "⚠ Descarga falló — espeak-ng se usará como TTS"
    fi
    if [ ! -f "$VOZ_DIR/es_ES-mls_10246-low.onnx.json" ]; then
        wget -q -O "$VOZ_DIR/es_ES-mls_10246-low.onnx.json" \
            "$BASE/es_ES-mls_10246-low.onnx.json?download=true" || true
    fi
fi

# ── 6. Dashboard Web (opcional) ─────────────────────────────────────────────
echo ""
read -r -p "🌐 ¿Instalar Dashboard Web (profesores/aprendices, puerto 5000)? [S/n] " RESP
if [ "${RESP,,}" != "n" ]; then
    pip install -r "$DIR/dashboard/requirements.txt"
    echo "✓ Dashboard instalado — accede en http://$(hostname -I | awk '{print $1}'):5000"
    echo "  Usuario: admin  |  Contrasena: admin  (cambiala despues)"
fi

# ── 7. Servicio systemd (arranque automático) ───────────────────────────────
echo ""
read -r -p "🚀 ¿Instalar arranque automático con systemd? [S/n] " RESP
if [ "${RESP,,}" != "n" ]; then
    UNIT=/etc/systemd/system/minka-voz.service
    $SUDO tee "$UNIT" >/dev/null <<EOF
[Unit]
Description=MINKA VOZ — Traductor Kogui<->Español (Raspberry Pi)
After=sound.target multi-user.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python $DIR/minka_voz.py
Restart=on-failure
RestartSec=5
Environment=MINKA_MODEL=base

[Install]
WantedBy=multi-user.target
EOF
    $SUDO systemctl daemon-reload
    $SUDO systemctl enable minka-voz.service
    echo "✓ Servicio instalado: sudo systemctl start|stop|status minka-voz"
fi

# ── 7. Permisos GPIO/I2C sin sudo ───────────────────────────────────────────
$SUDO usermod -aG gpio,i2c,audio "$USER" 2>/dev/null || true

echo ""
echo "✅ Instalación completa."
echo ""
echo "   Prueba los módulos tras reiniciar:"
echo "     arecord -l        # debe listar la tarjeta HiFiBerry ADC  (INMP441)"
echo "     aplay -l          # debe listar la tarjeta HiFiBerry DAC  (MAX98357A)"
echo ""
echo "   Traductor de voz:"
echo "     cd $DIR && source venv/bin/activate && python3 minka_voz.py"
echo ""
echo "   Dashboard web (si lo instalaste):"
echo "     cd $DIR/dashboard && source $DIR/venv/bin/activate && python3 app.py"
echo "     http://$(hostname -I 2>/dev/null | awk '{print $1}'):5000"
echo ""
echo "   ⚠ REINICIA la Raspberry Pi para aplicar los overlays I2S:"
echo "     sudo reboot"
echo ""
