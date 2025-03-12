import os
import pickle
import logging
import ipaddress
import random
import string
import telebot
import base64
import uuid
import subprocess
import time
from telebot import types
from datetime import datetime, timedelta
from config import TOKEN, DATA_FILE, DNS_RANGES_FILE, FILES_DIR, TUTORIALS_DIR, default_data
from ranges import default_dns_ranges
from file_handlers import (
    send_file_to_user, 
    get_file_uploader_keyboard, 
    handle_file_upload, 
    edit_uploaded_file
)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Check token
if not TOKEN:
    logger.error("❌ No token provided")
    exit(1)

# Initialize bot with optimized request threading
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)

# Create directories if they don't exist
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(TUTORIALS_DIR, exist_ok=True)

# Add simple caching to reduce disk IO
_data_cache = None
_last_loaded = 0
_CACHE_TTL = 30  # Cache time-to-live in seconds

# State storage
admin_states = {}
payment_states = {}
file_editing_states = {}

# Load data from pickle file with caching
def load_data(force_reload=False):
    global _data_cache, _last_loaded
    current_time = time.time()

    # Return cached data if available and not expired
    if not force_reload and _data_cache is not None and (current_time - _last_loaded) < _CACHE_TTL:
        return _data_cache.copy()  # برگرداندن یک کپی برای جلوگیری از تغییرات ناخواسته

    try:
        with open(DATA_FILE, 'rb') as f:
            data = pickle.load(f)
            _data_cache = data
            _last_loaded = current_time
            logger.info("Data loaded from file successfully")
            return data
    except (FileNotFoundError, EOFError) as e:
        logger.warning(f"Error loading data file: {e}. Creating new data file")
        with open(DATA_FILE, 'wb') as f:
            pickle.dump(default_data, f)
        _data_cache = default_data.copy()
        _last_loaded = current_time
        return _data_cache.copy()
    except Exception as e:
        logger.error(f"Unexpected error loading data: {e}")
        # در صورت خطای غیرمنتظره، از داده‌های پیش‌فرض استفاده می‌کنیم
        _data_cache = default_data.copy()
        _last_loaded = current_time
        return _data_cache.copy()

# Save data to pickle file and update cache
def save_data(data):
    global _data_cache, _last_loaded
    try:
        # ابتدا یک فایل موقت ایجاد می‌کنیم
        temp_file = f"{DATA_FILE}.temp"
        with open(temp_file, 'wb') as f:
            pickle.dump(data, f)
            f.flush()
            os.fsync(f.fileno())  # اطمینان از ذخیره فیزیکی داده‌ها
        
        # سپس فایل موقت را جایگزین فایل اصلی می‌کنیم
        if os.path.exists(temp_file):
            if os.path.exists(DATA_FILE):
                os.replace(temp_file, DATA_FILE)
            else:
                os.rename(temp_file, DATA_FILE)
        
        _data_cache = data.copy()  # کپی برای جلوگیری از تغییرات ناخواسته
        _last_loaded = time.time()
        logger.info("Data saved successfully")
        return True
    except Exception as e:
        logger.error(f"Error saving data: {e}")
        return False

# Load DNS ranges
def load_dns_ranges():
    try:
        with open(DNS_RANGES_FILE, 'rb') as f:
            return pickle.load(f)
    except (FileNotFoundError, EOFError):
        logger.info("Creating new DNS ranges file")
        with open(DNS_RANGES_FILE, 'wb') as f:
            pickle.dump(default_dns_ranges, f)
        return default_dns_ranges

# Save DNS ranges
def save_dns_ranges(ranges):
    with open(DNS_RANGES_FILE, 'wb') as f:
        pickle.dump(ranges, f)

# Generate random IP from CIDR
def generate_random_ip(cidr):
    try:
        network = ipaddress.IPv4Network(cidr)
        # Get a random IP from the network, avoiding network and broadcast addresses
        max_index = network.num_addresses - 1
        if max_index > 2:  # If network has more than 2 addresses (network + broadcast)
            random_ip = str(network[random.randint(1, max_index - 1)])
        else:
            random_ip = str(network[1])  # Use the single usable address in a /31 or /32
        return random_ip
    except Exception as e:
        logger.error(f"Error generating random IP from {cidr}: {e}")
        return None

# Generate random IPv6 from CIDR
def generate_random_ipv6(cidr):
    try:
        network = ipaddress.IPv6Network(cidr)
        # For IPv6, we use a more sophisticated approach to handle the large address space
        # Convert network address to integer
        network_int = int(network.network_address)
        # Calculate a random offset within the network
        # For very large networks, we'll limit to a reasonable range to avoid excessive memory usage
        if network.prefixlen < 64:
            # For networks larger than /64, generate random addresses within a limited range
            max_offset = min(1000000, network.num_addresses - 1)
        else:
            # For smaller networks, we can use the full range
            max_offset = network.num_addresses - 1

        if max_offset > 1:
            offset = random.randint(1, max_offset)
            random_ip = str(ipaddress.IPv6Address(network_int + offset))
        else:
            # For single-address networks (/128)
            random_ip = str(network.network_address)

        return random_ip
    except Exception as e:
        logger.error(f"Error generating random IPv6 from {cidr}: {e}")
        return None

# Import WireGuard config module
import WGconfig

# Generate WireGuard keys
def generate_wireguard_keys():
    # Use the function from the WGconfig module
    return WGconfig.generate_wireguard_keys()

# Generate WireGuard config
def generate_wireguard_config(location):
    dns_ranges = load_dns_ranges()

    if location not in dns_ranges:
        return None

    # Generate keys
    private_key, public_key = generate_wireguard_keys()

    # Generate endpoint from the location's IP range
    ipv4_ranges = dns_ranges[location]['ipv4']
    endpoint = generate_random_ip(random.choice(ipv4_ranges))

    # Generate DNS servers
    primary_dns = WGconfig.CLIENT_DNS_PRIMARY
    secondary_ipv4 = generate_random_ip(random.choice(dns_ranges[location]['ipv4']))
    secondary_ipv6 = generate_random_ipv6(random.choice(dns_ranges[location]['ipv6']))
    dns_servers = [primary_dns, secondary_ipv4, secondary_ipv6]

    # Generate client addresses
    client_ipv4 = WGconfig.CLIENT_IPV4_BASE
    # Additional address
    client_ipv4_add = f"{WGconfig.CLIENT_IPV4_ADDITIONAL_PREFIX}{random.randint(2, 254)}/32"
    # Generate random IPv6 from location's IPv6 range
    ipv6_ranges = dns_ranges[location]['ipv6']
    client_ipv6_base = generate_random_ipv6(random.choice(ipv6_ranges))
    # Format it as a client address with subnet
    client_ipv6 = f"{client_ipv6_base}/64"

    # Create config using the WGconfig module
    config = WGconfig.create_wireguard_config(
        private_key, 
        public_key, 
        endpoint, 
        client_ipv4, 
        client_ipv4_add, 
        client_ipv6, 
        dns_servers
    )

    return config

# Generate random DNS configuration
def generate_dns_config(location):
    data = load_data()
    dns_ranges = load_dns_ranges()

    if location not in dns_ranges:
        return None

    ipv4_ranges = dns_ranges[location]['ipv4']
    ipv6_ranges = dns_ranges[location]['ipv6']

    # Generate one random IPv4 address
    ipv4 = generate_random_ip(random.choice(ipv4_ranges))

    # Generate two random IPv6 addresses
    ipv6_1 = generate_random_ipv6(random.choice(ipv6_ranges))
    ipv6_2 = generate_random_ipv6(random.choice(ipv6_ranges))

    # Create a config with unique ID
    config_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    config = {
        'id': config_id,
        'ipv4': ipv4,
        'ipv6_1': ipv6_1,
        'ipv6_2': ipv6_2,
        'location': location,
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    return config

# User management functions
def register_user(user_id, username, first_name):
    data = load_data()
    if str(user_id) not in data['users']:
        data['users'][str(user_id)] = {
            'username': username,
            'first_name': first_name,
            'balance': 0,
            'dns_configs': [],
            'wireguard_configs': [],
            'referral_code': f"REF{user_id}",
            'referrals': [],
            'invited_by': None,
            'join_date': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        save_data(data)
    return data['users'][str(user_id)]

def get_user(user_id):
    data = load_data()
    if str(user_id) in data['users']:
        return data['users'][str(user_id)]
    return None

def update_user_balance(user_id, amount):
    data = load_data()
    if str(user_id) in data['users']:
        data['users'][str(user_id)]['balance'] += amount
        save_data(data)
        return True
    return False

def check_admin(user_id):
    data = load_data()
    # Make sure user_id is converted to integer for comparison
    user_id_int = int(user_id)
    # Ensure we're comparing the same data types (integers)
    admin_ids = [int(admin_id) if isinstance(admin_id, str) else admin_id for admin_id in data['admins']]
    is_admin = user_id_int in admin_ids
    logger.info(f"Checking admin for user {user_id_int}: {is_admin}, admins: {admin_ids}")
    return is_admin

def add_admin(user_id):
    data = load_data()
    user_id_int = int(user_id)
    if user_id_int not in data['admins']:
        data['admins'].append(user_id_int)
        save_data(data)
        return True
    return False

# Generate main menu keyboard (inline)
def get_main_keyboard(user_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)
    data = load_data()

    # Get button settings or use defaults
    button_settings = {}
    if 'settings' in data and 'main_buttons' in data['settings']:
        button_settings = data['settings']['main_buttons']
    else:
        # Default button settings if not configured
        button_settings = {
            'buy_dns': {'title': '🌐 خرید DNS اختصاصی', 'enabled': True},
            'buy_vpn': {'title': '🔒 خرید کانفیگ اختصاصی', 'enabled': True},
            'account': {'title': '💼 حساب کاربری', 'enabled': True},
            'referral': {'title': '👥 دعوت از دوستان', 'enabled': True},
            'support': {'title': '💬 پشتیبانی', 'enabled': True},
            'add_balance': {'title': '💰 افزایش موجودی', 'enabled': True},
            'tutorials': {'title': '📚 آموزش‌ها', 'enabled': True},
            'rules': {'title': '📜 قوانین و مقررات', 'enabled': True}
        }
        
        # Save default settings
        if 'settings' not in data:
            data['settings'] = {}
        data['settings']['main_buttons'] = button_settings
        save_data(data)

    # Create buttons based on settings
    buttons = []
    
    # DNS and VPN buttons (only add if enabled)
    if button_settings.get('buy_dns', {}).get('enabled', True):
        btn1 = types.InlineKeyboardButton(button_settings['buy_dns']['title'], callback_data="menu_buy_dns")
        buttons.append(btn1)
        
    if button_settings.get('buy_vpn', {}).get('enabled', True):
        btn3 = types.InlineKeyboardButton(button_settings['buy_vpn']['title'], callback_data="menu_buy_vpn")
        buttons.append(btn3)

    # Account button
    if button_settings.get('account', {}).get('enabled', True):
        btn2 = types.InlineKeyboardButton(button_settings['account']['title'], callback_data="menu_account")
        buttons.append(btn2)
    
    # Referral button
    if button_settings.get('referral', {}).get('enabled', True):
        btn7 = types.InlineKeyboardButton(button_settings['referral']['title'], callback_data="menu_referral")
        buttons.append(btn7)

    # Support button
    if button_settings.get('support', {}).get('enabled', True):
        btn6 = types.InlineKeyboardButton(button_settings['support']['title'], url="https://t.me/xping_official")
        buttons.append(btn6)
    
    # Add balance button
    if button_settings.get('add_balance', {}).get('enabled', True):
        btn5 = types.InlineKeyboardButton(button_settings['add_balance']['title'], callback_data="add_balance")
        buttons.append(btn5)

    # Tutorials button
    if button_settings.get('tutorials', {}).get('enabled', True):
        btn8 = types.InlineKeyboardButton(button_settings['tutorials']['title'], callback_data="menu_tutorials")
        buttons.append(btn8)
    
    # Rules button
    if button_settings.get('rules', {}).get('enabled', True):
        btn9 = types.InlineKeyboardButton(button_settings['rules']['title'], callback_data="menu_rules")
        buttons.append(btn9)

    # Add buttons to markup, two per row
    for i in range(0, len(buttons), 2):
        if i + 1 < len(buttons):
            markup.add(buttons[i], buttons[i+1])
        else:
            markup.add(buttons[i])

    # Add admin panel button only for admin users
    if user_id and check_admin(int(user_id)):
        admin_btn = types.InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")
        markup.add(admin_btn)

    return markup

# Import enhanced admin functions
from admin_functions import (
    get_enhanced_admin_keyboard, 
    get_advanced_users_management_keyboard,
    get_enhanced_discount_keyboard,
    get_advanced_server_management_keyboard,
    get_ticket_management_keyboard,
    get_transaction_management_keyboard,
    get_service_management_keyboard,
    generate_transactions_excel,
    generate_users_excel,
    process_add_new_server,
    get_user_purchase_history,
    send_expiry_reminders
)

# Generate admin menu keyboard
def get_admin_keyboard():
    return get_enhanced_admin_keyboard()

# Generate locations keyboard for purchasing DNS or VPN
def get_locations_keyboard(type_service):
    markup = types.InlineKeyboardMarkup(row_width=1)
    data = load_data()

    for loc_id, location in data['locations'].items():
        if location['enabled']:
            btn = types.InlineKeyboardButton(
                f"{location['name']} - {location['price']} تومان", 
                callback_data=f"{type_service}_{loc_id}"
            )
            markup.add(btn)

    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
    markup.add(back_btn)

    return markup

# Welcome message handler
@bot.message_handler(commands=['start'])
def welcome_message(message):
    # Check if user is blocked
    data = load_data()
    if message.from_user.id in data.get('blocked_users', []):
        bot.send_message(
            message.chat.id,
            "⛔ حساب کاربری شما مسدود شده است. لطفاً برای اطلاعات بیشتر با پشتیبانی تماس بگیرید."
        )
        return

    user = register_user(message.from_user.id, message.from_user.username, message.from_user.first_name)

    # Check for file_id in the start command
    if len(message.text.split()) > 1:
        file_id = message.text.split()[1]

        # Check if it's a file download request
        data = load_data()
        if file_id in data.get('uploaded_files', {}):
            file_info = data['uploaded_files'][file_id]
            file_path = os.path.join(FILES_DIR, file_id)

            # ابتدا پیام "در حال ارسال فایل" را نمایش بدهیم
            sending_message = bot.send_message(
                message.chat.id, 
                f"👋 سلام {message.from_user.first_name} عزیز!\n\n"
                "در حال آماده‌سازی و ارسال فایل درخواستی شما..."
            )

            # ارسال فایل به کاربر با استفاده از file_id اصلی
            logger.info(f"🔗 User {message.from_user.id} requested file with ID: {file_id}")

            # استفاده از send_file_to_user برای ارسال فایل
            send_file_to_user(bot, message, file_id, load_data)

            # ایجاد دکمه برای رفتن به منوی اصلی
            markup = types.InlineKeyboardMarkup(row_width=1)
            main_menu_btn = types.InlineKeyboardButton("🏠 رفتن به منوی اصلی", callback_data="show_main_menu")
            markup.add(main_menu_btn)

            # ارسال پیام تکمیلی با دکمه منوی اصلی
            bot.send_message(
                message.chat.id,
                f"✅ فایل «{file_info.get('title', 'درخواستی')}» با موفقیت ارسال شد!\n\n"
                "برای دسترسی به امکانات ربات، می‌توانید به منوی اصلی بروید.",
                reply_markup=markup
            )
            return

        # Check if it's a referral code
        ref_code = message.text.split()[1]
        if ref_code.startswith('REF') and ref_code != user['referral_code'] and not user['invited_by']:
            data = load_data()
            for uid, u_data in data['users'].items():
                if u_data['referral_code'] == ref_code:
                    # Add referral
                    reward = data['settings']['referral_reward']
                    data['users'][uid]['referrals'].append(str(message.from_user.id))
                    data['users'][str(message.from_user.id)]['invited_by'] = uid
                    # Add bonus to referrer
                    data['users'][uid]['balance'] += reward
                    save_data(data)
                    bot.send_message(
                        int(uid), 
                        f"🎉 کاربر جدیدی با لینک دعوت شما وارد ربات شد!\n"
                        f"مبلغ {reward} تومان به حساب شما اضافه شد."
                    )
                    break

    welcome_text = (
        f"👋 سلام {message.from_user.first_name} عزیز!\n\n"
        "✨ به ربات فروش DNS اختصاصی و سرورهای VPN خوش آمدید!\n\n"
        "💻 از طریق این ربات می‌توانید:\n"
        "- 🌐 DNS اختصاصی با IP معتبر خریداری کنید\n"
        "- 🔒 VPN اختصاصی خریداری کنید\n"
        "- 👥 دوستان خود را دعوت کرده و پاداش دریافت کنید\n\n"
        "🚀 برای شروع، از منوی زیر گزینه مورد نظر خود را انتخاب کنید."
    )

    # Add admin notification
    if check_admin(message.from_user.id):
        welcome_text += f"\n\n⚠️ شما (با آیدی {message.from_user.id}) دسترسی مدیریت دارید. می‌توانید از دکمه «پنل مدیریت» استفاده کنید."

    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(message.from_user.id))

# Main callback query handler
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    # Main menu actions
    if call.data == "menu_account":
        show_account_info(call.message, call.from_user.id)
    elif call.data == "menu_buy_dns":
        show_buy_dns_menu(call.message)
    elif call.data == "menu_buy_vpn":
        show_buy_vpn_menu(call.message)
    elif call.data == "menu_referral":
        show_referral_info(call.message, call.from_user.id)
    elif call.data == "menu_tutorials":
        show_tutorial_categories(call.message)
    elif call.data == "menu_rules":
        show_rules(call.message)
    elif call.data == "show_main_menu":
        welcome_new_user(call.message, call.from_user.id)
    elif call.data == "back_to_main":
        bot.edit_message_text(
            "🏠 منوی اصلی",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_main_keyboard(call.from_user.id)
        )
    elif call.data == "tutorials":
        show_tutorial_categories(call.message)
    elif call.data == "tutorial_no_files":
        # فقط پیام خطا نمایش دهیم
        bot.answer_callback_query(call.id, "هنوز آموزشی برای این پلتفرم ضبط نشده است", show_alert=True)
    elif call.data == "submit_ticket":
        handle_submit_ticket(call)
    # Payment approval handlers
    elif call.data.startswith("approve_payment_") and check_admin(call.from_user.id):
        request_id = call.data.replace("approve_payment_", "")
        from admin_functions import handle_payment_approval
        # ارسال پیامی که نشان دهد پردازش در حال انجام است
        bot.answer_callback_query(call.id, "در حال پردازش درخواست...", show_alert=False)
        
        success = handle_payment_approval(bot, request_id, approved=True)
        
        if success:
            bot.edit_message_text(
                f"✅ درخواست پرداخت با شناسه {request_id} با موفقیت تایید شد.",
                call.message.chat.id,
                call.message.message_id
            )
            # بررسی دوباره وضعیت با لاگ کردن
            data = load_data(force_reload=True)
            if request_id in data.get('payment_requests', {}):
                payment_request = data['payment_requests'][request_id]
                user_id = payment_request['user_id']
                user_id_str = str(user_id)
                if user_id_str in data['users']:
                    logging.info(f"After approval - User {user_id_str} balance: {data['users'][user_id_str].get('balance', 0)}")
            
            bot.answer_callback_query(call.id, "✅ پرداخت با موفقیت تایید شد!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ خطا در پردازش درخواست", show_alert=True)
    # Payment rejection handlers
    elif call.data.startswith("reject_payment_") and check_admin(call.from_user.id):
        request_id = call.data.replace("reject_payment_", "")
        from admin_functions import handle_payment_approval
        if handle_payment_approval(bot, request_id, approved=False):
            bot.edit_message_text(
                f"❌ درخواست پرداخت با شناسه {request_id} رد شد.",
                call.message.chat.id,
                call.message.message_id
            )
            bot.answer_callback_query(call.id, "❌ پرداخت رد شد!", show_alert=True)
        else:
            bot.answer_callback_query(call.id, "❌ خطا در پردازش درخواست", show_alert=True)
    # Admin panel
    elif call.data == "admin_panel":
        if call.from_user.id and check_admin(call.from_user.id):
            admin_text = (
                "⚙️ پنل مدیریت\n\n"
                "👨‍💻 خوش آمدید، ادمین گرامی!\n"
                "لطفاً گزینه مورد نظر خود را انتخاب کنید:"
            )
            bot.edit_message_text(
                admin_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=get_admin_keyboard()
            )
        else:
            bot.answer_callback_query(call.id, "⛔️ شما به این بخش دسترسی ندارید!", show_alert=True)
    # Buy services
    elif call.data.startswith("buy_dns_"):
        process_buy_dns(call)
    elif call.data.startswith("buy_vpn_"):
        process_buy_vpn(call)
    elif call.data.startswith("confirm_vpn_"):
        process_confirm_vpn(call)
    # Payment
    elif call.data == "add_balance":
        process_add_balance(call)
    elif call.data.startswith("payment_plan_"):
        handle_payment_plan_selection(call)
    elif call.data == "payment_custom":
        handle_payment_custom(call)
    # Admin file management handlers
    elif call.data in ["list_files", "upload_photo", "upload_video", "upload_document", "create_share_link"] and check_admin(call.from_user.id):
        process_admin_functions(call)
    elif call.data.startswith("file_list_page_") and check_admin(call.from_user.id):
        process_admin_functions(call)
    # Other admin panel actions
    elif call.data.startswith("admin_"):
        process_admin_functions(call)
    elif call.data.startswith("admin_file_") and check_admin(call.from_user.id):
        file_id = call.data.replace("admin_file_", "")
        show_file_management(call.message, file_id)
    # File management actions
    elif call.data.startswith("edit_file_") and check_admin(call.from_user.id):
        process_admin_functions(call)
    elif call.data.startswith("confirm_delete_file_") and check_admin(call.from_user.id):
        process_admin_functions(call)
    elif call.data.startswith("share_file_") and check_admin(call.from_user.id):
        process_admin_functions(call)
    # Tutorial actions
    elif call.data.startswith("tutorial_"):
        process_tutorial_actions(call)
    elif call.data.startswith("file_"):
        file_id = call.data.replace("file_", "")
        send_file_to_user(bot, call.message, file_id, load_data)
    elif call.data == "goto_account":
        show_account_info(call.message, call.from_user.id)
    elif call.data == "create_external_url":
        handle_create_external_url(call)
    # Handle external URL creation in the uploader
    elif call.data == "create_external_url":
        handle_create_external_url(call)
    # Handle file replacement in the uploader
    elif call.data == "replace_file":
        handle_replace_file_selection(call)
    else:
        bot.answer_callback_query(call.id, "⚠️ این قابلیت به زودی فعال خواهد شد.", show_alert=True)

# Function implementations
def show_account_info(message, user_id):
    user = get_user(user_id)
    if not user:
        user = register_user(user_id, None, None)

    data = load_data()
    card_number = data['settings']['payment_card']

    account_text = (
        f"👤 اطلاعات حساب کاربری\n\n"
        f"🆔 شناسه کاربری: <code>{user_id}</code>\n"
        f"💰 موجودی: {user['balance']} تومان\n"
        f"🔢 کد دعوت: {user['referral_code']}\n"
        f"👥 تعداد دعوت‌شدگان: {len(user['referrals'])}\n"
        f"📅 تاریخ عضویت: {user['join_date']}\n\n"
        f"💳 برای افزایش موجودی، مبلغ دلخواه را به شماره کارت زیر واریز کرده و سپس از دکمه «افزایش موجودی» استفاده کنید:\n\n"
        f"<code>{card_number}</code>"
    )

    # Add DNS configs info
    if user['dns_configs']:
        account_text += "\n\n🌐 DNS های اختصاصی شما:\n"
        for i, dns in enumerate(user['dns_configs']):
            account_text += f"\n{i+1}. {dns['location']} - {dns['created_at']}\n"
            account_text += f"   IPv4: <code>{dns['ipv4']}</code>\n"
            account_text += f"   IPv6_1: <code>{dns['ipv6_1']}</code>\n"
            account_text += f"   IPv6_2: <code>{dns['ipv6_2']}</code>\n"

    # Add WireGuard configs info
    if user['wireguard_configs']:
        account_text += "\n\n🔒 VPN های اختصاصی شما:\n"
        for i, vpn in enumerate(user['wireguard_configs']):
            account_text += f"\n{i+1}. {vpn['location_name']} - {vpn['created_at']}\n"

    markup = types.InlineKeyboardMarkup(row_width=2)
    payment_btn = types.InlineKeyboardButton("💰 افزایش موجودی", callback_data="add_balance")
    ticket_btn = types.InlineKeyboardButton("🎫 ثبت تیکت", callback_data="submit_ticket")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")

    markup.add(payment_btn, ticket_btn)
    markup.add(back_btn)

    bot.edit_message_text(
        account_text,
        message.chat.id,
        message.message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

# ساختارهای مربوط به سیستم تیکت
ticket_states = {}

def handle_submit_ticket(call):
    # ایجاد حالت ثبت تیکت برای کاربر
    ticket_states[call.from_user.id] = {'state': 'waiting_ticket_subject'}

    markup = types.InlineKeyboardMarkup(row_width=1)
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="goto_account")
    markup.add(cancel_btn)

    bot.edit_message_text(
        "🎫 ثبت تیکت پشتیبانی\n\n"
        "لطفاً موضوع تیکت خود را در یک پیام وارد کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def show_buy_dns_menu(message):
    buy_text = (
        "🌐 خرید DNS اختصاصی\n\n"
        "🔰 با خرید DNS اختصاصی شما صاحب آدرس‌های IPv4 و IPv6 اختصاصی خواهید شد که می‌توانید برای اتصال به اینترنت استفاده کنید.\n\n"
        "✅ مزایای DNS اختصاصی:\n"
        "- پایداری و سرعت بالا\n"
        "- IP اختصاصی و غیر مشترک\n"
        "- پشتیبانی از تمامی سرویس‌ها\n"
        "- قابل استفاده در تمامی دستگاه‌ها\n\n"
        "🌏 لطفاً موقعیت جغرافیایی مورد نظر خود را انتخاب کنید:"
    )

    bot.edit_message_text(
        buy_text,
        message.chat.id,
        message.message_id,
        reply_markup=get_locations_keyboard("buy_dns")
    )

def show_buy_vpn_menu(message):
    buy_text = (
        "🔒 خرید کانفیگ اختصاصی وایرگارد\n\n"
        "🔰 با خرید کانفیگ وایرگارد اختصاصی شما صاحب یک کانفیگ اختصاصی خواهید شد که می‌توانید برای اتصال امن به اینترنت استفاده کنید.\n\n"
        "✅ مزایای کانفیگ اختصاصی:\n"
        "- پایداری و سرعت بالا\n"
        "- کانفیگ اختصاصی و غیر مشترک\n"
        "- امنیت بالا با پروتکل WireGuard\n"
        "- قابل استفاده در تمامی دستگاه‌ها\n\n"
        "🌏 لطفاً موقعیت جغرافیایی مورد نظر خود را انتخاب کنید:"
    )

    bot.edit_message_text(
        buy_text,
        message.chat.id,
        message.message_id,
        reply_markup=get_locations_keyboard("buy_vpn")
    )

def show_referral_info(message, user_id):
    user = get_user(user_id)
    if not user:
        user = register_user(user_id, None, None)

    data = load_data()
    reward = data['settings']['referral_reward']

    bot_username = bot.get_me().username
    ref_link = f"https://t.me/{bot_username}?start={user['referral_code']}"

    referral_text = (
        "👥 دعوت از دوستان\n\n"
        f"🎁 با دعوت هر دوست به ربات، مبلغ {reward} تومان به حساب شما اضافه می‌شود!\n\n"
        "📣 برای دعوت از دوستان، لینک اختصاصی زیر را برای آنها ارسال کنید:\n\n"
        f"<code>{ref_link}</code>\n\n"
        f"👥 تعداد دعوت شدگان فعلی: {len(user['referrals'])}\n"
        f"💰 درآمد شما از سیستم دعوت: {len(user['referrals']) * reward} تومان"
    )

    markup = types.InlineKeyboardMarkup(row_width=1)
    share_btn = types.InlineKeyboardButton("🔗 اشتراک‌گذاری لینک", url=f"https://t.me/share/url?url={ref_link}&text=با%20استفاده%20از%20این%20ربات%20می‌توانید%20DNS%20اختصاصی%20و%20سرورهای%20VPN%20رایگان%20دریافت%20کنید!")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
    markup.add(share_btn, back_btn)

    bot.edit_message_text(
        referral_text,
        message.chat.id,
        message.message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

def process_buy_dns(call):
    location_id = call.data.replace("buy_dns_", "")
    user = get_user(call.from_user.id)
    data = load_data()

    if location_id in data['locations'] and data['locations'][location_id]['enabled']:
        location = data['locations'][location_id]
        
        # پرسیدن کد تخفیف قبل از نهایی کردن خرید
        markup = types.InlineKeyboardMarkup(row_width=2)
        yes_btn = types.InlineKeyboardButton("بله، کد تخفیف دارم", callback_data=f"has_discount_{location_id}")
        no_btn = types.InlineKeyboardButton("خیر، ادامه خرید", callback_data=f"no_discount_dns_{location_id}")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="menu_buy_dns")
        markup.add(yes_btn, no_btn)
        markup.add(back_btn)
        
        bot.edit_message_text(
            f"🔰 خرید DNS اختصاصی - {location['name']}\n\n"
            f"💰 قیمت: {location['price']} تومان\n\n"
            "آیا کد تخفیف دارید؟",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
        
    # این بخش دیگر اجرا نمی‌شود زیرا تابع در بالا با return پایان می‌یابد
    price = location['price']
    if user['balance'] >= price:
        # Generate DNS configuration
        dns_config = generate_dns_config(location_id)

        if dns_config:
            # Deduct balance
            user['balance'] -= price
            # Add DNS to user's configs
            user['dns_configs'].append(dns_config)
            data['users'][str(call.from_user.id)] = user
            save_data(data)

            # Notify user about balance reduction
            bot.send_message(
                call.from_user.id,
                f"💸 مبلغ {price} تومان بابت خرید DNS اختصاصی از حساب شما کسر شد.\n"
                f"💰 موجودی فعلی: {user['balance']} تومان"
            )

            success_text = (
                f"✅ خرید DNS اختصاصی با موفقیت انجام شد!\n\n"
                f"🌏 موقعیت: {location['name']}\n"
                f"💰 مبلغ پرداخت شده: {price} تومان\n"
                f"🔢 شناسه پیکربندی: {dns_config['id']}\n\n"
                f"🔰 اطلاعات DNS شما:\n\n"
                f"IPv4: <code>{dns_config['ipv4']}</code>\n\n"
                f"IPv6 اول: <code>{dns_config['ipv6_1']}</code>\n\n"
                f"IPv6 دوم: <code>{dns_config['ipv6_2']}</code>\n\n"
                f"📅 تاریخ خرید: {dns_config['created_at']}\n\n"
                f"💻 آموزش استفاده از DNS را می‌توانید از بخش آموزش‌ها دریافت کنید."
            )

            markup = types.InlineKeyboardMarkup(row_width=1)
            back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
            markup.add(back_btn)

            bot.edit_message_text(
                success_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode="HTML"
            )
        else:
            bot.answer_callback_query(call.id, "⚠️ خطا در تولید پیکربندی DNS. لطفاً با پشتیبانی تماس بگیرید.")
    else:
        insufficient_text = (
            f"⚠️ موجودی ناکافی\n\n"
            f"💰 موجودی فعلی شما: {user['balance']} تومان\n"
            f"💰 مبلغ مورد نیاز: {price} تومان\n\n"
            f"📝 برای افزایش موجودی به بخش 'حساب کاربری' مراجعه کنید."
        )

        markup = types.InlineKeyboardMarkup(row_width=1)
        account_btn = types.InlineKeyboardButton("👤 حساب کاربری", callback_data="goto_account")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
        markup.add(account_btn, back_btn)

        bot.edit_message_text(
            insufficient_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

def process_buy_vpn(call):
    location_id = call.data.replace("buy_vpn_", "")
    user = get_user(call.from_user.id)
    data = load_data()

    if location_id in data['locations'] and data['locations'][location_id]['enabled']:
        location = data['locations'][location_id]
        
        # پرسیدن کد تخفیف قبل از نهایی کردن خرید
        markup = types.InlineKeyboardMarkup(row_width=2)
        yes_btn = types.InlineKeyboardButton("بله، کد تخفیف دارم", callback_data=f"has_discount_{location_id}")
        no_btn = types.InlineKeyboardButton("خیر، ادامه خرید", callback_data=f"no_discount_vpn_{location_id}")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="menu_buy_vpn")
        markup.add(yes_btn, no_btn)
        markup.add(back_btn)
        
        bot.edit_message_text(
            f"🔰 خرید VPN اختصاصی - {location['name']}\n\n"
            f"💰 قیمت: {location['price']} تومان\n\n"
            "آیا کد تخفیف دارید؟",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
        
    # این بخش دیگر اجرا نمی‌شود زیرا تابع در بالا با return پایان می‌یابد
    price = location['price']
    if user['balance'] >= price:
        # Ask for confirmation before purchase
        confirm_text = (
            f"🔰 تأیید خرید VPN اختصاصی\n\n"
            f"🌏 موقعیت: {location['name']}\n"
            f"💰 قیمت: {price} تومان\n"
            f"💰 موجودی شما: {user['balance']} تومان\n\n"
            f"آیا مطمئن هستید که می‌خواهید این سرویس را خریداری کنید؟"
        )

        markup = types.InlineKeyboardMarkup(row_width=2)
        confirm_btn = types.InlineKeyboardButton("✅ بله، خرید شود", callback_data=f"confirm_vpn_{location_id}")
        cancel_btn = types.InlineKeyboardButton("❌ خیر، انصراف", callback_data="menu_buy_vpn")
        markup.add(confirm_btn, cancel_btn)

        bot.edit_message_text(
            confirm_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
    else:
        insufficient_text = (
            f"⚠️ موجودی ناکافی\n\n"
            f"💰 موجودی فعلی شما: {user['balance']} تومان\n"
            f"💰 مبلغ مورد نیاز: {price} تومان\n\n"
            f"📝 برای افزایش موجودی به بخش 'حساب کاربری' مراجعه کنید."
        )

        markup = types.InlineKeyboardMarkup(row_width=1)
        account_btn = types.InlineKeyboardButton("👤 حساب کاربری", callback_data="goto_account")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
        markup.add(account_btn, back_btn)

        bot.edit_message_text(
            insufficient_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )

def process_confirm_vpn(call):
    location_id = call.data.replace("confirm_vpn_", "")
    user = get_user(call.from_user.id)
    data = load_data()

    if location_id in data['locations'] and data['locations'][location_id]['enabled']:
        location = data['locations'][location_id]
        price = location['price']

        if user['balance'] >= price:
            # Generate WireGuard configuration
            config_text = generate_wireguard_config(location_id)

            if config_text:
                # Create a unique file name with new format
                random_letter = random.choice(string.ascii_uppercase)
                random_digits = ''.join(random.choices(string.digits, k=4))
                config_id = f"{random_letter}{random_digits}"
                file_name = f"{config_id}.conf"

                # Save config to a temporary file
                with open(file_name, 'w') as f:
                    f.write(config_text)

                # Deduct balance
                user['balance'] -= price

                # Add config to user's wireguard_configs
                vpn_config = {
                    'id': config_id,
                    'location': location_id,
                    'location_name': location['name'],
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }

                user['wireguard_configs'].append(vpn_config)
                data['users'][str(call.from_user.id)] = user
                save_data(data)

                # Notify user about balance reduction
                bot.send_message(
                    call.from_user.id,
                    f"💸 مبلغ {price} تومان بابت خرید VPN اختصاصی از حساب شما کسر شد.\n"
                    f"💰 موجودی فعلی: {user['balance']} تومان"
                )

                # Success message
                success_text = (
                    f"✅ خرید VPN اختصاصی با موفقیت انجام شد!\n\n"
                    f"🌏 موقعیت: {location['name']}\n"
                    f"💰 مبلغ پرداخت شده: {price} تومان\n"
                    f"🔢 شناسه پیکربندی: {config_id}\n\n"
                    f"📅 تاریخ خرید: {vpn_config['created_at']}\n\n"
                    f"🔽 فایل پیکربندی به زودی ارسال می‌شود...\n\n"
                    f"💻 برای استفاده، فایل را دانلود کرده و در اپلیکیشن WireGuard وارد کنید."
                )

                markup = types.InlineKeyboardMarkup(row_width=1)
                back_btn = types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
                markup.add(back_btn)

                # نمایش پیام به کاربر بدون حذف پیام خرید موفق
                bot.send_message(
                    call.message.chat.id,
                    success_text,
                    reply_markup=markup
                )

                # Then send the config file
                with open(file_name, 'rb') as f:
                    bot.send_document(
                        call.message.chat.id,
                        f,
                        caption=f"🔒 فایل پیکربندی VPN اختصاصی - {location['name']}"
                    )

                # Remove temporary file
                os.remove(file_name)
            else:
                bot.answer_callback_query(call.id, "⚠️ خطا در تولید پیکربندی VPN. لطفاً با پشتیبانی تماس بگیرید.")
        else:
            bot.answer_callback_query(call.id, "⚠️ موجودی ناکافی!")

def process_add_balance(call):
    markup = types.InlineKeyboardMarkup(row_width=2)

    # Add payment plans
    for plan in [
        {"amount": 50000, "name": "پلن برنزی"},
        {"amount": 100000, "name": "پلن نقره‌ای"},
        {"amount": 200000, "name": "پلن طلایی"},
        {"amount": 500000, "name": "پلن الماس"}
    ]:
        btn = types.InlineKeyboardButton(
            f"{plan['name']} - {plan['amount']} تومان", 
            callback_data=f"payment_plan_{plan['amount']}"
        )
        markup.add(btn)

    custom_btn = types.InlineKeyboardButton("💰 مبلغ دلخواه", callback_data="payment_custom")
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="back_to_main")
    markup.add(custom_btn)
    markup.add(cancel_btn)

    bot.edit_message_text(
        "💰 افزایش موجودی\n\n"
        "💳 لطفاً یکی از پلن‌های زیر را انتخاب کنید یا مبلغ دلخواه خود را وارد نمایید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

def handle_payment_plan_selection(call):
    amount = int(call.data.replace("payment_plan_", ""))
    payment_states[call.from_user.id] = {'state': 'waiting_receipt', 'amount': amount}

    data = load_data()
    card_number = data['settings']['payment_card']

    markup = types.InlineKeyboardMarkup(row_width=1)
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="back_to_main")
    markup.add(cancel_btn)

    bot.edit_message_text(
        f"💰 مبلغ {amount} تومان انتخاب شد.\n\n"
        f"لطفاً مبلغ را به شماره کارت زیر واریز کنید:\n"
        f"<code>{card_number}</code>\n\n"
        f"پس از واریز، لطفاً تصویر رسید پرداخت را ارسال کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

def handle_payment_custom(call):
    payment_states[call.from_user.id] = {'state': 'waiting_amount'}

    bot.edit_message_text(
        "💰 افزایش موجودی با مبلغ دلخواه\n\n"
        "لطفاً مبلغ مورد نظر خود را به تومان وارد کنید:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML"
    )

def process_tutorial_actions(call):
    if call.data == "tutorials":
        show_tutorial_categories(call.message)
    elif call.data.startswith("tutorial_device_"):
        # Format: tutorial_device_CATEGORY_DEVICE
        parts = call.data.split("_")
        category_id = parts[2]
        device = parts[3]

        # Show tutorials for selected device
        bot.edit_message_text(
            f"📚 {get_tutorial_category_title(category_id)} - {device.capitalize()}\n\n"
            "🔰 لطفاً آموزش مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_tutorial_files_for_device(category_id, device)
        )
    elif call.data.startswith("tutorial_"):
        category_id = call.data.replace("tutorial_", "")
        show_tutorial_files(call.message, category_id)

def show_tutorial_categories(message, admin_mode=False):
    bot.edit_message_text(
        "📚 آموزش‌ها\n\n"
        "🔰 لطفاً دسته‌بندی مورد نظر خود را انتخاب کنید:",
        message.chat.id,
        message.message_id,
        reply_markup=get_tutorial_categories_keyboard(admin_mode)
    )

def show_tutorial_files(message, category_id, admin_mode=False):
    if admin_mode:
        bot.edit_message_text(
            f"📚 فایل‌های آموزشی - {get_tutorial_category_title(category_id)}\n\n"
            "🔰 لطفاً فایل مورد نظر خود را انتخاب کنید:",
            message.chat.id,
            message.message_id,
            reply_markup=get_tutorial_files_keyboard(category_id, admin_mode)
        )
    else:
        # Show device selection for user mode
        bot.edit_message_text(
            f"📚 {get_tutorial_category_title(category_id)}\n\n"
            "🔰 لطفاً سیستم عامل خود را انتخاب کنید:",
            message.chat.id,
            message.message_id,
            reply_markup=get_tutorial_device_keyboard(category_id)
        )

def get_tutorial_category_title(category_id):
    data = load_data()
    if category_id in data['tutorials']:
        return data['tutorials'][category_id]['title']
    return "دسته‌بندی نامشخص"

def get_tutorial_device_keyboard(category_id):
    markup = types.InlineKeyboardMarkup(row_width=2)

    android_btn = types.InlineKeyboardButton("📱 اندروید", callback_data=f"tutorial_device_{category_id}_android")
    ios_btn = types.InlineKeyboardButton("🍎 iOS", callback_data=f"tutorial_device_{category_id}_ios")
    windows_btn = types.InlineKeyboardButton("🖥️ ویندوز", callback_data=f"tutorial_device_{category_id}_windows")

    markup.add(android_btn, ios_btn)
    markup.add(windows_btn)

    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="tutorials")
    markup.add(back_btn)

    return markup

def get_tutorial_files_for_device(category_id, device):
    markup = types.InlineKeyboardMarkup(row_width=1)
    data = load_data()
    found_files = False

    if category_id in data['tutorials']:
        files = data['tutorials'][category_id]['files']
        for file_id in files:
            if file_id in data['uploaded_files']:
                file_info = data['uploaded_files'][file_id]
                # Filter files based on device tag in the title
                if device.lower() in file_info['title'].lower():
                    btn = types.InlineKeyboardButton(
                        file_info['title'], 
                        callback_data=f"file_{file_id}"
                    )
                    markup.add(btn)
                    found_files = True

    # اگر هیچ فایلی یافت نشد، پیام مناسبی نمایش دهیم
    if not found_files:
        info_btn = types.InlineKeyboardButton(
            "⚠️ هنوز آموزشی برای این پلتفرم ضبط نشده است", 
            callback_data="tutorial_no_files"
        )
        markup.add(info_btn)

    # دکمه برگشت به انتخاب دستگاه
    device_btn = types.InlineKeyboardButton("🔙 بازگشت به انتخاب دستگاه", callback_data=f"tutorial_{category_id}")
    # دکمه برگشت به دسته‌بندی‌ها
    category_btn = types.InlineKeyboardButton("🔙 بازگشت به دسته‌بندی‌ها", callback_data="tutorials")

    markup.add(device_btn)
    markup.add(category_btn)

    return markup

def get_tutorial_categories_keyboard(admin_mode=False):
    markup = types.InlineKeyboardMarkup(row_width=2)
    data = load_data()

    for category_id, category in data['tutorials'].items():
        # Skip disabled categories for regular users, but show all to admins
        if not admin_mode and category.get('enabled', True) == False:
            continue
            
        btn = types.InlineKeyboardButton(category['title'], 
                                        callback_data=f"{'admin_' if admin_mode else ''}tutorial_{category_id}")
        markup.add(btn)

    back_btn = types.InlineKeyboardButton("🔙 بازگشت", 
                                        callback_data="admin_back" if admin_mode else "back_to_main")
    markup.add(back_btn)

    return markup

def get_tutorial_files_keyboard(category_id, admin_mode=False):
    markup = types.InlineKeyboardMarkup(row_width=1)
    data = load_data()

    if category_id in data['tutorials']:
        files = data['tutorials'][category_id]['files']
        for file_id in files:
            if file_id in data['uploaded_files']:
                file_info = data['uploaded_files'][file_id]
                btn = types.InlineKeyboardButton(
                    file_info['title'], 
                    callback_data=f"{'admin_' if admin_mode else ''}file_{file_id}"
                )
                markup.add(btn)

    if admin_mode:
        add_btn = types.InlineKeyboardButton("➕ افزودن فایل جدید", 
                                            callback_data=f"add_tutorial_{category_id}")
        markup.add(add_btn)

    back_btn = types.InlineKeyboardButton("🔙 بازگشت", 
                                        callback_data=f"{'admin_' if admin_mode else ''}tutorials")
    markup.add(back_btn)

    return markup

def show_rules(message):
    from rules import get_rules_text
    rules_text = get_rules_text()

    markup = types.InlineKeyboardMarkup(row_width=1)
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
    markup.add(back_btn)

    bot.edit_message_text(
        rules_text,
        message.chat.id,
        message.message_id,
        reply_markup=markup
    )

def welcome_new_user(message, user_id):
    welcome_text = (
        f"👋 خوش آمدید!\n\n"
        "✨ به ربات فروش DNS اختصاصی و سرورهای VPN خوش آمدید!\n\n"
        "💻 از طریق این ربات می‌توانید:\n"
        "- 🌐 DNS اختصاصی با IP معتبر خریداری کنید\n"
        "- 🔒 VPN اختصاصی خریداری کنید\n"
        "- 👥 دوستان خود را دعوت کرده و پاداش دریافت کنید\n\n"
        "🚀 برای شروع، از منوی زیر گزینه مورد نظر خود را انتخاب کنید."
    )

    # Add admin notification
    if check_admin(user_id):
        welcome_text += f"\n\n⚠️ شما (با آیدی {user_id}) دسترسی مدیریت دارید. می‌توانید از دکمه «پنل مدیریت» استفاده کنید."

    bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard(user_id))

# Admin command handler
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if not check_admin(message.from_user.id):
        bot.send_message(message.chat.id, "⛔️ شما به این دستور دسترسی ندارید!")
        return

    admin_text = (
        "⚙️ پنل مدیریت\n\n"
        "👨‍💻 خوش آمدید، ادمین گرامی!\n"
        "لطفاً گزینه مورد نظر خود را انتخاب کنید:"
    )

    bot.send_message(message.chat.id, admin_text, reply_markup=get_admin_keyboard())

# Cancel command for state handlers
@bot.message_handler(commands=['cancel'])
def cancel_command(message):
    if message.from_user.id in admin_states:
        del admin_states[message.from_user.id]
        bot.send_message(message.chat.id, "❌ عملیات لغو شد.")
        # Show main menu
        welcome_message(message)
    elif message.from_user.id in payment_states:
        del payment_states[message.from_user.id]
        bot.send_message(message.chat.id, "❌ عملیات افزایش موجودی لغو شد.")
        # Show main menu
        welcome_message(message)
    else:
        bot.send_message(message.chat.id, "متاسفانه فایل مورد نظر یافت نشد.")
        return False

    bot.send_message(message.chat.id, "❌ عملیاتی برای لغو کردن وجود ندارد.")

# Process admin functions - complete version
def process_admin_functions(call):
    admin_actions = {
        # Menu navigation actions
        "admin_back": lambda: bot.edit_message_text(
            "⚙️ پنل مدیریت\n\n"
            "👨‍💻 خوش آمدید، ادمین گرامی!\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_admin_keyboard()
        ),
        "admin_file_uploader": lambda: bot.edit_message_text(
            "📤 آپلودر فایل\n\n"
            "لطفاً نوع فایل برای آپلود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_file_uploader_keyboard()
        ),
        "create_external_url": lambda: handle_create_external_url(call),
        "replace_file": lambda: handle_replace_file_selection(call),
        # User management
        "admin_users": lambda: bot.edit_message_text(
            "👥 مدیریت کاربران\n\n"
            "از طریق این بخش می‌توانید کاربران را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_advanced_users_management_keyboard()
        ),
        # Server management
        "admin_servers": lambda: bot.edit_message_text(
            "🌐 مدیریت سرورها\n\n"
            "از طریق این بخش می‌توانید سرورها را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_advanced_server_management_keyboard()
        ),
        # Payment settings
        "admin_payment_settings": lambda: bot.edit_message_text(
            "💳 تنظیمات پرداخت\n\n"
            "از طریق این بخش می‌توانید تنظیمات پرداخت را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("💳 تغییر شماره کارت", callback_data="change_card_number"),
                types.InlineKeyboardButton("💰 تنظیم مبلغ رفرال", callback_data="set_referral_amount"),
                types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
            )
        ),
        # Stats and reports
        "admin_stats": lambda: bot.edit_message_text(
            "📈 آمار و گزارش\n\n"
            "از طریق این بخش می‌توانید آمار و گزارش‌ها را مشاهده کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("👥 آمار کاربران", callback_data="user_stats"),
                types.InlineKeyboardButton("💰 آمار مالی", callback_data="financial_stats"),
                types.InlineKeyboardButton("📊 نمودار فروش", callback_data="sales_chart"),
                types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
            )
        ),
        # Ticket management
        "admin_tickets": lambda: bot.edit_message_text(
            "🎫 مدیریت تیکت‌ها\n\n"
            "از طریق این بخش می‌توانید تیکت‌ها را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_ticket_management_keyboard()
        ),
        # Broadcast messages
        "admin_broadcast": lambda: bot.edit_message_text(
            "📩 ارسال پیام گروهی\n\n"
            "از طریق این بخش می‌توانید به تمامی کاربران پیام ارسال کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("📩 ارسال پیام به همه", callback_data="broadcast_all"),
                types.InlineKeyboardButton("📩 ارسال پیام به کاربران فعال", callback_data="broadcast_active"),
                types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
            )
        ),
        # Discount codes
        "admin_discount": lambda: bot.edit_message_text(
            "🏷️ کدهای تخفیف\n\n"
            "از طریق این بخش می‌توانید کدهای تخفیف را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_enhanced_discount_keyboard()
        ),
        # Referral settings
        "admin_referral": lambda: bot.edit_message_text(
            "🔄 تنظیم رفرال\n\n"
            "از طریق این بخش می‌توانید سیستم دعوت از دوستان را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("💰 تنظیم پاداش دعوت", callback_data="set_referral_reward"),
                types.InlineKeyboardButton("📊 آمار رفرال‌ها", callback_data="referral_stats"),
                types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
            )
        ),
        # Transactions
        "admin_transactions": lambda: bot.edit_message_text(
            "💹 تراکنش‌ها\n\n"
            "از طریق این بخش می‌توانید تراکنش‌ها را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_transaction_management_keyboard()
        ),
        # Service management
        "admin_services": lambda: bot.edit_message_text(
            "⏱️ مدیریت سرویس‌ها\n\n"
            "از طریق این بخش می‌توانید سرویس‌ها را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_service_management_keyboard()
        ),
        # Add admin
        "admin_add_admin": lambda: handle_add_admin(call),
        # Blocked users
        "admin_blocked_users": lambda: bot.edit_message_text(
            "🚫 کاربران مسدود\n\n"
            "از طریق این بخش می‌توانید کاربران مسدود را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("🚫 مسدودسازی کاربر", callback_data="block_user"),
                types.InlineKeyboardButton("✅ رفع مسدودیت کاربر", callback_data="unblock_user"),
                types.InlineKeyboardButton("📋 لیست کاربران مسدود", callback_data="list_blocked_users"),
                types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
            )
        ),
        # Export Excel
        "admin_export_excel": lambda: bot.edit_message_text(
            "📊 گزارش اکسل\n\n"
            "از طریق این بخش می‌توانید گزارش‌های اکسل دریافت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_excel_export_keyboard()
        ),
        # Tutorials
        "admin_tutorials": lambda: show_tutorial_categories(call.message, admin_mode=True),
        # Button management
        "admin_buttons": lambda: bot.edit_message_text(
            "🔘 مدیریت دکمه‌ها\n\n"
            "از طریق این بخش می‌توانید دکمه‌های منوها را مدیریت کنید.\n"
            "لطفاً گزینه مورد نظر خود را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_buttons_management_keyboard()
        ),
        # File Listing and Management
        "list_files": lambda: show_file_list(call.message),
        # Upload handlers
        "upload_photo": lambda: handle_upload_request(call, "photo"),
        "upload_video": lambda: handle_upload_request(call, "video"),
        "upload_document": lambda: handle_upload_request(call, "document"),
        # Create share link
        "create_share_link": lambda: handle_create_share_link(call),
    }

    # آپلودر فایل و مدیریت فایل‌ها
    if call.data in ["list_files", "upload_photo", "upload_video", "upload_document", "create_share_link"]:
        admin_actions[call.data]()
        return

    # Handle file page navigation
    if call.data.startswith("file_list_page_"):
        page = int(call.data.replace("file_list_page_", ""))
        data = load_data()
        file_ids = list(data['uploaded_files'].keys())
        files_per_page = 5
        markup = get_file_list_keyboard(file_ids, page, files_per_page)
        bot.edit_message_text(
            "📋 لیست فایل‌ها\n\n"
            "فایل‌های آپلود شده:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return

    # Handle user list pagination
    if call.data.startswith("user_list_page_"):
        page = int(call.data.replace("user_list_page_", ""))
        show_user_list(call.message, page)
        return

    # Process edit file requests
    if call.data.startswith("admin_edit_file_"):
        file_id = call.data.replace("admin_edit_file_", "")
        handle_edit_file_request(call, file_id)
        return

    # Process delete file requests
    if call.data.startswith("admin_delete_file_"):
        file_id = call.data.replace("admin_delete_file_", "")
        handle_delete_file_request(call, file_id)
        return

    # Process share file requests
    if call.data.startswith("share_file_"):
        file_id = call.data.replace("share_file_", "")
        handle_share_file_request(call, file_id)
        return

    # Confirm delete file
    if call.data.startswith("confirm_delete_file_"):
        file_id = call.data.replace("confirm_delete_file_", "")
        data = load_data()
        if file_id in data.get('uploaded_files', {}):
            # Delete file from filesystem
            file_path = os.path.join(FILES_DIR, file_id)
            if os.path.exists(file_path):
                os.remove(file_path)

            # Delete file from data
            del data['uploaded_files'][file_id]
            save_data(data)

            bot.edit_message_text(
                "✅ فایل با موفقیت حذف شد.",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_files")
                )
            )
        else:
            bot.answer_callback_query(call.id, "فایل مورد نظر یافت نشد!", show_alert=True)
        return

    # Process Edit file title
    if call.data.startswith("edit_file_title_"):
        file_id = call.data.replace("edit_file_title_", "")
        admin_states[call.from_user.id] = {'state': 'editing_file_title', 'file_id': file_id}

        bot.edit_message_text(
            "✏️ ویرایش عنوان فایل\n\n"
            "لطفاً عنوان جدید را وارد کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin_file_{file_id}")
            )
        )
        return

    # Process Edit file content
    if call.data.startswith("edit_file_content_"):
        file_id = call.data.replace("edit_file_content_", "")
        admin_states[call.from_user.id] = {'state': 'editing_file_content', 'file_id': file_id}

        bot.edit_message_text(
            "📝 ویرایش محتوای فایل\n\n"
            "لطفاً فایل جدید را ارسال کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin_file_{file_id}")
            )
        )
        return

    # Process Excel export requests
    if call.data == "export_users_excel":
        generate_users_excel(bot, call.message.chat.id)
        bot.answer_callback_query(call.id, "✅ گزارش کاربران تولید شد و به زودی ارسال می‌شود.", show_alert=True)
        return

    if call.data == "export_transactions_excel":
        generate_transactions_excel(bot, call.message.chat.id)
        bot.answer_callback_query(call.id, "✅ گزارش تراکنش‌ها تولید شد و به زودی ارسال می‌شود.", show_alert=True)
        return

    # Check if the action is defined
    if call.data in admin_actions:
        admin_actions[call.data]()
    # Handle buttons management
    elif call.data == "admin_buttons":
        markup = get_buttons_management_keyboard()
        bot.edit_message_text(
            "🔘 مدیریت دکمه‌ها\n\n"
            "لطفاً یکی از گزینه‌های زیر را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "manage_main_buttons":
        markup = get_main_buttons_management_keyboard()
        bot.edit_message_text(
            "🔘 مدیریت دکمه‌های منوی اصلی\n\n"
            "با کلیک روی هر دکمه، وضعیت نمایش آن را تغییر دهید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "manage_tutorial_buttons":
        markup = get_tutorial_buttons_management_keyboard()
        bot.edit_message_text(
            "🔘 مدیریت دکمه‌های آموزش‌ها\n\n"
            "با کلیک روی هر دکمه، وضعیت نمایش آن را تغییر دهید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data.startswith("toggle_main_button_"):
        button_id = call.data.replace("toggle_main_button_", "")
        if toggle_button_visibility('main', button_id):
            markup = get_main_buttons_management_keyboard()
            bot.edit_message_text(
                "🔘 مدیریت دکمه‌های منوی اصلی\n\n"
                "✅ وضعیت دکمه با موفقیت تغییر کرد.\n"
                "با کلیک روی هر دکمه، وضعیت نمایش آن را تغییر دهید:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        return
    elif call.data.startswith("toggle_tutorial_"):
        category_id = call.data.replace("toggle_tutorial_", "")
        if toggle_button_visibility('tutorial', category_id):
            markup = get_tutorial_buttons_management_keyboard()
            bot.edit_message_text(
                "🔘 مدیریت دکمه‌های آموزش‌ها\n\n"
                "✅ وضعیت دکمه با موفقیت تغییر کرد.\n"
                "با کلیک روی هر دکمه، وضعیت نمایش آن را تغییر دهید:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        return
    # User management functions
    elif call.data == "search_user":
        admin_states[call.from_user.id] = {'state': 'waiting_user_id_search'}
        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")
        markup.add(back_btn)

        bot.edit_message_text(
            "🔍 جستجوی کاربر\n\n"
            "لطفاً شناسه عددی کاربر مورد نظر را وارد کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "add_user_balance":
        admin_states[call.from_user.id] = {'state': 'waiting_user_id_for_balance'}
        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")
        markup.add(back_btn)

        bot.edit_message_text(
            "💰 افزایش موجودی کاربر\n\n"
            "لطفاً شناسه عددی کاربر مورد نظر را وارد کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "list_users":
        data = load_data()
        user_count = len(data['users'])

        if user_count == 0:
            bot.edit_message_text(
                "📊 لیست کاربران\n\n"
                "هیچ کاربری یافت نشد!",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=types.InlineKeyboardMarkup().add(
                    types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")
                )
            )
            return

        # Show first page of users
        show_user_list(call.message, 0)
        return
    elif call.data == "block_user":
        admin_states[call.from_user.id] = {'state': 'waiting_user_id_for_block'}
        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")
        markup.add(back_btn)

        bot.edit_message_text(
            "🚫 مسدودسازی کاربر\n\n"
            "لطفاً شناسه عددی کاربر مورد نظر را وارد کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "message_user":
        admin_states[call.from_user.id] = {'state': 'waiting_user_id_for_message'}
        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")
        markup.add(back_btn)

        bot.edit_message_text(
            "📨 ارسال پیام به کاربر\n\n"
            "لطفاً شناسه عددی کاربر مورد نظر را وارد کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "user_purchase_history":
        admin_states[call.from_user.id] = {'state': 'waiting_user_id_for_history'}
        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")
        markup.add(back_btn)

        bot.edit_message_text(
            "📜 تاریخچه خرید کاربر\n\n"
            "لطفاً شناسه عددی کاربر مورد نظر را وارد کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    # Server management functions
    elif call.data == "add_new_server":
        admin_states[call.from_user.id] = {'state': 'waiting_server_type'}
        markup = types.InlineKeyboardMarkup(row_width=1)
        location_btn = types.InlineKeyboardButton("🌍 لوکیشن جدید", callback_data="new_server_location")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_servers")
        markup.add(location_btn, back_btn)

        bot.edit_message_text(
            "➕ افزودن سرور جدید\n\n"
            "چه نوع سروری می‌خواهید اضافه کنید؟",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "list_servers":
        data = load_data()

        locations_text = "📋 لیست لوکیشن‌های فعال:\n\n"
        for loc_id, loc_info in data['locations'].items():
            status = "✅" if loc_info.get('enabled', True) else "❌"
            locations_text += f"{status} {loc_info['name']} - {loc_info['price']} تومان\n"

        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_servers")
        markup.add(back_btn)

        bot.edit_message_text(
            locations_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "edit_server":
        data = load_data()
        
        if not data.get('locations'):
            bot.answer_callback_query(call.id, "❌ هیچ سروری برای ویرایش وجود ندارد!", show_alert=True)
            return
            
        markup = types.InlineKeyboardMarkup(row_width=1)
        for loc_id, loc_info in data['locations'].items():
            btn = types.InlineKeyboardButton(loc_info['name'], callback_data=f"edit_server_{loc_id}")
            markup.add(btn)
            
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_servers")
        markup.add(back_btn)
        
        bot.edit_message_text(
            "🔄 ویرایش سرور\n\n"
            "لطفاً سرور مورد نظر برای ویرایش را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data.startswith("edit_server_"):
        server_id = call.data.replace("edit_server_", "")
        data = load_data()
        
        if server_id not in data.get('locations', {}):
            bot.answer_callback_query(call.id, "❌ سرور مورد نظر یافت نشد!", show_alert=True)
            return
            
        server_info = data['locations'][server_id]
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        edit_name_btn = types.InlineKeyboardButton("✏️ ویرایش نام", callback_data=f"edit_server_name_{server_id}")
        edit_price_btn = types.InlineKeyboardButton("💰 ویرایش قیمت", callback_data=f"edit_server_price_{server_id}")
        toggle_status_btn = types.InlineKeyboardButton(
            "🚦 غیرفعال کردن" if server_info.get('enabled', True) else "🚦 فعال کردن", 
            callback_data=f"toggle_server_{server_id}"
        )
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="edit_server")
        
        markup.add(edit_name_btn, edit_price_btn, toggle_status_btn, back_btn)
        
        status = "✅ فعال" if server_info.get('enabled', True) else "❌ غیرفعال"
        
        bot.edit_message_text(
            f"🔧 ویرایش سرور: {server_info['name']}\n\n"
            f"🆔 شناسه: {server_id}\n"
            f"💰 قیمت: {server_info['price']} تومان\n"
            f"📊 وضعیت: {status}\n\n"
            f"لطفاً گزینه مورد نظر برای ویرایش را انتخاب کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "server_pricing":
        data = load_data()
        
        pricing_text = "💰 قیمت سرورها\n\n"
        for loc_id, loc_info in data['locations'].items():
            status = "✅" if loc_info.get('enabled', True) else "❌"
            pricing_text += f"{status} {loc_info['name']}: {loc_info['price']} تومان\n"
            
        markup = types.InlineKeyboardMarkup(row_width=1)
        update_btn = types.InlineKeyboardButton("✏️ به‌روزرسانی قیمت‌ها", callback_data="update_server_prices")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_servers")
        
        markup.add(update_btn, back_btn)
        
        bot.edit_message_text(
            pricing_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "manage_locations":
        data = load_data()
        
        if not data.get('locations'):
            location_text = "❌ هیچ لوکیشنی یافت نشد!"
        else:
            location_text = "🌍 مدیریت لوکیشن‌ها\n\n"
            for loc_id, loc_info in data['locations'].items():
                status = "✅" if loc_info.get('enabled', True) else "❌"
                location_text += f"{status} {loc_info['name']} ({loc_id})\n"
                
        markup = types.InlineKeyboardMarkup(row_width=1)
        add_btn = types.InlineKeyboardButton("➕ افزودن لوکیشن", callback_data="add_new_location")
        remove_btn = types.InlineKeyboardButton("❌ حذف لوکیشن", callback_data="remove_location")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_servers")
        
        markup.add(add_btn, remove_btn, back_btn)
        
        bot.edit_message_text(
            location_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data == "toggle_server_status":
        data = load_data()
        
        if not data.get('locations'):
            bot.answer_callback_query(call.id, "❌ هیچ سروری برای تغییر وضعیت وجود ندارد!", show_alert=True)
            return
            
        markup = types.InlineKeyboardMarkup(row_width=1)
        for loc_id, loc_info in data['locations'].items():
            status = "✅" if loc_info.get('enabled', True) else "❌"
            btn = types.InlineKeyboardButton(f"{status} {loc_info['name']}", callback_data=f"toggle_server_{loc_id}")
            markup.add(btn)
            
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_servers")
        markup.add(back_btn)
        
        bot.edit_message_text(
            "🚦 تغییر وضعیت سرورها\n\n"
            "برای تغییر وضعیت فعال/غیرفعال، روی سرور مورد نظر کلیک کنید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    elif call.data.startswith("toggle_server_"):
        server_id = call.data.replace("toggle_server_", "")
        data = load_data()
        
        if server_id in data.get('locations', {}):
            current_status = data['locations'][server_id].get('enabled', True)
            data['locations'][server_id]['enabled'] = not current_status
            save_data(data)
            
            new_status = "فعال" if not current_status else "غیرفعال"
            bot.answer_callback_query(call.id, f"✅ سرور {data['locations'][server_id]['name']} {new_status} شد.", show_alert=True)
            
            # Refresh the toggle server status page
            markup = types.InlineKeyboardMarkup(row_width=1)
            for loc_id, loc_info in data['locations'].items():
                status = "✅" if loc_info.get('enabled', True) else "❌"
                btn = types.InlineKeyboardButton(f"{status} {loc_info['name']}", callback_data=f"toggle_server_{loc_id}")
                markup.add(btn)
                
            back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_servers")
            markup.add(back_btn)
            
            bot.edit_message_text(
                "🚦 تغییر وضعیت سرورها\n\n"
                "برای تغییر وضعیت فعال/غیرفعال، روی سرور مورد نظر کلیک کنید:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        else:
            bot.answer_callback_query(call.id, "❌ سرور مورد نظر یافت نشد!", show_alert=True)
        return
    elif call.data == "server_status":
        # نمایش وضعیت فنی سرورها
        markup = types.InlineKeyboardMarkup(row_width=1)
        check_btn = types.InlineKeyboardButton("🔄 بررسی وضعیت سرورها", callback_data="check_server_status")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_servers")
        markup.add(check_btn, back_btn)
        
        bot.edit_message_text(
            "🔍 وضعیت سرورها\n\n"
            "برای بررسی وضعیت آنلاین بودن و پینگ سرورها، دکمه زیر را فشار دهید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
        return
    else:
        bot.answer_callback_query(call.id, "⚠️ این قابلیت در حال پیاده‌سازی است.", show_alert=True)

def get_excel_export_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)

    btn1 = types.InlineKeyboardButton("📊 گزارش کاربران", callback_data="export_users_excel")
    btn2 = types.InlineKeyboardButton("📊 گزارش تراکنش‌ها", callback_data="export_transactions_excel")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")

    markup.add(btn1, btn2, back_btn)
    return markup

def get_buttons_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)

    # Main buttons for button management
    btn1 = types.InlineKeyboardButton("🔘 دکمه‌های منوی اصلی", callback_data="manage_main_buttons")
    btn2 = types.InlineKeyboardButton("🔘 دکمه‌های آموزش‌ها", callback_data="manage_tutorial_buttons")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")

    markup.add(btn1)
    markup.add(btn2)
    markup.add(back_btn)
    
    return markup

# Get main menu buttons management keyboard
def get_main_buttons_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    data = load_data()
    
    # Initialize settings if needed
    if 'settings' not in data:
        data['settings'] = {}
        
    # Initialize main buttons if needed
    if 'main_buttons' not in data['settings']:
        data['settings']['main_buttons'] = {
            'buy_dns': {'title': '🌐 خرید DNS اختصاصی', 'enabled': True},
            'buy_vpn': {'title': '🔒 خرید کانفیگ اختصاصی', 'enabled': True},
            'account': {'title': '💼 حساب کاربری', 'enabled': True},
            'referral': {'title': '👥 دعوت از دوستان', 'enabled': True},
            'support': {'title': '💬 پشتیبانی', 'enabled': True},
            'add_balance': {'title': '💰 افزایش موجودی', 'enabled': True},
            'tutorials': {'title': '📚 آموزش‌ها', 'enabled': True},
            'rules': {'title': '📜 قوانین و مقررات', 'enabled': True}
        }
        save_data(data)

    # Create buttons for each main menu item
    for button_id, button_info in data['settings']['main_buttons'].items():
        status = "✅" if button_info.get('enabled', True) else "❌"
        btn = types.InlineKeyboardButton(
            f"{status} {button_info['title']}", 
            callback_data=f"toggle_main_button_{button_id}"
        )
        markup.add(btn)

    # Back button
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_buttons")
    markup.add(back_btn)

    return markup

# Get tutorial buttons management keyboard
def get_tutorial_buttons_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    data = load_data()
    
    # Ensure all tutorial categories have the 'enabled' property
    for category_id, category in data['tutorials'].items():
        if 'enabled' not in category:
            category['enabled'] = True
    
    # Save changes to data
    save_data(data)
    
    # Add buttons for each tutorial category
    for category_id, category in data['tutorials'].items():
        status = "✅" if category.get('enabled', True) else "❌"
        btn = types.InlineKeyboardButton(
            f"{status} {category['title']}", 
            callback_data=f"toggle_tutorial_{category_id}"
        )
        markup.add(btn)

    # Back button
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_buttons")
    markup.add(back_btn)

    return markup

def handle_add_admin(call):
    admin_states[call.from_user.id] = {'state': 'waiting_admin_id'}

    markup = types.InlineKeyboardMarkup(row_width=1)
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    markup.add(back_btn)

    bot.edit_message_text(
        "➕ افزودن ادمین\n\n"
        "لطفاً آیدی عددی کاربر مورد نظر را وارد کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def handle_upload_request(call, file_type):
    admin_states[call.from_user.id] = {'state': f'waiting_{file_type}', 'file_type': file_type}

    markup = types.InlineKeyboardMarkup(row_width=1)
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_file_uploader")
    markup.add(back_btn)

    type_text = {
        "photo": "تصویر",
        "video": "ویدیو",
        "document": "فایل"
    }

    bot.edit_message_text(
        f"📤 آپلود {type_text[file_type]}\n\n"
        f"لطفاً {type_text[file_type]} مورد نظر خود را ارسال کنید:\n\n"
        "توجه: می‌توانید در کپشن، عنوان فایل را وارد کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def show_file_list(message):
    data = load_data()

    if not data.get('uploaded_files'):
        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_file_uploader")
        markup.add(back_btn)

        bot.edit_message_text(
            "📋 لیست فایل‌ها\n\n"
            "هیچ فایلی آپلود نشده است.",
            message.chat.id,
            message.message_id,
            reply_markup=markup
        )
        return

    # Create paginated keyboard for files
    page = 0
    files_per_page = 5
    file_ids = list(data['uploaded_files'].keys())

    markup = get_file_list_keyboard(file_ids, page, files_per_page)

    bot.edit_message_text(
        "📋 لیست فایل‌ها\n\n"
        "فایل‌های آپلود شده:",
        message.chat.id,
        message.message_id,
        reply_markup=markup
    )

def get_file_list_keyboard(file_ids, page, files_per_page):
    data = load_data()
    markup = types.InlineKeyboardMarkup(row_width=1)

    start_idx = page * files_per_page
    end_idx = min(start_idx + files_per_page, len(file_ids))

    for i in range(start_idx, end_idx):
        file_id = file_ids[i]
        file_info = data['uploaded_files'][file_id]
        file_title = file_info.get('title', file_id)
        file_type = file_info.get('type', 'نامشخص')

        # Add emoji based on file type
        if file_type == 'photo':
            emoji = '🖼️'
        elif file_type == 'video':
            emoji = '🎥'
        elif file_type == 'document':
            emoji = '📄'
        else:
            emoji = '📁'

        btn = types.InlineKeyboardButton(f"{emoji} {file_title}", callback_data=f"admin_file_{file_id}")
        markup.add(btn)

    # Navigation buttons
    nav_buttons = []
    if page > 0:
        nav_buttons.append(types.InlineKeyboardButton("◀️ قبلی", callback_data=f"file_list_page_{page-1}"))
    if end_idx < len(file_ids):
        nav_buttons.append(types.InlineKeyboardButton("بعدی ▶️", callback_data=f"file_list_page_{page+1}"))

    if nav_buttons:
        markup.add(*nav_buttons)

    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_file_uploader")
    markup.add(back_btn)

    return markup

def handle_edit_file_request(call, file_id):
    data = load_data()

    if file_id not in data.get('uploaded_files', {}):
        bot.answer_callback_query(call.id, "فایل مورد نظر یافت نشد!", show_alert=True)
        return

    file_info = data['uploaded_files'][file_id]

    # Set up state for editing
    admin_states[call.from_user.id] = {
        'state': 'editing_file',
        'file_id': file_id,
        'current_info': file_info
    }

    markup = types.InlineKeyboardMarkup(row_width=1)
    edit_title_btn = types.InlineKeyboardButton("✏️ ویرایش عنوان", callback_data=f"edit_file_title_{file_id}")
    edit_content_btn = types.InlineKeyboardButton("📝 ویرایش فایل", callback_data=f"edit_file_content_{file_id}")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin_file_{file_id}")

    markup.add(edit_title_btn, edit_content_btn, back_btn)

    bot.edit_message_text(
        f"✏️ ویرایش فایل: {file_info['title']}\n\n"
        f"شناسه فایل: {file_id}\n"
        f"نوع فایل: {file_info['type']}\n"
        f"عنوان فعلی: {file_info['title']}\n\n"
        "لطفاً عملیات ویرایشی مورد نظر را انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def handle_delete_file_request(call, file_id):
    data = load_data()

    if file_id not in data.get('uploaded_files', {}):
        bot.answer_callback_query(call.id, "فایل مورد نظر یافت نشد!", show_alert=True)
        return

    file_info = data['uploaded_files'][file_id]

    markup = types.InlineKeyboardMarkup(row_width=2)
    confirm_btn = types.InlineKeyboardButton("✅ بله، حذف شود", callback_data=f"confirm_delete_file_{file_id}")
    cancel_btn = types.InlineKeyboardButton("❌ خیر، انصراف", callback_data=f"admin_file_{file_id}")

    markup.add(confirm_btn, cancel_btn)

    bot.edit_message_text(
        f"🗑️ حذف فایل: {file_info['title']}\n\n"
        f"آیا از حذف این فایل اطمینان دارید؟\n"
        "این عملیات غیرقابل بازگشت است!",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

# Message handlers
@bot.message_handler(func=lambda message: message.from_user.id in payment_states and payment_states[message.from_user.id]['state'] == 'waiting_amount')
def handle_payment_amount(message):
    try:
        amount = int(message.text.strip())
        if amount > 0:
            payment_states[message.from_user.id]['amount'] = amount
            payment_states[message.from_user.id]['state'] = 'waiting_receipt'

            data = load_data()
            card_number = data['settings']['payment_card']

            bot.send_message(
                message.chat.id,
                f"💰 مبلغ {amount} تومان ثبت شد.\n\n"
                f"لطفاً مبلغ را به شماره کارت زیر واریز کنید:\n"
                f"<code>{card_number}</code>\n\n"
                f"پس از واریز، لطفاً تصویر رسید پرداخت را ارسال کنید.",
                parse_mode="HTML"
            )
        else:
            bot.send_message(
                message.chat.id,
                "⚠️ مبلغ باید بزرگتر از صفر باشد. لطفاً مجدداً تلاش کنید یا /cancel را برای لغو وارد کنید."
            )
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک عدد صحیح وارد کنید یا /cancel را برای لغو وارد کنید."
        )

@bot.message_handler(content_types=['photo'], func=lambda message: message.from_user.id in payment_states and payment_states[message.from_user.id]['state'] == 'waiting_receipt')
def handle_payment_receipt(message):
    user_id = message.from_user.id
    amount = payment_states[user_id]['amount']
    discount_code = payment_states[user_id].get('discount_code', None)
    discount_amount = payment_states[user_id].get('discount_amount', 0)

    # Get photo file_id
    photo_id = message.photo[-1].file_id

    # Create payment request record
    data = load_data()
    if 'payment_requests' not in data:
        data['payment_requests'] = {}

    # Update discount code usage if applied
    if discount_code and discount_code in data['discount_codes']:
        data['discount_codes'][discount_code]['uses'] += 1

    # Create transaction record
    if 'transactions' not in data:
        data['transactions'] = {}

    transaction_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    request_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    data['payment_requests'][request_id] = {
        'user_id': user_id,
        'amount': amount,
        'photo_id': photo_id,
        'status': 'pending',
        'discount_code': discount_code,
        'discount_amount': discount_amount,
        'original_amount': amount + discount_amount,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'transaction_id': transaction_id
    }

    # Record transaction
    data['transactions'][transaction_id] = {
        'user_id': user_id,
        'amount': amount,
        'type': 'deposit',
        'status': 'pending',
        'discount_code': discount_code,
        'discount_amount': discount_amount,
        'original_amount': amount + discount_amount,
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'request_id': request_id
    }

    save_data(data)

    # Notify user
    bot.send_message(
        user_id,
        f"✅ درخواست افزایش موجودی شما به مبلغ {amount} تومان ثبت شد.\n"
        f"🔢 شناسه پیگیری: <code>{request_id}</code>\n\n"
        f"📝 این درخواست در صف بررسی قرار گرفت و پس از تایید، موجودی شما افزایش خواهد یافت.",
        parse_mode="HTML"
    )

    # Notify all admins
    for admin_id in data['admins']:
        try:
            # Forward the photo
            forwarded = bot.forward_message(
                admin_id,
                message.chat.id,
                message.message_id
            )

            # Send payment request info
            markup = types.InlineKeyboardMarkup(row_width=2)
            approve_btn = types.InlineKeyboardButton("✅ تایید", callback_data=f"approve_payment_{request_id}")
            reject_btn = types.InlineKeyboardButton("❌ رد", callback_data=f"reject_payment_{request_id}")
            markup.add(approve_btn, reject_btn)

            bot.send_message(
                admin_id,
                f"💰 درخواست افزایش موجودی جدید\n\n"
                f"👤 کاربر: <code>{user_id}</code>\n"
                f"💲 مبلغ: {amount} تومان\n"
                f"🔢 شناسه: {request_id}\n"
                f"📅 تاریخ: {data['payment_requests'][request_id]['timestamp']}",
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

    # Clear payment state
    del payment_states[user_id]

# Handle file uploads for admin
@bot.message_handler(content_types=['photo'], func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id].get('state') == 'waiting_photo')
def handle_admin_photo_upload(message):
    success, file_id = handle_file_upload(bot, message, 'photo', admin_states)
    if success:
        bot.reply_to(
            message,
            f"✅ تصویر با موفقیت آپلود شد.\n\n"
            f"🆔 شناسه فایل: <code>{file_id}</code>\n\n"
            f"این فایل در بخش لیست فایل‌ها قابل مشاهده است.",
            parse_mode="HTML"
        )
        # Clear admin state
        del admin_states[message.from_user.id]
    else:
        bot.reply_to(
            message,
            "❌ خطا در آپلود تصویر. لطفاً مجدداً تلاش کنید."
        )

@bot.message_handler(content_types=['video'], func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id].get('state') == 'waiting_video')
def handle_admin_video_upload(message):
    success, file_id = handle_file_upload(bot, message, 'video', admin_states)
    if success:
        bot.reply_to(
            message,
            f"✅ ویدیو با موفقیت آپلود شد.\n\n"
            f"🆔 شناسه فایل: <code>{file_id}</code>\n\n"
            f"این فایل در بخش لیست فایل‌ها قابل مشاهده است.",
            parse_mode="HTML"
        )
        # Clear admin state
        del admin_states[message.from_user.id]
    else:
        bot.reply_to(
            message,
            "❌ خطا در آپلود ویدیو. لطفاً مجدداً تلاش کنید."
        )

@bot.message_handler(content_types=['document'], func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id].get('state') == 'waiting_document')
def handle_admin_document_upload(message):
    success, file_id = handle_file_upload(bot, message, 'document', admin_states)
    if success:
        bot.reply_to(
            message,
            f"✅ فایل با موفقیت آپلود شد.\n\n"
            f"🆔 شناسه فایل: <code>{file_id}</code>\n\n"
            f"این فایل در بخش لیست فایل‌ها قابل مشاهده است.",
            parse_mode="HTML"
        )
        # Clear admin state
        del admin_states[message.from_user.id]
    else:
        bot.reply_to(
            message,
            "❌ خطا در آپلود فایل. لطفاً مجدداً تلاش کنید."
        )

# Handle file title editing
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id].get('state') == 'editing_file_title')
def handle_edit_file_title(message):
    user_id = message.from_user.id
    file_id = admin_states[user_id]['file_id']
    new_title = message.text

    # Update file title
    data = load_data()
    if file_id in data.get('uploaded_files', {}):
        data['uploaded_files'][file_id]['title'] = new_title
        save_data(data)

        bot.reply_to(
            message,
            f"✅ عنوان فایل با موفقیت به «{new_title}» تغییر یافت."
        )

        # Show file management menu again
        show_file_management(message, file_id)
    else:
        bot.reply_to(
            message,
            "❌ فایل مورد نظر یافت نشد!"
        )

    # Clear admin state
    del admin_states[user_id]

# Handler for creating external URL link - step 1: Request title
def handle_create_external_url(call):
    admin_states[call.from_user.id] = {'state': 'waiting_external_url_title'}

    markup = types.InlineKeyboardMarkup(row_width=1)
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="admin_file_uploader")
    markup.add(cancel_btn)

    bot.edit_message_text(
        "🌐 ایجاد لینک خارجی\n\n"
        "لطفاً عنوان لینک را وارد کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

# Handler for creating external URL link - step 2: Get title and request URL
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id].get('state') == 'waiting_external_url_title')
def handle_external_url_title(message):
    user_id = message.from_user.id
    title = message.text.strip()

    if not title:
        bot.reply_to(message, "❌ عنوان نمی‌تواند خالی باشد. لطفاً دوباره تلاش کنید.")
        return

    admin_states[user_id]['state'] = 'waiting_external_url'
    admin_states[user_id]['title'] = title

    markup = types.InlineKeyboardMarkup(row_width=1)
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="admin_file_uploader")
    markup.add(cancel_btn)

    bot.reply_to(
        message,
        f"✅ عنوان «{title}» ثبت شد.\n\n"
        "لطفاً آدرس URL را وارد کنید:",
        reply_markup=markup
    )

# Handler for creating external URL link - step 3: Get URL and request caption
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id].get('state') == 'waiting_external_url')
def handle_external_url(message):
    user_id = message.from_user.id
    url = message.text.strip()

    if not url or not (url.startswith('http://') or url.startswith('https://')):
        bot.reply_to(message, "❌ لطفاً یک آدرس URL معتبر وارد کنید که با http:// یا https:// شروع شود.")
        return

    admin_states[user_id]['state'] = 'waiting_external_url_caption'
    admin_states[user_id]['url'] = url

    markup = types.InlineKeyboardMarkup(row_width=2)
    skip_btn = types.InlineKeyboardButton("⏩ رد کردن", callback_data="skip_external_url_caption")
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="admin_file_uploader")
    markup.add(skip_btn, cancel_btn)

    bot.reply_to(
        message,
        f"✅ لینک ثبت شد.\n\n"
        "لطفاً توضیحات (کپشن) را وارد کنید یا از دکمه «رد کردن» استفاده کنید:",
        reply_markup=markup
    )

# Skip caption for external URL
@bot.callback_query_handler(func=lambda call: call.data == "skip_external_url_caption")
def skip_external_url_caption(call):
    if call.from_user.id in admin_states and admin_states[call.from_user.id].get('state') == 'waiting_external_url_caption':
        create_external_url_final(call.from_user.id, "")

# Handler for creating external URL link - step 4: Get caption and create link
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id].get('state') == 'waiting_external_url_caption')
def handle_external_url_caption(message):
    user_id = message.from_user.id
    caption = message.text
    create_external_url_final(user_id, caption)

# Finalize external URL link creation
def create_external_url_final(user_id, caption):
    title = admin_states[user_id]['title']
    url = admin_states[user_id]['url']

    from file_handlers import create_external_url_link
    file_id = create_external_url_link(title, url, caption)

    # Get bot username for share link
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={file_id}"

    # Send confirmation with share link
    bot.send_message(
        user_id,
        f"✅ لینک خارجی با موفقیت ایجاد شد!\n\n"
        f"🔤 عنوان: {title}\n"
        f"🔗 آدرس: {url}\n\n"
        f"🔗 لینک اشتراک‌گذاری:\n"
        f"<code>{share_link}</code>",
        parse_mode="HTML"
    )

    # Clear admin state
    del admin_states[user_id]

# Handler for replacing a file - step 1: Show file selection
def handle_replace_file_selection(call):
    data = load_data()

    if not data.get('uploaded_files'):
        bot.edit_message_text(
            "❌ هیچ فایلی برای جایگزینی وجود ندارد.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_file_uploader")
            )
        )
        return

    markup = types.InlineKeyboardMarkup(row_width=1)

    # List first 10 files
    for file_id, file_info in list(data['uploaded_files'].items())[:10]:
        # Skip external URLs
        if file_info.get('type') == 'external_url':
            continue

        file_title = file_info.get('title', 'فایل بدون عنوان')
        markup.add(types.InlineKeyboardButton(file_title, callback_data=f"replace_file_{file_id}"))

    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_file_uploader"))

    bot.edit_message_text(
        "🔄 جایگزینی فایل\n\n"
        "لطفاً فایلی که می‌خواهید جایگزین کنید را انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

# Handler for selecting file to replace
@bot.callback_query_handler(func=lambda call: call.data.startswith("replace_file_"))
def select_file_to_replace(call):
    file_id = call.data.replace("replace_file_", "")
    data = load_data()

    if file_id not in data.get('uploaded_files', {}):
        bot.answer_callback_query(call.id, "❌ فایل مورد نظر یافت نشد!", show_alert=True)
        return

    file_info = data['uploaded_files'][file_id]
    file_type = file_info.get('type')

    if file_type == 'external_url':
        bot.answer_callback_query(call.id, "❌ لینک‌های خارجی قابل جایگزینی نیستند!", show_alert=True)
        return

    admin_states[call.from_user.id] = {
        'state': 'waiting_replacement_file',
        'file_id': file_id,
        'file_type': file_type
    }

    type_labels = {
        'photo': 'عکس',
        'video': 'ویدیو',
        'document': 'فایل'
    }

    markup = types.InlineKeyboardMarkup(row_width=1)
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="admin_file_uploader")
    markup.add(cancel_btn)

    bot.edit_message_text(
        f"🔄 جایگزینی فایل\n\n"
        f"شما در حال جایگزینی فایل زیر هستید:\n"
        f"🔤 عنوان: {file_info.get('title')}\n"
        f"📁 نوع: {type_labels.get(file_type, file_type)}\n\n"
        f"لطفاً {type_labels.get(file_type, 'فایل')} جدید را برای جایگزینی ارسال کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

# Handler for replacement file upload
@bot.message_handler(content_types=['photo', 'video', 'document'], func=lambda message: 
                    message.from_user.id in admin_states and 
                    admin_states[message.from_user.id].get('state') == 'waiting_replacement_file')
def handle_replacement_file(message):
    user_id = message.from_user.id
    file_id = admin_states[user_id]['file_id']
    expected_type = admin_states[user_id]['file_type']

    # Check if uploaded file type matches the expected type
    if (expected_type == 'photo' and message.content_type != 'photo') or \
       (expected_type == 'video' and message.content_type != 'video') or \
       (expected_type == 'document' and message.content_type != 'document'):
        bot.reply_to(
            message,
            f"❌ نوع فایل اشتباه است! شما باید یک {expected_type} آپلود کنید."
        )
        return

    try:
        # Download the file
        if message.content_type == 'photo':
            file_obj = message.photo[-1]
        elif message.content_type == 'video':
            file_obj = message.video
        else:
            file_obj = message.document

        file_info = bot.get_file(file_obj.file_id)
        downloaded_file = bot.download_file(file_info.file_path)

        # Update file info as needed
        update_info = {}
        if message.caption:
            update_info['caption'] = message.caption

        if message.content_type == 'document' and message.document.file_name:
            update_info['original_filename'] = message.document.file_name

        update_info['telegram_file_id'] = file_obj.file_id

        # Replace the file
        from file_handlers import replace_existing_file
        success = replace_existing_file(file_id, downloaded_file, update_info)

        if success:
            bot.reply_to(
                message,
                "✅ فایل با موفقیت جایگزین شد!\n\n"
                "لینک اشتراک‌گذاری قبلی همچنان معتبر است و فایل جدید از طریق آن قابل دسترسی است."
            )

            # Clear admin state
            del admin_states[user_id]
        else:
            bot.reply_to(
                message,
                "❌ خطا در جایگزینی فایل. لطفاً مجدداً تلاش کنید."
            )
    except Exception as e:
        logger.error(f"Error replacing file {file_id}: {e}")
        bot.reply_to(
            message,
            "❌ خطایی در پردازش فایل رخ داد. لطفاً مجدداً تلاش کنید."
        )

# Start the bot
if __name__ == "__main__":
    logger.info("Bot has deployed successfully✅")
    # Initialize data files if they don't exist
    data = load_data()
    load_dns_ranges()
    # Log admins for debugging
    logger.info(f"Current admins: {data['admins']}")
    # Start bot polling with skip_pending to avoid conflict and timeout parameter
    # Add allowed_updates to optimize requests and prevent conflicts
    bot.polling(none_stop=True, skip_pending=True, timeout=30, allowed_updates=["message", "callback_query"])

def show_file_management(message, file_id):
    data = load_data()
    if file_id in data.get('uploaded_files', {}):
        file_info = data['uploaded_files'][file_id]

        # Check if uploaded_at exists, if not add it
        if 'uploaded_at' not in file_info:
            file_info['uploaded_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            data['uploaded_files'][file_id] = file_info
            save_data(data)

        # Get emoji based on file type
        type_emoji = {
            'photo': '🖼️',
            'video': '🎥',
            'document': '📄',
            'external_url': '🌐'
        }.get(file_info['type'], '📁')

        file_text = (
            f"{type_emoji} مدیریت فایل: {file_info['title']}\n\n"
            f"🔢 شناسه فایل: {file_id}\n"
            f"🔤 عنوان فایل: {file_info['title']}\n"
            f"📁 نوع فایل: {file_info['type']}\n"
            f"📅 تاریخ آپلود: {file_info.get('uploaded_at', 'نامشخص')}\n"
        )

        # Add caption information if available
        if 'caption' in file_info and file_info['caption']:
            file_text += f"📝 کپشن: {file_info['caption']}\n"

        # Add file name for documents
        if file_info['type'] == 'document' and 'original_filename' in file_info:
            file_text += f"📝 نام اصلی فایل: {file_info['original_filename']}\n"

        # Add external URL for external URL type
        if file_info['type'] == 'external_url' and 'external_url' in file_info:
            file_text += f"🔗 آدرس: {file_info['external_url']}\n"

        # Add replaced timestamp if available
        if 'replaced_at' in file_info:
            file_text += f"🔄 آخرین جایگزینی: {file_info['replaced_at']}\n"

        # Get bot username for share link
        bot_username = bot.get_me().username
        share_link = f"https://t.me/{bot_username}?start={file_id}"
        file_text += f"\n🔗 لینک اشتراک‌گذاری:\n<code>{share_link}</code>\n"

        markup = types.InlineKeyboardMarkup(row_width=2)
        edit_btn = types.InlineKeyboardButton("✏️ ویرایش اطلاعات", callback_data=f"admin_edit_file_{file_id}")
        delete_btn = types.InlineKeyboardButton("🗑️ حذف فایل", callback_data=f"admin_delete_file_{file_id}")
        view_btn = types.InlineKeyboardButton("👁️ مشاهده فایل", callback_data=f"file_{file_id}")
        share_btn = types.InlineKeyboardButton("🔗 لینک اشتراک‌گذاری", callback_data=f"share_file_{file_id}")

        markup.add(edit_btn, delete_btn)
        markup.add(view_btn, share_btn)

        # Add replace button for non-external URL files
        if file_info['type'] != 'external_url':
            replace_btn = types.InlineKeyboardButton("🔄 جایگزینی فایل", callback_data=f"replace_file_{file_id}")
            markup.add(replace_btn)

        back_btn = types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_files")
        home_btn = types.InlineKeyboardButton("🏠 بازگشت به پنل ادمین", callback_data="admin_panel")
        markup.add(back_btn)
        markup.add(home_btn)

        # Check if message is too old or not
        try:
            bot.edit_message_text(
                file_text,
                message.chat.id,
                message.message_id,
                reply_markup=markup,
                parse_mode="HTML"
            )
        except Exception as e:
            # If edit fails (message too old), send a new message
            bot.send_message(
                message.chat.id,
                file_text,
                reply_markup=markup,
                parse_mode="HTML"
            )

# دریافت موضوع تیکت
@bot.message_handler(func=lambda message: message.from_user.id in ticket_states and ticket_states[message.from_user.id]['state'] == 'waiting_ticket_subject')
def handle_ticket_subject(message):
    user_id = message.from_user.id
    subject = message.text.strip()

    if not subject:
        bot.reply_to(message, "❌ موضوع تیکت نمی‌تواند خالی باشد. لطفاً دوباره تلاش کنید.")
        return

    # ذخیره موضوع تیکت و تغییر حالت برای دریافت متن تیکت
    ticket_states[user_id]['subject'] = subject
    ticket_states[user_id]['state'] = 'waiting_ticket_text'

    markup = types.InlineKeyboardMarkup(row_width=1)
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="goto_account")
    markup.add(cancel_btn)

    bot.reply_to(
        message,
        f"✅ موضوع: «{subject}»\n\n"
        "لطفاً متن پیام تیکت خود را وارد کنید:",
        reply_markup=markup
    )

# دریافت متن تیکت
@bot.message_handler(func=lambda message: message.from_user.id in ticket_states and ticket_states[message.from_user.id]['state'] == 'waiting_ticket_text')
def handle_ticket_text(message):
    user_id = message.from_user.id
    ticket_text = message.text.strip()

    if not ticket_text:
        bot.reply_to(message, "❌ متن تیکت نمی‌تواند خالی باشد. لطفاً دوباره تلاش کنید.")
        return

    subject = ticket_states[user_id]['subject']

    # ایجاد تیکت در دیتابیس
    data = load_data()

    # بررسی وجود ساختار تیکت‌ها
    if 'tickets' not in data:
        data['tickets'] = {}

    # ایجاد شناسه یکتا برای تیکت
    ticket_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))

    # ذخیره اطلاعات تیکت
    data['tickets'][ticket_id] = {
        'user_id': user_id,
        'subject': subject,
        'text': ticket_text,
        'status': 'open',
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'messages': [
            {
                'sender': 'user',
                'text': ticket_text,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
        ]
    }

    save_data(data)

    # ارسال تایید ثبت تیکت به کاربر
    markup = types.InlineKeyboardMarkup(row_width=1)
    account_btn = types.InlineKeyboardButton("👤 بازگشت به حساب کاربری", callback_data="menu_account")
    markup.add(account_btn)

    bot.reply_to(
        message,
        f"✅ تیکت شما با موفقیت ثبت شد!\n\n"
        f"🔢 شناسه تیکت: <code>{ticket_id}</code>\n"
        f"📋 موضوع: {subject}\n\n"
        "پاسخ تیکت شما در اسرع وقت توسط تیم پشتیبانی بررسی خواهد شد.",
        reply_markup=markup,
        parse_mode="HTML"
    )

    # ارسال اعلان به ادمین‌ها
    admin_markup = types.InlineKeyboardMarkup(row_width=2)
    answer_btn = types.InlineKeyboardButton("✍️ پاسخ", callback_data=f"answer_ticket_{ticket_id}")
    close_btn = types.InlineKeyboardButton("🔒 بستن تیکت", callback_data=f"close_ticket_{ticket_id}")
    admin_markup.add(answer_btn, close_btn)

    admin_text = (
        f"🎫 تیکت جدید دریافت شد\n\n"
        f"👤 کاربر: <code>{user_id}</code>\n"
        f"🔢 شناسه تیکت: <code>{ticket_id}</code>\n"
        f"📋 موضوع: {subject}\n\n"
        f"📝 متن پیام:\n{ticket_text}"
    )

    # ارسال پیام به تمام ادمین‌ها
    for admin_id in data['admins']:
        try:
            bot.send_message(
                admin_id,
                admin_text,
                reply_markup=admin_markup,
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id} about new ticket: {e}")

    # پاک کردن حالت تیکت کاربر
    del ticket_states[user_id]

    # Handle case where file doesn't exist
    try:
        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_files")
        markup.add(back_btn)

        bot.edit_message_text(
            "❌ فایل مورد نظر یافت نشد.",
            message.chat.id,
            message.message_id,
            reply_markup=markup
        )
    except Exception:
        # If we can't edit, send a new message with error
        bot.send_message(
            message.chat.id,
            "❌ فایل مورد نظر یافت نشد.",
            reply_markup=types.InlineKeyboardMarkup().add(
                types.InlineKeyboardButton("🔙 بازگشت به لیست", callback_data="list_files")
            )
        )

# Function to handle file sharing
def handle_share_file_request(call, file_id):
    data = load_data()

    if file_id not in data.get('uploaded_files', {}):
        bot.answer_callback_query(call.id, "فایل مورد نظر یافت نشد!", show_alert=True)
        return

    file_info = data['uploaded_files'][file_id]

    # Get bot username
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={file_id}"

    markup = types.InlineKeyboardMarkup(row_width=1)
    copy_btn = types.InlineKeyboardButton("📋 کپی لینک", callback_data=f"copy_link_{file_id}")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data=f"admin_file_{file_id}")
    share_direct_btn = types.InlineKeyboardButton("📤 اشتراک‌گذاری", url=f"https://t.me/share/url?url={share_link}&text=دانلود%20فایل:%20{file_info['title']}")

    markup.add(copy_btn, share_direct_btn, back_btn)

    bot.edit_message_text(
        f"🔗 اشتراک‌گذاری فایل: {file_info['title']}\n\n"
        f"با استفاده از لینک زیر می‌توانید این فایل را به اشتراک بگذارید:\n\n"
        f"<code>{share_link}</code>\n\n"
        f"کاربران با کلیک روی این لینک، مستقیماً فایل را دریافت خواهند کرد.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("copy_link_"))
def copy_file_link(call):
    file_id = call.data.replace("copy_link_", "")
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={file_id}"

    # We can't actually copy to clipboard, but we can show the link again
    bot.answer_callback_query(
        call.id, 
        "لینک در پیام نمایش داده شده است. آن را انتخاب و کپی کنید.", 
        show_alert=True
    )

# Function to handle create share link
def handle_create_share_link(call):
    data = load_data()

    # اگر هیچ فایلی وجود ندارد
    if not data.get('uploaded_files'):
        bot.edit_message_text(
            "❌ هیچ فایلی برای اشتراک‌گذاری وجود ندارد.\n\n"
            "ابتدا فایل‌های مورد نظر خود را آپلود کنید.",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=types.InlineKeyboardMarkup(row_width=1).add(
                types.InlineKeyboardButton("📤 آپلود فایل", callback_data="admin_file_uploader"),
                types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
            )
        )
        return

    # Create a paginated list of files for sharing
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_id, file_info in list(data['uploaded_files'].items())[:10]:  # First 10 files
        file_title = file_info.get('title', 'فایل بدون عنوان')
        markup.add(types.InlineKeyboardButton(file_title, callback_data=f"share_file_{file_id}"))

    markup.add(types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_file_uploader"))

    bot.edit_message_text(
        "🔗 ایجاد لینک اشتراک‌گذاری\n\n"
        "لطفاً فایل مورد نظر برای اشتراک‌گذاری را انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )


# Function to show paginated user list
def show_user_list(message, page=0, users_per_page=10):
    data = load_data()
    users = list(data['users'].items())
    total_users = len(users)

    start_idx = page * users_per_page
    end_idx = min(start_idx + users_per_page, total_users)

    users_text = f"📊 لیست کاربران (نمایش {start_idx+1} تا {end_idx} از {total_users})\n\n"

    for user_id, user_info in users[start_idx:end_idx]:
        username = user_info.get('username', 'بدون نام کاربری')
        first_name = user_info.get('first_name', 'بدون نام')
        balance = user_info.get('balance', 0)
        dns_count = len(user_info.get('dns_configs', []))
        vpn_count = len(user_info.get('wireguard_configs', []))

        users_text += f"👤 {first_name} (@{username})\n"
        users_text += f"🆔 شناسه: {user_id}\n"
        users_text += f"💰 موجودی: {balance} تومان\n"
        users_text += f"🌐 تعداد DNS: {dns_count}\n"
        users_text += f"🔒 تعداد VPN: {vpn_count}\n"
        users_text += f"📅 عضویت: {user_info.get('join_date', 'نامشخص')}\n\n"

    # Create pagination buttons
    markup = types.InlineKeyboardMarkup(row_width=4)

    pagination_buttons = []
    if page > 0:
        pagination_buttons.append(types.InlineKeyboardButton("◀️", callback_data=f"user_list_page_{page-1}"))

    # Add page indicator
    page_indicator = types.InlineKeyboardButton(f"{page+1}/{(total_users + users_per_page - 1) // users_per_page}", callback_data="dummy")
    pagination_buttons.append(page_indicator)

    if end_idx < total_users:
        pagination_buttons.append(types.InlineKeyboardButton("▶️", callback_data=f"user_list_page_{page+1}"))

    markup.add(*pagination_buttons)

    # Add back button
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")
    markup.add(back_btn)

    bot.edit_message_text(
        users_text,
        message.chat.id,
        message.message_id,
        reply_markup=markup
    )


# Get main menu buttons management keyboard
def get_main_buttons_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    data = load_data()

    if 'main_buttons' not in data.get('settings', {}):
        # Initialize default button settings if they don't exist
        data['settings']['main_buttons'] = {
            'buy_dns': {'title': '🌐 خرید DNS اختصاصی', 'enabled': True},
            'buy_vpn': {'title': '🔒 خرید کانفیگ اختصاصی', 'enabled': True},
            'account': {'title': '💼 حساب کاربری', 'enabled': True},
            'referral': {'title': '👥 دعوت از دوستان', 'enabled': True},
            'support': {'title': '💬 پشتیبانی', 'enabled': True},
            'add_balance': {'title': '💰 افزایش موجودی', 'enabled': True},
            'tutorials': {'title': '📚 آموزش‌ها', 'enabled': True},
            'rules': {'title': '📜 قوانین و مقررات', 'enabled': True}
        }
        save_data(data)

    # Create buttons for each main menu item
    for button_id, button_info in data['settings']['main_buttons'].items():
        status = "✅" if button_info.get('enabled', True) else "❌"
        btn = types.InlineKeyboardButton(
            f"{status} {button_info['title']}", 
            callback_data=f"toggle_main_button_{button_id}"
        )
        markup.add(btn)

    # Back button
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_buttons")
    markup.add(back_btn)

    return markup

# Get tutorial buttons management keyboard
def get_tutorial_buttons_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    data = load_data()
    
    # Temporarily disable 'general' (آموزش عمومی) category
    if 'general' in data['tutorials'] and 'enabled' not in data['tutorials']['general']:
        data['tutorials']['general']['enabled'] = False
        save_data(data)

    for category_id, category in data['tutorials'].items():
        status = "✅" if category.get('enabled', True) else "❌"
        btn = types.InlineKeyboardButton(
            f"{status} {category['title']}", 
            callback_data=f"toggle_tutorial_{category_id}"
        )
        markup.add(btn)

    # Back button
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_buttons")
    markup.add(back_btn)

    return markup

# Toggle button visibility function
def toggle_button_visibility(button_type, button_id):
    data = load_data()

    # Initialize settings if needed
    if 'settings' not in data:
        data['settings'] = {}
    
    if button_type == 'main':
        # Initialize main buttons if needed
        if 'main_buttons' not in data['settings']:
            data['settings']['main_buttons'] = {
                'buy_dns': {'title': '🌐 خرید DNS اختصاصی', 'enabled': True},
                'buy_vpn': {'title': '🔒 خرید کانفیگ اختصاصی', 'enabled': True},
                'account': {'title': '💼 حساب کاربری', 'enabled': True},
                'referral': {'title': '👥 دعوت از دوستان', 'enabled': True},
                'support': {'title': '💬 پشتیبانی', 'enabled': True},
                'add_balance': {'title': '💰 افزایش موجودی', 'enabled': True},
                'tutorials': {'title': '📚 آموزش‌ها', 'enabled': True},
                'rules': {'title': '📜 قوانین و مقررات', 'enabled': True}
            }
            
        if button_id in data['settings']['main_buttons']:
            # Toggle the current state
            current_state = data['settings']['main_buttons'][button_id].get('enabled', True)
            data['settings']['main_buttons'][button_id]['enabled'] = not current_state
            save_data(data)
            return True
    elif button_type == 'tutorial':
        if button_id in data['tutorials']:
            # Initialize enabled property if it doesn't exist
            if 'enabled' not in data['tutorials'][button_id]:
                data['tutorials'][button_id]['enabled'] = True
                
            # Toggle the current state
            current_state = data['tutorials'][button_id].get('enabled', True)
            data['tutorials'][button_id]['enabled'] = not current_state
            save_data(data)
            return True

    return False

# توابع مدیریت کد تخفیف
@bot.callback_query_handler(func=lambda call: call.data.startswith("has_discount_"))
def handle_has_discount(call):
    location_id = call.data.replace("has_discount_", "")
    
    # ذخیره اطلاعات در وضعیت کاربر
    if call.from_user.id not in payment_states:
        payment_states[call.from_user.id] = {}
    
    payment_states[call.from_user.id]['state'] = 'waiting_discount_code'
    payment_states[call.from_user.id]['location_id'] = location_id
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="back_to_main")
    markup.add(cancel_btn)
    
    bot.edit_message_text(
        "🏷️ کد تخفیف\n\n"
        "لطفاً کد تخفیف خود را وارد کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("no_discount_dns_"))
def process_without_discount_dns(call):
    location_id = call.data.replace("no_discount_dns_", "")
    user = get_user(call.from_user.id)
    data = load_data()
    
    if location_id in data['locations'] and data['locations'][location_id]['enabled']:
        location = data['locations'][location_id]
        price = location['price']
        
        if user['balance'] >= price:
            # Generate DNS configuration
            dns_config = generate_dns_config(location_id)
            
            if dns_config:
                # Deduct balance
                user['balance'] -= price
                # Add DNS to user's configs
                user['dns_configs'].append(dns_config)
                data['users'][str(call.from_user.id)] = user
                
                # Record transaction
                transaction_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                if 'transactions' not in data:
                    data['transactions'] = {}
                    
                data['transactions'][transaction_id] = {
                    'user_id': call.from_user.id,
                    'amount': price,
                    'type': 'purchase',
                    'item': 'dns',
                    'location': location_id,
                    'status': 'completed',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                save_data(data)
                
                # Notify user about balance reduction
                bot.send_message(
                    call.from_user.id,
                    f"💸 مبلغ {price} تومان بابت خرید DNS اختصاصی از حساب شما کسر شد.\n"
                    f"💰 موجودی فعلی: {user['balance']} تومان"
                )
                
                success_text = (
                    f"✅ خرید DNS اختصاصی با موفقیت انجام شد!\n\n"
                    f"🌏 موقعیت: {location['name']}\n"
                    f"💰 مبلغ پرداخت شده: {price} تومان\n"
                    f"🔢 شناسه پیکربندی: {dns_config['id']}\n\n"
                    f"🔰 اطلاعات DNS شما:\n\n"
                    f"IPv4: <code>{dns_config['ipv4']}</code>\n\n"
                    f"IPv6 اول: <code>{dns_config['ipv6_1']}</code>\n\n"
                    f"IPv6 دوم: <code>{dns_config['ipv6_2']}</code>\n\n"
                    f"📅 تاریخ خرید: {dns_config['created_at']}\n\n"
                    f"💻 آموزش استفاده از DNS را می‌توانید از بخش آموزش‌ها دریافت کنید."
                )
                
                markup = types.InlineKeyboardMarkup(row_width=1)
                back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
                markup.add(back_btn)
                
                bot.edit_message_text(
                    success_text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup,
                    parse_mode="HTML"
                )
            else:
                bot.answer_callback_query(call.id, "⚠️ خطا در تولید پیکربندی DNS. لطفاً با پشتیبانی تماس بگیرید.")
        else:
            insufficient_text = (
                f"⚠️ موجودی ناکافی\n\n"
                f"💰 موجودی فعلی شما: {user['balance']} تومان\n"
                f"💰 مبلغ مورد نیاز: {price} تومان\n\n"
                f"📝 برای افزایش موجودی به بخش 'حساب کاربری' مراجعه کنید."
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            account_btn = types.InlineKeyboardButton("👤 حساب کاربری", callback_data="goto_account")
            back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
            markup.add(account_btn, back_btn)
            
            bot.edit_message_text(
                insufficient_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )

@bot.callback_query_handler(func=lambda call: call.data.startswith("no_discount_vpn_"))
def process_without_discount_vpn(call):
    location_id = call.data.replace("no_discount_vpn_", "")
    user = get_user(call.from_user.id)
    data = load_data()
    
    if location_id in data['locations'] and data['locations'][location_id]['enabled']:
        location = data['locations'][location_id]
        price = location['price']
        
        if user['balance'] >= price:
            # Ask for confirmation before purchase
            confirm_text = (
                f"🔰 تأیید خرید VPN اختصاصی\n\n"
                f"🌏 موقعیت: {location['name']}\n"
                f"💰 قیمت: {price} تومان\n"
                f"💰 موجودی شما: {user['balance']} تومان\n\n"
                f"آیا مطمئن هستید که می‌خواهید این سرویس را خریداری کنید؟"
            )
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            confirm_btn = types.InlineKeyboardButton("✅ بله، خرید شود", callback_data=f"confirm_vpn_{location_id}")
            cancel_btn = types.InlineKeyboardButton("❌ خیر، انصراف", callback_data="menu_buy_vpn")
            markup.add(confirm_btn, cancel_btn)
            
            bot.edit_message_text(
                confirm_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        else:
            insufficient_text = (
                f"⚠️ موجودی ناکافی\n\n"
                f"💰 موجودی فعلی شما: {user['balance']} تومان\n"
                f"💰 مبلغ مورد نیاز: {price} تومان\n\n"
                f"📝 برای افزایش موجودی به بخش 'حساب کاربری' مراجعه کنید."
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            account_btn = types.InlineKeyboardButton("👤 حساب کاربری", callback_data="goto_account")
            back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
            markup.add(account_btn, back_btn)
            
            bot.edit_message_text(
                insufficient_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )

# دریافت کد تخفیف از کاربر
@bot.message_handler(func=lambda message: message.from_user.id in payment_states and payment_states[message.from_user.id]['state'] == 'waiting_discount_code')
def handle_discount_code(message):
    user_id = message.from_user.id
    discount_code = message.text.strip().upper()  # تبدیل به حروف بزرگ برای استاندارد کردن
    
    if not discount_code:
        bot.reply_to(message, "❌ کد تخفیف نمی‌تواند خالی باشد. لطفاً دوباره تلاش کنید.")
        return
    
    location_id = payment_states[user_id]['location_id']
    
    # بررسی اعتبار کد تخفیف
    data = load_data()
    user = get_user(user_id)
    
    if 'discount_codes' not in data:
        bot.reply_to(message, "❌ کد تخفیف وارد شده معتبر نیست.")
        return
        
    if discount_code not in data['discount_codes']:
        bot.reply_to(message, "❌ کد تخفیف وارد شده معتبر نیست.")
        return
        
    discount_info = data['discount_codes'][discount_code]
    
    # بررسی تاریخ انقضا
    if 'expires_at' in discount_info:
        expiry_date = datetime.strptime(discount_info['expires_at'], '%Y-%m-%d %H:%M:%S')
        if datetime.now() > expiry_date:
            bot.reply_to(message, "❌ این کد تخفیف منقضی شده است.")
            return
            
    # بررسی محدودیت استفاده
    if 'max_uses' in discount_info and discount_info['uses'] >= discount_info['max_uses']:
        bot.reply_to(message, "❌ این کد تخفیف به حداکثر تعداد استفاده رسیده است.")
        return
        
    # محاسبه تخفیف
    location = data['locations'][location_id]
    original_price = location['price']
    
    if discount_info['type'] == 'percentage':
        discount_amount = int(original_price * discount_info['value'] / 100)
    else:  # fixed amount
        discount_amount = discount_info['value']
        
    final_price = max(0, original_price - discount_amount)
    
    # ذخیره اطلاعات تخفیف
    payment_states[user_id]['discount_code'] = discount_code
    payment_states[user_id]['discount_amount'] = discount_amount
    payment_states[user_id]['final_price'] = final_price
    
    # ارسال تاییدیه به کاربر و پرسیدن تایید نهایی
    if 'service_type' not in payment_states[user_id]:
        # تشخیص نوع سرویس براساس کالبک آخر
        if 'no_discount_dns_' in bot.callback_data_cache.get(user_id, {'last': ''})['last']:
            payment_states[user_id]['service_type'] = 'dns'
        else:
            payment_states[user_id]['service_type'] = 'vpn'
    
    service_type = payment_states[user_id].get('service_type', 'dns')  # پیش‌فرض DNS
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    if service_type == 'dns':
        confirm_btn = types.InlineKeyboardButton("✅ تایید و خرید DNS", callback_data=f"confirm_discount_dns_{location_id}")
    else:
        confirm_btn = types.InlineKeyboardButton("✅ تایید و خرید VPN", callback_data=f"confirm_discount_vpn_{location_id}")
        
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="back_to_main")
    markup.add(confirm_btn, cancel_btn)
    
    discount_text = (
        f"✅ کد تخفیف «{discount_code}» با موفقیت اعمال شد!\n\n"
        f"🌏 موقعیت: {location['name']}\n"
        f"💰 قیمت اصلی: {original_price} تومان\n"
        f"🏷️ میزان تخفیف: {discount_amount} تومان\n"
        f"💰 قیمت نهایی: {final_price} تومان\n\n"
        f"💰 موجودی شما: {user['balance']} تومان\n\n"
        "آیا خرید را تایید می‌کنید؟"
    )
    
    bot.reply_to(
        message,
        discount_text,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_discount_dns_"))
def process_dns_with_discount(call):
    location_id = call.data.replace("confirm_discount_dns_", "")
    user_id = call.from_user.id
    
    if user_id not in payment_states or 'discount_code' not in payment_states[user_id]:
        bot.answer_callback_query(call.id, "❌ اطلاعات تخفیف یافت نشد. لطفاً دوباره تلاش کنید.")
        return
        
    user = get_user(user_id)
    data = load_data()
    
    discount_code = payment_states[user_id]['discount_code']
    discount_amount = payment_states[user_id]['discount_amount']
    final_price = payment_states[user_id]['final_price']
    
    if location_id in data['locations'] and data['locations'][location_id]['enabled']:
        if user['balance'] >= final_price:
            # Generate DNS configuration
            dns_config = generate_dns_config(location_id)
            
            if dns_config:
                # Deduct balance
                user['balance'] -= final_price
                # Add DNS to user's configs
                user['dns_configs'].append(dns_config)
                
                # Update discount code usage
                data['discount_codes'][discount_code]['uses'] += 1
                
                # Record transaction with discount info
                transaction_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                if 'transactions' not in data:
                    data['transactions'] = {}
                    
                data['transactions'][transaction_id] = {
                    'user_id': call.from_user.id,
                    'amount': final_price,
                    'original_amount': data['locations'][location_id]['price'],
                    'discount_code': discount_code,
                    'discount_amount': discount_amount,
                    'type': 'purchase',
                    'item': 'dns',
                    'location': location_id,
                    'status': 'completed',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                data['users'][str(call.from_user.id)] = user
                save_data(data)
                
                # Notify user about balance reduction
                bot.send_message(
                    call.from_user.id,
                    f"💸 مبلغ {final_price} تومان بابت خرید DNS اختصاصی از حساب شما کسر شد.\n"
                    f"🏷️ تخفیف اعمال شده: {discount_amount} تومان (کد: {discount_code})\n"
                    f"💰 موجودی فعلی: {user['balance']} تومان"
                )
                
                success_text = (
                    f"✅ خرید DNS اختصاصی با موفقیت انجام شد!\n\n"
                    f"🌏 موقعیت: {data['locations'][location_id]['name']}\n"
                    f"💰 مبلغ اصلی: {data['locations'][location_id]['price']} تومان\n"
                    f"🏷️ تخفیف: {discount_amount} تومان (کد: {discount_code})\n"
                    f"💰 مبلغ پرداخت شده: {final_price} تومان\n"
                    f"🔢 شناسه پیکربندی: {dns_config['id']}\n\n"
                    f"🔰 اطلاعات DNS شما:\n\n"
                    f"IPv4: <code>{dns_config['ipv4']}</code>\n\n"
                    f"IPv6 اول: <code>{dns_config['ipv6_1']}</code>\n\n"
                    f"IPv6 دوم: <code>{dns_config['ipv6_2']}</code>\n\n"
                    f"📅 تاریخ خرید: {dns_config['created_at']}\n\n"
                    f"💻 آموزش استفاده از DNS را می‌توانید از بخش آموزش‌ها دریافت کنید."
                )
                
                markup = types.InlineKeyboardMarkup(row_width=1)
                back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
                markup.add(back_btn)
                
                bot.edit_message_text(
                    success_text,
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup,
                    parse_mode="HTML"
                )
                
                # پاک کردن وضعیت پرداخت
                del payment_states[user_id]
            else:
                bot.answer_callback_query(call.id, "⚠️ خطا در تولید پیکربندی DNS. لطفاً با پشتیبانی تماس بگیرید.")
        else:
            insufficient_text = (
                f"⚠️ موجودی ناکافی\n\n"
                f"💰 موجودی فعلی شما: {user['balance']} تومان\n"
                f"💰 مبلغ مورد نیاز: {final_price} تومان\n\n"
                f"📝 برای افزایش موجودی به بخش 'حساب کاربری' مراجعه کنید."
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            account_btn = types.InlineKeyboardButton("👤 حساب کاربری", callback_data="goto_account")
            back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
            markup.add(account_btn, back_btn)
            
            bot.edit_message_text(
                insufficient_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_discount_vpn_"))
def process_vpn_with_discount(call):
    location_id = call.data.replace("confirm_discount_vpn_", "")
    user_id = call.from_user.id
    
    if user_id not in payment_states or 'discount_code' not in payment_states[user_id]:
        bot.answer_callback_query(call.id, "❌ اطلاعات تخفیف یافت نشد. لطفاً دوباره تلاش کنید.")
        return
        
    user = get_user(user_id)
    data = load_data()
    
    discount_code = payment_states[user_id]['discount_code']
    discount_amount = payment_states[user_id]['discount_amount']
    final_price = payment_states[user_id]['final_price']
    
    if location_id in data['locations'] and data['locations'][location_id]['enabled']:
        if user['balance'] >= final_price:
            # Ask for confirmation before purchase
            confirm_text = (
                f"🔰 تأیید خرید VPN اختصاصی با تخفیف\n\n"
                f"🌏 موقعیت: {data['locations'][location_id]['name']}\n"
                f"💰 قیمت اصلی: {data['locations'][location_id]['price']} تومان\n"
                f"🏷️ تخفیف: {discount_amount} تومان (کد: {discount_code})\n"
                f"💰 قیمت نهایی: {final_price} تومان\n"
                f"💰 موجودی شما: {user['balance']} تومان\n\n"
                f"آیا مطمئن هستید که می‌خواهید این سرویس را خریداری کنید؟"
            )
            
            # ذخیره اطلاعات تخفیف در callback_data
            discount_info = f"{discount_code}_{discount_amount}_{final_price}"
            
            markup = types.InlineKeyboardMarkup(row_width=2)
            confirm_btn = types.InlineKeyboardButton("✅ بله، خرید شود", callback_data=f"confirm_vpn_discount_{location_id}_{discount_info}")
            cancel_btn = types.InlineKeyboardButton("❌ خیر، انصراف", callback_data="menu_buy_vpn")
            markup.add(confirm_btn, cancel_btn)
            
            bot.edit_message_text(
                confirm_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )
        else:
            insufficient_text = (
                f"⚠️ موجودی ناکافی\n\n"
                f"💰 موجودی فعلی شما: {user['balance']} تومان\n"
                f"💰 مبلغ مورد نیاز: {final_price} تومان\n\n"
                f"📝 برای افزایش موجودی به بخش 'حساب کاربری' مراجعه کنید."
            )
            
            markup = types.InlineKeyboardMarkup(row_width=1)
            account_btn = types.InlineKeyboardButton("👤 حساب کاربری", callback_data="goto_account")
            back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
            markup.add(account_btn, back_btn)
            
            bot.edit_message_text(
                insufficient_text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup
            )

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_vpn_discount_"))
def process_confirm_vpn_with_discount(call):
    # جداسازی اطلاعات از callback_data
    parts = call.data.replace("confirm_vpn_discount_", "").split("_")
    location_id = parts[0]
    discount_code = parts[1]
    discount_amount = int(parts[2])
    final_price = int(parts[3])
    
    user = get_user(call.from_user.id)
    data = load_data()
    
    if location_id in data['locations'] and data['locations'][location_id]['enabled']:
        location = data['locations'][location_id]
        original_price = location['price']
        
        if user['balance'] >= final_price:
            # Generate WireGuard configuration
            config_text = generate_wireguard_config(location_id)
            
            if config_text:
                # Create a unique file name with new format
                random_letter = random.choice(string.ascii_uppercase)
                random_digits = ''.join(random.choices(string.digits, k=4))
                config_id = f"{random_letter}{random_digits}"
                file_name = f"{config_id}.conf"
                
                # Save config to a temporary file
                with open(file_name, 'w') as f:
                    f.write(config_text)
                
                # Deduct balance
                user['balance'] -= final_price
                
                # Update discount code usage
                data['discount_codes'][discount_code]['uses'] += 1
                
                # Add config to user's wireguard_configs
                vpn_config = {
                    'id': config_id,
                    'location': location_id,
                    'location_name': location['name'],
                    'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                user['wireguard_configs'].append(vpn_config)
                
                # Record transaction with discount info
                transaction_id = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
                if 'transactions' not in data:
                    data['transactions'] = {}
                    
                data['transactions'][transaction_id] = {
                    'user_id': call.from_user.id,
                    'amount': final_price,
                    'original_amount': original_price,
                    'discount_code': discount_code,
                    'discount_amount': discount_amount,
                    'type': 'purchase',
                    'item': 'vpn',
                    'location': location_id,
                    'status': 'completed',
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                }
                
                data['users'][str(call.from_user.id)] = user
                save_data(data)
                
                # Notify user about balance reduction
                bot.send_message(
                    call.from_user.id,
                    f"💸 مبلغ {final_price} تومان بابت خرید VPN اختصاصی از حساب شما کسر شد.\n"
                    f"🏷️ تخفیف اعمال شده: {discount_amount} تومان (کد: {discount_code})\n"
                    f"💰 موجودی فعلی: {user['balance']} تومان"
                )
                
                # Success message
                success_text = (
                    f"✅ خرید VPN اختصاصی با موفقیت انجام شد!\n\n"
                    f"🌏 موقعیت: {location['name']}\n"
                    f"💰 مبلغ اصلی: {original_price} تومان\n"
                    f"🏷️ تخفیف: {discount_amount} تومان (کد: {discount_code})\n"
                    f"💰 مبلغ پرداخت شده: {final_price} تومان\n"
                    f"🔢 شناسه پیکربندی: {config_id}\n\n"
                    f"📅 تاریخ خرید: {vpn_config['created_at']}\n\n"
                    f"🔽 فایل پیکربندی به زودی ارسال می‌شود...\n\n"
                    f"💻 برای استفاده، فایل را دانلود کرده و در اپلیکیشن WireGuard وارد کنید."
                )
                
                markup = types.InlineKeyboardMarkup(row_width=1)
                back_btn = types.InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="back_to_main")
                markup.add(back_btn)
                
                # نمایش پیام به کاربر بدون حذف پیام خرید موفق
                bot.send_message(
                    call.message.chat.id,
                    success_text,
                    reply_markup=markup
                )
                
                # Then send the config file
                with open(file_name, 'rb') as f:
                    bot.send_document(
                        call.message.chat.id,
                        f,
                        caption=f"🔒 فایل پیکربندی VPN اختصاصی - {location['name']}"
                    )
                
                # Remove temporary file
                os.remove(file_name)
                
                # پاک کردن وضعیت پرداخت
                if call.from_user.id in payment_states:
                    del payment_states[call.from_user.id]
            else:
                bot.answer_callback_query(call.id, "⚠️ خطا در تولید پیکربندی VPN. لطفاً با پشتیبانی تماس بگیرید.")
        else:
            bot.answer_callback_query(call.id, "⚠️ موجودی ناکافی!", show_alert=True)