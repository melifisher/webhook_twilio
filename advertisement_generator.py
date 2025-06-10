from PIL import Image, ImageDraw, ImageFont
from dataclasses import dataclass
from typing import List, Dict, Optional
import requests
from io import BytesIO
import textwrap
from datetime import datetime
from chatbot_system import ProductInfo;
from openai import OpenAI
import tempfile
import logging
import os
import boto3
import math
from pdf_generator import PDFBrochureGenerator

logger = logging.getLogger(__name__)

class AdvertisementGenerator:
    def __init__(self, vector_store, embedding_generator, db_manager=None):
        self.client = OpenAI()
        self.vector_store = vector_store
        self.embedding_generator = embedding_generator
        self.db_manager = db_manager
        self.s3 = boto3.client('s3',
            aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY']
        )
        self.pdf_generator = PDFBrochureGenerator(self)
    
    #MAIN METHOD
    # def create_ads_for_client(self, client_name:str, client_interests: Dict):
    #     try:
    #         for interest in client_interests:
    #             if(interest['tipo_interes'] == 'categoria'):
    #                 logger.info("entro en categoria")
    #                 ad_image_path = self.create_category_ad(interest['entidad_nombre'])
    #             elif(interest['tipo_interes'] == 'producto'):
    #                 logger.info("entro en producto")
    #                 ad_image_path = self.create_personalized_ad(interest)
    #             elif(interest['tipo_interes'] == 'promocion'):
    #                 logger.info("entro en promocion")
    #                 ad_image_path = self.create_promotion_ad(interest)
    #             else:
    #                 logger.warning(f"Tipo de interés desconocido: {interest['tipo_interes']}")
    #                 ad_image_path = None

    #             logger.info(f"ad_image_path: {ad_image_path}")

    #             if not ad_image_path:
    #                 logger.info(f"No se pudo crear la imagen de anuncio para el interés: {interest['entidad_nombre']}")
    #                 continue
            
    #             public_url= self.save_aws_ad(ad_image_path)
    #             logger.info(f"public_url: {public_url}")

    #             # Clean up temporary file
    #             try:
    #                 os.unlink(ad_image_path)
    #             except:
    #                 pass
    #     except Exception as e:
    #         logger.error(f"Error creating advertisements for client: {e}")
                    
    def get_relevant_products(self, query: str, k: int = 3) -> List[Dict]:
        """Get relevant products based on query"""
        response = self.client.embeddings.create(
            input=query,
            model=self.embedding_generator.model
        )
        query_embedding = response.data[0].embedding
        results = self.vector_store.search(query_embedding, k)
        return results
    
    def hex_to_rgb(self, hex_color):
        """Convert hex color to RGB tuple"""
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
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

    def get_product_for_interest(self, interest: Dict) -> Optional[ProductInfo]:
        """
        Get product information based on interest
        This assumes you have a way to retrieve ProductInfo objects
        """
        if interest['tipo_interes'] == 'producto':
            return self.db_manager.get_product_data(interest['entidad_nombre'])
            # Get specific product
            # query_text = f"producto {interest['entidad_nombre']}"
        # elif interest['tipo_interes'] == 'categoria':
        #     # Get products from category
        #     query_text = f"categoría {interest['entidad_nombre']}"
        # else:  # promocion
        #     # Get promotional products
        #     query_text = f"promoción {interest['entidad_nombre']}"
        
        # logger.info(f"Searching for products related to interest: {query_text}")
        # Use the advertisement generator to find relevant products
        # try:
        #     relevant_products = self.get_relevant_products(query_text, k=1)
        #     if relevant_products:
        #         return relevant_products[0]['metadata']['product_data']
        # except Exception as e:
        #     print(f"Error getting relevant products: {e}")
        #     logger.error(f"Error getting relevant products for interest {interest['entidad_nombre']}: {e}")
        
        return None

    def create_gradient_background(self, width, height, start_color, end_color, direction='vertical'):
        """Create a gradient background"""
        img = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(img)
        
        start_rgb = self.hex_to_rgb(start_color)
        end_rgb = self.hex_to_rgb(end_color)
        
        if direction == 'vertical':
            for y in range(height):
                ratio = y / height
                r = int(start_rgb[0] * (1 - ratio) + end_rgb[0] * ratio)
                g = int(start_rgb[1] * (1 - ratio) + end_rgb[1] * ratio)
                b = int(start_rgb[2] * (1 - ratio) + end_rgb[2] * ratio)
                draw.line([(0, y), (width, y)], fill=(r, g, b))
        else:  # horizontal
            for x in range(width):
                ratio = x / width
                r = int(start_rgb[0] * (1 - ratio) + end_rgb[0] * ratio)
                g = int(start_rgb[1] * (1 - ratio) + end_rgb[1] * ratio)
                b = int(start_rgb[2] * (1 - ratio) + end_rgb[2] * ratio)
                draw.line([(x, 0), (x, height)], fill=(r, g, b))
        
        return img
    
    def load_fonts(self):
        """Load fonts with fallback"""
        try:
            return {
                'title': ImageFont.truetype("arial.ttf", 42),
                'subtitle': ImageFont.truetype("arial.ttf", 28),
                'text': ImageFont.truetype("arial.ttf", 20),
                'price': ImageFont.truetype("arial.ttf", 36),
                'discount': ImageFont.truetype("arial.ttf", 48),
                'small': ImageFont.truetype("arial.ttf", 16),
                'badge': ImageFont.truetype("arial.ttf", 24)
            }
        except:
            default_font = ImageFont.load_default()
            return {
                'title': default_font,
                'subtitle': default_font,
                'text': default_font,
                'price': default_font,
                'discount': default_font,
                'small': default_font,
                'badge': default_font
            }
    
    def load_product_image(self, product, target_size=(300, 300)):
        """Load and resize product image"""
        if not product.imagenes or len(product.imagenes) == 0:
            return None
        
        try:
            if product.imagenes[0]["url"].startswith('http'):
                response = requests.get(product.imagenes[0]["url"])
                img = Image.open(BytesIO(response.content))
            else:
                img = Image.open(product.imagenes[0]["url"])
            
            # Convert to RGBA for transparency support
            img = img.convert('RGBA')
            img = img.resize(target_size, Image.Resampling.LANCZOS)
            return img
        except Exception as e:
            print(f"Could not load product image: {e}")
            return None
    
    def create_promotional_product_ad(self, product: ProductInfo, 
                                    output_path: str = None,
                                    width: int = 900, 
                                    height: int = 700) -> Image.Image:
        """Create attractive promotional advertisement for products with promotions"""
        
        # Create gradient background
        img = self.create_gradient_background(width, height, '#667eea', '#764ba2')
        
        # Add subtle pattern overlay
        overlay = Image.new('RGBA', (width, height), (255, 255, 255, 20))
        for i in range(0, width, 50):
            for j in range(0, height, 50):
                if (i + j) % 100 == 0:
                    draw_overlay = ImageDraw.Draw(overlay)
                    draw_overlay.ellipse([i-10, j-10, i+10, j+10], fill=(255, 255, 255, 30))
        
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(img)
        fonts = self.load_fonts()
        
        # Load product image
        product_img = self.load_product_image(product, (280, 280))
        
        # Create main content area with rounded rectangle
        content_x, content_y = 50, 80
        content_width, content_height = width - 100, height - 160
        
        # Draw white content background with shadow
        shadow_offset = 8
        draw.rounded_rectangle([content_x + shadow_offset, content_y + shadow_offset, 
                              content_x + content_width + shadow_offset, 
                              content_y + content_height + shadow_offset], 
                             radius=20, fill=(0, 0, 0, 30))
        
        draw.rounded_rectangle([content_x, content_y, content_x + content_width, 
                              content_y + content_height], radius=20, fill='white')
        
        # Position product image on the right
        if product_img:
            img_x = content_x + content_width - 300
            img_y = content_y + 40
            img.paste(product_img, (img_x, img_y), product_img)
        
        # Left side content
        left_x = content_x + 40
        current_y = content_y + 40
        
        # Promotional badge
        if product.promociones:
            promo = product.promociones[0]
            if 'descuento_porcentaje' in promo and promo['descuento_porcentaje']:
                # Create circular discount badge
                badge_size = 120
                badge_x = left_x
                badge_y = current_y
                
                # Badge shadow
                draw.ellipse([badge_x + 4, badge_y + 4, badge_x + badge_size + 4, 
                            badge_y + badge_size + 4], fill=(0, 0, 0, 40))
                
                # Badge background
                draw.ellipse([badge_x, badge_y, badge_x + badge_size, badge_y + badge_size], 
                           fill='#ff4757')
                
                # Badge text
                discount_text = f"{promo['descuento_porcentaje']}%"
                bbox = draw.textbbox((0, 0), discount_text, font=fonts['discount'])
                text_width = bbox[2] - bbox[0]
                text_height = bbox[3] - bbox[1]
                
                draw.text((badge_x + (badge_size - text_width) // 2, 
                          badge_y + (badge_size - text_height) // 2 - 10), 
                         discount_text, fill='white', font=fonts['discount'])
                
                draw.text((badge_x + (badge_size - 30) // 2, 
                          badge_y + badge_size // 2 + 15), 
                         "OFF", fill='white', font=fonts['small'])
                
                current_y += badge_size + 20
        
        # Product title
        title_text = product.nombre.upper()
        wrapped_title = textwrap.fill(title_text, width=25)
        draw.multiline_text((left_x, current_y), wrapped_title, 
                          fill='#2c3e50', font=fonts['title'])
        current_y += len(wrapped_title.split('\n')) * 50 + 20
        
        # Category with icon-like background
        cat_bg_width = 200
        cat_bg_height = 35
        draw.rounded_rectangle([left_x, current_y, left_x + cat_bg_width, 
                              current_y + cat_bg_height], 
                             radius=17, fill='#3498db')
        
        category_text = f"📚 {product.categoria}"
        draw.text((left_x + 10, current_y + 8), category_text, 
                 fill='white', font=fonts['text'])
        current_y += cat_bg_height + 25
        
        # Description
        if product.descripcion:
            desc_lines = textwrap.fill(product.descripcion, width=35).split('\n')
            for line in desc_lines[:3]:
                draw.text((left_x, current_y), line, fill='#34495e', font=fonts['text'])
                current_y += 25
            current_y += 15
        
        # Price section
        price_bg_height = 60
        draw.rounded_rectangle([left_x, current_y, left_x + 250, 
                              current_y + price_bg_height], 
                             radius=10, fill='#2ecc71')
        
        price_text = f"${product.precio_actual:,.2f}"
        draw.text((left_x + 15, current_y + 15), price_text, 
                 fill='white', font=fonts['price'])
        
        # Promotion details at bottom
        if product.promociones:
            promo = product.promociones[0]
            promo_y = content_y + content_height - 80
            
            # Promotion name
            if 'nombre' in promo:
                draw.text((left_x, promo_y), promo['nombre'].upper(), 
                         fill='#e74c3c', font=fonts['subtitle'])
                promo_y += 30
            
            # Dates
            if 'fecha_inicio' in promo and 'fecha_fin' in promo:
                date_text = f"⏰ Válido: {promo['fecha_inicio']} - {promo['fecha_fin']}"
                draw.text((left_x, promo_y), date_text, fill='#7f8c8d', font=fonts['small'])
        
        # Decorative elements
        # Top-left corner decoration
        draw.arc([0, 0, 100, 100], 0, 90, fill='#f39c12', width=8)
        
        # Bottom-right corner decoration  
        draw.arc([width-100, height-100, width, height], 180, 270, fill='#e67e22', width=8)
        
        if output_path:
            img.save(output_path, 'PNG', quality=95)
            print(f"Promotional advertisement saved to: {output_path}")
        
        return img
    
    def create_regular_product_ad(self, product: ProductInfo, 
                                output_path: str = None,
                                width: int = 800, 
                                height: int = 600) -> Image.Image:
        """Create elegant advertisement for products without promotions"""
        
        # Create subtle gradient background
        img = self.create_gradient_background(width, height, '#f8f9fa', '#e9ecef')
        draw = ImageDraw.Draw(img)
        fonts = self.load_fonts()
        
        # Load product image
        product_img = self.load_product_image(product, (350, 350))
        
        # Modern layout with asymmetric design
        if product_img:
            # Image on left side
            img.paste(product_img, (50, 125), product_img)
            text_start_x = 450
        else:
            text_start_x = 100
        
        # Title with modern typography
        current_y = 80
        title_text = product.nombre
        
        # Create title background bar
        title_bbox = draw.textbbox((0, 0), title_text, font=fonts['title'])
        title_width = title_bbox[2] - title_bbox[0]
        title_height = title_bbox[3] - title_bbox[1]
        
        # Background bar for title
        draw.rectangle([text_start_x - 20, current_y - 10, 
                       text_start_x + min(title_width + 40, width - text_start_x), 
                       current_y + title_height + 10], 
                      fill='#2c3e50')
        
        # Wrap title if needed
        if title_width > (width - text_start_x - 40):
            wrapped_title = textwrap.fill(title_text, width=20)
            draw.multiline_text((text_start_x, current_y), wrapped_title, 
                              fill='white', font=fonts['title'])
            current_y += len(wrapped_title.split('\n')) * 50 + 30
        else:
            draw.text((text_start_x, current_y), title_text, fill='white', font=fonts['title'])
            current_y += 60
        
        # Category with elegant styling
        category_text = product.categoria.upper()
        draw.text((text_start_x, current_y), category_text, 
                 fill='#3498db', font=fonts['subtitle'])
        
        # Underline for category
        cat_bbox = draw.textbbox((0, 0), category_text, font=fonts['subtitle'])
        cat_width = cat_bbox[2] - cat_bbox[0]
        draw.line([text_start_x, current_y + 35, text_start_x + cat_width, current_y + 35], 
                 fill='#3498db', width=3)
        current_y += 60
        
        # Description with better formatting
        if product.descripcion:
            desc_lines = textwrap.fill(product.descripcion, width=30).split('\n')
            for line in desc_lines[:4]:
                draw.text((text_start_x, current_y), line, fill='#2c3e50', font=fonts['text'])
                current_y += 28
            current_y += 20
        
        # Price with elegant presentation
        price_text = f"${product.precio_actual:,.2f}"
        price_bbox = draw.textbbox((0, 0), price_text, font=fonts['price'])
        price_width = price_bbox[2] - price_bbox[0]
        
        # Price background
        draw.rounded_rectangle([text_start_x - 10, current_y - 5, 
                              text_start_x + price_width + 20, current_y + 45], 
                             radius=8, fill='#27ae60')
        
        draw.text((text_start_x + 5, current_y), price_text, fill='white', font=fonts['price'])
        
        # Quality badge
        badge_text = "CALIDAD PREMIUM"
        badge_x = width - 200
        badge_y = height - 80
        
        draw.rounded_rectangle([badge_x, badge_y, badge_x + 180, badge_y + 40], 
                             radius=20, fill='#8e44ad')
        
        badge_bbox = draw.textbbox((0, 0), badge_text, font=fonts['small'])
        badge_width = badge_bbox[2] - badge_bbox[0]
        draw.text((badge_x + (180 - badge_width) // 2, badge_y + 12), 
                 badge_text, fill='white', font=fonts['small'])
        
        # Minimalist border
        draw.rectangle([10, 10, width-10, height-10], outline='#bdc3c7', width=2)
        
        if output_path:
            img.save(output_path, 'PNG', quality=95)
            print(f"Regular product advertisement saved to: {output_path}")
        
        return img
    
    def create_category_promotion_ad(self, category_name: str, products: List[Dict],
                                   output_path: str = None,
                                   width: int = 1000, 
                                   height: int = 700) -> Image.Image:
        """Create attractive category promotion showing multiple products"""
        
        # Dynamic gradient based on category
        if 'libro' in category_name.lower() or 'book' in category_name.lower():
            start_color, end_color = '#ff9a9e', '#fecfef'
        elif 'tech' in category_name.lower() or 'electr' in category_name.lower():
            start_color, end_color = '#667eea', '#764ba2'
        else:
            start_color, end_color = '#ffecd2', '#fcb69f'
        
        img = self.create_gradient_background(width, height, start_color, end_color, 'horizontal')
        draw = ImageDraw.Draw(img)
        fonts = self.load_fonts()
        
        # Header section
        header_height = 120
        draw.rectangle([0, 0, width, header_height], fill=(0, 0, 0, 50))
        
        # Category title
        title_text = f"DESCUBRE {category_name.upper()}"
        title_bbox = draw.textbbox((0, 0), title_text, font=fonts['title'])
        title_width = title_bbox[2] - title_bbox[0]
        
        draw.text(((width - title_width) // 2, 30), title_text, 
                 fill='white', font=fonts['title'])
        
        # Subtitle
        subtitle_text = f"Los mejores productos de {category_name}"
        subtitle_bbox = draw.textbbox((0, 0), subtitle_text, font=fonts['subtitle'])
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        
        draw.text(((width - subtitle_width) // 2, 70), subtitle_text, 
                 fill='white', font=fonts['subtitle'])
        
        # Products grid
        products_to_show = products[:6]  # Show up to 6 products
        if len(products_to_show) == 0:
            # No products message
            no_products_text = "Próximamente nuevos productos..."
            draw.text((width // 2 - 150, height // 2), no_products_text, 
                     fill='white', font=fonts['subtitle'])
        else:
            # Calculate grid layout
            cols = 3 if len(products_to_show) >= 3 else len(products_to_show)
            rows = math.ceil(len(products_to_show) / cols)
            
            card_width = (width - 100) // cols - 20
            card_height = (height - header_height - 80) // rows - 20
            
            start_x = 50
            start_y = header_height + 40
            
            for i, product_data in enumerate(products_to_show):
                row = i // cols
                col = i % cols
                
                card_x = start_x + col * (card_width + 20)
                card_y = start_y + row * (card_height + 20)
                
                # Create product card
                self.draw_product_card(img, draw, fonts, product_data, 
                                     card_x, card_y, card_width, card_height)
        
        # Footer with call to action
        footer_y = height - 60
        draw.rectangle([0, footer_y, width, height], fill=(0, 0, 0, 70))
        
        cta_text = "¡Explora toda nuestra colección!"
        cta_bbox = draw.textbbox((0, 0), cta_text, font=fonts['subtitle'])
        cta_width = cta_bbox[2] - cta_bbox[0]
        
        draw.text(((width - cta_width) // 2, footer_y + 15), cta_text, 
                 fill='white', font=fonts['subtitle'])
        
        if output_path:
            img.save(output_path, 'PNG', quality=95)
            print(f"Category promotion advertisement saved to: {output_path}")
        
        return img
    
    def draw_product_card(self, img, draw, fonts, product_data, x, y, width, height):
        """Draw individual product card in category promotion"""
        
        # Card background with shadow
        shadow_offset = 4
        draw.rounded_rectangle([x + shadow_offset, y + shadow_offset, 
                              x + width + shadow_offset, y + height + shadow_offset], 
                             radius=15, fill=(0, 0, 0, 30))
        
        draw.rounded_rectangle([x, y, x + width, y + height], 
                             radius=15, fill='white')
        
        # Product image area
        img_area_height = height * 0.6
        
        # Try to load product image
        product_img = None
        if 'imagenes' in product_data and product_data['imagenes']:
            try:
                img_size = min(int(width * 0.8), int(img_area_height * 0.8))
                if product_data['imagenes'][0]["url"].startswith('http'):
                    response = requests.get(product_data['imagenes'][0]["url"])
                    product_img = Image.open(BytesIO(response.content))
                else:
                    product_img = Image.open(product_data['imagenes'][0]["url"])
                
                product_img = product_img.convert('RGBA')
                product_img = product_img.resize((img_size, img_size), Image.Resampling.LANCZOS)
                
                img_x = x + (width - img_size) // 2
                img_y = y + 10
                img.paste(product_img, (img_x, img_y), product_img)
                
            except Exception as e:
                print(f"Could not load product image: {e}")
        
        # Product info area
        info_y = y + int(img_area_height) + 10
        
        # Product name
        name_text = product_data.get('nombre', 'Producto')
        if len(name_text) > 20:
            name_text = name_text[:20] + "..."
        
        name_bbox = draw.textbbox((0, 0), name_text, font=fonts['small'])
        name_width = name_bbox[2] - name_bbox[0]
        
        draw.text((x + (width - name_width) // 2, info_y), name_text, 
                 fill='#2c3e50', font=fonts['small'])
        
        # Price
        price = product_data.get('precio_actual', 0)
        price_text = f"${price:,.2f}"
        price_bbox = draw.textbbox((0, 0), price_text, font=fonts['text'])
        price_width = price_bbox[2] - price_bbox[0]
        
        draw.text((x + (width - price_width) // 2, info_y + 25), price_text, 
                 fill='#27ae60', font=fonts['text'])
        
        # Promotion indicator if available
        if 'promociones' in product_data and product_data['promociones']:
            promo = product_data['promociones'][0]
            if 'descuento_porcentaje' in promo:
                # Small discount badge
                badge_size = 30
                badge_x = x + width - badge_size - 5
                badge_y = y + 5
                
                draw.ellipse([badge_x, badge_y, badge_x + badge_size, badge_y + badge_size], 
                           fill='#e74c3c')
                
                discount_text = f"{promo['descuento_porcentaje']}%"
                badge_bbox = draw.textbbox((0, 0), discount_text, font=fonts['small'])
                badge_text_width = badge_bbox[2] - badge_bbox[0]
                
                draw.text((badge_x + (badge_size - badge_text_width) // 2, badge_y + 8), 
                         discount_text, fill='white', font=fonts['small'])

    def get_category_products(self, category_name: str, limit: int = 6) -> List[Dict]:
        """Get products from a specific category"""
        try:
            products = self.db_manager.get_products_by_category(category_name, limit)
            return products
        except Exception as e:
            logger.error(f"Error getting category products: {e}")
            return []

    def get_promotion(self, promo_id: int) -> Optional[Dict]:
        """Get promotion by id"""
        try:
            promotion = self.db_manager.get_promotion_data(promo_id)
            return promotion
        except Exception as e:
            logger.error(f"Error getting promotion: {e}")
            return None

    def create_personalized_ad(self, interest: Dict) -> Optional[str]:
        """Create personalized advertisement image for client"""
        try:
            product = self.get_product_for_interest(interest)

            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = temp_file.name
            temp_file.close()
            
            # product = self.dict_to_product_info(product_info)
            
            # Choose ad type based on promotions
            if product.promociones and len(product.promociones) > 0:
                self.create_promotional_product_ad(
                    product=product,
                    output_path=temp_path,
                    width=900,
                    height=700
                )
            else:
                self.create_regular_product_ad(
                    product=product,
                    output_path=temp_path,
                    width=800,
                    height=600
                )
            
            return temp_path
            
        except Exception as e:
            logger.error(f"Error creating advertisement for client: {e}")
            return None

    def create_category_ad(self, category_name: str, output_path: str = None) -> Optional[str]:
        """Create category promotion advertisement"""
        try:
            if not output_path:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                output_path = temp_file.name
                temp_file.close()
            
            # Get products from category
            products = self.get_category_products(category_name, limit=6)
            
            self.create_category_promotion_ad(
                category_name=category_name,
                products=products,
                output_path=output_path,
                width=1000,
                height=700
            )
            
            return output_path
            
        except Exception as e:
            logger.error(f"Error creating category advertisement: {e}")
            return None

    def create_promotion_ad(self, interest: Dict) -> Optional[str]:
        """Create personalized advertisement image for client"""
        try:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = temp_file.name
            temp_file.close()
            
            promocion = self.get_promotion(interest['entidad_id'])
            if promocion:
                logger.info(f"producto promociones: {promocion}")
                self.create_simple_promotion_banner(
                    promotion_info=promocion,
                    output_path=temp_path
                )
           
            return temp_path
            
        except Exception as e:
            logger.error(f"Error creating promo advertisement for client: {e}")
            return None

    def dict_to_product_info(self, data: Dict) -> ProductInfo:
        """Convert dictionary to ProductInfo object"""
        return ProductInfo(
            id=data['id'],
            nombre=data['nombre'],
            descripcion=data['descripcion'],
            categoria_id=data['categoria_id'],
            categoria=data['categoria'],
            categoria_descripcion=data.get('categoria_descripcion', ''),
            precio_actual=data['precio_actual'],
            lista_precios=data.get('lista_precios', ''),
            promociones=data.get('promociones', []),
            imagenes=data.get('imagenes', []),
            activo=data.get('activo', True)
        )

    def save_aws_ad(self, ad_image_path: str) -> str:
        """Save advertisement image to AWS S3"""
        name = ad_image_path.split('\\')[-1]
        key = f"ads/{name.split('/')[-1]}"
        print(f"key: {key}")
        self.s3.upload_file(ad_image_path, 'topicos-ads', key, 
                          ExtraArgs={'ContentType': 'image/png'})

        public_url = f"https://topicos-ads.s3.us-east-1.amazonaws.com/{key}"
        return public_url

    def create_pdf_brochure_for_client(self, client_name: str, client_interests: List[Dict]) -> Optional[str]:
        """Create and upload PDF brochure for client"""
        try:
            logger.info(f"Creating PDF brochure for client: {client_name}")
            
            # Create PDF brochure
            pdf_path = self.pdf_generator.create_brochure_for_client(client_name, client_interests)
            
            if not pdf_path:
                logger.error("Failed to create PDF brochure")
                return None
            
            # Upload to AWS
            public_url = self.pdf_generator.save_pdf_to_aws(pdf_path, client_name)
            
            # Clean up temporary file
            # try:
            #     os.unlink(pdf_path)
            # except Exception as e:
            #     logger.warning(f"Could not delete temp PDF file: {e}")
            
            # Clean up any other temp files
            # self.pdf_generator.cleanup_temp_files()
            
            logger.info(f"PDF brochure created and uploaded successfully: {public_url}")
            logger.info(f"pdf_path: {pdf_path}")
            return public_url, pdf_path
            
        except Exception as e:
            logger.error(f"Error creating PDF brochure for client: {e}")
            return None
    
    # Método actualizado para crear folletos en lugar de imágenes individuales
    def create_ads_for_client(self, client_name: str, client_interests: List[Dict]):
        """Create PDF brochure instead of individual images"""
        try:
            public_url, pdf_path = self.create_pdf_brochure_for_client(client_name, client_interests)
            
            if public_url:
                logger.info(f"PDF brochure created successfully for {client_name}: {public_url}")

                intereses_ids = [interest['id'] for interest in client_interests]
                # intereses_ids_str = ','.join(map(str, intereses_ids))
                logger.info(f"intereses_ids: {intereses_ids}")
                self.db_manager.intereses_procesados(intereses_ids)

                return public_url, pdf_path
            else:
                logger.error(f"Failed to create PDF brochure for {client_name}")
                return None
                
        except Exception as e:
            logger.error(f"Error creating advertisements for client: {e}")
            return None
