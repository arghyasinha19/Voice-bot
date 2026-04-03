from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from dotenv import load_dotenv
import os

load_dotenv()

class Settings(BaseSettings):
    # ElevenLabs Settings
    elevenlabs_api_key: str
    elevenlabs_voice_id: str
    elevenlabs_model_id: str
    elevenlabs_stability: float = 0.5
    elevenlabs_similarity_boost: float = 0.75
    elevenlabs_latency: int = 1

    # Application Settings
    port: int = 8000
    host: str = "0.0.0.0"

    # Embedding Settings
    embedding_model: str
    embedding_model_api_key: str
    chat_model: str = "gpt-4o"
    chat_model_api_key: str

    # Salesforce Integration
    sf_instance_url: Optional[str] = None    # e.g. https://yourorg.my.salesforce.com
    sf_access_token: Optional[str] = None    # Pre-issued OAuth bearer token
    sf_api_version: str = "v59.0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding='utf-8', extra='ignore')

settings = Settings()
