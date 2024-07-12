import os
import json
import tempfile
import asyncio
from typing import Dict, Set, Any, Optional
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters, ChatMemberHandler
from telegram.constants import ParseMode
from openai import OpenAI
from dotenv import load_dotenv
import logging

# 常量定义
MODELS_FILE = 'models.json'
USERS_FILE = 'allowed_users.json'
USER_SETTINGS_FILE = 'user_models.json'
DEFAULT_MODELS = ['gpt-3.5-turbo', 'gpt-4']
DEFAULT_VOICE = 'onyx'
VALID_VOICES = {'alloy', 'echo', 'fable', 'nova', 'shimmer', 'onyx'}

load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置加载和验证
class Config:
    TOKEN: str = os.getenv('TELEGRAM_BOT_TOKEN', '')
    OPENAI_API_KEY: str = os.getenv('OPENAI_API_KEY', '')
    OPENAI_BASE_URL: str = os.getenv('OPENAI_BASE_URL', 'https://api.openai.com/v1')
    ADMIN_ID: int = int(os.getenv('ADMIN_ID', '0'))

    @classmethod
    def validate(cls):
        if not cls.TOKEN or not cls.OPENAI_API_KEY or cls.ADMIN_ID == 0:
            raise ValueError("请确保设置了所有必要的环境变量：TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, ADMIN_ID")

Config.validate()

# OpenAI客户端初始化
client = OpenAI(api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_BASE_URL)

# 文件操作函数
def load_json(filename: str, default: Any) -> Any:
    try:
        with open(filename, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return default

def save_json(filename: str, data: Any) -> None:
    with open(filename, 'w') as f:
        json.dump(data, f)

# 数据加载
MODELS: list = load_json(MODELS_FILE, DEFAULT_MODELS)
allowed_users: Set[int] = set(load_json(USERS_FILE, []))
user_settings: Dict[str, Dict[str, Any]] = load_json(USER_SETTINGS_FILE, {})
user_sessions: Dict[str, list] = {}

# 用户权限检查
def is_user_allowed(user_id: int, chat_id: int) -> bool:
    return user_id in allowed_users or user_id == Config.ADMIN_ID or chat_id < 0

# 获取会话key
def get_session_key(user_id: int, chat_id: int) -> str:
    return f"{user_id}:{chat_id}"

# 用户设置处理
def get_user_setting(user_id: int, chat_id: int, key: str, default: Any) -> Any:
    user_id_str = str(user_id)
    chat_id_str = str(chat_id)
    if user_id_str in user_settings:
        if chat_id_str in user_settings[user_id_str].get("chats", {}):
            return user_settings[user_id_str]["chats"][chat_id_str].get(key, 
                   user_settings[user_id_str]["global"].get(key, default))
        else:
            return user_settings[user_id_str]["global"].get(key, default)
    return default

def set_user_setting(user_id: int, chat_id: int, key: str, value: Any) -> None:
    user_id_str = str(user_id)
    chat_id_str = str(chat_id)
    if user_id_str not in user_settings:
        user_settings[user_id_str] = {"global": {}, "chats": {}}
    if chat_id_str == user_id_str:  # 如果是私聊，设置全局设置
        user_settings[user_id_str]["global"][key] = value
    else:
        if chat_id_str not in user_settings[user_id_str]["chats"]:
            user_settings[user_id_str]["chats"][chat_id_str] = {}
        user_settings[user_id_str]["chats"][chat_id_str][key] = value
    save_json(USER_SETTINGS_FILE, user_settings)

# 帮助信息生成
def get_help_message(is_admin: bool = False) -> str:
    help_message = (
        "可用的命令：\n"
        "/start - 开始使用机器人并显示帮助信息\n"
        "/redo - 重新生成上一个回答\n"
        "/help - 显示此帮助信息\n"
        "/set_model <model> - 设置您想使用的模型\n"
        "/list_models - 列出所有可用的模型\n"
        "/current_settings - 显示当前使用的设置\n"
        "/set_voice <voice> - 设置TTS声音\n"
        "/toggle_stream - 切换流式输出模式\n"
        "/draw <prompt> - 使用DALL-E 3生成图像\n"
        "/chat <message> - 在群组中开始新的对话\n"
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

# 命令处理函数
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if is_user_allowed(user_id, chat_id):
        is_admin = user_id == Config.ADMIN_ID
        help_message = get_help_message(is_admin)
        await update.message.reply_text(f'欢迎使用GPT机器人！\n\n{help_message}')
    else:
        await update.message.reply_text('抱歉，您没有使用权限。')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if is_user_allowed(user_id, chat_id):
        is_admin = user_id == Config.ADMIN_ID
        help_message = get_help_message(is_admin)
        await update.message.reply_text(help_message)
    else:
        await update.message.reply_text('抱歉，您没有使用权限。')

async def redo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    session_key = get_session_key(user_id, chat_id)
    if session_key in user_sessions and len(user_sessions[session_key]) >= 2:
        user_sessions[session_key].pop()
        processing_message = await update.message.reply_text("正在重新生成回答，请稍候...")
        try:
            response = get_gpt_response(user_id, chat_id, user_sessions[session_key])
            user_sessions[session_key].append({'role': 'assistant', 'content': response})
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=processing_message.message_id,
                text=response,
                parse_mode=ParseMode.MARKDOWN
            )
        except Exception as e:
            print(f"Error in redo: {e}")
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=processing_message.message_id,
                text="抱歉，重新生成回答时发生了错误。请稍后再试。"
            )
    else:
        await update.message.reply_text('没有可以重做的消息。')

async def set_api_key(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != Config.ADMIN_ID:
        await update.message.reply_text('只有管理员可以设置API密钥。')
        return

    if len(context.args) != 1:
        await update.message.reply_text('请提供新的API密钥。')
        return

    Config.OPENAI_API_KEY = context.args[0]
    global client
    client = OpenAI(api_key=Config.OPENAI_API_KEY, base_url=Config.OPENAI_BASE_URL)
    await update.message.reply_text('API密钥已更新。')

async def set_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_allowed(user_id, chat_id):
        await update.message.reply_text('抱歉，您没有使用权限。')
        return

    if len(context.args) != 1 or context.args[0] not in MODELS:
        await update.message.reply_text(f'请选择有效的模型: {", ".join(MODELS)}')
        return

    set_user_setting(user_id, chat_id, 'model', context.args[0])
    await update.message.reply_text(f'您的模型已更改为 {context.args[0]}。')

async def set_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_allowed(user_id, chat_id):
        await update.message.reply_text('抱歉，您没有使用权限。')
        return

    if len(context.args) != 1 or context.args[0] not in VALID_VOICES:
        await update.message.reply_text(f'请选择有效的声音: {", ".join(VALID_VOICES)}')
        return

    set_user_setting(user_id, chat_id, 'voice', context.args[0])
    await update.message.reply_text(f'您的TTS声音已设置为 {context.args[0]}。')

async def toggle_stream_output(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_allowed(user_id, chat_id):
        await update.message.reply_text('抱歉，您没有使用权限。')
        return

    current_setting = get_user_setting(user_id, chat_id, 'stream_output', False)
    new_setting = not current_setting
    set_user_setting(user_id, chat_id, 'stream_output', new_setting)
    await update.message.reply_text(f'流式输出已{"开启" if new_setting else "关闭"}。')

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != Config.ADMIN_ID:
        await update.message.reply_text('只有管理员可以添加用户。')
        return

    if len(context.args) != 1:
        await update.message.reply_text('请提供要添加的用户ID。')
        return

    new_user_id = int(context.args[0])
    allowed_users.add(new_user_id)
    save_json(USERS_FILE, list(allowed_users))
    await update.message.reply_text(f'用户 {new_user_id} 已被添加到允许列表。')

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != Config.ADMIN_ID:
        await update.message.reply_text('只有管理员可以删除用户。')
        return

    if len(context.args) != 1:
        await update.message.reply_text('请提供要删除的用户ID。')
        return

    remove_user_id = int(context.args[0])
    if remove_user_id in allowed_users:
        allowed_users.remove(remove_user_id)
        save_json(USERS_FILE, list(allowed_users))
        await update.message.reply_text(f'用户 {remove_user_id} 已从允许列表中删除。')
    else:
        await update.message.reply_text(f'用户 {remove_user_id} 不在允许列表中。')

async def add_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != Config.ADMIN_ID:
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
        save_json(MODELS_FILE, MODELS)
        await update.message.reply_text(f'模型 {new_model} 已被添加到可用模型列表。')

async def remove_model(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != Config.ADMIN_ID:
        await update.message.reply_text('只有管理员可以删除模型。')
        return

    if len(context.args) != 1:
        await update.message.reply_text('请提供要删除的模型名称。')
        return

    remove_model_name = context.args[0]
    if remove_model_name in MODELS:
        MODELS.remove(remove_model_name)
        save_json(MODELS_FILE, MODELS)
        for settings_key, settings in user_settings.items():
            if settings.get('model') == remove_model_name:
                settings['model'] = MODELS[0]
        save_json(USER_SETTINGS_FILE, user_settings)
        await update.message.reply_text(f'模型 {remove_model_name} 已从可用模型列表中删除。使用此模型的用户已被更新为默认模型。')
    else:
        await update.message.reply_text(f'模型 {remove_model_name} 不在可用模型列表中。')

async def list_models(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(f'当前可用的模型: {", ".join(MODELS)}')

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id != Config.ADMIN_ID:
        await update.message.reply_text('只有管理员可以查看用户列表。')
        return

    users_list = ", ".join(str(user) for user in allowed_users)
    await update.message.reply_text(f'当前允许的用户: {users_list}')

async def current_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if is_user_allowed(user_id, chat_id):
        try:
            global_model = get_user_setting(user_id, user_id, 'model', MODELS[0])
            global_voice = get_user_setting(user_id, user_id, 'voice', DEFAULT_VOICE)
            global_stream_output = get_user_setting(user_id, user_id, 'stream_output', False)
            
            chat_model = get_user_setting(user_id, chat_id, 'model', global_model)
            chat_voice = get_user_setting(user_id, chat_id, 'voice', global_voice)
            chat_stream_output = get_user_setting(user_id, chat_id, 'stream_output', global_stream_output)
            
            settings_message = (
                f'您的全局设置：\n'
                f'模型: {global_model}\n'
                f'TTS声音: {global_voice}\n'
                f'流式输出: {"开启" if global_stream_output else "关闭"}\n\n'
            )
            
            if chat_id != user_id:
                settings_message += (
                    f'当前聊天的设置：\n'
                    f'模型: {chat_model}\n'
                    f'TTS声音: {chat_voice}\n'
                    f'流式输出: {"开启" if chat_stream_output else "关闭"}'
                )
            
            await update.message.reply_text(settings_message)
        except Exception as e:
            print(f"Error in current_settings: {e}")
            await update.message.reply_text('获取当前设置时发生错误。请稍后再试。')
    else:
        await update.message.reply_text('抱歉，您没有使用权限。')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_allowed(user_id, chat_id):
        await update.message.reply_text('抱歉，您没有使用权限。')
        return

    is_voice = update.message.voice is not None
    
    if is_voice:
        message = await process_voice_message(update, context)
    else:
        message = update.message.text
    
    is_reply = update.message.reply_to_message and update.message.reply_to_message.from_user.id == context.bot.id

    session_key = get_session_key(user_id, chat_id)
    if not is_reply:
        # 如果不是回复机器人的消息，并且不在私聊中，则忽略
        if chat_id < 0:  # 群组的 chat_id 是负数
            return
        user_sessions[session_key] = []

    if session_key not in user_sessions:
        user_sessions[session_key] = []

    user_sessions[session_key].append({'role': 'user', 'content': message})
    
    processing_message = await update.message.reply_text("正在处理您的请求，请稍候...")

    try:
        response = get_gpt_response(user_id, chat_id, user_sessions[session_key])
        user_sessions[session_key].append({'role': 'assistant', 'content': response})
        
        voice = get_user_setting(user_id, chat_id, 'voice', DEFAULT_VOICE)
        stream_output = get_user_setting(user_id, chat_id, 'stream_output', False)
        
        if is_voice:
            await send_voice_response(update, context, response, voice)
            await context.bot.delete_message(chat_id=chat_id, message_id=processing_message.message_id)
            
            if stream_output:
                await stream_response(update, context, response)
            else:
                await update.message.reply_text(response, parse_mode=ParseMode.MARKDOWN)
        else:
            if stream_output:
                await context.bot.delete_message(chat_id=chat_id, message_id=processing_message.message_id)
                await stream_response(update, context, response)
            else:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=processing_message.message_id,
                    text=response,
                    parse_mode=ParseMode.MARKDOWN
                )
    except Exception as e:
        print(f"Error in handle_message: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text="抱歉，处理您的请求时发生了错误。请稍后再试。"
        )

async def process_voice_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    voice_file = await context.bot.get_file(update.message.voice.file_id)
    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as voice_ogg:
        await voice_file.download_to_drive(voice_ogg.name)
        
        with open(voice_ogg.name, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1", 
                file=audio_file
            )
        
        os.unlink(voice_ogg.name)  # 删除临时文件
        return transcript.text

async def send_voice_response(update: Update, context: ContextTypes.DEFAULT_TYPE, response: str, voice: str) -> None:
    speech_file_path = tempfile.mktemp(suffix=".mp3")
    with client.audio.speech.with_streaming_response.create(
        model="tts-1",
        voice=voice,
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

async def stream_response(update: Update, context: ContextTypes.DEFAULT_TYPE, response: str):
    message = await update.message.reply_text("...")
    for i in range(0, len(response), 100):  # 每次发送100个字符
        chunk = response[i:i+100]
        await asyncio.sleep(0.5)  # 模拟打字效果
        await context.bot.edit_message_text(
            chat_id=update.effective_chat.id,
            message_id=message.message_id,
            text=response[:i+100],
            parse_mode=ParseMode.MARKDOWN
        )

def get_gpt_response(user_id: int, chat_id: int, messages: list) -> str:
    try:
        model = get_user_setting(user_id, chat_id, 'model', MODELS[0])
        response = client.chat.completions.create(
            model=model,
            messages=messages
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in get_gpt_response: {e}")
        raise

async def draw(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_allowed(user_id, chat_id):
        await update.message.reply_text('抱歉，您没有使用权限。')
        return

    if not context.args:
        await update.message.reply_text('请提供绘画提示。')
        return

    prompt = ' '.join(context.args)
    processing_message = await update.message.reply_text("正在生成图像，请稍候...")

    try:
        response = client.images.generate(
            model="dall-e-3",
            prompt=prompt,
            size="1024x1024",
            quality="high-quality",
            n=1,
        )

        logger.info(f"DALL-E API Response: {response}")  # 记录完整的响应

        if response and response.data and len(response.data) > 0:
            image_url = response.data[0].url
            if image_url:
                await context.bot.send_photo(chat_id=chat_id, photo=image_url)
                await context.bot.delete_message(chat_id=chat_id, message_id=processing_message.message_id)
            else:
                raise ValueError("Image URL is None")
        else:
            raise ValueError("Invalid response structure from DALL-E API")

    except Exception as e:
        logger.error(f"Error in draw: {e}", exc_info=True)  # 记录详细的错误信息
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text=f"抱歉，生成图像时发生了错误: {str(e)}。请稍后再试。"
        )

async def chat_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.effective_chat.id
    if not is_user_allowed(user_id, chat_id):
        await update.message.reply_text('抱歉，您没有使用权限。')
        return

    if not context.args:
        await update.message.reply_text('请在 /chat 命令后输入您的消息。')
        return

    message = ' '.join(context.args)
    session_key = get_session_key(user_id, chat_id)
    user_sessions[session_key] = [{'role': 'user', 'content': message}]

    processing_message = await update.message.reply_text("正在处理您的请求，请稍候...")

    try:
        response = get_gpt_response(user_id, chat_id, user_sessions[session_key])
        user_sessions[session_key].append({'role': 'assistant', 'content': response})
        
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text=response,
            parse_mode=ParseMode.MARKDOWN
        )
    except Exception as e:
        print(f"Error in chat_command: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=processing_message.message_id,
            text="抱歉，处理您的请求时发生了错误。请稍后再试。"
        )

async def unknown_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # 不做任何响应
    pass

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f'Exception while handling an update: {context.error}')

async def group_chat_created(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.chat_member
    if result.new_chat_member.status == "member" and result.new_chat_member.user.id == context.bot.id:
        await update.effective_chat.send_message("感谢将我添加到群组!使用 /help 查看可用命令。")

def main() -> None:
    application = Application.builder().token(Config.TOKEN).build()

    # 使用字典来注册命令
    commands = {
        "start": start,
        "help": help_command,
        "redo": redo,
        "set_api_key": set_api_key,
        "set_model": set_model,
        "set_voice": set_voice,
        "toggle_stream": toggle_stream_output,
        "add_user": add_user,
        "remove_user": remove_user,
        "add_model": add_model,
        "remove_model": remove_model,
        "list_models": list_models,
        "list_users": list_users,
        "current_settings": current_settings,
        "draw": draw,
        "chat": chat_command 
    }

    for command, handler in commands.items():
        application.add_handler(CommandHandler(command, handler))

    # 添加消息处理器
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND | filters.VOICE, handle_message))

    # 添加未知命令处理器
    application.add_handler(MessageHandler(filters.COMMAND, unknown_command))

    # 添加群组创建处理器
    application.add_handler(ChatMemberHandler(group_chat_created, ChatMemberHandler.CHAT_MEMBER))

    # 添加错误处理器
    application.add_error_handler(error_handler)

    application.run_polling()

if __name__ == '__main__':
    main()
