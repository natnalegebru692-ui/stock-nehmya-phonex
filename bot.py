import asyncio
import os
import sqlite3
from datetime import datetime, date
from decimal import Decimal, InvalidOperation

from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.types import Message

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}
DB_PATH = os.getenv("DB_PATH", "stock.db")

if not BOT_TOKEN:
    raise RuntimeError("Set BOT_TOKEN in your hosting environment.")
if not ADMIN_IDS:
    raise RuntimeError("Set at least one Telegram user ID in ADMIN_IDS.")

dp = Dispatcher()


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS staff (
            user_id INTEGER PRIMARY KEY, added_by INTEGER NOT NULL,
            added_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS phones (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT NOT NULL, model TEXT NOT NULL, ram TEXT NOT NULL,
            storage TEXT NOT NULL, imei TEXT NOT NULL UNIQUE,
            purchase_price REAL NOT NULL, selling_price REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'in_stock',
            added_by INTEGER NOT NULL, added_at TEXT NOT NULL
        )""")
        con.execute("""CREATE TABLE IF NOT EXISTS sales (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_id INTEGER NOT NULL, imei TEXT NOT NULL,
            customer TEXT NOT NULL, sold_price REAL NOT NULL,
            profit REAL NOT NULL, sold_by INTEGER NOT NULL,
            sold_at TEXT NOT NULL,
            FOREIGN KEY(phone_id) REFERENCES phones(id)
        )""")


def is_admin(user_id):
    return user_id in ADMIN_IDS


def is_staff(user_id):
    if is_admin(user_id):
        return True
    with db() as con:
        return con.execute("SELECT 1 FROM staff WHERE user_id=?", (user_id,)).fetchone() is not None


def money(value):
    return f"{value:,.2f} ETB"


def parse_price(value):
    try:
        amount = Decimal(value.replace(",", ""))
        if amount <= 0:
            raise ValueError
        return float(amount)
    except (InvalidOperation, ValueError):
        raise ValueError("ዋጋው ከዜሮ በላይ ቁጥር መሆን አለበት።")


async def allowed(message: Message):
    if not message.from_user or not is_staff(message.from_user.id):
        await message.answer("ይቅርታ፣ ይህን Bot ለመጠቀም ፈቃድ የለዎትም። Admin-ን ያነጋግሩ።")
        return False
    return True


@dp.message(Command("start"))
async def start(message: Message):
    uid = message.from_user.id
    if not is_staff(uid):
        await message.answer(f"እንኳን ወደ Stock Nehmya Phone በደህና መጡ።\nTelegram ID: {uid}\nAdmin-ዎ እንዲያክልዎ ይህን ID ይላኩት።")
        return
    role = "Admin" if is_admin(uid) else "Staff"
    await message.answer(
        f"📱 Stock Nehmya Phone\nRole: {role}\nCurrency: ETB\n\n"
        "/help - የትእዛዞች ዝርዝር\n"
        "/stock - በStock ያሉ ስልኮች\n"
        "/addphone brand model ram storage imei buy sell - ስልክ ጨምር\n"
        "/find IMEI - IMEI ፈልግ\n"
        "/sell IMEI customer name - ሽያጭ መዝግብ\n"
        "/report daily ወይም /report monthly - ሪፖርት (Admin)\n"
        "/addstaff TELEGRAM_ID - ሰራተኛ ጨምር (Admin)\n"
        "/removestaff TELEGRAM_ID - ሰራተኛ አስወግድ (Admin)\n"
        "/staff - የሰራተኞች ዝርዝር (Admin)"
    )


@dp.message(Command("help"))
async def help_cmd(message: Message):
    if await allowed(message):
        await start(message)


@dp.message(Command("addphone"))
async def add_phone(message: Message):
    if not await allowed(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 8:
        await message.answer("አጠቃቀም:\n/addphone brand model ram storage imei buy_price sell_price\nምሳሌ: /addphone Apple iPhone13 4GB 128GB 123456789012345 25000 30000")
        return
    _, brand, model, ram, storage, imei, buy, sell = parts
    try:
        buy_price, sell_price = parse_price(buy), parse_price(sell)
        with db() as con:
            con.execute("""INSERT INTO phones
                (brand,model,ram,storage,imei,purchase_price,selling_price,added_by,added_at)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (brand, model, ram, storage, imei, buy_price, sell_price,
                 message.from_user.id, datetime.now().isoformat(timespec="seconds")))
        await message.answer(f"✅ ስልኩ ተመዝግቧል።\n{brand} {model}\nIMEI: {imei}\nየሽያጭ ዋጋ: {money(sell_price)}")
    except sqlite3.IntegrityError:
        await message.answer("ይህ IMEI አስቀድሞ ተመዝግቧል።")
    except ValueError as e:
        await message.answer(str(e))


@dp.message(Command("stock"))
async def stock(message: Message):
    if not await allowed(message):
        return
    with db() as con:
        rows = con.execute("SELECT * FROM phones WHERE status='in_stock' ORDER BY id DESC LIMIT 40").fetchall()
        count = con.execute("SELECT COUNT(*) n FROM phones WHERE status='in_stock'").fetchone()["n"]
    if not rows:
        await message.answer("አሁን በStock ውስጥ ስልክ የለም።")
        return
    lines = [f"📦 በStock ያሉ: {count}", ""]
    for p in rows:
        lines.append(f"• {p['brand']} {p['model']} | {p['ram']} / {p['storage']}\n  IMEI: {p['imei']} | {money(p['selling_price'])}")
    await message.answer("\n".join(lines))


@dp.message(Command("find"))
async def find_phone(message: Message):
    if not await allowed(message):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) != 2:
        await message.answer("አጠቃቀም: /find IMEI")
        return
    with db() as con:
        p = con.execute("SELECT * FROM phones WHERE imei=?", (parts[1].strip(),)).fetchone()
    if not p:
        await message.answer("ይህ IMEI አልተገኘም።")
        return
    await message.answer(
        f"📱 {p['brand']} {p['model']}\nRAM: {p['ram']} | Storage: {p['storage']}\n"
        f"IMEI: {p['imei']}\nStatus: {'በStock አለ' if p['status']=='in_stock' else 'ተሽጧል'}\n"
        f"የሽያጭ ዋጋ: {money(p['selling_price'])}"
    )


@dp.message(Command("sell"))
async def sell_phone(message: Message):
    if not await allowed(message):
        return
    parts = (message.text or "").split(maxsplit=2)
    if len(parts) != 3:
        await message.answer("አጠቃቀም: /sell IMEI customer_name")
        return
    imei, customer = parts[1].strip(), parts[2].strip()
    with db() as con:
        p = con.execute("SELECT * FROM phones WHERE imei=?", (imei,)).fetchone()
        if not p:
            await message.answer("ይህ IMEI አልተገኘም።")
            return
        if p["status"] != "in_stock":
            await message.answer("ይህ ስልክ አስቀድሞ ተሽጧል።")
            return
        sold_at = datetime.now().isoformat(timespec="seconds")
        profit = p["selling_price"] - p["purchase_price"]
        con.execute("UPDATE phones SET status='sold' WHERE id=?", (p["id"],))
        con.execute("""INSERT INTO sales
            (phone_id,imei,customer,sold_price,profit,sold_by,sold_at)
            VALUES (?,?,?,?,?,?,?)""",
            (p["id"], imei, customer, p["selling_price"], profit, message.from_user.id, sold_at))
    await message.answer(
        f"✅ ሽያጭ ተመዝግቧል።\n{p['brand']} {p['model']}\nደንበኛ: {customer}\n"
        f"የሽያጭ ዋጋ: {money(p['selling_price'])}\nትርፍ: {money(profit)}"
    )


@dp.message(Command("report"))
async def report(message: Message):
    if not await allowed(message):
        return
    if not is_admin(message.from_user.id):
        await message.answer("ሪፖርት ማየት የAdmin ፈቃድ ብቻ ነው።")
        return
    parts = (message.text or "").split()
    period = parts[1].lower() if len(parts) > 1 else "daily"
    today = date.today()
    if period == "daily":
        start = today.isoformat()
        label = "የዛሬ"
    elif period == "monthly":
        start = today.replace(day=1).isoformat()
        label = "የዚህ ወር"
    else:
        await message.answer("አጠቃቀም: /report daily ወይም /report monthly")
        return
    with db() as con:
        row = con.execute("""SELECT COUNT(*) n, COALESCE(SUM(sold_price),0) revenue,
            COALESCE(SUM(profit),0) profit FROM sales WHERE date(sold_at)>=date(?)""", (start,)).fetchone()
        stock_count = con.execute("SELECT COUNT(*) n FROM phones WHERE status='in_stock'").fetchone()["n"]
    await message.answer(
        f"📊 {label} ሪፖርት\nየተሸጡ ስልኮች: {row['n']}\n"
        f"ጠቅላላ ሽያጭ: {money(row['revenue'])}\nትርፍ: {money(row['profit'])}\n"
        f"አሁን በStock ያሉ: {stock_count}"
    )


@dp.message(Command("addstaff"))
async def add_staff(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("ይህ ትእዛዝ ለAdmin ብቻ ነው።")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("አጠቃቀም: /addstaff TELEGRAM_ID")
        return
    uid = int(parts[1])
    if uid in ADMIN_IDS:
        await message.answer("ይህ ሰው አስቀድሞ Admin ነው።")
        return
    with db() as con:
        con.execute("INSERT OR IGNORE INTO staff(user_id,added_by,added_at) VALUES (?,?,?)",
                    (uid, message.from_user.id, datetime.now().isoformat(timespec="seconds")))
    await message.answer(f"✅ Staff ተጨምሯል። Telegram ID: {uid}")


@dp.message(Command("removestaff"))
async def remove_staff(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("ይህ ትእዛዝ ለAdmin ብቻ ነው።")
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].isdigit():
        await message.answer("አጠቃቀም: /removestaff TELEGRAM_ID")
        return
    uid = int(parts[1])
    with db() as con:
        cur = con.execute("DELETE FROM staff WHERE user_id=?", (uid,))
    await message.answer("Staff ተወግዷል።" if cur.rowcount else "ይህ ID በStaff ዝርዝር ውስጥ የለም።")


@dp.message(Command("staff"))
async def list_staff(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("ይህ ትእዛዝ ለAdmin ብቻ ነው።")
        return
    with db() as con:
        rows = con.execute("SELECT user_id,added_at FROM staff ORDER BY added_at").fetchall()
    text = "👥 Staff:\n" + ("\n".join(f"• {r['user_id']} ({r['added_at']})" for r in rows) if rows else "ምንም Staff አልተጨመረም።")
    await message.answer(text)


async def main():
    init_db()
    bot = Bot(BOT_TOKEN)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
