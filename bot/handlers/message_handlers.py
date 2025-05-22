from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatMemberStatus
from pyrogram.handlers import MessageHandler
from bot.services.admin_service import admin_service
from bot.services.book_service import book_service
from bot.services.cultivation_service import cultivation_service
from bot.services.db_service import db_service
from bot.config.config import CHAT_MIN_CHARS, ALLOWED_EXTENSIONS, BOOK_POINT_REWARD, CULTIVATION_STAGES, BOOK_DOWNLOAD_PATH
from bot.utils.helpers import is_chinese_text, auto_delete_messages, calculate_md5, auto_delete_reply
import pyrogram
import asyncio
import time
import random
from collections import defaultdict, deque
import os

# 全局处理队列和信号量
processing_queue = {}  # 用户ID -> 队列
user_semaphores = {}  # 用户ID -> 信号量
# 全局命令信号量，用于确保命令始终能被处理
command_semaphore = asyncio.Semaphore(30)  # 允许30个命令同时处理

# 群组消息记录，用于AI乱入回复
group_messages = defaultdict(lambda: deque(maxlen=30))  # 群组ID -> 最近30条消息
group_message_count = defaultdict(int)  # 群组ID -> 消息计数

# 用户上传速率控制器
class UploadRateController:
    def __init__(self, max_concurrent=3, rate_limit=10, time_window=60):
        """初始化上传速率控制器
        
        Args:
            max_concurrent: 同一用户最大并发处理数
            rate_limit: 时间窗口内最大处理数
            time_window: 时间窗口，单位秒
        """
        self.max_concurrent = max_concurrent
        self.rate_limit = rate_limit
        self.time_window = time_window
        self.user_uploads = defaultdict(list)
    
    def can_process_now(self, user_id):
        """检查是否可以立即处理用户上传
        
        Args:
            user_id: 用户ID
        
        Returns:
            bool: 是否允许立即处理
            int: 建议等待的时间（秒）
        """
        current_time = time.time()
        
        # 清理过期的上传记录
        self.user_uploads[user_id] = [t for t in self.user_uploads[user_id] 
                                     if current_time - t < self.time_window]
        
        # 检查上传次数是否超过限制
        if len(self.user_uploads[user_id]) >= self.rate_limit:
            # 计算需要等待的时间
            oldest_time = self.user_uploads[user_id][0]
            wait_time = int(self.time_window - (current_time - oldest_time))
            return False, max(1, wait_time)
        
        return True, 0
    
    def record_upload(self, user_id):
        """记录一次上传处理
        
        Args:
            user_id: 用户ID
        """
        self.user_uploads[user_id].append(time.time())
    
    def get_user_semaphore(self, user_id):
        """获取用户的信号量，用于控制并发
        
        Args:
            user_id: 用户ID
            
        Returns:
            asyncio.Semaphore: 用户的信号量
        """
        if user_id not in user_semaphores:
            user_semaphores[user_id] = asyncio.Semaphore(self.max_concurrent)
        return user_semaphores[user_id]

# 创建上传速率控制器 - 增加并发处理数和速率限制
upload_controller = UploadRateController(max_concurrent=10, rate_limit=50, time_window=60)

async def process_file_task(client, message, file_id, file_name, user_id, username):
    """异步处理文件任务"""
    semaphore = upload_controller.get_user_semaphore(user_id)
    
    async with semaphore:
        # 检查是否可以立即处理，如果不能，等待适当的时间
        can_process, wait_time = upload_controller.can_process_now(user_id)
        if not can_process:
            # 等待时间减少到1/4，显著提高处理速度
            adjusted_wait_time = max(1, wait_time // 4)
            await asyncio.sleep(adjusted_wait_time)
        
        # 记录此次处理
        upload_controller.record_upload(user_id)
        
        # 处理文件下载和奖励
        process_msg = None
        max_retries = 3
        retry_count = 0
        
        # 发送处理消息，有重试机制
        while process_msg is None and retry_count < max_retries:
            try:
                process_msg = await message.reply(f"🔄 正在处理文件: {file_name}...")
                break
            except pyrogram.errors.exceptions.flood_420.FloodWait as e:
                print(f"FloodWait: 需要等待 {e.value} 秒，文件: {file_name}")
                retry_count += 1
                if retry_count < max_retries:
                    # 减少等待时间至1/4，但不低于1秒
                    adjusted_wait = max(1, e.value // 4)
                    await asyncio.sleep(adjusted_wait)
                else:
                    print(f"达到最大重试次数，无法处理文件: {file_name}")
                    return
            except Exception as e:
                print(f"发送消息时出错: {str(e)}")
                return
        
        # 使用异步方式处理文件，不阻塞其他操作
        result = await asyncio.create_task(book_service.process_book_file(file_id, file_name, user_id, client))
        
        # 更新处理消息，有重试机制
        retry_count = 0
        while retry_count < max_retries:
            try:
                if result['success']:
                    if result['is_duplicate']:
                        response_msg = await process_msg.edit_text(f"⚠️ {result['message']}")
                        # 已存在书籍的消息10秒后只删除回复消息，保留原始文件消息
                        asyncio.create_task(auto_delete_reply(response_msg, 10))
                    else:
                        # 构建成功消息
                        success_message = f"✅ {result['message']}\n获得 {result['reward']} 灵石奖励！\n当前灵石: {result['new_points']}"
                        
                        # 添加书籍上传计数信息
                        if 'books_uploaded' in result:
                            success_message += f"\n今日已上传: {result['books_uploaded']}/10 本"
                            
                            # 如果刚激活保护罩，显示特别提示
                            if result.get('shield_activated', False):
                                success_message += "\n🛡️ 已获得今日保护罩，不会被任何人打劫！"
                        
                        response_msg = await process_msg.edit_text(success_message)
                        
                        # 在这里检查并处理飞升任务
                        if not result['is_duplicate']:
                            # 直接检查用户是否在飞升任务的第三阶段
                            task = db_service.get_ascension_task(user_id)
                            print(f"用户 {user_id} 飞升任务状态: {task}")
                            
                            if task and task['current_stage'] == 3:
                                print(f"用户 {user_id} 处于飞升任务第三阶段，开始处理书籍上传进度")
                                # 更新分享书籍数量
                                shared_books = task['shared_books'] + 1
                                db_service.update_ascension_task(user_id, shared_books=shared_books)
                                print(f"更新后的书籍数量: {shared_books}/20")
                                
                                # 发送飞升任务进度消息
                                progress_msg = await message.reply(
                                    f"📚 飞升任务进度更新！\n"
                                    f"已分享书籍：{shared_books}/20"
                                )
                                
                                # 10秒后自动删除进度消息
                                asyncio.create_task(auto_delete_reply(progress_msg, 10))
                        
                        # 成功上传书籍的消息10秒后只删除回复消息，保留原始文件消息
                        asyncio.create_task(auto_delete_reply(response_msg, 10))
                else:
                    await process_msg.edit_text(f"❌ {result['message']}")
                break
            except pyrogram.errors.exceptions.flood_420.FloodWait as e:
                print(f"FloodWait: 需要等待 {e.value} 秒以更新消息，文件: {file_name}")
                retry_count += 1
                if retry_count < max_retries:
                    # 减少等待时间至1/4，但不低于1秒
                    adjusted_wait = max(1, e.value // 4)
                    await asyncio.sleep(adjusted_wait)
                else:
                    print(f"达到最大重试次数，无法更新消息: {file_name}")
                    return
            except Exception as e:
                print(f"更新消息时出错: {str(e)}")
                print(f"错误详情: {type(e).__name__}: {str(e)}")
                import traceback
                print(traceback.format_exc())
                return

async def handle_new_member(client, message):
    """处理新成员加入群组"""
    async with command_semaphore:  # 使用命令信号量确保优先处理
        # 检查群组是否已授权
        if not admin_service.is_group_authorized(message.chat.id):
            return
        
        # 获取新加入的成员列表
        new_members = message.new_chat_members
        
        # 如果没有新成员或者新成员是机器人自己，则忽略
        if not new_members or any(member.is_self for member in new_members):
            return
        
        # 欢迎新成员
        welcome_text = "欢迎加入书群！\n\n"
        welcome_text += "📚 书群规则：\n"
        welcome_text += "1. 请文明交流，互相尊重\n"
        welcome_text += "2. 上传书籍可获得灵石奖励\n"
        welcome_text += "3. 多多水群，可能触发各种奇遇\n"
        welcome_text += "4. 使用 /help 查看可用命令\n"
        welcome_text += "5. 请使用 /checkin 每日签到获取灵石\n\n"
        welcome_text += "祝你在群内玩得愉快！😊"
        
        await message.reply_text(welcome_text)
        
        # 记录新用户加入群组
        for member in new_members:
            user_id = member.id
            username = member.username or member.first_name
            
            # 检查用户是否已注册
            user = db_service.get_user(user_id)
            if not user:
                # 创建新用户
                db_service.create_user(user_id, username)
            else:
                # 更新用户名
                db_service.update_username(user_id, username)
            
            # 添加用户到群组关联
            db_service.add_user_to_group(user_id, message.chat.id)

async def handle_text_message(client, message):
    """处理文本消息"""
    # 过滤命令消息
    if message.text.startswith('/'):
        return
        
    # 检查群组是否已授权
    if not admin_service.is_group_authorized(message.chat.id):
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # 在消息处理前检查用户是否存在
    user = db_service.get_user(user_id)
    if not user:
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        full_name = (first_name + " " + last_name).strip()
        username = full_name or message.from_user.username or "无名修士"
        db_service.create_user(user_id, username, first_name, last_name)
    
    # 确保用户有修仙记录
    cultivation = cultivation_service.get_user_cultivation(user_id)
    if not cultivation:
        db_service.initialize_user_cultivation(user_id)
    
    # 检查消息中是否包含"奶龙"，如果包含则触发AI回复
    if "奶龙" in message.text:
        asyncio.create_task(ai_direct_reply(client, message))
    
    # 检查用户是否是地仙（飞升成功），处理每日首次发言
    is_immortal = db_service.is_immortal(user_id)
    if is_immortal:
        # 判断是否为今日首次发言
        if not db_service.check_immortal_daily_chat(user_id):
            # 记录地仙已发言
            db_service.mark_immortal_greeted(user_id)
            
            # 获取用户全名
            first_name = message.from_user.first_name or ""
            last_name = message.from_user.last_name or ""
            user_full_name = (first_name + " " + last_name).strip() or message.from_user.username or "道友"
            
            # 发送欢迎语
            await welcome_immortal(client, message, user_full_name)
    
    # 处理文本内容（异步，不阻塞）
    asyncio.create_task(process_text_message(user_id, message))

async def ai_random_reply(client, chat_id):
    """AI随机乱入群聊"""
    try:
        # 获取最近的消息记录
        recent_messages = group_messages[chat_id]
        if not recent_messages:
            return
        
        # 构建上下文（最近30条消息）
        context = "\n".join([f"{msg['username']}: {msg['text']}" for msg in recent_messages])
        
        # 添加提示语，增强个性化和幽默感
        prompt = f"""以下是一个群聊中的最近消息，请你作为'奶龙'给出一个有趣的回复。

你是一只活泼、机智、略带傲娇的小女孩，自称'奶龙'。你说话风格幽默诙谐，偶尔卖萌，喜欢用可爱的语气词和表情，但也会适当展示自己的智慧。

回复要求：
1. 直接参与话题，不要做自我介绍
2. 言简意赅，长度控制在2-3句话
3. 加入适当的情绪和个性，如调皮、惊讶、好奇等
4. 可以偶尔加入"哼~"、"嘿嘿"、"呜~"、"喵"等可爱语气词
5. 偶尔可以用第三人称表达，如"奶龙表示很赞同"
6. 根据聊天内容进行幽默回应，可以调侃但不要刻意讽刺
7. 不要自我介绍，就像一个真实的角色一样自然对话
聊天记录：
{context}"""
        
        # 调用AI服务
        from bot.services.ai_service import ai_service
        thinking_msg = await client.send_message(chat_id, "🧠 思考中...")
        
        # 使用系统用户ID，无需真实用户名
        result = await ai_service.ask(0, prompt)  # 使用0作为系统用户ID
        
        # 删除"思考中"提示
        try:
            await thinking_msg.delete()
        except:
            pass
        
        # 发送AI回复，随机选择龙相关的emoji
        dragon_emojis = ["🐲", "🐉", "✨", "🔮", "💫", "🌟", "💭", "🧠"]
        emoji = random.choice(dragon_emojis)
        
        if result["success"]:
            await client.send_message(chat_id, f"{emoji} {result['message']}")
        else:
            print(f"AI乱入回复失败: {result['message']}")
    except Exception as e:
        print(f"AI乱入回复出错: {e}")
        import traceback
        print(traceback.format_exc())

async def process_text_message(user_id, message):
    """异步处理文本消息内容"""
    try:
        # 加1分作为水群奖励
        db_service.update_points(user_id, 1)
        
        # 处理可能的随机事件
        event = cultivation_service.process_message(user_id, message.text)
        
        # 如果触发了事件，发送通知
        if event and event['message']:
            await message.reply(event['message'])
    except Exception as e:
        print(f"处理消息时出错: {e}")
        # 不向用户显示错误，只在后台记录，避免影响用户体验

async def handle_document(client, message):
    """处理文档（书籍上传）"""
    # 检查群组是否已授权
    if not admin_service.is_group_authorized(message.chat.id):
        return
    
    # 获取文件信息
    if not message.document:
        return
    
    document = message.document
    file_name = document.file_name
    file_id = document.file_id
    
    # 检查文件类型是否允许
    if not any(file_name.lower().endswith(ext) for ext in ALLOWED_EXTENSIONS):
        return
    
    # 获取消息发送者信息
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    
    # 检查用户是否已注册
    user = db_service.get_user(user_id)
    if not user:
        db_service.create_user(user_id, username)
    
    # 初始化用户的处理队列
    if user_id not in processing_queue:
        processing_queue[user_id] = []
    
    # 创建异步任务处理文件（立即启动而不等待）
    task = asyncio.create_task(
        process_file_task(client, message, file_id, file_name, user_id, username)
    )
    
    # 添加到用户队列
    processing_queue[user_id].append(task)
    
    # 清理已完成的任务
    processing_queue[user_id] = [t for t in processing_queue[user_id] if not t.done()]

# 添加命令处理器装饰器，确保命令处理优先进行
def with_command_priority(func):
    """装饰器，确保命令处理函数获得优先级"""
    async def wrapper(client, message):
        async with command_semaphore:
            return await func(client, message)
    return wrapper

# 注册消息处理器
def register_message_handlers(app):
    """注册所有消息处理器"""
    app.add_handler(MessageHandler(handle_new_member, filters.new_chat_members))
    app.add_handler(MessageHandler(handle_text_message, filters.text))
    app.add_handler(MessageHandler(handle_document, filters.document)) 

# 添加新函数用于直接回复用户消息
async def ai_direct_reply(client, message):
    """AI随机直接回复用户的消息"""
    try:
        # 获取用户姓名
        first_name = message.from_user.first_name
        last_name = message.from_user.last_name
        
        # 构建提示
        prompt = f"""用户说: {message.text}
        
请你作为'奶龙'给出一个直接针对这条消息的有趣回复。
        
你是一只活泼、机智、略带傲娇的小龙，自称'奶龙'。你说话风格幽默诙谐，偶尔卖萌，喜欢用可爱的语气词和表情，但也会适当展示自己的智慧。
        
回复要求：
1. 直接回应这条消息，好像被触发了兴趣一样
2. 言简意赅，长度控制在1-2句话
3. 加入适当的情绪和个性，如调皮、惊讶、好奇等
4. 可以偶尔加入"哼~"、"嘿嘿"、"呜~"等可爱语气词
5. 像是忍不住插嘴一样，自然地加入对话"""
        
        # 调用AI服务
        from bot.services.ai_service import ai_service
        thinking_msg = await message.reply("🧠 思考中...")
        
        result = await ai_service.ask(0, prompt, first_name=first_name, last_name=last_name)  # 使用0作为系统用户ID
        
        # 删除"思考中"提示
        try:
            await thinking_msg.delete()
        except:
            pass
        
        # 随机选择龙相关的emoji
        dragon_emojis = ["🐲", "🐉", "✨", "🔮", "💫", "🌟", "💭", "👀"]
        emoji = random.choice(dragon_emojis)
                        
        # 发送回复
        if result["success"]:
            await message.reply(f"{emoji} {result['message']}")
        else:
            print(f"AI直接回复失败: {result['message']}")
    except Exception as e:
        print(f"AI直接回复出错: {e}")
        import traceback
        print(traceback.format_exc())

async def welcome_immortal(client, message, user_full_name):
    """欢迎地仙用户的每日首次发言"""
    try:
        # 构建欢迎提示语
        prompt = f"""作为书群管理员，你需要热情欢迎一位地仙境界的修士"{user_full_name}"今日首次现身。
        
请生成一个优雅、富有仙气的欢迎语，要求：
1. 简短精炼，2-3句话
2. 带有道教和修仙元素
3. 称呼对方为"仙尊"或类似尊称
4. 体现出对方超凡脱俗的地位
5. 可以适当加入一些祥瑞意象，如祥云、仙鹤、瑞气等
6. 结尾可以加入"群内修士见过仙尊"之类的敬语

回复格式要简洁，直接给出欢迎语，无需额外解释。"""

        # 调用AI服务生成欢迎语
        from bot.services.ai_service import ai_service
        result = await ai_service.ask(0, prompt)  # 使用系统用户ID
        
        if result["success"]:
            # 随机选择一些仙气emoji
            immortal_emojis = ["✨", "🌟", "☁️", "🌈", "🔮", "🌌", "🏯", "🏔️", "🧙"]
            emoji = random.choice(immortal_emojis)
            welcome_text = f"{emoji} {result['message']}"
            
            # 发送欢迎消息
            await message.reply(welcome_text)
        else:
            # 使用默认欢迎语
            await message.reply(f"✨ 祥云缭绕，仙气盈门！恭迎{user_full_name}仙尊驾临群内，群中修士速来参拜！")
    except Exception as e:
        print(f"欢迎地仙用户时发生错误: {e}")
        import traceback
        print(traceback.format_exc()) 

async def handle_message(client, message):
    """处理普通消息"""
    # 忽略删除的消息
    if not hasattr(message, 'text') or message.text is None:
        return
    
    # 忽略命令消息
    if message.text.startswith('/'):
        return
    
    user_id = message.from_user.id
    chat_id = message.chat.id
    
    # 检查用户是否存在
    user = db_service.get_user(user_id)
    if not user:
        first_name = message.from_user.first_name or ""
        last_name = message.from_user.last_name or ""
        full_name = (first_name + " " + last_name).strip()
        username = full_name or message.from_user.username or "无名修士"
        db_service.create_user(user_id, username, first_name, last_name)
    
    # 确保用户有修仙记录
    cultivation = cultivation_service.get_user_cultivation(user_id)
    if not cultivation:
        db_service.initialize_user_cultivation(user_id)
    
    # 处理随机事件
    event_result = cultivation_service.process_message(user_id, message.text)
    if event_result: 
        # 如果触发了事件，发送通知
        if 'message' in event_result and event_result['message']:
            await message.reply(event_result['message']) 