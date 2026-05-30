from aiogram.types import Message
from ..common import *

@dp.message(lambda message: (not is_admin(message.from_user.id)) and message.from_user.id in user_payment_state and user_payment_state.get(message.from_user.id, {}).get("step") == "discount_code")
async def handle_discount_code_input(message: Message):
    user_id = message.from_user.id
    code_text = message.text.strip().upper()
    state = user_payment_state.get(user_id, {})
    plan_id = state.get("plan_id")
    if not plan_id:
        await message.answer("❌ ابتدا پلن را انتخاب کنید.", parse_mode="HTML")
        return

    db = SessionLocal()
    try:
        plan = db.query(Plan).filter(Plan.id == plan_id).first()
        gift = db.query(GiftCode).filter(GiftCode.code == code_text, GiftCode.is_active == True).first()
        if not plan or not gift:
            await message.answer("❌ کد تخفیف نامعتبر است.", parse_mode="HTML")
            return
        if gift.expires_at and gift.expires_at < datetime.utcnow():
            await message.answer("❌ اعتبار این کد تخفیف تمام شده است.", parse_mode="HTML")
            return
        if gift.used_count >= gift.max_uses:
            await message.answer("❌ ظرفیت استفاده این کد تکمیل شده است.", parse_mode="HTML")
            return

        discount_amount = 0
        if gift.discount_percent:
            discount_amount = int((plan.price * gift.discount_percent) / 100)
        elif gift.discount_amount:
            discount_amount = gift.discount_amount

        final_price = max(plan.price - discount_amount, 0)
        state["discount_amount"] = discount_amount
        state["price"] = final_price
        state["gift_code"] = gift.code
        state.pop("step", None)
        user_payment_state[user_id] = state

        renew_config_id = state.get("renew_config_id")
        kb = get_payment_method_keyboard_for_renew(plan.id, renew_config_id) if renew_config_id else get_payment_method_keyboard(plan.id)
        await message.answer(
            f"✅ کد اعمال شد.\nقیمت اصلی: {plan.price} تومان\nمیزان تخفیف: {discount_amount} تومان\nقیمت نهایی: {final_price} تومان",
            reply_markup=kb,
            parse_mode="HTML"
        )
    finally:
        db.close()

@dp.message(lambda message: (not is_admin(message.from_user.id)) and message.from_user.id in user_payment_state and user_payment_state.get(message.from_user.id, {}).get("method") == "wallet_topup" and user_payment_state.get(message.from_user.id, {}).get("step") == "amount_input")
async def handle_wallet_topup_amount(message: Message):
    user_id = message.from_user.id
    amount_text = normalize_numbers((message.text or "").strip()).replace(",", "")
    if not amount_text.isdigit() or int(amount_text) <= 0:
        await message.answer("❌ لطفاً مبلغ معتبر (عدد) وارد کنید.", parse_mode="HTML")
        return
    amount = int(amount_text)
    state = user_payment_state.get(user_id, {})
    state["amount"] = amount
    state["step"] = "receipt_upload"
    user_payment_state[user_id] = state
    await message.answer("✅ مبلغ ثبت شد. حالا لطفاً عکس فیش واریز را ارسال کنید.", parse_mode="HTML")


# Receipt photo handler
@dp.message(lambda message: (not is_admin(message.from_user.id)) and message.from_user.id in user_payment_state and user_payment_state.get(message.from_user.id, {}).get("method") in ["card_to_card", "wallet_topup"])
async def handle_receipt_photo(message: Message):
    user_id = message.from_user.id
    
    # Check if user is in payment state and expecting a receipt
    if user_id not in user_payment_state:
        return
    
    payment_info = user_payment_state[user_id]
    if payment_info.get("method") not in ["card_to_card", "wallet_topup"]:
        return
    if payment_info.get("method") == "wallet_topup" and payment_info.get("step") != "receipt_upload":
        return
    
    # Check if message has a photo
    if not message.photo:
        await message.answer("❌ لطفاً تصویر فیش واریزی را ارسال کنید.", parse_mode="HTML")
        return
    
    # Get the photo file ID
    photo = message.photo[-1]  # Get the highest resolution
    file_id = photo.file_id
    
    # Save receipt to database
    db = SessionLocal()
    try:
        is_wallet_topup = payment_info.get("method") == "wallet_topup"
        receipt = PaymentReceipt(
            user_telegram_id=str(user_id),
            plan_id=(None if is_wallet_topup else payment_info["plan_id"]),
            plan_name=("شارژ کیف پول" if is_wallet_topup else payment_info["plan_name"]),
            amount=(payment_info.get("amount") if is_wallet_topup else payment_info["price"]),
            payment_method=("wallet_topup" if is_wallet_topup else "card_to_card"),
            server_id=(None if is_wallet_topup else payment_info.get("server_id")),
            renew_config_id=(None if is_wallet_topup else payment_info.get("renew_config_id")),
            receipt_file_id=file_id,
            status="pending"
        )
        db.add(receipt)

        gift_code = payment_info.get("gift_code")
        if payment_info.get("method") != "wallet_topup" and gift_code:
            gift = db.query(GiftCode).filter(GiftCode.code == gift_code).first()
            if gift:
                gift.used_count = (gift.used_count or 0) + 1

        db.commit()
        
        # Clear payment state
        del user_payment_state[user_id]
        
        # Send confirmation to user
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await message.answer(
            "سپاس از اعتماد شما . پس از تایید مبلغ مورد نظر به اعتبار شما اضافه خواهد شد ." if payment_info.get("method") == "wallet_topup" else "✅ فیش پرداخت دریافت شد!\n\n⏰ لطفاً منتظر تایید پرداخت توسط مدیریت باشید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🏠 منوی اصلی", callback_data="back_to_main")]
            ]),
            parse_mode="HTML"
        )
        
        # Get user info for admin notification
        user = message.from_user
        user_display_name = f"{user.first_name}"
        if user.last_name:
            user_display_name += f" {user.last_name}"
        user_username = f"@{user.username}" if user.username else "ندارد"
        
        # Forward receipt to admin
        for admin_id in ADMIN_IDS:
            try:
                # Send photo with user info in caption
                if payment_info.get("method") == "wallet_topup":
                    caption_text = f"💳 درخواست شارژ کیف پول\n\n👤 اطلاعات کاربر:\n• نام: {user_display_name}\n• آیدی: {user_id}\n• نام کاربری: {user_username}\n\n💰 اطلاعات پرداخت:\n• نوع: شارژ کیف پول\n• مبلغ: {payment_info.get('amount', 0)} تومان\n• روش پرداخت: کارت به کارت"
                else:
                    caption_text = f"💳 درخواست تایید پرداخت جدید\n\n👤 اطلاعات کاربر:\n• نام: {user_display_name}\n• آیدی: {user_id}\n• نام کاربری: {user_username}\n\n💰 اطلاعات پرداخت:\n• پلن: {payment_info['plan_name']}\n• مبلغ: {payment_info['price']} تومان\n• روش پرداخت: کارت به کارت"
                await message.bot.send_photo(
                    chat_id=admin_id,
                    photo=file_id,
                    caption=caption_text,
                    reply_markup=get_receipt_action_keyboard(receipt.id),
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Error sending to admin: {e}")
                
    except Exception as e:
        await message.answer(f"❌ خطا در ذخیره فیش: {str(e)}", parse_mode="HTML")
    finally:
        db.close()

@dp.message(lambda message: (not is_admin(message.from_user.id)) and message.from_user.id in org_user_state and org_user_state.get(message.from_user.id, {}).get("step") in {"name", "days", "traffic"})
async def handle_org_create_account_input(message: Message):
    user_id = message.from_user.id
    state = org_user_state.get(user_id, {})
    step = state.get("step")
    text = (message.text or "").strip()

    if step == "name":
        if not text:
            await message.answer("❌ نام معتبر وارد کنید.", parse_mode="HTML")
            return
        state["name"] = text
        state["step"] = "days"
        org_user_state[user_id] = state
        await message.answer("تعداد روز را وارد کنید:", parse_mode="HTML")
        return

    if step == "days":
        txt = normalize_numbers(text)
        if not txt.isdigit() or int(txt) <= 0:
            await message.answer("❌ تعداد روز نامعتبر است.", parse_mode="HTML")
            return
        state["days"] = int(txt)
        state["step"] = "traffic"
        org_user_state[user_id] = state
        await message.answer("مقدار ترافیک (گیگ) را وارد کنید:", parse_mode="HTML")
        return

    if step == "traffic":
        try:
            traffic = float(normalize_numbers(text))
        except ValueError:
            traffic = -1
        if traffic <= 0:
            await message.answer("❌ مقدار ترافیک نامعتبر است.", parse_mode="HTML")
            return
        state["traffic"] = traffic
        state["step"] = "server"
        org_user_state[user_id] = state

        db = SessionLocal()
        try:
            wireguard_type = db.query(ServiceType).filter(ServiceType.code == "wireguard").first()
            if not wireguard_type:
                await message.answer("❌ سرویس WireGuard تعریف نشده است.", parse_mode="HTML")
                return
            servers = db.query(Server).filter(Server.service_type_id == wireguard_type.id, Server.is_active == True).all()
            if not servers:
                await message.answer("❌ سرور فعالی وجود ندارد.", parse_mode="HTML")
                return
            await message.answer("سرور مدنظر را انتخاب کنید:", reply_markup=get_plan_server_select_keyboard(servers, "create_acc_custom_server_"), parse_mode="HTML")
        finally:
            db.close()


@dp.message(lambda message: (not is_admin(message.from_user.id)) and message.from_user.id in org_user_state and org_user_state.get(message.from_user.id, {}).get("step") == "settlement_receipt")
async def handle_org_settlement_receipt(message: Message):
    user_id = message.from_user.id
    state = org_user_state.get(user_id, {})
    if not message.photo:
        await message.answer("❌ لطفاً تصویر فیش را ارسال کنید.", parse_mode="HTML")
        return

    file_id = message.photo[-1].file_id

    db = SessionLocal()
    try:
        db_user = get_user(db, str(user_id))
        financials = calculate_org_user_financials(db, db_user) if db_user else None
        active_links_count = len(financials["active_configs"]) if financials else 0
        total_links_count = db.query(WireGuardConfig).filter(WireGuardConfig.user_telegram_id == str(user_id)).count()
        amount = int((financials or {}).get("debt_amount") or state.get("amount") or 0)

        receipt = PaymentReceipt(
            user_telegram_id=str(user_id),
            plan_id=None,
            plan_name="تسویه سازمانی",
            amount=amount,
            payment_method="org_settlement",
            receipt_file_id=file_id,
            status="pending",
        )
        db.add(receipt)
        db.commit()

        await message.answer("✅ فیش تسویه ارسال شد. پس از تایید ادمین، تسویه اعمال می‌شود.", parse_mode="HTML")

        user = message.from_user
        user_name = f"{user.first_name or ''} {user.last_name or ''}".strip() or "-"
        total_traffic_gb = (financials or {}).get("total_traffic_gb", 0)
        for admin_id in ADMIN_IDS:
            try:
                await message.bot.send_photo(
                    chat_id=admin_id,
                    photo=file_id,
                    caption=(
                        "💼 درخواست تسویه مشتری سازمانی\n\n"
                        f"👤 نام: {user_name}\n"
                        f"🆔 آیدی: {user_id}\n"
                        f"🔗 تعداد لینک‌ها: {total_links_count} (فعال: {active_links_count})\n"
                        f"📊 ترافیک مصرفی: {total_traffic_gb:.2f} گیگابایت\n"
                        f"💰 میزان بدهکاری: {amount:,} تومان"
                    ),
                    reply_markup=get_receipt_action_keyboard(receipt.id),
                    parse_mode="HTML",
                )
            except Exception as e:
                print(f"Error sending org settlement receipt to admin: {e}")
    finally:
        db.close()
        org_user_state.pop(user_id, None)
