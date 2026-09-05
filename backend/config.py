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

    # Data Directory & Paths
    DATA_DIR: str = "data"
    
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

    @property
    def data_path(self) -> Path:
        base = Path(__file__).resolve().parent.parent
        return base / self.DATA_DIR

settings = Settings()

# Official TBX Connected Banking Dataset Mapping (3 Tables)
DATASET_SCHEMA_MAPPINGS = {
    "bank": {
        "file": "bank.csv",
        "code_col": "bank_code",
        "name_col": "bank_name"
    },
    "account": {
        "file": "account.csv",
        "id_col": "account_id",
        "entity_id_col": "entity_id",
        "account_number_col": "account_number",
        "program_id_col": "program_id",
        "balance_col": "available_balance",
        "bank_code_col": "bank_code"
    },
    "transaction": {
        "file": "transaction.csv",
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
