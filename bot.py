import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from aiogram.enums import ParseMode
from aiogram.client.bot import DefaultBotProperties

# ======================== إعداد البوت ========================
BOT_TOKEN = "8314019736:AAG1_IOZnwENDxHq_egET-NctuI4BkGxJnA"
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

# ======================== إعداد المجموعات ========================
VIP_GROUP_ID = -1003257143205
GENERAL_GROUP_ID = -1003232189685
BROADCAST_GROUP_ID = -1003279352709
ADMIN_GROUP_ID = -1003216832217
COMPLAINT_GROUP_ID = -1003236739793

# ======================== تخزين البيانات ========================
requests = {}
completed_requests = []
canceled_requests = []
driver_requests_count = {}
all_users = set()
pending_complaints = {}
user_state = {}  # user_id: "request" / "broadcast" / "complaint" / None

# ======================== مدة تأخير إرسال الطلب للمجموعة العامة ========================
GENERAL_GROUP_DELAY = 5  # بالثواني

# ======================== /start ========================
@dp.message(CommandStart())
async def start_command(message: types.Message):
    all_users.add(message.from_user.id)
    user_state[message.from_user.id] = None
    await message.answer(
        "👋 مرحبًا!\n"
        "يمكنك استخدام الأوامر التالية:\n"
        "🚗 /request لطلب توصيلة\n"
        "📝 /complaint لتقديم شكوى"
    )

# ======================== /request ========================
async def start_request(user_id: int, username: str, full_name: str):
    user_state[user_id] = "request"

    if user_id in requests:  # تعطيل أي طلب قديم
        old_request = requests[user_id]
        for msg_id in old_request.get("message_ids", {}).values():
            try:
                await bot.edit_message_reply_markup(msg_id["chat_id"], msg_id["message_id"], reply_markup=None)
            except:
                pass

    requests[user_id] = {
        "step": "pickup",
        "username": username,
        "full_name": full_name,
        "message_ids": {},
        "cancel_button_id": None,
        "taken": False,
        "taken_by_vip": False,
        "timestamp": datetime.now()  # وقت إنشاء الطلب
    }
    await bot.send_message(user_id, "📍 أرسل لي مكان الانطلاق:")

@dp.message(F.text == "/request")
async def request_ride(message: types.Message):
    all_users.add(message.from_user.id)
    await start_request(message.from_user.id, message.from_user.username, message.from_user.full_name)

# ======================== خطوات الطلب ========================
@dp.message(lambda msg: user_state.get(msg.from_user.id) == "request")
async def handle_request_steps(message: types.Message):
    user_id = message.from_user.id
    step = requests[user_id]["step"]

    if step == "pickup":
        requests[user_id]["pickup"] = message.text
        requests[user_id]["step"] = "dropoff"
        await message.answer("🏁 أرسل لي مكان النزول:")

    elif step == "dropoff":
        requests[user_id]["dropoff"] = message.text
        requests[user_id]["step"] = "price"
        await message.answer("💰 حدد المبلغ الذي ترغب بدفعه لكل راكب:")

    elif step == "price":
        requests[user_id]["price"] = message.text
        requests[user_id]["step"] = "passengers"
        await message.answer("👥 عدد الركاب:")

    elif step == "passengers":
        requests[user_id]["passengers"] = message.text
        requests[user_id]["step"] = "time"
        await message.answer("🕒 متى تحتاج الرحلة؟ (الوقت)")

    elif step == "time":
        requests[user_id]["time"] = message.text
        requests[user_id]["step"] = "done"

        cancel_button = InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="❌ إلغاء الطلب", callback_data=f"user_cancel_{user_id}")]]
        )
        msg = await bot.send_message(
            user_id,
            "✅ تم إرسال طلبك للسائقين في انتظار موافقة أحدهم.\n"
            "ملاحظة: عندما يوافق السائق، سنرسل لك تفاصيله لتتواصل معه.",
            reply_markup=cancel_button
        )
        requests[user_id]["cancel_button_id"] = msg.message_id

        # إرسال الطلب أولًا لمجموعة VIP
        await send_request_to_group(user_id, VIP_GROUP_ID, is_vip=True)

# ======================== إرسال الطلب للمجموعات ========================
async def send_request_to_group(user_id, group_id, is_vip=False):
    data = requests[user_id]
    pickup = data["pickup"]
    dropoff = data["dropoff"]
    price = data["price"]
    passengers = data["passengers"]
    time_val = data["time"]

    accept_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🚗 خذ الطلب", callback_data=f"accept_{user_id}_{group_id}")]]
    )

    msg = await bot.send_message(
        group_id,
        f"🚗 طلب جديد للتوصيل\n\n"
        f"📍 الانطلاق: {pickup}\n"
        f"🏁 النزول: {dropoff}\n"
        f"💰 المبلغ: {price} لكل راكب\n"
        f"👥 عدد الركاب: {passengers}\n"
        f"🕒 الوقت: {time_val}\n\n"
        f"👤 الراكب: {data.get('full_name')}",
        reply_markup=accept_button
    )

    data["message_ids"][group_id] = {"message_id": msg.message_id, "chat_id": group_id}

    if is_vip:
        await asyncio.sleep(GENERAL_GROUP_DELAY)
        if user_id in requests:  # لم يقبله أحد
            await send_request_to_group(user_id, GENERAL_GROUP_ID, is_vip=False)

# ======================== إلغاء الطلب من قبل المستخدم ========================
@dp.callback_query(lambda c: c.data.startswith("user_cancel_"))
async def user_cancel_request(query: CallbackQuery):
    user_id = int(query.data.split("_")[-1])
    if user_id not in requests:
        await query.answer("❌ لا يوجد طلب نشط.", show_alert=True)
        return

    request_info = requests[user_id]
    for msg in request_info.get("message_ids", {}).values():
        try:
            await bot.delete_message(msg["chat_id"], msg["message_id"])
        except:
            pass

    try:
        await bot.edit_message_reply_markup(user_id, request_info["cancel_button_id"], reply_markup=None)
    except:
        pass

    canceled_requests.append({**request_info, "timestamp": datetime.now()})
    del requests[user_id]
    user_state[user_id] = None
    await query.message.edit_text("✅ تم إلغاء طلبك بنجاح.")
    await query.answer("تم الإلغاء")

# ======================== قبول الطلب ========================
@dp.callback_query(lambda c: c.data.startswith("accept_"))
async def accept_request(query: CallbackQuery):
    _, user_id_str, group_id_str = query.data.split("_")
    user_id = int(user_id_str)
    group_id = int(group_id_str)
    driver_id = query.from_user.id

    if user_id not in requests:
        await query.answer("❌ الطلب لم يعد متاحًا", show_alert=True)
        return

    rider_data = requests[user_id]
    driver_name = query.from_user.full_name
    driver_username = f"@{query.from_user.username}" if query.from_user.username else "بدون معرف"

    rider_data['taken'] = True
    if group_id == VIP_GROUP_ID:
        rider_data['taken_by_vip'] = True

    today_str = datetime.now().strftime("%Y-%m-%d")
    driver_requests_count.setdefault(driver_id, {}).setdefault(today_str, 0)
    driver_requests_count[driver_id][today_str] += 1

    # رسالة للراكب
    new_request_button = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🚗 طلب توصيلة جديدة", callback_data="new_request")]]
    )
    await bot.send_message(
        user_id,
        f"✅ تم قبول طلبك من السائق {driver_name}.\n"
        f"📌 تواصل معه الآن: {driver_username}\n\n"
        f"📍 الانطلاق: {rider_data['pickup']}\n"
        f"🏁 النزول: {rider_data['dropoff']}\n"
        f"💰 المبلغ: {rider_data['price']} لكل راكب\n"
        f"👥 عدد الركاب: {rider_data['passengers']}\n"
        f"🕒 الوقت: {rider_data['time']}",
        reply_markup=new_request_button
    )

    try:
        await bot.edit_message_reply_markup(user_id, rider_data["cancel_button_id"], reply_markup=None)
    except:
        pass

    for gid, msg in rider_data["message_ids"].items():
        try:
            if rider_data.get('taken_by_vip') and gid == GENERAL_GROUP_ID:
                text = "✅ تم أخذ هذا الطلب من قبل أحد السائقين في مجموعة VIP.\n📌 الطلب أصبح محجوزًا، سيتواصل معك الراكب في الخاص."
            else:
                text = "✅ تم أخذ هذا الطلب من قبل أحد السائقين.\n📌 الطلب أصبح محجوزًا، سيتواصل معك الراكب في الخاص."
            await bot.edit_message_text(chat_id=msg["chat_id"], message_id=msg["message_id"], text=text)
        except Exception as e:
            print(f"خطأ عند تعديل رسالة المجموعة {gid}: {e}")

    # رسالة للإدارة
    await bot.send_message(
        ADMIN_GROUP_ID,
        f"📌 تم قبول الطلب:\n"
        f"الراكب: {rider_data['full_name']} (@{rider_data['username']})\n"
        f"السائق: {driver_name} ({driver_username})\n"
        f"📍 الانطلاق: {rider_data['pickup']}\n"
        f"🏁 النزول: {rider_data['dropoff']}\n"
        f"💰 المبلغ: {rider_data['price']} لكل راكب\n"
        f"👥 عدد الركاب: {rider_data['passengers']}\n"
        f"🕒 الوقت: {rider_data['time']}\n"
        f"المجموعة: {'VIP' if group_id == VIP_GROUP_ID else 'عامة'}"
    )

    completed_requests.append({**rider_data, "timestamp": datetime.now()})
    del requests[user_id]
    user_state[user_id] = None
    await query.answer("✅ تم أخذ الطلب بنجاح")

# ======================== زر طلب توصيلة جديدة ========================
@dp.callback_query(lambda c: c.data == "new_request")
async def new_request_callback(query: CallbackQuery):
    await start_request(query.from_user.id, query.from_user.username, query.from_user.full_name)
    await query.answer("📌 يمكنك الآن إنشاء طلب جديد!")

# ======================== الشكاوى ========================
@dp.message(F.text == "/complaint")
async def complaint_command(message: types.Message):
    user_state[message.from_user.id] = "complaint"
    pending_complaints[message.from_user.id] = True
    await message.answer("📝 أرسل شكواك الآن برسالة واحدة وبدون تقطيع:")

@dp.message(lambda msg: pending_complaints.get(msg.from_user.id))
async def handle_complaint(message: types.Message):
    user_id = message.from_user.id
    text = message.text
    await bot.send_message(COMPLAINT_GROUP_ID, f"🚨 شكوى جديدة\n\n👤 الاسم: {message.from_user.full_name}\n📞 المعرف: @{message.from_user.username}\n📝 نص الشكوى:\n{text}")
    await message.answer("✅ تم إرسال شكواك بنجاح!")
    del pending_complaints[user_id]
    user_state[user_id] = None

# ======================== البث ========================
broadcast_state = {}

@dp.message(F.text == "/broadcast")
async def broadcast_start(message: types.Message):
    user_state[message.from_user.id] = "broadcast"
    broadcast_state[message.from_user.id] = "waiting_message"
    await message.answer("📣 أرسل لي الرسالة ليتم بثها لجميع المستخدمين:")

@dp.message(lambda msg: broadcast_state.get(msg.from_user.id) == "waiting_message")
async def broadcast_preview(message: types.Message):
    broadcast_state[message.from_user.id] = f"confirm_{message.text}"
    await message.answer(
        f"📢 هل أنت متأكد من إرسال هذه الرسالة لجميع المستخدمين؟\n\n{message.text}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="نعم، أرسل الآن ✅", callback_data="broadcast_confirm")],
                [InlineKeyboardButton(text="إلغاء ❌", callback_data="broadcast_cancel")]
            ]
        )
    )

@dp.callback_query(lambda c: c.data == "broadcast_confirm")
async def broadcast_confirm(query: CallbackQuery):
    user_id = query.from_user.id
    text = broadcast_state.get(user_id).replace("confirm_", "")
    for uid in all_users:
        try:
            await bot.send_message(uid, f"📢 {text}")
        except:
            pass
    broadcast_state[user_id] = None
    user_state[user_id] = None
    await query.message.edit_text("✅ تم بث الرسالة لجميع المستخدمين.")

@dp.callback_query(lambda c: c.data == "broadcast_cancel")
async def broadcast_cancel(query: CallbackQuery):
    user_id = query.from_user.id
    broadcast_state[user_id] = None
    user_state[user_id] = None
    await query.message.edit_text("❌ تم إلغاء البث.")

# ======================== تقرير الإدارة ========================
@dp.message(F.text == "/report")
async def report_requests(message: types.Message):
    if message.chat.id != ADMIN_GROUP_ID:
        await message.answer("❌ هذا الأمر متاح فقط لمجموعة الإدارة.")
        return

    now = datetime.now()
    last_24h = now - timedelta(hours=24)

    num_completed = sum(1 for r in completed_requests if r["timestamp"] >= last_24h)
    num_pending = sum(1 for r in requests.values() if r["timestamp"] >= last_24h)
    num_canceled = sum(1 for r in canceled_requests if r["timestamp"] >= last_24h)

    report_text = (
        f"📊 تقرير الطلبات خلال آخر 24 ساعة:\n\n"
        f"✅ الطلبات المكتملة: {num_completed}\n"
        f"⏳ الطلبات بانتظار الموافقة: {num_pending}\n"
        f"❌ الطلبات الملغاة: {num_canceled}"
    )

    await message.answer(report_text)

# ======================== تشغيل البوت ========================
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
