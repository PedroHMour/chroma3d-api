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

load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Configura logs
logging.basicConfig(level=logging.INFO)
logger = app.logger

# --- CONSTANTES IGUAIS AO SEU REFERENCIAL ---
TOKEN_ENDPOINT = '/bt/token'
PIX_ENDPOINT = '/bt/pix'

# Variáveis de Ambiente
CANVI_API_URL = os.getenv("CANVI_API_URL", "https://gateway-production.service-canvi.com.br")
CANVI_CLIENT_ID = os.getenv("CANVI_CLIENT_ID")
CANVI_PRIVATE_KEY = os.getenv("CANVI_PRIVATE_KEY")

EMAIL_REMETENTE = os.getenv("EMAIL_USER")
EMAIL_SENHA = os.getenv("EMAIL_PASS")

# Cache local
_cache_token = { "token": None, "expira_em": 0 }

# --- SUA FUNÇÃO DE TOKEN (ADAPTADA PARA FLASK) ---
def _obter_token():
    global _cache_token
    agora = int(time.time())
    
    if _cache_token["token"] and _cache_token["expira_em"] > agora:
        logger.info("[Auth] Usando token cache.")
        return _cache_token["token"]

    url_token = f"{CANVI_API_URL}{TOKEN_ENDPOINT}"
    headers = {'Content-Type': 'application/json'}
    payload = { "client_id": CANVI_CLIENT_ID, "private_key": CANVI_PRIVATE_KEY }

    try:
        logger.info(f"[Auth] Solicitando token em: {url_token}")
        response = requests.post(url_token, headers=headers, json=payload, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        
        if data.get("token"):
            _cache_token["token"] = data["token"]
            _cache_token["expira_em"] = agora + 3000
            return data["token"]
        else:
            raise Exception(f"Sem token na resposta: {data}")

    except Exception as e:
        logger.error(f"[Auth] Erro: {e}")
        raise e

# --- FUNÇÃO DE E-MAIL (BACKGROUND) ---
def enviar_email_confirmacao(dados, copia_cola):
    if not EMAIL_REMETENTE or not EMAIL_SENHA:
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_REMETENTE
        msg['To'] = dados.get('email')
        msg['Subject'] = "Reserva Confirmada - Chromatech Tupana A1"

        body = f"""
        <h2>Olá, {dados.get('nome')}</h2>
        <p>Código Pix para pagamento (R$ 990,00):</p>
        <pre style="background:#eee;padding:10px;">{copia_cola}</pre>
        """
        msg.attach(MIMEText(body, 'html'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_REMETENTE, EMAIL_SENHA)
        server.sendmail(EMAIL_REMETENTE, dados.get('email'), msg.as_string())
        server.quit()
        logger.info("✅ E-mail enviado.")
    except Exception as e:
        logger.error(f"❌ Erro E-mail: {e}")

@app.route('/')
def home():
    return "API Online", 200

@app.route('/api/pix', methods=['POST'])
def gerar_pix_route():
    try:
        # 1. Dados do Front
        data_front = request.json
        if not data_front:
            return jsonify({"erro": "JSON inválido"}), 400

        logger.info(f"[Pix] Iniciando para: {data_front.get('nome')}")

        # 2. Pega Token
        token = _obter_token()

        # 3. Prepara Payload IGUAL AO SEU CÓDIGO DE REFERÊNCIA
        url_pix = f"{CANVI_API_URL}{PIX_ENDPOINT}"
        headers = { "Authorization": f"Bearer {token}", "Content-Type": "application/json" }
        
        # Dados calculados
        valor_cobrar = 990.00
        vencimento = (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S")
        descricao = f"Entrada Tupana A1 - {data_front.get('nome')[:20]}"
        
        # PAYLOAD DO SEU CÓDIGO ANTIGO
        payload_canvi = {
            "valor": f"{valor_cobrar:.2f}", # Formata como string "990.00"
            "tipo_transacao": "pixCashin", 
            "vencimento": vencimento, 
            "descricao": descricao,
            "texto_instrucao": descricao, # Campo que faltava antes
            "identificador_externo": str(uuid.uuid4()), 
            "identificador_movimento": str(uuid.uuid4()), 
            "enviar_qr_code": True # Seu código usava True, voltamos para True
        }

        logger.info(f"[Pix] Enviando payload: {payload_canvi}")

        # 4. Request (Timeout 60 igual sua referência)
        response = requests.post(url_pix, headers=headers, json=payload_canvi, timeout=60)
        
        # Debug se der erro (Isso vai aparecer no log do Render)
        if response.status_code >= 400:
            logger.error(f"[Pix] Erro API Canvi ({response.status_code}): {response.text}")
            return jsonify({"erro": "Erro na operadora", "detalhe": response.text}), response.status_code

        data_canvi = response.json()

        # 5. Normaliza para o Front
        copia_cola = data_canvi.get('data', {}).get('brcode') or data_canvi.get('emv_payload')
        imagem_qr = data_canvi.get('data', {}).get('qrcode')

        if not copia_cola:
            return jsonify({"erro": "Pix não gerado", "debug": data_canvi}), 400

        # 6. E-mail em background
        threading.Thread(target=enviar_email_confirmacao, args=(data_front, copia_cola)).start()

        return jsonify({
            "status": "success",
            "copia_cola": copia_cola,
            "imagem_qr": imagem_qr
        })

    except requests.exceptions.ReadTimeout:
        logger.error("[Pix] Timeout da Canvi")
        return jsonify({"erro": "Gateway demorou muito"}), 504
    except Exception as e:
        logger.error(f"[Pix] Exception: {e}")
        return jsonify({"erro": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))