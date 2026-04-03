import asyncio
from loguru import logger
from pipecat.frames.frames import TextFrame
from rag.rag_engine import DysonRAGEngine

# Global instance of RAG engine
rag_engine = DysonRAGEngine()

async def search_dyson_knowledge(params, **kwargs):
    """Use this tool to search the Dyson knowledge base for information on 
    Dyson India products, troubleshooting, warranty, offers, or store locations. 
    Call this tool whenever you don't instantly know an exact spec or policy."""
    query: str = kwargs.get("query", "")
    logger.info(f"Maya Tool: Searching the Dyson knowledge base for: {query}")
    
    try:
        # Perform retrieval
        answer = rag_engine.retrieve_context(query)
        
        # Send result back to LLM via callback (required for DirectFunction)
        await params.result_callback(answer)
    except Exception as e:
        logger.error(f"Maya Tool Error: search_dyson_knowledge failed: {e}")
        # Provide a graceful fallback so the LLM doesn't hang
        await params.result_callback(
            "I'm having a little trouble accessing my product manual right now. "
            "However, I can still help you with general product questions or "
            "connect you with a Dyson specialist for more detailed assistance."
        )

# Tool schema mapping for LLM definition
DYSON_RAG_TOOL = {
    "type": "function",
    "function": {
        "name": "search_dyson_knowledge",
        "description": (
            "Use this tool to search the Dyson knowledge base for information on "
            "Dyson India products, troubleshooting, warranty, offers, or store locations. "
            "Call this tool whenever you don't instantly know an exact spec or policy."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The specific question or topic to search for in the Dyson knowledge base",
                }
            },
            "required": ["query"],
        },
    },
}
