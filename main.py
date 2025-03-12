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
from ranges import default_dns_ranges

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Bot configuration
TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '7824774995:AAGsV_ZoD67EasUUgX83h4_cXO8pfdRuKYM')
if not TOKEN:
    logger.error("❌ No token provided")
    exit(1)

# Initialize bot with optimized request threading
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)

# Data storage
DATA_FILE = 'bot_data.pkl'
DNS_RANGES_FILE = 'dns_ranges.pkl'
FILES_DIR = 'uploaded_files'
TUTORIALS_DIR = 'tutorials'

# Create directories if they don't exist
os.makedirs(FILES_DIR, exist_ok=True)
os.makedirs(TUTORIALS_DIR, exist_ok=True)

# Default data structure
default_data = {
    'users': {},
    'admins': [6712954701],  # Admin Telegram IDs
    'payment_requests': {},
    'settings': {
        'payment_card': '6219-8619-4308-4037',
        'servers_enabled': True,
        'referral_reward': 2000,  # Tomans (2000 تومان)
    },
    'locations': {
        'germany': {
            'name': '🇩🇪 آلمان',
            'price': 30000,  # Tomans
            'enabled': True
        },
        'uae': {
            'name': '🇦🇪 امارات',
            'price': 28000,
            'enabled': True
        },
        'russia': {
            'name': '🇷🇺 روسیه',
            'price': 25000,
            'enabled': True
        },
        'france': {
            'name': '🇫🇷 فرانسه',
            'price': 27000,
            'enabled': True
        }
    },
    'free_servers': [
        {'name': '🇫🇷 فرانسه رایگان 1', 'location': 'france', 'enabled': True},
        {'name': '🇩🇪 آلمان رایگان 1', 'location': 'germany', 'enabled': True},
        {'name': '🇷🇺 روسیه رایگان 1', 'location': 'russia', 'enabled': True}
    ],
    'uploaded_files': {},
    'tutorials': {
        'dns_usage': {'title': '📘 آموزش DNS', 'files': []},
        'vpn_usage': {'title': '📗 آموزش VPN', 'files': []},
        'payment': {'title': '💳 آموزش پرداخت', 'files': []},
        'general': {'title': '📚 آموزش عمومی', 'files': []}
    },
    'discount_codes': {},
    'tickets': {},
    'transactions': {},
    'broadcast_messages': [],
    'blocked_users': []
}

# Add simple caching to reduce disk IO
_data_cache = None
_last_loaded = 0
_CACHE_TTL = 30  # Cache time-to-live in seconds

# Load data from pickle file with caching
def load_data(force_reload=False):
    global _data_cache, _last_loaded
    current_time = time.time()

    # Return cached data if available and not expired
    if not force_reload and _data_cache is not None and (current_time - _last_loaded) < _CACHE_TTL:
        return _data_cache

    try:
        with open(DATA_FILE, 'rb') as f:
            _data_cache = pickle.load(f)
            _last_loaded = current_time
            return _data_cache
    except (FileNotFoundError, EOFError):
        logger.info("Creating new data file")
        with open(DATA_FILE, 'wb') as f:
            pickle.dump(default_data, f)
        _data_cache = default_data.copy()
        _last_loaded = current_time
        return _data_cache

# Save data to pickle file and update cache
def save_data(data):
    global _data_cache, _last_loaded
    with open(DATA_FILE, 'wb') as f:
        pickle.dump(data, f)
    _data_cache = data
    _last_loaded = time.time()

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
    # Generate random IPv6 for client
    client_ipv6 = f"{WGconfig.DEFAULT_IPV6_PREFIX}{random.randint(1000, 9999)}:{random.randint(1000, 9999)}/64"

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
    if user_id not in data['admins']:
        data['admins'].append(user_id)
        save_data(data)
        return True
    return False

# Generate main menu keyboard (inline)
def get_main_keyboard(user_id=None):
    markup = types.InlineKeyboardMarkup(row_width=2)

    # DNS and VPN buttons (in pairs)
    btn1 = types.InlineKeyboardButton("🌐 خرید DNS اختصاصی", callback_data="menu_buy_dns")
    btn3 = types.InlineKeyboardButton("🔒 خرید کانفیگ اختصاصی", callback_data="menu_buy_vpn")

    # Account and referral buttons
    btn2 = types.InlineKeyboardButton("💼 حساب کاربری", callback_data="menu_account")
    btn7 = types.InlineKeyboardButton("👥 دعوت از دوستان", callback_data="menu_referral")

    # Support and balance buttons
    btn6 = types.InlineKeyboardButton("💬 پشتیبانی", url="https://t.me/xping_official")
    btn5 = types.InlineKeyboardButton("💰 افزایش موجودی", callback_data="add_balance")

    # The rest in pairs of two
    btn8 = types.InlineKeyboardButton("📚 آموزش‌ها", callback_data="menu_tutorials")
    btn9 = types.InlineKeyboardButton("📜 قوانین و مقررات", callback_data="menu_rules")

    # Add buttons to markup with pairs layout
    markup.add(btn1, btn3)
    markup.add(btn2, btn7)
    markup.add(btn6, btn5)
    markup.add(btn8)
    markup.add(btn9)

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

            # First send the welcome message
            welcome_text = (
                f"👋 سلام {message.from_user.first_name} عزیز!\n\n"
                "🌟 به ربات فروش DNS اختصاصی و سرورهای VPN خوش آمدید!\n\n"
                "💻 از طریق این ربات می‌توانید:\n"
                "- DNS اختصاصی با IP معتبر خریداری کنید\n"
                "- VPN اختصاصی خریداری کنید\n"
                "- از سرورهای رایگان VPN استفاده کنید\n"
                "- دوستان خود را دعوت کرده و پاداش دریافت کنید\n\n"
                "🚀 برای شروع، از منوی زیر گزینه مورد نظر خود را انتخاب کنید."
            )

            # Add admin notification
            if check_admin(message.from_user.id):
                welcome_text += "\n\n⚠️ شما دسترسی مدیریت دارید. برای ورود به پنل مدیریت از دکمه پنل مدیریت استفاده کنید."

            bot.send_message(message.chat.id, welcome_text, reply_markup=get_main_keyboard())

            # Now send the requested file
            logger.info(f"🔗 User {message.from_user.id} requested file with ID: {file_id}")
            with open(file_path, 'rb') as f:
                if file_info['type'] == 'photo':
                    bot.send_photo(message.chat.id, f, caption=file_info.get('caption', ''))
                elif file_info['type'] == 'video':
                    bot.send_video(message.chat.id, f, caption=file_info.get('caption', ''))
                elif file_info['type'] == 'document':
                    bot.send_document(message.chat.id, f, caption=file_info.get('caption', ''))
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

# Admin panel
@bot.message_handler(commands=['admin'])
def admin_panel(message):
    if not check_admin(message.from_user.id):
        # Use send_message instead of reply_to to avoid the "message to be replied not found" error
        bot.send_message(message.chat.id, "⛔️ شما به این دستور دسترسی ندارید!")
        return

    admin_text = (
        "⚙️ پنل مدیریت\n\n"
        "👨‍💻 خوش آمدید، ادمین گرامی!\n"
        "لطفاً گزینه مورد نظر خود را انتخاب کنید:"
    )

    bot.send_message(message.chat.id, admin_text, reply_markup=get_admin_keyboard())

# File uploader functions
def get_file_uploader_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)

    btn1 = types.InlineKeyboardButton("🖼️ تصویر", callback_data="upload_photo")
    btn2 = types.InlineKeyboardButton("🎥 ویدیو", callback_data="upload_video")
    btn3 = types.InlineKeyboardButton("📄 فایل", callback_data="upload_document")
    btn4 = types.InlineKeyboardButton("📋 لیست فایل‌ها", callback_data="list_files")
    btn5 = types.InlineKeyboardButton("🔗 ایجاد لینک اشتراک‌گذاری", callback_data="create_share_link")
    btn6 = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")

    markup.add(btn1, btn2, btn3)
    markup.add(btn4, btn5)
    markup.add(btn6)

    return markup

def get_tutorial_categories_keyboard(admin_mode=False):
    markup = types.InlineKeyboardMarkup(row_width=2)
    data = load_data()

    for category_id, category in data['tutorials'].items():
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

def generate_file_id():
    return str(uuid.uuid4())[:8]

# State handler for admin functions
admin_states = {}

# Add balance state handlers
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_user_id')
def handle_add_balance_user_id(message):
    try:
        user_id = int(message.text.strip())
        user = get_user(user_id)

        if user:
            admin_states[message.from_user.id]['user_id'] = user_id
            admin_states[message.from_user.id]['state'] = 'waiting_amount'
            bot.send_message(
                message.chat.id,
                f"👤 کاربر {user_id} انتخاب شد.\n"
                f"💰 موجودی فعلی: {user['balance']} تومان\n\n"
                "لطفاً مبلغ مورد نظر برای افزایش موجودی را وارد کنید (به تومان):"
            )
        else:
            bot.send_message(
                message.chat.id,
                "❌ کاربری با این شناسه یافت نشد. لطفاً مجدداً تلاش کنید یا /cancel را برای لغو وارد کنید."
            )
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک عدد صحیح وارد کنید یا /cancel را برای لغو وارد کنید."
        )

@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_amount')
def handle_add_balance_amount(message):
    try:
        amount = int(message.text.strip())
        user_id = admin_states[message.from_user.id]['user_id']

        if amount > 0:
            if update_user_balance(user_id, amount):
                user = get_user(user_id)
                bot.send_message(
                    message.chat.id,
                    f"✅ مبلغ {amount} تومان به حساب کاربر {user_id} اضافه شد.\n"
                    f"💰 موجودی جدید: {user['balance']} تومان"
                )
                bot.send_message(
                    user_id,
                    f"💰 موجودی حساب شما به میزان {amount} تومان افزایش یافت.\n"
                    f"👨‍💻 توسط: مدیریت"
                )
                # Clear state
                del admin_states[message.from_user.id]
                # Show admin panel again
                admin_panel(message)
            else:
                bot.send_message(
                    message.chat.id,
                    "❌ خطا در بروزرسانی موجودی. لطفاً مجدداً تلاش کنید یا /cancel را برای لغو وارد کنید."
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

# Add admin state handlers
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_admin_id')
def handle_add_admin_id(message):
    try:
        new_admin_id = int(message.text.strip())

        if add_admin(new_admin_id):
            bot.send_message(
                message.chat.id,
                f"✅ کاربر با شناسه {new_admin_id} با موفقیت به عنوان ادمین اضافه شد."
            )
            # Try to notify the new admin
            try:
                bot.send_message(
                    new_admin_id,
                    "🎉 تبریک! شما به عنوان ادمین ربات انتخاب شده‌اید.\n"
                    "برای ورود به پنل مدیریت از دستور /admin استفاده کنید."
                )
            except Exception as e:
                logger.error(f"Failed to notify new admin: {e}")
        else:
            bot.send_message(
                message.chat.id,
                f"⚠️ کاربر با شناسه {new_admin_id} قبلاً به عنوان ادمین اضافه شده است."
            )

        # Clear state
        del admin_states[message.from_user.id]
        # Show admin panel again
        admin_panel(message)
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک عدد صحیح وارد کنید یا /cancel را برای لغو وارد کنید."
        )

# Change card number state handlers
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_card_number')
def handle_change_card_number(message):
    card_number = message.text.strip()

    data = load_data()
    data['settings']['payment_card'] = card_number
    save_data(data)

    bot.send_message(
        message.chat.id,
        f"✅ شماره کارت پرداخت با موفقیت به {card_number} تغییر یافت."
    )

    # Clear state
    del admin_states[message.from_user.id]
    # Show admin panel again
    admin_panel(message)

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
        bot.send_message(message.chat.id, "❌ عملیاتی برای لغو کردن وجود ندارد.")

# Callback query handler with dispatcher pattern
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    # Using a dispatcher pattern for cleaner code organization
    callback_handlers = {
        # Main menu items
        "menu_account": lambda: show_account_info(call.message, call.from_user.id),
        "menu_buy_dns": lambda: show_buy_dns_menu(call.message),
        "menu_buy_vpn": lambda: show_buy_vpn_menu(call.message),
        "menu_support": lambda: show_support_info(call.message),
        "menu_referral": lambda: show_referral_info(call.message, call.from_user.id),
        "menu_tutorials": lambda: show_tutorial_categories(call.message),
        "menu_rules": lambda: show_rules(call.message),

        # Back to main menu
        "back_to_main": lambda: bot.edit_message_text(
            "🏠 منوی اصلی",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_main_keyboard(call.from_user.id)
        ),
        
        # File uploader related callbacks
        "upload_photo": lambda: start_file_upload(call, "photo"),
        "upload_video": lambda: start_file_upload(call, "video"),
        "upload_document": lambda: start_file_upload(call, "document"),
        "list_files": lambda: show_uploaded_files(call),
        "create_share_link": lambda: start_create_share_link(call)
    }

    # Try to get direct handler first
    if call.data in callback_handlers:
        return callback_handlers[call.data]()

    # Handle payment plan selection
    elif call.data.startswith("payment_plan_"):
        handle_payment_plan_selection(call)

    # Admin panel button    
    elif call.data == "admin_panel":
        if call.from_user.id and check_admin(call.from_user.id):
            # Show admin panel directly instead of using /admin command
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

    # Buy DNS
    elif call.data.startswith("buy_dns_"):
        process_buy_dns(call)

    # Buy VPN
    elif call.data.startswith("buy_vpn_"):
        process_buy_vpn(call)
    elif call.data.startswith("confirm_vpn_"):
        process_confirm_vpn(call)


    # Tutorial navigation
    elif call.data == "tutorials":
        show_tutorial_categories(call.message)

    elif call.data.startswith("tutorial_"):
        category_id = call.data.replace("tutorial_", "")
        show_tutorial_files(call.message, category_id)

    elif call.data.startswith("file_"):
        file_id = call.data.replace("file_", "")
        send_file_to_user(call.message, file_id)

    # Admin functions
    elif call.data.startswith("admin_") and check_admin(call.from_user.id):
        process_admin_functions(call)
    elif call.data == "broadcast_all" and check_admin(call.from_user.id):
        admin_states[call.from_user.id] = {'state': 'waiting_broadcast_message'}
        bot.edit_message_text(
            "📢 ارسال پیام به همه کاربران\n\n"
            "لطفاً متن پیامی که می‌خواهید به تمام کاربران ارسال شود را وارد کنید:",
            call.message.chat.id,
            call.message.message_id
        )
    elif call.data == "confirm_broadcast" and check_admin(call.from_user.id):
        if call.from_user.id in admin_states and 'broadcast_text' in admin_states[call.from_user.id]:
            broadcast_text = admin_states[call.from_user.id]['broadcast_text']
            data = load_data()
            
            # Save broadcast to history
            if 'broadcast_messages' not in data:
                data['broadcast_messages'] = []
            
            data['broadcast_messages'].append({
                'text': broadcast_text,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'sent_by': call.from_user.id
            })
            
            # Send to all users
            success = 0
            failed = 0
            for user_id in data['users']:
                try:
                    bot.send_message(
                        int(user_id),
                        f"📢 پیام مهم از مدیریت:\n\n{broadcast_text}"
                    )
                    success += 1
                except Exception as e:
                    failed += 1
                    logging.error(f"Failed to send broadcast to {user_id}: {e}")
            
            save_data(data)
            
            bot.edit_message_text(
                f"✅ پیام با موفقیت به {success} کاربر ارسال شد.\n"
                f"❌ ارسال به {failed} کاربر ناموفق بود.",
                call.message.chat.id,
                call.message.message_id
            )
            
            # Clear state
            del admin_states[call.from_user.id]
    elif call.data == "view_broadcasts" and check_admin(call.from_user.id):
        data = load_data()
        broadcasts = data.get('broadcast_messages', [])
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_broadcast")
        markup.add(back_btn)
        
        if broadcasts:
            broadcasts_text = "📊 پیام‌های سراسری ارسال شده:\n\n"
            for i, broadcast in enumerate(reversed(broadcasts[-10:])):  # Show last 10 messages
                broadcasts_text += f"{i+1}. تاریخ: {broadcast['timestamp']}\n"
                broadcasts_text += f"📄 متن: {broadcast['text'][:50]}...\n\n"
        else:
            broadcasts_text = "📊 تاریخچه پیام‌های سراسری خالی است."
        
        bot.edit_message_text(
            broadcasts_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )
    elif call.data == "change_referral_reward" and check_admin(call.from_user.id):
        admin_states[call.from_user.id] = {'state': 'waiting_referral_amount'}
        data = load_data()
        current_reward = data['settings']['referral_reward']
        
        bot.edit_message_text(
            f"🎁 تغییر مبلغ پاداش رفرال\n\n"
            f"مبلغ فعلی: {current_reward} تومان\n\n"
            f"لطفاً مبلغ جدید پاداش رفرال را به تومان وارد کنید:",
            call.message.chat.id,
            call.message.message_id
        )

    # Payment flow
    elif call.data == "add_balance":
        bot.edit_message_text(
            "💰 افزایش موجودی\n\n"
            "💳 لطفاً یکی از پلن‌های زیر را انتخاب کنید یا مبلغ دلخواه خود را وارد نمایید:",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=get_payment_plans_keyboard(),
            parse_mode="HTML"
        )

    # Custom payment amount
    elif call.data == "payment_custom":
        payment_states[call.from_user.id] = {'state': 'waiting_amount'}

        bot.edit_message_text(
            "💰 افزایش موجودی با مبلغ دلخواه\n\n"
            "لطفاً مبلغ مورد نظر خود را به تومان وارد کنید:",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )

    # Payment approval/rejection
    elif call.data.startswith("approve_payment_") and check_admin(call.from_user.id):
        process_payment_request(call, "approve")

    elif call.data.startswith("reject_payment_") and check_admin(call.from_user.id):
        process_payment_request(call, "reject")

    # Go to account page
    elif call.data == "goto_account":
        show_account_info(call.message, call.from_user.id)

    # Share file functions
    elif call.data.startswith("share_file_"):
        handle_share_file_selection(call)
    elif call.data.startswith("copy_link_"):
        handle_copy_link(call)
    elif call.data.startswith("preview_file_"):
        handle_preview_file(call)
    # Go to account page
    elif call.data == "goto_account":
        show_account_info(call.message, call.from_user.id)

    # Card number change
    elif call.data == "change_card_number" and check_admin(call.from_user.id):
        admin_states[call.from_user.id] = {'state': 'waiting_card_number'}
        data = load_data()
        current_card = data['settings']['payment_card']

        bot.edit_message_text(
            f"💳 تغییر شماره کارت\n\n"
            f"شماره کارت فعلی: <code>{current_card}</code>\n\n"
            f"لطفاً شماره کارت جدید را وارد کنید:",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML"
        )

    else:
        bot.answer_callback_query(call.id, "⚠️ دستور نامعتبر!", show_alert=True)

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
            account_text += f"\n{i+1}. {vpn['location']} - {vpn['created_at']}\n"

    markup = types.InlineKeyboardMarkup(row_width=1)
    payment_btn = types.InlineKeyboardButton("💰 افزایش موجودی", callback_data="add_balance")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
    markup.add(payment_btn)
    markup.add(back_btn)

    bot.edit_message_text(
        account_text,
        message.chat.id,
        message.message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

def show_buy_dns_menu(message):
    buy_text = (
        "🌐 خرید DNS اختصاصی\n\n"
        "🔰 با خرید DNS اختصاصی شما صاحب آدرس‌های IPv4 و IPv6 اختصاصی خواهید شد کهمی‌توانید برای اتصال به اینترنت استفاده کنید.\n\n"
        "✅ مزایای DNS اختصاصی:\n"
        "- پایداری و سرعت بالا\n"
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


def show_support_info(message):
    support_text = (
        "💬 پشتیبانی\n\n"
        "برای ارتباط با پشتیبانی و یا گزارش مشکلات، از طریق لینک زیر اقدام نمایید:\n\n"
        "👤 @xping_official\n\n"
        "⏱ ساعات پاسخگویی: 9 صبح تا 9 شب"
    )

    markup = types.InlineKeyboardMarkup(row_width=2)
    contact_btn = types.InlineKeyboardButton("📲 ارتباط با پشتیبانی", url="https://t.me/xping_official")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="back_to_main")
    markup.add(contact_btn)
    markup.add(back_btn)

    bot.edit_message_text(
        support_text,
        message.chat.id,
        message.message_id,
        reply_markup=markup
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
                    f"💻 آموزش استفاده از DNS را می‌توانید از بخش پشتیبانی دریافت کنید."
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

# Payment state handler for users
payment_states = {}

def get_payment_plans_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    plans = [
        {"amount": 50000, "name": "پلن برنزی"},
        {"amount": 100000, "name": "پلن نقره‌ای"},
        {"amount": 200000, "name": "پلن طلایی"},
        {"amount": 500000, "name": "پلن الماس"}
    ]

    for plan in plans:
        btn = types.InlineKeyboardButton(
            f"{plan['name']} - {plan['amount']} تومان", 
            callback_data=f"payment_plan_{plan['amount']}"
        )
        markup.add(btn)

    custom_btn = types.InlineKeyboardButton("💰 مبلغ دلخواه", callback_data="payment_custom")
    cancel_btn = types.InlineKeyboardButton("❌ انصراف", callback_data="back_to_main")
    markup.add(custom_btn)
    markup.add(cancel_btn)

    return markup

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

def process_payment_request(call, action):
    request_id = call.data.replace(f"{action}_payment_", "")

    data = load_data()
    if 'payment_requests' in data and request_id in data['payment_requests']:
        payment_request = data['payment_requests'][request_id]
        user_id = payment_request['user_id']
        amount = payment_request['amount']
        discount_code = payment_request.get('discount_code', None)
        discount_amount = payment_request.get('discount_amount', 0)
        original_amount = payment_request.get('original_amount', amount)
        transaction_id = payment_request.get('transaction_id', None)

        if action == "approve":
            # Update payment status
            data['payment_requests'][request_id]['status'] = 'approved'

            # Update transaction status if exists
            if transaction_id and transaction_id in data.get('transactions', {}):
                data['transactions'][transaction_id]['status'] = 'approved'

            # Add balance to user
            if str(user_id) in data['users']:
                data['users'][str(user_id)]['balance'] += amount

                # Generate notification message
                notification_text = f"✅ درخواست افزایش موجودی شما به مبلغ {amount} تومان تایید شد.\n"

                # Add discount info if applicable
                if discount_code:
                    notification_text += f"🏷️ کد تخفیف: {discount_code}\n"
                    notification_text += f"💰 میزان تخفیف: {discount_amount} تومان\n"
                    notification_text += f"💰 مبلغ اصلی: {original_amount} تومان\n"

                notification_text += f"💰 موجودی جدید: {data['users'][str(user_id)]['balance']} تومان"

                # Notify user
                try:
                    bot.send_message(
                        user_id,
                        notification_text,
                        parse_mode="HTML"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify user {user_id} about payment approval: {e}")

                # Notify admin
                admin_text = f"✅ درخواست افزایش موجودی به مبلغ {amount} تومان برای کاربر <code>{user_id}</code> تایید شد."
                if discount_code:
                    admin_text += f"\n🏷️ کد تخفیف {discount_code} استفاده شده است."

                bot.edit_message_text(
                    admin_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode="HTML"
                )
        else:  # Reject
            # Update payment status
            data['payment_requests'][request_id]['status'] = 'rejected'

            # Update transaction status if exists
            if transaction_id and transaction_id in data.get('transactions', {}):
                data['transactions'][transaction_id]['status'] = 'rejected'

            # Notify user
            try:
                bot.send_message(
                    user_id,
                    f"❌ درخواست افزایش موجودی شما به مبلغ {amount} تومان رد شد.\n"
                    f"📝 لطفاً برای اطلاعات بیشتر با پشتیبانی تماس بگیرید.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Failed to notify user {user_id} about payment rejection: {e}")

            # Notify admin
            bot.edit_message_text(
                f"❌ درخواست افزایش موجودی به مبلغ {amount} تومان برای کاربر <code>{user_id}</code> رد شد.",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="HTML"
            )

        save_data(data)

def process_admin_functions(call):
    # Using a dispatcher pattern for admin functions
    admin_handlers = {
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
        "upload_photo": lambda: start_file_upload(call, "photo"),
        "upload_video": lambda: start_file_upload(call, "video"),
        "upload_document": lambda: start_file_upload(call, "document"),
        "list_files": lambda: show_uploaded_files(call),
        "create_share_link": lambda: start_create_share_link(call),
        "admin_tutorials": lambda: show_tutorial_categories(call.message, True),
        "admin_tutorial_": lambda: show_tutorial_files(call.message, call.data.replace("admin_tutorial_", ""), True),
        "add_tutorial_": lambda: start_add_tutorial_file(call),
        "admin_file_": lambda: send_file_to_user(call.message, call.data.replace("admin_file_", "")),
        "change_card_number": lambda: handle_change_card_number_callback(call),
        "add_balance_user": lambda: handle_add_balance_to_user(call),
        "gift_all_users": lambda: handle_gift_all_users_menu(call),

        # Added missing handlers for admin functions:
        "admin_broadcast": lambda: handle_broadcast_menu(call),
        "admin_tickets": lambda: handle_tickets_menu(call),
        "admin_discount": lambda: handle_discount_menu(call),
        "admin_users": lambda: handle_users_menu(call),
        "admin_servers": lambda: handle_servers_menu(call),
        "admin_payment_settings": lambda: handle_payment_settings_menu(call),
        "admin_stats": lambda: handle_stats_menu(call),
        "admin_referral": lambda: handle_referral_menu(call),
        "admin_transactions": lambda: handle_transactions_menu(call),
        "admin_services": lambda: handle_services_menu(call),
        "admin_add_admin": lambda: handle_add_admin_menu(call),
        "admin_blocked_users": lambda: handle_blocked_users_menu(call),
        "admin_export_excel": lambda: handle_export_excel_menu(call),
    }

    # First check for direct matches in the dictionary
    if call.data in admin_handlers:
        return admin_handlers[call.data]()
    
    # Then check for prefix matches using starts with
    if call.data.startswith("admin_tutorial_"):
        return show_tutorial_files(call.message, call.data.replace("admin_tutorial_", ""), True)
    elif call.data.startswith("add_tutorial_"):
        return start_add_tutorial_file(call)
    elif call.data.startswith("admin_file_"):
        return send_file_to_user(call.message, call.data.replace("admin_file_", ""))
    elif call.data.startswith("export_"):
        if call.data == "export_users":
            return generate_users_excel(bot, call.message.chat.id)
        elif call.data == "export_transactions":
            return generate_transactions_excel(bot, call.message.chat.id)
    elif call.data == "block_user":
        admin_states[call.from_user.id] = {'state': 'waiting_block_user'}
        bot.edit_message_text(
            "🚫 مسدود کردن کاربر\n\n"
            "لطفاً شناسه (آیدی عددی) کاربر مورد نظر را وارد کنید:",
            call.message.chat.id,
            call.message.message_id
        )
    elif call.data == "user_search":
        admin_states[call.from_user.id] = {'state': 'waiting_search_user'}
        bot.edit_message_text(
            "🔍 جستجوی کاربر\n\n"
            "لطفاً شناسه، نام یا نام کاربری کاربر مورد نظر را وارد کنید:",
            call.message.chat.id,
            call.message.message_id
        )
    elif call.data == "user_history":
        admin_states[call.from_user.id] = {'state': 'waiting_history_user_id'}
        bot.edit_message_text(
            "📊 تاریخچه خرید کاربر\n\n"
            "لطفاً شناسه (آیدی عددی) کاربر مورد نظر را وارد کنید:",
            call.message.chat.id,
            call.message.message_id
        )
    elif call.data == "add_discount":
        admin_states[call.from_user.id] = {'state': 'waiting_discount_code'}
        bot.edit_message_text(
            "🏷️ افزودن کد تخفیف جدید\n\n"
            "لطفاً کد تخفیف را وارد کنید (فقط از حروف انگلیسی و اعداد استفاده کنید):",
            call.message.chat.id,
            call.message.message_id
        )
    elif call.data == "send_reminder":
        send_expiry_reminders(bot)
        bot.answer_callback_query(call.id, "یادآوری‌ها با موفقیت ارسال شد!", show_alert=True)
    
    # Handler for other admin functions that aren't implemented yet
    else:
        bot.answer_callback_query(call.id, "این قابلیت در حال توسعه است. لطفاً بعداً مجدداً تلاش کنید.", show_alert=True)

def handle_add_balance_to_user(call):
    admin_states[call.from_user.id] = {'state': 'waiting_user_id_for_balance'}
    bot.edit_message_text(
        "💰 افزایش موجودی کاربر\n\n"
        "لطفاً شناسه (آیدی عددی) کاربر مورد نظر را وارد کنید:",
        call.message.chat.id,
        call.message.message_id
    )

def handle_gift_all_users_menu(call):
    admin_states[call.from_user.id] = {'state': 'waiting_gift_amount'}
    bot.edit_message_text(
        "🎁 اهدای موجودی به تمام کاربران\n\n"
        "لطفاً مبلغی که می‌خواهید به حساب تمام کاربران اضافه شود را به تومان وارد کنید:",
        call.message.chat.id,
        call.message.message_id
    )

def start_file_upload(call, file_type):
    admin_states[call.from_user.id] = {'state': 'waiting_file', 'file_type': file_type}
    bot.edit_message_text(
        f"📤 آپلود فایل ({file_type})\n\n"
        "لطفاً فایل مورد نظر را ارسال کنید:",
        call.message.chat.id,
        call.message.message_id
    )

def show_uploaded_files(call):
    data = load_data()
    uploaded_files = data['uploaded_files']
    if uploaded_files:
        files_text = "📋 لیست فایل‌های آپلود شده:\n\n"
        for file_id, file_info in uploaded_files.items():
            files_text += f"📄 {file_info['title']} ({file_info['type']})\n"
            files_text += f"🆔 شناسه: {file_id}\n\n"
        bot.edit_message_text(
            files_text,
            call.message.chat.id,
            call.message.message_id
        )
    else:
        bot.edit_message_text(
            "📋 لیست فایل‌های آپلود شده:\n\n"
            "❌ هیچ فایلی آپلود نشده است!",
            call.message.chat.id,
            call.message.message_id
        )


def start_create_share_link(call):
    data = load_data()
    if not data.get('uploaded_files'):
        bot.answer_callback_query(call.id, "هیچ فایلی برای اشتراک‌گذاری وجود ندارد!", show_alert=True)
        return

    # ایجاد کیبورد برای انتخاب فایل از لیست
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_id, file_info in data['uploaded_files'].items():
        btn = types.InlineKeyboardButton(
            f"📄 {file_info['title']} ({file_info['type']})",
            callback_data=f"share_file_{file_id}"
        )
        markup.add(btn)

    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_file_uploader")
    markup.add(back_btn)

    bot.edit_message_text(
        "🔗 ایجاد لینک اشتراک‌گذاری\n\n"
        "لطفاً فایل مورد نظر را از لیست زیر انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("share_file_"))
def handle_share_file_selection(call):
    file_id = call.data.replace("share_file_", "")
    data = load_data()

    if file_id in data['uploaded_files']:
        bot_username = bot.get_me().username
        share_link = f"https://t.me/{bot_username}?start={file_id}"

        # کیبورد برای کپی لینک و بازگشت
        markup = types.InlineKeyboardMarkup(row_width=1)
        copy_btn = types.InlineKeyboardButton("📋 کپی لینک", callback_data=f"copy_link_{file_id}")
        preview_btn = types.InlineKeyboardButton("👁️ پیش‌نمایش فایل", callback_data=f"preview_file_{file_id}")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="create_share_link")
        markup.add(copy_btn, preview_btn, back_btn)

        file_info = data['uploaded_files'][file_id]
        bot.edit_message_text(
            f"✅ لینک اشتراک‌گذاری ایجاد شد!\n\n"
            f"🔢 شناسه فایل: {file_id}\n"
            f"📄 عنوان: {file_info['title']}\n"
            f"🔖 نوع: {file_info['type']}\n\n"
            f"🔗 لینک:\n<code>{share_link}</code>\n\n"
            f"کاربران با کلیک روی این لینک وارد ربات می‌شوند و فایل بلافاصله برای آن‌ها ارسال می‌شود.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup
        )
    else:
        bot.answer_callback_query(call.id, "❌ فایل مورد نظر یافت نشد!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("copy_link_"))
def handle_copy_link(call):
    file_id = call.data.replace("copy_link_", "")
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={file_id}"

    # پاسخ به کاربر و اطلاع از کپی شدن لینک
    bot.answer_callback_query(call.id, "لینک در کلیپ‌بورد کپی شد!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("preview_file_"))
def handle_preview_file(call):
    file_id = call.data.replace("preview_file_", "")
    # ارسال پیش‌نمایش فایل به ادمین
    send_file_to_user(call.message, file_id)

def start_file_upload(call, file_type):
    admin_states[call.from_user.id] = {'state': 'waiting_file', 'file_type': file_type}
    bot.edit_message_text(
        f"📤 آپلود فایل ({file_type})\n\n"
        "لطفاً فایل مورد نظر را ارسال کنید:",
        call.message.chat.id,
        call.message.message_id
    )

def show_uploaded_files(call):
    data = load_data()
    uploaded_files = data['uploaded_files']
    if uploaded_files:
        files_text = "📋 لیست فایل‌های آپلود شده:\n\n"
        for file_id, file_info in uploaded_files.items():
            files_text += f"📄 {file_info['title']} ({file_info['type']})\n"
            files_text += f"🆔 شناسه: {file_id}\n\n"
        bot.edit_message_text(
            files_text,
            call.message.chat.id,
            call.message.message_id
        )
    else:
        bot.edit_message_text(
            "📋 لیست فایل‌های آپلود شده:\n\n"
            "❌ هیچ فایلی آپلود نشده است!",
            call.message.chat.id,
            call.message.message_id
        )


def start_create_share_link(call):
    data = load_data()
    if not data.get('uploaded_files'):
        bot.answer_callback_query(call.id, "هیچ فایلی برای اشتراک‌گذاری وجود ندارد!", show_alert=True)
        return

    # ایجاد کیبورد برای انتخاب فایل از لیست
    markup = types.InlineKeyboardMarkup(row_width=1)
    for file_id, file_info in data['uploaded_files'].items():
        btn = types.InlineKeyboardButton(
            f"📄 {file_info['title']} ({file_info['type']})",
            callback_data=f"share_file_{file_id}"
        )
        markup.add(btn)

    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_file_uploader")
    markup.add(back_btn)

    bot.edit_message_text(
        "🔗 ایجاد لینک اشتراک‌گذاری\n\n"
        "لطفاً فایل مورد نظر را از لیست زیر انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

@bot.callback_query_handler(func=lambda call: call.data.startswith("share_file_"))
def handle_share_file_selection(call):
    file_id = call.data.replace("share_file_", "")
    data = load_data()

    if file_id in data['uploaded_files']:
        bot_username = bot.get_me().username
        share_link = f"https://t.me/{bot_username}?start={file_id}"

        # کیبورد برای کپی لینک و بازگشت
        markup = types.InlineKeyboardMarkup(row_width=1)
        copy_btn = types.InlineKeyboardButton("📋 کپی لینک", callback_data=f"copy_link_{file_id}")
        preview_btn = types.InlineKeyboardButton("👁️ پیش‌نمایش فایل", callback_data=f"preview_file_{file_id}")
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="create_share_link")
        markup.add(copy_btn, preview_btn, back_btn)

        file_info = data['uploaded_files'][file_id]
        bot.edit_message_text(
            f"✅ لینک اشتراک‌گذاری ایجاد شد!\n\n"
            f"🔢 شناسه فایل: {file_id}\n"
            f"📄 عنوان: {file_info['title']}\n"
            f"🔖 نوع: {file_info['type']}\n\n"
            f"🔗 لینک:\n<code>{share_link}</code>\n\n"
            f"کاربران با کلیک روی این لینک وارد ربات می‌شوند و فایل بلافاصله برای آن‌ها ارسال می‌شود.",
            call.message.chat.id,
            call.message.message_id,
            parse_mode="HTML",
            reply_markup=markup
        )
    else:
        bot.answer_callback_query(call.id, "❌ فایل مورد نظر یافت نشد!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("copy_link_"))
def handle_copy_link(call):
    file_id = call.data.replace("copy_link_", "")
    bot_username = bot.get_me().username
    share_link = f"https://t.me/{bot_username}?start={file_id}"

    # پاسخ به کاربر و اطلاع از کپی شدن لینک
    bot.answer_callback_query(call.id, "لینک در کلیپ‌بورد کپی شد!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("preview_file_"))
def handle_preview_file(call):
    file_id = call.data.replace("preview_file_", "")
    # ارسال پیش‌نمایش فایل به ادمین
    send_file_to_user(call.message, file_id)

@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_file')
def handle_file_upload(message):
    admin_state = admin_states[message.from_user.id]
    file_type = admin_state['file_type']
    data = load_data()

    if file_type == 'photo' and message.content_type == 'photo':
        file_id = generate_file_id()
        file_path = os.path.join(FILES_DIR, file_id)
        file_info = bot.download_file(bot.get_file(message.photo[-1].file_id).file_path)
        with open(file_path, 'wb') as f:
            f.write(file_info)
        data['uploaded_files'][file_id] = {'type': 'photo', 'title': message.caption or file_id, 'caption': message.caption}
    elif file_type == 'video' and message.content_type == 'video':
        file_id = generate_file_id()
        file_path = os.path.join(FILES_DIR, file_id)
        file_info = bot.download_file(bot.get_file(message.video.file_id).file_path)
        with open(file_path, 'wb') as f:
            f.write(file_info)
        data['uploaded_files'][file_id] = {'type': 'video', 'title': message.caption or file_id, 'caption': message.caption}
    elif file_type == 'document' and message.content_type == 'document':
        file_id = generate_file_id()
        file_path = os.path.join(FILES_DIR, file_id)
        file_info = bot.download_file(bot.get_file(message.document.file_id).file_path)
        with open(file_path, 'wb') as f:
            f.write(file_info)
        data['uploaded_files'][file_id] = {'type': 'document', 'title': message.document.file_name, 'caption': message.caption}
    else:
        bot.send_message(message.chat.id, "❌ نوع فایل پشتیبانی نمی‌شود. لطفاً فایل صحیحی ارسال کنید.")
        return

    save_data(data)
    bot.send_message(message.chat.id, f"✅ فایل با شناسه {file_id} با موفقیت آپلود شد.")
    del admin_states[message.from_user.id]
    admin_panel(message)

@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_file_id')
def handle_create_share_link(message):
    file_id = message.text.strip()
    data = load_data()

    if file_id in data['uploaded_files']:
        share_link = f"https://t.me/{bot.get_me().username}?start={file_id}"
        bot.send_message(
            message.chat.id,
            f"✅ لینک اشتراک‌گذاری برای فایل با شناسه {file_id} ایجاد شد:\n\n"
            f"{share_link}"
        )
        del admin_states[message.from_user.id]
        admin_panel(message)
    else:
        bot.send_message(
            message.chat.id,
            "❌ فایلی با این شناسه یافت نشد!"
        )
        del admin_states[message.from_user.id]
        admin_panel(message)


def show_tutorial_categories(message, admin_mode=False):
    bot.edit_message_text(
        "📚 آموزش‌ها\n\n"
        "🔰 لطفاً دسته‌بندی مورد نظر خود را انتخاب کنید:",
        message.chat.id,
        message.message_id,
        reply_markup=get_tutorial_categories_keyboard(admin_mode)
    )

def show_rules(message):
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

def get_rules_text():
    try:
        with open('rules.txt', 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        return "متاسفانه متن قوانین در دسترس نیست."

def show_tutorial_files(message, category_id, admin_mode=False):
    bot.edit_message_text(
        f"📚 فایل‌های آموزشی - {get_tutorial_category_title(category_id)}\n\n"
        "🔰 لطفاً فایل مورد نظر خود را انتخاب کنید:",
        message.chat.id,
        message.message_id,
        reply_markup=get_tutorial_files_keyboard(category_id, admin_mode)
    )

def get_tutorial_category_title(category_id):
    data = load_data()
    if category_id in data['tutorials']:
        return data['tutorials'][category_id]['title']
    return "دسته‌بندی نامشخص"

def send_file_to_user(message, file_id):
    data = load_data()
    if file_id in data.get('uploaded_files', {}):
        file_info = data['uploaded_files'][file_id]
        file_path = os.path.join(FILES_DIR, file_id)
        try:
            with open(file_path, 'rb') as f:
                if file_info['type'] == 'photo':
                    bot.send_photo(message.chat.id, f, caption=file_info.get('caption', ''))
                elif file_info['type'] == 'video':
                    bot.send_video(message.chat.id, f, caption=file_info.get('caption', ''))
                elif file_info['type'] == 'document':
                    bot.send_document(message.chat.id, f, caption=file_info.get('caption', ''))
        except FileNotFoundError:
            bot.send_message(message.chat.id, "متاسفانه فایل مورد نظر یافت نشد.")
    else:
        bot.send_message(message.chat.id, "متاسفانه فایل مورد نظر یافت نشد.")

@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_tutorial_file')
def handle_add_tutorial_file(message):
    admin_state = admin_states[message.from_user.id]
    category_id = admin_state['category_id']
    data = load_data()

    if message.content_type == 'photo':
        file_id = generate_file_id()
        file_path = os.path.join(FILES_DIR, file_id)
        file_info = bot.download_file(bot.get_file(message.photo[-1].file_id).file_path)
        with open(file_path, 'wb') as f:
            f.write(file_info)
        data['uploaded_files'][file_id] = {'type': 'photo', 'title': message.caption or file_id, 'caption': message.caption}
    elif message.content_type == 'video':
        file_id = generate_file_id()
        file_path = os.path.join(FILES_DIR, file_id)
        file_info = bot.download_file(bot.get_file(message.video.file_id).file_path)
        with open(file_path, 'wb') as f:
            f.write(file_info)
        data['uploaded_files'][file_id] = {'type': 'video', 'title': message.caption or file_id, 'caption': message.caption}
    elif message.content_type == 'document':
        file_id = generate_file_id()
        file_path = os.path.join(FILES_DIR, file_id)
        file_info = bot.download_file(bot.get_file(message.document.file_id).file_path)
        with open(file_path, 'wb') as f:
            f.write(file_info)
        data['uploaded_files'][file_id] = {'type': 'document', 'title': message.document.file_name, 'caption': message.caption}
    else:
        bot.send_message(message.chat.id, "❌ نوع فایل پشتیبانی نمی‌شود. لطفاً عکس، فیلم یا سند ارسال کنید.")
        return

    data['tutorials'][category_id]['files'].append(file_id)
    save_data(data)
    bot.send_message(message.chat.id, f"✅ فایل با موفقیت اضافه شد.")
    del admin_states[message.from_user.id]
    admin_panel(message)

# Generate discount code management keyboard
def get_discount_keyboard():
    return get_enhanced_discount_keyboard()

# Generate users management keyboard
def get_users_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    btn1 = types.InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="user_search")
    btn2 = types.InlineKeyboardButton("💰 افزایش موجودی کاربر", callback_data="add_balance_user")
    btn3 = types.InlineKeyboardButton("🎁 اهدای موجودی به همه کاربران", callback_data="gift_all_users")
    btn4 = types.InlineKeyboardButton("📊 تاریخچه خرید کاربر", callback_data="user_history")
    btn5 = types.InlineKeyboardButton("📱 ارسال پیام به کاربر", callback_data="message_user")
    btn6 = types.InlineKeyboardButton("🚫 مسدود کردن کاربر", callback_data="block_user")
    btn7 = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    
    markup.add(btn1, btn2, btn3, btn4, btn5, btn6, btn7)
    
    return markup

# Discount code handlers
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_discount_code')
def handle_new_discount_code(message):
    discount_code = message.text.strip().upper()
    admin_states[message.from_user.id]['discount_code'] = discount_code
    admin_states[message.from_user.id]['state'] = 'waiting_discount_amount'

    bot.send_message(
        message.chat.id,
        f"🏷️ کد تخفیف: {discount_code}\n\n"
        "لطفاً مقدار تخفیف را به درصد وارد کنید (عدد بین 1 تا 100):"
    )

@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_discount_amount')
def handle_discount_amount(message):
    try:
        amount = int(message.text.strip())
        if 1 <= amount <= 100:
            discount_code = admin_states[message.from_user.id]['discount_code']
            admin_states[message.from_user.id]['discount_amount'] = amount
            admin_states[message.from_user.id]['state'] = 'waiting_discount_expiry'

            bot.send_message(
                message.chat.id,
                f"🏷️ کد تخفیف: {discount_code}\n"
                f"💰 مقدار تخفیف: {amount}%\n\n"
                "لطفاً تعداد روز اعتبار کد تخفیف را وارد کنید (عدد بین 1 تا 365):"
            )
        else:
            bot.send_message(
                message.chat.id,
                "⚠️ مقدار تخفیف باید بین 1 تا 100 باشد. لطفاً مجدداً وارد کنید:"
            )
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک عدد صحیح وارد کنید:"
        )

@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_discount_expiry')
def handle_discount_expiry(message):
    try:
        days = int(message.text.strip())
        if 1 <= days <= 365:
            discount_code = admin_states[message.from_user.id]['discount_code']
            discount_amount = admin_states[message.from_user.id]['discount_amount']

            # Calculate expiry date
            expiry_date = (datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d')

            # Save discount code
            data = load_data()
            data['discount_codes'][discount_code] = {
                'amount': discount_amount,
                'expiry_date': expiry_date,
                'uses': 0,
                'max_uses': 100,  # Default max uses
                'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            save_data(data)

            bot.send_message(
                message.chat.id,
                f"✅ کد تخفیف با موفقیت ایجاد شد!\n\n"
                f"🏷️ کد تخفیف: {discount_code}\n"
                f"💰 مقدار تخفیف: {discount_amount}%\n"
                f"📅 تاریخ انقضا: {expiry_date}\n"
                f"🔄 حداکثر تعداد استفاده: 100"
            )

            # Clear state and show admin panel
            del admin_states[message.from_user.id]
            admin_panel(message)
        else:
            bot.send_message(
                message.chat.id,
                "⚠️ تعداد روز اعتبار باید بین 1 تا 365 باشد. لطفاً مجدداً وارد کنید:"
            )
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک عدد صحیح وارد کنید:"
        )

# User search handler
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_search_user')
def handle_user_search(message):
    search_term = message.text.strip()
    data = load_data()

    found_users = []
    for user_id, user_info in data['users'].items():
        # Search by user ID
        if search_term in user_id:
            found_users.append((user_id, user_info))
        # Search by username if available
        elif user_info.get('username') and search_term.lower() in user_info['username'].lower():
            found_users.append((user_id, user_info))
        # Search by first name if available
        elif user_info.get('first_name') and search_term.lower() in user_info['first_name'].lower():
            found_users.append((user_id, user_info))

    if found_users:
        response = "🔍 نتایج جستجو:\n\n"
        for user_id, user_info in found_users[:10]:  # Limit to 10 results
            response += f"👤 کاربر: {user_info.get('first_name', 'بدون نام')}\n"
            response += f"🆔 شناسه: <code>{user_id}</code>\n"
            response += f"💰 موجودی: {user_info['balance']} تومان\n"
            response += f"📅 تاریخ عضویت: {user_info['join_date']}\n\n"

        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")
        markup.add(back_btn)

        bot.send_message(
            message.chat.id,
            response,
            reply_markup=markup,
            parse_mode="HTML"
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ هیچ کاربری با این مشخصات یافت نشد!",
            reply_markup=get_advanced_users_management_keyboard()
        )

    # Clear search state
    del admin_states[message.from_user.id]

# Referral amount handler
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_referral_amount')
def handle_referral_amount(message):
    try:
        amount = int(message.text.strip())
        if amount >= 0:
            data = load_data()
            data['settings']['referral_reward'] = amount
            save_data(data)

            bot.send_message(
                message.chat.id,
                f"✅ مقدار پاداش رفرال با موفقیت به {amount} تومان تغییر یافت."
            )

            # Clear state and show admin panel
            del admin_states[message.from_user.id]
            admin_panel(message)
        else:
            bot.send_message(
                message.chat.id,
                "⚠️ مقدار باید بزرگتر یا مساوی صفر باشد. لطفاً مجدداً وارد کنید:"
            )
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک عدد صحیح وارد کنید:"
        )

# Server info handlers
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] in ['waiting_location_info', 'waiting_server_info'])
def handle_server_info(message):
    result = process_add_new_server(bot, admin_states, message.from_user.id, message.text)

    if result:
        bot.send_message(
            message.chat.id,
            "✅ سرور جدید با موفقیت اضافه شد!"
        )

        # Clear state and show admin panel
        del admin_states[message.from_user.id]
        admin_panel(message)

# User purchase history handler
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_history_user_id')
def handle_purchase_history_request(message):
    try:
        user_id = int(message.text.strip())
        history_text = get_user_purchase_history(user_id)

        markup = types.InlineKeyboardMarkup(row_width=1)
        back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_users")
        markup.add(back_btn)

        bot.send_message(
            message.chat.id,
            history_text,
            reply_markup=markup
        )

        # Clear state
        del admin_states[message.from_user.id]
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک شناسه کاربری معتبر (عدد) وارد کنید:"
        )

# Block user handler
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_block_user')
def handle_block_user(message):
    try:
        user_id = int(message.text.strip())
        data = load_data()

        if str(user_id) in data['users']:
            if user_id in data['admins']:
                bot.send_message(
                    message.chat.id,
                    "⚠️ شما نمی‌توانید یک ادمین را مسدود کنید!"
                )
            else:
                if user_id not in data['blocked_users']:
                    data['blocked_users'].append(user_id)
                    save_data(data)
                    bot.send_message(
                        message.chat.id,
                        f"✅ کاربر با شناسه {user_id} با موفقیت مسدود شد."
                    )
                    try:
                        bot.send_message(
                            user_id,
                            "⛔ حساب کاربری شما توسط مدیریت مسدود شده است. لطفاً برای اطلاعات بیشتر با پشتیبانی تماس بگیرید."
                        )
                    except:
                        pass
                else:
                    bot.send_message(
                        message.chat.id,
                        f"⚠️ کاربر با شناسه {user_id} قبلاً مسدود شده است."
                    )
        else:
            bot.send_message(
                message.chat.id,
                "❌ کاربری با این شناسه یافت نشد!"
            )

        # Clear state and show admin panel
        del admin_states[message.from_user.id]
        admin_panel(message)
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک شناسه کاربری معتبر (عدد) وارد کنید:"
        )

# Broadcast message handler
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_broadcast_message')
def handle_broadcast_message(message):
    broadcast_text = message.text
    admin_states[message.from_user.id]['broadcast_text'] = broadcast_text

    markup = types.InlineKeyboardMarkup(row_width=2)
    btn1 = types.InlineKeyboardButton("✅ تایید و ارسال", callback_data="confirm_broadcast")
    btn2 = types.InlineKeyboardButton("❌ انصراف", callback_data="admin_back")
    markup.add(btn1, btn2)

    bot.send_message(
        message.chat.id,        f"📢 پیش‌نمایش پیام:\n\n{broadcast_text}\n\n"
        "آیا از ارسال این پیام به تمام کاربران اطمینان دارید؟",
        reply_markup=markup
    )

# Message to user handler
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_message_user_id')
def handle_message_user_id(message):
    try:
        user_id = int(message.text.strip())
        data = load_data()

        if str(user_id) in data['users']:
            admin_states[message.from_user.id]['target_user_id'] = user_id
            admin_states[message.from_user.id]['state'] = 'waiting_message_text'

            user_info = data['users'][str(user_id)]
            bot.send_message(
                message.chat.id,
                f"👤 کاربر انتخاب شده: {user_info.get('first_name', 'بدون نام')}\n"
                f"🆔 شناسه: {user_id}\n\n"
                "لطفاً پیامی که می‌خواهید به این کاربر ارسال کنید را وارد کنید:"
            )
        else:
            bot.send_message(
                message.chat.id,
                "❌ کاربری با این شناسه یافت نشد! لطفاً مجدداً وارد کنید یا /cancel را برای لغو وارد کنید."
            )
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک شناسه کاربری معتبر (عدد) وارد کنید:"
        )

@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_message_text')
def handle_message_text(message):
    user_id = admin_states[message.from_user.id]['target_user_id']
    message_text = message.text

    try:
        # Add admin signature
        full_message = f"{message_text}\n\n👨‍💻 پیام از طرف مدیریت"

        # Send message to user
        bot.send_message(
            user_id,
            full_message
        )

        bot.send_message(
            message.chat.id,
            f"✅ پیام شما با موفقیت به کاربر {user_id} ارسال شد."
        )
    except Exception as e:
        bot.send_message(
            message.chat.id,
            f"❌ خطا در ارسال پیام: {str(e)}"
        )

    # Clear state and show admin panel
    del admin_states[message.from_user.id]
    admin_panel(message)

# Function to check valid discount code
def check_discount_code(code, amount):
    data = load_data()
    if code.upper() in data['discount_codes']:
        discount_info = data['discount_codes'][code.upper()]

        # Check if code is expired
        expiry_date = datetime.strptime(discount_info['expiry_date'], '%Y-%m-%d')
        if expiry_date < datetime.now():
            return None, "منقضی شده"

        # Check if code has reached max uses
        if discount_info['uses'] >= discount_info['max_uses']:
            return None, "به حداکثر استفاده رسیده"

        # Calculate discount amount
        discount_percent = discount_info['amount']
        discount_amount = int((discount_percent / 100) * amount)

        return discount_amount, f"{discount_percent}% ({discount_amount} تومان)"
    return None, "نامعتبر"

# Apply discount code handler
@bot.message_handler(func=lambda message: message.from_user.id in payment_states and payment_states[message.from_user.id]['state'] == 'waiting_discount_code')
def handle_apply_discount(message):
    discount_code = message.text.strip()
    amount = payment_states[message.from_user.id]['amount']

    discount_amount, status = check_discount_code(discount_code, amount)

    if discount_amount:
        new_amount = amount - discount_amount
        payment_states[message.from_user.id]['amount'] = new_amount
        payment_states[message.from_user.id]['discount_code'] = discount_code.upper()
        payment_states[message.from_user.id]['discount_amount'] = discount_amount
        payment_states[message.from_user.id]['state'] = 'waiting_receipt'

        data = load_data()
        card_number = data['settings']['payment_card']

        bot.send_message(
            message.chat.id,
            f"✅ کد تخفیف اعمال شد!\n\n"
            f"🏷️ کد تخفیف: {discount_code.upper()}\n"
            f"💰 میزان تخفیف: {status}\n"
            f"💰 مبلغ نهایی: {new_amount} تومان\n\n"
            f"لطفاً مبلغ را به شماره کارت زیر واریز کنید:\n"
            f"<code>{card_number}</code>\n\n"
            f"پس از واریز، لطفاً تصویر رسید پرداخت را ارسال کنید.",
            parse_mode="HTML"
        )
    else:
        bot.send_message(
            message.chat.id,
            f"❌ کد تخفیف {discount_code} {status} است!\n"
            "لطفاً کد دیگری وارد کنید یا برای ادامه بدون تخفیف، /cancel را وارد کنید."
        )
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_user_id_for_balance')
def handle_add_balance_by_id(message):
    try:
        user_id = int(message.text.strip())
        user = get_user(user_id)

        if user:
            admin_states[message.from_user.id]['user_id'] = user_id
            admin_states[message.from_user.id]['state'] = 'waiting_amount_for_balance'
            bot.send_message(
                message.chat.id,
                f"👤 کاربر {user_id} انتخاب شد.\n"
                f"💰 موجودی فعلی: {user['balance']} تومان\n\n"
                "لطفاً مبلغ مورد نظر برای افزایش موجودی را وارد کنید (به تومان):"
            )
        else:
            bot.send_message(
                message.chat.id,
                "❌ کاربری با این شناسه یافت نشد. لطفاً مجدداً تلاش کنید یا /cancel را برای لغو وارد کنید."
            )
    except ValueError:
        bot.send_message(
            message.chat.id,
            "⚠️ لطفاً یک عدد صحیح وارد کنید یا /cancel را برای لغو وارد کنید."
        )

@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_amount_for_balance')
def handle_add_balance_amount_by_id(message):
    try:
        amount = int(message.text.strip())
        user_id = admin_states[message.from_user.id]['user_id']

        if amount > 0:
            if update_user_balance(user_id, amount):
                user = get_user(user_id)
                bot.send_message(
                    message.chat.id,
                    f"✅ مبلغ {amount} تومان به حساب کاربر {user_id} اضافه شد.\n"
                    f"💰 موجودی جدید: {user['balance']} تومان"
                )
                bot.send_message(
                    user_id,
                    f"💰 موجودی حساب شما به میزان {amount} تومان افزایش یافت.\n"
                    f"👨‍💻 توسط: مدیریت"
                )
                # Clear state
                del admin_states[message.from_user.id]
                # Show admin panel again
                admin_panel(message)
            else:
                bot.send_message(
                    message.chat.id,
                    "❌ خطا در بروزرسانی موجودی. لطفاً مجدداً تلاش کنید یا /cancel را برای لغو وارد کنید."
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
@bot.message_handler(func=lambda message: message.from_user.id in admin_states and admin_states[message.from_user.id]['state'] == 'waiting_gift_amount')
def handle_gift_all_users(message):
    try:
        amount = int(message.text.strip())
        if amount > 0:
            data = load_data()
            for user_id in data['users']:
                update_user_balance(int(user_id), amount)
                bot.send_message(
                    int(user_id),
                    f"🎁 هدیه از طرف مدیریت:\n\n"
                    f"💰 مبلغ {amount} تومان به حساب شما اضافه شد!"
                )
            bot.send_message(
                message.chat.id,
                f"✅ مبلغ {amount} تومان به حساب همه کاربران اضافه شد."
            )
            del admin_states[message.from_user.id]
            admin_panel(message)
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

# توابع مدیریتی پنل ادمین
def handle_tickets_menu(call):
    markup = types.InlineKeyboardMarkup(row_width=1)
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    markup.add(back_btn)
    
    bot.edit_message_text(
        "💬 مدیریت تیکت‌ها\n\n"
        "این بخش در حال توسعه است.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def handle_discount_menu(call):
    bot.edit_message_text(
        "🏷️ مدیریت کدهای تخفیف\n\n"
        "در این بخش می‌توانید کدهای تخفیف را مدیریت کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=get_discount_keyboard()
    )

def handle_users_menu(call):
    bot.edit_message_text(
        "👥 مدیریت کاربران\n\n"
        "در این بخش می‌توانید کاربران را مدیریت کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=get_users_management_keyboard()
    )

def handle_servers_menu(call):
    bot.edit_message_text(
        "🖥️ مدیریت سرورها\n\n"
        "در این بخش می‌توانید سرورها را مدیریت کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=get_advanced_server_management_keyboard()
    )

def handle_payment_settings_menu(call):
    data = load_data()
    current_card = data['settings']['payment_card']
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("💳 تغییر شماره کارت", callback_data="change_card_number")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    markup.add(btn1, back_btn)
    
    bot.edit_message_text(
        f"💰 تنظیمات پرداخت\n\n"
        f"شماره کارت فعلی: <code>{current_card}</code>",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

def handle_stats_menu(call):
    data = load_data()
    
    # محاسبه آمار
    total_users = len(data['users'])
    total_dns = sum(len(user['dns_configs']) for user in data['users'].values())
    total_vpn = sum(len(user['wireguard_configs']) for user in data['users'].values())
    total_balance = sum(user['balance'] for user in data['users'].values())
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    markup.add(back_btn)
    
    bot.edit_message_text(
        f"📊 آمار ربات\n\n"
        f"👥 تعداد کل کاربران: {total_users}\n"
        f"🌐 تعداد DNS فروخته شده: {total_dns}\n"
        f"🔒 تعداد VPN فروخته شده: {total_vpn}\n"
        f"💰 مجموع موجودی کاربران: {total_balance} تومان",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def handle_referral_menu(call):
    data = load_data()
    current_reward = data['settings']['referral_reward']
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton(f"🎁 تغییر مبلغ پاداش (فعلی: {current_reward} تومان)", callback_data="change_referral_reward")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    markup.add(btn1, back_btn)
    
    bot.edit_message_text(
        "👥 مدیریت سیستم دعوت\n\n"
        "در این بخش می‌توانید تنظیمات سیستم دعوت را مدیریت کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def handle_transactions_menu(call):
    bot.edit_message_text(
        "💰 مدیریت تراکنش‌ها\n\n"
        "در این بخش می‌توانید تراکنش‌ها را مدیریت کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=get_transaction_management_keyboard()
    )

def handle_services_menu(call):
    bot.edit_message_text(
        "🛠️ مدیریت سرویس‌ها\n\n"
        "در این بخش می‌توانید سرویس‌های DNS و VPN را مدیریت کنید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=get_service_management_keyboard()
    )

def handle_add_admin_menu(call):
    admin_states[call.from_user.id] = {'state': 'waiting_admin_id'}
    
    bot.edit_message_text(
        "➕ افزودن ادمین جدید\n\n"
        "لطفاً شناسه کاربری (آیدی عددی) ادمین جدید را وارد کنید:",
        call.message.chat.id,
        call.message.message_id
    )

def handle_blocked_users_menu(call):
    data = load_data()
    blocked_users = data.get('blocked_users', [])
    
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("➕ مسدود کردن کاربر جدید", callback_data="block_user")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    markup.add(btn1, back_btn)
    
    if blocked_users:
        blocked_text = "🚫 لیست کاربران مسدود شده:\n\n"
        for user_id in blocked_users:
            user_info = data['users'].get(str(user_id), {})
            name = user_info.get('first_name', 'کاربر ناشناس')
            blocked_text += f"🆔 {user_id} - {name}\n"
    else:
        blocked_text = "🚫 لیست کاربران مسدود شده خالی است."
    
    bot.edit_message_text(
        blocked_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def handle_export_excel_menu(call):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("📊 گزارش کاربران", callback_data="export_users")
    btn2 = types.InlineKeyboardButton("💰 گزارش تراکنش‌ها", callback_data="export_transactions")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    markup.add(btn1, btn2, back_btn)
    
    bot.edit_message_text(
        "📊 گزارش اکسل\n\n"
        "لطفاً نوع گزارش مورد نظر خود را انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )

def start_add_tutorial_file(call):
    category_id = call.data.replace("add_tutorial_", "")
    admin_states[call.from_user.id] = {'state': 'waiting_tutorial_file', 'category_id': category_id}
    
    bot.edit_message_text(
        f"📤 افزودن فایل به دسته‌بندی {get_tutorial_category_title(category_id)}\n\n"
        "لطفاً فایل مورد نظر را ارسال کنید (عکس، فیلم یا سند):",
        call.message.chat.id,
        call.message.message_id
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

def handle_change_card_number_callback(call):
    admin_states[call.from_user.id] = {'state': 'waiting_card_number'}
    data = load_data()
    current_card = data['settings']['payment_card']

    bot.edit_message_text(
        f"💳 تغییر شماره کارت\n\n"
        f"شماره کارت فعلی: <code>{current_card}</code>\n\n"
        f"لطفاً شماره کارت جدید را وارد کنید:",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML"
    )

def handle_broadcast_menu(call):
    markup = types.InlineKeyboardMarkup(row_width=1)
    btn1 = types.InlineKeyboardButton("📢 ارسال پیام به همه کاربران", callback_data="broadcast_all")
    btn2 = types.InlineKeyboardButton("📊 مشاهده پیام‌های قبلی", callback_data="view_broadcasts")
    back_btn = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    markup.add(btn1, btn2, back_btn)

    bot.edit_message_text(
        "📢 مدیریت پیام‌های سراسری\n\n"
        "از این بخش می‌توانید به تمام کاربران ربات پیام ارسال کنید یا پیام‌های قبلی را مشاهده نمایید.",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )