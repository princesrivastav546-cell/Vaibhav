import requests
import json
import logging
import time
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# ==================== CONFIGURATION ====================

API_BASE = "https://anishexploits.site/api/api.php?key=exploits&num="
BOT_TOKEN = "8372266918:AAGMkYzH0QvmxGJVrrTXvF8nzT7KXjj1O40"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 13; Termux) Gecko/117.0 Firefox/117.0",
    "Accept": "application/json,text/html,application/xhtml+xml,application/xml;q=0.9,/;q=0.8",
    "Referer": "https://oliver-exploits.vercel.app/",
    "Connection": "keep-alive"
}

# ==================== BOT SETUP ====================

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# ==================== WELCOME MESSAGE ====================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = "👋 *WELCOME TO OLIVER EXPLOITS*\n\n" \
                   "\n" \
                   ""
    
    keyboard = [[KeyboardButton("📞 ENTER NUMBER")]]  
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)  
    
    await update.message.reply_text(welcome_text, reply_markup=reply_markup, parse_mode='Markdown')

# ==================== HANDLE BUTTON CLICK ====================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == "📞 ENTER NUMBER":
        await update.message.reply_text("📤 *Send Your 10-digit Number Without +91:*", parse_mode='Markdown')  
    else:  
        await process_number(update, context)

# ==================== PROCESS NUMBER ====================

async def process_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    number = update.message.text.strip()
    
    if not number.isdigit() or len(number) != 10:  
        await update.message.reply_text("❌ *INVALID INPUT*\nPlease send 10-digit number only.", parse_mode='Markdown')  
        return  
    
    processing_msg = await update.message.reply_text("🔍 *Scanning Database...*", parse_mode='Markdown')  
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")  
    time.sleep(2)  
    
    result = await search_number_api(number)  
    
    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=processing_msg.message_id)  
    
    await update.message.reply_text(result, parse_mode='Markdown')

# ==================== API CALL FUNCTION ====================

async def search_number_api(number):
    url = f"{API_BASE}{number}"
    
    try:  
        response = requests.get(url, headers=HEADERS, timeout=30)
        
        if response.status_code != 200:  
            return "🛡️ OLIVER EXPLOITS CYBERSECURITY INFORMATION 🛡️\n\n" \
                   "🎯 TARGET: {}\n\n" \
                   "❌ DATABASE ERROR\n\n" \
                   "Server connection failed.\n\n" \
                   "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" \
                   "🔐 END OF REPORT".format(number)
        
        try:
            data = response.json()
        except:
            return "🛡️ OLIVER EXPLOITS CYBERSECURITY INFORMATION 🛡️\n\n" \
                   "🎯 TARGET: {}\n\n" \
                   "❌ DATA ERROR\n\n" \
                   "Invalid response format.\n\n" \
                   "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" \
                   "🔐 END OF REPORT".format(number)
        
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        user_data, record_count = extract_user_data(data)
        
        if user_data:
            return format_cybersecurity_report(user_data, number, record_count, current_time)
        else:
            return "🛡️ OLIVER EXPLOITS CYBERSECURITY INFORMATION 🛡️\n\n" \
                   "🎯 TARGET: {}\n\n" \
                   "⚠️ NO INFORMATION FOUND\n\n" \
                   "Number not found in database.\n\n" \
                   "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" \
                   "🔐 END OF REPORT".format(number)
        
    except requests.exceptions.Timeout:
        return "🛡️ OLIVER EXPLOITS CYBERSECURITY INFORMATION 🛡️\n\n" \
               "🎯 TARGET: {}\n\n" \
               "⏱️ TIMEOUT ERROR\n\n" \
               "Request timed out.\n\n" \
               "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" \
               "🔐 END OF REPORT".format(number)
    except requests.exceptions.ConnectionError:
        return "🛡️ OLIVER EXPLOITS CYBERSECURITY INFORMATION 🛡️\n\n" \
               "🎯 TARGET: {}\n\n" \
               "🌐 CONNECTION ERROR\n\n" \
               "Network connection failed.\n\n" \
               "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" \
               "🔐 END OF REPORT".format(number)
    except Exception as e:  
        return "🛡️ OLIVER EXPLOITS CYBERSECURITY INFORMATION 🛡️\n\n" \
               "🎯 TARGET: {}\n\n" \
               "❌ SYSTEM ERROR\n\n" \
               "Unknown error occurred.\n\n" \
               "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n" \
               "🔐 END OF REPORT".format(number)

# ==================== DATA EXTRACTION ====================

def extract_user_data(data):
    """Extract user data from different API formats"""
    user_data = None
    record_count = 1
    
    if isinstance(data, dict) and data.get('success') and data.get('result'):
        results = data.get('result', [])
        if results:
            user_data = results[0]
            record_count = len(results)
    elif isinstance(data, dict) and (data.get('mobile') or data.get('name')):
        user_data = data
    elif isinstance(data, list) and len(data) > 0:
        user_data = data[0]
        record_count = len(data)
    elif isinstance(data, dict) and data.get('status') == 'success':
        user_data = data.get('data', {})
    
    return user_data, record_count

# ==================== REPORT FORMATTING ====================

def format_cybersecurity_report(user_data, number, record_count, current_time):
    """Format the cybersecurity report"""
    
    # Extract all data
    phone = user_data.get('mobile', number)
    alt = user_data.get('alt_mobile')
    aadhar = user_data.get('id_number', user_data.get('aadhar'))
    name = user_data.get('name', 'None')
    father = user_data.get('father_name', 'None')
    address = user_data.get('address', '')
    circle = user_data.get('circle', '')
    
    # Clean address
    if address:
        address = address.replace('!', ' ').replace('|', ' ').replace('NA', '').replace('l\'', '').replace('Ii', '')
        address = ' '.join(address.split())
    
    # Extract actual circle/state from API data
    actual_circle = 'Unknown'
    if circle:
        parts = circle.split()
        if len(parts) >= 2:
            actual_circle = parts[0]
        else:
            actual_circle = circle
    
    # Determine network
    network = 'Unknown'
    if 'JIO' in circle.upper():
        network = 'JIO'
    elif 'VODAFONE' in circle.upper():
        network = 'VODAFONE'
    elif 'AIRTEL' in circle.upper():
        network = 'AIRTEL'
    elif 'BSNL' in circle.upper():
        network = 'BSNL'
    elif circle:
        operators = ['JIO', 'VODAFONE', 'AIRTEL', 'BSNL', 'IDEA', 'AIRCEL']
        for operator in operators:
            if operator in circle.upper():
                network = operator
                break
    
    # Calculate risk level
    data_points = sum([
        1 if name and name != 'None' and name.strip() else 0,
        1 if father and father != 'None' and father.strip() else 0,
        1 if aadhar and aadhar.strip() else 0,
        1 if address and address.strip() else 0,
        1 if alt and alt.strip() else 0
    ])
    
    if data_points >= 4:
        risk_emoji = "🔴"
        exposure = "🔓 SEVERE"
    elif data_points >= 2:
        risk_emoji = "🟠"
        exposure = "🔓 HIGH"
    else:
        risk_emoji = "🟡"
        exposure = "🔐 MODERATE"
    
    # Build the report
    report = "🛡️ OLIVER EXPLOITS CYBERSECURITY INFORMATION 🛡️\n\n"
    
    report += "🎯 OLIVER EXPLOITS\n"
    report += f"├─ 📞 Primary Vector: {phone}\n"
    report += f"├─ 📱 Secondary Vector: {alt if alt else 'None'}\n"
    report += f"└─ 🆔 Identity Marker: {aadhar if aadhar else 'None'}\n\n"
    
    report += "👤 TARGET PROFILE\n"
    report += f"├─ 🎭 Owner: {name if name != 'None' else 'Not Available'}\n"
    report += f"├─ 👨‍👦 Father : {father if father != 'None' else 'Not Available'}\n"
    report += f"└─ 📍 Circle : {actual_circle if actual_circle != 'Unknown' else 'Not Available'}\n\n"
    
    report += "📍 DIGITAL GEO-LOCK\n"
    if address:
        if len(address) > 80:
            address = address[:77] + "..."
        report += f"├─ 🏠 Address : {address}\n"
    else:
        report += f"├─ 🏠 Address : Not Available\n"
    
    # Check for landmark in address
    landmark = 'Not Specified'
    if address:
        address_lower = address.lower()
        if 'chowk' in address_lower:
            landmark = 'Katar Chowk'
        elif 'market' in address_lower:
            landmark = 'Market Area'
        elif 'station' in address_lower:
            landmark = 'Railway Station'
    
    report += f"├─ 🚩 Landmark: {landmark}\n"
    report += f"├─ 🏛️ District : Samastipur\n"
    
    if aadhar:
        report += f"├─ 🪪 Aadhar: {aadhar}\n"
    
    report += f"├─ 📡 Network: {network}\n"
    report += f"└─ 🌍 Country : India\n\n"
    
    report += "📊 DIGITAL FOOTPRINT\n"
    report += f"├─ 🗃️ Database Traces: {record_count}\n"
    report += f"├─ ✅ Verification: CONFIRMED\n"
    report += f"└─ ⏰ Last Detection: {current_time}\n\n"
    
    report += "⚠️ THREAT ASSESSMENT\n"
    report += f"├─ 🚨 Risk Level: {risk_emoji} {'CRITICAL' if risk_emoji == '🔴' else 'HIGH' if risk_emoji == '🟠' else 'MEDIUM'}\n"
    report += f"├─ 🔓 Exposure: {exposure}\n"
    report += f"└─ 🛡️ Protection: COMPROMISED\n\n"
    
    report += "🔍 INTELLIGENCE SOURCE\n"
    report += f"├─ 🛡️ Oliver Exploits\n"
    report += f"├─ 👨‍💻 Developer: @platoonleaderr\n"
    report += f"└─ ⚡ Status: ACTIVE MONITORING\n\n"
    
    report += "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    report += "🔐 END OF REPORT"
    
    return report

# ==================== MAIN FUNCTION ====================

def main():
    print("\n" * 2)
    print("=" * 50)
    print("🛡️ OLIVER EXPLOITS NUMBER SCANNER")
    print("📱 Status: OPERATIONAL")
    print("=" * 50)
    print("\n✅ Bot initialized successfully!")
    print("🔍 Waiting for scan requests...\n")
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    application.run_polling()

if __name__ == "__main__":
    main()