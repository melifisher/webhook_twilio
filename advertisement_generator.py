from PIL import Image, ImageDraw, ImageFont
from dataclasses import dataclass
from typing import List, Dict, Optional
import requests
from io import BytesIO
import textwrap
from datetime import datetime
from chatbot_system import ProductInfo;
from openai import OpenAI

class AdvertisementGenerator:
    def __init__(self, vector_store, embedding_generator, db_manager=None):
        self.client = OpenAI()
        self.vector_store = vector_store
        self.embedding_generator = embedding_generator
        self.db_manager = db_manager
    
    def get_relevant_products(self, query: str, k: int = 3) -> List[Dict]:
        """Get relevant products based on query"""
        response = self.client.embeddings.create(
            input=query,
            model=self.embedding_generator.model
        )
        query_embedding = response.data[0].embedding
        results = self.vector_store.search(query_embedding, k)
        return results
    
    def create_product_advertisement(self, product: ProductInfo, 
                                output_path: str = None,
                                width: int = 800, 
                                height: int = 600,
                                background_color: str = "#f8f9fa") -> Image.Image:
        """
        Creates a promotional image for a product with discounts and promotions.
        
        Args:
            product: ProductInfo object containing product details
            output_path: Path to save the image (optional)
            width: Image width in pixels
            height: Image height in pixels
            background_color: Background color in hex format
        
        Returns:
            PIL Image object
        """
        
        # Create image and drawing context
        img = Image.new('RGB', (width, height), background_color)
        draw = ImageDraw.Draw(img)
        
        # Try to load fonts (fallback to default if not available)
        try:
            title_font = ImageFont.truetype("arial.ttf", 36)
            subtitle_font = ImageFont.truetype("arial.ttf", 24)
            text_font = ImageFont.truetype("arial.ttf", 18)
            price_font = ImageFont.truetype("arial.ttf", 32)
            discount_font = ImageFont.truetype("arial.ttf", 28)
        except:
            title_font = ImageFont.load_default()
            subtitle_font = ImageFont.load_default()
            text_font = ImageFont.load_default()
            price_font = ImageFont.load_default()
            discount_font = ImageFont.load_default()
        
        # Color scheme
        primary_color = "#2563eb"
        accent_color = "#dc2626"
        text_color = "#1f2937"
        white = "#ffffff"
        
        # Current Y position for drawing elements
        current_y = 30
        
        # Draw product image if available
        product_img = None
        if product.imagenes and len(product.imagenes) > 0:
            try:
                # Try to load the first image
                if product.imagenes[0]["url"].startswith('http'):
                    response = requests.get(product.imagenes[0]["url"])
                    product_img = Image.open(BytesIO(response.content))
                else:
                    product_img = Image.open(product.imagenes[0]["url"])
                
                # Resize and position product image
                img_size = min(width // 3, height // 2)
                product_img = product_img.resize((img_size, img_size), Image.Resampling.LANCZOS)
                img.paste(product_img, (width - img_size - 30, 30))
                
            except Exception as e:
                print(f"Could not load product image: {e}")
        
        # Draw title
        title_text = product.nombre.upper()
        title_bbox = draw.textbbox((0, 0), title_text, font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        
        if title_width > width - 300:  # Leave space for product image
            # Wrap title if too long
            wrapped_title = textwrap.fill(title_text, width=30)
            draw.multiline_text((30, current_y), wrapped_title, fill=primary_color, font=title_font)
            current_y += 80
        else:
            draw.text((30, current_y), title_text, fill=primary_color, font=title_font)
            current_y += 50
        
        # Draw category
        category_text = f"Categoría: {product.categoria}"
        draw.text((30, current_y), category_text, fill=text_color, font=text_font)
        current_y += 30
        
        # Draw description
        if product.descripcion:
            desc_lines = textwrap.fill(product.descripcion, width=50).split('\n')
            for line in desc_lines[:3]:  # Limit to 3 lines
                draw.text((30, current_y), line, fill=text_color, font=text_font)
                current_y += 25
            current_y += 10
        
        # Draw price
        price_text = f"${product.precio_actual:,.2f}"
        draw.text((30, current_y), price_text, fill=primary_color, font=price_font)
        current_y += 50
        
        # Draw promotions and discounts
        if product.promociones:
            for promo in product.promociones:
                # Create promotion box
                promo_box_height = 120
                promo_box = Image.new('RGB', (width - 60, promo_box_height), accent_color)
                promo_draw = ImageDraw.Draw(promo_box)
                
                # Promotion title
                promo_name = promo.get('nombre', 'PROMOCIÓN ESPECIAL')
                promo_draw.text((20, 10), promo_name.upper(), fill=white, font=subtitle_font)
                
                # Discount percentage
                if 'descuento_porcentaje' in promo and promo['descuento_porcentaje']:
                    discount_text = f"{promo['descuento_porcentaje']}% OFF"
                    promo_draw.text((20, 40), discount_text, fill=white, font=discount_font)
                
                # Promotion description
                if 'descripcion' in promo and promo['descripcion']:
                    desc_text = textwrap.fill(promo['descripcion'], width=60)
                    promo_draw.text((20, 75), desc_text, fill=white, font=text_font)
                
                # Dates
                if 'fecha_inicio' in promo and 'fecha_fin' in promo:
                    date_text = f"Válido: {promo['fecha_inicio']} - {promo['fecha_fin']}"
                    promo_draw.text((width - 350, 85), date_text, fill=white, font=text_font)
                
                # Paste promotion box onto main image
                img.paste(promo_box, (30, current_y))
                current_y += promo_box_height + 20
        
        # Add decorative elements
        # Draw corner accent
        accent_points = [(0, 0), (100, 0), (0, 100)]
        draw.polygon(accent_points, fill=primary_color)
        
        # Draw bottom border
        draw.rectangle([(0, height-10), (width, height)], fill=primary_color)
        
        # Add "OFERTA ESPECIAL" badge if there are promotions
        if product.promociones:
            badge_width = 200
            badge_height = 60
            badge_x = width - badge_width - 20
            badge_y = height - badge_height - 20
            
            # Create badge
            badge_points = [
                (badge_x, badge_y + 15),
                (badge_x + 15, badge_y),
                (badge_x + badge_width - 15, badge_y),
                (badge_x + badge_width, badge_y + 15),
                (badge_x + badge_width, badge_y + badge_height - 15),
                (badge_x + badge_width - 15, badge_y + badge_height),
                (badge_x + 15, badge_y + badge_height),
                (badge_x, badge_y + badge_height - 15)
            ]
            draw.polygon(badge_points, fill=accent_color)
            
            # Badge text
            badge_text = "¡OFERTA!"
            badge_bbox = draw.textbbox((0, 0), badge_text, font=subtitle_font)
            badge_text_width = badge_bbox[2] - badge_bbox[0]
            badge_text_x = badge_x + (badge_width - badge_text_width) // 2
            badge_text_y = badge_y + (badge_height - 24) // 2
            draw.text((badge_text_x, badge_text_y), badge_text, fill=white, font=subtitle_font)
        
        # Save image if path provided
        if output_path:
            img.save(output_path, 'PNG', quality=95)
            print(f"Advertisement saved to: {output_path}")
        
        return img

    def create_simple_promotion_banner(self, promotion_info: Dict, 
                                    product_name: str = "",
                                    output_path: str = None,
                                    width: int = 600, 
                                    height: int = 200) -> Image.Image:
        """
        Creates a simple promotional banner for specific promotions.
        
        Args:
            promotion_info: Dictionary with promotion details
            product_name: Optional product name
            output_path: Path to save the image
            width: Banner width
            height: Banner height
        
        Returns:
            PIL Image object
        """
        
        # Create gradient background
        img = Image.new('RGB', (width, height), "#ff6b6b")
        draw = ImageDraw.Draw(img)
        
        # Create gradient effect
        for i in range(height):
            color_value = int(255 - (i * 100 / height))
            color = f"#{color_value:02x}4d{color_value:02x}"
            draw.line([(0, i), (width, i)], fill=color)
        
        # Try to load fonts
        try:
            big_font = ImageFont.truetype("arial.ttf", 48)
            medium_font = ImageFont.truetype("arial.ttf", 24)
            small_font = ImageFont.truetype("arial.ttf", 16)
        except:
            big_font = ImageFont.load_default()
            medium_font = ImageFont.load_default()
            small_font = ImageFont.load_default()
        
        # Draw discount percentage
        if 'descuento_porcentaje' in promotion_info:
            discount_text = f"{promotion_info['descuento_porcentaje']}%"
            discount_bbox = draw.textbbox((0, 0), discount_text, font=big_font)
            discount_width = discount_bbox[2] - discount_bbox[0]
            draw.text(((width - discount_width) // 2, 20), discount_text, fill="white", font=big_font)
            
            off_text = "OFF"
            off_bbox = draw.textbbox((0, 0), off_text, font=medium_font)
            off_width = off_bbox[2] - off_bbox[0]
            draw.text(((width - off_width) // 2, 80), off_text, fill="white", font=medium_font)
        
        # Draw promotion name
        if 'nombre' in promotion_info:
            promo_bbox = draw.textbbox((0, 0), promotion_info['nombre'], font=medium_font)
            promo_width = promo_bbox[2] - promo_bbox[0]
            draw.text(((width - promo_width) // 2, 120), promotion_info['nombre'], fill="white", font=medium_font)
        
        # Draw product name if provided
        if product_name:
            product_bbox = draw.textbbox((0, 0), product_name, font=small_font)
            product_width = product_bbox[2] - product_bbox[0]
            draw.text(((width - product_width) // 2, 150), product_name, fill="white", font=small_font)
        
        # Draw dates
        if 'fecha_inicio' in promotion_info and 'fecha_fin' in promotion_info:
            date_text = f"Válido: {promotion_info['fecha_inicio']} - {promotion_info['fecha_fin']}"
            date_bbox = draw.textbbox((0, 0), date_text, font=small_font)
            date_width = date_bbox[2] - date_bbox[0]
            draw.text(((width - date_width) // 2, 170), date_text, fill="white", font=small_font)
        
        if output_path:
            img.save(output_path, 'PNG', quality=95)
            print(f"Banner saved to: {output_path}")
        
        return img

    def get_product_for_interest(self, interest: Dict) -> Optional[Dict]:
        """
        Get product information based on interest
        This assumes you have a way to retrieve ProductInfo objects
        """
        if interest['tipo_interes'] == 'producto':
            # Get specific product
            query_text = f"producto {interest['entidad_nombre']}"
        elif interest['tipo_interes'] == 'categoria':
            # Get products from category
            query_text = f"categoría {interest['entidad_nombre']}"
        else:  # promocion
            # Get promotional products
            query_text = f"promoción {interest['entidad_nombre']}"
        
        logger.info(f"Searching for products related to interest: {query_text}")
        # Use the advertisement generator to find relevant products
        try:
            relevant_products = self.get_relevant_products(query_text, k=1)
            if relevant_products:
                return relevant_products[0]['metadata']['product_data']
        except Exception as e:
            print(f"Error getting relevant products: {e}")
            logger.error(f"Error getting relevant products for interest {interest['entidad_nombre']}: {e}")
        
        return None

    def create_personalized_ad(self, client: Dict, product_info) -> Optional[str]:
        """
        Create personalized advertisement image for client
        Returns path to the created image
        """
        try:
            # Create temporary file for the advertisement
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = temp_file.name
            temp_file.close()
            
            # Generate the advertisement
            self.ad_generator.create_product_advertisement(
                product=product_info,
                output_path=temp_path,
                width=800,
                height=600
            )
            
            return temp_path
            
        except Exception as e:
            print(f"Error creating advertisement for client {client['nombre']}: {e}")
            return None

    def send_personalized_ads():
        """
        Endpoint to send personalized advertisements to clients based on their interests
        """
        try:
            # Get clients with interests
            clients = self.db_manager.get_clients_with_interests(
                min_interest_level=0.6,
                days_back=10
            )
            
            if not clients:
                return jsonify({
                    'success': True,
                    'message': 'No clients found with specified interest criteria',
                    'sent_count': 0
                })
        
            for client in clients:
                try:
                    # Get the top interest for this client
                    top_interest = client['interests'][0] if client['interests'] else None
                    
                    if not top_interest:
                        results['details'].append({
                            'client': client['nombre'],
                            'phone': client['telefono'],
                            'status': 'skipped',
                            'reason': 'No interests found'
                        })
                        continue
                    
                    product_info = self.get_product_for_interest(top_interest)
                    
                    if not product_info:
                        results['details'].append({
                            'client': client['nombre'],
                            'phone': client['telefono'],
                            'status': 'skipped',
                            'reason': 'No matching product found'
                        })
                        continue
                    
                    # Create personalized advertisement
                    ad_image_path = self.create_personalized_ad(client, product_info)
                    
                    if not ad_image_path:
                        results['details'].append({
                            'client': client['nombre'],
                            'phone': client['telefono'],
                            'status': 'failed',
                            'reason': 'Failed to create advertisement'
                        })
                        results['failed_sends'] += 1
                        continue
                    
                    # Create personalized caption
                    caption = f"¡Hola {client['nombre']}! 🎉\n\n"
                    caption += f"Vimos que te interesa {top_interest['entidad_nombre']}. "
                    caption += f"¡Tenemos una oferta especial para ti!\n\n"
                    caption += f"💝 ¡No te pierdas esta oportunidad!"
                    
                    # Send WhatsApp message
                    success = whatsapp_service.send_whatsapp_message(
                        client['telefono'], 
                        ad_image_path, 
                        caption
                    )
                    
                    if success:
                        # Log message to database
                        whatsapp_service.log_message_to_db(
                            client['cliente_id'], 
                            caption,
                            ad_image_path
                        )
                        
                        results['successful_sends'] += 1
                        results['details'].append({
                            'client': client['nombre'],
                            'phone': client['telefono'],
                            'status': 'sent',
                            'interest': top_interest['entidad_nombre']
                        })
                    else:
                        results['failed_sends'] += 1
                        results['details'].append({
                            'client': client['nombre'],
                            'phone': client['telefono'],
                            'status': 'failed',
                            'reason': 'WhatsApp send failed'
                        })
                    
                    # Clean up temporary file
                    try:
                        os.unlink(ad_image_path)
                    except:
                        pass
                        
                except Exception as e:
                    results['failed_sends'] += 1
                    results['details'].append({
                        'client': client.get('nombre', 'Unknown'),
                        'phone': client.get('telefono', 'Unknown'),
                        'status': 'error',
                        'reason': str(e)
                    })
            
            return jsonify({
                'success': True,
                'message': f"Processed {results['total_clients']} clients",
                'results': results
            })
            
        except Exception as e:
            return jsonify({
                'success': False,
                'error': str(e)
            }), 500


