
import os
import sqlite3
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, PreCheckoutQueryHandler, ContextTypes, filters
)

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = 8171293744
DB = "shop.db"


def connect():
    return sqlite3.connect(DB)


def setup():
    with connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                price INTEGER,
                description TEXT,
                file_id TEXT
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                amount INTEGER
            )
        """)


def is_admin(user_id):
    return user_id == ADMIN_ID


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with connect() as db:
        products = db.execute(
            "SELECT id, name, price, description FROM products"
        ).fetchall()

    if not products:
        await update.message.reply_text("Әзірге тауар жоқ.")
        return

    for pid, name, price, description in products:
        keyboard = [[
            InlineKeyboardButton(
                f"Сатып алу — {price} ⭐",
                callback_data=f"buy_{pid}"
            )
        ]]
        await update.message.reply_text(
            f"📱 {name}\n\n{description}\n\nБағасы: {price} ⭐",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    pid = int(query.data.split("_")[1])

    with connect() as db:
        product = db.execute(
            "SELECT name, price, description FROM products WHERE id=?",
            (pid,)
        ).fetchone()

    if not product:
        await query.message.reply_text("Тауар табылмады.")
        return

    name, price, description = product

    await context.bot.send_invoice(
        chat_id=query.message.chat_id,
        title=name,
        description=description[:255],
        payload=f"product:{pid}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(name, price)]
    )


async def precheckout(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    query = update.pre_checkout_query

    try:
        pid = int(query.invoice_payload.split(":")[1])
        with connect() as db:
            product = db.execute(
                "SELECT price FROM products WHERE id=?",
                (pid,)
            ).fetchone()

        valid = (
            product is not None
            and query.currency == "XTR"
            and query.total_amount == product[0]
        )
    except (ValueError, IndexError):
        valid = False

    await query.answer(
        ok=valid,
        error_message=None if valid else "Тауар немесе төлем дұрыс емес."
    )


async def successful_payment(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    payment = update.message.successful_payment

    if payment.currency != "XTR":
        return

    try:
        pid = int(payment.invoice_payload.split(":")[1])
    except (ValueError, IndexError):
        return

    with connect() as db:
        product = db.execute(
            "SELECT name, file_id FROM products WHERE id=?",
            (pid,)
        ).fetchone()

        if product:
            db.execute(
                "INSERT INTO sales (product_id, amount) VALUES (?, ?)",
                (pid, payment.total_amount)
            )

    if not product:
        await update.message.reply_text(
            "Төлем қабылданды, бірақ тауар табылмады. Әкімшіге хабарлас."
        )
        return

    name, file_id = product
    await update.message.reply_document(
        document=file_id,
        caption=f"✅ {name} сатып алынды! Рақмет!"
    )


async def add_product(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    document = update.message.document
    caption = update.message.caption or ""
    parts = caption.split("|", 3)

    if len(parts) != 4 or parts[0].lower() != "add":
        await update.message.reply_text(
            "Файлға сипаттаманы былай жаз:\n"
            "add|Yrgak|25|Күнделікті өмірді тәртіпке келтіру"
        )
        return

    try:
        name = parts[1].strip()
        price = int(parts[2].strip())
        description = parts[3].strip()

        if not name or price < 1 or not description:
            raise ValueError()

        with connect() as db:
            db.execute(
                """INSERT INTO products
                (name, price, description, file_id)
                VALUES (?, ?, ?, ?)""",
                (name, price, description, document.file_id)
            )

        await update.message.reply_text(
            f"✅ {name} каталогқа қосылды!"
        )
    except ValueError:
        await update.message.reply_text("Баға немесе сипаттама қате.")


async def products_admin(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    with connect() as db:
        products = db.execute(
            "SELECT id, name, price FROM products"
        ).fetchall()

    if not products:
        await update.message.reply_text("Каталог бос.")
        return

    text = "\n".join(
        f"ID: {p[0]} | {p[1]} | {p[2]} ⭐"
        for p in products
    )
    await update.message.reply_text(text)


async def delete_product(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    if not is_admin(update.effective_user.id):
        return

    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Қолдану: /delete ID")
        return

    pid = int(context.args[0])

    with connect() as db:
        cursor = db.execute(
            "DELETE FROM products WHERE id=?", (pid,)
        )

    await update.message.reply_text(
        "✅ Өшірілді." if cursor.rowcount else "Тауар табылмады."
    )


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return

    with connect() as db:
        count, total = db.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM sales"
        ).fetchone()

    await update.message.reply_text(
        f"📊 Сатылым саны: {count}\n"
        f"⭐ Жалпы сатылған Stars: {total}"
    )


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN құпия айнымалысы орнатылмаған.")

    setup()
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("products", products_admin))
    app.add_handler(CommandHandler("delete", delete_product))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CallbackQueryHandler(buy, pattern=r"^buy_\d+$"))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(
        MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment)
    )
    app.add_handler(
        MessageHandler(filters.Document.ALL, add_product)
    )

    print("QoldanbaShop іске қосылды!")
    app.run_polling()


if __name__ == "__main__":
    main()
      
