import os
import sys
import asyncio
import threading
import time
import requests
from flask import Flask

# Добавляем текущую папку в путь
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bot import main

app = Flask(__name__)

@app.route('/')
def hello():
    return "✅ Casino Bot работает!"

@app.route('/health')
def health():
    return "OK"

def keep_alive():
    url = os.environ.get('RENDER_EXTERNAL_URL', 'https://casino-bot.onrender.com')
    while True:
        try:
            requests.get(url)
            time.sleep(300)
        except:
            time.sleep(60)

def run_bot():
    asyncio.run(main())

if __name__ == '__main__':
    threading.Thread(target=keep_alive, daemon=True).start()
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
