import os
import asyncio
from typing import Dict, Any
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import uvicorn
from starlette.middleware.cors import CORSMiddleware
from loguru import logger

from pipecat.frames.frames import EndFrame
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.transports.smallwebrtc.transport import SmallWebRTCTransport
from pipecat.transports.smallwebrtc.connection import SmallWebRTCConnection
from pipecat.transports.base_transport import TransportParams

# Modular imports
from src.bot.pipeline import MayaPipelineFactory

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Calculate paths relative to project root
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC_DIR = os.path.join(BASE_DIR, "static")

os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = os.path.join(STATIC_DIR, "index.html")
    with open(index_path, "r") as f:
        return f.read()

class Offer(BaseModel):
    sdp: str
    type: str

@app.post("/offer")
async def handle_offer(offer: Offer):
    webrtc_connection = SmallWebRTCConnection()
    await webrtc_connection.initialize(offer.sdp, offer.type)

    transport = SmallWebRTCTransport(
        webrtc_connection=webrtc_connection,
        params=TransportParams(
            audio_out_enabled=True,
            audio_in_enabled=True,
            vad_enabled=True,
            vad_analyzer=SileroVADAnalyzer(),
            vad_audio_passthrough=True,
        )
    )

    # Use Factory to build Maya's brain
    pipeline, context, context_aggregator = MayaPipelineFactory.build_standard_pipeline(transport)

    task = PipelineTask(pipeline, params=PipelineParams(
        allow_interruptions=True,
        enable_metrics=True,
        enable_usage_metrics=True,
    ))

    @transport.event_handler("on_client_connected")
    async def on_client_connected(transport, client):
        logger.info("WebRTC Maya: Client connected")
        initial_greeting = {"role": "user", "content": "Initial greeting."}
        context.add_message(initial_greeting)
        await task.queue_frames([context_aggregator.user().get_context_frame()])

    @transport.event_handler("on_client_disconnected")
    async def on_client_disconnected(transport, client):
        logger.info("WebRTC Maya: Client disconnected")
        await task.queue_frames([EndFrame()])

    runner = PipelineRunner()

    if webrtc_connection.pc.iceGatheringState != "complete":
        gathering_complete = asyncio.Future()
        @webrtc_connection.pc.on("icegatheringstatechange")
        async def on_icegatheringstatechange():
            if webrtc_connection.pc.iceGatheringState == "complete":
                if not gathering_complete.done():
                    gathering_complete.set_result(True)
        try:
            await asyncio.wait_for(gathering_complete, timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("ICE gathering timed out.")

    answer = webrtc_connection.get_answer()
    
    async def run_pipeline():
        await runner.run(task)

    asyncio.create_task(run_pipeline())

    return JSONResponse(content={"sdp": answer["sdp"], "type": answer["type"]})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
