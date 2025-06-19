from flask import Flask, request, jsonify
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from supabase import create_client, Client
import asyncio
import os

app = Flask(__name__)

SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def supabase_save_session(user_id: str, session_str: str):
    supabase.table('sessions').upsert({'user_id': user_id, 'session': session_str}).execute()

def supabase_get_session(user_id: str):
    response = supabase.table('sessions').select('session').eq('user_id', user_id).single().execute()
    if response.data:
        return response.data['session']
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

    session_str = supabase_get_session(user_id)

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
