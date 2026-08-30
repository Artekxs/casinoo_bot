import os
import sys
import asyncio
import threading
import time
import requests
from flask import Flask

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
    url = os.environ.get('RENDER_EXTERNAL_URL', 'https://casino-bot1.onrender.com')
    while True:
        try:
            requests.get(url)
            time.sleep(300)
        except:
            time.sleep(60)

def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

if __name__ == '__main__':
    # Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    # Keep-alive в отдельном потоке
    threading.Thread(target=keep_alive, daemon=True).start()
    
    # Бот в ГЛАВНОМ потоке
    asyncio.run(main())
