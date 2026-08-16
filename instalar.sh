#!/bin/bash
echo ""
echo "🌿 Instalando MINKA VOZ..."
echo ""
sudo apt update -q
sudo apt install -y portaudio19-dev ffmpeg python3-pip python3-venv
echo ""
echo "🐍 Creando entorno virtual..."
python3 -m venv venv
source venv/bin/activate
echo ""
echo "📚 Instalando librerías..."
pip install --upgrade pip -q
pip install openai-whisper sounddevice soundfile anthropic gTTS pygame numpy pynput
echo ""
echo "✅ Listo. Ahora ejecuta:"
echo "   source venv/bin/activate"
echo "   export ANTHROPIC_API_KEY='sk-ant-...'"
echo "   python3 minka_voz.py"
echo ""
