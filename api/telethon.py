from flask import Flask, request, jsonify
from telethon import TelegramClient
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
import asyncio
import os
from supabase import create_client, Client

app = Flask(__name__)

# Initialize Supabase client with env variables
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')  # Use service key for server
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Table schema assumption: sessions table with columns (user_id text PRIMARY KEY, session text)

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
            if hasattr(d.entity, 'participants_count'):
                chat_info["member_count"] = d.entity.participants_count
            else:
                chat_info["member_count"] = None

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
            chat_info["member_count"] = None
            chat_info["members_preview"] = []

        chat_list.append(chat_info)

    return chat_list

def supabase_save_session(user_id: str, session_str: str):
    # Upsert session for user_id
    supabase.table('sessions').upsert({'user_id': user_id, 'session': session_str}).execute()

def supabase_get_session(user_id: str):
    response = supabase.table('sessions').select('session').eq('user_id', user_id).single().execute()
    if response.data:
        return response.data['session']
    return None

@app.route('/api/telegram/connect', methods=['POST'])
def telegram_connect():
    data = request.get_json()
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')
    user_id = data.get('user_id')  # Identify user uniquely to save session
    session_str = None
    if user_id:
        session_str = supabase_get_session(user_id)

    if not api_id or not api_hash or not user_id:
        return jsonify({'error': 'Missing api_id, api_hash, or user_id'}), 400

    async def main():
        from telethon.sessions import StringSession

        if session_str:
            client = TelegramClient(StringSession(session_str), int(api_id), api_hash)
        else:
            client = TelegramClient(StringSession(), int(api_id), api_hash)

        await client.start()
        chats = await get_chats_and_members(client)

        if not session_str:
            # Save new session string
            new_session = await client.session.save()
            supabase_save_session(user_id, new_session)

        await client.disconnect()
        return chats

    try:
        chats = asyncio.run(main())
        return jsonify({'chats': chats})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == "__main__":
    app.run()
