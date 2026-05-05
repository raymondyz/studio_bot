from litellm import acompletion

async def query_llm(
  system_prompt: str,
  user_message: str,
  model: str = "claude-sonnet-4-6",
  temperature: float = 1,
  internet_access: bool = False,
) -> str:
  
  tools = []
  if internet_access:
    tools.append({"type": "web_search_20250305", "name": "web_search"})

  response = await acompletion(
    model=model,
    messages=[
      {"role": "system", "content": system_prompt},
      {"role": "user", "content": user_message}
    ],
    temperature=temperature,
    tools=tools,
  )
  return response.choices[0].message.content