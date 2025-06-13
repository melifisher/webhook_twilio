from flask import Flask, request, jsonify
import psycopg2
import psycopg2.extras
from datetime import datetime
import logging
import os
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import urllib.parse
from database_integration import setup_complete_system, update_product_embeddings
from config import config

load_dotenv()

TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

bot, db_manager, add_generator = setup_complete_system()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.files.log_file),
        logging.StreamHandler()
    ]
)

logging.getLogger('openai').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

app = Flask(__name__)

############ ENDPOINTS ############
@app.route('/webhook', methods=['POST'])
def webhook():
    """Manejar mensajes entrantes de WhatsApp desde Twilio"""
    try:
        incoming_msg = request.form.get('Body', '')
        wa_id = request.form.get('From', '').replace('whatsapp:', '')
        nombre = request.form.get('ProfileName', None)
        
        logger.info(f"Mensaje recibido de {wa_id}: {incoming_msg}")
        result = bot.process_client_message(wa_id, incoming_msg, nombre)
        
        if result['success']:
            logger.info(f"Respuesta generada: {result['response']}")
            resp = MessagingResponse()
            resp.message(result['response'])
        else :
            logger.error(f"Error procesando mensaje: {result['error']}")
            resp = MessagingResponse()
            resp.message('Gracias por tu mensaje, te contestaremos enseguida!')
            return jsonify({"error": result['error']}), 500

        return str(resp)
    
    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/update_embeddings', methods=['GET'])
def update_embeddings():
    """actualiza los embeddings de la base de datos"""
    try:
        update_product_embeddings()

        return jsonify({
            "success": True
        })
    
    except Exception as e:
        logger.error(f"Error en update_embeddings: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/analyze_client_intents', methods=['GET'])
def analyze_client_intents():
    """Analiza las intenciones de todas las conversaciones de un cliente"""
    try:
        cliente_id = request.args.get('cliente_id')
        
        if not cliente_id:
            return jsonify({"error": "Se requiere ID de cliente"}), 400
        
        intents = bot.process_client_conversation_intents(cliente_id)
        
        return jsonify({
            "success": True,
            "cant_intents": len(intents),
            "intents": intents
        })
    
    except Exception as e:
        logger.error(f"Error en analyze_client_intent: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/send_message', methods=['POST'])
def send_message():
    """Enviar un mensaje de WhatsApp a un cliente"""
    try:
        data = request.json
        phone_number = data.get('phone_number')
        message_text = data.get('message')
        media_url = data.get('media_url')
        logger.info(f"Enviando mensaje a {phone_number}: {message_text}, media_url: {media_url}")
    
        if not phone_number:
            return jsonify({"error": "Se requiere número de teléfono"}), 400
        
        # Formatear número de teléfono para WhatsApp
        if not phone_number.startswith('whatsapp:'):
            whatsapp_number = f"whatsapp:{phone_number}"
        else:
            whatsapp_number = phone_number
            phone_number = phone_number.replace('whatsapp:', '')
        
        # Enviar mensaje a través de Twilio
        message_params = {
            'from_': f"whatsapp:{TWILIO_PHONE_NUMBER}",
            'to': whatsapp_number
        }
        
        if media_url:
            message_params['media_url'] = [media_url]
        
        if message_text:
            message_params['body'] = message_text
        
        logger.info(f"message_params: {message_params}")

        # Enviar el mensaje
        twilio_message = client.messages.create(**message_params)
        logger.info(f"Mensaje enviado a {whatsapp_number}: {twilio_message.sid}")
        logger.info(twilio_message.sid)

        # Almacenar el mensaje enviado en la base de datos
        message_type = 'media' if media_url else 'text'
        media_mimetype = None
        media_filename = None
        
        if media_url:
            # Intentar determinar el tipo de medio y nombre de archivo desde la URL
            parsed_url = urllib.parse.urlparse(media_url)
            media_filename = os.path.basename(parsed_url.path)
            
            extension = os.path.splitext(media_filename)[1].lower()
            mime_map = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg', 
                '.png': 'image/png',
                '.pdf': 'application/pdf',
                '.doc': 'application/msword',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
            }
            media_mimetype = mime_map.get(extension, 'application/octet-stream')
        
        return jsonify({
            "success": True,
            "message": "Mensaje enviado exitosamente",
            "twilio_sid": twilio_message.sid
        })
    
    except Exception as e:
        logger.error(f"Error al enviar mensaje: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/send_adds', methods=['GET'])
def send_add_messages():
    """Enviar adds a clientes por WhatsApp"""
    try:
        clients = db_manager.get_clients_with_interests(
            min_interest_level=0.6,
            days_back=50
        )

        logger.info(f"clients: {clients}")

        if not clients:
            logger.info("No clients found with specified interest criteria")
            return jsonify({
                'success': True,
                'message': 'No clients found with specified interest criteria',
                'sent_count': 0
            })
            
        results = {
            'total_clients': len(clients),
            'successful_sends': 0,
            'failed_sends': 0,
            'details': []
        }

        for cliente in clients:
            try:
                public_url, pdf_path = add_generator.create_ads_for_client(cliente['nombre'], cliente['interests'])
                logger.info(f"url en @: {public_url}")
                caption = f"¡Hola {cliente['nombre']}! 🎉\n\n"
                caption += f"¡Tenemos una oferta especial para ti!\n\n"
                caption += f"💝 ¡No te pierdas esta oportunidad!"
                
                whatsapp_number = f"whatsapp:{cliente['telefono']}"
        
                # Enviar mensaje a través de Twilio
                message_params = {
                    'from_': f"whatsapp:{TWILIO_PHONE_NUMBER}",
                    'to': whatsapp_number,
                    'body': caption,
                    'media_url': [public_url]
                }
                twilio_message = client.messages.create(**message_params)
                logger.info(f"Mensaje enviado a {whatsapp_number}: {twilio_message.sid}")
                logger.info(twilio_message.sid)

                results['successful_sends'] += 1

            except Exception as e:
                logger.error(f"Error enviando mensaje a {cliente.get('nombre', 'Unknown')}: {e}")
                results['failed_sends'] += 1
                results['details'].append({
                    'client': cliente.get('nombre', 'Unknown'),
                    'phone': cliente.get('telefono', 'Unknown'),
                    'status': 'error',
                    'reason': str(e)
                })
        

        logger.info(f"results: {results}")
        return jsonify({
            'success': True,
            'message': f"Processed {len(clients)} clients",
            'results': results
        })
    
    except Exception as e:
        logger.error(f"Error al enviar mensaje: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/create_ad', methods=['POST'])
def create_ad():
    """Enviar adds a clientes por WhatsApp"""
    try:
        data = request.json
        logger.info(f"data: {data}")
        cliente = data
        
        logger.info(f"cliente: {cliente}")

        if not cliente:
            logger.info("No cliente found with specified interest criteria")
            return jsonify({"error": 'No client found with specified interest criteria'}), 500

        try:
            public_url = add_generator.create_ads_for_client(cliente['nombre'], cliente['interests'])
            logger.info(f"url en @: {public_url}")
            caption = f"¡Hola {cliente['nombre']}! 🎉\n\n"
            caption += f"¡Tenemos una oferta especial para ti!\n\n"
            caption += f"💝 ¡No te pierdas esta oportunidad!"
            
            whatsapp_number = f"whatsapp:{cliente['telefono']}"
    
            # Enviar mensaje a través de Twilio
            message_params = {
                'from_': f"whatsapp:{TWILIO_PHONE_NUMBER}",
                'to': whatsapp_number,
                'body': caption,
                'media_url': [public_url]
            }
            twilio_message = client.messages.create(**message_params)
            logger.info(f"Mensaje enviado a {whatsapp_number}: {twilio_message.sid}")
            logger.info(twilio_message.sid)

            return public_url

        except Exception as e:
            logger.error(f"Error enviando mensaje a {cliente.get('nombre', 'Unknown')}: {e}")
            return jsonify({"error": str(e)}), 500
    
    except Exception as e:
        logger.error(f"Error al enviar mensaje: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/get_clients', methods=['GET'])
def get_clients():
    """Obtener todos los clientes"""
    try:
        clients = db_manager.get_all_clients()
        logger.info(f"clients: {clients}")
        return clients
    
    except Exception as e:
        logger.error(f"Error al recuperar clientes: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/get_clients_with_interests', methods=['GET'])
def get_clients_with_interests():
    """
    Obtener clientes que han mostrado interés en productos/categorías/promociones
    con filtros opcionales de tiempo y nivel de interés
    """
    try:
        clients = db_manager.get_clients_with_interests(
            min_interest_level=0.6,
            days_back=10
        )
        logger.info(f"clients: {clients}")
        return clients
    
    except Exception as e:
        logger.error(f"Error al recuperar clientes con intereses: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Verificación simple del estado de salud del servicio"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)