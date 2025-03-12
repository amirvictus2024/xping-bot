import os
import logging
import random
import string
import uuid
import base64
from telebot import types
from datetime import datetime

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Directory for file storage
FILES_DIR = 'uploaded_files'
os.makedirs(FILES_DIR, exist_ok=True)

# Generate a unique file ID
def generate_file_id():
    return str(uuid.uuid4())[:8]

# Function to edit an uploaded file
def edit_uploaded_file(file_id, new_file_info, new_file_data=None, data_manager=None):
    """
    Edit uploaded file information or content

    Args:
        file_id: The ID of the file to edit
        new_file_info: Dictionary with new information (title, caption, etc.)
        new_file_data: Binary data for the new file (optional)
        data_manager: Function to handle data loading/saving

    Returns:
        bool: True if successful, False otherwise
    """
    if data_manager is None:
        # Default data manager function
        from main import load_data, save_data
    else:
        load_data, save_data = data_manager

    data = load_data()

    if file_id in data.get('uploaded_files', {}):
        # Update file information (title, caption, etc.)
        current_file_info = data['uploaded_files'][file_id]

        # Update only provided fields
        for key, value in new_file_info.items():
            current_file_info[key] = value

        # Update file data if provided
        if new_file_data:
            file_path = os.path.join(FILES_DIR, file_id)
            with open(file_path, 'wb') as f:
                f.write(new_file_data)

        # Save updated data
        data['uploaded_files'][file_id] = current_file_info
        save_data(data)
        return True

    return False

# Function to handle file upload
def handle_file_upload(bot, message, file_type, admin_state, data_manager=None):
    """
    Handle file upload from admin

    Args:
        bot: Telebot instance
        message: Message object containing the file
        file_type: Type of file (photo, video, document)
        admin_state: Admin state dictionary
        data_manager: Function to handle data loading/saving

    Returns:
        tuple: (success, file_id)
    """
    if data_manager is None:
        # Default data manager function
        from main import load_data, save_data
    else:
        load_data, save_data = data_manager

    data = load_data()
    success = False
    file_id = None

    try:
        logger.info(f"Received file upload: content_type={message.content_type}, file_type={file_type}")

        if file_type == 'photo' and message.content_type == 'photo':
            file_id = generate_file_id()
            file_path = os.path.join(FILES_DIR, file_id)
            telegram_file_id = message.photo[-1].file_id
            file_info = bot.get_file(telegram_file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with open(file_path, 'wb') as f:
                f.write(downloaded_file)
            data['uploaded_files'][file_id] = {
                'type': 'photo', 
                'title': message.caption or file_id, 
                'caption': message.caption,
                'telegram_file_id': telegram_file_id,
                'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            success = True

        elif file_type == 'video' and message.content_type == 'video':
            file_id = generate_file_id()
            file_path = os.path.join(FILES_DIR, file_id)
            telegram_file_id = message.video.file_id
            file_info = bot.get_file(telegram_file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with open(file_path, 'wb') as f:
                f.write(downloaded_file)
            data['uploaded_files'][file_id] = {
                'type': 'video', 
                'title': message.caption or file_id, 
                'caption': message.caption,
                'telegram_file_id': telegram_file_id,
                'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            success = True

        elif file_type == 'document' and message.content_type == 'document':
            file_id = generate_file_id()
            file_path = os.path.join(FILES_DIR, file_id)
            telegram_file_id = message.document.file_id
            file_info = bot.get_file(telegram_file_id)
            downloaded_file = bot.download_file(file_info.file_path)
            with open(file_path, 'wb') as f:
                f.write(downloaded_file)

            file_name = message.document.file_name
            data['uploaded_files'][file_id] = {
                'type': 'document', 
                'title': message.caption or file_name or file_id, 
                'caption': message.caption,
                'original_filename': file_name,
                'telegram_file_id': telegram_file_id,
                'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            success = True
    except Exception as e:
        logger.error(f"Error uploading file: {e}")
        return False, None

    save_data(data)
    return success, file_id

# Send file to user
def send_file_to_user(bot, message, file_id, data_manager=None):
    """
    Send a file to a user

    Args:
        bot: Telebot instance
        message: Message object
        file_id: ID of the file to send
        data_manager: Function to handle data loading

    Returns:
        bool: True if successful, False otherwise
    """
    if data_manager is None:
        # Default data manager function
        from main import load_data
    else:
        load_data = data_manager

    data = load_data()
    if file_id in data.get('uploaded_files', {}):
        file_info = data['uploaded_files'][file_id]
        try:
            # If it's an external URL file
            if file_info.get('type') == 'external_url':
                external_url = file_info.get('external_url')
                if external_url:
                    # Send message with the URL
                    bot.send_message(
                        message.chat.id,
                        f"📎 <b>{file_info.get('title', 'فایل خارجی')}</b>\n\n"
                        f"🔗 <a href='{external_url}'>لینک دانلود مستقیم</a>\n\n"
                        f"{file_info.get('caption', '')}",
                        parse_mode="HTML",
                        disable_web_page_preview=False
                    )
                    return True
            # If Telegram file_id is available, use it (faster method)
            elif 'telegram_file_id' in file_info:
                if file_info['type'] == 'photo':
                    bot.send_photo(message.chat.id, file_info['telegram_file_id'], caption=file_info.get('caption', ''))
                elif file_info['type'] == 'video':
                    bot.send_video(message.chat.id, file_info['telegram_file_id'], caption=file_info.get('caption', ''))
                elif file_info['type'] == 'document':
                    bot.send_document(message.chat.id, file_info['telegram_file_id'], caption=file_info.get('caption', ''))
            # Otherwise use the saved file
            else:
                file_path = os.path.join(FILES_DIR, file_id)
                with open(file_path, 'rb') as f:
                    if file_info['type'] == 'photo':
                        bot.send_photo(message.chat.id, f, caption=file_info.get('caption', ''))
                    elif file_info['type'] == 'video':
                        bot.send_video(message.chat.id, f, caption=file_info.get('caption', ''))
                    elif file_info['type'] == 'document':
                        bot.send_document(message.chat.id, f, caption=file_info.get('caption', ''))
            return True
        except Exception as e:
            logger.error(f"Error sending file {file_id}: {e}")
            bot.send_message(message.chat.id, "متاسفانه در ارسال فایل مورد نظر خطایی رخ داد.")
            return False
    else:
        bot.send_message(message.chat.id, "متاسفانه فایل مورد نظر یافت نشد.")
        return False
        
def send_file_to_user(bot, message, file_id, load_data_func):
    """Send a file to user using its ID"""
    data = load_data_func()
    if file_id in data.get('uploaded_files', {}):
        file_info = data['uploaded_files'][file_id]
        try:
            # Handle external URL links
            if file_info.get('type') == 'external_url' and 'external_url' in file_info:
                bot.send_message(
                    message.chat.id,
                    f"🌐 لینک خارجی: {file_info.get('title')}\n\n"
                    f"🔗 <a href='{file_info['external_url']}'>{file_info.get('title')}</a>\n\n"
                    f"{file_info.get('caption', '')}",
                    parse_mode="HTML",
                    disable_web_page_preview=False
                )
            # Handle telegram file_id links (for faster sending)
            elif 'telegram_file_id' in file_info:
                if file_info['type'] == 'photo':
                    bot.send_photo(message.chat.id, file_info['telegram_file_id'], caption=file_info.get('caption', ''))
                elif file_info['type'] == 'video':
                    bot.send_video(message.chat.id, file_info['telegram_file_id'], caption=file_info.get('caption', ''))
                elif file_info['type'] == 'document':
                    bot.send_document(message.chat.id, file_info['telegram_file_id'], caption=file_info.get('caption', ''))
            # Otherwise read from file
            else:
                file_path = os.path.join(FILES_DIR, file_id)
                with open(file_path, 'rb') as f:
                    if file_info['type'] == 'photo':
                        bot.send_photo(message.chat.id, f, caption=file_info.get('caption', ''))
                    elif file_info['type'] == 'video':
                        bot.send_video(message.chat.id, f, caption=file_info.get('caption', ''))
                    elif file_info['type'] == 'document':
                        bot.send_document(message.chat.id, f, caption=file_info.get('caption', ''))
            return True
        except Exception as e:
            logger.error(f"Error sending file {file_id}: {e}")
            bot.send_message(message.chat.id, "متاسفانه در ارسال فایل مورد نظر خطایی رخ داد.")
            return False
    else:
        bot.send_message(message.chat.id, "متاسفانه فایل مورد نظر یافت نشد.")
        return False

# Create external URL share link
def create_external_url_link(title, url, caption="", data_manager=None):
    """
    Create a shareable link for an external URL

    Args:
        title: Title for the external URL
        url: The external URL
        caption: Optional caption for the URL
        data_manager: Function to handle data loading/saving

    Returns:
        str: The generated file_id for sharing
    """
    if data_manager is None:
        # Default data manager function
        from main import load_data, save_data
    else:
        load_data, save_data = data_manager

    data = load_data()

    # Generate a unique file ID
    file_id = generate_file_id()

    # Add to uploaded_files data
    data['uploaded_files'][file_id] = {
        'type': 'external_url',
        'title': title,
        'external_url': url,
        'caption': caption,
        'uploaded_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }

    save_data(data)
    return file_id

# Replace an existing file with new content
def replace_existing_file(file_id, new_file_data, new_file_info=None, data_manager=None):
    """
    Replace an existing file with new content while keeping the same file_id

    Args:
        file_id: ID of the file to replace
        new_file_data: Binary data of the new file
        new_file_info: New file information (optional, will only update provided fields)
        data_manager: Function to handle data loading/saving

    Returns:
        bool: True if successful, False otherwise
    """
    if data_manager is None:
        # Default data manager function
        from main import load_data, save_data
    else:
        load_data, save_data = data_manager

    data = load_data()

    if file_id not in data.get('uploaded_files', {}):
        return False

    try:
        # Replace file content
        file_path = os.path.join(FILES_DIR, file_id)
        with open(file_path, 'wb') as f:
            f.write(new_file_data)

        # Update file info if provided
        if new_file_info:
            current_info = data['uploaded_files'][file_id]
            for key, value in new_file_info.items():
                if key != 'type':  # Don't change the file type
                    current_info[key] = value

            # Update the replaced timestamp
            current_info['replaced_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            data['uploaded_files'][file_id] = current_info
            save_data(data)

        return True
    except Exception as e:
        logger.error(f"Error replacing file {file_id}: {e}")
        return False

# Get file uploader keyboard
def get_file_uploader_keyboard():
    markup = types.InlineKeyboardMarkup(row_width=2)

    btn1 = types.InlineKeyboardButton("🖼️ آپلود تصویر", callback_data="upload_photo")
    btn2 = types.InlineKeyboardButton("🎥 آپلود ویدیو", callback_data="upload_video")
    btn3 = types.InlineKeyboardButton("📄 آپلود فایل", callback_data="upload_document")
    btn4 = types.InlineKeyboardButton("📋 لیست فایل‌ها", callback_data="list_files")
    btn5 = types.InlineKeyboardButton("🔗 ایجاد لینک اشتراک‌گذاری", callback_data="create_share_link")
    btn7 = types.InlineKeyboardButton("🌐 لینک خارجی", callback_data="create_external_url")
    btn8 = types.InlineKeyboardButton("🔄 جایگزینی فایل", callback_data="replace_file")
    btn6 = types.InlineKeyboardButton("🔙 بازگشت به پنل مدیریت", callback_data="admin_back")

    markup.add(btn1, btn2, btn3)
    markup.add(btn4, btn5)
    markup.add(btn7, btn8)
    markup.add(btn6)

    return markup