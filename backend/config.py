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
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    AWS_REGION: str = "us-east-1"
    BEDROCK_MODEL_ID: str = "us.meta.llama3-1-8b-instruct-v1:0"

    # Groq Settings
    GROQ_API_KEY: str = ""
    GROQ_MODEL: str = "llama-3.1-8b-instant"

    # Database Configuration (PostgreSQL Native)
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/finops"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "finops"
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_POOL_MIN: int = 2
    POSTGRES_POOL_MAX: int = 20
    
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

# Official TBX Relational Schema Table Definitions
DATASET_SCHEMA_MAPPINGS = {
    "bank": {
        "table": "bank",
        "code_col": "bank_code",
        "name_col": "bank_name"
    },
    "account": {
        "table": "account",
        "id_col": "account_id",
        "entity_id_col": "entity_id",
        "account_number_col": "account_number",
        "program_id_col": "program_id",
        "balance_col": "available_balance",
        "bank_code_col": "bank_code"
    },
    "transaction": {
        "table": "transaction",
        "id_col": "transaction_id",
        "account_id_col": "account_id",
        "date_col": "transaction_date",
        "type_col": "transaction_type",
        "description_col": "description",
        "amount_col": "transaction_amount",
        "reference_id_col": "transaction_reference_id",
        "utr_col": "utr_number"
    }
}
