import os
import csv
import json
from datetime import datetime
from loguru import logger
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate
from config import settings

# Ensure data directory exists
os.makedirs("data", exist_ok=True)
CSV_FILE = "data/sentiment_log.csv"

# Initialize CSV if it doesn't exist
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Timestamp", "SessionID", "OverallSentiment", "ActionableInsights", "Product", "Transcript"])

async def analyze_and_log_sentiment(session_id: str, transcript: str):
    """
    Analyzes the full conversation transcript and appends the result to a CSV file.
    """
    if not transcript or not transcript.strip():
        logger.info(f"Sentiment: Transcript for session {session_id} is empty. Skipping analysis.")
        return

    logger.info(f"Sentiment: Starting end-of-call analysis for session {session_id}...")

    # Initialize a fast, cheap model for summarization/sentiment
    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0.2,
        api_key=settings.chat_model_api_key
    )

    prompt = ChatPromptTemplate.from_messages([
        (
            "system",
            "You are a customer experience analyst. Review the following conversation transcript between a user "
            "and Maya (a Dyson customer service AI). Evaluate the overall sentiment of the user (POSITIVE, NEUTRAL, or NEGATIVE). "
            "Identify the specific 'product' being discussed (e.g., 'V15 Detect', 'Airwrap'). If no specific product is mentioned or identifiable, set 'product' to null. "
            "If a product is mentioned, provide 1-2 sentences of 'insights' (actionable advice for customer service). "
            "Format your response as a strict JSON object with exactly three keys: 'sentiment', 'product', and 'insights'. "
            "Do not include markdown blocks or any other text outside the JSON."
        ),
        ("human", "Transcript:\n{transcript}")
    ])

    chain = prompt | llm

    try:
        response = await chain.ainvoke({"transcript": transcript})
        
        # Clean response if wrapped in markdown
        output = response.content.strip()
        if output.startswith("```json"):
            output = output[7:]
        if output.endswith("```"):
            output = output[:-3]
            
        data = json.loads(output)
        sentiment = data.get("sentiment", "UNKNOWN").upper()
        insights = data.get("insights", "No insights generated.")
        product = data.get("product")
        
        # Ignore if no product reference
        if not product or str(product).lower() in ["none", "null", ""]:
            logger.info(f"Sentiment: No product referenced in session {session_id}. Ignoring log.")
            return
        
        # Log to CSV
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow([timestamp, session_id, sentiment, insights, product, transcript])
            
        logger.success(f"Sentiment: Logged {sentiment} sentiment for session {session_id} (Product: {product}).")
    except Exception as e:
        logger.error(f"Sentiment: Failed to analyze sentiment for session {session_id}: {e}")
