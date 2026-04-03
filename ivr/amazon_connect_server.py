import os
import json
import base64
import asyncio
import audioop
from typing import Dict, Any
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from loguru import logger

from pipecat.frames.frames import AudioRawFrame, EndFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

# Modular imports
from src.bot.pipeline import MayaPipelineFactory
from src.bot.prompts import CONNECT_SYSTEM_PROMPT

app = FastAPI()

# --- Custom AWS Media Stream Bridge ---
class AmazonConnectOutputProcessor(FrameProcessor):
    """Encodes outgoing audio to AWS Mu-law JSON format."""
    def __init__(self, websocket: WebSocket, stream_id: str):
        super().__init__()
        self._websocket = websocket
        self._stream_id = stream_id
        self._state = None

    async def process_frame(self, frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, AudioRawFrame):
            try:
                resampled_audio, self._state = audioop.ratecv(
                    frame.audio, 2, 1, frame.sample_rate, 8000, self._state
                )
                ulaw_audio = audioop.lin2ulaw(resampled_audio, 2)
                message = {
                    "event": "media",
                    "media": {"payload": base64.b64encode(ulaw_audio).decode("utf-8")}
                }
                if self._stream_id:
                    message["streamId"] = self._stream_id
                await self._websocket.send_text(json.dumps(message))
            except Exception as e:
                logger.error(f"Error encoding audio for AWS: {e}")
        elif isinstance(frame, EndFrame):
            logger.info("Ending AWS stream")

@app.websocket("/connect")
async def handle_connect(websocket: WebSocket):
    await websocket.accept()
    logger.info("AWS Maya: Connect call started")
    
    stream_id = None
    task = None
    
    # Custom 'Empty' transport for manual management
    # Since we are piping raw bytes, we don't need the full transport.input() logic here
    # But we need a dummy component to satisfied the factory if we want full reuse
    # However, it's cleaner to build the services directly and manually hook the IO.
    
    # Factory helpers for services
    llm = MayaPipelineFactory.create_llm_service()
    stt = MayaPipelineFactory.create_stt_service()
    tts = MayaPipelineFactory.create_tts_service()

    # Shared Context & Logic
    from src.bot.tools import DYSON_RAG_TOOL
    from src.bot.prompts import CONNECT_SYSTEM_PROMPT
    
    context = OpenAILLMContext([CONNECT_SYSTEM_PROMPT], tools=[DYSON_RAG_TOOL])
    context_aggregator = llm.create_context_aggregator(context)

    # Simplified Pipeline for Manual IO
    pipeline = Pipeline(
        [
            stt,
            context_aggregator.user(),
            llm,
            tts,
            # AWS Output bridge added after 'start'
            context_aggregator.assistant(),
        ]
    )

    runner = PipelineRunner()
    in_state = None

    try:
        while True:
            msg_text = await websocket.receive_text()
            data = json.loads(msg_text)
            event = data.get("event")
            
            if event == "start":
                stream_id = data.get("start", {}).get("streamId")
                logger.info(f"AWS Maya: Stream ID: {stream_id}")
                
                aws_output = AmazonConnectOutputProcessor(websocket, stream_id)
                pipeline.add_processor(aws_output)
                
                task = PipelineTask(pipeline)
                asyncio.create_task(runner.run(task))

                greeting_msg = {"role": "user", "content": "Maya phone greeting."}
                context.add_message(greeting_msg)
                await task.queue_frames([context_aggregator.user().get_context_frame()])

            elif event == "media":
                if task:
                    payload = data.get("media", {}).get("payload")
                    raw_ulaw = base64.b64decode(payload)
                    linear_8k = audioop.ulaw2lin(raw_ulaw, 2)
                    linear_16k, in_state = audioop.ratecv(linear_8k, 2, 1, 8000, 16000, in_state)
                    await task.queue_frames([AudioRawFrame(linear_16k, 16000, 1)])

            elif event == "stop":
                logger.info("AWS Maya: Call stopped")
                break

    except WebSocketDisconnect:
        logger.info("AWS Maya: WebSocket disconnected")
    finally:
        if task:
            await task.queue_frames([EndFrame()])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)