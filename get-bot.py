import os
import json
import tempfile
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters
from telegram.constants import ParseMode
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

# 从环境变量加载配置
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
OPENAI_BASE_URL = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')
ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))  # 提供默认值 '0'

if not TOKEN or not OPENAI_API_KEY or ADMIN_ID == 0:
    raise ValueError("请确保设置了所有必要的环境变量：TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, ADMIN_ID")

# 初始化OpenAI客户端
client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)

# 文件路径
MODELS_FILE = 'models.json'
USERS_FILE = 'allowed_users.json'
USER_MODELS_FILE = 'user_models.json'

# 加载模型列表
def load_models():
    try:
        with open(MODELS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return ['gpt-3.5-turbo', 'gpt-4']  # 默认模型

# 保存模型列表
def save_models():
    with open(MODELS_FILE, 'w') as f:
        json.dump(MODELS, f)

# 加载允许的用户列表
def load_allowed_users():
    try:
        with open(USERS_FILE, 'r') as f:
            return set(json.load(f))
    except FileNotFoundError:
        return set()

# 保存允许的用户列表
def save_allowed_users():
    with open(USERS_FILE, 'w') as f:
        json.dump(list(allowed_users), f)

# 加载用户模型选择
def load_user_models():
    try:
        with open(USER_MODELS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# 保存用户模型选择
def save_user_models():
    with open(USER_MODELS_FILE, 'w') as f:
        json.dump(user_models, f)

# 加载数据
MODELS = load_models()
allowed_users = load_allowed_users()
user_models = load_user_models()

# 存储用户会话
user_sessions = {}

def get_help_message(is_admin=False):
    help_message = (
        "可用的命令：\n"
        "/start - 开始使用机器人并显示帮助信息\n"
        "/redo - 重新生成上一个回答\n"
        "/help - 显示此帮助信息\n"
        "/set_model <model> - 设置您想使用的模型\n"
        "/list_models - 列出所有可用的模型\n"
        "/current_model - 显示当前使用的模型\n"
        "\n直接发送消息开始新对话，回复机器人消息继续上下文对话。"
    )
    if is_admin:
        help_message += (
            "\n管理员命令：\n"
            "/set_api_key <key> - 设置新的API密钥\n"
            "/add_user <user_id> - 添加新的允许用户\n"
            "/remove_user <user_id> - 删除允许的用户\n"
            "/add_model <model> - 添加新的模型\n"
            "/remove_model <model> - 删除模型\n"
            "/list_users - 列出所有允许的用户\n"
        )
    return help_message

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in allowed_users or user_id == ADMIN_ID:
        is_admin = user_id == ADMIN_ID
        help_message = get_help_message(is_admin)
        await update.message.reply_text(f'欢迎使用GPT机器人！\n\n{help_message}')
    else:
        await update.message.reply_text('抱歉，您没有使用权限。')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in allowed_users or user_id == ADMIN_ID:
        is_admin = user_id == ADMIN_ID
        help_message = get_help_message(is_admin)
        await update.message.reply_text(help_message)
    else:
        await update.message.reply_text('抱歉，您没有使用权限。')

async def redo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in user_sessions and len(user_sessions[user_id]) >= 2:
        # 移除最后一个助手回复
        user_sessions[user_id].pop()
        # 发送"正在处理"的消息
        processing_message = await update.message.reply_text("正在重新生成回答，请稍候...")
        try:
            # 重新生成回复
            response = get_gpt_response(user_id, user_sessions[user_id])
            user_sessions[user_id].append({'role': 'assistant', 'content': response})
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=processing_message.message_id,
                text=response,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            print(f"Error in redo: {e}")
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=processing_message.message_id,
                text="抱歉，重新生成回答时发生了错误。请稍后再试。"
            )
    else:
        await update.message.reply_text('没有可以重做的消息。')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in allowed_users and user_id != ADMIN_ID:
        await update.message.reply_text('抱歉，您没有使用权限。')
        return

    is_voice = update.message.voice is not None
    
    if is_voice:
        # 处理语音消息
        voice_file = await context.bot.get_file(update.message.voice.file_id)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as voice_ogg:
            await voice_file.download_to_drive(voice_ogg.name)
            
            # 使用 OpenAI 的 Whisper 模型进行语音识别
            with open(voice_ogg.name, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1", 
                    file=audio_file
                )
            
            message = transcript.text
            os.unlink(voice_ogg.name)  # 删除临时文件
    else:
        # 处理文本消息
        message = update.message.text
    
    # 检查是否是回复消息
    is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id

    if not is_reply:
        # 如果不是回复消息，开始新的会话
        user_sessions[user_id] = []

    user_sessions[user_id].append({'role': 'user', 'content': message})
    
    # 发送"正在处理"的消息
    processing_message = await update.message.reply_text("正在处理您的请求，请稍候...")

    try:
        response = get_gpt_response(user_id, user_sessions[user_id])
        user_sessions[user_id].append({'role': 'assistant', 'content': response})
        
        if is_voice:
            # 使用 OpenAI 的 TTS 模型生成语音回复
            speech_file_path = tempfile.mktemp(suffix=".mp3")
            with client.audio.speech.with_streaming_response.create(
                model="tts-1",
                voice="alloy",
                input=response
            ) as response_audio:
                with open(speech_file_path, 'wb') as f:
                    for chunk in response_audio.iter_bytes():
                        f.write(chunk)
            
            await context.bot.send_voice(
                chat_id=update.effective_chat.id,
                voice=open(speech_file_path, 'rb')
            )
            os.remove(speech_file_path)
            
            await context.bot.delete_message(
                chat_id=update.effective_chat.id,
                message_id=processing_message.message_id
            )
        else:
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=processing_message.message_id,
                text=response,
                parse_mode=ParseMode.MARKDOWN
            )
    except Exception as e:
        print(f"Error in handle_message: {e}")
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=processing_message.message_id,
            text="抱歉，处理您的请求时发生了错误。请稍后再试。"
        )

def get_gpt_response(user_id, messages):
    try:
        model = user_models.get(str(user_id), MODELS[0])  # 使用用户特定的模型，如果没有设置则使用默认模型
        response = client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in get_gpt_response: {e}")
        raise

async def set_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text('只有管理员可以设置API密钥。')
        return

    if len(context.args) != 1:
        await update.message.reply_text('请提供新的API密钥。')
        return

    global OPENAI_API_KEY
    OPENAI_API_KEY = context.args[0]
    global client
    client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL)
    await update.message.reply_text('API密钥已更新。')

async def set_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in allowed_users and user_id != ADMIN_ID:
        await update.message.reply_text('抱歉，您没有使用权限。')
        return

    if len(context.args) != 1 or context.args[0] not in MODELS:
        await update.message.reply_text(f'请选择有效的模型: {", ".join(MODELS)}')
        return

    user_models[str(user_id)] = context.args[0]
    save_user_models()
    await update.message.reply_text(f'您的模型已更改为 {context.args[0]}。')

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text('只有管理员可以添加用户。')
        return

    if len(context.args) != 1:
        await update.message.reply_text('请提供要添加的用户ID。')
        return

    new_user_id = int(context.args[0])
    allowed_users.add(new_user_id)
    save_allowed_users()
    await update.message.reply_text(f'用户 {new_user_id} 已被添加到允许列表。')

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text('只有管理员可以删除用户。')
        return

    if len(context.args) != 1:
        await update.message.reply_text('请提供要删除的用户ID。')
        return

    remove_user_id = int(context.args[0])
    if remove_user_id in allowed_users:
        allowed_users.remove(remove_user_id)
        save_allowed_users()
        await update.message.reply_text(f'用户 {remove_user_id} 已从允许列表中删除。')
    else:
        await update.message.reply_text(f'用户 {remove_user_id} 不在允许列表中。')

async def add_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text('只有管理员可以添加模型。')
        return

    if len(context.args) != 1:
        await update.message.reply_text('请提供要添加的模型名称。')
        return

    new_model = context.args[0]
    if new_model in MODELS:
        await update.message.reply_text(f'模型 {new_model} 已经存在。')
    else:
        MODELS.append(new_model)
        save_models()
        await update.message.reply_text(f'模型 {new_model} 已被添加到可用模型列表。')

async def remove_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text('只有管理员可以删除模型。')
        return

    if len(context.args) != 1:
        await update.message.reply_text('请提供要删除的模型名称。')
        return

    remove_model_name = context.args[0]
    if remove_model_name in MODELS:
        MODELS.remove(remove_model_name)
        save_models()
        # 更新使用被删除模型的用户
        for user, model in user_models.items():
            if model == remove_model_name:
                user_models[user] = MODELS[0]
        save_user_models()
        await update.message.reply_text(f'模型 {remove_model_name} 已从可用模型列表中删除。使用此模型的用户已被更新为默认模型。')
    else:
        await update.message.reply_text(f'模型 {remove_model_name} 不在可用模型列表中。')

async def list_models(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f'当前可用的模型: {", ".join(MODELS)}')

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text('只有管理员可以查看用户列表。')
        return

    users_list = ", ".join(str(user) for user in allowed_users)
    await update.message.reply_text(f'当前允许的用户: {users_list}')

async def current_model_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id in allowed_users or user_id == ADMIN_ID:
        model = user_models.get(str(user_id), MODELS[0])
        await update.message.reply_text(f'您当前使用的模型是: {model}。')
    else:
        await update.message.reply_text('抱歉，您没有使用权限。')

def main() -> None:
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("redo", redo))
    application.add_handler(CommandHandler("set_api_key", set_api_key))
    application.add_handler(CommandHandler("set_model", set_model))
    application.add_handler(CommandHandler("add_user", add_user))
    application.add_handler(CommandHandler("remove_user", remove_user))
    application.add_handler(CommandHandler("add_model", add_model))
    application.add_handler(CommandHandler("remove_model", remove_model))
    application.add_handler(CommandHandler("list_models", list_models))
    application.add_handler(CommandHandler("list_users", list_users))
    application.add_handler(CommandHandler("current_model", current_model_command))
    #application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(MessageHandler(filters.TEXT | filters.VOICE, handle_message))

    application.run_polling()

if __name__ == '__main__':
    main()
