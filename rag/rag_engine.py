import os
import json
from typing import List
from langchain_google_genai import GoogleGenerativeAIEmbeddings, ChatGoogleGenerativeAI
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import ChatPromptTemplate
from config import settings
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate


class DysonRAGEngine:
    def __init__(self, data_file="dyson_data.json"):
        self.data_file = data_file
        self.persist_directory = "chroma_db"
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.embedding_model,
            google_api_key=settings.embedding_model_api_key
        )
        self.vectorstore = None
        
        # Load and initialize vectorstore
        if os.path.exists(self.persist_directory):
            self.vectorstore = Chroma(
                persist_directory=self.persist_directory,
                embedding_function=self.embeddings
            )
        elif os.path.exists(self.data_file):
            self._initialize()
        else:
            print(f"Neither {self.persist_directory} nor {self.data_file} found.")

    def _initialize(self):
        # Load and split documents
        with open(self.data_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        documents = []
        for item in data:
            doc = Document(
                page_content=item['content'],
                metadata={"source": item['source'], "title": item['title']}
            )
            documents.append(doc)
        
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        splits = text_splitter.split_documents(documents)
        
        # Initialize VectorStore
        self.vectorstore = Chroma.from_documents(
            documents=splits,
            embedding=self.embeddings,
            persist_directory=self.persist_directory
        )
        print(f"Successfully injected {len(splits)} chunks into Chroma.")

    def retrieve_context(self, user_input: str) -> str:
        """Retrieves raw context from the vectorstore for the given query without LLM summarization."""
        if not self.vectorstore:
            return "Dyson RAG engine is not initialized. Please run the injector first."
        
        try:
            docs = self.vectorstore.similarity_search(user_input, k=3)
            context = "\n\n".join([d.page_content for d in docs])
            return context
        except Exception as e:
            print(f"Error querying ChromaDB: {e}")
            return f"Error retrieving context: {e}"

    def query(self, user_input: str) -> str:
        if not self.vectorstore:
            return "Dyson RAG engine is not initialized. Please run the injector first."
        
        try:
            # Manual RAG retrieval
            docs = self.vectorstore.similarity_search(user_input, k=3)
            context = "\n\n".join([d.page_content for d in docs])
            
            llm = ChatOpenAI(
                model=os.environ.get("CHAT_MODEL"), 
                temperature=0,
                api_key=os.environ.get("CHAT_MODEL_API_KEY")
            )
            
            system_prompt = (
                "You are an expert Dyson concierge assistant. "
                "Use the following pieces of retrieved context to answer the user's question about Dyson India products. "
                "If you don't know the answer, say that you don't know and suggest visiting dyson.in for more details. "
                "Maintain a premium, helpful, and concise tone."
            )
            
            messages = [
                ("system", f"{system_prompt}\n\nContext:\n{context}"),
                ("human", user_input),
            ]
            
            response = llm.invoke(messages)
            return response.content
        except Exception as e:
            print(f"Error querying RAG: {e}")
            return f"Error querying RAG: {e}"

if __name__ == "__main__":
    # Test (requires API key)
    # engine = DysonRAGEngine()
    # print(engine.query("What are the key features of Dyson V15 Detect?"))
    pass
