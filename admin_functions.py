
import os
import pickle
import logging
import datetime
import random
import string
import telebot
from telebot import types
from datetime import datetime, timedelta
import pandas as pd
import io

# Load data function
def load_data(DATA_FILE='bot_data.pkl'):
    try:
        with open(DATA_FILE, 'rb') as f:
            return pickle.load(f)
    except (FileNotFoundError, EOFError):
        logger = logging.getLogger(__name__)
        logger.error("Failed to load data file")
        return None

# Save data function
def save_data(data, DATA_FILE='bot_data.pkl'):
    with open(DATA_FILE, 'wb') as f:
        pickle.dump(data, f)

# Enhanced admin keyboard with more options
def get_enhanced_admin_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)

    # مدیریت کاربران و سرورها
    btn1 = types.InlineKeyboardButton("👥 مدیریت کاربران", callback_data="admin_users")
    btn2 = types.InlineKeyboardButton("🌐 مدیریت سرورها", callback_data="admin_servers")
    
    # مدیریت مالی و آمار
    btn3 = types.InlineKeyboardButton("💳 تنظیمات پرداخت", callback_data="admin_payment_settings")
    btn4 = types.InlineKeyboardButton("📈 آمار و گزارش", callback_data="admin_stats")
    
    # مدیریت تیکت و پیام‌ها
    btn5 = types.InlineKeyboardButton("🎫 مدیریت تیکت‌ها", callback_data="admin_tickets")
    btn6 = types.InlineKeyboardButton("📩 ارسال پیام گروهی", callback_data="admin_broadcast")
    
    # مدیریت تخفیف‌ها
    btn7 = types.InlineKeyboardButton("🏷️ کدهای تخفیف", callback_data="admin_discount")
    btn8 = types.InlineKeyboardButton("🔄 تنظیم رفرال", callback_data="admin_referral")
    
    # مدیریت سرویس‌ها و تراکنش‌ها
    btn9 = types.InlineKeyboardButton("💹 تراکنش‌ها", callback_data="admin_transactions")
    btn10 = types.InlineKeyboardButton("⏱️ مدیریت سرویس‌ها", callback_data="admin_services")
    
    # مدیریت دسترسی‌ها
    btn11 = types.InlineKeyboardButton("➕ افزودن ادمین", callback_data="admin_add_admin")
    btn12 = types.InlineKeyboardButton("🚫 کاربران مسدود", callback_data="admin_blocked_users")

    # گزارش و آموزش
    btn13 = types.InlineKeyboardButton("📊 گزارش اکسل", callback_data="admin_export_excel")
    btn14 = types.InlineKeyboardButton("📚 آموزش‌ها", callback_data="admin_tutorials")
    
    # بازگشت
    btn15 = types.InlineKeyboardButton("🏠 بازگشت به اصلی", callback_data="back_to_main")

    # چینش دکمه‌ها
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5, btn6)
    markup.add(btn7, btn8)
    markup.add(btn9, btn10)
    markup.add(btn11, btn12)
    markup.add(btn13, btn14)
    markup.add(btn15)

    return markup

# Advanced user management functions
def get_advanced_users_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton("🔍 جستجوی کاربر", callback_data="search_user")
    btn2 = types.InlineKeyboardButton("💰 افزایش موجودی", callback_data="add_user_balance")
    btn3 = types.InlineKeyboardButton("📊 لیست کاربران", callback_data="list_users")
    btn4 = types.InlineKeyboardButton("🚫 مسدودسازی کاربر", callback_data="block_user")
    btn5 = types.InlineKeyboardButton("📨 ارسال پیام به کاربر", callback_data="message_user")
    btn6 = types.InlineKeyboardButton("📜 تاریخچه خرید", callback_data="user_purchase_history")
    btn7 = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5, btn6)
    markup.add(btn7)
    
    return markup

# Enhanced discount management
def get_enhanced_discount_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)

    btn1 = types.InlineKeyboardButton("➕ افزودن کد تخفیف", callback_data="add_discount")
    btn2 = types.InlineKeyboardButton("📋 لیست کدهای تخفیف", callback_data="list_discounts")
    btn3 = types.InlineKeyboardButton("⏱️ تخفیف زمان‌دار", callback_data="timed_discount")
    btn4 = types.InlineKeyboardButton("❌ حذف کد تخفیف", callback_data="delete_discount")
    btn5 = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5)

    return markup

# Advanced server management 
def get_advanced_server_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton("➕ افزودن سرور جدید", callback_data="add_new_server")
    btn2 = types.InlineKeyboardButton("🔄 ویرایش سرور", callback_data="edit_server")
    btn3 = types.InlineKeyboardButton("📋 لیست سرورها", callback_data="list_servers")
    btn4 = types.InlineKeyboardButton("🔍 وضعیت سرورها", callback_data="server_status")
    btn5 = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5)
    
    return markup

# Ticket management system
def get_ticket_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton("📬 تیکت‌های جدید", callback_data="new_tickets")
    btn2 = types.InlineKeyboardButton("📝 تیکت‌های در حال بررسی", callback_data="pending_tickets")
    btn3 = types.InlineKeyboardButton("✅ تیکت‌های پاسخ داده شده", callback_data="answered_tickets")
    btn4 = types.InlineKeyboardButton("❌ تیکت‌های بسته", callback_data="closed_tickets")
    btn5 = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5)
    
    return markup

# Transaction management
def get_transaction_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton("✅ تراکنش‌های موفق", callback_data="successful_transactions")
    btn2 = types.InlineKeyboardButton("❌ تراکنش‌های ناموفق", callback_data="failed_transactions")
    btn3 = types.InlineKeyboardButton("⏳ تراکنش‌های در انتظار", callback_data="pending_transactions")
    btn4 = types.InlineKeyboardButton("📊 گزارش مالی", callback_data="financial_report")
    btn5 = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5)
    
    return markup

# Service management
def get_service_management_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    btn1 = types.InlineKeyboardButton("📝 سرویس‌های فعال", callback_data="active_services")
    btn2 = types.InlineKeyboardButton("⏱️ سرویس‌های نزدیک انقضا", callback_data="expiring_services")
    btn3 = types.InlineKeyboardButton("⚠️ ارسال یادآوری", callback_data="send_expiry_reminder")
    btn4 = types.InlineKeyboardButton("🔄 تمدید دستی", callback_data="manual_renew")
    btn5 = types.InlineKeyboardButton("🔙 بازگشت", callback_data="admin_back")
    
    markup.add(btn1, btn2)
    markup.add(btn3, btn4)
    markup.add(btn5)
    
    return markup

# Generate Excel report for transactions
def generate_transactions_excel(bot, chat_id):
    data = load_data()
    
    if not data or 'transactions' not in data or not data['transactions']:
        bot.send_message(chat_id, "❌ هیچ تراکنشی یافت نشد!")
        return
    
    transactions = data['transactions']
    
    # Convert to dataframe
    transaction_records = []
    for tx_id, tx_info in transactions.items():
        user_id = tx_info.get('user_id', 'نامشخص')
        user_name = 'نامشخص'
        
        # Try to get user name if user exists
        if str(user_id) in data.get('users', {}):
            user_name = data['users'][str(user_id)].get('first_name', 'نامشخص')
        
        record = {
            'شناسه تراکنش': tx_id,
            'کاربر': f"{user_name} ({user_id})",
            'مبلغ': tx_info.get('amount', 0),
            'نوع': tx_info.get('type', 'نامشخص'),
            'وضعیت': tx_info.get('status', 'نامشخص'),
            'زمان': tx_info.get('timestamp', 'نامشخص')
        }
        
        if 'discount_code' in tx_info and tx_info['discount_code']:
            record['کد تخفیف'] = tx_info['discount_code']
            record['مقدار تخفیف'] = tx_info.get('discount_amount', 0)
            record['مبلغ اصلی'] = tx_info.get('original_amount', 0)
        
        transaction_records.append(record)
    
    # Create Excel file
    df = pd.DataFrame(transaction_records)
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False, engine='openpyxl')
    excel_file.seek(0)
    
    # Send Excel file
    bot.send_document(
        chat_id,
        excel_file,
        visible_file_name='transactions_report.xlsx',
        caption="📊 گزارش تراکنش‌ها"
    )

# Generate user report in Excel
def generate_users_excel(bot, chat_id):
    data = load_data()
    
    if not data or 'users' not in data or not data['users']:
        bot.send_message(chat_id, "❌ هیچ کاربری یافت نشد!")
        return
    
    users = data['users']
    
    # Convert to dataframe
    user_records = []
    for user_id, user_info in users.items():
        record = {
            'شناسه کاربر': user_id,
            'نام': user_info.get('first_name', 'نامشخص'),
            'نام کاربری': user_info.get('username', 'نامشخص'),
            'موجودی': user_info.get('balance', 0),
            'تعداد DNS': len(user_info.get('dns_configs', [])),
            'تعداد VPN': len(user_info.get('wireguard_configs', [])),
            'کد دعوت': user_info.get('referral_code', 'نامشخص'),
            'تعداد دعوت‌ها': len(user_info.get('referrals', [])),
            'تاریخ عضویت': user_info.get('join_date', 'نامشخص')
        }
        user_records.append(record)
    
    # Create Excel file
    df = pd.DataFrame(user_records)
    excel_file = io.BytesIO()
    df.to_excel(excel_file, index=False, engine='openpyxl')
    excel_file.seek(0)
    
    # Send Excel file
    bot.send_document(
        chat_id,
        excel_file,
        visible_file_name='users_report.xlsx',
        caption="📊 گزارش کاربران"
    )

# Process adding new server
def process_add_new_server(bot, admin_states, user_id, message_text):
    # Parse the server info from the message
    lines = message_text.strip().split('\n')
    server_info = {}
    
    for line in lines:
        if ':' in line:
            key, value = line.split(':', 1)
            server_info[key.strip()] = value.strip()
    
    # Check for required fields
    required_fields = ['name', 'location', 'price']
    missing_fields = [field for field in required_fields if field not in server_info]
    
    if missing_fields:
        bot.send_message(
            user_id, 
            f"❌ اطلاعات ناقص است. لطفاً فیلدهای زیر را تکمیل کنید: {', '.join(missing_fields)}"
        )
        return False
    
    # Add the server to the data
    data = load_data()
    
    # For a location
    if admin_states[user_id].get('server_type') == 'location':
        location_id = server_info['location'].lower().replace(' ', '_')
        data['locations'][location_id] = {
            'name': server_info['name'],
            'price': int(server_info['price']),
            'enabled': True
        }
    
    
    
    save_data(data)
    return True

# Get user purchase history
def get_user_purchase_history(user_id):
    data = load_data()
    
    if str(user_id) not in data['users']:
        return "❌ کاربری با این شناسه یافت نشد!"
    
    user = data['users'][str(user_id)]
    history_text = f"📜 تاریخچه خرید کاربر {user_id}:\n\n"
    
    # Add DNS purchase history
    if user['dns_configs']:
        history_text += "🌐 DNS های خریداری شده:\n"
        for i, dns in enumerate(user['dns_configs']):
            history_text += f"{i+1}. {dns.get('location', 'نامشخص')} - {dns.get('created_at', 'نامشخص')}\n"
    else:
        history_text += "🌐 تاکنون DNS خریداری نشده است.\n"
    
    # Add VPN purchase history
    if user.get('wireguard_configs', []):
        history_text += "\n🔒 VPN های خریداری شده:\n"
        for i, vpn in enumerate(user.get('wireguard_configs', [])):
            history_text += f"{i+1}. {vpn.get('location_name', 'نامشخص')} - {vpn.get('created_at', 'نامشخص')}\n"
    else:
        history_text += "\n🔒 تاکنون VPN خریداری نشده است.\n"
    
    # Add transaction history
    transactions = [tx for tx_id, tx in data.get('transactions', {}).items() if tx.get('user_id') == int(user_id)]
    
    if transactions:
        history_text += "\n💰 تراکنش‌ها:\n"
        for i, tx in enumerate(sorted(transactions, key=lambda x: x.get('timestamp', ''), reverse=True)):
            status = "✅" if tx.get('status') == 'approved' else "❌" if tx.get('status') == 'rejected' else "⏳"
            history_text += f"{i+1}. {status} {tx.get('amount', 0)} تومان - {tx.get('timestamp', 'نامشخص')}\n"
    else:
        history_text += "\n💰 تاکنون تراکنشی انجام نشده است.\n"
    
    return history_text

# Send reminder to users with expiring services
def send_expiry_reminders(bot):
    data = load_data()
    now = datetime.now()
    reminder_count = 0
    
    for user_id, user_info in data['users'].items():
        # Check DNS configs for expiration
        for dns in user_info.get('dns_configs', []):
            if 'expiry_date' in dns:
                expiry = datetime.strptime(dns['expiry_date'], '%Y-%m-%d %H:%M:%S')
                days_left = (expiry - now).days
                
                if 0 <= days_left <= 3:  # Send reminder if 3 or fewer days left
                    reminder_text = (
                        f"⚠️ یادآوری مهم\n\n"
                        f"کاربر گرامی، DNS اختصاصی شما در لوکیشن {dns.get('location', 'نامشخص')} "
                        f"تا {days_left} روز دیگر منقضی خواهد شد.\n\n"
                        f"لطفاً نسبت به تمدید آن اقدام نمایید."
                    )
                    
                    try:
                        bot.send_message(int(user_id), reminder_text)
                        reminder_count += 1
                    except:
                        pass  # Skip if user has blocked the bot
        
        # Check VPN configs for expiration
        for vpn in user_info.get('wireguard_configs', []):
            if 'expiry_date' in vpn:
                expiry = datetime.strptime(vpn['expiry_date'], '%Y-%m-%d %H:%M:%S')
                days_left = (expiry - now).days
                
                if 0 <= days_left <= 3:  # Send reminder if 3 or fewer days left
                    reminder_text = (
                        f"⚠️ یادآوری مهم\n\n"
                        f"کاربر گرامی، VPN اختصاصی شما در لوکیشن {vpn.get('location_name', 'نامشخص')} "
                        f"تا {days_left} روز دیگر منقضی خواهد شد.\n\n"
                        f"لطفاً نسبت به تمدید آن اقدام نمایید."
                    )
                    
                    try:
                        bot.send_message(int(user_id), reminder_text)
                        reminder_count += 1
                    except:
                        pass  # Skip if user has blocked the bot
    
    return reminder_count
# DNS Range Management Functions

def show_dns_ranges_admin(call):
    """Show DNS ranges statistics for admin"""
    from main import load_dns_ranges, bot
    
    dns_ranges = load_dns_ranges()
    
    keyboard = types.InlineKeyboardMarkup()
    for location in dns_ranges.keys():
        keyboard.add(types.InlineKeyboardButton(
            f"🌐 {location.capitalize()}", 
            callback_data=f"dns_range_detail_{location}"
        ))
    
    keyboard.add(types.InlineKeyboardButton("🔙 برگشت", callback_data="admin_back"))
    
    bot.edit_message_text(
        "📊 مدیریت رنج‌های DNS\n\n"
        "لوکیشن مورد نظر را انتخاب کنید:",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=keyboard
    )

def show_dns_range_detail(call, location):
    """Show DNS range details for a specific location"""
    from main import load_dns_ranges, bot, get_dns_ranges_summary
    
    dns_ranges = load_dns_ranges()
    summary = get_dns_ranges_summary()
    
    if location not in dns_ranges:
        bot.answer_callback_query(call.id, "❌ لوکیشن مورد نظر پیدا نشد!")
        return
    
    # Get the data for this location
    location_data = dns_ranges[location]
    summary_data = summary[location]
    
    # Prepare message
    message = f"📍 آمار رنج‌های <b>{location.upper()}</b>:\n\n"
    message += f"🔹 تعداد رنج IPv4: {summary_data['ipv4_ranges']}\n"
    message += f"🔹 تعداد تقریبی IP های IPv4: {summary_data['estimated_ipv4_ips']:,}\n"
    message += f"🔹 تعداد پرفیکس IPv6: {summary_data['ipv6_ranges']}\n\n"
    
    # Show sample ranges
    message += "📌 نمونه رنج‌های IPv4:\n"
    for i, cidr in enumerate(location_data['ipv4'][:5]):
        message += f"   {i+1}. {cidr}\n"
    
    if len(location_data['ipv4']) > 5:
        message += f"   ... و {len(location_data['ipv4']) - 5} رنج دیگر\n\n"
    
    message += "📌 نمونه رنج‌های IPv6:\n"
    for i, cidr in enumerate(location_data['ipv6'][:5]):
        message += f"   {i+1}. {cidr}\n"
    
    if len(location_data['ipv6']) > 5:
        message += f"   ... و {len(location_data['ipv6']) - 5} رنج دیگر"
    
    # Create keyboard
    keyboard = types.InlineKeyboardMarkup()
    keyboard.add(types.InlineKeyboardButton("🔙 برگشت به لیست لوکیشن‌ها", callback_data="admin_dns_ranges"))
    
    bot.edit_message_text(
        message,
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML",
        reply_markup=keyboard
    )
