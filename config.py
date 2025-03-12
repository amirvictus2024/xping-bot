
import os
import logging

# Bot configuration
TOKEN = '7824774995:AAGsV_ZoD67EasUUgX83h4_cXO8pfdRuKYM'  # Your Telegram bot token from BotFather

# Check if TOKEN is set to the placeholder value
if TOKEN == '7824774995:AAGsV_ZoD67EasUUgX83h4_cXO8pfdRuKYM':
    print("⚠️ Please replace the placeholder with your actual Telegram bot token")
    print("Open config.py and replace 'YOUR_TELEGRAM_BOT_TOKEN_HERE' with your token from @BotFather")

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Data storage
DATA_FILE = 'bot_data.pkl'
DNS_RANGES_FILE = 'dns_ranges.pkl'
FILES_DIR = 'uploaded_files'
TUTORIALS_DIR = 'tutorials'

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
            'price': 70000,  # Tomans
            'enabled': True
        },
        'uae': {
            'name': '🇦🇪 امارات',
            'price': 70000,
            'enabled': True
        },
        'russia': {
            'name': '🇷🇺 روسیه',
            'price': 70000,
            'enabled': True
        },
        'france': {
            'name': '🇫🇷 فرانسه',
            'price': 70000,
            'enabled': True
        }
    },
    'uploaded_files': {},
    'tutorials': {
        'dns_usage': {'title': '📘 آموزش دی ان اس', 'files': []},
        'vpn_usage': {'title': '📗 آموزش وایرگارد', 'files': []},
        'panel_usage': {'title': '🖥️ آموزش استفاده از پنل', 'files': []},
        'general': {'title': '📚 آموزش عمومی', 'files': []}
    },
    'discount_codes': {},
    'tickets': {},
    'transactions': {},
    'broadcast_messages': [],
    'blocked_users': []
}

# Payment plans
payment_plans = [
    {"amount": 50000, "name": "پلن برنزی"},
    {"amount": 100000, "name": "پلن نقره‌ای"},
    {"amount": 200000, "name": "پلن طلایی"},
    {"amount": 500000, "name": "پلن الماس"}
]

# State storage for various operations
admin_states = {}
payment_states = {}
file_editing_states = {}
