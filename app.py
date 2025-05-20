from flask import Flask, request, jsonify
import psycopg2
import psycopg2.extras
import requests
from datetime import datetime
import logging
import json
import os
import openai
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import urllib.parse

load_dotenv()

OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
openai.api_key = OPENAI_API_KEY

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'topicos_2')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASS = os.getenv('DB_PASS', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')

TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

app = Flask(__name__)

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

def get_product_categories_promos():
    """Obtener los productos, categorías y promociones"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        # Obtener productos
        cursor.execute("SELECT id, nombre, descripcion FROM producto WHERE activo = TRUE")
        productos = [dict(row) for row in cursor.fetchall()]
        
        # Obtener categorías
        cursor.execute("SELECT id, nombre, descripcion FROM categoria")
        categorias = [dict(row) for row in cursor.fetchall()]
        
        # Obtener promociones activas
        today = datetime.now().date()
        cursor.execute("""
            SELECT id, nombre, descripcion 
            FROM promocion 
            WHERE fecha_inicio <= %s AND fecha_fin >= %s
            """, (today, today))
        promociones = [dict(row) for row in cursor.fetchall()]
        
        return {
            'productos': productos,
            'categorias': categorias,
            'promociones': promociones
        }
    except Exception as e:
        logger.error(f"Error al obtener datos para análisis: {e}")
        return {'productos': [], 'categorias': [], 'promociones': []}
    finally:
        cursor.close()
        conn.close()

def analyze_intent(message_text, catalog_data):
    """
    Analiza el mensaje del cliente para detectar intenciones de interés
    utilizando la API de OpenAI
    """
    try:
        if not message_text or message_text.strip() == "":
            return []
        
        productos_str = "\n".join([f"ID: {p['id']}, Nombre: {p['nombre']}, Descripción: {p['descripcion']}" 
                                 for p in catalog_data['productos']])
        categorias_str = "\n".join([f"ID: {c['id']}, Nombre: {c['nombre']}, Descripción: {c['descripcion']}" 
                                  for c in catalog_data['categorias']])
        promociones_str = "\n".join([f"ID: {p['id']}, Nombre: {p['nombre']}, Descripción: {p['descripcion']}" 
                                   for p in catalog_data['promociones']])
        
        # Preparar el prompt para OpenAI
        prompt = f"""
        Analiza el siguiente mensaje de un cliente para detectar intenciones de interés en productos, categorías o promociones.
        
        Mensaje del cliente: "{message_text}"
        
        Catálogo de productos:
        {productos_str}
        
        Categorías disponibles:
        {categorias_str}
        
        Promociones activas:
        {promociones_str}
        
        Responde con un JSON que contenga un array de intereses detectados, donde cada interés debe incluir:
        1. tipo_interes: "producto", "categoria" o "promocion"
        2. entidad_id: el ID numérico de la entidad (producto, categoría o promoción)
        3. nivel_interes: un valor entre 0 y 1 que indique el nivel de confianza en el interés (0 = no hay interés, 1 = interés confirmado)
        
        Si no se detecta interés, devuelve un array vacío.
        Ejemplo de formato de respuesta:
        {{"intereses": [
            {{"tipo_interes": "producto", "entidad_id": 5, "nivel_interes": 0.9}},
            {{"tipo_interes": "categoria", "entidad_id": 2, "nivel_interes": 0.7}}
        ]}}
        
        Solo responde con el objeto JSON, sin texto adicional.
        """
        
        # Llamada a la API de OpenAI
        response = openai.chat.completions.create(
            model="gpt-4o",  # o el modelo que prefieras
            messages=[
                {"role": "system", "content": "Eres un sistema de análisis de intenciones para un e-commerce."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3
        )
        
        # Extraer y procesar la respuesta
        result_text = response.choices[0].message.content.strip()
        
        # Intentar extraer solo el JSON si está rodeado de texto
        try:
            # Buscar el JSON en la respuesta
            import re
            json_match = re.search(r'({[\s\S]*})', result_text)
            if json_match:
                result_text = json_match.group(1)
            
            result = json.loads(result_text)
            
            # Verificar si el resultado tiene el formato esperado
            if 'intereses' not in result:
                # Si devuelve un formato diferente pero parece válido, intentamos adaptarlo
                if isinstance(result, list):
                    return result
                else:
                    # Intentar extraer intereses si están en la raíz del objeto
                    return result.get('intereses', [])
            
            return result['intereses']
        except json.JSONDecodeError as e:
            logger.error(f"Error al decodificar JSON de OpenAI: {e}, respuesta: {result_text}")
            return []
    
    except Exception as e:
        logger.error(f"Error en análisis de intenciones: {e}")
        return []

def store_intent(mensaje_id, cliente_id, intereses_detectados):
    """Almacena los intereses detectados en la base de datos"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        for interes in intereses_detectados:
            tipo_interes = interes.get('tipo_interes')
            entidad_id = interes.get('entidad_id')
            nivel_interes = interes.get('nivel_interes', 0.5)
            
            # Validar datos
            if not tipo_interes or not entidad_id:
                logger.warning(f"Datos de interés incompletos: {interes}")
                continue
                
            # Preparar la inserción según el tipo de interés
            producto_id = entidad_id if tipo_interes == 'producto' else None
            categoria_id = entidad_id if tipo_interes == 'categoria' else None
            promocion_id = entidad_id if tipo_interes == 'promocion' else None
            
            # Insertar en la tabla interes
            cursor.execute("""
                INSERT INTO interes 
                (cliente_id, mensaje_id, producto_id, categoria_id, promocion_id, nivel_interes)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                RETURNING id
            """, (cliente_id, mensaje_id, producto_id, categoria_id, promocion_id, nivel_interes))
            
            result = cursor.fetchone()
            if result:
                logger.info(f"Interés almacenado con ID: {result[0]}")
            else:
                logger.info("No se insertó el interés (posible duplicado)")
        
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Error al almacenar interés: {e}")
        return False
    finally:
        cursor.close()
        conn.close()

def process_message_intent(mensaje_id, message_text, cliente_id):
    """Procesa un mensaje para análisis de intenciones y almacena los resultados"""
    try:
        # Obtener datos del catálogo
        catalog_data = get_product_categories_promos()
        
        # Analizar intenciones
        intereses_detectados = analyze_intent(message_text, catalog_data)
        
        if intereses_detectados:
            logger.info(f"Intereses detectados para mensaje {mensaje_id}: {intereses_detectados}")
            
            # Almacenar intereses
            if store_intent(mensaje_id, cliente_id, intereses_detectados):
                return {"success": True, "intereses": intereses_detectados}
            else:
                return {"success": False, "error": "Error al almacenar intereses"}
        else:
            logger.info(f"No se detectaron intereses para mensaje {mensaje_id}")
            return {"success": True, "intereses": []}
    
    except Exception as e:
        logger.error(f"Error en process_message_intent: {e}")
        return {"success": False, "error": str(e)}

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

def get_or_create_conversation(client_id):
    """Crear una nueva conversación o obtener la activa para hoy"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        today = datetime.now().date()
        
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
                 media_url=None, media_mimetype=None, media_filename=None, is_bot=False):
    """Almacenar un mensaje en la base de datos"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            INSERT INTO mensaje 
            (tipo, contenido_texto, media_url, media_mimetype, media_filename, conversacion_id, isbot)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        """, (message_type, content_text, media_url, media_mimetype, 
              media_filename, conversation_id, is_bot))
        
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
        incoming_msg = request.form.get('Body', '')
        wa_id = request.form.get('From', '').replace('whatsapp:', '')
        
        logger.info(f"Mensaje recibido de {wa_id}: {incoming_msg}")
        
        # Obtener o crear cliente y conversación
        client_id = get_or_create_client(wa_id)
        conversation_id = get_or_create_conversation(client_id)
        
        # Verificar si hay medios
        num_media = int(request.form.get('NumMedia', '0'))
        
        # Almacenar mensaje
        if num_media > 0:
            # Manejar mensaje con medios
            for i in range(num_media):
                media_url = request.form.get(f'MediaUrl{i}')
                media_type = request.form.get(f'MediaContentType{i}')
                
                # Extraer nombre de archivo o usar uno predeterminado
                media_filename = f"media_{datetime.now().strftime('%Y%m%d%H%M%S')}"
                
                # Almacenar mensaje con medios
                mensaje_id = store_message(
                    conversation_id=conversation_id,
                    message_type='media',
                    content_text=incoming_msg if incoming_msg else None,
                    media_url=media_url,
                    media_mimetype=media_type,
                    media_filename=media_filename
                )
        else:
            # Almacenar mensaje de texto
            mensaje_id = store_message(
                conversation_id=conversation_id,
                message_type='text',
                content_text=incoming_msg
            )
        
        #analizando 
        if incoming_msg:
            process_message_intent(mensaje_id, incoming_msg, client_id)
        
        # Crear una respuesta
        resp = MessagingResponse()
        resp.message("Mensaje recibido, gracias!")
        
        return str(resp)
    
    except Exception as e:
        logger.error(f"Error en webhook: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/analyze_message_intent', methods=['POST'])
def analyze_message_intent():
    """Analiza las intenciones de un mensaje existente"""
    try:
        data = request.json
        mensaje_id = data.get('mensaje_id')
        
        if not mensaje_id:
            return jsonify({"error": "Se requiere ID de mensaje"}), 400
        
        # Obtener el mensaje y el cliente asociado
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("""
            SELECT m.id, m.contenido_texto, c.cliente_id
            FROM mensaje m
            JOIN conversacion c ON m.conversacion_id = c.id
            WHERE m.id = %s
        """, (mensaje_id,))
        
        message = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not message:
            return jsonify({"error": "Mensaje no encontrado"}), 404
        
        # Procesar intenciones
        result = process_message_intent(
            mensaje_id=mensaje_id,
            message_text=message['contenido_texto'],
            cliente_id=message['cliente_id']
        )
        
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error en analyze_message_intent: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/analyze_client_intent', methods=['POST'])
def analyze_client_intent():
    """Analiza las intenciones de todas las conversaciones de un cliente"""
    try:
        data = request.json
        cliente_id = data.get('cliente_id')
        
        if not cliente_id:
            return jsonify({"error": "Se requiere ID de cliente"}), 400
        
        # Obtener mensajes del cliente que no han sido analizados
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("""
            SELECT m.id, m.contenido_texto
            FROM mensaje m
            JOIN conversacion c ON m.conversacion_id = c.id
            WHERE c.cliente_id = %s
            AND m.isbot = FALSE
            AND m.contenido_texto IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM interes i WHERE i.mensaje_id = m.id
            )
        """, (cliente_id,))
        
        messages = cursor.fetchall()
        cursor.close()
        conn.close()
        
        if not messages:
            return jsonify({"message": "No hay mensajes nuevos para analizar"}), 200
        
        # Analizar cada mensaje
        results = []
        for message in messages:
            result = process_message_intent(
                mensaje_id=message['id'],
                message_text=message['contenido_texto'],
                cliente_id=cliente_id
            )
            results.append({
                "mensaje_id": message['id'],
                "result": result
            })
        
        return jsonify({
            "success": True,
            "messages_analyzed": len(results),
            "results": results
        })
    
    except Exception as e:
        logger.error(f"Error en analyze_client_intent: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/get_client_interests', methods=['GET'])
def get_client_interests():
    """Obtener todos los intereses de un cliente específico"""
    try:
        cliente_id = request.args.get('cliente_id')
        
        if not cliente_id:
            return jsonify({"error": "Se requiere ID de cliente"}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("""
            SELECT i.*, 
                   p.nombre as producto_nombre,
                   c.nombre as categoria_nombre,
                   pr.nombre as promocion_nombre,
                   m.contenido_texto as mensaje_texto
            FROM interes i
            LEFT JOIN producto p ON i.producto_id = p.id
            LEFT JOIN categoria c ON i.categoria_id = c.id
            LEFT JOIN promocion pr ON i.promocion_id = pr.id
            LEFT JOIN mensaje m ON i.mensaje_id = m.id
            WHERE i.cliente_id = %s
            ORDER BY i.fecha_interes DESC
        """, (cliente_id,))
        
        interests = []
        for row in cursor.fetchall():
            interest_type = None
            entity_id = None
            entity_name = None
            
            if row['producto_id']:
                interest_type = 'producto'
                entity_id = row['producto_id']
                entity_name = row['producto_nombre']
            elif row['categoria_id']:
                interest_type = 'categoria'
                entity_id = row['categoria_id']
                entity_name = row['categoria_nombre']
            elif row['promocion_id']:
                interest_type = 'promocion'
                entity_id = row['promocion_id']
                entity_name = row['promocion_nombre']
            
            interests.append({
                "id": row['id'],
                "tipo_interes": interest_type,
                "entidad_id": entity_id,
                "entidad_nombre": entity_name,
                "nivel_interes": float(row['nivel_interes']),
                "mensaje_id": row['mensaje_id'],
                "mensaje_texto": row['mensaje_texto'],
                "fecha_interes": row['fecha_interes'].isoformat() if row['fecha_interes'] else None
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "cliente_id": cliente_id,
            "intereses": interests
        })
    
    except Exception as e:
        logger.error(f"Error al recuperar intereses del cliente: {e}")
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
        
        store_message(
            conversation_id=conversation_id,
            message_type=message_type,
            content_text=message_text,
            media_url=media_url,
            media_mimetype=media_mimetype,
            media_filename=media_filename,
            is_bot=True
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
            SELECT c.*, COUNT(m.id) as conversation_count 
            FROM cliente c
            LEFT JOIN conversacion m ON c.id = m.cliente_id
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
                "conversation_count": row['conversation_count']
            })
        
        cursor.close()
        conn.close()
        
        return clients
    
    except Exception as e:
        logger.error(f"Error al recuperar clientes: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Verificación simple del estado de salud del servicio"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=True)