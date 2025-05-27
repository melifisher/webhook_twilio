import os
from dotenv import load_dotenv
from dataclasses import dataclass
from typing import Dict, Optional

load_dotenv()

@dataclass
class DatabaseConfig:
    host: str
    database: str
    user: str
    password: str
    port: int = 5432
    
    def to_dict(self) -> Dict[str, str]:
        return {
            'host': self.host,
            'database': self.database,
            'user': self.user,
            'password': self.password,
            'port': str(self.port)
        }

@dataclass
class OpenAIConfig:
    api_key: str
    embedding_model: str = "text-embedding-3-small"
    chat_model: str = "gpt-3.5-turbo"
    max_tokens: int = 500
    temperature: float = 0.7

@dataclass
class VectorConfig:
    dimension: int = 1536  # text-embedding-3-small dimension
    top_k_results: int = 3
    similarity_threshold: float = 0.7

@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 5000
    debug: bool = False

@dataclass
class FileConfig:
    embeddings_file: str = "product_embeddings.pkl"
    vector_index_path: str = "product_vectors"
    log_file: str = "logs/chatbot.log"
    
    def ensure_directories(self):
        """Ensure required directories exist"""
        os.makedirs(os.path.dirname(self.log_file), exist_ok=True)
        os.makedirs(os.path.dirname(self.embeddings_file), exist_ok=True)

class Config:
    def __init__(self):
        self.database = DatabaseConfig(
            host=os.getenv('DB_HOST', 'localhost'),
            database=os.getenv('DB_NAME', 'ecommerce'),
            user=os.getenv('DB_USER', ''),
            password=os.getenv('DB_PASS', ''),
            port=int(os.getenv('DB_PORT', '5432'))
        )
        
        self.openai = OpenAIConfig(
            api_key=os.getenv('OPENAI_API_KEY', ''),
            embedding_model=os.getenv('OPENAI_EMBEDDING_MODEL', 'text-embedding-3-small'),
            chat_model=os.getenv('OPENAI_CHAT_MODEL', 'gpt-3.5-turbo'),
            max_tokens=int(os.getenv('OPENAI_MAX_TOKENS', '500')),
            temperature=float(os.getenv('OPENAI_TEMPERATURE', '0.7'))
        )
        
        self.vector = VectorConfig(
            dimension=int(os.getenv('VECTOR_DIMENSION', '1536')),
            top_k_results=int(os.getenv('VECTOR_TOP_K', '3')),
            similarity_threshold=float(os.getenv('VECTOR_SIMILARITY_THRESHOLD', '0.7'))
        )
        
        # self.server = ServerConfig(
        #     host=os.getenv('FLASK_HOST', '0.0.0.0'),
        #     port=int(os.getenv('FLASK_PORT', '5000')),
        #     debug=os.getenv('FLASK_DEBUG', 'False').lower() == 'true',
        #     webhook_secret=os.getenv('WEBHOOK_SECRET')
        # )
        
        self.files = FileConfig(
            embeddings_file=os.getenv('EMBEDDINGS_FILE', 'data/product_embeddings.pkl'),
            vector_index_path=os.getenv('VECTOR_INDEX_PATH', 'data/product_vectors'),
            log_file=os.getenv('LOG_FILE', 'logs/chatbot.log')
        )
        
        # Ensure directories exist
        self.files.ensure_directories()
    
    def validate(self) -> bool:
        """Validate configuration"""
        errors = []
        
        # Check required fields
        if not self.database.host:
            errors.append("DB_HOST is required")
        if not self.database.database:
            errors.append("DB_NAME is required")
        if not self.database.user:
            errors.append("DB_USER is required")
        if not self.database.password:
            errors.append("DB_PASSWORD is required")
        if not self.openai.api_key:
            errors.append("OPENAI_API_KEY is required")
        
        if errors:
            print("Configuration errors:")
            for error in errors:
                print(f"  - {error}")
            return False
        
        return True

# Global configuration instance
config = Config()

