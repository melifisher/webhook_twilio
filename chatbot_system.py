import psycopg2
import numpy as np
import json
from datetime import datetime, date
from typing import List, Dict, Any, Optional
import pandas as pd
from dataclasses import dataclass
import pickle
import faiss
from sentence_transformers import SentenceTransformer
from openai import OpenAI

@dataclass
class ProductInfo:
    id: int
    nombre: str
    descripcion: str
    categoria: str
    categoria_descripcion: str
    precio_actual: float
    lista_precios: str
    promociones: List[Dict]
    imagenes: List[str]
    activo: bool

class EmbeddingGenerator:
    def __init__(self, model: str = "text-embedding-3-small"):
        self.client = OpenAI()
        self.model = model
    
    def create_product_text(self, product: ProductInfo) -> str:
        """Crea representación de texto comprensiva del producto para embedding"""
        text_parts = []
        
        # Información básica del producto
        text_parts.append(f"Producto: {product.nombre}")
        if product.descripcion:
            text_parts.append(f"Descripción: {product.descripcion}")
        
        # Información de categoría
        text_parts.append(f"Categoría: {product.categoria}")
        if product.categoria_descripcion:
            text_parts.append(f"Descripción de categoría: {product.categoria_descripcion}")
        
        # Información de precio
        text_parts.append(f"Precio actual: ${product.precio_actual:.2f}")
        text_parts.append(f"Lista de precios: {product.lista_precios}")
        
        # Promociones
        if product.promociones:
            promo_texts = []
            for promo in product.promociones:
                promo_text = f"{promo['nombre']} - {promo['descuento_porcentaje']}% descuento"
                if promo['descripcion']:
                    promo_text += f" - {promo['descripcion']}"
                promo_texts.append(promo_text)
            text_parts.append(f"Promociones activas: {'; '.join(promo_texts)}")
        
        # Información de imágenes
        if product.imagenes:
            img_descriptions = [img['descripcion'] for img in product.imagenes if img['descripcion']]
            if img_descriptions:
                text_parts.append(f"Imágenes: {'; '.join(img_descriptions)}")
        
        return " | ".join(text_parts)
    
    def generate_embeddings(self, products: List[ProductInfo]) -> List[Dict]:
        """Genera embeddings para todos los productos"""
        embeddings_data = []
        
        for product in products:
            text = self.create_product_text(product)
            
            try:
                # Usando embeddings de OpenAI
                response = self.client.embeddings.create(
                    input=text,
                    model=self.model
                )
                embedding = response.data[0].embedding
                
                # Alternativa: usando sentence-transformers
                # embedding = self.sentence_model.encode(text).tolist()
                
                embedding_info = {
                    'product_id': product.id,
                    'text': text,
                    'embedding': embedding,
                    'product_data': {
                        'nombre': product.nombre,
                        'descripcion': product.descripcion,
                        'categoria': product.categoria,
                        'precio_actual': product.precio_actual,
                        'promociones': product.promociones,
                        'imagenes': product.imagenes
                    }
                }
                embeddings_data.append(embedding_info)
                
            except Exception as e:
                print(f"Error generando embedding para producto {product.id}: {e}")
                continue
        
        return embeddings_data
    
    def save_embeddings(self, embeddings_data: List[Dict], filepath: str):
        """Guarda embeddings en archivo"""
        with open(filepath, 'wb') as f:
            pickle.dump(embeddings_data, f)
        print(f"Embeddings guardados en {filepath}")
    
    def load_embeddings(self, filepath: str) -> List[Dict]:
        """Carga embeddings desde archivo"""
        with open(filepath, 'rb') as f:
            embeddings_data = pickle.load(f)
        print(f"Embeddings cargados desde {filepath}")
        return embeddings_data

class VectorStore:
    def __init__(self, dimension: int = 1536):  # Dimensión de OpenAI text-embedding-3-small
        self.dimension = dimension
        self.index = faiss.IndexFlatIP(dimension)  # Producto interno para similitud coseno
        self.metadata = []
        
    def add_embeddings(self, embeddings_data: List[Dict]):
        """Agrega embeddings al almacén vectorial"""
        embeddings = np.array([item['embedding'] for item in embeddings_data]).astype('float32')
        
        # Normalizar para similitud coseno
        faiss.normalize_L2(embeddings)
        
        self.index.add(embeddings)
        self.metadata.extend(embeddings_data)
        
        print(f"Agregados {len(embeddings_data)} embeddings al almacén vectorial")
    
    def search(self, query_embedding: List[float], k: int = 5) -> List[Dict]:
        """Busca embeddings similares"""
        query_vec = np.array([query_embedding]).astype('float32')
        faiss.normalize_L2(query_vec)
        
        scores, indices = self.index.search(query_vec, k)
        
        results = []
        for i, idx in enumerate(indices[0]):
            if idx != -1:  # Índice válido
                result = {
                    'score': float(scores[0][i]),
                    'metadata': self.metadata[idx]
                }
                results.append(result)
        
        return results
    
    def save_index(self, filepath: str):
        """Guarda el índice vectorial y metadatos"""
        faiss.write_index(self.index, f"{filepath}.index")
        with open(f"{filepath}.metadata", 'wb') as f:
            pickle.dump(self.metadata, f)
    
    def load_index(self, filepath: str):
        """Carga el índice vectorial y metadatos"""
        self.index = faiss.read_index(f"{filepath}.index")
        with open(f"{filepath}.metadata", 'rb') as f:
            self.metadata = pickle.load(f)

# Usage Example
# def main():
#     db_config = {
#         'host': 'localhost',
#         'database': 'ecommerce',
#         'user': 'your_user',
#         'password': 'your_password'
#     }
    
    
#     # Step 1: Extract data from database
#     print("Extracting data from database...")
#     extractor = DatabaseManager(db_config)
#     extractor.connect()
#     products = extractor.extract_products_data()
#     extractor.disconnect()
#     print(f"Extracted {len(products)} products")
    
#     # Step 2: Generate embeddings
#     print("Generating embeddings...")
#     embedding_gen = EmbeddingGenerator()
#     embeddings_data = embedding_gen.generate_embeddings(products)
#     embedding_gen.save_embeddings(embeddings_data, "product_embeddings.pkl")
    
#     # Step 3: Create vector store
#     print("Creating vector store...") 
#     vector_store = VectorStore()
#     vector_store.add_embeddings(embeddings_data)
#     vector_store.save_index("product_vectors")
    
#     # Step 4: Create conversational bot
#     print("Creating conversational bot...")
#     bot = ConversationalBot(vector_store, embedding_gen)
    
#     # Example conversation
#     client_id = 1
    
#     # Simulate conversation
#     responses = []
    
#     # User asks about shorts
#     user_msg1 = "Busco shorts para hombre"
#     response1 = bot.generate_response(client_id, user_msg1)
#     responses.append(f"Cliente: {user_msg1}")
#     responses.append(f"Bot: {response1}")
    
#     # User asks about price (should understand context)
#     user_msg2 = "¿Cuál es el precio?"
#     response2 = bot.generate_response(client_id, user_msg2)
#     responses.append(f"Cliente: {user_msg2}")
#     responses.append(f"Bot: {response2}")
    
#     # User asks about promotions
#     user_msg3 = "¿Hay alguna promoción?"
#     response3 = bot.generate_response(client_id, user_msg3)
#     responses.append(f"Cliente: {user_msg3}")
#     responses.append(f"Bot: {response3}")
    
#     print("\n=== EXAMPLE CONVERSATION ===")
#     for response in responses:
#         print(response)

# if __name__ == "__main__":
#     main()
    