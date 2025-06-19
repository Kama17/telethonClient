from flask import Flask, request, jsonify
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from supabase import create_client, Client
import asyncio
import os
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # <-- This enables CORS for all domains by default

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
custom_headers = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Accept": "application/json"  # <-- this is what fixes 406
}


url: str = os.environ.get(SUPABASE_URL)
key: str = os.environ.get(SUPABASE_KEY)
supabase: Client = create_client(url, key)

def supabase_save_session(user_id: str, session_str: str):
    supabase.table('sessions').upsert({'user_id': user_id, 'session_string': session_str}).execute()

def supabase_get_session(user_id: str):
    response = supabase.table('telegram_sessions').select('session_string').eq('user_id', user_id).single().execute()
    if response.data:
        return response.data['session_string']
    return None

async def get_chats_and_members(client):
    dialogs = await client.get_dialogs()
    chat_list = []

    for d in dialogs:
        chat_info = {
            "id": d.id,
            "title": d.name or "Untitled",
            "type": d.entity.__class__.__name__,
        }
        try:
            participants = await client(GetParticipantsRequest(
                channel=d.entity,
                filter=ChannelParticipantsSearch(''),
                offset=0,
                limit=10,
                hash=0
            ))
            members = [{"id": p.id, "username": p.username, "name": f"{p.first_name or ''} {p.last_name or ''}".strip()} for p in participants.users]
            chat_info["members_preview"] = members
        except Exception:
            chat_info["members_preview"] = []

        chat_list.append(chat_info)

    return chat_list

@app.route('/')
def home():
    return 'Telethon API is running!'

@app.route('/connect', methods=['POST'])
def telegram_connect():
    data = request.get_json()
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    user_id = data.get('user_id')

    if not all([api_id, api_hash, user_id]):
        return jsonify({'error': 'Missing api_id, api_hash, or user_id'}), 400

    session_str = None #supabase_get_session(user_id)

    async def main():
        if session_str:
            client = TelegramClient(StringSession(session_str), int(api_id), api_hash)
        else:
            client = TelegramClient(StringSession(), int(api_id), api_hash)

        await client.start()
        chats = await get_chats_and_members(client)

        if not session_str:
            new_session = client.session.save()
            supabase_save_session(user_id, new_session)

        await client.disconnect()
        return chats

    try:
        chats = asyncio.run(main())
        return jsonify({'chats': chats})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
