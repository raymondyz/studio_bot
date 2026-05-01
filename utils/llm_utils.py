import os
from litellm import acompletion

async def query_llm(system_prompt: str, user_message: str, model: str = "claude-sonnet-4-6") -> str:
  response = await acompletion(
    model=model,
    messages=[
      {"role": "system", "content": system_prompt},
      {"role": "user", "content": user_message}
    ],
    temperature=1
  )
  return response.choices[0].message.content