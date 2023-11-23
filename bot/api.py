import os
import time
import json
import aiohttp
import hashlib
import hmac

import config

def hash_query(params):
    data_check_arr = []
    for key, value in params.items():
        data_check_arr.append(f'{key}={value}')
    data_check_arr.sort()
    data_check_string = '\n'.join(data_check_arr)
    secret_key = hashlib.sha256(config.TELEGRAM_BOT_TOKEN.encode()).digest()
    hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return hash

def common_params(user_id):
    params = {
        'user': json.dumps({'id': user_id}),
    }

    return params

async def api_request(endpoint, method='GET', params = None, data = None):
    if not config.API_ENDPOINT:
        return None
    url = os.path.join(config.API_ENDPOINT, endpoint)

    params['auth_date'] = int(time.time())
    hash = hash_query(params)
    params['hash'] = hash
    
    async with aiohttp.ClientSession() as session:
        async with session.request(method, url, params=params, json=data) as response:
            if response.status == 200:
                response_data = await response.json()
                return response_data
            else:
                # handle error response
                return None


async def create_order(user_id, payment_method, price, token_amount):
    params = common_params(user_id)
    data = {
        'payment_method': payment_method,
        'payment_amount': price,
        'token_amount': token_amount,
    }
    
    return await api_request("orders", method="POST", params=params, data=data)

async def earn(user_id):
    params = common_params(user_id)
    
    return await api_request("earn", params=params)
