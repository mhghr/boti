import json
import os
import io
import re
import subprocess
from datetime import datetime
from datetime import datetime, timedelta

from aiogram import Dispatcher
from aiogram.types import Message, CallbackQuery, FSInputFile, BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton

from database import SessionLocal, engine
from models import User, Panel, Plan, PaymentReceipt, WireGuardConfig, GiftCode, ServiceType, Server, PlanServerMap, ServiceTutorial, Representative
from config import (
    CHANNEL_ID, CHANNEL_USERNAME, ADMIN_IDS,
    admin_plan_state, admin_create_account_state, user_payment_state,
    admin_user_search_state, admin_wallet_adjust_state, admin_discount_state, admin_receipt_reject_state,
    admin_service_type_state, admin_server_state, admin_tutorial_state, admin_representative_state,
    admin_card_state, admin_software_links_state,
    org_user_state,
    AGENT_BOT_DOCKER_IMAGE, AGENT_BOT_CONTAINER_PREFIX, AGENT_BOT_DOCKER_NETWORK
)

from keyboards import (
    get_main_keyboard, get_admin_keyboard, get_panels_keyboard,
    get_pending_panel_keyboard, get_plans_keyboard, get_plan_list_keyboard,
    get_plan_action_keyboard, get_plan_edit_keyboard, get_buy_keyboard,
    get_payment_method_keyboard, get_receipt_action_keyboard, get_receipt_done_keyboard, get_create_account_keyboard,
    get_configs_keyboard, get_config_detail_keyboard, get_found_users_keyboard, get_found_configs_keyboard, get_admin_search_keyboard,
    get_admin_user_manage_keyboard, get_payment_method_keyboard_for_renew,
    get_admin_config_detail_keyboard, get_admin_config_confirm_delete_keyboard,
    get_admin_user_configs_keyboard, get_test_account_keyboard, get_service_types_keyboard,
    get_servers_service_type_keyboard, get_servers_keyboard, get_server_detail_keyboard,
    get_service_type_picker_keyboard, get_plan_servers_picker_keyboard, get_plan_created_actions_keyboard, get_plan_server_select_keyboard,
    get_representatives_keyboard, get_representative_action_keyboard,
    get_profile_keyboard, get_org_finance_keyboard,
    get_wallet_keyboard, get_admin_card_keyboard, get_admin_software_links_keyboard,
    get_software_links_keyboard
)

from texts import (
    WELCOME_MESSAGE, NOT_MEMBER_MESSAGE, ADMIN_MESSAGE, PANELS_MESSAGE, SEARCH_USER_MESSAGE, PLANS_MESSAGE, TEST_ACCOUNT_PLAN_NAME
)


from services.user_service import (
    get_or_create_user,
    get_user,
    is_admin,
    calculate_org_user_financials as _calculate_org_user_financials,
    search_users,
)
from services.plan_service import (
    get_plan_servers,
    get_server_active_config_count,
    get_available_servers_for_plan,
    build_wg_kwargs,
)
from services.card_service import get_card_info, set_card_info
from services.software_links_service import get_software_links, set_software_link
from services.server_service import evaluate_server_parameters

dp = Dispatcher()


# Helper functions
def normalize_numbers(text: str) -> str:
    """Convert Persian/Arabic numbers to English numbers."""
    if not text:
        return text
    # Persian numbers: ۰۱۲۳۴۵۶۷۸۹
    # Arabic numbers: ٠١٢٣٤٥٦٧٨٩
    persian_digits = '۰۱۲۳۴۵۶۷۸۹'
    arabic_digits = '٠١٢٣٤٥٦٧٨٩'
    english_digits = '0123456789'
    
    result = text
    for i, d in enumerate(persian_digits):
        result = result.replace(d, english_digits[i])
    for i, d in enumerate(arabic_digits):
        result = result.replace(d, english_digits[i])
    
    return result


def load_pending_panel():
    try:
        if os.path.exists("pending_panel.json"):
            with open("pending_panel.json", "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return None


def delete_pending_panel():
    try:
        if os.path.exists("pending_panel.json"):
            os.remove("pending_panel.json")
    except Exception:
        pass


async def check_channel_member(bot, user_id: int, channel_id: str) -> bool:
    try:
        from aiogram.enums import ChatMemberStatus
        chat_id = f"@{channel_id}" if not channel_id.startswith("-") else channel_id
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in [ChatMemberStatus.MEMBER, ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.CREATOR]
    except Exception:
        return False





def _sanitize_container_name(name: str) -> str:
    base = re.sub(r"[^a-zA-Z0-9_-]", "-", name or "agent")
    return base.strip("-").lower() or "agent"


def start_representative_container(rep: Representative) -> tuple[bool, str]:
    container_name = f"{AGENT_BOT_CONTAINER_PREFIX}_{rep.id}_{_sanitize_container_name(rep.name)}"
    env_vars = [
        "-e", f"BOT_TOKEN={rep.bot_token}",
        "-e", f"ADMIN_ID={rep.admin_telegram_id}",
        "-e", f"CHANNEL_ID={rep.channel_id}",
        "-e", f"CHANNEL_USERNAME={rep.channel_id}",
    ]
    cmd = ["docker", "run", "-d", "--restart", "unless-stopped", "--name", container_name]
    if AGENT_BOT_DOCKER_NETWORK:
        cmd += ["--network", AGENT_BOT_DOCKER_NETWORK]
    cmd += env_vars + [AGENT_BOT_DOCKER_IMAGE]

    try:
        subprocess.run(["docker", "rm", "-f", container_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        run_result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        rep.docker_container_name = container_name
        return True, (run_result.stdout.strip() or "کانتینر اجرا شد.")
    except Exception as e:
        return False, str(e)


def stop_representative_container(container_name: str) -> tuple[bool, str]:
    if not container_name:
        return False, "نام کانتینر ثبت نشده است."
    try:
        result = subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, text=True, check=True)
        return True, (result.stdout.strip() or "کانتینر متوقف و حذف شد.")
    except Exception as e:
        return False, str(e)


def format_traffic(total_bytes: int) -> str:
    gb = (total_bytes or 0) / (1024 ** 3)
    return f"{gb:.2f} GB"




def get_config_limits(config: WireGuardConfig, plan: Plan | None):
    duration_days = config.duration_days if config.duration_days is not None else (plan.duration_days if plan else None)
    traffic_limit_gb = config.traffic_limit_gb if config.traffic_limit_gb is not None else (plan.traffic_gb if plan else None)
    return duration_days, traffic_limit_gb


def get_config_expires_at(config: WireGuardConfig, plan: Plan | None):
    expires_at = config.expires_at
    duration_days, _ = get_config_limits(config, plan)
    if not expires_at and duration_days:
        expires_at = config.created_at + timedelta(days=duration_days)
    return expires_at


def is_ssh_account_config(config: WireGuardConfig) -> bool:
    return bool(str(config.public_key or "").startswith("npvt-ssh://"))


def supports_traffic_tracking(config: WireGuardConfig) -> bool:
    return not is_ssh_account_config(config)


def get_config_consumed_bytes(config: WireGuardConfig) -> int:
    return int((config.cumulative_rx_bytes or 0) + (config.cumulative_tx_bytes or 0))


def get_config_remaining_bytes(config: WireGuardConfig, plan: Plan | None) -> tuple[int, int]:
    if not supports_traffic_tracking(config):
        return 0, 0
    _, traffic_limit_gb = get_config_limits(config, plan)
    limit_bytes = int((traffic_limit_gb or 0) * (1024 ** 3)) if traffic_limit_gb else 0
    consumed = get_config_consumed_bytes(config)
    remaining = max(limit_bytes - consumed, 0) if limit_bytes else 0
    return limit_bytes, remaining

def can_renew_config_now(config: WireGuardConfig, plan: Plan | None) -> bool:
    """Return True when config is eligible for direct renew action."""
    if not config:
        return False

    now = datetime.utcnow()
    plan_traffic_bytes, _ = get_config_remaining_bytes(config, plan)
    consumed_bytes = get_config_consumed_bytes(config) if supports_traffic_tracking(config) else 0
    expires_at = get_config_expires_at(config, plan)

    is_expired_by_date = bool(expires_at and expires_at <= now)
    is_expired_by_traffic = bool(plan_traffic_bytes and consumed_bytes >= plan_traffic_bytes)
    is_disabled = config.status in ["expired", "revoked", "disabled"]
    is_notified = bool(config.expiry_alert_sent if not supports_traffic_tracking(config) else (
        config.low_traffic_alert_sent
        or config.expiry_alert_sent
        or config.threshold_alert_sent
    ))
    return bool(is_expired_by_date or is_expired_by_traffic or is_disabled or is_notified)



def build_admin_user_info_message(db, user_obj: User) -> str:
    username = f"@{user_obj.username}" if user_obj.username else "ندارد"
    joined_date = format_jalali_date(user_obj.joined_at) if user_obj.joined_at else "نامشخص"
    all_configs_count = db.query(WireGuardConfig).filter(WireGuardConfig.user_telegram_id == user_obj.telegram_id).count()
    blocked_status = "⛔ مسدود" if user_obj.is_blocked else "✅ فعال"
    msg = (
        f"👤 اطلاعات کاربر:\n\n"
        f"شناسه: {user_obj.telegram_id}\n"
        f"نام: {user_obj.first_name} {user_obj.last_name or ''}\n"
        f"نام کاربری: {username}\n"
        f"موجودی: {user_obj.wallet_balance:,} تومان\n"
        f"تاریخ عضویت: {joined_date}\n"
        f"وضعیت عضویت: {'✅ فعال' if user_obj.is_member else '❌ غیرفعال'}\n"
        f"ادمین: {'✅ بله' if user_obj.is_admin else '❌ خیر'}\n"
        f"وضعیت دسترسی: {blocked_status}\n"
        f"تعداد لینک/کانفیگ‌ها: {all_configs_count}"
    )
    return msg


def get_admin_user_manage_view(db, user_obj: User, show_wallet_actions: bool = False, show_finance_panel: bool = False):
    username = f"@{user_obj.username}" if user_obj.username else "ندارد"
    joined_date = format_jalali_date(user_obj.joined_at) if user_obj.joined_at else "نامشخص"
    all_configs_count = db.query(WireGuardConfig).filter(WireGuardConfig.user_telegram_id == user_obj.telegram_id).count()
    return (
        "👤 مدیریت کاربر",
        get_admin_user_manage_keyboard(
            user_id=user_obj.id,
            telegram_id=user_obj.telegram_id,
            full_name=f"{user_obj.first_name or ''} {user_obj.last_name or ''}".strip() or "ندارد",
            username=username,
            wallet_balance=user_obj.wallet_balance or 0,
            joined_date=joined_date,
            is_member=bool(user_obj.is_member),
            is_admin=bool(user_obj.is_admin),
            config_count=all_configs_count,
            is_blocked=bool(user_obj.is_blocked),
            show_wallet_actions=show_wallet_actions,
            show_finance_panel=show_finance_panel,
        ),
    )


async def send_qr_code(sender, qr_base64: str, caption: str = None, chat_id: int = None):
    """
    Send QR code image from base64 string.
    Can use with message, callback.message, or bot.
    """
    import base64
    try:
        # Remove data:image/png;base64, prefix if present
        if ',' in qr_base64:
            qr_base64 = qr_base64.split(',')[1]
        
        # Decode base64
        image_data = base64.b64decode(qr_base64)
        
        # Create BufferedInputFile from bytes
        photo_file = BufferedInputFile(image_data, filename="qr_code.png")
        
        # Send photo
        if chat_id:
            # Using bot.send_photo
            await sender.send_photo(chat_id=chat_id, photo=photo_file, caption=caption)
        else:
            # Using message.answer_photo
            await sender.answer_photo(photo=photo_file, caption=caption)
                
    except Exception as e:
        print(f"Error sending QR code: {e}")


async def send_wireguard_config_file(sender, config_text: str, caption: str = None, chat_id: int = None):
    """Send SSH tunnel URI as a text file."""
    import tempfile
    import os

    if not config_text:
        return

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            tmp.write(config_text)
            tmp_path = tmp.name

        document = FSInputFile(tmp_path, filename="npvt-ssh.txt")
        if chat_id:
            await sender.send_document(chat_id=chat_id, document=document, caption=caption or "📄 فایل کانفیگ WireGuard")
        else:
            await sender.answer_document(document=document, caption=caption or "📄 فایل کانفیگ WireGuard")
    except Exception as e:
        print(f"Error sending config file: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def parse_ip_range(input_str: str) -> dict:
    """
    Parse IP range input in two formats:
    1. CIDR: x.y.z.0/24
    2. Range: x.y.z.10-x.y.z.220 or x.y.z.10-220
    
    Returns dict with keys: base_ip, start_ip, end_ip, cidr, is_range
    """
    input_str = input_str.strip()
    
    # Check if it's a range format (contains -)
    if '-' in input_str and '/' not in input_str:
        # Format: x.y.z.10-x.y.z.220 or x.y.z.10-220
        parts = input_str.split('-')
        if len(parts) == 2:
            try:
                start_ip = parts[0].strip()
                end_part = parts[1].strip()

                # Parse start IP
                start_parts = start_ip.split('.')
                if len(start_parts) != 4:
                    return None
                base_prefix = '.'.join(start_parts[:3])
                start_last = int(start_parts[3])

                # Parse end IP - could be full IP or just last octet
                if '.' in end_part:
                    # Full IP like 192.168.30.220
                    end_parts = end_part.split('.')
                    if len(end_parts) != 4:
                        return None
                    end_base = '.'.join(end_parts[:3])
                    if end_base != base_prefix:
                        return None
                    end_last = int(end_parts[3])
                else:
                    # Just last octet like 220
                    end_last = int(end_part)

                # Required bounds for custom range mode
                if not (10 <= start_last <= 250 and 10 <= end_last <= 250 and start_last <= end_last):
                    return None

                return {
                    # Persist as full network-base IP to keep octets intact later
                    # (e.g. 192.168.30.0 instead of 192.168.30)
                    'base_ip': f"{base_prefix}.0",
                    'start_ip': start_ip,
                    'end_ip': f"{base_prefix}.{end_last}",
                    'cidr': None,
                    'is_range': True,
                    'start_last': start_last,
                    'end_last': end_last
                }
            except (ValueError, IndexError):
                return None
    
    # Check if it's CIDR format
    if '/' in input_str:
        # Format: x.y.z.0/24
        parts = input_str.split('/')
        if len(parts) == 2:
            ip = parts[0].strip()
            mask = int(parts[1].strip())
            
            # Calculate start and end IPs based on CIDR
            ip_parts = ip.split('.')
            if len(ip_parts) == 4 and 0 <= mask <= 32:
                ip_int = (int(ip_parts[0]) << 24) + (int(ip_parts[1]) << 16) + (int(ip_parts[2]) << 8) + int(ip_parts[3])
                mask_int = (0xFFFFFFFF << (32 - mask)) & 0xFFFFFFFF
                start_int = ip_int & mask_int
                end_int = start_int | (0xFFFFFFFF - mask_int)
                
                return {
                    'base_ip': ip,
                    'start_ip': f"{(start_int >> 24) & 0xFF}.{(start_int >> 16) & 0xFF}.{(start_int >> 8) & 0xFF}.{start_int & 0xFF}",
                    'end_ip': f"{(end_int >> 24) & 0xFF}.{(end_int >> 16) & 0xFF}.{(end_int >> 8) & 0xFF}.{end_int & 0xFF}",
                    'cidr': mask,
                    'is_range': False,
                    'start_last': start_int & 0xFF,
                    'end_last': end_int & 0xFF
                }
    
    # Default: treat as simple base (backward compatibility)
    parts = input_str.split('.')
    if len(parts) == 4:
        base = '.'.join(parts[:3])
        return {
            'base_ip': input_str,
            'start_ip': f"{base}.1",
            'end_ip': f"{base}.254",
            'cidr': 24,
            'is_range': False,
            'start_last': 1,
            'end_last': 254
        }
    
    return None


def get_server_field_prompt(field: str, step_num: int = None, total_steps: int = None) -> tuple:
    prompts = {
        "name": ("نام سرور را وارد کنید:", False),
        "host": ("IP/Host سرور را وارد کنید:", False),
        "api_port": ("پورت SSH سرور را وارد کنید. مثال: 22", False),
        "username": ("یوزرنیم لاگین SSH سرور را وارد کنید:", False),
        "password": ("پسورد لاگین SSH سرور را وارد کنید:", False),
        "wg_interface": ("نام اینترفیس وایرگارد:", False),
        "wg_server_public_key": ("Public Key سرور:", False),
        "wg_server_endpoint": ("Endpoint سرور:", False),
        "wg_server_port": ("پورت وایرگارد:", False),
        "wg_client_network_base": ("رنج IP را وارد کنید:\n• فرمت CIDR: 192.168.30.0/24\n• فرمت رنج: 192.168.30.10-192.168.30.220", False),
        "wg_client_dns": ("DNS (مثلاً 8.8.8.8,1.0.0.1):", False),
        "capacity": ("ظرفیت سرور (تعداد اکانت):", True)
    }
    msg, is_last = prompts.get(field, ("مقدار را وارد کنید:", False))
    return msg, is_last


def get_server_creation_steps():
    return ["name", "host", "api_port", "username", "password", "wg_interface", "wg_server_public_key", "wg_server_endpoint", "wg_server_port", "wg_client_network_base", "wg_client_dns", "capacity"]




def get_plan_field_prompt(field: str) -> str:
    prompts = {
        "name": "📝 یک نام برای پلن خود انتخاب کنید:",
        "days": "⏰ تعداد روز پلن را وارد کنید:",
        "traffic": "📊 مقدار ترافیک پلن (گیگ) را وارد کنید:",
        "price": "💰 قیمت پلن را به تومان وارد کنید:",
        "description": "📄 توضیحات پلن را وارد کنید (اختیاری):",
    }
    return prompts.get(field, "لطفاً مقدار را وارد کنید:")

def get_plan_creation_summary(data: dict) -> str:
    return (
        "➕ ایجاد پلن جدید\n\n"
        "اطلاعات وارد شده:\n"
        f"• نام: {data.get('name', '➖')}\n"
        f"• مدت: {data.get('days', '➖')} روز\n"
        f"• ترافیک: {data.get('traffic', '➖')} گیگ\n"
        f"• قیمت: {data.get('price', '➖')} تومان"
    )


def parse_positive_number(value: str, allow_float: bool = False):
    """Parse positive numeric input from Persian/Arabic/English digits."""
    normalized = normalize_numbers((value or "").strip()).replace("٫", ".").replace(",", ".")
    if allow_float:
        number = float(normalized)
    else:
        number = int(normalized)
    if number <= 0:
        raise ValueError
    return number


def format_gb_value(value) -> str:
    """Render traffic in GB without trailing .0 for integer values."""
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return str(value)
    if numeric.is_integer():
        return str(int(numeric))
    return f"{numeric:g}"


def gregorian_to_jalali(g_date: datetime):
    gy = g_date.year - 1600
    gm = g_date.month - 1
    gd = g_date.day - 1

    g_day_no = 365 * gy + (gy + 3) // 4 - (gy + 99) // 100 + (gy + 399) // 400
    g_days_in_month = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    for i in range(gm):
        g_day_no += g_days_in_month[i]
    if gm > 1 and ((gy + 1600) % 4 == 0 and ((gy + 1600) % 100 != 0 or (gy + 1600) % 400 == 0)):
        g_day_no += 1
    g_day_no += gd

    j_day_no = g_day_no - 79
    j_np = j_day_no // 12053
    j_day_no %= 12053

    jy = 979 + 33 * j_np + 4 * (j_day_no // 1461)
    j_day_no %= 1461

    if j_day_no >= 366:
        jy += (j_day_no - 1) // 365
        j_day_no = (j_day_no - 1) % 365

    if j_day_no < 186:
        jm = 1 + j_day_no // 31
        jd = 1 + j_day_no % 31
    else:
        jm = 7 + (j_day_no - 186) // 30
        jd = 1 + (j_day_no - 186) % 30

    return jy, jm, jd


def format_jalali_date(dt: datetime) -> str:
    if not dt:
        return "نامشخص"
    months = [
        "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
        "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند"
    ]
    jy, jm, jd = gregorian_to_jalali(dt)
    return f"{jd} {months[jm - 1]} {jy}"


def format_traffic_size(size_bytes: int) -> str:
    size_bytes = max(int(size_bytes or 0), 0)
    gib = 1024 ** 3
    mib = 1024 ** 2
    if size_bytes >= gib:
        return f"{size_bytes / gib:.2f} گیگابایت"
    return f"{size_bytes / mib:.2f} مگابایت"


def slugify_service_code(name: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in name).strip("_") or "service"







# Messages
TEST_ACCOUNT_PLAN_NAME = "اکانت تست"

# Local messages that need dynamic values
MY_CONFIGS_MESSAGE = "🔗 کانفیگ های من\n\nشما هنوز کانفیگ فعالی ندارید.\n\nبرای خرید سرویس جدید، روی دکمه «🛒 خرید» کلیک کنید."
WALLET_MESSAGE = "💰 شارژ کیف پول\n\nموجودی فعلی شما: {balance} تومان\n\nبرای شارژ کیف پول، لطفاً با پشتیبانی تماس بگیرید."


# Message handlers
from aiogram import filters


async def send_wireguard_config_file(sender, config_text: str, caption: str = None, chat_id: int = None):
    """Override legacy sender to ship the SSH URI as a text file."""
    import os
    import tempfile

    if not config_text:
        return

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            tmp.write(config_text)
            tmp_path = tmp.name

        document = FSInputFile(tmp_path, filename="npvt-ssh.txt")
        final_caption = caption or "فایل لینک اتصال SSH"
        if chat_id:
            await sender.send_document(chat_id=chat_id, document=document, caption=final_caption)
        else:
            await sender.answer_document(document=document, caption=final_caption)
    except Exception as e:
        print(f"Error sending config file: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def get_server_field_prompt(field: str, step_num: int = None, total_steps: int = None) -> tuple:
    prompts = {
        "name": ("نام سرور را وارد کنید:", False),
        "host": ("IP یا Host سرور را وارد کنید:", False),
        "api_port": ("پورت SSH سرور را وارد کنید. مثال: 22", False),
        "username": ("یوزرنیم لاگین SSH سرور را وارد کنید:", False),
        "password": ("پسورد لاگین SSH سرور را وارد کنید:", False),
        "capacity": ("ظرفیت سرور (تعداد اکانت):", True),
    }
    return prompts.get(field, ("مقدار را وارد کنید:", False))


def get_server_creation_steps():
    return ["name", "host", "api_port", "username", "password", "capacity"]


def get_connection_apps_message() -> str:
    return (
        "📱 نرم‌افزارهای مورد نیاز\n\n"
        "برای این سرویس باید از اپلیکیشنی استفاده کنید که لینک‌های npvt-ssh:// را پشتیبانی کند.\n"
        "بعد از دریافت QR Code یا لینک، آن را داخل اپ سازگار ایمپورت کنید."
    )

# ASCII-safe overrides
async def send_wireguard_config_file(sender, config_text: str, caption: str = None, chat_id: int = None):
    import os
    import tempfile
    if not config_text:
        return
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
            tmp.write(config_text)
            tmp_path = tmp.name
        document = FSInputFile(tmp_path, filename="npvt-ssh.txt")
        final_caption = caption or "فایل اتصال"
        if chat_id:
            await sender.send_document(chat_id=chat_id, document=document, caption=final_caption)
        else:
            await sender.answer_document(document=document, caption=final_caption)
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.remove(tmp_path)


def get_server_field_prompt(field: str, step_num: int = None, total_steps: int = None) -> tuple:
    prompts = {
        "name": ("نام سرور:", False),
        "host": ("هاست یا IP سرور:", False),
        "api_port": ("پورت سرور:", False),
        "username": ("نام کاربری ورود سرور:", False),
        "password": ("رمز ورود سرور:", False),
        "capacity": ("ظرفیت سرور:", True),
    }
    return prompts.get(field, ("مقدار را وارد کنید:", False))


def get_server_creation_steps():
    return ["name", "host", "api_port", "username", "password", "capacity"]


def get_connection_apps_message() -> str:
    return (
        "برنامه‌های مورد نیاز\n\n"
        "پس از دریافت لینک یا QR Code، آن را در برنامه خود اضافه کنید."
    )
async def send_wireguard_config_file(sender, config_text: str, caption: str = None, chat_id: int = None):
    if not config_text:
        return
    if chat_id:
        await sender.send_message(chat_id=chat_id, text=config_text)
    else:
        await sender.answer(config_text)
