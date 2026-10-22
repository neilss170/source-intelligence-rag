"""A stand-in OpenAI-compatible model for load tests.

Load tests should measure this stack - retrieval, reranking, claim checking,
streaming, the database - not a provider's free-tier rate limits. This
server answers in the OpenAI streaming format with fixed timing: the first
token after FIRST_TOKEN_S, then the rest over about half a second.

    python scripts/load/fake_llm.py            # serves on :9100
"""

import asyncio
import json
import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

FIRST_TOKEN_S = float(os.environ.get("FAKE_FIRST_TOKEN_S", "0.35"))
TOKEN_GAP_S = float(os.environ.get("FAKE_TOKEN_GAP_S", "0.025"))
ANSWER = (
    "According to the report, the figure you asked about is stated in the "
    "first passage [E1], and the surrounding section gives the context for it [E1]."
)

app = FastAPI()


@app.post("/v1/chat/completions")
async def completions(request: Request) -> StreamingResponse:
    body = await request.json()
    user = body["messages"][-1]["content"]
    if "--- FOLLOW-UP QUESTION ---" in user:
        text = user.rsplit("--- FOLLOW-UP QUESTION ---", 1)[1].strip()
    elif "[E1]" in user:
        text = ANSWER
    else:
        text = "Hello! Ask me about your documents."

    async def stream():
        await asyncio.sleep(FIRST_TOKEN_S)
        words = text.split(" ")
        for index, word in enumerate(words):
            piece = word if index == 0 else " " + word
            chunk = {"choices": [{"delta": {"content": piece}}]}
            yield f"data: {json.dumps(chunk)}\n\n"
            await asyncio.sleep(TOKEN_GAP_S)
        usage = {"prompt_tokens": len(user) // 4, "completion_tokens": len(words)}
        yield f"data: {json.dumps({'choices': [], 'usage': usage})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "9100")))
