import json
import uuid
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessageChunk, HumanMessage

from app.agent.graph import chatbot, langfuse_handler
from app.api.schemas.chat import ChatRequest

router = APIRouter()


@router.post("/chat")
def chat_stream(req: ChatRequest):
    thread_id = req.thread_id or str(uuid.uuid4())
    callbacks = [langfuse_handler] if langfuse_handler else []
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,
    }

    def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'meta', 'thread_id': thread_id})}\n\n"
            for chunk, _metadata in chatbot.stream(
                {"messages": [HumanMessage(content=req.message)]},
                config=config,
                stream_mode="messages",
            ):
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    content = chunk.content
                    if isinstance(content, list):
                        text = "".join(
                            b if isinstance(b, str) else b.get("text", "")
                            for b in content
                            if isinstance(b, (str, dict))
                        )
                    else:
                        text = str(content)
                    if text:
                        yield f"data: {json.dumps({'type': 'token', 'content': text})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'thread_id': thread_id})}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'type': 'error', 'error': str(exc)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
