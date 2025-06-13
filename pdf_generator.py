from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch, cm, mm
from reportlab.lib.colors import Color, HexColor, white, black
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle, PageBreak, KeepTogether
from reportlab.platypus.frames import Frame
from reportlab.platypus.doctemplate import PageTemplate, BaseDocTemplate
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.graphics.shapes import Drawing, Rect, Circle, Line, String
from reportlab.graphics import renderPDF
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.pdfgen import canvas
from reportlab.lib import utils
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance
import tempfile
import os
import logging
from datetime import datetime
from typing import List, Dict, Optional
import io
import requests
from io import BytesIO
import urllib.parse

logger = logging.getLogger(__name__)

class PDFBrochureGenerator:
    def __init__(self, advertisement_generator):
        self.ad_generator = advertisement_generator
        self.temp_files = [] 
        self.brand_colors = {
            'primary': HexColor('#1a73e8'),     # Google Blue
            'secondary': HexColor('#34a853'),   # Google Green  
            'accent': HexColor('#ea4335'),      # Google Red
            'warning': HexColor('#fbbc04'),     # Google Yellow
            'dark': HexColor('#202124'),        # Dark Gray
            'light': HexColor('#f8f9fa'),       # Light Gray
            'white': white
        }
        
    def create_brochure_for_client(self, client_name: str, client_interests: List[Dict]) -> Optional[str]:
        """Create a complete PDF brochure based on client interests"""
        try:
            # Create temporary PDF file
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf')
            pdf_path = temp_file.name
            temp_file.close()
            self.temp_files.append(pdf_path)
            
            # Create the PDF document with custom page template
            doc = BaseDocTemplate(
                pdf_path,
                pagesize=A4,
                rightMargin=15*mm,
                leftMargin=15*mm,
                topMargin=20*mm,
                bottomMargin=20*mm
            )
            
            # Create custom page template
            frame = Frame(
                15*mm, 20*mm, 
                A4[0] - 30*mm, A4[1] - 40*mm,
                id='normal'
            )
            
            template = PageTemplate(id='main', frames=frame, onPage=self._add_page_decorations)
            doc.addPageTemplates([template])
            
            # Build the story (content)
            story = []
            
            # Add cover page
            story.extend(self._create_cover_page(client_name))
            story.append(PageBreak())
            
            # Group interests by type for better organization
            categorias = [i for i in client_interests if i.get('tipo_interes') == 'categoria']
            productos = [i for i in client_interests if i.get('tipo_interes') == 'producto']
            promociones = [i for i in client_interests if i.get('tipo_interes') == 'promocion']
            
            # Add table of contents
            # story.extend(self._create_table_of_contents(categorias, productos, promociones))
            # story.append(PageBreak())
            
            if productos:
                story.extend(self._create_enhanced_product_section(productos))
            
            if promociones:
                story.extend(self._create_promotion_section(promociones))

            if categorias:
                story.extend(self._create_category_section(categorias))
            
            # Add back page
            story.append(PageBreak())
            story.extend(self._create_back_page())
            
            # Build PDF
            doc.build(story)
            
            logger.info(f"Enhanced PDF brochure created successfully: {pdf_path}")
            return pdf_path
            
        except Exception as e:
            logger.error(f"Error creating PDF brochure: {e}")
            if hasattr(e, '__traceback__'):
                import traceback
                logger.error(traceback.format_exc())
            return None
    
    def _add_page_decorations(self, canvas, doc):
        """Add decorative elements to each page"""
        try:
            canvas.saveState()
            if doc.page == 1:
                self._draw_cover_background(canvas)

            # Add header line (skip on cover page)
            if doc.page > 1:
                canvas.setStrokeColor(self.brand_colors['primary'])
                canvas.setLineWidth(3)
                canvas.line(15*mm, A4[1] - 15*mm, A4[0] - 15*mm, A4[1] - 15*mm)
            
            # Add footer
            canvas.setFont('Helvetica', 8)
            canvas.setFillColor(self.brand_colors['dark'])
            canvas.drawString(15*mm, 10*mm, f"Página {doc.page}")
            canvas.drawRightString(A4[0] - 15*mm, 10*mm, f"Catálogo Personalizado - {datetime.now().year}")
            
            # Add corner decorations
            if doc.page > 1:
                self._add_corner_decorations(canvas)
            
            canvas.restoreState()
        except Exception as e:
            logger.error(f"Error adding page decorations: {e}")
    
    def _draw_cover_background(self, canvas):
        """Draw background directly on canvas"""
        try:
            # Background gradient effect
            colors = ['#1a73e8', '#1557b0', '#0f3c78', '#0a2040']
            rect_height = A4[1] / len(colors)
            
            for i, color_hex in enumerate(colors):
                canvas.setFillColor(HexColor(color_hex))
                canvas.rect(0, i * rect_height, A4[0], rect_height, fill=1, stroke=0)
            
            # Add decorative circles
            for i in range(5):
                canvas.setFillColor(HexColor('#ffffff20'))  # Transparent white
                x = A4[0] * (0.1 + i * 0.2)
                y = A4[1] * 0.8
                radius = 20 + i * 10
                canvas.circle(x, y, radius, fill=1, stroke=0)
                
        except Exception as e:
            logger.error(f"Error drawing cover background: {e}")


    def _add_corner_decorations(self, canvas):
        """Add decorative corner elements"""
        try:
            # Top-right corner
            canvas.setFillColor(self.brand_colors['primary'])
            canvas.circle(A4[0] - 10*mm, A4[1] - 10*mm, 2*mm, fill=1, stroke=0)
            
            # Bottom-left corner  
            canvas.setFillColor(self.brand_colors['secondary'])
            canvas.circle(10*mm, 10*mm, 2*mm, fill=1, stroke=0)
        except Exception as e:
            logger.error(f"Error adding corner decorations: {e}")

    def _create_cover_page(self, client_name: str) -> List:
        """Create an attractive cover page"""
        story = []
        styles = getSampleStyleSheet()
        
        # story.append(self._create_cover_background())
        
        # Custom styles with better typography
        title_style = ParagraphStyle(
            'EnhancedTitle',
            parent=styles['Heading1'],
            fontSize=36,
            spaceAfter=20,
            alignment=TA_CENTER,
            textColor=self.brand_colors['white'],
            fontName='Helvetica-Bold',
            leading=40,
            bold=True
        )
        
        subtitle_style = ParagraphStyle(
            'EnhancedSubtitle',
            parent=styles['Heading2'],
            fontSize=18,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=self.brand_colors['light'],
            fontName='Helvetica',
            leading=22
        )
        
        client_style = ParagraphStyle(
            'EnhancedClient',
            parent=styles['Normal'],
            fontSize=20,
            spaceAfter=40,
            alignment=TA_CENTER,
            textColor=self.brand_colors['warning'],
            fontName='Helvetica-Bold',
            borderWidth=2,
            borderColor=self.brand_colors['warning'],
            borderPadding=15,
            borderRadius=10
        )
        
        # Add space from top
        story.append(Spacer(1, 6*cm))
        
        # Main title with emoji
        story.append(Paragraph("CATÁLOGO EXCLUSIVO", title_style))
        
        # Subtitle
        story.append(Paragraph("Selección Premium Personalizada", subtitle_style))
        
        # Client name in highlighted box
        story.append(Paragraph(f"Para: {client_name}", client_style))
        
        # Welcome message with better formatting
        welcome_style = ParagraphStyle(
            'EnhancedWelcome',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=25,
            alignment=TA_JUSTIFY,
            textColor=self.brand_colors['light'],
            fontName='Helvetica',
            leftIndent=3*cm,
            rightIndent=3*cm,
            leading=18,
            backColor=HexColor('#00000040'),  # Semi-transparent background
            borderPadding=20,
            borderRadius=5
        )
        story.append(Spacer(1, 1*cm))
        welcome_text = """
        Hemos creado esta colección exclusiva basada en sus preferencias únicas. 
        Cada producto ha sido cuidadosamente seleccionado para ofrecerle las mejores 
        opciones con precios especiales y ofertas limitadas diseñadas especialmente para usted.
        """
        story.append(Paragraph(welcome_text, welcome_style))
        
        # Add feature highlights
        # story.extend(self._create_feature_highlights())
        
        # Date with better styling
        date_style = ParagraphStyle(
            'EnhancedDate',
            parent=styles['Normal'],
            fontSize=12,
            alignment=TA_RIGHT,
            textColor=self.brand_colors['light'],
            fontName='Helvetica-Oblique'
        )
        
        current_date = datetime.now().strftime("%d de %B de %Y")
        story.append(Spacer(1, 2*cm))
        story.append(Paragraph(f"📅 {current_date}", date_style))
        
        return story
    
    def _create_cover_background(self):
        """Create a background drawing for the cover"""
        try:
            drawing = Drawing(A4[0], A4[1])
            
            # Background gradient effect using rectangles
            colors = [
                HexColor('#1a73e8'),
                HexColor('#1557b0'), 
                HexColor('#0f3c78'),
                HexColor('#0a2040')
            ]
            
            rect_height = A4[1] / len(colors)
            for i, color in enumerate(colors):
                rect = Rect(0, i * rect_height, A4[0], rect_height)
                rect.fillColor = color
                rect.strokeColor = None
                drawing.add(rect)
            
            # Add decorative circles
            for i in range(5):
                circle = Circle(
                    A4[0] * (0.1 + i * 0.2), 
                    A4[1] * 0.8, 
                    20 + i * 10
                )
                circle.fillColor = HexColor('#ffffff20')  # Transparent white
                circle.strokeColor = None
                drawing.add(circle)
            
            logger.info(f"drawing: {drawing}")
            # Convert Drawing to image using renderPM
            img_io = io.BytesIO()
            renderPM.drawToFile(drawing, img_io, fmt="PNG")
            img_io.seek(0)
            pil_img = Image.open(img_io)

            # Convert PIL image to RLImage
            output_io = io.BytesIO()
            pil_img.save(output_io, format="PNG")
            output_io.seek(0)
            rl_image = RLImage(output_io, width=498, height=716)

            return rl_image
        except Exception as e:
            logger.error(f"Error creating cover background: {e}")
            return Spacer(1, 0)
    
    def _create_feature_highlights(self) -> List:
        """Create feature highlight boxes"""
        story = []
        
        try:
            features = [
                ("🎯", "Selección Personalizada", "Productos elegidos específicamente para usted"),
                ("💰", "Precios Exclusivos", "Ofertas especiales no disponibles públicamente"),
                ("⚡", "Disponibilidad Limitada", "Stock reservado por tiempo limitado"),
                ("🚚", "Envío Prioritario", "Entrega rápida y segura garantizada")
            ]
            
            # Create feature table
            feature_data = []
            for i in range(0, len(features), 2):
                row = []
                for j in range(2):
                    if i + j < len(features):
                        emoji, title, desc = features[i + j]
                        feature_cell = f"""
                        <para align='center'>
                        <font size='24'>{emoji}</font><br/>
                        <font size='12' color='#fbbc04'><b>{title}</b></font><br/>
                        <font size='10' color='#f8f9fa'>{desc}</font>
                        </para>
                        """
                        row.append(feature_cell)
                    else:
                        row.append("")
                feature_data.append(row)
            
            if feature_data:
                feature_table = Table(feature_data, colWidths=[9*cm, 9*cm])
                feature_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 10),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                    ('TOPPADDING', (0, 0), (-1, -1), 15),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
                    ('BACKGROUND', (0, 0), (-1, -1), HexColor('#ffffff15')),
                    ('ROUNDEDCORNERS', (0, 0), (-1, -1), [5, 5, 5, 5]),
                ]))
                
                story.append(Spacer(1, 1*cm))
                story.append(feature_table)
                
        except Exception as e:
            logger.error(f"Error creating feature highlights: {e}")
            
        return story
    
    def _create_table_of_contents(self, categorias: List, productos: List, promociones: List) -> List:
        """Create an attractive table of contents"""
        story = []
        styles = getSampleStyleSheet()
        
        # TOC Title
        toc_title_style = ParagraphStyle(
            'TOCTitle',
            parent=styles['Heading1'],
            fontSize=28,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=self.brand_colors['primary'],
            fontName='Helvetica-Bold'
        )
        
        story.append(Paragraph("📋 CONTENIDO", toc_title_style))
        
        # TOC Items
        toc_style = ParagraphStyle(
            'TOCItem',
            parent=styles['Normal'],
            fontSize=16,
            spaceAfter=15,
            leftIndent=20,
            textColor=self.brand_colors['dark'],
            fontName='Helvetica'
        )
        
        toc_items = []
        page_num = 3  # Starting page after cover and TOC
        
        if categorias:
            toc_items.append(f"📚 Categorías de Interés ({len(categorias)} categorías) ............ Página {page_num}")
            page_num += 1
            
        if productos:
            toc_items.append(f"🎯 Productos Recomendados ({len(productos)} productos) .......... Página {page_num}")
            page_num += 1
            
        if promociones:
            toc_items.append(f"🔥 Promociones Especiales ({len(promociones)} ofertas) ........... Página {page_num}")
            page_num += 1
            
        toc_items.append(f"📞 Información de Contacto ................................. Página {page_num}")
        
        for item in toc_items:
            story.append(Paragraph(item, toc_style))
        
        # Add summary statistics
        story.append(Spacer(1, 2*cm))
        story.extend(self._create_summary_stats(categorias, productos, promociones))
        
        return story
    
    def _create_summary_stats(self, categorias: List, productos: List, promociones: List) -> List:
        """Create visual summary statistics"""
        story = []
        
        try:
            # Stats title
            stats_style = ParagraphStyle(
                'StatsTitle',
                fontSize=20,
                spaceAfter=20,
                alignment=TA_CENTER,
                textColor=self.brand_colors['secondary'],
                fontName='Helvetica-Bold'
            )
            
            story.append(Paragraph("📊 RESUMEN DE SU SELECCIÓN", stats_style))
            
            # Create stats boxes
            stats_data = [[
                self._create_stat_box("📚", len(categorias), "Categorías", self.brand_colors['primary']),
                self._create_stat_box("🎯", len(productos), "Productos", self.brand_colors['secondary']),
                self._create_stat_box("🔥", len(promociones), "Promociones", self.brand_colors['accent'])
            ]]
            
            stats_table = Table(stats_data, colWidths=[6*cm, 6*cm, 6*cm])
            stats_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('LEFTPADDING', (0, 0), (-1, -1), 10),
                ('RIGHTPADDING', (0, 0), (-1, -1), 10),
                ('TOPPADDING', (0, 0), (-1, -1), 20),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 20),
            ]))
            
            story.append(stats_table)
            
        except Exception as e:
            logger.error(f"Error creating summary stats: {e}")
            
        return story
    
    def _create_stat_box(self, emoji: str, number: int, label: str, color) -> str:
        """Create individual stat box"""
        return f"""
        <para align='center'>
        <font size='24'>{emoji}</font><br/>
        <font size='32' color='{color}'><b>{number}</b></font><br/>
        <font size='14' color='#202124'><b>{label}</b></font>
        </para>
        """
    
    def _create_category_section(self, categorias: List[Dict]) -> List:
        """Create enhanced category section with better layout"""
        story = []
        
        section_title_style = ParagraphStyle(
            'EnhancedSectionTitle',
            fontSize=28,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=self.brand_colors['accent'],
            fontName='Helvetica-Bold',
            # borderWidth=1,
            # borderColor=self.brand_colors['accent'],
            # borderPadding=15,
            # backColor=self.brand_colors['light']
        )
        
        story.append(Paragraph("📚 CATEGORÍAS DE INTERÉS", section_title_style))
        story.append(Spacer(1, 0.3*cm))
        
        for i, categoria in enumerate(categorias):
            if i > 0:
                story.append(Spacer(1, 0.3*cm))
            story.extend(self._create_enhanced_category_page(categoria))
        
        return story
    
    def _create_enhanced_category_page(self, categoria: Dict) -> List:
        """Create enhanced category page with better product display"""
        story = []
        
        try:
            # Category header with improved styling
            # cat_title_style = ParagraphStyle(
            #     'EnhancedCategoryTitle',
            #     fontSize=22,
            #     spaceAfter=20,
            #     alignment=TA_LEFT,
            #     textColor=self.brand_colors['primary'],
            #     fontName='Helvetica-Bold',
            #     borderWidth=1,
            #     borderColor=self.brand_colors['primary'],
            #     borderPadding=15,
            #     backColor=HexColor('#e3f2fd'),
            #     leftIndent=10
            # )
            
            category_name = categoria.get('entidad_nombre', 'Categoría')
            # story.append(Paragraph(f"🏷️ {category_name.upper()}", cat_title_style))
            
            # Get products from this category
            products = self._get_category_products_safe(category_name, limit=6)
            
            if products:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                output_path = temp_file.name
                temp_file.close()
                ad_image = self.ad_generator.create_category_promotion_ad(
                    category_name=category_name,
                    products=products,
                    output_path=output_path,
                    width=1000,
                    height=700
                )
                logger.info(f"categoria: {output_path}")
                logger.info(f"ad_image : {ad_image}")
                rl_image = self.convert_image_pil_to_reportlab(ad_image)
                logger.info(f"rl_image : {rl_image}")
                story.append(rl_image)
                #     story.append(products_table)
            else:
                # Enhanced no products message
                no_products_style = ParagraphStyle(
                    'EnhancedNoProducts',
                    fontSize=16,
                    alignment=TA_CENTER,
                    textColor=self.brand_colors['dark'],
                    fontName='Helvetica-Oblique',
                    backColor=self.brand_colors['light'],
                    borderPadding=20
                )
                story.append(Paragraph("🔄 Próximamente nuevos productos en esta categoría...", no_products_style))
                
        except Exception as e:
            logger.error(f"Error creating enhanced category page: {e}")
            # Add error message instead of failing silently
            error_style = ParagraphStyle(
                'ErrorStyle',
                fontSize=14,
                alignment=TA_CENTER,
                textColor=self.brand_colors['accent'],
                fontName='Helvetica'
            )
            story.append(Paragraph("⚠️ Error al cargar productos de esta categoría", error_style))
        
        return story
    
    def _get_category_products_safe(self, category_name: str, limit: int = 4) -> List[Dict]:
        """Safely get products from category with error handling"""
        try:
            if hasattr(self.ad_generator, 'get_category_products'):
                return self.ad_generator.get_category_products(category_name, limit=limit)
            else:
                # Mock data if method doesn't exist
                return self._generate_mock_products(category_name, limit)
        except Exception as e:
            logger.warning(f"Could not get products for category {category_name}: {e}")
            return self._generate_mock_products(category_name, limit)
    
    def _generate_mock_products(self, category_name: str, limit: int) -> List[Dict]:
        """Generate mock products for testing"""
        mock_products = []
        for i in range(min(limit, 3)):  # Generate up to 3 mock products
            mock_products.append({
                'nombre': f'Producto {i+1} de {category_name}',
                'precio_actual': 99.99 + i * 50,
                'categoria': category_name,
                'descripcion': f'Excelente producto de la categoría {category_name}',
                'promociones': []
            })
        return mock_products
    
    def _create_enhanced_product_cell(self, product: Dict) -> str:
        """Create enhanced product cell with better formatting"""
        try:
            name = product.get('nombre', 'Producto')
            # Truncate long names more elegantly
            if len(name) > 30:
                name = name[:27] + "..."
                
            price = product.get('precio_actual', 0)
            category = product.get('categoria', 'Sin categoría')
            
            # Check for promotions
            promo_text = ""
            if product.get('promociones') and len(product['promociones']) > 0:
                promo = product['promociones'][0]
                if promo.get('descuento_porcentaje'):
                    promo_text = f"<br/><font color='#ea4335' size='12'><b>🏷️ {promo['descuento_porcentaje']}% OFF</b></font>"
            
            # Enhanced cell design
            cell_content = f"""
            <para align='center'>
            <font size='14' color='#202124'><b>{name}</b></font><br/>
            <font color='#1a73e8' size='10'>{category}</font><br/><br/>
            <font color='#34a853' size='16'><b>${price:,.2f}</b></font>
            {promo_text}
            </para>
            """
            
            return cell_content
            
        except Exception as e:
            logger.error(f"Error creating enhanced product cell: {e}")
            return """
            <para align='center'>
            <font color='#ea4335'>⚠️ Error al cargar producto</font>
            </para>
            """
    
    def _create_enhanced_product_section(self, productos: List[Dict]) -> List:
        """Create enhanced products section"""
        story = []
        
        section_title_style = ParagraphStyle(
            'EnhancedSectionTitle',
            fontSize=28,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=self.brand_colors['secondary'],
            fontName='Helvetica-Bold',
            # borderWidth=2,
            # borderColor=self.brand_colors['secondary'],
            # borderPadding=15,
            # backColor=self.brand_colors['light']
        )
        
        story.append(Paragraph("🎯 PRODUCTOS RECOMENDADOS", section_title_style))
        story.append(Spacer(1, 0.3*cm))
        
        for i, producto in enumerate(productos):
            story.extend(self._create_enhanced_individual_product_page(producto))
            story.append(Spacer(1, 0.3*cm))
        
        return story
    
    def _create_enhanced_individual_product_page(self, producto: Dict) -> List:
        """Create enhanced individual product page"""
        story = []
        
        try:
            product = self._get_product_for_interest_safe(producto)
            if not product:
                return story
            
            # Enhanced product layout
            # product_data = [[
            #     self._get_enhanced_product_image_cell(product),
            #     self._get_enhanced_product_details_cell(product)
            # ]]
            
            # product_table = Table(product_data, colWidths=[8*cm, 10*cm])
            # product_table.setStyle(TableStyle([
            #     ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            #     ('LEFTPADDING', (0, 0), (-1, -1), 15),
            #     ('RIGHTPADDING', (0, 0), (-1, -1), 15),
            #     ('TOPPADDING', (0, 0), (-1, -1), 15),
            #     ('BOTTOMPADDING', (0, 0), (-1, -1), 15),
            #     ('BOX', (0, 0), (-1, -1), 2, self.brand_colors['primary']),
            #     ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f8f9fa')),
            #     ('ROUNDEDCORNERS', (0, 0), (-1, -1), [10, 10, 10, 10]),
            # ]))
            
            # story.append(KeepTogether([product_table]))
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
            temp_path = temp_file.name
            temp_file.close()

            if product.promociones and len(product.promociones) > 0:
                ad_image = self.ad_generator.create_promotional_product_ad(
                    product=product,
                    output_path=temp_path,
                    width=900,
                    height=700
                )
            else:
                ad_image = self.ad_generator.create_regular_product_ad(
                    product=product,
                    output_path=temp_path,
                    width=800,
                    height=600
                )

            logger.info(f"ad_image : {ad_image}, temp_path: {temp_path}")
            rl_image = self.convert_image_pil_to_reportlab(ad_image)
            logger.info(f"rl_image : {rl_image}")
            story.append(rl_image)
            
        except Exception as e:
            logger.error(f"Error creating enhanced product page: {e}")
        
        return story
    
    def _get_product_for_interest_safe(self, producto: Dict):
        """Safely get product for interest"""
        try:
            if hasattr(self.ad_generator, 'get_product_for_interest'):
                return self.ad_generator.get_product_for_interest(producto)
            else:
                # Return mock product data
                return {
                    'nombre': producto.get('entidad_nombre', 'Producto'),
                    'precio_actual': 149.99,
                    'categoria': 'Categoría General',
                    'descripcion': f'Excelente {producto.get("entidad_nombre", "producto")} con características premium.',
                    'imagenes': [],
                    'promociones': []
                }
        except Exception as e:
            logger.warning(f"Could not get product for interest: {e}")
            return None
    
    def _dict_to_product_info_safe(self, product_dict):
        """Safely convert dict to product info"""
        try:
            if hasattr(self.ad_generator, 'dict_to_product_info'):
                return self.ad_generator.dict_to_product_info(product_dict)
            else:
                # Create simple object-like structure
                class ProductInfo:
                    def __init__(self, data):
                        self.nombre = data.get('nombre', 'Producto')
                        self.precio_actual = data.get('precio_actual', 0)
                        self.categoria = data.get('categoria', 'Sin categoría')
                        self.descripcion = data.get('descripcion', 'Sin descripción')
                        self.imagenes = data.get('imagenes', [])
                        self.promociones = data.get('promociones', [])
                
                return ProductInfo(product_dict)
        except Exception as e:
            logger.warning(f"Could not convert dict to product info: {e}")
            return None

    def _create_product_section(self, productos: List[Dict]) -> List:
        """Create products section"""
        story = []
        styles = getSampleStyleSheet()
        
        section_title_style = ParagraphStyle(
            'SectionTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=20,
            alignment=TA_CENTER,
            textColor=HexColor('#27ae60'),
            fontName='Helvetica-Bold'
        )
        
        story.append(Paragraph("🎯 PRODUCTOS RECOMENDADOS", section_title_style))
        story.append(Spacer(1, 1*cm))
        
        for producto in productos:
            story.extend(self._create_individual_product_page(producto))
            story.append(Spacer(1, 1.5*cm))
        
        return story
    
    def _create_individual_product_page(self, producto: Dict) -> List:
        """Create detailed page for individual product"""
        story = []
        
        try:
            product = self.ad_generator.get_product_for_interest(producto)
            if not product:
                return story
            
            # Create product layout with image and details
            product_data = [[
                self._get_product_image_cell(product),
                self._get_product_details_cell(product)
            ]]
            
            product_table = Table(product_data, colWidths=[8*cm, 10*cm])
            product_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 12),
                ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                ('TOPPADDING', (0, 0), (-1, -1), 12),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
                ('BOX', (0, 0), (-1, -1), 1, HexColor('#bdc3c7')),
                ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f8f9fa')),
            ]))
            
            story.append(product_table)
            
        except Exception as e:
            logger.error(f"Error creating product page: {e}")
        
        return story
    
    def _create_promotion_section(self, promociones: List[Dict]) -> List:
        """Create promotions section"""
        story = []
        styles = getSampleStyleSheet()
        logger.info(f"promociones en _create_promotion_section: {promociones}")

        section_title_style = ParagraphStyle(
            'SectionTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=20,
            alignment=TA_CENTER,
            textColor=HexColor('#e67e22'),
            fontName='Helvetica-Bold'
        )
        
        story.append(Paragraph("🔥 PROMOCIONES ESPECIALES", section_title_style))
        story.append(Spacer(1, 0.3*cm))
        
        for promocion in promociones:
            story.extend(self._create_promotion_page(promocion))
            story.append(Spacer(1, 0.3*cm))
        
        return story
    
    def _create_promotion_page(self, promocion: Dict) -> List:
        """Create promotion page"""
        story = []
        
        try:
            logger.info(f"promocion in _create_promotion_page: {promocion}")
            promo = self.ad_generator.get_promotion(promocion['entidad_id'])
            if not promo:
                return story
            
            logger.info(f"promo en _create_promotion_page: {promo}")
            # product = self.ad_generator.dict_to_product_info(product_info)
            
            if promo:
                temp_file = tempfile.NamedTemporaryFile(delete=False, suffix='.png')
                temp_path = temp_file.name
                temp_file.close()
                ad_image = self.ad_generator.create_simple_promotion_banner(
                    promotion_info=promo,
                    output_path=temp_path
                )
                logger.info(f"ad_image : {ad_image}, temp_path: {temp_path}")

                rl_image = self.convert_image_pil_to_reportlab(ad_image)
                logger.info(f"rl_image : {rl_image}")
                story.append(rl_image)
                
        except Exception as e:
            logger.error(f"Error creating promotion page: {e}")
        
        return story
    
    def _create_back_page(self) -> List:
        """Create back page with contact info and thank you message"""
        story = []
        styles = getSampleStyleSheet()
        
        # Add space from top
        story.append(Spacer(1, 3*cm))
        
        # Thank you message
        thanks_style = ParagraphStyle(
            'ThanksStyle',
            parent=styles['Heading1'],
            fontSize=28,
            spaceAfter=30,
            alignment=TA_CENTER,
            textColor=HexColor('#2c3e50'),
            fontName='Helvetica-Bold'
        )
        
        story.append(Paragraph("¡GRACIAS POR ELEGIRNOS!", thanks_style))
        
        # Contact information
        contact_style = ParagraphStyle(
            'ContactStyle',
            parent=styles['Normal'],
            fontSize=14,
            spaceAfter=15,
            alignment=TA_CENTER,
            textColor=HexColor('#34495e'),
            fontName='Helvetica'
        )
        
        contact_info = [
            "📞 Teléfono: +141 55238886",
            "📧 Email: ventas@librosbo.com",
            "🌐 Web: www.librosbo.com",
            "📍 Dirección: Av. Principal 123, Ciudad"
        ]
        
        for info in contact_info:
            story.append(Paragraph(info, contact_style))
        
        story.append(Spacer(1, 2*cm))
        
        # Final message
        final_style = ParagraphStyle(
            'FinalStyle',
            parent=styles['Normal'],
            fontSize=16,
            alignment=TA_CENTER,
            textColor=HexColor('#3498db'),
            fontName='Helvetica-Bold'
        )
        
        story.append(Paragraph("Síguenos en nuestras redes sociales para más ofertas", final_style))
        story.append(Spacer(1, 0.2*cm))

        # Social media
        social_style = ParagraphStyle(
            'SocialStyle',
            parent=styles['Normal'],
            fontSize=14,
            spaceAfter=20,
            alignment=TA_CENTER,
            textColor=HexColor('#e67e22'),
            fontName='Helvetica'
        )
        
        story.append(Paragraph("instagram: @librosbo | facebook: /librosbo | twitter: @librosbo", social_style))
        
        return story

    def _get_product_image_cell(self, product) -> str:
        """Get product image for table cell"""
        try:
            if product.imagenes and len(product.imagenes) > 0:
                # Create a placeholder for now - in real implementation you'd process the image
                return f"""
                <para align='center'>
                <b>📷 IMAGEN</b><br/>
                <font size='10'>Imagen del producto<br/>disponible en línea</font>
                </para>
                """
            else:
                return """
                <para align='center'>
                <b>📦 PRODUCTO</b><br/>
                <font size='10'>Sin imagen<br/>disponible</font>
                </para>
                """
        except Exception as e:
            logger.error(f"Error getting product image: {e}")
            return "Sin imagen"
    
    def _get_product_details_cell(self, product) -> str:
        """Get product details for table cell"""
        try:
            description = product.descripcion[:150] + ("..." if len(product.descripcion) > 150 else "") if product.descripcion else "Sin descripción disponible"
            
            details = f"""
            <b><font size='16' color='#2c3e50'>{product.nombre}</font></b><br/><br/>
            <font color='#3498db'><b>Categoría:</b> {product.categoria}</font><br/><br/>
            <b>Descripción:</b><br/>
            {description}<br/><br/>
            <font color='#27ae60' size='18'><b>Precio: ${product.precio_actual:,.2f}</b></font>
            """
            
            if product.promociones:
                promo = product.promociones[0]
                promo_details = f"<br/><br/><font color='#e74c3c'><b>🎉 PROMOCIÓN ESPECIAL</b></font><br/>"
                if 'nombre' in promo:
                    promo_details += f"<b>{promo['nombre']}</b><br/>"
                if 'descuento_porcentaje' in promo:
                    promo_details += f"<font color='#e74c3c' size='14'><b>{promo['descuento_porcentaje']}% DE DESCUENTO</b></font><br/>"
                if 'fecha_inicio' in promo and 'fecha_fin' in promo:
                    promo_details += f"<font size='10'>Válido: {promo['fecha_inicio']} - {promo['fecha_fin']}</font>"
                
                details += promo_details
            
            return details
            
        except Exception as e:
            logger.error(f"Error getting product details: {e}")
            return "Detalles no disponibles"
    
    def save_pdf_to_aws(self, pdf_path: str, client_name: str) -> str:
        """Save PDF brochure to AWS S3"""
        try:
            # Generate unique filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"brochure_{client_name.replace(' ', '_')}_{timestamp}.pdf"
            key = f"brochures/{filename}"
            
            # Upload to S3
            self.ad_generator.s3.upload_file(
                pdf_path, 
                'topicos-ads', 
                key,
                ExtraArgs={'ContentType': 'application/pdf'}
            )
            
            public_url = f"https://topicos-ads.s3.us-east-1.amazonaws.com/{key}"
            logger.info(f"PDF brochure uploaded to: {public_url}")
            
            return public_url
            
        except Exception as e:
            logger.error(f"Error uploading PDF to AWS: {e}")
            return None
    
    def cleanup_temp_files(self):
        """Clean up temporary files"""
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except Exception as e:
                logger.warning(f"Could not delete temp file {temp_file}: {e}")
        self.temp_files.clear()

    def convert_image_pil_to_reportlab(self, ad_image) -> RLImage:
        if isinstance(ad_image, Image.Image):  # Verifica que sea un objeto PIL.Image
            buffer = BytesIO()
            ad_image.save(buffer, format='PNG')
            buffer.seek(0)

            # Medidas máximas del frame
            max_width = A4[0] - 30 * mm  # 498.23
            max_height = A4[1] - 40 * mm  # 716.50

            # Tamaño original de la imagen en píxeles
            img_width_px, img_height_px = ad_image.size

            dpi_info = ad_image.info.get('dpi', (72, 72))
            if len(dpi_info) < 2:
                dpi_info = (dpi_info[0], dpi_info[0])  # Repetir si solo hay uno
            dpi_x, dpi_y = dpi_info

            # Convertir a puntos
            img_width_pt = img_width_px * 72 / dpi_x
            img_height_pt = img_height_px * 72 / dpi_y

            # Escalar proporcionalmente si excede el tamaño del frame
            scale_x = max_width / img_width_pt
            scale_y = max_height / img_height_pt
            scale = min(scale_x, scale_y, 1.0)  # solo reducir

            final_width = img_width_pt * scale
            final_height = img_height_pt * scale

            rl_image = RLImage(buffer, width=final_width, height=final_height)
            return rl_image
        else:
            logger.warning("ad_image no es un objeto PIL.Image.Image válido.")