
async def get_member_messages(channel, member, limit=100):
  messages = []

  async for message in channel.history(limit=limit):
    if message.author == member:
      messages.append(message)
  return messages
