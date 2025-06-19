from flask import Flask, request, jsonify
from flask_cors import CORS
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsSearch
from supabase import create_client, Client
import os
import asyncio

app = Flask(__name__)
CORS(app)

phone_code_hashes = {}

# Supabase config from environment
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY')
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Utilities ---

def supabase_save_session(user_id: str, session_str: str):
    supabase.table('telegram_sessions').upsert({
        'user_id': user_id,
        'session_string': session_str
    }).execute()

def supabase_get_session(user_id: str):
    result = supabase.table('telegram_sessions').select('session_string').eq('user_id', user_id).single().execute()
    if result.data:
        return result.data['session_string']
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
            chat_info["members_preview"] = [{
                "id": p.id,
                "username": p.username,
                "name": f"{p.first_name or ''} {p.last_name or ''}".strip()
            } for p in participants.users]
        except Exception:
            chat_info["members_preview"] = []

        chat_list.append(chat_info)

    return chat_list

# --- Routes ---

@app.route('/')
def home():
    return 'Telethon API is running!'

@app.route('/send-code', methods=['POST'])
def send_code():
    data = request.get_json()
    api_id = data.get("api_id")
    api_hash = data.get("api_hash")
    phone = data.get("phone")
    user_id = data.get("user_id")

    if not all([api_id, api_hash, phone, user_id]):
        return jsonify({"error": "Missing required fields"}), 400

    async def main():
        client = TelegramClient(StringSession(), int(api_id), api_hash)
        await client.connect()
        sent = await client.send_code_request(phone)
        session_str = client.session.save()
        supabase_save_session(user_id, session_str)
        await client.disconnect()
        return {
            "phone_code_hash": sent.phone_code_hash,
            "session": session_str  # Optional; useful for debugging
        }

    try:
        result = asyncio.run(main())
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/sign-in', methods=['POST'])
def sign_in():
    data = request.get_json()
    api_id = data.get("api_id")
    api_hash = data.get("api_hash")
    phone = data.get("phone")
    code = data.get("code")
    phone_code_hash = data.get("phone_code_hash") 
    user_id = data.get("user_id")

    session_str = supabase_get_session(user_id)

    if not all([api_id, api_hash, phone, code, phone_code_hash, session_str]):
        return jsonify({"error": "Missing required fields"}), 400

    async def main():
        client = TelegramClient(StringSession(session_str), int(api_id), api_hash)
        await client.connect()
        await client.sign_in(phone=phone,phone_code_hash=phone_code_hash)
        chats = await get_chats_and_members(client)
        new_session = client.session.save()
        supabase_save_session(user_id, new_session)
        await client.disconnect()
        return chats

    try:
        result = asyncio.run(main())
        return jsonify({"chats": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
