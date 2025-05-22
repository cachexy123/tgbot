from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.handlers import MessageHandler
from bot.services.admin_service import admin_service
from bot.services.db_service import db_service
from datetime import datetime
import os
import glob
import math
import asyncio
import re
from typing import List, Dict
from pyrogram.enums import ChatType
import time

# 自动删除消息的辅助函数
async def auto_delete_messages(messages, delay=10):
    """延迟一定时间后删除消息
    
    Args:
        messages: 单个消息或消息列表
        delay: 延迟时间(秒)
    """
    if not isinstance(messages, list):
        messages = [messages]
    
    await asyncio.sleep(delay)
    
    for message in messages:
        try:
            await message.delete()
        except Exception as e:
            print(f"删除消息失败: {e}")

# 进度回调函数
async def progress_callback(current, total, status_message, file_name, start_time):
    """显示文件下载进度
    
    Args:
        current: 当前已下载的字节数
        total: 文件总字节数
        status_message: 用于更新的状态消息
        file_name: 文件名称
        start_time: 开始时间
    """
    # 防止除零错误
    if total <= 0:
        total = 1  # 避免除零错误
    
    # 计算百分比
    percent = current * 100 / total
    
    # 计算速度
    elapsed_time = time.time() - start_time
    if elapsed_time == 0:
        elapsed_time = 0.1  # 避免除零错误
    speed = current / elapsed_time
    
    # 格式化速度
    if speed < 1024:
        speed_text = f"{speed:.2f} B/s"
    elif speed < 1024 * 1024:
        speed_text = f"{speed/1024:.2f} KB/s"
    else:
        speed_text = f"{speed/(1024*1024):.2f} MB/s"
    
    # 每5%更新一次消息，避免频繁更新
    if current == total or percent % 5 < 0.1 or current == 0:
        try:
            await status_message.edit_text(
                f"⏳ 正在下载 {file_name}...\n"
                f"进度: {current}/{total} 字节 ({percent:.1f}%)\n"
                f"速度: {speed_text}"
            )
        except Exception as e:
            print(f"更新进度消息失败: {e}")

# 精品书籍存储路径
PREMIUM_BOOKS_DIR = 'shu'
# 每页显示的书籍数量
BOOKS_PER_PAGE = 10
# 兑换书籍的积分成本
BOOK_EXCHANGE_COST = 2000
# 上传书籍奖励积分
BOOK_UPLOAD_REWARD = 2000

# 确保书籍目录存在
if not os.path.exists(PREMIUM_BOOKS_DIR):
    os.makedirs(PREMIUM_BOOKS_DIR)

# 保存管理员上传会话状态
# user_id -> {status: "uploading"/"waiting_user_id", uploaded_books: []}
admin_upload_sessions = {}

# 文件下载锁，防止并发问题
download_lock = asyncio.Lock()

# 清理文件名，去除特殊字符
def clean_filename(filename):
    # 删除文件扩展名
    name, ext = os.path.splitext(filename)
    # 移除无效的文件名字符，只保留字母、数字、中文、下划线、短横线和空格
    cleaned_name = re.sub(r'[^\w\s\u4e00-\u9fff-]', '', name)
    # 将空格替换为下划线
    cleaned_name = re.sub(r'\s+', '_', cleaned_name)
    # 如果清理后文件名为空，使用默认名称
    if not cleaned_name:
        cleaned_name = "book"
    # 限制文件名长度，避免过长
    if len(cleaned_name) > 50:
        cleaned_name = cleaned_name[:50]
    return cleaned_name + ext

# 上传精品书籍 - 开始上传会话
async def upload_premium_book(client, message):
    """处理/upload命令，开始上传精品书籍会话"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        reply = await message.reply("⚠️ 只有管理员才能执行此操作")
        # 5秒后自动删除
        await auto_delete_messages([message, reply], 5)
        return
    
    # 创建或重置上传会话
    admin_upload_sessions[user_id] = {
        "status": "uploading",
        "uploaded_books": []
    }
    
    # 发送开始上传的消息
    reply = await message.reply(
        "📚 请开始上传书籍...\n"
        "• 直接发送文件即可\n"
        "• 可以上传多本书籍\n"
        "• 上传完成后，请发送 /done 命令"
    )
    
    # 自动删除命令消息，但保留回复
    await auto_delete_messages(message, 5)

# 处理群组中的/upload命令
async def group_upload_command(client, message):
    """处理群组中的/upload命令"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if admin_service.is_admin(user_id):
        reply = await message.reply("⚠️ 请在私聊中使用此命令上传书籍")
    else:
        reply = await message.reply("⚠️ 你不是管理员，管理员请在私聊中使用此命令")
    
    # 5秒后自动删除命令和回复
    await auto_delete_messages([message, reply], 5)

# 处理管理员上传的文件
async def handle_admin_file_upload(client, message):
    """处理管理员上传的文件"""
    user_id = message.from_user.id
    
    # 检查是否有活跃的上传会话
    if user_id not in admin_upload_sessions or admin_upload_sessions[user_id]["status"] != "uploading":
        return  # 没有活跃会话，忽略
    
    # 获取文件信息
    if not message.document:
        return  # 不是文件，忽略
    
    document = message.document
    file_name = document.file_name
    file_id = document.file_id
    
    # 生成新文件名：书名+日期
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_name = clean_filename(file_name)
    name_base, file_extension = os.path.splitext(clean_name)
    new_file_name = f"{name_base}_{timestamp}{file_extension}"
    file_path = os.path.join(PREMIUM_BOOKS_DIR, new_file_name)
    
    # 通知用户
    status_message = await message.reply(f"⏳ 准备下载 {file_name}...")
    
    try:
        # 记录开始时间
        start_time = time.time()
        
        # 下载文件，使用进度回调来更新状态
        await client.download_media(
            message=file_id, 
            file_name=file_path,
            progress=progress_callback,
            progress_args=(status_message, file_name, start_time)
        )
        
        # 创建书籍信息文件
        info_file_path = os.path.join(PREMIUM_BOOKS_DIR, f"{name_base}_{timestamp}.info")
        with open(info_file_path, 'w', encoding='utf-8') as f:
            f.write(f"原始文件名: {file_name}\n")
            f.write(f"上传时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"上传者ID: {user_id}\n")
            f.write(f"文件大小: {document.file_size} 字节\n")
        
        # 更新状态消息
        await status_message.edit_text(f"✅ 书籍 {file_name} 上传成功！\n存储为: {new_file_name}")
        
        # 添加到上传会话中
        admin_upload_sessions[user_id]["uploaded_books"].append({
            "original_name": file_name,
            "new_name": new_file_name,
            "size": document.file_size
        })
        
        # 向所有授权群组发送新书通知
        try:
            # 格式化文件大小
            size_mb = document.file_size / (1024 * 1024)
            file_size_str = f"{size_mb:.2f} MB"
            
            # 获取所有授权群组
            authorized_groups = db_service.get_all_authorized_groups()
            
            # 构建通知消息
            notification_text = f"📚 书单新入一本书：{file_name} {file_size_str}"
            
            # 发送到所有授权群组
            for group in authorized_groups:
                try:
                    await client.send_message(group['group_id'], notification_text)
                except Exception as e:
                    print(f"向群组 {group['group_name']} 发送新书通知失败: {e}")
        except Exception as e:
            print(f"发送群组新书通知失败: {e}")
        
    except Exception as e:
        # 上传失败
        await status_message.edit_text(f"❌ 上传失败: {str(e)}")

# 处理上传完成命令
async def done_upload_command(client, message):
    """处理/done命令，完成上传会话"""
    user_id = message.from_user.id
    print(f"收到/done命令，用户ID: {user_id}")
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        print(f"用户{user_id}不是管理员")
        return await message.reply("⚠️ 只有管理员才能执行此操作")
    
    # 检查是否在私聊
    print(f"聊天类型: {message.chat.type}")
    if message.chat.type != ChatType.PRIVATE:
        print(f"不是私聊环境: {message.chat.type}")
        return await message.reply("⚠️ 请在私聊中使用此命令")
    
    print(f"当前上传会话状态: {admin_upload_sessions.get(user_id, '无')}")
    
    # 检查是否有活跃的上传会话
    if user_id not in admin_upload_sessions:
        print(f"用户{user_id}没有活跃的上传会话")
        return await message.reply("⚠️ 没有活跃的上传会话，请先使用 /upload 命令开始上传")
    
    if admin_upload_sessions[user_id]["status"] != "uploading":
        print(f"用户{user_id}的会话状态不是uploading: {admin_upload_sessions[user_id]['status']}")
        return await message.reply("⚠️ 当前会话状态不正确，请重新使用 /upload 命令开始上传")
    
    # 检查是否有上传的书籍
    if not admin_upload_sessions[user_id]["uploaded_books"]:
        print(f"用户{user_id}没有上传任何书籍")
        admin_upload_sessions.pop(user_id)  # 清除空会话
        return await message.reply("⚠️ 您没有上传任何书籍，会话已取消")
    
    # 显示上传统计
    uploaded_count = len(admin_upload_sessions[user_id]["uploaded_books"])
    total_reward = uploaded_count * BOOK_UPLOAD_REWARD
    
    summary_text = (
        f"📚 上传完成！共上传 {uploaded_count} 本书籍\n\n"
        f"每本奖励 {BOOK_UPLOAD_REWARD} 灵石\n"
        f"总奖励 {total_reward} 灵石\n\n"
    )
    
    for i, book in enumerate(admin_upload_sessions[user_id]["uploaded_books"], 1):
        summary_text += f"{i}. {book['original_name']}\n"
    
    summary_text += "\n请输入要奖励的用户ID："
    print(f"准备发送上传总结: {summary_text}")
    
    # 更新会话状态为等待用户ID
    admin_upload_sessions[user_id]["status"] = "waiting_user_id"
    
    try:
        await message.reply(summary_text)
        print("发送上传总结成功")
    except Exception as e:
        print(f"发送上传总结失败: {str(e)}")
        # 尝试再次发送
        try:
            await client.send_message(chat_id=user_id, text=summary_text)
            print("使用另一种方式发送成功")
        except Exception as e:
            print(f"再次发送失败: {str(e)}")

# 处理管理员输入的用户ID
async def handle_reward_user_id(client, message):
    """处理管理员输入的用户ID"""
    admin_id = message.from_user.id
    print(f"收到可能的用户ID输入: {message.text}，来自管理员: {admin_id}")
    
    # 检查是否是管理员
    if not admin_service.is_admin(admin_id):
        print(f"用户{admin_id}不是管理员")
        return
    
    # 检查是否在私聊
    if message.chat.type != ChatType.PRIVATE:
        print(f"不是私聊环境: {message.chat.type}")
        return
    
    print(f"当前会话状态: {admin_upload_sessions.get(admin_id, '无')}")
    
    # 检查是否有等待用户ID的会话
    if admin_id not in admin_upload_sessions:
        print(f"管理员{admin_id}没有活跃的会话")
        return
    
    if admin_upload_sessions[admin_id]["status"] != "waiting_user_id":
        print(f"管理员{admin_id}的会话状态不是waiting_user_id: {admin_upload_sessions[admin_id]['status']}")
        return
    
    # 获取用户ID
    try:
        target_user_id = int(message.text.strip())
        print(f"解析的目标用户ID: {target_user_id}")
    except ValueError:
        print(f"输入的不是有效数字: {message.text}")
        return await message.reply("⚠️ 无效的用户ID，请输入一个数字")
    
    # 检查用户是否存在
    print(f"正在检查用户 {target_user_id} 是否存在")
    target_user = db_service.get_user(target_user_id)
    if not target_user:
        print(f"用户 {target_user_id} 不存在")
        return await message.reply(f"⚠️ 用户 {target_user_id} 不存在")
    
    print(f"用户存在: {target_user}")
    
    # 计算奖励积分
    uploaded_count = len(admin_upload_sessions[admin_id]["uploaded_books"])
    total_reward = uploaded_count * BOOK_UPLOAD_REWARD
    
    print(f"准备奖励积分: {total_reward}，书籍数量: {uploaded_count}")
    
    # 给用户增加积分
    try:
        new_points = db_service.update_points(target_user_id, total_reward)
        print(f"已成功增加积分，用户新积分: {new_points}")
        
        # 构建奖励消息
        reward_text = (
            f"✅ 成功为用户 {target_user['username']} (ID: {target_user_id}) 增加了 {total_reward} 灵石！\n"
            f"• 上传书籍数量: {uploaded_count} 本\n"
            f"• 每本奖励: {BOOK_UPLOAD_REWARD} 灵石\n"
            f"• 用户当前灵石: {new_points} 个"
        )
        
        # 清除会话
        admin_upload_sessions.pop(admin_id)
        print(f"已清除管理员会话")
        
        await message.reply(reward_text)
        print("成功发送奖励消息")
    except Exception as e:
        print(f"奖励积分失败: {str(e)}")
        return await message.reply(f"⚠️ 奖励积分失败: {str(e)}")

# 获取精品书籍列表
def get_premium_books() -> List[Dict]:
    """获取所有精品书籍信息"""
    books = []
    
    # 获取所有书籍文件
    book_files = glob.glob(os.path.join(PREMIUM_BOOKS_DIR, "*.*"))
    for file_path in book_files:
        # 排除.info文件
        if file_path.endswith('.info'):
            continue
        
        # 获取文件名（不含路径）
        file_name = os.path.basename(file_path)
        # 获取文件大小
        file_size = os.path.getsize(file_path)
        # 获取对应的信息文件
        info_file = os.path.splitext(file_path)[0] + '.info'
        
        original_name = file_name
        
        # 如果有信息文件，读取原始文件名
        if os.path.exists(info_file):
            with open(info_file, 'r', encoding='utf-8') as f:
                info_content = f.read()
                for line in info_content.splitlines():
                    if line.startswith("原始文件名:"):
                        original_name = line.split(":", 1)[1].strip()
                        break
        
        books.append({
            'filename': file_name,
            'original_name': original_name,
            'size': file_size,
            'path': file_path
        })
    
    # 按上传时间排序（文件名中包含时间戳）
    books.sort(key=lambda x: x['filename'], reverse=True)
    
    # 处理同名书籍，添加编号
    book_count = {}  # 用于记录每个书名出现的次数
    book_index = {}  # 用于记录每个书名当前的编号
    
    # 第一次遍历，统计每个书名出现的次数
    for book in books:
        name = book['original_name']
        if name in book_count:
            book_count[name] += 1
        else:
            book_count[name] = 1
    
    # 第二次遍历，添加编号
    for book in books:
        name = book['original_name']
        # 只有当同名书籍多于1本时才添加编号
        if book_count[name] > 1:
            # 初始化或增加编号
            if name not in book_index:
                book_index[name] = 1
            else:
                book_index[name] += 1
            # 添加编号到原始名称中
            book['display_name'] = f"{name} (#{book_index[name]})"
        else:
            book['display_name'] = name
    
    return books

# 列出精品书籍
async def list_premium_books(client, message):
    """处理/list命令，列出精品书籍"""
    user_id = message.from_user.id
    
    # 检查是否是管理员，普通用户也可以查看
    is_admin = admin_service.is_admin(user_id)
    
    # 获取书籍列表
    books = get_premium_books()
    
    if not books:
        reply = await message.reply("📚 精品书籍库为空")
        # 如果在群组中，5秒后自动删除
        if message.chat.type != ChatType.PRIVATE:
            await auto_delete_messages([message, reply], 5)
        return
    
    # 获取页码参数
    command_parts = message.text.split()
    page = 1
    if len(command_parts) > 1:
        try:
            page = int(command_parts[1])
        except ValueError:
            page = 1
    
    # 计算总页数
    total_pages = math.ceil(len(books) / BOOKS_PER_PAGE)
    
    # 确保页码有效
    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages
    
    # 获取当前页的书籍
    start_idx = (page - 1) * BOOKS_PER_PAGE
    end_idx = start_idx + BOOKS_PER_PAGE
    current_page_books = books[start_idx:end_idx]
    
    # 构建显示文本
    reply_text = f"📚 精品书籍列表 (第 {page}/{total_pages} 页)\n\n"
    
    for idx, book in enumerate(current_page_books, start=1):
        # 格式化文件大小
        size_mb = book['size'] / (1024 * 1024)
        file_size_str = f"{size_mb:.2f} MB"
        
        # 提取上传时间
        timestamp_match = re.search(r'_(\d{8}_\d{6})', book['filename'])
        upload_time = ""
        if timestamp_match:
            time_str = timestamp_match.group(1)
            upload_time = time_str[:8]  # 只取日期部分 YYYYMMDD
            try:
                # 格式化为更易读的形式: YYYY-MM-DD
                upload_time = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]}"
            except:
                pass
        
        # 使用新格式：书名 大小, 上传时间
        reply_text += f"{idx}. `{book['display_name']}` {file_size_str}, {upload_time}\n\n"
    
    # 添加分页按钮
    buttons = []
    
    # 上一页按钮
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"book_list_{page-1}"))
    
    # 下一页按钮
    if page < total_pages:
        buttons.append(InlineKeyboardButton("下一页 ▶️", callback_data=f"book_list_{page+1}"))
    
    # 如果有按钮，则创建行
    if buttons:
        keyboard = InlineKeyboardMarkup([buttons])
    else:
        keyboard = None
    
    # 管理员提示
    if is_admin:
        reply_text += "\n管理员可以使用 /upload 上传精品书籍"
    
    # 普通用户提示 - 根据是群聊还是私聊显示不同提示
    if message.chat.type == ChatType.PRIVATE:
        reply_text += "\n使用 /huan [书名] 兑换书籍 (花费 2000 灵石)"
    else:
        reply_text += "\n在群组中使用 /huan [书名] 或私聊机器人兑换书籍 (花费 2000 灵石)"
    
    # 发送消息
    reply = await message.reply(reply_text, reply_markup=keyboard)
    
    # 如果在群组中，自动删除命令和回复
    if message.chat.type != ChatType.PRIVATE:
        await auto_delete_messages([message, reply], 30)  # 30秒后删除

# 处理书籍列表翻页回调
async def handle_book_list_callback(client, callback_query):
    """处理书籍列表的翻页回调"""
    try:
        # 获取页码
        parts = callback_query.data.split('_')
        if len(parts) < 3:
            await callback_query.answer("⚠️ 无效的请求数据")
            return
            
        page = int(parts[2])
        
        # 获取书籍列表
        books = get_premium_books()
        
        if not books:
            await callback_query.answer("📚 精品书籍库为空")
            return
        
        # 计算总页数
        total_pages = math.ceil(len(books) / BOOKS_PER_PAGE)
        
        # 确保页码有效
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        
        # 获取当前页的书籍
        start_idx = (page - 1) * BOOKS_PER_PAGE
        end_idx = start_idx + BOOKS_PER_PAGE
        current_page_books = books[start_idx:end_idx]
        
        # 检查用户是否是管理员
        user_id = callback_query.from_user.id
        is_admin = admin_service.is_admin(user_id)
        
        # 构建显示文本
        reply_text = f"📚 精品书籍列表 (第 {page}/{total_pages} 页)\n\n"
        
        for idx, book in enumerate(current_page_books, start=1):
            # 格式化文件大小
            size_mb = book['size'] / (1024 * 1024)
            file_size_str = f"{size_mb:.2f} MB"
            
            # 提取上传时间
            timestamp_match = re.search(r'_(\d{8}_\d{6})', book['filename'])
            upload_time = ""
            if timestamp_match:
                time_str = timestamp_match.group(1)
                upload_time = time_str[:8]  # 只取日期部分 YYYYMMDD
                try:
                    # 格式化为更易读的形式: YYYY-MM-DD
                    upload_time = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]}"
                except:
                    pass
            
            # 使用新格式：书名 大小, 上传时间
            reply_text += f"{idx}. `{book['display_name']}` {file_size_str}, {upload_time}\n\n"
        
        # 添加分页按钮
        buttons = []
        
        # 上一页按钮
        if page > 1:
            buttons.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"book_list_{page-1}"))
        
        # 下一页按钮
        if page < total_pages:
            buttons.append(InlineKeyboardButton("下一页 ▶️", callback_data=f"book_list_{page+1}"))
        
        # 如果有按钮，则创建行
        if buttons:
            keyboard = InlineKeyboardMarkup([buttons])
        else:
            keyboard = None
        
        # 管理员提示
        if is_admin:
            reply_text += "\n管理员可以使用 /upload 上传精品书籍"
        
        # 普通用户提示 - 根据是群聊还是私聊显示不同提示
        if callback_query.message.chat.type == ChatType.PRIVATE:
            reply_text += "\n使用 /huan [书名] 兑换书籍 (花费 2000 灵石)"
        else:
            reply_text += "\n在群组中使用 /huan [书名] 或私聊机器人兑换书籍 (花费 2000 灵石)"
        
        # 更新消息
        await callback_query.message.edit_text(reply_text, reply_markup=keyboard)
        await callback_query.answer()
    except Exception as e:
        print(f"翻页回调处理出错: {str(e)}")
        try:
            await callback_query.answer(f"翻页出错，请重试")
        except:
            pass

# 兑换精品书籍
async def exchange_premium_book(client, message):
    """处理/huan命令，兑换精品书籍"""
    user_id = message.from_user.id
    
    # 解析命令参数
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2:
        reply = await message.reply("⚠️ 请提供书名，格式: /huan [书名]")
        # 如果在群组中，5秒后自动删除
        if message.chat.type != ChatType.PRIVATE:
            await auto_delete_messages([message, reply], 5)
        return
    
    book_name = command_parts[1].strip()
    
    # 获取用户信息
    user = db_service.get_user(user_id)
    if not user:
        reply = await message.reply("⚠️ 您还未注册，请先使用 /start 命令注册")
        # 如果在群组中，5秒后自动删除
        if message.chat.type != ChatType.PRIVATE:
            await auto_delete_messages([message, reply], 5)
        return
    
    # 检查用户积分是否足够
    if user['points'] < BOOK_EXCHANGE_COST:
        reply = await message.reply(f"⚠️ 灵石不足！兑换精品书籍需要 {BOOK_EXCHANGE_COST} 灵石，您当前只有 {user['points']} 灵石")
        # 如果在群组中，5秒后自动删除
        if message.chat.type != ChatType.PRIVATE:
            await auto_delete_messages([message, reply], 5)
        return
    
    # 获取书籍列表
    books = get_premium_books()
    
    # 查找匹配的书籍
    found_book = None
    
    # 首先尝试精确匹配完整书名（包括编号）
    for book in books:
        if book_name.lower() == book['display_name'].lower():
            found_book = book
            break
    
    # 如果精确匹配不成功，尝试部分匹配
    if not found_book:
        # 检查是否包含编号格式 (#数字)
        number_match = re.search(r'\(#(\d+)\)', book_name)
        if number_match:
            # 提取书名和编号
            pure_name = book_name.split('(#')[0].strip()
            book_number = int(number_match.group(1))
            
            # 查找匹配书名和编号的书籍
            for book in books:
                book_number_match = re.search(r'\(#(\d+)\)', book['display_name'])
                if (book_number_match and 
                    pure_name.lower() in book['original_name'].lower() and
                    int(book_number_match.group(1)) == book_number):
                    found_book = book
                    break
        else:
            # 如果没有指定编号，使用常规包含匹配
            for book in books:
                if book_name.lower() in book['display_name'].lower():
                    found_book = book
                    break
    
    if not found_book:
        reply = await message.reply(f"⚠️ 未找到书籍: {book_name}\n请使用 /list 命令查看可用的书籍")
        # 如果在群组中，5秒后自动删除
        if message.chat.type != ChatType.PRIVATE:
            await auto_delete_messages([message, reply], 5)
        return
    
    # 先扣除积分
    new_points = db_service.update_points(user_id, -BOOK_EXCHANGE_COST)
    
    # 发送状态消息
    status_message = await message.reply(f"⏳ 正在准备发送书籍: {found_book['display_name']}...")
    
    try:
        # 在群组中使用时，私聊发送书籍
        if message.chat.type != ChatType.PRIVATE:
            # 先通知群组
            await status_message.edit_text(f"✅ 书籍准备就绪，请查看私聊消息获取书籍")
            
            # 私聊发送文件
            await client.send_document(
                chat_id=user_id,
                document=found_book['path'],
                file_name=found_book['original_name'],
                caption=f"📚 您在群组中兑换的精品书籍!\n消费: {BOOK_EXCHANGE_COST} 灵石\n剩余灵石: {new_points}"
            )
            
            # 私聊发送提示
            await client.send_message(
                chat_id=user_id,
                text=f"这是您在群组「{message.chat.title}」中兑换的书籍"
            )
            
            # 群组中自动删除命令和状态消息
            await auto_delete_messages([message, status_message], 15)
        else:
            # 私聊直接发送
            await client.send_document(
                chat_id=user_id,
                document=found_book['path'],
                file_name=found_book['original_name'],
                caption=f"📚 您已成功兑换精品书籍!\n消费: {BOOK_EXCHANGE_COST} 灵石\n剩余灵石: {new_points}"
            )
            
            # 更新状态消息
            await status_message.edit_text(f"✅ 书籍发送成功: {found_book['display_name']}")
    except Exception as e:
        # 失败时退还积分
        db_service.update_points(user_id, BOOK_EXCHANGE_COST)
        
        # 更新状态消息
        await status_message.edit_text(f"❌ 书籍发送失败: {str(e)}\n已退还 {BOOK_EXCHANGE_COST} 灵石")
        
        # 如果在群组中，失败后也自动删除
        if message.chat.type != ChatType.PRIVATE:
            await auto_delete_messages([message, status_message], 15)

# 注册精品书籍相关的处理器
def register_book_handlers(app):
    """注册精品书籍相关的处理器"""
    # 命令处理器
    app.add_handler(MessageHandler(upload_premium_book, filters.command("upload") & filters.private))
    app.add_handler(MessageHandler(group_upload_command, filters.command("upload") & filters.group))
    app.add_handler(MessageHandler(done_upload_command, filters.command("done") & filters.private))
    app.add_handler(MessageHandler(list_premium_books, filters.command("list")))
    app.add_handler(MessageHandler(exchange_premium_book, filters.command("huan")))
    app.add_handler(MessageHandler(search_premium_books, filters.command("sou")))
    
    # 文件和文本处理器
    app.add_handler(MessageHandler(
        handle_admin_file_upload, 
        filters.private & filters.document & filters.create(lambda _, __, m: not m.command)
    ))
    app.add_handler(MessageHandler(
        handle_reward_user_id,
        filters.private & filters.text & filters.create(lambda _, __, m: 
            not m.command and m.from_user and m.from_user.id in admin_upload_sessions and 
            admin_upload_sessions[m.from_user.id]["status"] == "waiting_user_id"
        )
    ))
    
    # 回调查询处理器
    from pyrogram.handlers import CallbackQueryHandler
    app.add_handler(CallbackQueryHandler(handle_book_list_callback, filters.regex("^book_list_")))
    app.add_handler(CallbackQueryHandler(handle_book_search_callback, filters.regex("^book_search_")))

# 搜索精品书籍
async def search_premium_books(client, message):
    """处理/sou命令，搜索精品书籍"""
    # 提取搜索关键词
    command_parts = message.text.split(' ', 1)
    if len(command_parts) < 2 or not command_parts[1].strip():
        reply = await message.reply("⚠️ 请提供搜索关键词，格式: /sou [关键词]")
        # 如果在群组中，5秒后自动删除
        if message.chat.type != ChatType.PRIVATE:
            await auto_delete_messages([message, reply], 5)
        return
    
    search_term = command_parts[1].strip().lower()
    
    # 获取所有书籍
    all_books = get_premium_books()
    
    # 过滤匹配的书籍
    matching_books = []
    for book in all_books:
        if (search_term in book['display_name'].lower() or 
            search_term in book['original_name'].lower()):
            matching_books.append(book)
    
    if not matching_books:
        reply = await message.reply(f"📚 未找到包含关键词 \"{search_term}\" 的书籍")
        # 如果在群组中，5秒后自动删除
        if message.chat.type != ChatType.PRIVATE:
            await auto_delete_messages([message, reply], 5)
        return
    
    # 计算总页数
    total_pages = math.ceil(len(matching_books) / BOOKS_PER_PAGE)
    page = 1
    
    # 获取当前页的书籍
    start_idx = (page - 1) * BOOKS_PER_PAGE
    end_idx = start_idx + BOOKS_PER_PAGE
    current_page_books = matching_books[start_idx:end_idx]
    
    # 构建显示文本
    reply_text = f"📚 搜索结果: \"{search_term}\" (第 {page}/{total_pages} 页)\n"
    reply_text += f"找到 {len(matching_books)} 本相关书籍\n\n"
    
    for idx, book in enumerate(current_page_books, start=1):
        # 格式化文件大小
        size_mb = book['size'] / (1024 * 1024)
        file_size_str = f"{size_mb:.2f} MB"
        
        # 提取上传时间
        timestamp_match = re.search(r'_(\d{8}_\d{6})', book['filename'])
        upload_time = ""
        if timestamp_match:
            time_str = timestamp_match.group(1)
            upload_time = time_str[:8]  # 只取日期部分 YYYYMMDD
            try:
                # 格式化为更易读的形式: YYYY-MM-DD
                upload_time = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]}"
            except:
                pass
        
        # 使用新格式：书名 大小, 上传时间
        reply_text += f"{idx}. `{book['display_name']}` {file_size_str}, {upload_time}\n\n"
    
    # 添加分页按钮
    buttons = []
    
    # 上一页按钮
    if page > 1:
        buttons.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"book_search_{page-1}_{search_term}"))
    
    # 下一页按钮
    if page < total_pages:
        buttons.append(InlineKeyboardButton("下一页 ▶️", callback_data=f"book_search_{page+1}_{search_term}"))
    
    # 如果有按钮，则创建行
    if buttons:
        keyboard = InlineKeyboardMarkup([buttons])
    else:
        keyboard = None
    
    # 添加提示
    reply_text += "\n使用 /huan [书名] 兑换书籍 (花费 2000 灵石)"
    
    # 发送消息
    reply = await message.reply(reply_text, reply_markup=keyboard)
    
    # 如果在群组中，30秒后自动删除
    if message.chat.type != ChatType.PRIVATE:
        await auto_delete_messages([message, reply], 30)

# 处理书籍搜索翻页回调
async def handle_book_search_callback(client, callback_query):
    """处理书籍搜索的翻页回调"""
    try:
        # 解析回调数据
        parts = callback_query.data.split('_')
        if len(parts) < 3:
            await callback_query.answer("⚠️ 无效的请求")
            return
            
        page = int(parts[2])
        search_term = '_'.join(parts[3:]) if len(parts) > 3 else ""
        
        # 获取所有书籍
        all_books = get_premium_books()
        
        # 过滤匹配的书籍
        matching_books = []
        for book in all_books:
            if (search_term.lower() in book['display_name'].lower() or 
                search_term.lower() in book['original_name'].lower()):
                matching_books.append(book)
        
        if not matching_books:
            await callback_query.answer("📚 未找到匹配的书籍")
            return
        
        # 计算总页数
        total_pages = math.ceil(len(matching_books) / BOOKS_PER_PAGE)
        
        # 确保页码有效
        if page < 1:
            page = 1
        if page > total_pages:
            page = total_pages
        
        # 获取当前页的书籍
        start_idx = (page - 1) * BOOKS_PER_PAGE
        end_idx = start_idx + BOOKS_PER_PAGE
        current_page_books = matching_books[start_idx:end_idx]
        
        # 构建显示文本
        reply_text = f"📚 搜索结果: \"{search_term}\" (第 {page}/{total_pages} 页)\n"
        reply_text += f"找到 {len(matching_books)} 本相关书籍\n\n"
        
        for idx, book in enumerate(current_page_books, start=1):
            # 格式化文件大小
            size_mb = book['size'] / (1024 * 1024)
            file_size_str = f"{size_mb:.2f} MB"
            
            # 提取上传时间
            timestamp_match = re.search(r'_(\d{8}_\d{6})', book['filename'])
            upload_time = ""
            if timestamp_match:
                time_str = timestamp_match.group(1)
                upload_time = time_str[:8]  # 只取日期部分 YYYYMMDD
                try:
                    # 格式化为更易读的形式: YYYY-MM-DD
                    upload_time = f"{time_str[:4]}-{time_str[4:6]}-{time_str[6:8]}"
                except:
                    pass
            
            # 使用新格式：书名 大小, 上传时间
            reply_text += f"{idx}. `{book['display_name']}` {file_size_str}, {upload_time}\n\n"
        
        # 添加分页按钮
        buttons = []
        
        # 上一页按钮
        if page > 1:
            buttons.append(InlineKeyboardButton("◀️ 上一页", callback_data=f"book_search_{page-1}_{search_term}"))
        
        # 下一页按钮
        if page < total_pages:
            buttons.append(InlineKeyboardButton("下一页 ▶️", callback_data=f"book_search_{page+1}_{search_term}"))
        
        # 如果有按钮，则创建行
        if buttons:
            keyboard = InlineKeyboardMarkup([buttons])
        else:
            keyboard = None
        
        # 添加提示
        reply_text += "\n使用 /huan [书名] 兑换书籍 (花费 2000 灵石)"
        
        # 更新消息
        await callback_query.message.edit_text(reply_text, reply_markup=keyboard)
        await callback_query.answer()
    except Exception as e:
        print(f"搜索翻页回调处理出错: {str(e)}")
        try:
            await callback_query.answer(f"翻页出错，请重试")
        except:
            pass 