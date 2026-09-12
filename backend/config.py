import os
from typing import List, Dict
from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path

class Settings(BaseSettings):
    # LLM Provider: 'bedrock' (Meta Llama 3.1 8B via Bedrock), 'ollama', 'groq', or 'mock'
    LLM_PROVIDER: str = "bedrock"

    # Ollama Local Settings
    OLLAMA_BASE_URL: str = "http://localhost:11434/v1"
    OLLAMA_MODEL: str = "llama3.1:8b"

    # AWS Bedrock Settings
    # Supported & Benchmarked Models:
    # - Default 8B:  "us.meta.llama3-1-8b-instruct-v1:0" (Meta Llama 3.1 8B Instruct)
    # - 3B Model:    "mistral.ministral-3-3b-instruct"   (Mistral Ministral 3B - ultra-fast ~540ms)
    # - 3B Micro:    "amazon.nova-micro-v1:0"             (Amazon Nova Micro)
    # - 4B Model:    "google.gemma-3-4b-it"               (Google Gemma 3 4B IT)
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    BEDROCK_MODEL_ID: str = "us.meta.llama3-1-8b-instruct-v1:0"

    # Groq Settings
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # Database Configuration (MySQL 8.0 Engine - loaded from .env)
    DB_ENGINE: str = "mysql"
    DATABASE_URL: str = ""
    
    # MySQL Settings (loaded from .env)
    MYSQL_HOST: str = "localhost"
    MYSQL_PORT: int = 3306
    MYSQL_DB: str = ""
    MYSQL_USER: str = ""
    MYSQL_PASSWORD: str = ""
    # Database Pool Settings
    DB_POOL_MIN: int = 2
    DB_POOL_MAX: int = 20

    @property
    def is_mysql(self) -> bool:
        return True
    
    # Evaluator Hash / Encryption Key (for UTR encryption at rest)
    HASH_KEY: str = "finops-evaluator-secret-hashkey-2026"

    # Server & CORS
    CORS_ORIGINS: str = "http://localhost:5173,http://localhost:3000,http://localhost:8000"
    DEBUG: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @property
    def cors_origins_list(self) -> List[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

settings = Settings()
