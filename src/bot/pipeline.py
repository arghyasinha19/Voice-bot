import os
from loguru import logger
from typing import List, Dict, Any, Optional

from pipecat.frames.frames import EndFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.services.elevenlabs.tts import ElevenLabsTTSService
from pipecat.services.elevenlabs.stt import ElevenLabsRealtimeSTTService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext

from config import settings
from .tools import DYSON_RAG_TOOL, search_dyson_knowledge
from .prompts import SYSTEM_PROMPT

# Salesforce Lead tools
from src.salesforce.maya_tool import (
    capture_lead_interest,
    confirm_lead_creation,
    SALESFORCE_LEAD_TOOLS,
)

class MayaPipelineFactory:
    """Factory for building Maya's conversational AI pipeline."""

    @staticmethod
    def create_llm_service() -> OpenAILLMService:
        llm = OpenAILLMService(
            api_key=settings.chat_model_api_key,
            model=settings.chat_model,
        )
        # Register all tools using the direct registration method
        llm.register_direct_function(search_dyson_knowledge)
        llm.register_direct_function(capture_lead_interest)
        llm.register_direct_function(confirm_lead_creation)
        return llm

    @staticmethod
    def create_stt_service() -> ElevenLabsRealtimeSTTService:
        return ElevenLabsRealtimeSTTService(
            api_key=settings.elevenlabs_api_key,
        )

    @staticmethod
    def create_tts_service() -> ElevenLabsTTSService:
        return ElevenLabsTTSService(
            api_key=settings.elevenlabs_api_key,
            voice_id=settings.elevenlabs_voice_id,
            model=settings.elevenlabs_model_id,
            params=ElevenLabsTTSService.InputParams(
                optimize_streaming_latency=2
            )
        )

    @classmethod
    def build_standard_pipeline(
        cls,
        transport,
        system_prompt: Optional[Dict[str, str]] = None,
        session_id: str = "default",
    ):
        """Assembles a standard real-time voice pipeline."""
        llm = cls.create_llm_service()
        stt = cls.create_stt_service()
        tts = cls.create_tts_service()

        # Inject the authoritative session_id into the system prompt so the LLM
        # always passes the correct key when calling Salesforce tools.
        base_prompt = system_prompt or SYSTEM_PROMPT
        session_injected_prompt = {
            "role": base_prompt["role"],
            "content": (
                base_prompt["content"]
                + f"\n\n### Session Context\n"
                + f"Your current session_id is: `{session_id}`. "
                + "You MUST pass this exact value as the `session_id` parameter "
                + "whenever you call `capture_lead_interest` or `confirm_lead_creation`."
            ),
        }

        all_tools = [DYSON_RAG_TOOL] + SALESFORCE_LEAD_TOOLS
        
        context = OpenAILLMContext([session_injected_prompt], tools=all_tools)
        context_aggregator = llm.create_context_aggregator(context)

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                context_aggregator.user(),
                llm,
                tts,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        return pipeline, context, context_aggregator
