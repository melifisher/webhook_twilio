from flask import Flask, request, jsonify
import psycopg2
import psycopg2.extras
import requests
from datetime import datetime
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import logging
import json
import urllib.parse
import os

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'topicos_2')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASS = os.getenv('DB_PASS', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')

TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

def get_db_connection():
    """Conexión a la base de datos PostgreSQL"""
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT
        )
        return conn
    except Exception as e:
        logger.error(f"Error de conexión a la base de datos: {e}")
        raise

def get_or_create_client(phone_number, name=None):
    """Obtener cliente por número de teléfono o crear si no existe"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        # Intentar encontrar el cliente
        cursor.execute("SELECT * FROM cliente WHERE telefono = %s", (phone_number,))
        client = cursor.fetchone()
        
        # Si el cliente no existe, crear uno nuevo
        if not client:
            if not name:
                name = f"Cliente {phone_number}"
            
            cursor.execute(
                "INSERT INTO cliente (telefono, nombre) VALUES (%s, %s) RETURNING id",
                (phone_number, name)
            )
            client_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"Nuevo cliente creado con ID: {client_id}")
        else:
            client_id = client['id']
            logger.info(f"Cliente existente encontrado con ID: {client_id}")
        
        return client_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_or_create_client: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def get_or_create_conversation():
    """Crear una nueva conversación o obtener la activa para hoy"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        today = datetime.now().date()
        
        # Intentar encontrar una conversación para hoy
        cursor.execute("SELECT * FROM conversacion WHERE fecha = %s AND cliente_id = %s", (today, client_id))
        conversation = cursor.fetchone()
        
        if not conversation:
            cursor.execute(
                "INSERT INTO conversacion (fecha, descripcion, cliente_id) VALUES (%s, %s, %s) RETURNING id",
                (today, f"Conversación para {today}", client_id)
            )
            conversation_id = cursor.fetchone()[0]
            conn.commit()
            logger.info(f"Nueva conversación creada con ID: {conversation_id} para cliente {client_id}")
        else:
            conversation_id = conversation['id']
            logger.info(f"Conversación existente encontrada con ID: {conversation_id} para cliente {client_id}")
        
        return conversation_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_or_create_conversation: {e}")
        raise
    finally:
        cursor.close()
        conn.close()


def store_message(conversation_id, message_type, content_text=None, 
                 media_url=None, media_mimetype=None, media_filename=None):
    """Almacenar un mensaje en la base de datos"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO mensaje 
            (tipo, contenido_texto, media_url, media_mimetype, media_filename, conversacion_id)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (message_type, content_text, media_url, media_mimetype, 
              media_filename, conversation_id))
        
        message_id = cursor.fetchone()[0]
        conn.commit()
        logger.info(f"Mensaje almacenado con ID: {message_id} para conversación {conversation_id}")
        return message_id
    except Exception as e:
        conn.rollback()
        logger.error(f"Error al almacenar mensaje: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def download_media(media_url):
    """Descargar medios desde la API de Twilio"""
    media_response = requests.get(
        media_url,
        auth=(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    )
    if media_response.status_code == 200:
        return media_response.content
    else:
        logger.error(f"Error al descargar medios: {media_response.status_code}")
        return None

############ ENDPOINTS ############
@app.route('/webhook', methods=['POST'])
def webhook():
    """Manejar mensajes entrantes de WhatsApp desde Twilio"""
    try:
        # Extraer detalles del mensaje
        incoming_msg = request.form.get('Body', '')
        wa_id = request.form.get('From', '').replace('whatsapp:', '')
        
        logger.info(f"Mensaje recibido de {wa_id}: {incoming_msg}")
        
        # Obtener o crear cliente y conversación
        client_id = get_or_create_client(wa_id)
        conversation_id = get_or_create_conversation(client_id)
        
        # Verificar si hay medios
        num_media = int(request.form.get('NumMedia', '0'))
        
        if num_media > 0:
            # Manejar mensaje con medios
            for i in range(num_media):
                media_url = request.form.get(f'MediaUrl{i}')
                media_type = request.form.get(f'MediaContentType{i}')
                
                # Extraer nombre de archivo del encabezado content-disposition o usar uno predeterminado
                media_filename = f"media_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                
                # Almacenar mensaje con medios
                store_message(
                    conversation_id=conversation_id,
                    message_type='media',
                    content_text=incoming_msg if incoming_msg else None,
                    media_url=media_url,
                    media_mimetype=media_type,
                    media_filename=media_filename
                )
        else:
            # Almacenar mensaje de texto
            store_message(
                conversation_id=conversation_id,
                message_type='text',
                content_text=incoming_msg
            )
        
        # Crear una respuesta (opcional)
        resp = MessagingResponse()
        # resp.message("Mensaje recibido, gracias!")
        
        return str(resp)
    
    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/send_message', methods=['POST'])
def send_message():
    """Enviar un mensaje de WhatsApp a un cliente"""
    try:
        data = request.json
        phone_number = data.get('phone_number')
        message_text = data.get('message')
        media_url = data.get('media_url')
        
        if not phone_number:
            return jsonify({"error": "Se requiere número de teléfono"}), 400
        
        # Formatear número de teléfono para WhatsApp
        if not phone_number.startswith('whatsapp:'):
            whatsapp_number = f"whatsapp:{phone_number}"
        else:
            whatsapp_number = phone_number
            phone_number = phone_number.replace('whatsapp:', '')
        
        # Obtener o crear cliente y conversación
        client_id = get_or_create_client(phone_number)
        conversation_id = get_or_create_conversation(client_id)
        
        # Enviar mensaje a través de Twilio
        message_params = {
            'from_': f"whatsapp:{TWILIO_PHONE_NUMBER}",
            'to': whatsapp_number
        }
        
        if media_url:
            message_params['media_url'] = [media_url]
        
        if message_text:
            message_params['body'] = message_text
        
        # Enviar el mensaje
        twilio_message = client.messages.create(**message_params)
        
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
        
        store_message(
            conversation_id=conversation_id,
            message_type=message_type,
            content_text=message_text,
            media_url=media_url,
            media_mimetype=media_mimetype,
            media_filename=media_filename
        )
        
        return jsonify({
            "success": True,
            "message": "Mensaje enviado exitosamente",
            "twilio_sid": twilio_message.sid
        })
    
    except Exception as e:
        logger.error(f"Error al enviar mensaje: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_client_messages', methods=['GET'])
def get_client_messages():
    """Obtener todos los mensajes para un cliente específico"""
    try:
        phone_number = request.args.get('phone_number')
        
        if not phone_number:
            return jsonify({"error": "Se requiere número de teléfono"}), 400
        
        phone_number = phone_number.replace('whatsapp:', '')
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Obtener ID del cliente
        cursor.execute("SELECT id FROM cliente WHERE telefono = %s", (phone_number,))
        client = cursor.fetchone()
        
        if not client:
            return jsonify({"error": "Cliente no encontrado"}), 404
        
        client_id = client['id']
        
        # Obtener conversaciones para este cliente
        cursor.execute("""
            SELECT id, fecha, descripcion
            FROM conversacion
            WHERE cliente_id = %s
            ORDER BY fecha DESC
        """, (client_id,))
        
        conversations = []
        for conv in cursor.fetchall():
            # Obtener mensajes para cada conversación
            cursor.execute("""
                SELECT m.*
                FROM mensaje m
                WHERE m.conversacion_id = %s
                ORDER BY m.fecha ASC
            """, (conv['id'],))
            
            messages = []
            for row in cursor.fetchall():
                messages.append({
                    "id": row['id'],
                    "type": row['tipo'],
                    "content": row['contenido_texto'],
                    "media_url": row['media_url'],
                    "media_type": row['media_mimetype'],
                    "media_filename": row['media_filename'],
                    "timestamp": row['fecha'].isoformat() if row['fecha'] else None
                })
            
            conversations.append({
                "id": conv['id'],
                "date": conv['fecha'].isoformat() if conv['fecha'] else None,
                "description": conv['descripcion'],
                "messages": messages
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "client_phone": phone_number,
            "conversations": conversations
        })
    
    except Exception as e:
        logger.error(f"Error al recuperar mensajes del cliente: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_clients', methods=['GET'])
def get_clients():
    """Obtener todos los clientes"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("""
            SELECT c.*, COUNT(m.id) as message_count 
            FROM cliente c
            LEFT JOIN mensaje m ON c.id = m.cliente_id
            GROUP BY c.id
            ORDER BY c.fecha_creacion DESC
        """)
        
        clients = []
        for row in cursor.fetchall():
            clients.append({
                "id": row['id'],
                "phone": row['telefono'],
                "name": row['nombre'],
                "email": row['correo'],
                "created_at": row['fecha_creacion'].isoformat() if row['fecha_creacion'] else None,
                "message_count": row['message_count']
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "clients": clients
        })
    
    except Exception as e:
        logger.error(f"Error al recuperar clientes: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Verificación simple del estado de salud del servicio"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)