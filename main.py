import asyncio
import html
import logging
import os  # Додано для роботи зі змінними середовища
from aiogram import Bot, Dispatcher, types, F
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import ReplyKeyboardBuilder

# --- НАЛАШТУВАННЯ (БЕЗПЕЧНО) ---
# Ми беремо дані зі змінних середовища хостингу, а не пишемо їх прямо в код
BOT_TOKEN = (os.getenv("BOT_TOKEN") or "").strip()
admin_id_value = (os.getenv("ADMIN_ID") or "").strip()

# Перевірка конфігурації до створення бота.
if not BOT_TOKEN:
    raise ValueError("Помилка: Не задана змінна середовища BOT_TOKEN!")
try:
    ADMIN_ID = int(admin_id_value)
except ValueError as exc:
    raise ValueError("Помилка: ADMIN_ID має бути цілим числом!") from exc
if ADMIN_ID == 0:
    raise ValueError("Помилка: ADMIN_ID не може дорівнювати 0!")

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

class ReportState(StatesGroup):
    waiting_for_photos = State()

# --- КЛАВІАТУРИ ---
def get_start_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="👉 Тиць 👈")
    return builder.as_markup(resize_keyboard=True)

def get_yes_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Так")
    return builder.as_markup(resize_keyboard=True)

def get_forward_keyboard():
    builder = ReplyKeyboardBuilder()
    builder.button(text="Вперед")
    builder.button(text="Далі")
    return builder.as_markup(resize_keyboard=True)

# --- ХЕНДЛЕРИ ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    await state.clear()
    welcome_text = (
        "🛡 Вітаємо у боті ГО «Варта Доступності»!\n\n"
        "Перетвори бачення бар'єрів у реальні зміни міста та отримуй винагороду:\n\n"
        "1️⃣ Бачиш недоступний пандус, сходи чи аптеку?\n"
        "2️⃣ Зроби 2-3 фото та заповни чек-лист (1 хв).\n"
        "3️⃣ Ми сформуємо скаргу до ДІАМ/Держлікслужби.\n"
        "4️⃣ Отримай бонуси після перевірки об'єкта!\n\n"
        "👇 Натисни кнопку нижче, щоб розпочати фіксацію:"
    )
    await message.answer(welcome_text, reply_markup=get_start_keyboard())

@dp.message(F.text == "👉 Тиць 👈")
async def step_one(message: types.Message):
    await message.answer("1️⃣ Бачиш недоступний пандус, сходи чи аптеку?", reply_markup=get_yes_keyboard())

@dp.message(F.text == "Так")
async def step_two(message: types.Message):
    await message.answer("2️⃣ Зроби 2-3 фото та заповни чек-лист (1 хв).", reply_markup=get_forward_keyboard())

@dp.message(F.text.in_({"Вперед", "Далі"}))
async def ask_for_photos(message: types.Message, state: FSMContext):
    await state.set_state(ReportState.waiting_for_photos)
    await state.update_data(photos=[])
    await message.answer("📸 Будь ласка, надішліть 1-3 фотографії об'єкта (можна відправляти по одній).\nКоли закінчите, напишіть текстом короткий опис проблеми (наприклад: 'Пандус зламаний біля аптеки на вул. Хрещатик').")

@dp.message(ReportState.waiting_for_photos, F.photo)
async def handle_photos(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get('photos', [])
    
    if len(photos) >= 3:
        await message.answer("⚠️ Ви вже надіслали максимальну кількість фото (3). Тепер напишіть текстовий опис проблеми.")
        return

    photos.append(message.photo[-1].file_id)
    await state.update_data(photos=photos)
    await message.answer(f"✅ Фото додано ({len(photos)}/3). Надішліть ще фото або напишіть текстовий опис для завершення.")

@dp.message(ReportState.waiting_for_photos, F.text)
async def finish_report(message: types.Message, state: FSMContext):
    data = await state.get_data()
    photos = data.get('photos', [])
    user_description = (message.text or "").strip()
    if not photos:
        await message.answer("Спочатку надішліть хоча б одне фото об'єкта.")
        return
    if not user_description:
        await message.answer("Будь ласка, додайте короткий текстовий опис проблеми.")
        return
    user = message.from_user
    if user is None:
        logging.warning("Отримано заявку без даних відправника")
        await message.answer("Не вдалося визначити відправника заявки. Спробуйте ще раз у приватному чаті.")
        return

    user_name = html.escape(user.full_name)
    user_username = html.escape(f"@{user.username}" if user.username else "немає")

    safe_description = html.escape(user_description)
    admin_text = (
        f"🚨 <b>НОВА ЗАЯВКА!</b>\n\n"
        f"👤 Від: {user_name} ({user_username})\n"
        f"🆔 ID: <code>{user.id}</code>\n\n"
        f"📝 Опис: {safe_description}\n"
        f"🖼 Кількість фото: {len(photos)}"
    )
    if len(admin_text) > 4096:
        await message.answer("Опис задовгий. Скоротіть його та надішліть знову.")
        return

    try:
        for photo in photos:
            await bot.send_photo(chat_id=ADMIN_ID, photo=photo)
        await bot.send_message(chat_id=ADMIN_ID, text=admin_text, parse_mode="HTML")
    except TelegramAPIError:
        logging.exception("Не вдалося надіслати заявку адміну")
        await message.answer(
            "Не вдалося передати заявку. Ваші дані залишилися в діалозі; "
            "спробуйте надіслати опис ще раз пізніше."
        )
        return

    thank_you_text = (
        "Дякуємо за вашу активну громадянську позицію та внесок у безбар'єрність нашого міста! 🛡\n"
        "Ми прийняли вашу заявку. Наша команда перевірить надані дані, сформує офіційне звернення до контролюючих органів та зв'яжеться з вами протягом 14 робочих днів щодо статусу розгляду та нарахування винагороди.\n"
        "Разом робимо простір доступним для кожного!"
    )
    
    builder = ReplyKeyboardBuilder()
    builder.button(text="/start")
    
    await message.answer(thank_you_text, reply_markup=builder.as_markup(resize_keyboard=True))
    await state.clear()

# --- ЗАПУСК ---
async def main():
    print("Бот запущено в робочому режимі!")
    # Цей рядок допомагає уникнути помилок, якщо бот перезавантажиться
    await bot.delete_webhook(drop_pending_updates=True) 
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
