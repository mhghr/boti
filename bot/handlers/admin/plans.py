from ..common import *


def _get_location_bucket(server: Server) -> str:
    location = (getattr(server, "location", "") or "").strip()
    return location or "بدون لوکیشن"


def _get_ordered_locations(servers: list[Server]) -> list[str]:
    locations = []
    seen_locations = set()
    for server in servers:
        location = _get_location_bucket(server)
        if location not in seen_locations:
            seen_locations.add(location)
            locations.append(location)
    return locations


def _get_location_picker_keyboard(prefix: str, locations: list[str], back_callback: str = "admin_create_account"):
    buttons = [[InlineKeyboardButton(text=f"📍 {location}", callback_data=f"{prefix}{index}")] for index, location in enumerate(locations)]
    buttons.append([InlineKeyboardButton(text="🔙 بازگشت", callback_data=back_callback)])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def handle_plan_management_callbacks(callback: CallbackQuery, bot, data: str, user_id: int) -> bool:
    if data == "admin_plans":
        admin_server_state.pop(user_id, None)
        db = SessionLocal()
        try:
            plans = db.query(Plan).all()
            await callback.message.answer(PLANS_MESSAGE, reply_markup=get_plans_keyboard(plans), parse_mode="HTML")
        finally:
            db.close()

    elif data == "admin_receipts":
        db = SessionLocal()
        try:
            pending_receipts = db.query(PaymentReceipt).filter(PaymentReceipt.status == "pending").all()
            if pending_receipts:
                for receipt in pending_receipts:
                    msg = f"💳 فیش پرداخت\n\n• پلن: {receipt.plan_name}\n• مبلغ: {receipt.amount} تومان\n• کاربر: {receipt.user_telegram_id}\n• تاریخ: {receipt.created_at}"
                    await callback.message.answer(msg, reply_markup=get_receipt_action_keyboard(receipt.id), parse_mode="HTML")
            else:
                await callback.message.answer("❌ فیش پرداخت در انتظار تاییدی وجود ندارد.", parse_mode="HTML")
        finally:
            db.close()

    # === CREATE ACCOUNT HANDLERS ===
    elif data == "admin_create_account":
        db = SessionLocal()
        try:
            plans = db.query(Plan).filter(Plan.is_active == True).all()
            if plans:
                await callback.message.answer("🔗 ساخت اکانت\n\nیکی از پلن‌های زیر را انتخاب کنید و یا پلن دلخواه بسازید:", reply_markup=get_create_account_keyboard(plans), parse_mode="HTML")
            else:
                await callback.message.answer("❌ پلن فعالی وجود ندارد. می‌توانید پلن دلخواه بسازید.", reply_markup=get_create_account_keyboard([]), parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("create_acc_plan_location_"):
        parts = data.split("_")
        plan_id = int(parts[4])
        location_index = int(parts[5])
        db = SessionLocal()
        try:
            plan = db.query(Plan).filter(Plan.id == plan_id, Plan.is_active == True).first()
            if not plan:
                await callback.message.answer("❌ پلن معتبر نیست.", parse_mode="HTML")
                return
            available_servers = get_available_active_servers(db)
            if not available_servers:
                await callback.message.answer("❌ هیچ سرور فعالی با ظرفیت خالی ثبت نشده است.", parse_mode="HTML")
                return
            locations = _get_ordered_locations(available_servers)
            if location_index < 0 or location_index >= len(locations):
                await callback.message.answer("❌ لوکیشن انتخاب‌شده معتبر نیست.", parse_mode="HTML")
                return
            selected_location = locations[location_index]
            filtered_servers = [server for server in available_servers if _get_location_bucket(server) == selected_location]
            await callback.message.answer(
                f"لوکیشن {selected_location} انتخاب شد. حالا سرور را انتخاب کنید:",
                reply_markup=get_plan_server_select_keyboard(filtered_servers, f"create_acc_server_{plan.id}_"),
                parse_mode="HTML",
            )
        finally:
            db.close()

    elif data.startswith("create_acc_plan_"):
        plan_id = int(data.split("_")[-1])
        db = SessionLocal()
        try:
            plan = db.query(Plan).filter(Plan.id == plan_id, Plan.is_active == True).first()
            if not plan:
                await callback.message.answer("❌ پلن یافت نشد یا غیرفعال است.", parse_mode="HTML")
                return
            available_servers = get_available_active_servers(db)
            if not available_servers:
                await callback.message.answer("❌ هیچ سرور فعالی با ظرفیت خالی ثبت نشده است.", parse_mode="HTML")
                return
            locations = _get_ordered_locations(available_servers)
            if len(locations) > 1:
                await callback.message.answer(
                    "ابتدا لوکیشن را برای ساخت اکانت انتخاب کنید:",
                    reply_markup=_get_location_picker_keyboard(f"create_acc_plan_location_{plan.id}_", locations),
                    parse_mode="HTML",
                )
                return
            await callback.message.answer(
                "سرور را برای ساخت اکانت انتخاب کنید:",
                reply_markup=get_plan_server_select_keyboard(available_servers, f"create_acc_server_{plan.id}_"),
                parse_mode="HTML",
            )
        finally:
            db.close()

    elif data.startswith("create_acc_server_"):
        parts = data.split("_")
        plan_id = int(parts[3])
        server_id = int(parts[4])
        db = SessionLocal()
        try:
            plan = db.query(Plan).filter(Plan.id == plan_id, Plan.is_active == True).first()
            server = db.query(Server).filter(Server.id == server_id, Server.is_active == True).first()
            if not plan or not server:
                await callback.message.answer("❌ پلن/سرور نامعتبر است.", parse_mode="HTML")
                return
            import wireguard
            wg_result = wireguard.create_wireguard_account(**build_wg_kwargs(server, str(user_id), plan, plan.name, plan.duration_days, traffic_limit_gb=plan.traffic_gb))
            if wg_result.get("success"):
                await callback.message.answer(f"✅ اکانت روی سرور {server.name} ایجاد شد.", parse_mode="HTML")
                if wg_result.get("config"):
                    await send_wireguard_config_file(callback.message, wg_result.get("config"), caption="📄 فایل اتصال")
                if wg_result.get("qr_code"):
                    await send_qr_code(callback.message, wg_result.get("qr_code"), f"QR Code - {plan.name}")
            else:
                await callback.message.answer(f"❌ خطا در ایجاد اکانت: {wg_result.get('error', 'خطای نامشخص')}", parse_mode="HTML")
        finally:
            db.close()


    elif data.startswith("create_acc_custom_server_"):
        server_id = int(data.split("_")[-1])
        state = admin_create_account_state.get(user_id)
        source_state = "admin"
        if not state:
            state = org_user_state.get(user_id)
            source_state = "org"
        if not state or state.get("step") != "server":
            await callback.message.answer("❌ ابتدا فرایند ساخت پلن دلخواه را تکمیل کنید.", parse_mode="HTML")
            return
        db = SessionLocal()
        try:
            server = db.query(Server).filter(Server.id == server_id, Server.is_active == True).first()
            if not server:
                await callback.message.answer("❌ سرور نامعتبر است.", parse_mode="HTML")
                return
            account_name = state.get("name") or "بدون پلن"
            days = int(state.get("days") or 0)
            traffic = float(state.get("traffic") or 0)
            owner_tg = str(user_id)
            import wireguard
            wg_result = wireguard.create_wireguard_account(
                **build_wg_kwargs(
                    server,
                    owner_tg,
                    None,
                    account_name,
                    days,
                    traffic_limit_gb=traffic,
                    peer_name_prefix=account_name,
                )
            )
            if wg_result.get("success"):
                await callback.message.answer(f"✅ اکانت دلخواه روی سرور {server.name} ایجاد شد.", parse_mode="HTML")
                if wg_result.get("config"):
                    await send_wireguard_config_file(callback.message, wg_result.get("config"), caption="📄 فایل اتصال")
                if wg_result.get("qr_code"):
                    await send_qr_code(callback.message, wg_result.get("qr_code"), f"QR Code - {account_name}")

                if source_state == "org":
                    created_at_text = format_jalali_date(datetime.utcnow())
                    requester = callback.from_user
                    requester_name = f"{requester.first_name or ''} {requester.last_name or ''}".strip() or "-"
                    requester_username = f"@{requester.username}" if requester.username else "ندارد"
                    notify_text = (
                        "🔔 ساخت اکانت جدید برای مشتری سازمانی\n\n"
                        f"👤 کاربر: {requester_name}\n"
                        f"🆔 آیدی تلگرام: {user_id}\n"
                        f"📛 نام کاربری: {requester_username}\n"
                        f"📦 نام اکانت: {account_name}\n"
                        f"🗓️ تعداد روز: {days}\n"
                        f"📊 ترافیک: {traffic:g} گیگ\n"
                        f"🖥️ سرور: {server.name}\n"
                        f"📅 تاریخ ساخت: {created_at_text}"
                    )
                    for admin_id in ADMIN_IDS:
                        try:
                            await callback.message.bot.send_message(
                                chat_id=admin_id,
                                text=notify_text,
                                parse_mode="HTML",
                            )
                        except Exception as e:
                            print(f"Error sending org create-account notification to admin {admin_id}: {e}")
            else:
                await callback.message.answer(f"❌ خطا در ایجاد اکانت: {wg_result.get('error', 'خطای نامشخص')}", parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("create_acc_custom_location_"):
        location_index = int(data.split("_")[-1])
        state = admin_create_account_state.get(user_id)
        source_state = "admin"
        if not state:
            state = org_user_state.get(user_id)
            source_state = "org"
        if not state or state.get("step") != "server":
            await callback.message.answer("❌ ابتدا فرایند ساخت پلن دلخواه را تکمیل کنید.", parse_mode="HTML")
            return
        db = SessionLocal()
        try:
            servers = get_available_active_servers(db)
            if not servers:
                await callback.message.answer("❌ هیچ سرور فعالی با ظرفیت خالی ثبت نشده است.", parse_mode="HTML")
                return
            locations = _get_ordered_locations(servers)
            if location_index < 0 or location_index >= len(locations):
                await callback.message.answer("❌ لوکیشن انتخاب‌شده معتبر نیست.", parse_mode="HTML")
                return
            selected_location = locations[location_index]
            filtered_servers = [server for server in servers if _get_location_bucket(server) == selected_location]
            if source_state == "admin":
                admin_create_account_state[user_id] = state
            else:
                org_user_state[user_id] = state
            await callback.message.answer(
                f"لوکیشن {selected_location} انتخاب شد. حالا سرور را انتخاب کنید:",
                reply_markup=get_plan_server_select_keyboard(filtered_servers, "create_acc_custom_server_"),
                parse_mode="HTML",
            )
        finally:
            db.close()

    elif data == "create_acc_custom":
        # Start custom plan flow - ask for name first
        admin_create_account_state[user_id] = {"step": "name"}
        await callback.message.answer(
            "📝 ساخت پلن دلخواه\n\nلطفاً یک نام برای کانفیگ وارد کنید:",
            parse_mode="HTML"
        )

    # === PLAN CALLBACKS ===
    elif data == "plan_list":
        db = SessionLocal()
        try:
            plans = db.query(Plan).all()
            if plans:
                await callback.message.answer("📋 لیست پلن‌ها:", reply_markup=get_plan_list_keyboard(plans), parse_mode="HTML")
            else:
                await callback.message.answer("❌ پلنی یافت نشد.\n\nبرای ایجاد پلن جدید، دکمه «➕ پلن جدید» را بزنید.", parse_mode="HTML")
        finally:
            db.close()

    elif data == "plan_test_account":
        db = SessionLocal()
        try:
            test_plan = db.query(Plan).filter(Plan.name == TEST_ACCOUNT_PLAN_NAME).first()
            if test_plan:
                await callback.message.answer(
                    "🧪 مدیریت اکانت تست\n\nروی هر پارامتر بزنید تا مقدار جدید را وارد کنید.",
                    reply_markup=get_test_account_keyboard(
                        days_text=str(test_plan.duration_days),
                        traffic_text=format_gb_value(test_plan.traffic_gb),
                        is_active=bool(test_plan.is_active),
                        has_plan=True,
                    ),
                    parse_mode="HTML",
                )
            else:
                await callback.message.answer(
                    "🧪 اکانت تست هنوز تعریف نشده است.",
                    reply_markup=get_test_account_keyboard(has_plan=False),
                    parse_mode="HTML",
                )
        finally:
            db.close()

    elif data == "test_account_ro":
        await callback.answer("این گزینه فقط جهت نمایش است.", show_alert=False)

    elif data == "plan_test_account_edit":
        admin_plan_state[user_id] = {"action": "test_account_setup", "step": "days"}
        await callback.message.answer("⏰ تعداد روز اکانت تست را وارد کنید:", parse_mode="HTML")

    elif data == "plan_test_set_days":
        admin_plan_state[user_id] = {"action": "test_account_setup", "field": "days"}
        await callback.message.answer("⏰ مقدار جدید مدت اکانت تست (روز) را وارد کنید:", parse_mode="HTML")

    elif data == "plan_test_set_traffic":
        admin_plan_state[user_id] = {"action": "test_account_setup", "field": "traffic"}
        await callback.message.answer("🌐 مقدار جدید ترافیک اکانت تست (گیگ) را وارد کنید:\nمثال: <code>1</code> یا <code>0.5</code>", parse_mode="HTML")

    elif data == "plan_test_toggle":
        db = SessionLocal()
        try:
            test_plan = db.query(Plan).filter(Plan.name == TEST_ACCOUNT_PLAN_NAME).first()
            if not test_plan:
                await callback.answer("اکانت تست هنوز ایجاد نشده است.", show_alert=True)
                return
            test_plan.is_active = not bool(test_plan.is_active)
            db.commit()
            await callback.answer("وضعیت اکانت تست تغییر کرد.", show_alert=False)
            await callback.message.answer(
                "🧪 مدیریت اکانت تست\n\nروی هر پارامتر بزنید تا مقدار جدید را وارد کنید.",
                reply_markup=get_test_account_keyboard(
                    days_text=str(test_plan.duration_days),
                    traffic_text=format_gb_value(test_plan.traffic_gb),
                    is_active=bool(test_plan.is_active),
                    has_plan=True,
                ),
                parse_mode="HTML",
            )
        finally:
            db.close()

    elif data == "plan_create":
        admin_server_state.pop(user_id, None)
        admin_plan_state[user_id] = {"action": "create", "plan_id": "new", "step": "name", "data": {}}
        from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
        await callback.message.answer(
            "➕ ایجاد پلن جدید\n\n"
            "📝 یک نام برای پلن خود انتخاب کنید.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔙 انصراف", callback_data="admin_plans")]
            ]),
            parse_mode="HTML"
        )
        

    elif data.startswith("plan_view_"):
        plan_id = int(data.split("_")[-1])
        db = SessionLocal()
        try:
            plan = db.query(Plan).filter(Plan.id == plan_id).first()
            if plan:
                selected_server_ids = [m.server_id for m in db.query(PlanServerMap).filter(PlanServerMap.plan_id == plan.id).all()]
                admin_plan_state[user_id] = {
                    "action": "edit",
                    "plan_id": plan_id,
                    "data": {
                        "name": plan.name,
                        "days": str(plan.duration_days),
                        "traffic": str(plan.traffic_gb),
                        "price": str(plan.price),
                        "description": plan.description or "",
                        "service_type_id": plan.service_type_id,
                        "server_ids": selected_server_ids,
                    },
                }
                service_type_name = db.query(ServiceType).filter(ServiceType.id == plan.service_type_id).first()
                service_text = service_type_name.name if service_type_name else "-"
                mapped_servers = db.query(Server).join(PlanServerMap, PlanServerMap.server_id == Server.id).filter(PlanServerMap.plan_id == plan.id).all()
                has_server_mapping = bool(mapped_servers)
                server_text = mapped_servers[0].name if has_server_mapping else "بدون سرور"
                await callback.message.answer(
                    "📦 مدیریت پلن\n\nروی هر پارامتر بزنید تا در صورت نیاز مقدار جدید وارد کنید.",
                    reply_markup=get_plan_action_keyboard(
                        plan_id=plan.id,
                        plan_name=plan.name,
                        days_text=str(plan.duration_days),
                        traffic_text=format_gb_value(plan.traffic_gb),
                        price_text=f"{plan.price:,}",
                        description_text=(plan.description or "ندارد")[:40],
                        is_active=bool(plan.is_active),
                        service_text=service_text,
                        server_text=server_text,
                        has_server_mapping=has_server_mapping,
                    ),
                    parse_mode="HTML",
                )
            else:
                await callback.message.answer("❌ پلن یافت نشد.", parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("plan_edit_"):
        plan_id = int(data.split("_")[-1])
        db = SessionLocal()
        try:
            plan = db.query(Plan).filter(Plan.id == plan_id).first()
            if plan:
                selected_server_ids = [m.server_id for m in db.query(PlanServerMap).filter(PlanServerMap.plan_id == plan.id).all()]
                admin_plan_state[user_id] = {"action": "edit", "plan_id": plan_id, "data": {"name": plan.name, "days": str(plan.duration_days), "traffic": str(plan.traffic_gb), "price": str(plan.price), "description": plan.description or "", "service_type_id": plan.service_type_id, "server_ids": selected_server_ids}}
                msg = f"✏️ ویرایش پلن: {plan.name}\n\nمی‌توانید هر فیلدی را که می‌خواهید تغییر دهید:"
                await callback.message.answer(msg, reply_markup=get_plan_edit_keyboard(plan_id), parse_mode="HTML")
            else:
                await callback.message.answer("❌ پلن یافت نشد.", parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("plan_toggle_") and not data.startswith("plan_toggle_server_"):
        plan_id = int(data.split("_")[-1])
        db = SessionLocal()
        try:
            plan = db.query(Plan).filter(Plan.id == plan_id).first()
            if plan:
                plan.is_active = not plan.is_active
                db.commit()
                status_text = "فعال" if plan.is_active else "غیرفعال"
                await callback.message.answer(f"✅ پلن «{plan.name}» {status_text} شد.", parse_mode="HTML")
                service_type_name = db.query(ServiceType).filter(ServiceType.id == plan.service_type_id).first()
                service_text = service_type_name.name if service_type_name else "-"
                mapped_servers = db.query(Server).join(PlanServerMap, PlanServerMap.server_id == Server.id).filter(PlanServerMap.plan_id == plan.id).all()
                has_server_mapping = bool(mapped_servers)
                server_text = mapped_servers[0].name if has_server_mapping else "بدون سرور"
                await callback.message.answer(
                    "📦 مدیریت پلن\n\nروی هر پارامتر بزنید تا در صورت نیاز مقدار جدید وارد کنید.",
                    reply_markup=get_plan_action_keyboard(
                        plan_id=plan.id,
                        plan_name=plan.name,
                        days_text=str(plan.duration_days),
                        traffic_text=format_gb_value(plan.traffic_gb),
                        price_text=f"{plan.price:,}",
                        description_text=(plan.description or "ندارد")[:40],
                        is_active=bool(plan.is_active),
                        service_text=service_text,
                        server_text=server_text,
                        has_server_mapping=has_server_mapping,
                    ),
                    parse_mode="HTML",
                )
            else:
                await callback.message.answer("❌ پلن یافت نشد.", parse_mode="HTML")
        except Exception as e:
            await callback.message.answer(f"❌ خطا: {str(e)}", parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("plan_delete_"):
        plan_id = int(data.split("_")[-1])
        db = SessionLocal()
        try:
            plan = db.query(Plan).filter(Plan.id == plan_id).first()
            if plan:
                plan_name = plan.name
                db.query(PlanServerMap).filter(PlanServerMap.plan_id == plan.id).delete()
                db.delete(plan)
                db.commit()
                await callback.message.answer(f"✅ پلن «{plan_name}» با موفقیت حذف شد.", parse_mode="HTML")
                # Show the plans list with remaining plans
                all_plans = db.query(Plan).all()
                await callback.message.answer(PLANS_MESSAGE, reply_markup=get_plans_keyboard(all_plans), parse_mode="HTML")
            else:
                await callback.message.answer("❌ پلن یافت نشد.", parse_mode="HTML")
        except Exception as e:
            await callback.message.answer(f"❌ خطا در حذف: {str(e)}", parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("plan_set_name_"):
        plan_id = data.split("_")[-1]
        current_state = admin_plan_state.get(user_id, {})
        current = current_state.get("data", {}).get("name", "")
        admin_plan_state[user_id] = {"action": "create" if plan_id == "new" else "edit", "plan_id": plan_id, "field": "name", "data": current_state.get("data", {})}
        await callback.message.answer(f"📝 اگر می‌خواهید نام پلن را تغییر دهید، مقدار جدید را وارد کنید:\n\nنام فعلی: <code>{current or '-'}</code>", parse_mode="HTML")

    elif data.startswith("plan_set_days_"):
        plan_id = data.split("_")[-1]
        current_state = admin_plan_state.get(user_id, {})
        current = current_state.get("data", {}).get("days", "")
        admin_plan_state[user_id] = {"action": "create" if plan_id == "new" else "edit", "plan_id": plan_id, "field": "days", "data": current_state.get("data", {})}
        await callback.message.answer(f"⏰ اگر می‌خواهید مدت را تغییر دهید، تعداد روز جدید را وارد کنید:\n\nمقدار فعلی: <code>{current or '-'}</code>", parse_mode="HTML")

    elif data.startswith("plan_set_traffic_"):
        plan_id = data.split("_")[-1]
        current_state = admin_plan_state.get(user_id, {})
        current = current_state.get("data", {}).get("traffic", "")
        admin_plan_state[user_id] = {"action": "create" if plan_id == "new" else "edit", "plan_id": plan_id, "field": "traffic", "data": current_state.get("data", {})}
        await callback.message.answer(f"🌐 اگر می‌خواهید ترافیک را تغییر دهید، مقدار جدید (گیگ) را وارد کنید:\n\nمقدار فعلی: <code>{current or '-'}</code>", parse_mode="HTML")

    elif data.startswith("plan_set_price_"):
        plan_id = data.split("_")[-1]
        current_state = admin_plan_state.get(user_id, {})
        current = current_state.get("data", {}).get("price", "")
        admin_plan_state[user_id] = {"action": "create" if plan_id == "new" else "edit", "plan_id": plan_id, "field": "price", "data": current_state.get("data", {})}
        await callback.message.answer(f"💰 اگر می‌خواهید قیمت را تغییر دهید، قیمت جدید را وارد کنید:\n\nمقدار فعلی: <code>{current or '-'}</code>", parse_mode="HTML")

    elif data.startswith("plan_set_desc_"):
        plan_id = data.split("_")[-1]
        current_state = admin_plan_state.get(user_id, {})
        current = current_state.get("data", {}).get("description", "")
        admin_plan_state[user_id] = {"action": "create" if plan_id == "new" else "edit", "plan_id": plan_id, "field": "description", "data": current_state.get("data", {})}
        await callback.message.answer(f"📄 اگر می‌خواهید توضیحات را تغییر دهید، متن جدید را وارد کنید:\n\nمقدار فعلی: <code>{current or '-'}</code>", parse_mode="HTML")

    elif data.startswith("plan_set_service_"):
        plan_id = data.split("_")[-1]
        db = SessionLocal()
        try:
            service_types = db.query(ServiceType).filter(ServiceType.is_active == True).all()
            await callback.message.answer("نوع سرویس پلن را انتخاب کنید:", reply_markup=get_service_type_picker_keyboard(service_types, f"plan_pick_service_{plan_id}_"), parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("plan_pick_service_"):
        parts = data.split("_")
        plan_id = parts[3]
        service_type_id = int(parts[-1])
        current_state = admin_plan_state.get(user_id, {"data": {}})
        current_state.setdefault("data", {})["service_type_id"] = service_type_id
        current_state["plan_id"] = plan_id
        current_state["action"] = "create" if plan_id == "new" else "edit"
        admin_plan_state[user_id] = current_state
        await callback.message.answer("✅ نوع سرویس ثبت شد.", parse_mode="HTML")

        db = SessionLocal()
        try:
            servers = db.query(Server).filter(Server.service_type_id == service_type_id, Server.is_active == True).all()
            if not servers:
                await callback.message.answer(
                    "❌ سروری اضافه نشده است. ابتدا سرور را اضافه کنید و سپس پلن را ایجاد کنید.",
                    parse_mode="HTML"
                )
                return
            await callback.message.answer(
                "سرور/سرورهای پلن را انتخاب کنید. با انتخاب سرور، پلن فوراً ذخیره می‌شود.",
                reply_markup=get_plan_servers_picker_keyboard(servers, plan_id),
                parse_mode="HTML"
            )
        finally:
            db.close()

    elif data.startswith("plan_set_servers_"):
        plan_id = data.split("_")[-1]
        st = admin_plan_state.get(user_id, {"data": {}})
        service_type_id = st.get("data", {}).get("service_type_id")
        if not service_type_id:
            await callback.message.answer("❌ ابتدا نوع سرویس را انتخاب کنید.", parse_mode="HTML")
            return
        db = SessionLocal()
        try:
            servers = db.query(Server).filter(Server.service_type_id == service_type_id, Server.is_active == True).all()
            if not servers:
                await callback.message.answer(
                    "❌ سروری اضافه نشده است. ابتدا سرور را اضافه کنید و سپس پلن را ایجاد کنید.",
                    parse_mode="HTML"
                )
                return
            await callback.message.answer("سرور/سرورهای پلن را انتخاب کنید. با انتخاب سرور، پلن فوراً ذخیره می‌شود.", reply_markup=get_plan_servers_picker_keyboard(servers, plan_id), parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("plan_toggle_server_"):
        _, _, _, plan_id_token, server_id_s = data.split("_", 4)
        server_id = int(server_id_s)
        state = admin_plan_state.get(user_id, {})
        plan_data = state.get("data", {})

        if not all([plan_data.get("name"), plan_data.get("days"), plan_data.get("traffic"), plan_data.get("price"), plan_data.get("service_type_id")]):
            await callback.message.answer("❌ لطفاً ابتدا فیلدهای الزامی پلن را تکمیل کنید.", parse_mode="HTML")
            return

        # Convert Persian/Arabic numbers to English
        days = normalize_numbers(plan_data.get("days", "0"))
        traffic = normalize_numbers(plan_data.get("traffic", "0"))
        price = normalize_numbers(plan_data.get("price", "0"))

        db = SessionLocal()
        try:
            plan_id = state.get("plan_id")
            if plan_id_token == "new" or str(plan_id) == "new":
                plan = Plan(
                    name=plan_data["name"],
                    duration_days=int(days),
                    traffic_gb=float(traffic),
                    price=int(price),
                    description=plan_data.get("description", ""),
                    is_active=True,
                    service_type_id=int(plan_data.get("service_type_id")),
                )
                db.add(plan)
                db.commit()
                state["plan_id"] = plan.id
                state["action"] = "edit"
                admin_plan_state[user_id] = state
            else:
                plan = db.query(Plan).filter(Plan.id == int(plan_id)).first()
                if not plan:
                    await callback.message.answer("❌ پلن یافت نشد.", parse_mode="HTML")
                    return
                plan.name = plan_data["name"]
                plan.duration_days = int(days)
                plan.traffic_gb = float(traffic)
                plan.price = int(price)
                plan.description = plan_data.get("description", "")
                plan.service_type_id = int(plan_data.get("service_type_id") or 0) or plan.service_type_id
                db.commit()

            existing = db.query(PlanServerMap).filter(PlanServerMap.plan_id == plan.id, PlanServerMap.server_id == server_id).first()
            if existing:
                await callback.answer("این سرور قبلاً ثبت شده است", show_alert=False)
                return

            db.add(PlanServerMap(plan_id=plan.id, server_id=server_id))
            db.commit()
            await callback.message.answer(
                f"✅ پلن «{plan.name}» با موفقیت اضافه شد.",
                reply_markup=get_plan_created_actions_keyboard(str(plan.id)),
                parse_mode="HTML",
            )
        except Exception as e:
            await callback.message.answer(f"❌ خطا در ذخیره پلن: {str(e)}", parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("plan_back_service_select_"):
        plan_id = data.split("_")[-1]
        db = SessionLocal()
        try:
            service_types = db.query(ServiceType).filter(ServiceType.is_active == True).all()
            if not service_types:
                await callback.message.answer("❌ هیچ نوع سرویس فعالی یافت نشد.", parse_mode="HTML")
                return
            await callback.message.answer(
                "نوع سرویس پلن را انتخاب کنید:",
                reply_markup=get_service_type_picker_keyboard(service_types, f"plan_pick_service_{plan_id}_"),
                parse_mode="HTML",
            )
        finally:
            db.close()

    elif data == "plan_save_new":
        state = admin_plan_state.get(user_id, {})
        plan_data = state.get("data", {})
        if not all([plan_data.get("name"), plan_data.get("days"), plan_data.get("traffic"), plan_data.get("price"), plan_data.get("service_type_id")]):
            await callback.message.answer("❌ لطفاً تمام فیلدهای الزامی (از جمله نوع سرویس) را تکمیل کنید.", parse_mode="HTML")
            return
        if not plan_data.get("server_ids"):
            await callback.message.answer("❌ در مرحله آخر باید حداقل یک سرور برای پلن انتخاب کنید.", parse_mode="HTML")
            return
        # Convert Persian/Arabic numbers to English
        days = normalize_numbers(plan_data.get("days", "0"))
        traffic = normalize_numbers(plan_data.get("traffic", "0"))
        price = normalize_numbers(plan_data.get("price", "0"))
        db = SessionLocal()
        try:
            plan = Plan(name=plan_data["name"], duration_days=int(days), traffic_gb=float(traffic),
                       price=int(price), description=plan_data.get("description", ""), is_active=True,
                       service_type_id=int(plan_data.get("service_type_id")))
            db.add(plan)
            db.commit()
            selected_servers = plan_data.get("server_ids", [])
            for sid in selected_servers:
                db.add(PlanServerMap(plan_id=plan.id, server_id=int(sid)))
            db.commit()
            if user_id in admin_plan_state:
                del admin_plan_state[user_id]
            await callback.message.answer(f"✅ پلن «{plan.name}» با موفقیت ایجاد شد!", parse_mode="HTML")
            # Show the plans list with all plans
            all_plans = db.query(Plan).all()
            await callback.message.answer(PLANS_MESSAGE, reply_markup=get_plans_keyboard(all_plans), parse_mode="HTML")
        except Exception as e:
            await callback.message.answer(f"❌ خطا در ذخیره: {str(e)}", parse_mode="HTML")
        finally:
            db.close()

    elif data.startswith("plan_save_") and data != "plan_save_new":
        plan_id = int(data.split("_")[-1])
        state = admin_plan_state.get(user_id, {})
        plan_data = state.get("data", {})
        if not all([plan_data.get("name"), plan_data.get("days"), plan_data.get("traffic"), plan_data.get("price"), plan_data.get("service_type_id")]):
            await callback.message.answer("❌ لطفاً تمام فیلدهای الزامی (از جمله نوع سرویس) را تکمیل کنید.", parse_mode="HTML")
            return
        if not plan_data.get("server_ids"):
            await callback.message.answer("❌ در مرحله آخر باید حداقل یک سرور برای پلن انتخاب کنید.", parse_mode="HTML")
            return
        # Convert Persian/Arabic numbers to English
        days = normalize_numbers(plan_data.get("days", "0"))
        traffic = normalize_numbers(plan_data.get("traffic", "0"))
        price = normalize_numbers(plan_data.get("price", "0"))
        db = SessionLocal()
        try:
            plan = db.query(Plan).filter(Plan.id == plan_id).first()
            if plan:
                plan.name = plan_data["name"]
                plan.duration_days = int(days)
                plan.traffic_gb = float(traffic)
                plan.price = int(price)
                plan.description = plan_data.get("description", "")
                plan.service_type_id = int(plan_data.get("service_type_id") or 0) or plan.service_type_id
                db.query(PlanServerMap).filter(PlanServerMap.plan_id == plan.id).delete()
                for sid in plan_data.get("server_ids", []):
                    db.add(PlanServerMap(plan_id=plan.id, server_id=int(sid)))
                db.commit()
                if user_id in admin_plan_state:
                    del admin_plan_state[user_id]
                await callback.message.answer(f"✅ پلن «{plan.name}» با موفقیت ویرایش شد!", parse_mode="HTML")
                # Show the plans list with all plans
                all_plans = db.query(Plan).all()
                await callback.message.answer(PLANS_MESSAGE, reply_markup=get_plans_keyboard(all_plans), parse_mode="HTML")
            else:
                await callback.message.answer("❌ پلن یافت نشد.", parse_mode="HTML")
        except Exception as e:
            await callback.message.answer(f"❌ خطا در ذخیره: {str(e)}", parse_mode="HTML")
        finally:
            db.close()
    else:
        return False
    return True
