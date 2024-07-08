# GPT Telegram Bot 部署和使用指南（功能实现及文档完全由GPT编写）
## 1. 环境准备
### 1.1 安装依赖
确保你的系统已安装 Python 3.7 或更高版本，然后安装必要的依赖：
```bash
pip install python-telegram-bot openai python-dotenv
```
### 1.2 配置环境变量
创建一个 .env 文件，并填入以下内容：
```
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
OPENAI_API_KEY=your_openai_api_key
ADMIN_ID=your_admin_telegram_id
OPENAI_BASE_URL=https://api.openai.com/v1  # 可选，如果你使用自定义 API 端点
```
将 your_telegram_bot_token、your_openai_api_key 和 your_admin_telegram_id 替换为实际的值。
## 2. 部署机器人
### 2.1 下载代码
将机器人代码保存为 gpt-bot.py。
### 2.2 运行机器人
你可以直接运行机器人：
```
python3 gpt-bot.py
```
### 2.3 设置为系统服务（可选）
创建一个系统服务文件：
```
sudo nano /etc/systemd/system/gpt-bot.service
```
在文件中添加以下内容：
```
[Unit]
Description=GPT Telegram Bot
After=network.target

[Service]
ExecStart=/usr/bin/python3 /path/to/gpt-bot.py
WorkingDirectory=/path/to/bot/directory
User=your_username
Group=your_group
Restart=always

[Install]
WantedBy=multi-user.target
```
替换 /path/to/gpt-bot.py、/path/to/bot/directory、your_username 和 your_group 为实际的值。

重新加载 systemd，启动并启用服务：
```
sudo systemctl daemon-reload
sudo systemctl start gpt-bot
sudo systemctl enable gpt-bot
```
## 3. 使用指南
### 3.1 管理员命令
/start - 开始使用机器人并显示帮助信息  
/help - 显示帮助信息  
/set_api_key <key> - 设置新的 OpenAI API 密钥  
/add_user <user_id> - 添加新的允许用户  
/remove_user <user_id> - 删除允许的用户  
/add_model <model> - 添加新的模型  
/remove_model <model> - 删除模型  
/list_users - 列出所有允许的用户
### 3.2 用户命令
/start - 开始使用机器人并显示帮助信息  
/help - 显示帮助信息  
/redo - 重新生成上一个回答  
/set_model <model> - 设置您想使用的模型  
/list_models - 列出所有可用的模型  
/current_model - 显示当前使用的模型并结束当前会话
### 3.3 使用流程
管理员使用 /add_user 命令添加允许的用户。  
用户发送 /start 命令开始使用机器人。  
用户可以直接发送消息与 GPT 模型对话。  
使用 /new 命令开始新的对话，清除之前的上下文。  
使用 /set_model 命令更改使用的 GPT 模型。
## 4. 故障排除
如果机器人无响应，检查日志:
```
sudo journalctl -u gpt-bot
```
确保 .env 文件中的所有变量都已正确设置。  
检查 OpenAI API 密钥是否有效，以及是否有足够的使用额度。
## 5. 注意事项
定期备份 models.json、allowed_users.json 和 user_models.json 文件。  
保护好 .env 文件，不要泄露 API 密钥和 Bot Token。  
定期检查和更新依赖库，以确保安全性和稳定性。
## 6. 高级配置
### 6.1 自定义 OpenAI API 端点
如果你使用的是自定义的 OpenAI API 端点（例如，通过反向代理或自己部署的模型服务），你可以在 `.env` 文件中设置 `OPENAI_BASE_URL`：
OPENAI_BASE_URL=https://your-custom-endpoint.com/v1
### 6.2 调整模型参数
你可以修改 `get_gpt_response` 函数来调整模型的参数，例如温度、最大令牌数等：
```python
def get_gpt_response(user_id, messages):
    try:
        model = user_models.get(str(user_id), MODELS[0])
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.7,  # 调整此值以改变输出的随机性
            max_tokens=150,   # 调整此值以限制回复的长度
            top_p=1,
            frequency_penalty=0,
            presence_penalty=0
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"Error in get_gpt_response: {e}")
        raise
```
## 7. 安全性考虑
### 7.1 API 密钥轮换
定期更换 OpenAI API 密钥是一个好习惯。你可以使用管理员命令 /set_api_key 来更新 API 密钥，而无需重启机器人。
### 7.2 用户权限管理
仔细管理允许使用机器人的用户列表。定期审查用户列表，移除不再需要访问的用户。
### 7.3 日志管理
考虑实现日志轮换，以防止日志文件过大：
安装 logrotate（如果尚未安装）：
```
sudo apt-get install logrotate
```
创建 logrotate 配置文件：
```
sudo nano /etc/logrotate.d/gpt-bot
```
添加以下内容：
```
/path/to/bot/logs/gpt-bot.log {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
    create 644 bot_user bot_group
}
```
替换 /path/to/bot/logs/gpt-bot.log、bot_user 和 bot_group 为实际的值。
## 8. 性能优化
### 8.1 使用异步操作
确保所有的 I/O 操作（如文件读写、API 调用）都是异步的，以提高机器人的响应速度和并发处理能力。
### 8.2 缓存机制
考虑实现一个简单的缓存机制，以减少重复的 API 调用：
```
import functools

@functools.lru_cache(maxsize=100)
def cached_gpt_response(model, messages_tuple):
    messages = list(messages_tuple)
    return get_gpt_response(model, messages)

def get_gpt_response(user_id, messages):
    model = user_models.get(str(user_id), MODELS[0])
    messages_tuple = tuple(tuple(m.items()) for m in messages)
    return cached_gpt_response(model, messages_tuple)
```
## 9. 监控和维护
### 9.1 设置监控
使用诸如 Prometheus 和 Grafana 的工具来监控机器人的性能和使用情况。
### 9.2 定期备份
设置定期备份任务，备份配置文件和用户数据：
```
0 2 * * * tar -czf /path/to/backup/gpt-bot-$(date +\%Y\%m\%d).tar.gz /path/to/bot/directory
```
### 9.3 更新依赖
定期更新依赖库以确保安全性和性能：
```
pip install --upgrade python-telegram-bot openai python-dotenv
```
## 10. 扩展功能
### 10.1 多语言支持
实现多语言支持，允许用户选择他们喜欢的语言：
```
LANGUAGES = {
    'en': 'English',
    'zh': '中文',
    # 添加更多语言
}

async def set_language(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if len(context.args) != 1 or context.args[0] not in LANGUAGES:
        await update.message.reply_text(f'请选择有效的语言: {", ".join(LANGUAGES.keys())}')
        return
    user_languages[str(user_id)] = context.args[0]
    save_user_languages()
    await update.message.reply_text(f'语言已设置为 {LANGUAGES[context.args[0]]}')
```
### 10.2 语音消息支持
添加对语音消息的支持，将语音转换为文本后处理：
```
from telegram import Update
from telegram.ext import MessageHandler, filters

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    voice = update.message.voice
    # 使用语音识别 API 将语音转换为文本
    # 处理文本消息
    # ...

application.add_handler(MessageHandler(filters.VOICE, handle_voice))
```
这些额外的部分涵盖了更多高级主题，包括安全性考虑、性能优化、监控和维护，以及一些可能的扩展功能。你可以根据实际需求选择性地实现这些功能，或者根据你的具体使用场景进一步定制。
