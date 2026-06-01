from aiogram import filters
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from ..common import *

@dp.message(filters.CommandStart())
async def start_handler(message: Message, bot):
    user = message.from_user
    user_id = user.id
    db = SessionLocal()
    try:
        is_member = await check_channel_member(bot, user_id, CHANNEL_ID)
        if is_member:
            db_user, is_new_user = get_or_create_user(
                db,
                str(user_id),
                user.username,
                user.first_name,
                user.last_name,
                return_created=True,
            )
            if db_user.is_blocked:
                await message.answer("⛔ حساب شما توسط ادمین مسدود شده است.", parse_mode="HTML")
                return
            db_user.is_member = True
            db.commit()
            await message.answer(WELCOME_MESSAGE, reply_markup=get_main_keyboard(db_user.is_admin), parse_mode="HTML")
            if is_new_user:
                await message.answer("🎉 خوش آمدید! عضویت شما در کانال تایید شد.", parse_mode="HTML")
                for admin_id in ADMIN_IDS:
                    try:
                        username_text = f"@{db_user.username}" if db_user.username else "ندارد"
                        await bot.send_message(
                            chat_id=int(admin_id),
                            text=(
                                "👤 عضو جدید به ربات اضافه شد\n\n"
                                f"• آیدی: {db_user.telegram_id}\n"
                                f"• نام: {db_user.first_name or '-'} {db_user.last_name or ''}\n"
                                f"• نام کاربری: {username_text}"
                            ),
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
        else:
            db_user = get_user(db, str(user_id))
            if db_user:
                db_user.is_member = False
                db.commit()
            await message.answer(NOT_MEMBER_MESSAGE.format(channel_username=CHANNEL_USERNAME), parse_mode="HTML")
    except Exception as e:
        print(f"Error in start_handler: {e}")
        await message.answer("❌ خطایی رخ داد. لطفاً دوباره تلاش کنید.")
    finally:
        db.close()


@dp.message(filters.Command("register_panel"))
async def register_panel_handler(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("❌ شما دسترسی ادمین ندارید.")
        return
    pending = load_pending_panel()
    if not pending:
        await message.answer("❌ درخواست پنل جدیدی وجود ندارد.\n\nابتدا agent را روی سرور اجرا کنید.")
        return
    msg = f"🔔 درخواست ثبت پنل جدید\n\n📍 اطلاعات پنل:\n• نام: {pending.get('name', 'Unknown')}\n• آی پی: {pending.get('ip', 'Unknown')}\n• لوکیشن: {pending.get('location', 'Unknown')}\n• پورت: {pending.get('port', 'Unknown')}\n• مسیر: {pending.get('path', '/')}\n\n📊 اطلاعات سیستم:\n• هاست نیم: {pending.get('system_info', {}).get('hostname', 'Unknown')}\n• سیستم عامل: {pending.get('system_info', {}).get('os', 'Unknown')}"
    await message.answer(msg, reply_markup=get_pending_panel_keyboard(), parse_mode="HTML")




@dp.message(lambda message: not is_admin(message.from_user.id) and (message.text or "").strip() in {
    "🛒 خرید جدید", "📱 نرم‌افزارها", "🔗 کانفیگ‌های من", "📚 آموزش اتصال", "💳 شارژ کیف پول", "🧪 اکانت تست", "👤 حساب کاربری"
})
async def handle_user_menu_buttons(message: Message):
    text = (message.text or "").strip()
    user_id = message.from_user.id

    if text == "🛒 خرید جدید":
        db = SessionLocal()
        try:
            plans = db.query(Plan).filter(Plan.is_active == True).all()
            if plans:
                await message.answer("🛒 خرید سرویس وی پی ان\n\nیکی از پلن‌های زیر را انتخاب کنید:\n", reply_markup=get_buy_keyboard(plans), parse_mode="HTML")
            else:
                await message.answer("❌ در حال حاضر پلن فعالی برای خرید وجود ندارد.", parse_mode="HTML")
        finally:
            db.close()
        return

    if text == "📱 نرم‌افزارها":
        sw_list = get_software_list()
        if not sw_list:
            await message.answer("❌ هیچ نرم‌افزاری ثبت نشده است.", parse_mode="HTML")
            return
        await message.answer(
            "📱 نرم‌افزارهای مورد نیاز\n\n"
            "یکی از نرم‌افزارها را انتخاب کنید:",
            reply_markup=get_software_list_keyboard(sw_list),
            parse_mode="HTML"
        )
        return

    if text == "🔗 کانفیگ‌های من":
        db = SessionLocal()
        try:
            configs = db.query(WireGuardConfig).filter(WireGuardConfig.user_telegram_id == str(user_id)).order_by(WireGuardConfig.created_at.desc()).all()
            if configs:
                await message.answer("🔗 کانفیگ های من\n\nبرای مشاهده جزئیات، کانفیگ موردنظر را انتخاب کنید:", reply_markup=get_configs_keyboard(configs), parse_mode="HTML")
            else:
                await message.answer(MY_CONFIGS_MESSAGE, parse_mode="HTML")
        finally:
            db.close()
        return

    if text == "💳 شارژ کیف پول":
        db = SessionLocal()
        try:
            user = get_user(db, str(user_id))
            await message.answer(WALLET_MESSAGE.format(balance=user.wallet_balance if user else 0), parse_mode="HTML")
        finally:
            db.close()
        return

    if text == "👤 حساب کاربری":
        await message.answer("برای مشاهده جزئیات حساب از دکمه‌های داخل صفحه استفاده کنید.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="👤 نمایش حساب", callback_data="profile")]]), parse_mode="HTML")
        return

    if text == "🧪 اکانت تست":
        await message.answer("برای ایجاد اکانت تست روی دکمه زیر بزنید.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🧪 ایجاد اکانت تست", callback_data="test_account_create")]]), parse_mode="HTML")
        return

    if text == "📚 آموزش اتصال":
        await message.answer("📚 لیست آموزش‌ها:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📚 آموزش‌ها", callback_data="user_tutorials")]]), parse_mode="HTML")
        return
