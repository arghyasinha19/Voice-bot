import os
from dotenv import load_dotenv
from config import settings

load_dotenv()

def debug_config():
    print("--- DEBUG CONFIG ---")
    print(f"ELEVENLABS_API_KEY: {settings.elevenlabs_api_key[:5]}...")
    print(f"ELEVENLABS_VOICE_ID: {settings.elevenlabs_voice_id}")
    print(f"ELEVENLABS_MODEL_ID: {settings.elevenlabs_model_id}")
    print(f"CHAT_MODEL: {settings.chat_model}")
    print("--- END DEBUG ---")

if __name__ == "__main__":
    debug_config()
