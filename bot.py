import asyncio
import logging
import os
import json
import re
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, \
    CallbackQuery, FSInputFile, BufferedInputFile, KeyboardButtonRequestUser
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp
import sqlite3
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
API_URL = "http://api.onlysq.ru/ai/v2"

# Логирование
logging.basicConfig(level=logging.INFO)

# Инициализация бота
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Список доступных моделей
AVAILABLE_MODELS = [
    "gpt-5.2-chat", "deepseek-v3", "deepseek-r1",
    "gemini-3-pro", "gemini-3-pro-preview", "gemini-3-flash",
    "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro",
    "gemini-2.0-flash", "gemini-2.0-flash-lite"
]

# ID премиум эмодзи
EMOJI = {
    "settings": "5870982283724328568",
    "profile": "5870994129244131212",
    "people": "5870772616305839506",
    "user_check": "5891207662678317861",
    "user_x": "5893192487324880883",
    "file": "5870528606328852614",
    "smile": "5870764288364252592",
    "chart_up": "5870930636742595124",
    "chart": "5870921681735781843",
    "home": "5873147866364514353",
    "lock": "6037249452824072506",
    "unlock": "6037496202990194718",
    "megaphone": "6039422865189638057",
    "check": "5870633910337015697",
    "cross": "5870657884844462243",
    "pencil": "5870676941614354370",
    "trash": "5870875489362513438",
    "download": "5893057118545646106",
    "clip": "6039451237743595514",
    "link": "5769289093221454192",
    "info": "6028435952299413210",
    "bot": "6030400221232501136",
    "eye": "6037397706505195857",
    "eye_hidden": "6037243349675544634",
    "send": "5963103826075456248",
    "download_file": "6039802767931871481",
    "bell": "6039486778597970865",
    "gift": "6032644646587338669",
    "clock": "5983150113483134607",
    "celebrate": "6041731551845159060",
    "font": "5870801517140775623",
    "write": "5870753782874246579",
    "media": "6035128606563241721",
    "geo": "6042011682497106307",
    "wallet": "5769126056262898415",
    "box": "5884479287171485878",
    "crypto": "5260752406890711732",
    "calendar": "5890937706803894250",
    "tag": "5886285355279193209",
    "time_passed": "5775896410780079073",
    "apps": "5778672437122045013",
    "brush": "6050679691004612757",
    "add_text": "5771851822897566479",
    "format": "5778479949572738874",
    "money": "5904462880941545555",
    "send_money": "5890848474563352982",
    "receive_money": "5879814368572478751",
    "code": "5940433880585605708",
    "loading": "5345906554510012647",
    "back": "5357809205607475128"
}

# Состояния FSM
class CodeModificationStates(StatesGroup):
    waiting_for_code = State()
    waiting_for_request = State()


# База данных
def init_db():
    conn = sqlite3.connect('code_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY, 
                  current_model TEXT DEFAULT 'gemini-3-flash',
                  last_code TEXT,
                  last_filename TEXT)''')
    conn.commit()
    conn.close()


def get_user_model(user_id):
    conn = sqlite3.connect('code_bot.db')
    c = conn.cursor()
    c.execute("SELECT current_model FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else "gemini-3-flash"


def set_user_model(user_id, model):
    conn = sqlite3.connect('code_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, current_model) VALUES (?, ?)", (user_id, model))
    conn.commit()
    conn.close()


def save_user_code(user_id, code, filename):
    conn = sqlite3.connect('code_bot.db')
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO users (user_id, last_code, last_filename) VALUES (?, ?, ?)",
              (user_id, code, filename))
    conn.commit()
    conn.close()


def get_user_code(user_id):
    conn = sqlite3.connect('code_bot.db')
    c = conn.cursor()
    c.execute("SELECT last_code, last_filename FROM users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result if result else (None, None)


# Клавиатуры
def main_keyboard(is_admin=False):
    buttons = [
        [KeyboardButton(text="Изменить код", icon_custom_emoji_id=EMOJI["pencil"])],
        [KeyboardButton(text="Сменить модель", icon_custom_emoji_id=EMOJI["settings"]), 
         KeyboardButton(text="Информация", icon_custom_emoji_id=EMOJI["info"])],
        [KeyboardButton(text="Поддержка", icon_custom_emoji_id=EMOJI["megaphone"])]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def models_keyboard(current_model):
    buttons = []
    for i in range(0, len(AVAILABLE_MODELS), 2):
        row = []
        for j in range(i, min(i + 2, len(AVAILABLE_MODELS))):
            model = AVAILABLE_MODELS[j]
            checkmark_emoji = f'<tg-emoji emoji-id="{EMOJI["check"]}">✅</tg-emoji> ' if model == current_model else ""
            row.append(InlineKeyboardButton(
                text=f"{checkmark_emoji}{model}",
                callback_data=f"model_{model}"
            ))
        buttons.append(row)
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data="back_to_menu",
        icon_custom_emoji_id=EMOJI["back"]
    )])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# AI функции
async def send_ai_request(user_id, code, request_text, model):
    """Отправка запроса к AI для модификации кода"""

    system_prompt = """Ты AI ассистент для модификации кода. 
Пользователь отправит тебе код и запрос на изменение.

ТВОЯ ЗАДАЧА:
1. Проанализировать код
2. Понять что нужно изменить, добавить или удалить
3. Вернуть ТОЛЬКО JSON в следующем формате:

{
  "summary": "Краткое описание что ты изменил/добавил/удалил",
  "changes": [
    {
      "action": "replace",
      "old_code": "точный код который нужно заменить",
      "new_code": "новый код на замену"
    },
    {
      "action": "add_after",
      "marker": "код после которого добавить",
      "new_code": "код для добавления"
    },
    {
      "action": "delete",
      "code_to_delete": "код который нужно удалить"
    }
  ]
}

ВАЖНО:
- Возвращай ТОЛЬКО JSON без комментариев и markdown
- В "old_code" и "marker" указывай ТОЧНУЮ строку из кода
- Будь максимально точным в указании фрагментов
- Действия: "replace", "add_after", "add_before", "delete"
"""

    user_prompt = f"""КОД:
```

{code}

```

ЗАПРОС:
{request_text}

Верни JSON с изменениями."""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    send = {
        "model": model,
        "request": {
            "messages": messages
        }
    }

    headers = {
        "Authorization": "Bearer openai"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=120)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            logging.info(f"Отправка запроса к AI API с моделью {model}")

            async with session.post(API_URL, json=send, headers=headers) as response:
                response_text = await response.text()
                logging.info(f"Ответ API (статус {response.status}): {response_text[:300]}")

                if response.status == 200:
                    data = await response.json()
                    ai_response = data['choices'][0]['message']['content']

                    if ai_response:
                        logging.info(f"AI ответ получен: {len(ai_response)} символов")
                        return ai_response
                    else:
                        logging.error(f"Не удалось извлечь ответ из данных: {data}")
                        return None
                else:
                    logging.error(f"API вернул статус {response.status}: {response_text}")
                    return None

    except aiohttp.ClientError as ce:
        logging.error(f"Ошибка соединения с API: {ce}")
        return None
    except Exception as e:
        logging.error(f"Общая ошибка AI запроса: {e}")
        return None


def apply_changes(code, changes_json):
    """Применение изменений к коду"""
    try:
        cleaned_json = changes_json

        if "```json" in cleaned_json:
            cleaned_json = re.sub(r'```json\s*', '', cleaned_json)
            cleaned_json = re.sub(r'```\s*$', '', cleaned_json)
        elif "```" in cleaned_json:
            cleaned_json = re.sub(r'```\s*', '', cleaned_json)

        json_match = re.search(r'\{.*\}', cleaned_json, re.DOTALL)
        if json_match:
            cleaned_json = json_match.group()

        logging.info(f"Попытка парсинга JSON: {cleaned_json[:200]}")

        changes = json.loads(cleaned_json)
        modified_code = code
        summary = changes.get("summary", "Изменения применены")

        changes_applied = 0

        for change in changes.get("changes", []):
            action = change.get("action")

            if action == "replace":
                old_code = change.get("old_code", "")
                new_code = change.get("new_code", "")
                if old_code in modified_code:
                    modified_code = modified_code.replace(old_code, new_code, 1)
                    changes_applied += 1
                    logging.info(f"Заменен фрагмент: {old_code[:50]}")
                else:
                    logging.warning(f"Фрагмент для замены не найден: {old_code[:50]}")

            elif action == "add_after":
                marker = change.get("marker", "")
                new_code = change.get("new_code", "")
                if marker in modified_code:
                    parts = modified_code.split(marker, 1)
                    modified_code = parts[0] + marker + "\n" + new_code + parts[1]
                    changes_applied += 1
                    logging.info(f"Добавлен код после: {marker[:50]}")
                else:
                    logging.warning(f"Маркер не найден: {marker[:50]}")

            elif action == "add_before":
                marker = change.get("marker", "")
                new_code = change.get("new_code", "")
                if marker in modified_code:
                    parts = modified_code.split(marker, 1)
                    modified_code = parts[0] + new_code + "\n" + marker + parts[1]
                    changes_applied += 1
                    logging.info(f"Добавлен код перед: {marker[:50]}")
                else:
                    logging.warning(f"Маркер не найден: {marker[:50]}")

            elif action == "delete":
                code_to_delete = change.get("code_to_delete", "")
                if code_to_delete in modified_code:
                    modified_code = modified_code.replace(code_to_delete, "", 1)
                    changes_applied += 1
                    logging.info(f"Удален фрагмент: {code_to_delete[:50]}")
                else:
                    logging.warning(f"Фрагмент для удаления не найден: {code_to_delete[:50]}")

        logging.info(f"Применено изменений: {changes_applied}")

        if changes_applied == 0:
            return False, None, "Не удалось применить ни одного изменения. AI указал несуществующие фрагменты кода."

        return True, modified_code, f"{summary} (применено {changes_applied} изменений)"

    except json.JSONDecodeError as je:
        logging.error(f"Ошибка JSON: {je}")
        return False, None, f"Ошибка: AI вернул некорректный JSON формат. {str(je)}"
    except Exception as e:
        logging.error(f"Ошибка применения изменений: {e}")
        return False, None, f"Ошибка применения изменений: {str(e)}"


# Обработчики команд
@dp.message(CommandStart())
async def cmd_start(message: Message):
    is_admin = message.from_user.id == ADMIN_ID

    await message.answer(
        f'<blockquote><tg-emoji emoji-id="{EMOJI["smile"]}">👋</tg-emoji> Добро пожаловать в Vest Cursor!</blockquote>\n\n'
        f'<b><tg-emoji emoji-id="{EMOJI["settings"]}">⚙️</tg-emoji> Возможности бота:</b>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["pencil"]}">📝</tg-emoji> <b>Я помогу изменить ваш код с помощью AI</b></blockquote>\n\n'
        f'<tg-emoji emoji-id="{EMOJI["check"]}">🔹</tg-emoji> Отправьте файл с кодом\n'
        f'<tg-emoji emoji-id="{EMOJI["check"]}">🔹</tg-emoji> Опишите что нужно изменить\n'
        f'<tg-emoji emoji-id="{EMOJI["check"]}">🔹</tg-emoji> Получите готовый файл\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["download"]}">👇</tg-emoji> Выберите действие:</blockquote>',
        reply_markup=main_keyboard(is_admin),
        parse_mode="HTML"
    )


@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect('code_bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    conn.close()

    await message.answer(
        f'<tg-emoji emoji-id="{EMOJI["profile"]}">👨‍💼</tg-emoji> <b>Админ панель</b>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["people"]}">👥</tg-emoji> Пользователей: {total_users}</blockquote>',
        parse_mode="HTML"
    )


# Обработчик кнопки "Изменить код"
@dp.message(F.text == "Изменить код")
async def start_code_modification(message: Message, state: FSMContext):
    await message.answer(
        f'<b><tg-emoji emoji-id="{EMOJI["file"]}">📂</tg-emoji> Отправьте файл с кодом</b>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["clip"]}">📎</tg-emoji> Прикрепите файл (.py, .js, .html, .txt и т.д.)</blockquote>\n\n'
        f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> Для отмены введите /cancel',
        parse_mode="HTML"
    )
    await state.set_state(CodeModificationStates.waiting_for_code)


# Отмена операции
@dp.message(Command("cancel"))
async def cancel_operation(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        await message.answer(
            f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> <b>Операция отменена</b>\n\n'
            f'<blockquote>Возвращаемся в главное меню</blockquote>',
            parse_mode="HTML"
        )
    else:
        await message.answer("Нет активных операций для отмены")


# Получение файла
@dp.message(CodeModificationStates.waiting_for_code, F.document)
async def receive_code_file(message: Message, state: FSMContext):
    document = message.document

    try:
        file = await bot.get_file(document.file_id)
        file_path = file.file_path

        downloaded_file = await bot.download_file(file_path)
        code_content = downloaded_file.read().decode('utf-8')

        save_user_code(message.from_user.id, code_content, document.file_name)

        await message.answer(
            f'<tg-emoji emoji-id="{EMOJI["check"]}">✅</tg-emoji> <b>Файл получен!</b>\n\n'
            f'<blockquote><tg-emoji emoji-id="{EMOJI["file"]}">📄</tg-emoji> Имя: {document.file_name}\n'
            f'<tg-emoji emoji-id="{EMOJI["box"]}">📦</tg-emoji> Размер: {len(code_content)} символов</blockquote>\n\n'
            f'<tg-emoji emoji-id="{EMOJI["write"]}">💬</tg-emoji> <b>Теперь опишите что нужно изменить:</b>\n\n'
            f'<blockquote>Например:\n'
            f'• Добавь функцию для...\n'
            f'• Измени переменную X на Y\n'
            f'• Удали функцию Z\n'
            f'• Исправь ошибку в...</blockquote>\n\n'
            f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> Для отмены введите /cancel',
            parse_mode="HTML"
        )
        await state.set_state(CodeModificationStates.waiting_for_request)
    except UnicodeDecodeError:
        await message.answer(
            f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> <b>Ошибка чтения файла</b>\n\n'
            f'<blockquote>Файл не является текстовым или имеет неподдерживаемую кодировку</blockquote>\n\n'
            f'Попробуйте другой файл',
            parse_mode="HTML"
        )
    except Exception as e:
        logging.error(f"Ошибка обработки файла: {e}")
        await message.answer(
            f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> <b>Ошибка при обработке файла</b>\n\n'
            f'<blockquote>{str(e)}</blockquote>',
            parse_mode="HTML"
        )


# Обработка неверного типа данных (не файл)
@dp.message(CodeModificationStates.waiting_for_code)
async def wrong_data_type_code(message: Message):
    await message.answer(
        f'<tg-emoji emoji-id="{EMOJI["info"]}">⚠️</tg-emoji> <b>Ожидается файл</b>\n\n'
        f'<blockquote>Пожалуйста, отправьте файл с кодом, а не текст</blockquote>\n\n'
        f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> Для отмены введите /cancel',
        parse_mode="HTML"
    )


# Получение запроса на изменение
@dp.message(CodeModificationStates.waiting_for_request, F.text)
async def receive_modification_request(message: Message, state: FSMContext):
    user_request = message.text

    if user_request.startswith('/'):
        return

    code, filename = get_user_code(message.from_user.id)

    if not code:
        await message.answer(f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> Код не найден. Отправьте файл заново.', parse_mode="HTML")
        await state.clear()
        return

    model = get_user_model(message.from_user.id)

    status_msg = await message.answer(
        f'<tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> <b>AI анализирует код...</b>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["chart"]}">📊</tg-emoji> Модель: <code>{model}</code>\n'
        f'<tg-emoji emoji-id="{EMOJI["pencil"]}">📝</tg-emoji> Размер кода: {len(code)} символов</blockquote>',
        parse_mode="HTML"
    )

    ai_response = await send_ai_request(message.from_user.id, code, user_request, model)

    if not ai_response:
        await status_msg.edit_text(
            f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> <b>Ошибка связи с AI</b>\n\n'
            f'<blockquote><tg-emoji emoji-id="{EMOJI["code"]}">🔧</tg-emoji> Возможные причины:\n'
            f'• Проблемы с интернетом\n'
            f'• API временно недоступен\n'
            f'• Неверная модель</blockquote>\n\n'
            f'<tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> Модель: <code>{model}</code>\n\n'
            f'<tg-emoji emoji-id="{EMOJI["info"]}">💡</tg-emoji> Попробуйте:\n'
            f'• Сменить модель (/start → ⚙️ Сменить модель)\n'
            f'• Повторить запрос через минуту\n'
            f'• Использовать команду /test для диагностики',
            parse_mode="HTML"
        )
        await state.clear()
        return

    await status_msg.edit_text(
        f'<tg-emoji emoji-id="{EMOJI["settings"]}">⚙️</tg-emoji> <b>Применяю изменения...</b>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["loading"]}">🔄</tg-emoji> Обработка кода...</blockquote>',
        parse_mode="HTML"
    )

    success, modified_code, summary = apply_changes(code, ai_response)

    if not success:
        await status_msg.edit_text(
            f'<tg-emoji emoji-id="{EMOJI["info"]}">⚠️</tg-emoji> <b>AI не смог автоматически изменить код</b>\n\n'
            f'<blockquote><tg-emoji emoji-id="{EMOJI["write"]}">💬</tg-emoji> Ответ AI:\n{ai_response[:500]}...</blockquote>\n\n'
            f'<blockquote><tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> {summary}</blockquote>\n\n'
            f'<tg-emoji emoji-id="{EMOJI["info"]}">💡</tg-emoji> <b>Попробуйте:</b>\n'
            f'• Переформулировать запрос более конкретно\n'
            f'• Указать точные имена функций/переменных\n'
            f'• Сменить модель AI (gemini-3-pro рекомендуется)\n'
            f'• Разбить задачу на несколько простых запросов',
            parse_mode="HTML"
        )
        await state.clear()
        return

    new_filename = f"modified_{filename}"
    modified_file_path = f"/tmp/{new_filename}"

    try:
        with open(modified_file_path, 'w', encoding='utf-8') as f:
            f.write(modified_code)

        await status_msg.delete()

        file_to_send = FSInputFile(modified_file_path)
        await message.answer_document(
            document=file_to_send,
            caption=f'<tg-emoji emoji-id="{EMOJI["check"]}">✅</tg-emoji> <b>Готово!</b>\n\n'
                    f'<blockquote><tg-emoji emoji-id="{EMOJI["code"]}">🔧</tg-emoji> {summary}</blockquote>\n\n'
                    f'<tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> <b>Модель:</b> <code>{model}</code>\n'
                    f'<tg-emoji emoji-id="{EMOJI["file"]}">📄</tg-emoji> <b>Файл:</b> <code>{new_filename}</code>',
            parse_mode="HTML"
        )

        os.remove(modified_file_path)

    except Exception as e:
        logging.error(f"Ошибка при сохранении/отправке файла: {e}")
        await status_msg.edit_text(
            f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> <b>Ошибка при создании файла</b>\n\n'
            f'<blockquote>{str(e)}</blockquote>',
            parse_mode="HTML"
        )

    await state.clear()


# Обработка неверного типа данных (не текст) при ожидании запроса
@dp.message(CodeModificationStates.waiting_for_request)
async def wrong_data_type_request(message: Message):
    await message.answer(
        f'<tg-emoji emoji-id="{EMOJI["info"]}">⚠️</tg-emoji> <b>Ожидается текстовый запрос</b>\n\n'
        f'<blockquote>Пожалуйста, опишите текстом что нужно изменить в коде</blockquote>\n\n'
        f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> Для отмены введите /cancel',
        parse_mode="HTML"
    )


# Команда для тестирования API
@dp.message(Command("test"))
async def test_api(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    model = get_user_model(message.from_user.id)
    status_msg = await message.answer(
        f'<tg-emoji emoji-id="{EMOJI["code"]}">🧪</tg-emoji> <b>Тестирование API</b>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["send"]}">📡</tg-emoji> URL: <code>{API_URL}</code>\n'
        f'<tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> Модель: <code>{model}</code></blockquote>\n\n'
        f'<tg-emoji emoji-id="{EMOJI["clock"]}">⏳</tg-emoji> Отправка тестового запроса...',
        parse_mode="HTML"
    )

    test_code = "print('Hello, World!')"
    test_request = "Добавь комментарий к этой строке"

    ai_response = await send_ai_request(message.from_user.id, test_code, test_request, model)

    if ai_response:
        await status_msg.edit_text(
            f'<tg-emoji emoji-id="{EMOJI["check"]}">✅</tg-emoji> <b>API работает!</b>\n\n'
            f'<blockquote><tg-emoji emoji-id="{EMOJI["send"]}">📡</tg-emoji> Соединение установлено\n'
            f'<tg-emoji emoji-id="{EMOJI["lock"]}">🔑</tg-emoji> Авторизация пройдена\n'
            f'<tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> Модель: <code>{model}</code>\n'
            f'<tg-emoji emoji-id="{EMOJI["chart"]}">📊</tg-emoji> Получен ответ: {len(ai_response)} символов</blockquote>\n\n'
            f'<tg-emoji emoji-id="{EMOJI["write"]}">💬</tg-emoji> <b>Фрагмент ответа:</b>\n'
            f'<blockquote>{ai_response[:300]}...</blockquote>',
            parse_mode="HTML"
        )
    else:
        await status_msg.edit_text(
            f'<tg-emoji emoji-id="{EMOJI["cross"]}">❌</tg-emoji> <b>API не отвечает</b>\n\n'
            f'<blockquote><tg-emoji emoji-id="{EMOJI["send"]}">📡</tg-emoji> URL: <code>{API_URL}</code>\n'
            f'<tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> Модель: <code>{model}</code></blockquote>\n\n'
            f'<tg-emoji emoji-id="{EMOJI["code"]}">🔧</tg-emoji> <b>Возможные причины:</b>\n'
            f'• API недоступен\n'
            f'• Проблемы с интернетом\n'
            f'• Модель не поддерживается\n\n'
            f'<tg-emoji emoji-id="{EMOJI["file"]}">📋</tg-emoji> Проверьте логи бота для деталей',
            parse_mode="HTML"
        )


# Обработчик кнопки "Сменить модель"
@dp.message(F.text == "Сменить модель")
async def show_models(message: Message):
    current_model = get_user_model(message.from_user.id)

    await message.answer(
        f'<tg-emoji emoji-id="{EMOJI["settings"]}">⚙️</tg-emoji> <b>Выбор AI модели</b>\n\n'
        f'<blockquote>Текущая: <code>{current_model}</code></blockquote>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["download"]}">👇</tg-emoji> Выберите модель:</blockquote>',
        reply_markup=models_keyboard(current_model),
        parse_mode="HTML"
    )


# Выбор модели
@dp.callback_query(F.data.startswith("model_"))
async def select_model(callback: CallbackQuery):
    model = callback.data.split("model_")[1]
    set_user_model(callback.from_user.id, model)

    await callback.message.edit_text(
        f'<tg-emoji emoji-id="{EMOJI["check"]}">✅</tg-emoji> <b>Модель изменена!</b>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> Новая модель: <code>{model}</code></blockquote>',
        parse_mode="HTML"
    )
    await callback.answer(f"✅ Модель {model} установлена!")


@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()


# Обработчик кнопки "Информация"
@dp.message(F.text == "Информация")
async def show_info(message: Message):
    current_model = get_user_model(message.from_user.id)
    is_admin = message.from_user.id == ADMIN_ID

    commands_text = f'<tg-emoji emoji-id="{EMOJI["file"]}">📋</tg-emoji> <b>Команды:</b>\n<blockquote>/start - главное меню\n/cancel - отмена операции'
    if is_admin:
        commands_text += '\n/admin - админ панель\n/test - тест API'
    commands_text += '</blockquote>\n\n'

    await message.answer(
        f'<tg-emoji emoji-id="{EMOJI["info"]}">ℹ️</tg-emoji> <b>Информация о боте</b>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> <b>Vest Cursor</b>\n\n'
        f'Бот для автоматической модификации кода с помощью AI</blockquote>\n\n'
        f'<tg-emoji emoji-id="{EMOJI["check"]}">🔹</tg-emoji> <b>Как использовать:</b>\n\n'
        f'<blockquote>1️⃣ Нажмите «Изменить код»\n'
        f'2️⃣ Отправьте файл с кодом\n'
        f'3️⃣ Опишите нужные изменения\n'
        f'4️⃣ Получите готовый файл</blockquote>\n\n'
        f'{commands_text}'
        f'<tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> <b>Текущая модель:</b> <code>{current_model}</code>\n\n'
        f'<tg-emoji emoji-id="{EMOJI["chart"]}">📊</tg-emoji> <b>Доступно моделей:</b> {len(AVAILABLE_MODELS)}',
        parse_mode="HTML"
    )


# Обработчик кнопки "Поддержка"
@dp.message(F.text == "Поддержка")
async def show_support(message: Message):
    await message.answer(
        f'<tg-emoji emoji-id="{EMOJI["megaphone"]}">🆘</tg-emoji> <b>Поддержка</b>\n\n'
        f'<blockquote>По всем вопросам и предложениям обращайтесь к администратору:</blockquote>\n\n'
        f'<tg-emoji emoji-id="{EMOJI["profile"]}">👤</tg-emoji> <b>Контакт:</b> @fuck_zaza',
        parse_mode="HTML"
    )


# Обработчик кнопки "Админ панель"
@dp.message(F.text == "Админ панель")
async def admin_panel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    conn = sqlite3.connect('code_bot.db')
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    conn.close()

    await message.answer(
        f'<tg-emoji emoji-id="{EMOJI["profile"]}">👨‍💼</tg-emoji> <b>Админ панель</b>\n\n'
        f'<blockquote><tg-emoji emoji-id="{EMOJI["people"]}">👥</tg-emoji> <b>Всего пользователей:</b> {total_users}\n'
        f'<tg-emoji emoji-id="{EMOJI["bot"]}">🤖</tg-emoji> <b>Доступно моделей:</b> {len(AVAILABLE_MODELS)}</blockquote>',
        parse_mode="HTML"
    )


# Главная функция
async def main():
    init_db()
    logging.info("🚀 Vest Cursor бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
