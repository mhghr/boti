from ..common import *

async def handle_user_profile_callbacks(callback: CallbackQuery, bot, data: str, user_id: int) -> bool:
    if data in {"profile_ro", "profile_finance_ro", "org_finance_ro"}:
        await callback.answer("این بخش فقط خواندنی است.", show_alert=False)

    elif data == "profile_finance":
        await callback.answer("بخش مشتری سازمانی غیرفعال شده است.", show_alert=True)

    elif data.startswith("cfg_renew_unavailable_"):
        data = data.replace("cfg_renew_unavailable_", "cfg_renew_")

    elif data == "cfg_renew_force_no":
        await callback.message.answer("✅ عملیات تمدید لغو شد.", parse_mode="HTML")

    elif data.startswith("cfg_renew_force_yes_"):
        data = data.replace("cfg_renew_force_yes_", "cfg_renew_")

    elif data.startswith("cfg_renew_"):
        config_id = int(data.replace("cfg_renew_", ""))
        db = SessionLocal()
        try:
            config = db.query(WireGuardConfig).filter(
                WireGuardConfig.id == config_id
            ).first()
            if not config or not config.plan_id:
                await callback.message.answer("❌ امکان تمدید برای این کانفیگ وجود ندارد.", parse_mode="HTML")
                return

            # Check if user is the owner or admin
            is_owner = str(user_id) == config.user_telegram_id
            is_admin_user = is_admin(user_id)

            if not is_owner and not is_admin_user:
                await callback.message.answer("❌ شما دسترسی ندارید.", parse_mode="HTML")
                return

            plan = db.query(Plan).filter(Plan.id == config.plan_id, Plan.is_active == True).first()
            if not plan:
                await callback.message.answer("❌ پلن این سرویس یافت نشد یا غیرفعال است.", parse_mode="HTML")
                return

            user_payment_state[user_id] = {
                "plan_id": plan.id,
                "plan_name": plan.name,
                "price": plan.price,
                "renew_config_id": config.id,
                "server_id": config.server_id,
            }

            msg = f"♻️ تمدید سرویس \"{plan.name}\"\n\n• حجم: {plan.traffic_gb} گیگ\n• مدت: {plan.duration_days} روز\n• قیمت: {plan.price} تومان\n\nروش پرداخت را انتخاب کنید:"
            await callback.message.answer(msg, reply_markup=get_payment_method_keyboard_for_renew(plan.id, config.id), parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("apply_discount_"):
        payload = data.replace("apply_discount_", "")
        parts = payload.split("_")
        plan_id = int(parts[0])
        renew_config_id = int(parts[1]) if len(parts) > 1 else None
        st = user_payment_state.get(user_id, {})
        st.update({"plan_id": plan_id, "renew_config_id": renew_config_id, "step": "discount_code"})
        user_payment_state[user_id] = st
        await callback.message.answer("🎁 کد تخفیف را ارسال کنید:", parse_mode="HTML")

    elif data == "wallet":
        db = SessionLocal()
        try:
            user = get_user(db, str(user_id))
            if user:
                await callback.message.answer(f"💰 شارژ کیف پول\n\nموجودی فعلی شما: {user.wallet_balance} تومان\n\nبرای شارژ کیف پول، لطفاً با پشتیبانی تماس بگیرید.", parse_mode="HTML")
            else:
                await callback.message.answer(WALLET_MESSAGE.format(balance=0), parse_mode="HTML")
        finally:
            db.close()

    elif data == "profile":
        db = SessionLocal()
        try:
            user = get_user(db, str(user_id))
            if user:
                configs_count = db.query(WireGuardConfig).filter(
                    WireGuardConfig.user_telegram_id == str(user_id)
                ).count()
                active_configs = db.query(WireGuardConfig).filter(
                    WireGuardConfig.user_telegram_id == str(user_id),
                    WireGuardConfig.status == "active"
                ).count()
                joined_date = format_jalali_date(user.joined_at) if user.joined_at else "نامشخص"
                member_status = "✅ فعال" if user.is_member else "❌ غیرفعال"
                await callback.message.answer(
                    "👤 حساب کاربری\n\nبرای مشاهده جزئیات، از دکمه‌های فقط‌خواندنی زیر استفاده کنید:",
                    reply_markup=get_profile_keyboard(
                        first_name=user.first_name or "-",
                        username=user.username,
                        wallet_balance=user.wallet_balance,
                        configs_count=configs_count,
                        active_configs=active_configs,
                        joined_date=joined_date,
                        member_status=member_status,
                        is_org_customer=False,
                    ),
                    parse_mode="HTML",
                )
            else:
                await callback.message.answer("❌ کاربر یافت نشد.", parse_mode="HTML")
        finally:
            db.close()
    else:
        return False
    return True
