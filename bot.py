import os
import logging
import asyncio
import subprocess
import signal
import sys
import psutil
import json
import threading
import shutil
from flask import Flask, request
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, ContextTypes, CommandHandler, 
    MessageHandler, filters, ConversationHandler, CallbackQueryHandler
)

# --- CONFIGURATION ---
TOKEN = os.environ.get("TOKEN") 
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0")) 
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:8080")

UPLOAD_DIR = "scripts"
if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

USERS_FILE = "allowed_users.json"
OWNERSHIP_FILE = "ownership.json"

# Global State
running_processes = {} 

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home(): return "🤖 Python Host Bot is Alive!", 200

@app.route('/status')
def script_status():
    script_name = request.args.get('script')
    if not script_name: return "Specify script", 400
    if script_name in running_processes and running_processes[script_name]['process'].poll() is None:
        return f"✅ {script_name} is running.", 200
    return f"❌ {script_name} is stopped.", 404

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- DATA MANAGEMENT ---

def get_allowed_users():
    if not os.path.exists(USERS_FILE): return []
    try:
        with open(USERS_FILE, 'r') as f: return json.load(f)
    except: return []

def save_allowed_user(uid):
    users = get_allowed_users()
    if uid not in users:
        users.append(uid)
        with open(USERS_FILE, 'w') as f: json.dump(users, f)
        return True
    return False

def remove_allowed_user(uid):
    users = get_allowed_users()
    if uid in users:
        users.remove(uid)
        with open(USERS_FILE, 'w') as f: json.dump(users, f)
        return True
    return False

def load_ownership():
    if not os.path.exists(OWNERSHIP_FILE): return {}
    try:
        with open(OWNERSHIP_FILE, 'r') as f: return json.load(f)
    except: return {}

def save_ownership(target_id, user_id, type_):
    data = load_ownership()
    data[target_id] = {"owner": user_id, "type": type_}
    with open(OWNERSHIP_FILE, 'w') as f: json.dump(data, f)

def delete_ownership(target_id):
    data = load_ownership()
    if target_id in data:
        del data[target_id]
        with open(OWNERSHIP_FILE, 'w') as f: json.dump(data, f)

def get_owner(target_id):
    data = load_ownership()
    return data.get(target_id, {}).get("owner")

# --- DECORATORS ---
def restricted(func):
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        uid = update.effective_user.id
        if uid != ADMIN_ID and uid not in get_allowed_users():
            await update.message.reply_text("⛔ Access Denied.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

def super_admin_only(func):
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_user.id != ADMIN_ID:
            await update.message.reply_text("⛔ Super Admin Only.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapped

# --- KEYBOARDS (UPDATED: REMOVED .ENV BUTTON) ---
def main_menu_keyboard():
    return ReplyKeyboardMarkup([
        ["📤 Upload File", "🌐 Clone from Git"],
        ["📂 My Hosted Apps", "📊 Server Stats"],
        ["🆘 Help"]
    ], resize_keyboard=True)

def extras_keyboard():
    return ReplyKeyboardMarkup([
        ["➕ Add reqs", "📝 Type Env Vars"], 
        ["🚀 RUN NOW", "🔙 Cancel"]
    ], resize_keyboard=True)

def git_extras_keyboard():
    return ReplyKeyboardMarkup([
        ["📝 Type Env Vars"],
        ["📂 Select File to Run", "🔙 Cancel"]
    ], resize_keyboard=True)

# --- HELPER: REQ FIXER ---
def smart_fix_requirements(req_path):
    try:
        with open(req_path, 'r') as f: lines = f.readlines()
        clean = []
        for line in lines:
            line = line.strip()
            if not line: continue
            if line.lower().startswith("pip install"):
                clean.extend(line[11:].strip().split())
            else:
                clean.append(line)
        with open(req_path, 'w') as f: f.write('\n'.join(clean))
        return True
    except: return False

async def install_requirements(req_path, update):
    msg = await update.message.reply_text("⏳ **Installing requirements...**")
    smart_fix_requirements(req_path)
    try:
        proc = await asyncio.create_subprocess_exec("pip", "install", "-r", req_path, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, stderr = await proc.communicate()
        if proc.returncode == 0: await msg.edit_text("✅ **Installed!**")
        else: await msg.edit_text(f"❌ Failed:\n```\n{stderr.decode()[-1000:]}\n```", parse_mode="Markdown")
    except Exception as e: await msg.edit_text(f"❌ Error: {e}")

# --- HANDLERS ---
@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 **Python & Git Hosting Bot**", reply_markup=main_menu_keyboard())

# --- CANCEL HANDLER ---
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🚫 Operation Cancelled.", reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# --- CONVERSATION 1: UPLOAD FILE ---
WAIT_PY, WAIT_EXTRAS, WAIT_ENV_TEXT = range(3)

@restricted
async def upload_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📤 Send `.py` file.", reply_markup=ReplyKeyboardMarkup([['🔙 Cancel']], resize_keyboard=True))
    return WAIT_PY

async def receive_py(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "🔙 Cancel": return await cancel(update, context)

    file = await update.message.document.get_file()
    fname = update.message.document.file_name
    uid = update.effective_user.id
    
    if not fname.endswith(".py"): return await update.message.reply_text("❌ Needs .py")
    
    owner = get_owner(fname)
    if os.path.exists(os.path.join(UPLOAD_DIR, fname)) and owner and owner != uid and uid != ADMIN_ID:
        await update.message.reply_text(f"❌ **Taken!** `{fname}` is owned by another user.")
        return WAIT_PY

    path = os.path.join(UPLOAD_DIR, fname)
    await file.download_to_drive(path)
    save_ownership(fname, uid, "file")
    
    context.user_data['type'] = 'file'
    context.user_data['target_id'] = fname 
    context.user_data['work_dir'] = UPLOAD_DIR
    
    await update.message.reply_text(f"✅ Saved. Options:", reply_markup=extras_keyboard())
    return WAIT_EXTRAS

async def receive_extras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if txt == "🚀 RUN NOW": return await execute_logic(update, context)
    elif txt == "🔙 Cancel": return await cancel(update, context)
    
    elif txt == "📝 Type Env Vars":
        await update.message.reply_text(
            "📝 **Type Env Variables**\n\nExample:\n`TOKEN = \"12345\"`\n`DEBUG=True`",
            parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup([['🔙 Cancel']], resize_keyboard=True)
        )
        return WAIT_ENV_TEXT

    elif "reqs" in txt:
        await update.message.reply_text("📂 Send `requirements.txt`.")
        context.user_data['wait'] = 'req'
    
    return WAIT_EXTRAS

async def receive_env_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔙 Cancel": return await cancel(update, context)
    
    work_dir = context.user_data['work_dir']
    target_id = context.user_data['target_id']
    
    if context.user_data['type'] == 'repo':
        env_path = os.path.join(work_dir, ".env")
        next_markup = git_extras_keyboard() 
        next_state = WAIT_GIT_EXTRAS
    else:
        prefix = target_id 
        env_path = os.path.join(work_dir, f"{prefix}.env")
        next_markup = extras_keyboard() 
        next_state = WAIT_EXTRAS

    try:
        with open(env_path, "a") as f:
            if os.path.getsize(env_path) > 0: f.write("\n")
            f.write(text)
        await update.message.reply_text("✅ **Variables Saved!**", reply_markup=next_markup)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}", reply_markup=next_markup)
        
    return next_state

async def receive_extra_files(update: Update, context: ContextTypes.DEFAULT_TYPE):
    wait = context.user_data.get('wait')
    if not wait: return WAIT_EXTRAS
    file = await update.message.document.get_file()
    fname = update.message.document.file_name
    target_id = context.user_data['target_id']
    work_dir = context.user_data['work_dir']
    
    prefix = target_id if context.user_data['type'] == 'file' else target_id.split("|")[0]
    
    if wait == 'req' and fname.endswith('.txt'):
        path = os.path.join(work_dir, f"{prefix}_req.txt")
        await file.download_to_drive(path)
        await install_requirements(path, update)
    
    context.user_data['wait'] = None
    await update.message.reply_text("Next?", reply_markup=extras_keyboard())
    return WAIT_EXTRAS

# --- CONVERSATION 2: GIT CLONE ---
WAIT_URL, WAIT_GIT_EXTRAS, WAIT_GIT_ENV_TEXT, WAIT_SELECT_FILE = range(3, 7)

@restricted
async def git_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🌐 **Send Public Git Repository URL**", reply_markup=ReplyKeyboardMarkup([['🔙 Cancel']], resize_keyboard=True))
    return WAIT_URL

async def receive_git_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if url == "🔙 Cancel": return await cancel(update, context)

    if not url.startswith("http"): return await update.message.reply_text("❌ Invalid URL.")
    
    repo_name = url.split("/")[-1].replace(".git", "")
    repo_path = os.path.join(UPLOAD_DIR, repo_name)
    
    msg = await update.message.reply_text(f"⏳ Cloning `{repo_name}`...")
    if os.path.exists(repo_path): shutil.rmtree(repo_path)
    
    try:
        subprocess.check_call(["git", "clone", url, repo_path])
        await msg.edit_text("✅ **Cloned Successfully!**")
        
        # Auto install reqs
        req_path = os.path.join(repo_path, "requirements.txt")
        if os.path.exists(req_path):
            await update.message.reply_text("📦 Installing `requirements.txt`...")
            await install_requirements(req_path, update)

        context.user_data['repo_path'] = repo_path
        context.user_data['repo_name'] = repo_name
        
        # Save placeholder target_id for Env saver to work
        context.user_data['target_id'] = f"{repo_name}|PLACEHOLDER"
        context.user_data['type'] = 'repo'
        context.user_data['work_dir'] = repo_path
        
        await update.message.reply_text(
            "⚙️ **Setup Environment**\n"
            "Add Env Variables (Optional) or Select File to Run.",
            reply_markup=git_extras_keyboard()
        )
        return WAIT_GIT_EXTRAS

    except Exception as e:
        await msg.edit_text(f"❌ Clone Failed: {e}")
        return ConversationHandler.END

async def receive_git_extras(update: Update, context: ContextTypes.DEFAULT_TYPE):
    txt = update.message.text
    if txt == "🔙 Cancel": return await cancel(update, context)
    
    elif txt == "📝 Type Env Vars":
        await update.message.reply_text(
            "📝 **Type Env Variables**\n\nExample:\n`TELEGRAM_BOT_TOKEN = \"12345\"`",
            parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup([['🔙 Cancel']], resize_keyboard=True)
        )
        return WAIT_GIT_ENV_TEXT

    elif txt == "📂 Select File to Run":
        return await show_file_selection(update, context)

    return WAIT_GIT_EXTRAS

async def show_file_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    repo_path = context.user_data['repo_path']
    py_files = []
    for root, dirs, files in os.walk(repo_path):
        for file in files:
            if file.endswith(".py"):
                rel_path = os.path.relpath(os.path.join(root, file), repo_path)
                py_files.append(rel_path)
    
    if not py_files:
        await update.message.reply_text("❌ No .py files found.", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    keyboard = []
    for f in py_files[:10]:
        keyboard.append([InlineKeyboardButton(f, callback_data=f"sel_py_{f}")])
    
    await update.message.reply_text("👇 **Select Main File:**", reply_markup=InlineKeyboardMarkup(keyboard))
    return WAIT_SELECT_FILE

async def select_git_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    filename = query.data.split("sel_py_")[1]
    repo_path = context.user_data['repo_path']
    repo_name = context.user_data['repo_name']
    uid = update.effective_user.id
    
    unique_id = f"{repo_name}|{filename}"
    save_ownership(unique_id, uid, "repo")
    
    context.user_data['type'] = 'repo'
    context.user_data['target_id'] = unique_id
    context.user_data['path'] = filename 
    context.user_data['work_dir'] = repo_path
    
    await query.edit_message_text(f"✅ Selected `{filename}`")
    return await execute_logic(update.callback_query, context)

# --- EXECUTION ---
async def execute_logic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg_func = update.message.reply_text if update.message else update.callback_query.message.reply_text
    
    target_id = context.user_data.get('target_id', context.user_data.get('fallback_id'))
    
    if "|" in target_id:
        repo, file = target_id.split("|")
        work_dir = os.path.join(UPLOAD_DIR, repo)
        script_path = file
        env_path = os.path.join(work_dir, ".env")
    else:
        work_dir = UPLOAD_DIR
        script_path = target_id
        env_path = os.path.join(work_dir, f"{target_id}.env")

    if target_id in running_processes and running_processes[target_id]['process'].poll() is None:
        await msg_func(f"⚠️ `{target_id}` is already running!", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    custom_env = os.environ.copy()
    if os.path.exists(env_path):
        with open(env_path) as f:
            for l in f:
                # Basic parsing for KEY="VALUE" or KEY=VALUE
                if '=' in l and not l.strip().startswith('#'):
                    k,v = l.strip().split('=', 1)
                    v = v.strip().strip('"').strip("'")
                    custom_env[k.strip()] = v

    log_file_path = os.path.join(UPLOAD_DIR, f"{target_id.replace('|','_')}.log")
    log_file = open(log_file_path, "w")
    
    try:
        proc = subprocess.Popen(
            ["python", "-u", script_path], 
            env=custom_env, stdout=log_file, stderr=subprocess.STDOUT, 
            cwd=work_dir, preexec_fn=os.setsid
        )
        running_processes[target_id] = {"process": proc, "log": log_file_path}
        
        await msg_func(f"🚀 **Started!**\nID: `{target_id}`\nPID: {proc.pid}")
        await asyncio.sleep(3)
        if proc.poll() is not None:
            log_file.close()
            with open(log_file_path) as f: log = f.read()[-2000:]
            await msg_func(f"❌ **Crashed:**\n`{log}`", parse_mode="Markdown", reply_markup=main_menu_keyboard())
        else:
            url = f"{BASE_URL}/status?script={target_id}"
            await msg_func(f"🟢 **Running!**\n🔗 URL: `{url}`", parse_mode="Markdown", reply_markup=main_menu_keyboard())

    except Exception as e:
        await msg_func(f"❌ Error: {e}", reply_markup=main_menu_keyboard())
        
    return ConversationHandler.END

# --- LIST & MANAGE ---
@restricted
async def list_hosted(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    ownership = load_ownership()
    keyboard = []
    
    for tid, meta in ownership.items():
        owner = meta.get("owner")
        if uid == ADMIN_ID or uid == owner:
            status = "🟢" if tid in running_processes and running_processes[tid]['process'].poll() is None else "🔴"
            label = f"{status} {tid}"
            if uid == ADMIN_ID and uid != owner: label += f" (User: {owner})"
            keyboard.append([InlineKeyboardButton(label, callback_data=f"man_{tid}")])

    if not keyboard:
        await update.message.reply_text("📂 No hosted files.", reply_markup=main_menu_keyboard())
        return

    await update.message.reply_text("📂 **Your Apps:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    uid = update.effective_user.id

    if data.startswith("man_"):
        target_id = data.split("man_")[1]
        owner = get_owner(target_id)
        if uid != ADMIN_ID and uid != owner: return await query.message.reply_text("⛔ Not yours.")

        is_running = target_id in running_processes and running_processes[target_id]['process'].poll() is None
        text = f"⚙️ **Manage:** `{target_id}`\nStatus: {'🟢 Running' if is_running else '🔴 Stopped'}"
        btns = []
        if is_running:
            btns.append([InlineKeyboardButton("🛑 Stop", callback_data=f"stop_{target_id}")])
            btns.append([InlineKeyboardButton("🔗 URL", callback_data=f"url_{target_id}")])
        else:
            btns.append([InlineKeyboardButton("🚀 Run", callback_data=f"rerun_{target_id}")])
        btns.append([InlineKeyboardButton("📜 Logs", callback_data=f"log_{target_id}")])
        btns.append([InlineKeyboardButton("🗑️ Delete", callback_data=f"del_{target_id}")])
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(btns), parse_mode="Markdown")

    elif data.startswith("stop_"):
        pid = data.split("stop_")[1]
        if pid in running_processes:
            os.killpg(os.getpgid(running_processes[pid]['process'].pid), signal.SIGTERM)
            running_processes[pid]['process'].wait()
            await query.edit_message_text(f"🛑 Stopped `{pid}`")
            
    elif data.startswith("rerun_"):
        context.user_data['fallback_id'] = data.split("rerun_")[1]
        await query.delete_message()
        await execute_logic(update, context)

    elif data.startswith("del_"):
        pid = data.split("del_")[1]
        if pid in running_processes:
            try: os.killpg(os.getpgid(running_processes[pid]['process'].pid), signal.SIGTERM)
            except: pass
            del running_processes[pid]
        delete_ownership(pid)
        
        if "|" in pid: shutil.rmtree(os.path.join(UPLOAD_DIR, pid.split("|")[0]), ignore_errors=True)
        else: 
            try: os.remove(os.path.join(UPLOAD_DIR, pid))
            except: pass
        
        for ext in ['.env', '_req.txt', '.log']:
             extra = os.path.join(UPLOAD_DIR, pid + ext if ext != '_req.txt' else f"{pid}_req.txt")
             if os.path.exists(extra): os.remove(extra)
        await query.edit_message_text(f"🗑️ Deleted `{pid}`")

    elif data.startswith("log_"):
        pid = data.split("log_")[1]
        path = os.path.join(UPLOAD_DIR, f"{pid.replace('|','_')}.log")
        if os.path.exists(path): await context.bot.send_document(chat_id=update.effective_chat.id, document=open(path, 'rb'))
        else: await query.message.reply_text("❌ No logs.")

    elif data.startswith("url_"):
        pid = data.split("url_")[1]
        await query.message.reply_text(f"🔗 `{BASE_URL}/status?script={pid}`", parse_mode="Markdown")

    elif data.startswith("sel_py_"):
        await select_git_file(update, context)

# --- SYSTEM & ADMIN ---
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🆘 **Help & Support**\n\n"
        "Contact the dev: @platoonleaderr\n\n"
        "• **Upload File:** Host a single .py file.\n"
        "• **Git Clone:** Host a repo from a public URL.\n"
        "• **Env Vars:** You can now type them directly!\n"
        "• **Manage:** Stop/Delete/Run your scripts.",
        parse_mode="Markdown"
    )

@super_admin_only
async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/add 123`")
    if save_allowed_user(int(context.args[0])): await update.message.reply_text("✅ Added.")
    else: await update.message.reply_text("⚠️ Exists.")

@super_admin_only
async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args: return await update.message.reply_text("Usage: `/remove 123`")
    if remove_allowed_user(int(context.args[0])): await update.message.reply_text("🗑️ Removed.")
    else: await update.message.reply_text("⚠️ Not found.")

@restricted
async def server_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cpu = psutil.cpu_percent()
    ram = psutil.virtual_memory().percent
    active = sum(1 for p in running_processes.values() if p['process'].poll() is None)
    await update.message.reply_text(f"📊 **Stats**\nCPU: {cpu}%\nRAM: {ram}%\nActive Apps: {active}", parse_mode="Markdown")

if __name__ == '__main__':
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    app_bot = ApplicationBuilder().token(TOKEN).build()
    
    # Upload Handler
    conv_file = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📤 Upload File$"), upload_start)],
        states={
            WAIT_PY: [
                MessageHandler(filters.Regex("^🔙 Cancel$"), cancel),
                MessageHandler(filters.Document.FileExtension("py"), receive_py)
            ],
            WAIT_EXTRAS: [
                MessageHandler(filters.Regex("^🔙 Cancel$"), cancel),
                MessageHandler(filters.Regex("^(🚀|➕|📝)"), receive_extras), 
                MessageHandler(filters.Document.ALL, receive_extra_files)
            ],
            WAIT_ENV_TEXT: [
                MessageHandler(filters.Regex("^🔙 Cancel$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_env_text)
            ]
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex("^🔙 Cancel$"), cancel)]
    )

    # Git Handler
    conv_git = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^🌐 Clone from Git$"), git_start)],
        states={
            WAIT_URL: [
                MessageHandler(filters.Regex("^🔙 Cancel$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_git_url)
            ],
            WAIT_GIT_EXTRAS: [
                MessageHandler(filters.Regex("^🔙 Cancel$"), cancel),
                MessageHandler(filters.Regex("^(📝|📂)"), receive_git_extras) 
            ],
            WAIT_GIT_ENV_TEXT: [
                MessageHandler(filters.Regex("^🔙 Cancel$"), cancel),
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_env_text)
            ],
            WAIT_SELECT_FILE: [CallbackQueryHandler(select_git_file)]
        },
        fallbacks=[CommandHandler('cancel', cancel), MessageHandler(filters.Regex("^🔙 Cancel$"), cancel)]
    )
    
    app_bot.add_handler(CommandHandler('add', add_user))
    app_bot.add_handler(CommandHandler('remove', remove_user))
    app_bot.add_handler(conv_file)
    app_bot.add_handler(conv_git)
    app_bot.add_handler(MessageHandler(filters.Regex("^📂 My Hosted Apps$"), list_hosted))
    app_bot.add_handler(MessageHandler(filters.Regex("^📊 Server Stats$"), server_stats))
    app_bot.add_handler(MessageHandler(filters.Regex("^🆘 Help$"), help_command))
    app_bot.add_handler(CallbackQueryHandler(manage_callback))
    app_bot.add_handler(CommandHandler('start', start))

    print("Bot is up and running!")
    app_bot.run_polling()
