import os
import time
import uuid
import threading
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# Carrega variáveis locais se existirem
load_dotenv()

app = Flask(__name__)
# Permite acesso do seu site (CORS)
CORS(app)

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
        # Timeout curto (10s)
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if data.get("token"):
            _cache_token["token"] = data["token"]
            _cache_token["expira_em"] = agora + 80000 
            return data["token"]
        
        raise Exception("API Canvi não retornou token.")
    except Exception as e:
        print(f"Erro Auth: {e}")
        raise e

def enviar_email_confirmacao(dados, copia_cola):
    if not EMAIL_REMETENTE or not EMAIL_SENHA:
        print("⚠️ E-mail não configurado. Pulei o envio.")
        return

    print(f"📧 Enviando e-mail para {dados.get('email')}...")

    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_REMETENTE
        msg['To'] = dados.get('email')
        msg['Subject'] = "Reserva Confirmada - Chromatech Tupana A1"

        html_body = f"""
        <div style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto;">
            <div style="background-color: #000; padding: 20px; text-align: center;">
                <h2 style="color: #fff; margin: 0;">Confirmação de Pedido</h2>
            </div>
            <div style="padding: 20px; border: 1px solid #ddd;">
                <p>Olá, <strong>{dados.get('nome')}</strong>!</p>
                <p>Recebemos sua reserva para a <strong>Tupana A1</strong>.</p>
                <p>Se ainda não pagou, use o código Pix abaixo:</p>
                <div style="background-color: #f4f4f4; padding: 15px; border-radius: 8px; word-wrap: break-word; font-family: monospace; font-size: 12px; color: #555;">
                    {copia_cola}
                </div>
                <p style="margin-top: 20px;"><strong>Valor:</strong> R$ 990,00</p>
                <p>Assim que compensar, entraremos em contato.</p>
            </div>
            <div style="text-align: center; padding: 10px; font-size: 12px; color: #999;">
                &copy; 2025 Chromatech.
            </div>
        </div>
        """
        
        msg.attach(MIMEText(html_body, 'html'))

        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(EMAIL_REMETENTE, EMAIL_SENHA)
        text = msg.as_string()
        server.sendmail(EMAIL_REMETENTE, dados.get('email'), text)
        server.quit()
        print("✅ E-mail enviado!")

    except Exception as e:
        print(f"❌ Erro E-mail: {e}")

@app.route('/')
def home():
    return "API Chroma3D Online 🚀", 200

@app.route('/api/pix', methods=['POST'])
def gerar_pix():
    try:
        data = request.json
        token = obter_token()
        nome = data.get('nome', 'Cliente')
        
        payload_canvi = {
            "valor": "990.00",
            "tipo_transacao": "pixCashin",
            "vencimento": (datetime.now() + timedelta(hours=24)).strftime("%Y-%m-%dT%H:%M:%S"),
            "descricao": f"Entrada Tupana A1 - {nome[:20]}",
            "identificador_externo": str(uuid.uuid4()),
            "identificador_movimento": str(uuid.uuid4()),
            "enviar_qr_code": True
        }

        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        # Chama Canvi (Timeout 30s)
        resp = requests.post(f"{CANVI_BASE_URL}/bt/pix", json=payload_canvi, headers=headers, timeout=30)
        resp_data = resp.json()

        copia_cola = resp_data.get('data', {}).get('brcode') or resp_data.get('emv_payload')
        imagem_qr = resp_data.get('data', {}).get('qrcode')

        if not copia_cola:
            print(f"Erro Canvi: {resp_data}")
            return jsonify({"status": "error", "message": "Erro ao gerar Pix."}), 400

        # Dispara e-mail em background (não trava o site)
        threading.Thread(target=enviar_email_confirmacao, args=(data, copia_cola)).start()

        return jsonify({
            "status": "success",
            "copia_cola": copia_cola,
            "imagem_qr": imagem_qr
        })

    except Exception as e:
        print(f"Erro Geral: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))