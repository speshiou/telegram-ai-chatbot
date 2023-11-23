import aiohttp

import config

async def send_bugreport(message: str) -> None:
    if not config.BUGREPORT_BOT_TOKEN or not config.BUGREPORT_CHAT_ID:
        raise ValueError('env BUGREPORT_BOT_TOKEN or BUGREPORT_CHAT_ID not set')
    url = f'https://api.telegram.org/bot{config.BUGREPORT_BOT_TOKEN}/sendMessage'
    async with aiohttp.ClientSession() as session:
        data = {
            'chat_id': config.BUGREPORT_CHAT_ID, 
            'text': message,
            'parse_mode': 'HTML',
            }
        async with session.post(url, data=data) as response:
            if response.status != 200:
                raise ValueError(f'Telegram API error {response.status}: {await response.text()}')
