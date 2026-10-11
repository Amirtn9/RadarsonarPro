"""Validate Telegram Mini App initData signed by Telegram; reject tampered/expired data."""
import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl


def verify_init_data(init_data,bot_token,now=None,max_age=300):
    if not isinstance(init_data,str) or len(init_data)>8192 or not bot_token:raise PermissionError('Missing credentials')
    pairs=parse_qsl(init_data,keep_blank_values=True,strict_parsing=True)
    if len(pairs)>32 or len(set(k for k,v in pairs))!=len(pairs):raise PermissionError('Invalid fields')
    fields=dict(pairs)
    received=fields.pop('hash','')
    if not received or len(received)!=64:raise PermissionError('Missing signature')
    try:auth_date=int(fields['auth_date'])
    except (ValueError,KeyError,TypeError):raise PermissionError('Invalid auth date')
    now=int(time.time() if now is None else now)
    if auth_date>now+30 or now-auth_date>max_age:raise PermissionError('Expired Telegram authorization')
    check='\n'.join(f'{key}={val}' for key,val in sorted(fields.items()))
    secret=hmac.new(b'WebAppData',bot_token.encode(),hashlib.sha256).digest()
    expected=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected,received):raise PermissionError('Invalid Telegram signature')
    try:user=json.loads(fields['user']);uid=int(user['id'])
    except (ValueError,TypeError,KeyError):raise PermissionError('Invalid user')
    if uid<=0:raise PermissionError('Invalid user id')
    return uid
