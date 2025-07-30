import os
import discord
from discord.ext import commands, tasks
from discord import app_commands
from dotenv import load_dotenv
import sqlite3
from datetime import datetime, timezone, timedelta, time

from keep_alive import keep_alive

# Зміщення UTC для вашого часового поясу.
# Якщо ваш час UTC+3, встановіть UTC_OFFSET = 3.
UTC_OFFSET = 3
message_hour = 16  # Година, коли повідомлення має бути надіслано (за місцевим часом)


BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def create_table():
    """Створює таблицю 'calendar' у базі даних, якщо вона ще не існує."""
    connection = sqlite3.connect(os.path.join(BASE_DIR, "calendar.db"))
    cursor = connection.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS "calendar" (
            "name" TEXT,
            "birthday" TEXT,
            PRIMARY KEY("name"))"""
    )
    connection.commit()
    connection.close()


create_table()


def add_birthday(name: str, birthday_int: str) -> None:
    """Додає або оновлює запис про день народження в базі даних."""
    connection = sqlite3.connect(os.path.join(BASE_DIR, "calendar.db"))
    try:
        cursor = connection.cursor()
        cursor.execute(
            """
            INSERT INTO calendar (name, birthday)
            VALUES (?, ?)
            ON CONFLICT(name) DO UPDATE SET birthday=excluded.birthday
        """,
            (name, birthday_int),
        )
        connection.commit()
    finally:
        connection.close()


def get_birthday(birthday_int: str):
    """Отримує всі імена, у яких день народження відповідає заданій даті."""
    connection = sqlite3.connect(os.path.join(BASE_DIR, "calendar.db"))
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT name, birthday FROM calendar WHERE birthday = ?", (birthday_int,)
        )
        rows = cursor.fetchall()
        return rows
    finally:
        connection.close()


def get_all_birthdays():
    """Отримує всі записи про дні народження з бази даних."""
    connection = sqlite3.connect(os.path.join(BASE_DIR, "calendar.db"))
    try:
        cursor = connection.cursor()
        cursor.execute("SELECT name, birthday FROM calendar ORDER BY birthday ASC")
        rows = cursor.fetchall()
        return rows
    finally:
        connection.close()


def delete_birthday(name: str) -> int:
    """Видаляє запис про день народження за іменем."""
    connection = sqlite3.connect(os.path.join(BASE_DIR, "calendar.db"))
    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM calendar WHERE name = ?", (name,))
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

keep_alive()

intents = discord.Intents.default()
intents.message_content = True  # Дозволяє боту читати вміст повідомлень
intents.guilds = True  # Дозволяє боту отримувати інформацію про гільдії

bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    """Викликається, коли бот підключається до Discord."""
    print(f"Увійшов як {bot.user} (ID: {bot.user.id})")
    # Запускаємо завдання перевірки днів народження
    if not check_birthdays.is_running():
        check_birthdays.start()
    print("Завдання check_birthdays запущено.")

    # Синхронізуємо команди додатків
    try:
        synced = await bot.tree.sync()
        print(f"Синхронізовано {len(synced)} команд.")
    except Exception as e:
        print(f"Помилка синхронізації команд: {e}")


@tasks.loop(time=time(hour=message_hour - UTC_OFFSET, minute=0))
async def check_birthdays():
    """
    Перевіряє дні народження та надсилає повідомлення на всі сервери.
    Запускається щодня о заданій годині.
    """
    await bot.wait_until_ready()
    print(f"Запуск перевірки днів народження о {datetime.now().strftime('%H:%M:%S')}")

    now = datetime.now()
    # Формат "день/місяць" для порівняння з базою даних
    today_str = now.strftime("%d/%m")
    rows = get_birthday(today_str)

    if not rows:
        print(f"Сьогодні ({today_str}) немає днів народження.")
        return

    names = ", ".join(name for name, _ in rows)
    msg = f"🎉 Сьогодні ({now:%d.%m}) день народження в: {names}! 🎂"

    # Перебираємо всі гільдії (сервери), до яких бот підключений
    for guild in bot.guilds:
        target_channel = None
        # Спроба знайти канал 'birthdays', потім 'general', потім будь-який текстовий канал
        # з дозволом на надсилання повідомлень
        for channel in guild.text_channels:
            if channel.permissions_for(guild.me).send_messages:
                if channel.name == "birthdays":
                    target_channel = channel
                    break
                elif (
                    channel.name == "general" and not target_channel
                ):  # Якщо 'birthdays' не знайдено, але 'general' є
                    target_channel = channel
                elif (
                    not target_channel
                ):  # Якщо ні 'birthdays', ні 'general' не знайдено, беремо перший доступний
                    target_channel = channel

        if target_channel:
            try:
                await target_channel.send(msg)
                print(
                    f"Надіслано повідомлення про день народження у канал '{target_channel.name}' в гільдії '{guild.name}'."
                )
            except discord.Forbidden:
                print(
                    f"[ПОПЕРЕДЖЕННЯ] Немає дозволу на надсилання повідомлень у каналі '{target_channel.name}' в гільдії '{guild.name}'."
                )
            except Exception as e:
                print(
                    f"[ПОМИЛКА] Помилка надсилання повідомлення у гільдію '{guild.name}': {e}"
                )
        else:
            print(
                f"[ПОПЕРЕДЖЕННЯ] Не знайдено відповідного каналу для надсилання повідомлення у гільдії '{guild.name}'."
            )


@bot.tree.command(name="add_bday", description="Додати або оновити день народження.")
@app_commands.describe(name="Ім'я людини", day="День (1-31)", month="Місяць (1-12)")
async def add_bday(interaction: discord.Interaction, name: str, day: int, month: int):
    """Додає або оновлює день народження в базі даних."""
    if not (1 <= day <= 31 and 1 <= month <= 12):
        await interaction.response.send_message(
            "Будь ласка, введіть дійсний день (1-31) та місяць (1-12).", ephemeral=True
        )
        return

    # Форматуємо день і місяць як "ДД/ММ"
    birthday_str = f"{day:02d}/{month:02d}"
    add_birthday(name, birthday_str)
    await interaction.response.send_message(
        f"День народження {name} ({birthday_str}) додано/оновлено.", ephemeral=True
    )


@bot.tree.command(name="list_bdays", description="Показати всі дні народження.")
async def list_bdays(interaction: discord.Interaction):
    """Показує список усіх днів народження з бази даних."""
    all_bdays = get_all_birthdays()
    if not all_bdays:
        await interaction.response.send_message(
            "У базі даних немає днів народження.", ephemeral=True
        )
        return

    response_message = "Список днів народження:\n"
    for name, bday in all_bdays:
        response_message += f"- {name}: {bday}\n"

    await interaction.response.send_message(response_message, ephemeral=True)


@bot.tree.command(name="delete_bday", description="Видалити день народження.")
@app_commands.describe(name="Ім'я людини, день народження якої потрібно видалити")
async def delete_bday(interaction: discord.Interaction, name: str):
    """Видаляє день народження з бази даних."""
    row_count = delete_birthday(name)
    if row_count > 0:
        await interaction.response.send_message(
            f"День народження {name} видалено.", ephemeral=True
        )
    else:
        await interaction.response.send_message(
            f"День народження {name} не знайдено.", ephemeral=True
        )


# Запускаємо бота
bot.run(TOKEN)
