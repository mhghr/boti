from ..common import *
from .profile import handle_user_profile_callbacks

async def handle_user_callbacks(callback: CallbackQuery, bot, data: str, user_id: int) -> bool:
    # === USER CALLBACKS ===
    if data == "buy":
        db = SessionLocal()
        try:
            plans = db.query(Plan).filter(Plan.is_active == True).all()
            if plans:
                await callback.message.answer("🛒 خرید سرویس وی پی ان\n\nیکی از پلن‌های زیر را انتخاب کنید:\n", reply_markup=get_buy_keyboard(plans), parse_mode="HTML")
            else:
                await callback.message.answer("❌ در حال حاضر پلن فعالی برای خرید وجود ندارد.", parse_mode="HTML")
        finally:
            db.close()

    elif data == "test_account_create":
        db = SessionLocal()
        try:
            user = get_or_create_user(
                db,
                str(user_id),
                callback.from_user.username,
                callback.from_user.first_name,
                callback.from_user.last_name,
            )
            if user.has_used_test_account:
                await callback.message.answer("❌ شما قبلاً از اکانت تست استفاده کرده‌اید و فقط یک‌بار مجاز هستید.", parse_mode="HTML")
                return

            plan = db.query(Plan).filter(Plan.name == TEST_ACCOUNT_PLAN_NAME, Plan.is_active == True).first()
            if not plan:
                await callback.message.answer("❌ پلن «اکانت تست» یافت نشد یا غیرفعال است.", parse_mode="HTML")
                return

            try:
                import accounts
                available_servers = get_available_servers_for_plan(db, plan.id)
                server = available_servers[0] if available_servers else None
                if not server:
                    await callback.message.answer("❌ هیچ سرور فعالی برای پلن اکانت تست یافت نشد.", parse_mode="HTML")
                    return
                wg_result = accounts.create_wireguard_account(**build_wg_kwargs(server, str(user_id), plan, plan.name, plan.duration_days))
            except Exception as e:
                await callback.message.answer(f"❌ خطا در ایجاد اکانت تست: {str(e)}", parse_mode="HTML")
                return

            if not wg_result.get("success"):
                await callback.message.answer(
                    f"❌ خطا در ایجاد اکانت تست: {wg_result.get('error', 'خطای نامشخص')}",
                    parse_mode="HTML"
                )
                return

            user.has_used_test_account = True
            db.commit()

            client_ip = wg_result.get("client_ip", "N/A")
            config_text = wg_result.get("config", "")
            await callback.message.answer(
                (
                    f"✅ اکانت تست شما ساخته شد.\n\n"
                    f"• پلن: {plan.name}\n"
                    f"• مدت: {plan.duration_days} روز\n"
                    f"• حجم: {plan.traffic_gb} گیگ\n"
                    f"• قیمت: {plan.price:,} تومان\n"
                    f"• آی‌پی: {client_ip}\n\n"
                    "📥 فایل کانفیگ و QR Code ارسال شد."
                ),
                parse_mode="HTML"
            )

            if config_text:
                await send_wireguard_config_file(
                    callback.message,
                    config_text,
                    caption="📄 فایل اتصال (اکانت تست)",
                )

            if wg_result.get("qr_code"):
                await send_qr_code(
                    callback.message,
                    wg_result.get("qr_code"),
                    caption=(
                        "📷 QR Code اکانت تست\n\n"
                        f"🏷 نام کانفیگ: {wg_result.get('peer_comment', 'نامشخص')}\n"
                        f"📦 پلن انتخابی: {plan.name}"
                    ),
                )
        finally:
            db.close()

    elif data == "software_ro":
        await callback.answer("📦 برای دانلود روی لینک‌های زیر کلیک کنید", show_alert=True)

    elif data == "software":
        sw_list = get_software_list()
        if not sw_list:
            await callback.message.answer("❌ هیچ نرم‌افزاری ثبت نشده است.", parse_mode="HTML")
            return
        await callback.message.answer(
            "📱 نرم‌افزارهای مورد نیاز\n\n"
            "یکی از نرم‌افزارها را انتخاب کنید:",
            reply_markup=get_software_list_keyboard(sw_list),
            parse_mode="HTML"
        )

    elif data.startswith("software_"):
        index_str = data.replace("software_", "")
        if not index_str.isdigit():
            await callback.answer("دستور نامعتبر است.", show_alert=True)
            return
        index = int(index_str)
        sw_list = get_software_list()
        if 0 <= index < len(sw_list):
            sw = sw_list[index]
            await callback.message.answer(
                f"📱 لینک‌های دانلود {sw.get('name', '')}\n\n"
                "برای نصب روی لینک دستگاه خود کلیک کنید:",
                reply_markup=get_software_links_keyboard(sw, index),
                parse_mode="HTML"
            )
        else:
            await callback.answer("❌ نرم‌افزار یافت نشد.", show_alert=True)

    elif data == "configs":
        db = SessionLocal()
        try:
            configs = db.query(WireGuardConfig).filter(
                WireGuardConfig.user_telegram_id == str(user_id)
            ).order_by(WireGuardConfig.created_at.desc()).all()
            if configs:
                await callback.message.answer(
                    "🔗 کانفیگ های من\n\nبرای مشاهده جزئیات، کانفیگ موردنظر را انتخاب کنید:",
                    reply_markup=get_configs_keyboard(configs),
                    parse_mode="HTML"
                )
            else:
                await callback.message.answer(MY_CONFIGS_MESSAGE, parse_mode="HTML")
        finally:
            db.close()

    elif data in {"org_create_account", "org_finance", "org_finance_settlement", "org_finance_ro"}:
        await callback.answer("بخش مشتری سازمانی غیرفعال شده است.", show_alert=True)

    elif data.startswith("cfg_view_"):
        config_id = data.replace("cfg_view_", "")
        db = SessionLocal()
        try:
            config = db.query(WireGuardConfig).filter(
                WireGuardConfig.id == int(config_id)
            ).first()
            if not config:
                await callback.message.answer("❌ کانفیگ یافت نشد.", parse_mode="HTML")
                return

            # Check if user is the owner or admin
            is_owner = str(user_id) == config.user_telegram_id
            is_admin_user = is_admin(user_id)

            if not is_owner and not is_admin_user:
                await callback.message.answer("❌ شما دسترسی ندارید.", parse_mode="HTML")
                return

            plan = db.query(Plan).filter(Plan.id == config.plan_id).first() if config.plan_id else None
            plan_traffic_bytes, remaining_bytes = get_config_remaining_bytes(config, plan)
            supports_traffic = supports_traffic_tracking(config)
            consumed_bytes = get_config_consumed_bytes(config) if supports_traffic else 0
            expires_at = get_config_expires_at(config, plan)

            can_renew = can_renew_config_now(config, plan)
            server = db.query(Server).filter(Server.id == config.server_id).first() if config.server_id else None
            config_name = (config.plan_name or "").strip() or f"کانفیگ {config.id}"
            await callback.message.answer(
                "📋 مدیریت کانفیگ:",
                reply_markup=get_config_detail_keyboard(
                    config.id,
                    can_renew=can_renew,
                    details={
                        "name": config_name,
                        "ip": config.client_ip,
                        "server": server.name if server else "-",
                        "consumed": (format_traffic_size(consumed_bytes) if supports_traffic else "نامشخص در حالت SSH"),
                        "remaining": (format_traffic_size(remaining_bytes) if supports_traffic and plan_traffic_bytes else "نامشخص در حالت SSH"),
                        "expires_at": format_jalali_date(expires_at),
                        "status": "🔴 غیرفعال" if config.status != "active" else "🟢 فعال",
                    },
                ),
                parse_mode="HTML"
            )
        finally:
            db.close()

    elif data == "cfg_changeloc_hdr":
        await callback.answer("📍 برای انتخاب سرور روی گزینه‌های زیر کلیک کنید", show_alert=True)

    elif data == "cfg_changeloc_none":
        await callback.answer("❌ لوکیشن دیگری در دسترس نیست", show_alert=True)

    elif data.startswith("cfg_changeloc_srv_"):
        parts = data.split("_")
        config_id = int(parts[3])
        target_server_id = int(parts[4])

        db = SessionLocal()
        try:
            old_config = db.query(WireGuardConfig).filter(
                WireGuardConfig.id == config_id,
                WireGuardConfig.user_telegram_id == str(user_id)
            ).first()
            if not old_config:
                await callback.message.answer("❌ کانفیگ یافت نشد.", parse_mode="HTML")
                return

            if old_config.status != "active":
                await callback.message.answer("❌ فقط کانفیگ‌های فعال قابل انتقال هستند.", parse_mode="HTML")
                return

            target_server = db.query(Server).filter(
                Server.id == target_server_id, Server.is_active == True
            ).first()
            if not target_server:
                await callback.message.answer("❌ سرور مقصد یافت نشد.", parse_mode="HTML")
                return

            old_server = db.query(Server).filter(Server.id == old_config.server_id).first() if old_config.server_id else None
            plan = db.query(Plan).filter(Plan.id == old_config.plan_id).first() if old_config.plan_id else None

            now = datetime.utcnow()
            expires_at = get_config_expires_at(old_config, plan)
            if expires_at and expires_at > now:
                remaining_days = max(1, (expires_at - now).days)
            else:
                remaining_days = old_config.duration_days or 1

            supports_traffic = supports_traffic_tracking(old_config)
            if supports_traffic:
                _, remaining_bytes = get_config_remaining_bytes(old_config, plan)
                remaining_traffic_gb = max(0.1, remaining_bytes / (1024 ** 3)) if remaining_bytes else (old_config.traffic_limit_gb or 0)
            else:
                remaining_traffic_gb = old_config.traffic_limit_gb

            if old_server:
                try:
                    import accounts
                    accounts.delete_wireguard_peer(
                        mikrotik_host=old_server.host,
                        mikrotik_user=old_server.username,
                        mikrotik_pass=old_server.password,
                        mikrotik_port=old_server.api_port,
                        wg_interface="",
                        client_ip=old_config.client_ip,
                    )
                except Exception as e:
                    print(f"Failed to delete old peer during location change: {e}")

            import accounts
            plan_name = old_config.plan_name or (plan.name if plan else "")
            wg_result = accounts.create_wireguard_account(
                **build_wg_kwargs(
                    target_server,
                    str(user_id),
                    plan,
                    plan_name,
                    remaining_days,
                    traffic_limit_gb=remaining_traffic_gb if remaining_traffic_gb else None,
                )
            )

            if not wg_result.get("success"):
                await callback.message.answer(
                    f"❌ خطا در ایجاد اکانت جدید: {wg_result.get('error', 'خطای نامشخص')}",
                    parse_mode="HTML"
                )
                return

            old_config.status = "transferred"
            db.commit()

            new_client_ip = wg_result.get("client_ip", "-")
            new_server_name = target_server.name or "-"
            new_expires_at = wg_result.get("expires_at")
            new_expires_text = format_jalali_date(new_expires_at) if new_expires_at else "-"

            await callback.message.answer(
                f"✅ انتقال لوکیشن با موفقیت انجام شد\n\n"
                f"📦 کانفیگ جدید:\n"
                f"🖥 سرور: {new_server_name}\n"
                f"👤 نام کاربری: {new_client_ip}\n"
                f"📅 انقضا: {new_expires_text}\n"
                f"📊 حجم: {remaining_traffic_gb if remaining_traffic_gb else 'نامحدود'} گیگابایت",
                parse_mode="HTML"
            )

            if wg_result.get("config"):
                await send_wireguard_config_file(callback.message, wg_result.get("config"), caption="📄 فایل اتصال")
            if wg_result.get("qr_code"):
                await send_qr_code(callback.message, wg_result.get("qr_code"), "QR Code - New Location")

        finally:
            db.close()

    elif data.startswith("cfg_changeloc_"):
        config_id = int(data.replace("cfg_changeloc_", ""))

        db = SessionLocal()
        try:
            config = db.query(WireGuardConfig).filter(
                WireGuardConfig.id == config_id,
                WireGuardConfig.user_telegram_id == str(user_id)
            ).first()
            if not config:
                await callback.message.answer("❌ کانفیگ یافت نشد.", parse_mode="HTML")
                return

            if config.status != "active":
                await callback.message.answer("❌ فقط کانفیگ‌های فعال قابل انتقال هستند.", parse_mode="HTML")
                return

            current_server = db.query(Server).filter(Server.id == config.server_id).first() if config.server_id else None
            current_location = (current_server.location or "").strip() if current_server else ""

            plan = db.query(Plan).filter(Plan.id == config.plan_id).first() if config.plan_id else None
            service_type_id = plan.service_type_id if plan else (current_server.service_type_id if current_server else None)

            if not service_type_id:
                await callback.message.answer("❌ نوع سرویس قابل تشخیص نیست.", parse_mode="HTML")
                return

            all_active = db.query(Server).filter(
                Server.service_type_id == service_type_id,
                Server.is_active == True
            ).all()

            available = [
                s for s in all_active
                if (s.location or "").strip() != current_location
            ]

            if not available:
                await callback.message.answer("❌ هیچ لوکیشن دیگری با این سرویس در دسترس نیست.", parse_mode="HTML")
                return

            await callback.message.answer(
                "📍 انتخاب لوکیشن جدید\n\n"
                "لطفاً لوکیشن و سرور مورد نظر را انتخاب کنید:",
                reply_markup=get_change_location_keyboard(config_id, available),
                parse_mode="HTML"
            )
        finally:
            db.close()

    elif data.startswith("cfg_ro_"):
        await callback.answer("این بخش فقط جهت نمایش است.", show_alert=False)

    elif data == "admin_user_info_ro":
        await callback.answer("این بخش فقط جهت نمایش است.", show_alert=False)


    elif data.startswith("cfg_disable_"):
        config_id = int(data.replace("cfg_disable_", ""))
        db = SessionLocal()
        try:
            cfg = db.query(WireGuardConfig).filter(WireGuardConfig.id == config_id, WireGuardConfig.user_telegram_id == str(user_id)).first()
            if not cfg:
                await callback.message.answer("❌ کانفیگ یافت نشد.", parse_mode="HTML")
                return
            if cfg.status != "active":
                await callback.answer("این کانفیگ از قبل غیرفعال است.", show_alert=True)
                return

            server = db.query(Server).filter(Server.id == cfg.server_id, Server.is_active == True).first() if cfg.server_id else None
            if server:
                try:
                    import accounts
                    accounts.disable_wireguard_peer(
                        mikrotik_host=server.host,
                        mikrotik_user=server.username,
                        mikrotik_pass=server.password,
                        mikrotik_port=server.api_port,
                        wg_interface=server.wg_interface,
                        client_ip=cfg.client_ip,
                    )
                except Exception as e:
                    print(f"User disable config failed ({cfg.client_ip}): {e}")

            cfg.status = "disabled"
            db.commit()
            await callback.message.answer("✅ کانفیگ غیرفعال شد.", parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("cfg_delete_confirm_"):
        config_id = int(data.replace("cfg_delete_confirm_", ""))
        db = SessionLocal()
        try:
            cfg = db.query(WireGuardConfig).filter(WireGuardConfig.id == config_id, WireGuardConfig.user_telegram_id == str(user_id)).first()
            if not cfg:
                await callback.message.answer("❌ کانفیگ یافت نشد.", parse_mode="HTML")
                return

            client_ip = cfg.client_ip
            server = db.query(Server).filter(Server.id == cfg.server_id, Server.is_active == True).first()
            if not server:
                await callback.message.answer("❌ سرور این کانفیگ یافت نشد؛ حذف انجام نشد.", parse_mode="HTML")
                return

            import accounts

            try:
                deleted = accounts.delete_wireguard_peer(
                    mikrotik_host=server.host,
                    mikrotik_user=server.username,
                    mikrotik_pass=server.password,
                    mikrotik_port=server.api_port,
                    wg_interface=server.wg_interface,
                    client_ip=client_ip,
                    fallback_host=server.domain or server.host,
                )
            except Exception as e:
                print(f"User delete config failed ({client_ip}): {e}")
                await callback.message.answer("❌ حذف اکانت از روی سرور ناموفق بود؛ کانفیگ حذف نشد.", parse_mode="HTML")
                return

            if not deleted:
                await callback.message.answer("❌ حذف اکانت از روی سرور ناموفق بود؛ کانفیگ حذف نشد.", parse_mode="HTML")
                return

            db.delete(cfg)
            db.commit()

            await callback.message.answer(f"✅ کانفیگ {client_ip} با موفقیت از سرور و دیتابیس حذف شد.", parse_mode="HTML")

            configs = db.query(WireGuardConfig).filter(WireGuardConfig.user_telegram_id == str(user_id)).all()
            if configs:
                await callback.message.answer("🔗 کانفیگ‌های شما:", reply_markup=get_user_configs_keyboard(configs), parse_mode="HTML")
            else:
                await callback.message.answer("🔗 شما هیچ کانفیگ فعالی ندارید.", parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("cfg_delete_cancel_"):
        await callback.message.answer("❎ حذف لینک لغو شد.", parse_mode="HTML")

    elif data.startswith("cfg_delete_"):
        config_id = int(data.replace("cfg_delete_", ""))
        db = SessionLocal()
        try:
            cfg = db.query(WireGuardConfig).filter(WireGuardConfig.id == config_id, WireGuardConfig.user_telegram_id == str(user_id)).first()
            if not cfg:
                await callback.message.answer("❌ کانفیگ یافت نشد.", parse_mode="HTML")
                return
            await callback.message.answer(
                "⚠️ مطمئن هستید که می‌خواهید این لینک را حذف کنید؟",
                reply_markup=get_user_config_confirm_delete_keyboard(config_id),
                parse_mode="HTML"
            )
        finally:
            db.close()

    elif data.startswith("cfg_financial_"):
        config_id = int(data.replace("cfg_financial_", ""))
        db = SessionLocal()
        try:
            config = db.query(WireGuardConfig).filter(WireGuardConfig.id == config_id).first()
            if not config:
                await callback.answer("کانفیگ یافت نشد.", show_alert=True)
                return
            if str(user_id) != config.user_telegram_id and not is_admin(user_id):
                await callback.answer("شما دسترسی ندارید.", show_alert=True)
                return
            await callback.answer("بخش مشتری سازمانی غیرفعال شده است.", show_alert=True)
        finally:
            db.close()

    elif await handle_user_profile_callbacks(callback, bot, data, user_id):
        return True

    else:
        return False
    return True
