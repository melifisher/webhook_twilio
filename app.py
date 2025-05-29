from flask import Flask, request, jsonify
import psycopg2
import psycopg2.extras
import requests
from datetime import datetime
import logging
import json
import os
from openai import OpenAI
from dotenv import load_dotenv
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import urllib.parse
from database_integration import setup_complete_system
from config import config

load_dotenv()

clientOpenAi = OpenAI()

DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_NAME = os.getenv('DB_NAME', 'topicos_2')
DB_USER = os.getenv('DB_USER', 'postgres')
DB_PASS = os.getenv('DB_PASS', 'postgres')
DB_PORT = os.getenv('DB_PORT', '5432')

TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_PHONE_NUMBER = os.getenv('TWILIO_PHONE_NUMBER')

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

bot, db_manager = setup_complete_system()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.files.log_file),
        logging.StreamHandler()
    ]
)

# Set specific log levels
logging.getLogger('openai').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

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
        response = clientOpenAi.chat.completions.create(
            model="gpt-3.5-turbo",
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

def get_client_by_id(id):
    """Obtener cliente por id"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        cursor.execute("SELECT * FROM cliente WHERE id = %s", (id,))
        client = cursor.fetchone()
        
        return client
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_client_by_id: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def get_messages_by_conversation_id(id):
    """Obtener mensajes de la conversacion"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cursor.execute("SELECT * FROM mensaje WHERE conversacion_id = %s AND id NOT IN (SELECT id FROM mensaje WHERE conversacion_id = %s ORDER BY id DESC LIMIT 1)", (id, id))
        mensajes = cursor.fetchall()  # ← AQUÍ el cambio importante
        return mensajes
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_messages_by_conversation_id: {e}")
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

def create_message(incoming_msg, conversacion_id,client_name=None):
    """
    Crea una respuesta personalizada usando la API de ChatGPT basada en el mensaje entrante
    y el contexto de la empresa (productos, categorías, promociones y precios).
    
    Args:
        incoming_msg (str): El mensaje recibido del cliente
        client_name (str, optional): Nombre del cliente si está disponible
    
    Returns:
        str: Mensaje de respuesta generado
    """
    try:
        conversacion = get_messages_by_conversation_id(conversacion_id)
        if not isinstance(conversacion, list):
            conversacion = [conversacion]

        productos = get_productos_activos()
        categorias = get_categorias()
        promociones = get_promociones_activas(datetime.now().date())
        
        # Obtener precios actuales de los productos
        precios_productos = get_precios_actuales()
        
        productos_promocion = []
        for promo in promociones:
            prods = get_productos_en_promocion(promo['id'])
            for prod in prods:
                productos_promocion.append({
                    "producto": prod['nombre'],
                    "promocion": promo['nombre'],
                    "descuento": prod['descuento_porcentaje'],
                    "descripcion_promo": promo['descripcion'],
                    "fecha_fin": promo['fecha_fin']
                })
        
        # Enriquecer productos con información de precios
        productos_con_precios = []
        for p in productos:
            precio_info = next((precio for precio in precios_productos if precio['producto_id'] == p['id']), None)
            categoria_nombre = next((c['nombre'] for c in categorias if c['id'] == p['categoria_id']), None)
            
            producto_completo = {
                "nombre": p['nombre'],
                "descripcion": p['descripcion'],
                "categoria": categoria_nombre,
                "precio": precio_info['valor'] if precio_info else None,
                "lista_precio": precio_info['lista_nombre'] if precio_info else None
            }
            productos_con_precios.append(producto_completo)
        
        # Construir el contexto para ChatGPT
        context = {
            "empresa": {
                "nombre": "Ropa Bonita SC",
                "descripcion": "Ofrecemos prendas de alta calidad para nuestros clientes" 
            },
            "productos": productos_con_precios,
            "categorias": [{"nombre": c['nombre'], "descripcion": c['descripcion']} for c in categorias],
            "promociones_activas": [{"nombre": p['nombre'], "descripcion": p['descripcion'], 
                                   "fecha_fin": p['fecha_fin'].strftime('%d/%m/%Y')} for p in promociones],
            "productos_en_promocion": productos_promocion
        }
        
        # Crear string de productos con precios para el prompt
        productos_info = []
        for p in productos_con_precios:
            precio_str = f"Bs{p['precio']:.2f}" if p['precio'] else "Precio no disponible"
            productos_info.append(f"{p['nombre']} ({p['categoria']}) - {precio_str}")
        
        prompt = f"""
        Eres un asistente virtual amable y profesional de {context['empresa']['nombre']}.
        
        Esta es la conversacion hasta ahora con el cliente llamado "{client_name}":
        "{chr(10).join([f"{m['contenido_texto']} (hour: {m['fecha'].strftime('%H:%M')}) (is_bot: {m['isbot']})" for m in conversacion])}"
        Ahora, te ha enviado este mensaje: "{incoming_msg}"
        -------
        Responde de manera concisa, amigable y útil, utilizando la siguiente información sobre nuestra empresa:
        
        PRODUCTOS DISPONIBLES CON PRECIOS:
        {chr(10).join(productos_info)}
        
        CATEGORÍAS:
        {', '.join([c['nombre'] for c in context['categorias']])}
        
        PROMOCIONES ACTIVAS:
        {', '.join([f"{p['nombre']} (hasta {p['fecha_fin']})" for p in context['promociones_activas']])}
        
        PRODUCTOS EN PROMOCIÓN:
        {', '.join([f"{p['producto']} con {p['descuento']}% de descuento en {p['promocion']}" for p in context['productos_en_promocion']])}
        
        INSTRUCCIONES:
        - Si el cliente pregunta por precios, proporciona la información actual disponible
        - Si pregunta por un producto específico, incluye descripción, precio y categoría
        - Si pide más detalles del producto, tienes libertad de inventarte tallas, colores, etc.
        - Si pregunta por promociones, menciona las activas y cómo afectan los precios
        - Si pregunta por rango de precios o productos más económicos/caros, ayúdale con esa información
        - Si su consulta no está relacionada con productos o servicios, ayúdale de manera general sin inventar información
        - Si no puedes responder algo específico, ofrece contactar con un asesor humano
        - Sigue la conversación
        La respuesta debe ser breve (máximo 3-4 frases) pero informativa.
        """
        logger.info(f"Prompt enviado a ChatGPT: {prompt}")
        
        # Llamar a la API de ChatGPT
        response = clientOpenAi.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt},
                     {"role": "system", "content": "Eres un asistente virtual de atención al cliente profesional y amigable. Proporciona información precisa sobre precios cuando sea solicitada."}],
        )
        
        message = response.choices[0].message.content.strip()
        
        return message
    
    except Exception as e:
        # En caso de error, devolver un mensaje genérico
        logger.error(f"Error generando respuesta con ChatGPT: {e}")
        logging.error(f"Error generando respuesta con ChatGPT: {e}")
        return f"Hola{' ' + client_name if client_name else ''}, gracias por contactarnos. En breve un asesor se comunicará contigo."

def get_productos_activos():
    """Obtiene todos los productos activos de la base de datos"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        cursor.execute("""SELECT id, nombre, descripcion, categoria_id 
            FROM producto 
            WHERE activo = TRUE""")
        products = cursor.fetchall()
        
        return products
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_productos_activos: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def get_categorias():
    """Obtiene todas las categorías de la base de datos"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        cursor.execute("""SELECT id, nombre, descripcion FROM categoria""")
        categories = cursor.fetchall()
        
        return categories
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_categorias: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def get_promociones_activas(fecha_actual):
    """Obtiene las promociones activas en la fecha actual"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        logger.info(f"Fecha actual: {fecha_actual}")
    
        cursor.execute("""SELECT id, nombre, descripcion, fecha_inicio, fecha_fin
            FROM promocion
            WHERE fecha_inicio <= %s AND fecha_fin >= %s""", (fecha_actual, fecha_actual))
        promotions = cursor.fetchall()
        logger.info(f"Promociones activas: {promotions}")
        return promotions
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_promociones_activas: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def get_productos_en_promocion(promocion_id):
    """Obtiene los productos asociados a una promoción específica"""
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        cursor.execute("""SELECT p.id, p.nombre, p.descripcion, pp.descuento_porcentaje
        FROM producto p
        JOIN promo_producto pp ON p.id = pp.producto_id
        WHERE pp.promocion_id = %s AND p.activo = TRUE""", (promocion_id,))
        promo_products = cursor.fetchall()
        
        return promo_products
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_productos_en_promocion: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def get_precios_actuales():
    """
    Obtiene los precios actuales vigentes para todos los productos activos.
    Retorna el precio más reciente válido para cada producto.
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        cursor.execute("""
            SELECT DISTINCT ON (p.producto_id) 
                   p.producto_id,
                   p.valor,
                   lp.nombre as lista_nombre,
                   lp.id as lista_id,
                   p.fecha_inicio,
                   p.fecha_fin
            FROM precio p
            JOIN lista_precios lp ON p.lista_precios_id = lp.id
            JOIN producto prod ON p.producto_id = prod.id
            WHERE prod.activo = TRUE
              AND p.fecha_inicio <= CURRENT_DATE
              AND (p.fecha_fin IS NULL OR p.fecha_fin >= CURRENT_DATE)
            ORDER BY p.producto_id, p.fecha_inicio DESC
        """)
        prices = cursor.fetchall()
        
        return prices
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_precios_actuales: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def get_precios_por_producto(producto_id):
    """
    Obtiene todos los precios vigentes para un producto específico
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        cursor.execute("""
            SELECT p.valor,
                   lp.nombre as lista_nombre,
                   p.fecha_inicio,
                   p.fecha_fin
            FROM precio p
            JOIN lista_precios lp ON p.lista_precios_id = lp.id
            WHERE p.producto_id = %s
              AND p.fecha_inicio <= CURRENT_DATE
              AND (p.fecha_fin IS NULL OR p.fecha_fin >= CURRENT_DATE)
            ORDER BY p.fecha_inicio DESC
        """, (producto_id,))
        prices = cursor.fetchall()
        
        return prices
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_precios_por_producto: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

def get_productos_por_rango_precio(precio_min=None, precio_max=None):
    """
    Obtiene productos filtrados por rango de precios
    """
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    
    try:
        base_query = """
            SELECT DISTINCT prod.id, prod.nombre, prod.descripcion, 
                   cat.nombre as categoria_nombre, p.valor as precio
            FROM producto prod
            JOIN categoria cat ON prod.categoria_id = cat.id
            JOIN precio p ON prod.id = p.producto_id
            JOIN lista_precios lp ON p.lista_precios_id = lp.id
            WHERE prod.activo = TRUE
              AND p.fecha_inicio <= CURRENT_DATE
              AND (p.fecha_fin IS NULL OR p.fecha_fin >= CURRENT_DATE)
        """
        
        params = []
        if precio_min is not None:
            base_query += " AND p.valor >= %s"
            params.append(precio_min)
        
        if precio_max is not None:
            base_query += " AND p.valor <= %s"
            params.append(precio_max)
        
        base_query += " ORDER BY p.valor ASC"
        
        cursor.execute(base_query, params)
        products = cursor.fetchall()
        
        return products
    except Exception as e:
        conn.rollback()
        logger.error(f"Error en get_productos_por_rango_precio: {e}")
        raise
    finally:
        cursor.close()
        conn.close()

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


@app.route('/analyze_message_intent', methods=['POST'])#TODO: change to conversation
def analyze_message_intent():
    """Analiza las intenciones de una conversacion existente"""
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

@app.route('/analyze_client_intents', methods=['POST'])
def analyze_client_intents():
    """Analiza las intenciones de todas las conversaciones de un cliente"""
    try:
        data = request.json
        cliente_id = data.get('cliente_id')
        
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
        logger.info(f"Enviando mensaje a {phone_number}: {message_text}, media_url: {media_url}")
    
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


@app.route('/get_clients_with_interests', methods=['GET'])
def get_clients_with_interests():
    """
    Obtener clientes que han mostrado interés en productos/categorías/promociones
    con filtros opcionales de tiempo y nivel de interés
    """
    try:
        # Parámetros opcionales
        days = request.args.get('days', '30')  # Por defecto, último mes
        min_interest = request.args.get('min_interest', '0.6')  # Nivel mínimo de interés
        
        try:
            days = int(days)
            min_interest = float(min_interest)
        except ValueError:
            return jsonify({"error": "Los parámetros 'days' y 'min_interest' deben ser numéricos"}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Obtener clientes con intereses significativos en el período especificado
        cursor.execute("""
            SELECT DISTINCT c.id, c.telefono, c.nombre, c.correo,
                   MAX(i.nivel_interes) as max_interes,
                   COUNT(DISTINCT i.id) as total_intereses
            FROM cliente c
            JOIN interes i ON c.id = i.cliente_id
            WHERE i.fecha_interes >= NOW() - INTERVAL '%s days'
            AND i.nivel_interes >= %s
            GROUP BY c.id, c.telefono, c.nombre, c.correo
            ORDER BY max_interes DESC, total_intereses DESC
        """, (days, min_interest))
        
        clients = []
        for row in cursor.fetchall():
            clients.append({
                "id": row['id'],
                "phone": row['telefono'],
                "name": row['nombre'],
                "email": row['correo'],
                "max_interest_level": float(row['max_interes']),
                "total_interests": row['total_intereses']
            })
        
        cursor.close()
        conn.close()
        
        return clients
    
    except Exception as e:
        logger.error(f"Error al recuperar clientes con intereses: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/get_client_recommendations', methods=['GET'])
def get_client_recommendations():
    """
    Obtiene recomendaciones de productos para un cliente específico 
    basadas en sus intereses
    """
    try:
        cliente_id = request.args.get('cliente_id')
        limit = request.args.get('limit', '3')  # Número de recomendaciones
        
        if not cliente_id:
            return jsonify({"error": "Se requiere cliente_id"}), 400
        
        try:
            limit = int(limit)
        except ValueError:
            return jsonify({"error": "El parámetro 'limit' debe ser numérico"}), 400
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        # Obtener intereses del cliente
        cursor.execute("""
            WITH cliente_intereses AS (
                SELECT 
                    COALESCE(i.producto_id, NULL) as producto_id,
                    COALESCE(i.categoria_id, NULL) as categoria_id,
                    i.nivel_interes
                FROM interes i
                WHERE i.cliente_id = %s
                ORDER BY i.fecha_interes DESC, i.nivel_interes DESC
            )
            SELECT 
                p.id, 
                p.nombre, 
                p.descripcion,
                COALESCE(
                    (SELECT MAX(pr.descuento_porcentaje)
                     FROM promo_producto pr
                     JOIN promocion prom ON pr.promocion_id = prom.id
                     WHERE pr.producto_id = p.id
                     AND CURRENT_DATE BETWEEN prom.fecha_inicio AND prom.fecha_fin),
                    0
                ) as descuento,
                (SELECT precio.valor
                 FROM precio
                 WHERE precio.producto_id = p.id
                 AND (precio.fecha_fin IS NULL OR precio.fecha_fin >= CURRENT_DATE)
                 ORDER BY precio.fecha_inicio DESC
                 LIMIT 1) as precio,
                (SELECT MIN(img.url)
                 FROM imagen img
                 WHERE img.producto_id = p.id
                 LIMIT 1) as imagen_url
            FROM producto p
            WHERE p.activo = TRUE AND (
                -- Productos que son del mismo interés directo del cliente
                p.id IN (SELECT producto_id FROM cliente_intereses WHERE producto_id IS NOT NULL)
                OR 
                -- Productos de las mismas categorías de interés del cliente
                p.categoria_id IN (SELECT categoria_id FROM cliente_intereses WHERE categoria_id IS NOT NULL)
                OR
                -- Si no hay coincidencias, recomendar productos populares
                (NOT EXISTS (SELECT 1 FROM cliente_intereses WHERE producto_id IS NOT NULL OR categoria_id IS NOT NULL))
            )
            ORDER BY 
                -- Priorizar productos con descuento
                descuento DESC,
                -- Priorizar productos que coinciden directamente con intereses
                CASE WHEN p.id IN (SELECT producto_id FROM cliente_intereses WHERE producto_id IS NOT NULL) THEN 1 ELSE 0 END DESC,
                -- Luego priorizar productos de categorías de interés
                CASE WHEN p.categoria_id IN (SELECT categoria_id FROM cliente_intereses WHERE categoria_id IS NOT NULL) THEN 1 ELSE 0 END DESC
            LIMIT %s
        """, (cliente_id, limit))
        
        recomendaciones = []
        for row in cursor.fetchall():
            recomendaciones.append({
                "id": row['id'],
                "nombre": row['nombre'],
                "descripcion": row['descripcion'],
                "precio": float(row['precio']) if row['precio'] else None,
                "descuento": float(row['descuento']) if row['descuento'] else 0,
                "precio_final": float(row['precio'] * (1 - row['descuento']/100)) if row['precio'] and row['descuento'] else (float(row['precio']) if row['precio'] else None),
                "imagen_url": row['imagen_url']
            })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            "cliente_id": cliente_id,
            "recomendaciones": recomendaciones
        })
    
    except Exception as e:
        logger.error(f"Error al obtener recomendaciones para cliente: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/generate_personalized_message', methods=['POST'])
def generate_personalized_message():
    """
    Genera un mensaje personalizado para un cliente basado en sus intereses
    utilizando OpenAI
    """
    try:
        data = request.json
        logger.info(f"Datos recibidos para generar mensaje: {data}")
        cliente_id = data.get('cliente_id')
        template_type = data.get('template_type', 'general')  # 'general', 'promocion', 'seguimiento'
        include_products = data.get('include_products', True)
        
        if not cliente_id:
            return jsonify({"error": "Se requiere cliente_id"}), 400
        
        # Obtener datos del cliente
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("SELECT * FROM cliente WHERE id = %s", (cliente_id,))
        cliente = cursor.fetchone()
        
        if not cliente:
            return jsonify({"error": "Cliente no encontrado"}), 404
        
        # Obtener intereses del cliente
        cursor.execute("""
            SELECT i.*, 
                   p.nombre as producto_nombre,
                   c.nombre as categoria_nombre,
                   pr.nombre as promocion_nombre
            FROM interes i
            LEFT JOIN producto p ON i.producto_id = p.id
            LEFT JOIN categoria c ON i.categoria_id = c.id
            LEFT JOIN promocion pr ON i.promocion_id = pr.id
            WHERE i.cliente_id = %s
            ORDER BY i.nivel_interes DESC, i.fecha_interes DESC
            LIMIT 5
        """, (cliente_id,))
        
        intereses = []
        for row in cursor.fetchall():
            interes_data = {
                "nivel": float(row['nivel_interes']),
                "fecha": row['fecha_interes'].isoformat() if row['fecha_interes'] else None
            }
            
            if row['producto_id']:
                interes_data["tipo"] = "producto"
                interes_data["nombre"] = row['producto_nombre']
                interes_data["id"] = row['producto_id']
            elif row['categoria_id']:
                interes_data["tipo"] = "categoria"
                interes_data["nombre"] = row['categoria_nombre']
                interes_data["id"] = row['categoria_id']
            elif row['promocion_id']:
                interes_data["tipo"] = "promocion"
                interes_data["nombre"] = row['promocion_nombre']
                interes_data["id"] = row['promocion_id']
                
            intereses.append(interes_data)
        
        # Obtener recomendaciones de productos si se solicita
        recomendaciones = []
        if include_products:
            cursor.execute("""
                SELECT p.id, p.nombre, p.descripcion,
                       (SELECT precio.valor
                        FROM precio
                        WHERE precio.producto_id = p.id
                        AND (precio.fecha_fin IS NULL OR precio.fecha_fin >= CURRENT_DATE)
                        ORDER BY precio.fecha_inicio DESC
                        LIMIT 1) as precio,
                       COALESCE(
                           (SELECT MAX(pr.descuento_porcentaje)
                            FROM promo_producto pr
                            JOIN promocion prom ON pr.promocion_id = prom.id
                            WHERE pr.producto_id = p.id
                            AND CURRENT_DATE BETWEEN prom.fecha_inicio AND prom.fecha_fin),
                           0
                       ) as descuento
                FROM producto p
                WHERE p.activo = TRUE
                AND (
                    p.id IN (SELECT producto_id FROM interes WHERE cliente_id = %s AND producto_id IS NOT NULL)
                    OR p.categoria_id IN (SELECT categoria_id FROM interes WHERE cliente_id = %s AND categoria_id IS NOT NULL)
                )
                ORDER BY descuento DESC
                LIMIT 3
            """, (cliente_id, cliente_id))
            
            for row in cursor.fetchall():
                precio_original = float(row['precio']) if row['precio'] else None
                descuento = float(row['descuento']) if row['descuento'] else 0
                precio_final = None
                
                if precio_original is not None:
                    precio_final = precio_original * (1 - descuento/100)
                    
                recomendaciones.append({
                    "id": row['id'],
                    "nombre": row['nombre'],
                    "descripcion": row['descripcion'],
                    "precio_original": precio_original,
                    "descuento": descuento,
                    "precio_final": precio_final
                })
        
        cursor.close()
        conn.close()
        
        # Plantillas según el tipo solicitado
        templates = {
            "general": "Crea un mensaje amistoso para WhatsApp dirigido a un cliente basado en sus intereses. El mensaje debe ser corto, personal y con un llamado a la acción claro.",
            "promocion": "Crea un mensaje promocional para WhatsApp que mencione específicamente descuentos o promociones relevantes para los intereses del cliente. Debe ser breve, atractivo y generar sensación de urgencia.",
            "seguimiento": "Crea un mensaje de seguimiento para WhatsApp que pregunte sobre la experiencia o interés previo del cliente. El mensaje debe ser corto, conversacional y buscar reenganche."
        }
        
        template = templates.get(template_type, templates["general"])
        
        # Preparar el contexto para OpenAI
        nombre_cliente = cliente['nombre']
        intereses_texto = json.dumps(intereses, ensure_ascii=False)
        recomendaciones_texto = json.dumps(recomendaciones, ensure_ascii=False) if recomendaciones else "[]"
        
        # Llamada a OpenAI
        prompt = f"""
        {template}
        
        Datos del cliente:
        - Nombre: {nombre_cliente}
        - Intereses detectados: {intereses_texto}
        - Productos recomendados: {recomendaciones_texto}
        
        El mensaje debe:
        - Ser personalizado usando el nombre del cliente
        - Tener entre 100-200 caracteres
        - Ser amigable y conversacional (apropiado para WhatsApp)
        - Incluir emojis relevantes pero sin exagerar
        - Terminar con un llamado a la acción claro
        
        Si hay productos con descuento, menciona brevemente uno.
        No menciones explícitamente que estás usando sus datos de interés.
        """
        
        response = clientOpenAi.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Eres un asistente de marketing especializado en crear mensajes personalizados para WhatsApp."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.7,
            max_tokens=200
        )
        
        mensaje = response.choices[0].message.content.strip()
        
        return jsonify({
            "cliente_id": cliente_id,
            "nombre_cliente": nombre_cliente,
            "telefono": cliente['telefono'],
            "mensaje_personalizado": mensaje,
            "intereses": intereses,
            "recomendaciones": recomendaciones,
            "tipo_plantilla": template_type
        })
    
    except Exception as e:
        logger.error(f"Error al generar mensaje personalizado: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/send_bulk_personalized_messages', methods=['POST'])
def send_bulk_personalized_messages():
    """
    Endpoint para enviar mensajes personalizados en bloque a clientes con intereses
    """
    try:
        data = request.json
        days = data.get('days', 30)
        min_interest = data.get('min_interest', 0.6)
        template_type = data.get('template_type', 'general')
        test_mode = data.get('test_mode', True)  # Por defecto en modo prueba
        max_clients = data.get('max_clients', 10)  # Limitar número de clientes
        
        # Obtener clientes con intereses
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        
        cursor.execute("""
            SELECT DISTINCT c.id, c.telefono, c.nombre
            FROM cliente c
            JOIN interes i ON c.id = i.cliente_id
            WHERE i.fecha_interes >= NOW() - INTERVAL %s DAY
            AND i.nivel_interes >= %s
            GROUP BY c.id, c.telefono, c.nombre
            ORDER BY MAX(i.nivel_interes) DESC
            LIMIT %s
        """, (days, min_interest, max_clients))
        
        clients = cursor.fetchall()
        cursor.close()
        conn.close()
        
        results = []
        
        for client in clients:
            try:
                # Generar mensaje personalizado (llamada interna)
                mensaje_data = {
                    "cliente_id": client['id'],
                    "template_type": template_type,
                    "include_products": True
                }
                
                # En lugar de hacer una llamada HTTP, podemos llamar directamente a la función
                with app.test_request_context(
                    '/generate_personalized_message',
                    method='POST',
                    json=mensaje_data
                ):
                    response = generate_personalized_message()
                    mensaje_result = json.loads(response.get_data(as_text=True))
                
                # Si no está en modo prueba, enviar el mensaje
                if not test_mode:
                    # Preparar datos para envío
                    whatsapp_number = client['telefono']
                    if not whatsapp_number.startswith('whatsapp:'):
                        whatsapp_number = f"whatsapp:{whatsapp_number}"
                    
                    # Enviar mensaje a través de Twilio
                    message_params = {
                        'from_': f"whatsapp:{TWILIO_PHONE_NUMBER}",
                        'to': whatsapp_number,
                        'body': mensaje_result['mensaje_personalizado']
                    }
                    
                    twilio_message = client.messages.create(**message_params)
                    mensaje_result['sent'] = True
                    mensaje_result['twilio_sid'] = twilio_message.sid
                else:
                    mensaje_result['sent'] = False
                    mensaje_result['test_mode'] = True
                    
                results.append(mensaje_result)
                
            except Exception as e:
                logger.error(f"Error procesando cliente {client['id']}: {e}")
                results.append({
                    "cliente_id": client['id'],
                    "error": str(e),
                    "sent": False
                })
        
        return jsonify({
            "success": True,
            "clients_processed": len(results),
            "test_mode": test_mode,
            "results": results
        })
    
    except Exception as e:
        logger.error(f"Error en envío masivo de mensajes: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Verificación simple del estado de salud del servicio"""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)