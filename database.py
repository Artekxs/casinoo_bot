import aiosqlite
from datetime import datetime

DB_PATH = "casino.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                balance REAL DEFAULT 0.0,
                turnover REAL DEFAULT 0.0,
                total_deposit REAL DEFAULT 0.0,
                total_withdraw REAL DEFAULT 0.0,
                referrer_id INTEGER DEFAULT NULL,
                registered_at TEXT,
                is_banned INTEGER DEFAULT 0
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                type TEXT,
                amount REAL,
                status TEXT,
                created_at TEXT,
                extra TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                game_type TEXT,
                bet REAL,
                win REAL,
                result TEXT,
                created_at TEXT
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS crypto_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                invoice_id INTEGER UNIQUE,
                order_id TEXT,
                amount REAL,
                asset TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                paid_at TEXT
            )
        """)
        await db.commit()

async def get_or_create_user(user_id: int, username: str = None, full_name: str = None, referrer_id: int = None):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            if user:
                return user
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            await db.execute(
                "INSERT INTO users (user_id, username, full_name, registered_at, referrer_id) VALUES (?, ?, ?, ?, ?)",
                (user_id, username, full_name, now, referrer_id)
            )
            await db.commit()
            async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
                return await cursor.fetchone()

async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def update_balance(user_id: int, amount: float, is_turnover: bool = False):
    async with aiosqlite.connect(DB_PATH) as db:
        if is_turnover:
            await db.execute(
                "UPDATE users SET balance = balance + ?, turnover = turnover + ? WHERE user_id = ?",
                (amount, abs(amount) if amount < 0 else 0, user_id)
            )
        else:
            await db.execute(
                "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id)
            )
        await db.commit()

async def add_transaction(user_id: int, type_: str, amount: float, status: str = "done", extra: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO transactions (user_id, type, amount, status, created_at, extra) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, type_, amount, status, now, extra)
        )
        if type_ == "deposit":
            await db.execute(
                "UPDATE users SET total_deposit = total_deposit + ? WHERE user_id = ?",
                (amount, user_id)
            )
        elif type_ == "withdraw":
            await db.execute(
                "UPDATE users SET total_withdraw = total_withdraw + ? WHERE user_id = ?",
                (amount, user_id)
            )
        await db.commit()

async def get_top_players(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, username, full_name, turnover, balance FROM users ORDER BY turnover DESC LIMIT ?",
            (limit,)
        ) as cursor:
            return await cursor.fetchall()

async def save_invoice(user_id: int, invoice_id: int, order_id: str, amount: float, asset: str = "USDT"):
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        await db.execute(
            "INSERT INTO crypto_invoices (user_id, invoice_id, order_id, amount, asset, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, invoice_id, order_id, amount, asset, now)
        )
        await db.commit()

async def get_pending_invoices():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, invoice_id, amount, asset, order_id FROM crypto_invoices WHERE status = 'pending'"
        ) as cursor:
            return await cursor.fetchall()

async def update_invoice_status(invoice_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        paid_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S") if status == "paid" else None
        await db.execute(
            "UPDATE crypto_invoices SET status = ?, paid_at = ? WHERE invoice_id = ?",
            (status, paid_at, invoice_id)
        )
        await db.commit()
