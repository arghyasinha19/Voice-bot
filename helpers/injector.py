import os
import json
import logging
from rag.rag_engine import DysonRAGEngine
from config import settings

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def inject_data():
    logger.info("Initializing Dyson RAG Engine and injecting data...")
    
    # Ensure the data file exists
    data_file = os.path.join(os.path.dirname(__file__), "..", "data", "dyson_data.json")
    if not os.path.exists(data_file):
        logger.error(f"Error: {data_file} not found. Please run the scraper first.")
        return
    
    # Initialize the engine. The __init__ call and _initialize method 
    # will handle the embedding and storage.
    try:
        # Check if chroma_db exists and delete if we want a fresh start
        if os.path.exists("chroma_db"):
            import shutil
            shutil.rmtree("chroma_db")
            logger.info("Removed existing chroma_db for a fresh injection.")
            
        engine = DysonRAGEngine(data_file=data_file)
        logger.info("Data injection complete. Chroma DB is now ready at 'chroma_db/'.")
        
        # Test query
        test_query = "What is the Dyson V15 Detect?"
        logger.info(f"Testing RAG with query: '{test_query}'")
        response = engine.query(test_query)
        logger.info(f"Response: {response}")
        
    except Exception as e:
        logger.exception(f"Error during injection: {e}")

if __name__ == "__main__":
    inject_data()
