import os
import time
import uuid
import threading
import requests
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Carrega .env localmente
load_dotenv()

app = Flask(__name__)

# --- CORS SIMPLIFICADO E ROBUSTO ---
# Isso habilita CORS para todas as rotas e origens automaticamente
CORS(app, resources={r"/*": {"origins": "*"}})

# Configura logs para aparecerem no painel do Render
logging.basicConfig(level=logging.INFO)
logger = app.logger

# --- CONFIGURAÇÕES ---
CANVI_BASE_URL = os.getenv("CANVI_API_URL", "https://gateway-production.service-canvi.com.br")
CANVI_CLIENT_ID = os.getenv("CANVI_CLIENT_ID")
CANVI_PRIVATE_KEY = os.getenv("CANVI_PRIVATE_KEY")
EMAIL_REMETENTE = os.getenv("EMAIL_USER")
EMAIL_SENHA = os.getenv("EMAIL_PASS")

_cache_token = {"token": None, "expira_em": 0}

def obter_token():
    global _cache_token
    agora = int(time.time())
    
    if _cache_token["token"] and _cache_token["expira_em"] > agora:
        return _cache_token["token"]

    url = f"{CANVI_BASE_URL}/bt/token"
    payload = {"client_id": CANVI_CLIENT_ID, "private_key": CANVI_PRIVATE_KEY}
    
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("token"):
            _cache_token["token"] = data["token"]
            _cache_token["expira_em"] = agora + 80000 
            return data["token"]
        
        raise Exception("API Canvi não retornou token.")
    except Exception as e:
        logger.error(f"Erro Auth: {e}")
        raise e

def enviar_email_confirmacao(dados, copia_cola):
    if not EMAIL_REMETENTE or not EMAIL_SENHA:
        logger.warning("⚠️ E-mail não configurado. Pulei o envio.")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_REMETENTE
        msg['To'] = dados.get('email')
        msg['Subject'] = "Reserva Confirmada - Chromatech Tupana A1"

        html_body = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Olá, {dados.get('nome')}!</h2>
            <p>Código Pix para pagamento:</p>
            <pre style="background: #f4f4f4; padding: 15px;">{copia_cola}</pre>
            <p>Valor: R$ 990,00</p>
        </div>
        """
        msg.attach(MIMEText(html_body, 'html'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_REMETENTE, EMAIL_SENHA)
        server.sendmail(EMAIL_REMETENTE, dados.get('email'), msg.as_string())
        server.quit()
        logger.info(f"✅ E-mail enviado para {dados.get('email')}")

    except Exception as e:
        logger.error(f"❌ Erro E-mail: {e}")

@app.route('/')
def home():
    return "API Chroma3D Online 🚀", 200

@app.route('/api/pix', methods=['POST'])
def gerar_pix():
    # Log para debug no Render
    logger.info("🔔 Recebi uma chamada em /api/pix")
    
    try:
        data = request.json
        if not data:
            return jsonify({"status": "error", "message": "JSON vazio"}), 400

        logger.info(f"Gerando Pix para: {data.get('nome')}")

        token = obter_token()
        
        payload_canvi = {
            "valor": "990.00",
            "tipo_transacao": "pixCashin",
            "vencimento": (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S"),
            "descricao": f"Entrada Tupana A1 - {data.get('nome', 'Cli')[:20]}",
            "identificador_externo": str(uuid.uuid4()),
            "identificador_movimento": str(uuid.uuid4()),
            "enviar_qr_code": True
        }

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        resp = requests.post(f"{CANVI_BASE_URL}/bt/pix", json=payload_canvi, headers=headers, timeout=30)
        resp_data = resp.json()

        copia_cola = resp_data.get('data', {}).get('brcode') or resp_data.get('emv_payload')
        imagem_qr = resp_data.get('data', {}).get('qrcode')

        if not copia_cola:
            logger.error(f"Erro Canvi: {resp_data}")
            return jsonify({"status": "error", "message": "Erro ao gerar Pix na operadora."}), 400

        threading.Thread(target=enviar_email_confirmacao, args=(data, copia_cola)).start()

        return jsonify({
            "status": "success",
            "copia_cola": copia_cola,
            "imagem_qr": imagem_qr
        })

    except Exception as e:
        logger.error(f"Erro Geral: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))