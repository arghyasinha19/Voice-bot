import asyncio
import os
from dotenv import load_dotenv
from pipecat.services.elevenlabs import ElevenLabsTTSService
from pipecat.services.openai import OpenAILLMService
from config import settings

load_dotenv()

async def test_services():
    print(f"Testing with Model: {settings.chat_model}")
    print(f"Testing with Voice ID: {settings.elevenlabs_voice_id}")
    print(f"Testing with TTS Model: {settings.elevenlabs_model_id}")
    
    try:
        tts = ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model=settings.elevenlabs_model_id
        )
        print("TTS Service initialized.")
        
        # Test LLM
        llm = OpenAILLMService(
            api_key=settings.chat_model_api_key,
            model=settings.chat_model
        )
        print("LLM Service initialized.")
        
    except Exception as e:
        print(f"Initialization Failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_services())
