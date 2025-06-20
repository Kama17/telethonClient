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
    }, on_conflict='user_id').execute()


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
            members = []
            async for user in client.iter_participants(d.entity, limit=10):
                members.append({
                "id": user.id,
                "username": user.username,
                "name": f"{user.first_name or ''} {user.last_name or ''}".strip()
                })
            chat_info["members_preview"] = members
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

        try:
            await client.sign_in(phone=phone, phone_code_hash=phone_code_hash, code=code)
        except Exception as e:
            await client.disconnect()
            raise e

        if not await client.is_user_authorized():
            await client.disconnect()
            return {'error': 'User not authorized after sign-in.'}

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
    

@app.route('/auto-login', methods=['POST'])
def auto_login():
    data = request.get_json()
    session_str = data.get('session_string')
    api_id = data.get('api_id')
    api_hash = data.get('api_hash')

    if not all([session_str, api_id, api_hash]):
        return jsonify({'error': 'Missing required fields'}), 400

    async def main():
        client = TelegramClient(StringSession(session_str), int(api_id), api_hash)
        await client.connect()
        is_auth = await client.is_user_authorized()
        if not is_auth:
            await client.disconnect()
            return {'error': 'Session is not authorized'}

        me = await client.get_me()
        await client.disconnect()
        return {'session': session_str, 'username': me.username, 'user_id': me.id}

    try:
        result = asyncio.run(main())
        return jsonify(result)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.errorhandler(500)
def handle_internal_error(error):
    return jsonify({"error": "Internal Server Error", "details": str(error)}), 500
