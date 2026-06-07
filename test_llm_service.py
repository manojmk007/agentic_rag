import asyncio
from dotenv import load_dotenv
load_dotenv()

from app.models.context import AssembledContext
from app.services.llm_service import generate_response

async def test():
    ctx = AssembledContext(
        session_id="test-session-001",
        tenant_id="test-tenant",
        user_query="What is the capital of France?",
        system_prompt="You are a helpful assistant.",
        source_documents=[],
        conversation_history=[],
        memory_context=None,
        fresh_context=None,
    )
    response = await generate_response(ctx)
    print(f"Response ID : {response.response_id}")
    print(f"Answer      : {response.raw_answer}")
    print(f"Confidence  : {response.confidence_score}")
    print(f"Model used  : {response.model_used}")
    print(f"Latency     : {response.latency_ms} ms")

asyncio.run(test())