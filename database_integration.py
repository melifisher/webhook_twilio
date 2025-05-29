import psycopg2
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
import json
from config import config
from chatbot_system import EmbeddingGenerator, VectorStore, ProductInfo;
from advertisement_generator import AdvertisementGenerator;
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_config: Dict[str, str]):
        self.db_config = db_config
        self.connection = None

    def connect(self):
        try:
            self.connection = psycopg2.connect(
                host=self.db_config.host,
                database=self.db_config.database,
                user=self.db_config.user,
                password=self.db_config.password,
                port=self.db_config.port
            )
            self.connection.autocommit = True
            print("Database connection established")
        except Exception as e:
            print(f"Error connecting to database: {e}")
            raise

    def disconnect(self):
        if self.connection:
            self.connection.close()

    # === Producto metodos ===
    def extract_products_data(self) -> List[ProductInfo]:
        query = """SELECT 
            p.id,
            p.nombre,
            p.descripcion,
            p.activo,
            c.id as categoria_id,
            c.nombre as categoria_nombre,
            c.descripcion as categoria_descripcion,
            lp.nombre as lista_precios_nombre,
            pr.valor as precio_valor,
            pr.fecha_inicio as precio_fecha_inicio,
            pr.fecha_fin as precio_fecha_fin
        FROM producto p
        LEFT JOIN categoria c ON p.categoria_id = c.id
        LEFT JOIN precio pr ON p.id = pr.producto_id
        LEFT JOIN lista_precios lp ON pr.lista_precios_id = lp.id
        WHERE p.activo = TRUE
        ORDER BY p.id, pr.fecha_inicio DESC;"""

        cursor = self.connection.cursor()
        cursor.execute(query)
        results = cursor.fetchall()

        products_dict = {}
        for row in results:
            product_id = row[0]
            if product_id not in products_dict:
                products_dict[product_id] = {
                    'id': row[0],
                    'nombre': row[1],
                    'descripcion': row[2] or "",
                    'activo': row[3],
                    'categoria_id': row[4] or 0,
                    'categoria': row[5] or "",
                    'categoria_descripcion': row[6] or "",
                    'precios': [],
                    'promociones': [],
                    'imagenes': []
                }
            if row[7]:
                precio_info = {
                    'lista_precios': row[7],
                    'valor': float(row[8]) if row[8] else 0,
                    'fecha_inicio': row[9],
                    'fecha_fin': row[10]
                }
                if precio_info not in products_dict[product_id]['precios']:
                    products_dict[product_id]['precios'].append(precio_info)

        for product_id in products_dict.keys():
            products_dict[product_id]['promociones'] = self._get_product_promotions(product_id)
            products_dict[product_id]['imagenes'] = self._get_product_images(product_id)

        products = []
        for data in products_dict.values():
            current_price = 0
            current_lista = "Sin lista de precios"
            if data['precios']:
                current_date = date.today()
                valid_prices = [p for p in data['precios']
                                if p['fecha_inicio'] <= current_date and
                                (p['fecha_fin'] is None or p['fecha_fin'] >= current_date)]
                selected_price = valid_prices[0] if valid_prices else data['precios'][0]
                current_price = selected_price['valor']
                current_lista = selected_price['lista_precios']

            products.append(ProductInfo(
                id=data['id'],
                nombre=data['nombre'],
                descripcion=data['descripcion'],
                categoria_id=data['categoria_id'],
                categoria=data['categoria'],
                categoria_descripcion=data['categoria_descripcion'],
                precio_actual=current_price,
                lista_precios=current_lista,
                promociones=data['promociones'],
                imagenes=data['imagenes'],
                activo=data['activo']
            ))

        cursor.close()
        return products

    def _get_product_promotions(self, product_id: int) -> List[Dict]:
        query = """ SELECT 
                pr.id,
                pr.nombre,
                pr.descripcion,
                pr.fecha_inicio,
                pr.fecha_fin,
                pp.descuento_porcentaje
            FROM promocion pr
            JOIN promo_producto pp ON pr.id = pp.promocion_id
            WHERE pp.producto_id = %s
            AND pr.fecha_inicio <= CURRENT_DATE
            AND (pr.fecha_fin IS NULL OR pr.fecha_fin >= CURRENT_DATE);"""
        cursor = self.connection.cursor()
        cursor.execute(query, (product_id,))
        results = cursor.fetchall()
        cursor.close()
        return [{
            'id': row[0],
            'nombre': row[1],
            'descripcion': row[2] or "",
            'fecha_inicio': row[3],
            'fecha_fin': row[4],
            'descuento_porcentaje': float(row[5]) if row[5] else 0
        } for row in results]

    def _get_product_images(self, product_id: int) -> List[str]:
        query = """SELECT url, descripcion
        FROM imagen
        WHERE producto_id = %s;""" 
        cursor = self.connection.cursor()
        cursor.execute(query, (product_id,))
        results = cursor.fetchall()
        cursor.close()
        return [{"url": row[0], "descripcion": row[1] or ""} for row in results]

    # === Chat metodos ===
    def get_or_create_client(self, telefono: str, nombre: str = None, correo: str = None) -> int:
        cursor = self.connection.cursor()
        cursor.execute("SELECT id FROM cliente WHERE telefono = %s", (telefono,))
        result = cursor.fetchone()
        if result:
            client_id = result[0]
        else:
            nombre = nombre or f"Cliente_{telefono}"
            cursor.execute(
                "INSERT INTO cliente (telefono, nombre, correo) VALUES (%s, %s, %s) RETURNING id",
                (telefono, nombre, correo)
            )
            client_id = cursor.fetchone()[0]
            print(f"Created new client with ID: {client_id}")
        cursor.close()
        return client_id

    def get_or_create_conversation(self, client_id: int, descripcion: str = None) -> int:
        cursor = self.connection.cursor()
        today = date.today()
        cursor.execute("""
            SELECT id FROM conversacion WHERE cliente_id = %s AND fecha = %s 
            ORDER BY id DESC LIMIT 1
        """, (client_id, today))
        result = cursor.fetchone()
        if result:
            conversation_id = result[0]
        else:
            descripcion = descripcion or f"Conversación del {today}"
            cursor.execute("""
                INSERT INTO conversacion (fecha, descripcion, cliente_id)
                VALUES (%s, %s, %s) RETURNING id
            """, (today, descripcion, client_id))
            conversation_id = cursor.fetchone()[0]
            print(f"Created new conversation with ID: {conversation_id}")
        cursor.close()
        return conversation_id

    def save_message(self, conversation_id: int, tipo: str, contenido_texto: str,
                     is_bot: bool, media_url: str = None, media_mimetype: str = None,
                     media_filename: str = None):
        cursor = self.connection.cursor()
        cursor.execute("""
            INSERT INTO mensaje (tipo, contenido_texto, media_url, media_mimetype,
                                 media_filename, fecha, isBot, conversacion_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (tipo, contenido_texto, media_url, media_mimetype, media_filename,
              datetime.now(), is_bot, conversation_id))
        cursor.close()
        logger.info(f"Message saved: {tipo}, is_bot: {is_bot}, conversation_id: {conversation_id}")

    def get_conversation_history(self, conversation_id: int, limit: int = 20) -> List[Dict]:
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT tipo, contenido_texto, fecha, isBot, media_url
            FROM mensaje 
            WHERE conversacion_id = %s 
            ORDER BY fecha DESC 
            LIMIT %s
        """, (conversation_id, limit))
        results = cursor.fetchall()
        cursor.close()
        return [{
            'tipo': row[0],
            'contenido_texto': row[1],
            'fecha': row[2],
            'is_bot': row[3],
            'media_url': row[4]
        } for row in reversed(results)]

    def get_client_conversations(self, client_id: int) -> List[Dict]:
        cursor = self.connection.cursor()
        cursor.execute(
        """
            SELECT c.id, c.fecha, c.descripcion, COUNT(m.id) as message_count
            FROM conversacion c
            LEFT JOIN mensaje m ON c.id = m.conversacion_id
            WHERE c.cliente_id = %s
            GROUP BY c.id, c.fecha, c.descripcion
            ORDER BY c.fecha DESC
        """, (client_id,))
        results = cursor.fetchall()
        cursor.close()
        return [{
            'id': row[0],
            'fecha': row[1],
            'descripcion': row[2],
            'message_count': row[3]
        } for row in results]
    
    def get_messages_for_analize(self, cliente_id) -> List[Dict]:
        cursor = self.connection.cursor()
        cursor.execute("""
            SELECT m.conversacion_id, m.id as mensaje_id, m.contenido_texto, m.isbot
            FROM mensaje m
            JOIN conversacion c ON m.conversacion_id = c.id
            WHERE c.cliente_id = %s
            AND m.contenido_texto IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM interes i WHERE i.conversacion_id = c.id
            )
        """, (cliente_id,))
        messages = cursor.fetchall()
        cursor.close()
        if not messages:
            return []
        
        return messages
    
    def save_conversation_intents(self, intents):
        cursor = self.connection.cursor()
        try:
            for intent in intents:
                cursor.execute("""
                    INSERT INTO interes (conversacion_id, tipo_interes, entidad_id, entidad_nombre, nivel_interes, contexto, fecha_creacion)
                    VALUES (%s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT DO NOTHING
                    RETURNING id
                """, (
                    intent['conversacion_id'],
                    intent['tipo_interes'], 
                    intent['entidad_id'],
                    intent.get('entidad_nombre', ''),
                    intent['nivel_interes'],
                    intent.get('contexto', '')
                ))
                result = cursor.fetchone()
                if result:
                    logger.info(f"Interés almacenado con ID: {result[0]}")
                else:
                    logger.info("No se insertó el interés (posible duplicado)")
            cursor.close()
            return True
        except Exception as e:
            logger.error(f"Error en save_conversation_intents: {e}")
            return False
    
    def get_clients_with_interests(self, min_interest_level: float = 0.5, 
                                 days_back: int = 30) -> List[Dict]:
        """
        Get clients with their top interests from the last N days
        """
        cursor = self.connection.cursor()
        query = """
        SELECT DISTINCT
            c.id as cliente_id,
            c.telefono,
            c.nombre,
            c.correo,
            i.tipo_interes,
            i.entidad_id,
            i.entidad_nombre,
            i.nivel_interes,
            i.contexto,
            ROW_NUMBER() OVER (PARTITION BY c.id ORDER BY i.nivel_interes DESC) as rn
        FROM cliente c
        JOIN conversacion conv ON c.id = conv.cliente_id
        JOIN interes i ON conv.id = i.conversacion_id
        WHERE i.nivel_interes >= %s
        AND i.fecha_creacion >= %s
        ORDER BY c.id, i.nivel_interes DESC
        """
        
        cutoff_date = datetime.now() - timedelta(days=days_back)
        
        cursor.execute(query, (min_interest_level, cutoff_date))
        results = cursor.fetchall()
        cursor.close()
        logger.info(f"clientes result: {results}")
        # Group by client and get top 3 interests per client
        clients_dict = {}
        for row in results:
            client_id = row[0]
            if client_id not in clients_dict:
                clients_dict[client_id] = {
                    'cliente_id': client_id,
                    'telefono': row[1],
                    'nombre': row[2],
                    'correo': row[3],
                    'interests': []
                }
            
            # Add interest if we have less than 3 for this client
            if len(clients_dict[client_id]['interests']) < 3:
                clients_dict[client_id]['interests'].append({
                    'tipo_interes': row[4],
                    'entidad_id': row[5],
                    'entidad_nombre': row[6],
                    'nivel_interes': float(row[7]),
                    'contexto': row[8]
                })
        
        return list(clients_dict.values())
    
class ConversationalBot:
    def __init__(self, vector_store, embedding_generator, db_manager=None):
        self.client = OpenAI()
        self.vector_store = vector_store
        self.embedding_generator = embedding_generator
        self.db_manager = db_manager
        self.conversation_history = {}
        
    def get_relevant_products(self, query: str, k: int = 3) -> List[Dict]:
        """Get relevant products based on query"""
        response = self.client.embeddings.create(
            input=query,
            model=self.embedding_generator.model
        )
        query_embedding = response.data[0].embedding
        results = self.vector_store.search(query_embedding, k)
        return results
    
    def update_conversation_context(self, client_id: int, message: str, is_bot: bool = False):
        """Update conversation context for a client"""
        if client_id not in self.conversation_history:
            self.conversation_history[client_id] = []
        
        self.conversation_history[client_id].append({
            'message': message,
            'is_bot': is_bot,
            'timestamp': datetime.now()
        })
        
        if len(self.conversation_history[client_id]) > 10:
            self.conversation_history[client_id] = self.conversation_history[client_id][-10:]
    
    def get_conversation_context(self, client_id: int) -> str:
        """Get conversation context as string"""
        if client_id not in self.conversation_history:
            return ""
        
        context_parts = []
        for entry in self.conversation_history[client_id]:
            role = "Bot" if entry['is_bot'] else "Cliente"
            context_parts.append(f"{role}: {entry['message']}")
        
        return "\n".join(context_parts)
    
    def generate_response(self, client_id: int, user_message: str) -> str:
        """Generate response using context and relevant products"""
        self.update_conversation_context(client_id, user_message, is_bot=False)
        context = self.get_conversation_context(client_id)
        relevant_products = self.get_relevant_products(user_message)
        
        products_info = []
        for result in relevant_products:
            product = result['metadata']['product_data']
            info = f"- {product['nombre']}: ${product['precio_actual']:.2f}"
            if product['descripcion']:
                info += f" - {product['descripcion']}"
            if product['promociones']:
                promos = [f"{p['nombre']} ({p['descuento_porcentaje']}% desc.)" for p in product['promociones']]
                info += f" | Promociones: {', '.join(promos)}"
            products_info.append(info)
        
        products_context = "\n".join(products_info) if products_info else "No se encontraron productos relevantes."
        
        system_prompt = f"""
        Eres un asistente de ventas para una tienda online de libros. Tu trabajo es ayudar a los clientes con información sobre productos, precios, promociones y realizar ventas.

        CONTEXTO DE LA CONVERSACIÓN:
        {context}

        PRODUCTOS RELEVANTES:
        {products_context}

        INSTRUCCIONES:
        1. Mantén el contexto de la conversación - si el cliente preguntó sobre un producto específico, recuerda cuál es
        2. Proporciona información precisa sobre precios, promociones y categorías
        3. Sé amigable y útil
        4. Si el cliente pregunta sobre precios, especifica a qué producto te refieres
        5. Sugiere productos relacionados cuando sea apropiado
        6. Si no tienes información específica, sé honesto al respecto
        """
        
        try:
            response = self.client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message}
                ],
                max_tokens=500,
                temperature=0.7
            )
            bot_response = response.choices[0].message.content.strip()
            self.update_conversation_context(client_id, bot_response, is_bot=True)
            return bot_response
        except Exception as e:
            return f"Lo siento, ha ocurrido un error. Por favor intenta de nuevo. Error: {str(e)}"

    def process_client_message(self, telefono: str, mensaje: str, nombre: str = None) -> Dict:
        """Procesa el mensaje del cliente y devuelve una respuesta con almacenamiento opcional en la base de datos"""
        if not self.db_manager:
            return {
                'success': False,
                'error': "Database manager not configured.",
                'response': "Error interno del sistema. Por favor intenta más tarde."
            }

        try:
            client_id = self.db_manager.get_or_create_client(telefono, nombre)
            conversation_id = self.db_manager.get_or_create_conversation(client_id)
            
            self.db_manager.save_message(
                conversation_id=conversation_id,
                tipo="text",
                contenido_texto=mensaje,
                is_bot=False
            )
            
            db_history = self.db_manager.get_conversation_history(conversation_id)
            self.conversation_history[client_id] = []
            for msg in db_history:
                self.conversation_history[client_id].append({
                    'message': msg['contenido_texto'],
                    'is_bot': msg['is_bot'],
                    'timestamp': msg['fecha']
                })
            
            bot_response = self.generate_response(client_id, mensaje)
            
            logger.info(f"Client {client_id} sent message: {mensaje}")

            self.db_manager.save_message(
                conversation_id=conversation_id,
                tipo="text",
                contenido_texto=bot_response,
                is_bot=True
            )
            
            return {
                'success': True,
                'response': bot_response,
                'client_id': client_id,
                'conversation_id': conversation_id
            }
        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            print(error_msg)
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg,
                'response': "Lo siento, ha ocurrido un error procesando tu mensaje."
            }

    def analyze_conversation_intent(self, cliente_id: int, k: int = 15):
        """
        Analiza las intenciones de todas las conversaciones de un cliente
        que aún no han sido analizadas
        """
        try:
            # Obtener mensajes sin analizar
            messages = self.db_manager.get_messages_for_analize(cliente_id)
            # logger.info(f"messages: {messages}")
            if not messages:
                return []
            
            # Agrupar mensajes por conversación
            conversations = {}
            for msg in messages:
                conv_id = msg[0]  # conversacion_id
                if conv_id not in conversations:
                    conversations[conv_id] = []
                conversations[conv_id].append({
                    'mensaje_id': msg[1],
                    'contenido': msg[2],
                    'isbot': msg[3]
                })
            
            all_intents = []
            
            # Analizar cada conversación
            for conversacion_id, msgs in conversations.items():
                # Combinar todos los mensajes del usuario (no bot) de la conversación
                user_messages = [msg['contenido'] for msg in msgs if not msg['isbot']]
                
                if not user_messages:
                    continue
                
                # Crear un texto combinado de la conversación
                conversation_text = " ".join(user_messages)
                
                # Obtener productos relevantes usando embeddings
                relevant_products = self.get_relevant_products(conversation_text, k)
                
                if not relevant_products:
                    continue
                
                # Preparar información de productos relevantes
                productos_info = []
                for result in relevant_products:
                    product = result['metadata']['product_data']
                   
                    info = {
                        'id': product['id'],
                        'nombre': product['nombre'],
                        'descripcion': product.get('descripcion', ''),
                        'categoria_id': product['categoria_id'],
                        'categoria': product.get('categoria', ''),
                        'precio': product.get('precio_actual', 0),
                        'promociones': product.get('promociones', [])
                    }
                    productos_info.append(info)
                
                # Construir contexto de la conversación completa
                conversation_context = []
                for msg in msgs:
                    role = "Bot" if msg['isbot'] else "Cliente"
                    conversation_context.append(f"{role}: {msg['contenido']}")
                
                conversation_str = "\n".join(conversation_context)
                
                # Construir string de productos para el prompt
                productos_str = "\n".join([
                    f"ID: {p['id']}, Nombre: {p['nombre']}, Descripción: {p['descripcion']}, Categoría: {p['categoria']}" 
                    for p in productos_info
                ])
                
                # Extraer categorías únicas y promociones
                categorias_unicas = {}
                promociones_unicas = {}
                prods_promo = {}
                categorias_str = ""
                for p in productos_info:
                    if p['categoria_id'] and p['categoria_id'] not in categorias_unicas:
                        categorias_unicas[p['categoria_id']] = p['categoria']
                        categorias_str += f"Id: {p['categoria_id']}, Nombre: {p['categoria']}"
                    if p['promociones']:
                        for promo in p['promociones']:
                            if prods_promo.get(promo['id']) is None:
                                prods_promo[promo['id']] = f"Producto: {p['nombre']} - {promo.get('descuento_porcentaje', 0)}%, "
                            else:
                                prods_promo[promo['id']] += f"Producto: {p['nombre']} - {promo.get('descuento_porcentaje', 0)}%, "
                            promociones_unicas[promo['id']] = {
                                'id': promo['id'],
                                'nombre': promo['nombre'],
                                'productos_descuento': prods_promo[promo['id']],
                                'descripcion': promo.get('descripcion', '')
                            }
                logger.info(f"categorias_unicas: {categorias_unicas}")
                logger.info(f"promociones_unicas: {promociones_unicas}")

                promociones_str = "\n".join([
                    f"Id: {promo['id']}, Nombre: {promo.get('nombre', '')}, Descripción: {promo.get('descripcion', '')}, Descuentos: {promo.get('productos_descuento', '')}"
                    for promo in promociones_unicas.values()
                ])
                
                
                
                # Preparar el prompt para OpenAI
                prompt = f"""
                Analiza la siguiente conversación completa entre un cliente y un bot de ventas para detectar intenciones de interés en productos, categorías o promociones.
                
                CONVERSACIÓN COMPLETA:
                {conversation_str}
                
                Productos relevantes encontrados:
                {productos_str}
                
                Categorías disponibles:
                {categorias_str}
                
                Promociones activas:
                {promociones_str}
                
                Analiza toda la conversación en conjunto para detectar patrones de interés. Considera:
                - Productos específicos mencionados o preguntados directamente por el cliente
                - Categorías de interés mostradas
                - Promociones consultadas
                - Intenciones implícitas basadas en el contexto completo
                
                Responde con un JSON que contenga un array de intereses detectados, donde cada interés debe incluir:
                1. tipo_interes: "producto", "categoria" o "promocion"
                2. entidad_id: el ID numérico del producto, categoría o promoción
                3. nivel_interes: un valor entre 0 y 1 que indique el nivel de confianza en el interés basado en toda la conversación
                4. entidad_nombre: el nombre del producto, categoría o promoción
                5. contexto: una breve explicación de por qué se detectó este interés
                
                Si no se detecta interés, devuelve un array vacío.
                Ejemplo de formato de respuesta:
                {{"intereses": [
                    {{"tipo_interes": "producto", "entidad_id": 5, "nivel_interes": 0.9, "entidad_nombre": "Libro de Python", "contexto": "Cliente preguntó específicamente por libros de programación de Python"}},
                    {{"tipo_interes": "categoria", "entidad_id": 10, "entidad_nombre": "Tecnología", "nivel_interes": 0.7, "contexto": "Mostró interés general en libros de tecnología"}}
                ]}}
                
                Solo responde con el objeto JSON, sin texto adicional.
                """
                logger.info(f"prompt: {prompt}")
                # Llamada a la API de OpenAI
                response = self.client.chat.completions.create(
                    model="gpt-3.5-turbo",
                    messages=[
                        {"role": "system", "content": "Eres un sistema de análisis de intenciones para un e-commerce de libros. Analiza conversaciones completas para detectar patrones de interés."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=1000
                )
                
                # Extraer y procesar la respuesta
                result_text = response.choices[0].message.content.strip()
                
                try:
                    import re
                    import json
                    
                    # Buscar el JSON en la respuesta
                    json_match = re.search(r'({[\s\S]*})', result_text)
                    if json_match:
                        result_text = json_match.group(1)
                    
                    result = json.loads(result_text)
                    
                    # Verificar formato y agregar conversacion_id
                    intents = result.get('intereses', [])
                    if isinstance(result, list):
                        intents = result
                    
                    # Agregar conversacion_id a cada interés
                    for intent in intents:
                        intent['conversacion_id'] = conversacion_id
                    
                    all_intents.extend(intents)
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Error al decodificar JSON de OpenAI para conversación {conversacion_id}: {e}, respuesta: {result_text}")
                    continue
            
            return all_intents
            
        except Exception as e:
            logger.error(f"Error en análisis de intenciones de conversación: {e}")
            return []

    def process_client_conversation_intents(self, cliente_id: int):
        """
        Procesa y guarda los intereses de todas las conversaciones de un cliente
        """
        try:
            # Analizar intenciones
            intents = self.analyze_conversation_intent(cliente_id)
            
            if not intents:
                logger.info(f"No se encontraron intenciones para el cliente {cliente_id}")
                return []
            
            # Guardar en base de datos
            if self.db_manager.save_conversation_intents(intents):
                logger.info(f"Se guardaron {len(intents)} intenciones para el cliente {cliente_id}")
                return intents
            else:
                logger.error(f"Error al guardar intenciones para el cliente {cliente_id}")
                return []
                
        except Exception as e:
            logger.error(f"Error procesando intenciones del cliente {cliente_id}: {e}")
            return []

# pa pruebas
class WhatsAppBotAPI:
    def __init__(self, bot: ConversationalBot):
        self.bot = bot
    
    def webhook_handler(self, webhook_data: Dict) -> Dict:
        """Handle incoming WhatsApp webhook"""
        try:
            telefono = webhook_data.get('from', '')
            mensaje = webhook_data.get('text', {}).get('body', '')
            nombre = webhook_data.get('profile', {}).get('name', '')
            
            if not telefono or not mensaje:
                return {'success': False, 'error': 'Missing required data'}
            
            result = self.bot.process_client_message(telefono, mensaje, nombre)
            
            if result['success']:
                print('response:', result['response'])
            
            return result
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

# Hacer el embedding
def setup_complete_system():
    """Complete setup of the e-commerce chatbot system"""
    
    print("Setting up complete e-commerce chatbot system...")
    
    # 1. Extract and generate embeddings
    try:
        # Load existing embeddings or create new ones
        embedding_gen = EmbeddingGenerator()
        
        try:
            embeddings_data = embedding_gen.load_embeddings(config.files.embeddings_file)
            print("Loaded existing embeddings")
        except FileNotFoundError:
            print("Creating new embeddings...")
            extractor = DatabaseManager(config.database)
            extractor.connect()
            products = extractor.extract_products_data()
            extractor.disconnect()
            
            embeddings_data = embedding_gen.generate_embeddings(products)
            embedding_gen.save_embeddings(embeddings_data, config.files.embeddings_file)
        
        # 2. Setup vector store
        vector_store = VectorStore()
        try:
            vector_store.load_index(config.files.vector_index_path)
            print("Loaded existing vector index")
        except:
            print("Creating new vector index...")
            vector_store.add_embeddings(embeddings_data)
            vector_store.save_index(config.files.vector_index_path)
        
        # 3. Setup database manager
        db_manager = DatabaseManager(config.database)
        db_manager.connect()
        
        # 4. Create enhanced bot
        bot = ConversationalBot(vector_store, embedding_gen, db_manager)

        # 5. 
        add_generator = AdvertisementGenerator(vector_store, embedding_gen, db_manager)

        print("System setup complete!")
        return bot, db_manager, add_generator
        # api_handler, 
        
    except Exception as e:
        print(f"Error setting up system: {e}")
        return None, None, None


# Actualizar los embeddings
def update_product_embeddings():
    """Update product embeddings"""
    print("Updating product embeddings...")
    
    db_config = {
        'host': 'localhost',
        'database': 'ecommerce',
        'user': 'your_user',
        'password': 'your_password'
    }
    
    
    try:
        # Extract fresh data
        extractor = DatabaseManager(config.database)
        extractor.connect()
        products = extractor.extract_products_data()
        extractor.disconnect()
        
        # Generate new embeddings
        embedding_gen = EmbeddingGenerator()
        embeddings_data = embedding_gen.generate_embeddings(products)
        
        # Save embeddings
        embedding_gen.save_embeddings(embeddings_data, config.files.embeddings_file)
        
        # Update vector store
        vector_store = VectorStore()
        vector_store.add_embeddings(embeddings_data)
        vector_store.save_index(config.files.vector_index_path)
        
        print(f"Successfully updated embeddings for {len(products)} products")
        
    except Exception as e:
        print(f"Error updating embeddings: {e}")

def test_conversation_flow():
    """Test the complete conversation flow"""
    print("\n=== PROBANDO LA CONVERSACION ===")
    
    bot, api_handler, db_manager = setup_complete_system()
    if not bot:
        print("Failed to setup system")
        return
    
    # Simulate WhatsApp messages
    test_messages = [
        {
            'from': '+1234567890',
            'text': {'body': 'Hola, busco un libro de Gabriel García Márquez'},
            'profile': {'name': 'Juan Pérez'}
        },
        {
            'from': '+1234567890',
            'text': {'body': '¿Cuál es el precio?'},
            'profile': {'name': 'Juan Pérez'}
        },
        {
            'from': '+1234567890',
            'text': {'body': '¿Hay promociones disponibles?'},
            'profile': {'name': 'Juan Pérez'}
        },
        {
            'from': '+1234567890',
            'text': {'body': 'Me interesa también los libros de No Ficción'},
            'profile': {'name': 'Juan Pérez'}
        },
        {
            'from': '+1234567890',
            'text': {'body': '¿Cuánto cuesta el libro de No Ficción más barato?'},
            'profile': {'name': 'Juan Pérez'}
        }
    ]
    
    print("\nSimulating conversation:")
    for i, msg_data in enumerate(test_messages, 1):
        user_msg = msg_data['text']['body']
        print(f"\n--- Message {i} ---")
        print(f"Usuario: {user_msg}")
        
        result = api_handler.webhook_handler(msg_data)
        if result['success']:
            print(f"Bot: {result['response']}")
        else:
            print(f"Error: {result['error']}")
        
        # Small delay to simulate real conversation
        import time
        time.sleep(1)
    
    # Show conversation history from database
    print("\n=== CONVERSATION HISTORY FROM DATABASE ===")
    try:
        client_id = db_manager.get_or_create_client('+1234567890')
        conversations = db_manager.get_client_conversations(client_id)
        
        for conv in conversations:
            print(f"\nConversation {conv['id']} - {conv['fecha']}")
            print(f"Description: {conv['descripcion']}")
            print(f"Messages: {conv['message_count']}")
            
            messages = db_manager.get_conversation_history(conv['id'])
            for msg in messages[-5:]:  # Show last 5 messages
                role = "Bot" if msg['is_bot'] else "Cliente"
                print(f"  {role}: {msg['contenido_texto']}")
    
    except Exception as e:
        print(f"Error retrieving conversation history: {e}")
    
    finally:
        db_manager.disconnect()

# Analytics and Reporting
class ChatAnalytics:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def get_conversation_stats(self, days: int = 30) -> Dict:
        """Get conversation statistics"""
        cursor = self.db_manager.connection.cursor()
        
        # Total conversations in last N days
        cursor.execute("""
            SELECT COUNT(*) FROM conversacion 
            WHERE fecha >= CURRENT_DATE - INTERVAL '%s days'
        """, (days,))
        total_conversations = cursor.fetchone()[0]
        
        # Total messages in last N days
        cursor.execute("""
            SELECT COUNT(*) FROM mensaje m
            JOIN conversacion c ON m.conversacion_id = c.id
            WHERE c.fecha >= CURRENT_DATE - INTERVAL '%s days'
        """, (days,))
        total_messages = cursor.fetchone()[0]
        
        # Active clients in last N days
        cursor.execute("""
            SELECT COUNT(DISTINCT c.cliente_id) FROM conversacion c
            WHERE c.fecha >= CURRENT_DATE - INTERVAL '%s days'
        """, (days,))
        active_clients = cursor.fetchone()[0]
        
        # Most common message types
        cursor.execute("""
            SELECT m.tipo, COUNT(*) as count FROM mensaje m
            JOIN conversacion c ON m.conversacion_id = c.id
            WHERE c.fecha >= CURRENT_DATE - INTERVAL '%s days'
            GROUP BY m.tipo
            ORDER BY count DESC
        """, (days,))
        message_types = cursor.fetchall()
        
        cursor.close()
        
        return {
            'period_days': days,
            'total_conversations': total_conversations,
            'total_messages': total_messages,
            'active_clients': active_clients,
            'avg_messages_per_conversation': total_messages / max(total_conversations, 1),
            'message_types': dict(message_types)
        }
    
    def get_popular_queries(self, limit: int = 10) -> List[Dict]:
        """Get most common user queries"""
        cursor = self.db_manager.connection.cursor()
        
        cursor.execute("""
            SELECT m.contenido_texto, COUNT(*) as frequency
            FROM mensaje m
            JOIN conversacion c ON m.conversacion_id = c.id
            WHERE m.isBot = FALSE 
            AND m.contenido_texto IS NOT NULL
            AND LENGTH(m.contenido_texto) > 5
            AND c.fecha >= CURRENT_DATE - INTERVAL '30 days'
            GROUP BY m.contenido_texto
            ORDER BY frequency DESC
            LIMIT %s
        """, (limit,))
        
        results = cursor.fetchall()
        cursor.close()
        
        return [{'query': row[0], 'frequency': row[1]} for row in results]


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "setup":
            setup_complete_system()
        elif command == "test":
            test_conversation_flow()
        elif command == "update_embeddings":
            update_product_embeddings()
        elif command == "server":
            bot, api_handler, db_manager = setup_complete_system()
            if bot:
                app = create_webhook_server(api_handler)
                print("Starting webhook server on port 5000...")
                app.run(host='0.0.0.0', port=5000, debug=True)
        else:
            print("Unknown command. Use: setup, test, update_embeddings, or server")
    else:
        print("Usage:")
        print("  python script.py setup - Setup the complete system")
        print("  python script.py update_embeddings - Update product embeddings")
        print("  python script.py server - Start webhook server")