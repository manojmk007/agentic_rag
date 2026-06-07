import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

from litellm import acompletion

models = [
    'gemini/gemini-2.5-flash',      # Best value — fast + smart, free tier available
    'gemini/gemini-2.5-flash-lite', # Cheapest / fastest fallback
    'gemini/gemini-2.5-pro',        # Most capable (costs more)
]

async def test():
    for model in models:
        try:
            await acompletion(
                model=model,
                messages=[{"role": "user", "content": "say ok"}],
                max_tokens=5,
            )
            print(f"WORKS: {model}")
            return
        except Exception as e:
            print(f"FAIL: {model} -> {e}")

asyncio.run(test())