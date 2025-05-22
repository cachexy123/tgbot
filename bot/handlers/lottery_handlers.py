from pyrogram import Client, filters
from pyrogram.types import Message
from pyrogram.enums import ChatType
from pyrogram.handlers import MessageHandler
from bot.services.lottery_service import lottery_service
from bot.services.admin_service import admin_service
from bot.services.db_service import db_service
from bot.utils.helpers import auto_delete, auto_delete_messages
import asyncio
import time

# 大乐透状态
lottery_status = {
    "is_active": False,
    "announcement_message_id": None,
    "result_message_id": None
}

# 启动大乐透
async def start_lottery(client, chat_id=None, force=False):
    """启动新一期大乐透
    
    Args:
        client: Pyrogram客户端
        chat_id: 指定的群组ID，如果不指定则发送到所有授权群组
        force: 是否强制启动，忽略活跃状态检查
    """
    global lottery_status
    
    # 检查是否已经有进行中的大乐透
    if lottery_status["is_active"] and not force:
        print("已经有进行中的大乐透，无法启动新的大乐透")
        return
    
    # 启动新的大乐透
    numbers = lottery_service.start_new_lottery()
    pool_amount = lottery_service.current_pool_amount
    
    # 生成公告消息
    announcement_text = (
        f"🎯 第{get_lottery_round_number()}期大乐透盛大开启！\n\n"
        f"💰 当前奖池总额: {pool_amount:,} 灵石\n\n"
        f"📋 游戏规则:\n"
        f"• 选择3个0-9之间的数字\n"
        f"• 使用命令 /le [三位数字] [注数] 参与\n"
        f"• 每注100灵石\n"
        f"• 猜中2位数字(按位置): 获得5,000灵石/注\n"
        f"• 猜中全部3位数字: 获得50,000灵石/注\n\n"
        f"⏰ 开奖时间: 今晚22:00\n"
        f"🍀 祝君好运！"
    )
    
    # 如果指定了群组ID，只发送到该群组
    if chat_id:
        try:
            # 发送公告并置顶
            message = await client.send_message(chat_id, announcement_text)
            await client.pin_chat_message(chat_id, message.id)
            
            # 保存消息ID
            lottery_status["announcement_message_id"] = message.id
            lottery_service.set_lottery_message_id(message.id)
            
            print(f"大乐透公告已发送到群组 {chat_id}，消息ID: {message.id}")
        except Exception as e:
            print(f"发送大乐透公告到群组 {chat_id} 失败: {e}")
    else:
        # 发送到所有授权群组
        groups = db_service.get_all_authorized_groups()
        for group in groups:
            try:
                # 发送公告并置顶
                message = await client.send_message(group["group_id"], announcement_text)
                await client.pin_chat_message(group["group_id"], message.id)
                
                # 保存第一个群组的消息ID
                if not lottery_status["announcement_message_id"]:
                    lottery_status["announcement_message_id"] = message.id
                    lottery_service.set_lottery_message_id(message.id)
                
                print(f"大乐透公告已发送到群组 {group['group_name']}，消息ID: {message.id}")
            except Exception as e:
                print(f"发送大乐透公告到群组 {group['group_name']} 失败: {e}")
    
    # 更新状态
    lottery_status["is_active"] = True
    
    # 保存中奖号码到日志（仅用于开发调试）
    print(f"本期大乐透中奖号码: {numbers}")

# 结束大乐透并开奖
async def end_lottery(client, chat_id=None):
    """结束大乐透并开奖
    
    Args:
        client: Pyrogram客户端
        chat_id: 指定的群组ID，如果不指定则发送到所有授权群组
    """
    global lottery_status
    
    # 检查是否有进行中的大乐透
    if not lottery_status["is_active"]:
        print("没有进行中的大乐透，无法开奖")
        return
    
    # 进行开奖
    result = lottery_service.draw_lottery()
    
    if not result["success"]:
        print(f"大乐透开奖失败: {result['message']}")
        return
    
    # 获取中奖号码和奖池
    winning_numbers = result["winning_numbers"]
    winners = result["winners"]
    total_reward = result["total_reward"]
    new_pool_amount = result["new_pool_amount"]
    
    # 构建开奖结果消息
    result_text = (
        f"🎊 第{get_lottery_round_number()}期大乐透开奖结果！\n\n"
        f"🔢 中奖号码: {winning_numbers}\n\n"
    )
    
    # 添加中奖信息
    if winners["first"] or winners["second"]:
        result_text += "🏆 中奖名单:\n\n"
        
        # 一等奖
        if winners["first"]:
            result_text += "✨ 一等奖 (三个数字全中):\n"
            for winner in winners["first"]:
                result_text += f"• {winner['username']}: {winner['numbers']} - {winner['bet_count']}注 - 获得{winner['reward']:,}灵石\n"
            result_text += "\n"
        
        # 二等奖
        if winners["second"]:
            result_text += "🌟 二等奖 (两个数字相同):\n"
            for winner in winners["second"]:
                result_text += f"• {winner['username']}: {winner['numbers']} - {winner['bet_count']}注 - 获得{winner['reward']:,}灵石\n"
            result_text += "\n"
    else:
        result_text += "💔 本期无人中奖\n\n"
    
    # 添加奖金信息
    result_text += (
        f"💰 本期派奖总额: {total_reward:,} 灵石\n"
        f"💰 下期奖池金额: {new_pool_amount:,} 灵石\n\n"
        f"📆 下一期大乐透将于明早8:00开始，敬请期待！"
    )
    
    # 解除之前公告的置顶
    old_message_id = lottery_status["announcement_message_id"]
    
    # 如果指定了群组ID，只发送到该群组
    if chat_id:
        try:
            # 解除之前的置顶
            if old_message_id:
                try:
                    await client.unpin_chat_message(chat_id, old_message_id)
                except Exception as e:
                    print(f"解除之前的置顶消息失败: {e}")
            
            # 发送开奖结果并置顶
            message = await client.send_message(chat_id, result_text)
            await client.pin_chat_message(chat_id, message.id)
            
            # 保存消息ID
            lottery_status["result_message_id"] = message.id
            
            print(f"大乐透开奖结果已发送到群组 {chat_id}，消息ID: {message.id}")
        except Exception as e:
            print(f"发送大乐透开奖结果到群组 {chat_id} 失败: {e}")
    else:
        # 发送到所有授权群组
        groups = db_service.get_all_authorized_groups()
        for group in groups:
            try:
                # 解除之前的置顶
                if old_message_id:
                    try:
                        await client.unpin_chat_message(group["group_id"], old_message_id)
                    except Exception as e:
                        print(f"解除之前的置顶消息失败: {e}")
                
                # 发送开奖结果并置顶
                message = await client.send_message(group["group_id"], result_text)
                await client.pin_chat_message(group["group_id"], message.id)
                
                # 保存第一个群组的消息ID
                if not lottery_status["result_message_id"]:
                    lottery_status["result_message_id"] = message.id
                
                print(f"大乐透开奖结果已发送到群组 {group['group_name']}，消息ID: {message.id}")
            except Exception as e:
                print(f"发送大乐透开奖结果到群组 {group['group_name']} 失败: {e}")
    
    # 更新状态
    lottery_status["is_active"] = False
    lottery_status["announcement_message_id"] = None

# 更新大乐透公告
async def update_lottery_announcement(client, chat_id, new_pool_amount):
    """更新大乐透公告信息
    
    Args:
        client: Pyrogram客户端
        chat_id: 群组ID
        new_pool_amount: 新的奖池金额
    """
    message_id = lottery_status["announcement_message_id"]
    if not message_id:
        print("无法更新大乐透公告，消息ID不存在")
        return
    
    try:
        # 获取原始消息
        message = await client.get_messages(chat_id, message_id)
        if not message:
            print(f"无法获取消息 {message_id}")
            return
        
        # 更新公告文本
        announcement_text = (
            f"🎯 第{get_lottery_round_number()}期大乐透盛大开启！\n\n"
            f"💰 当前奖池总额: {new_pool_amount:,} 灵石\n\n"
            f"📋 游戏规则:\n"
            f"• 选择3个0-9之间的数字\n"
            f"• 使用命令 /le [三位数字] [注数] 参与\n"
            f"• 每注100灵石\n"
            f"• 猜中2位数字(按位置): 获得5,000灵石/注\n"
            f"• 猜中全部3位数字: 获得50,000灵石/注\n\n"
            f"⏰ 开奖时间: 今晚22:00\n"
            f"🍀 祝君好运！"
        )
        
        # 编辑消息
        await client.edit_message_text(chat_id, message_id, announcement_text)
        print(f"已更新群组 {chat_id} 的大乐透公告，新奖池金额: {new_pool_amount:,}")
    except Exception as e:
        print(f"更新大乐透公告失败: {e}")

# 获取当前大乐透期数
def get_lottery_round_number():
    """获取当前大乐透期数，格式为YYYYMMDD-XX"""
    # 获取今天的日期
    from datetime import datetime
    today = datetime.now().strftime("%Y%m%d")
    
    # 查询今天已经开了几期
    connection = db_service.get_connection()
    try:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT COUNT(*) FROM lottery_numbers
                WHERE DATE(created_at) = CURDATE()
            """)
            count = cursor.fetchone()[0]
            return f"{today}-{count+1}"
    except Exception as e:
        print(f"获取大乐透期数失败: {e}")
        return f"{today}-1"
    finally:
        connection.close()

# 管理员启动大乐透命令
@auto_delete()
async def daletou_command(client, message):
    """处理/daletou命令，管理员强制启动大乐透"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        reply = await message.reply("⚠️ 只有管理员才能执行此操作")
        return await auto_delete_messages([message, reply], 5)
    
    # 检查是否在群组中
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        reply = await message.reply("⚠️ 此命令只能在群组中使用")
        return await auto_delete_messages([message, reply], 5)
    
    # 如果有正在进行的大乐透，提示确认
    if lottery_status["is_active"]:
        reply = await message.reply(
            "⚠️ 已经有一期大乐透在进行中，是否确定要强制启动新的大乐透？\n"
            "如果确定，请在10秒内回复 `确定`"
        )
        
        # 监听确认消息
        try:
            confirm_message = await client.wait_for_message(
                filters.chat(message.chat.id) & 
                filters.user(user_id) & 
                filters.text & 
                filters.regex("^确定$"),
                timeout=10
            )
            
            if confirm_message:
                # 删除确认消息
                await confirm_message.delete()
                # 强制启动
                await start_lottery(client, message.chat.id, force=True)
                # 删除命令和回复
                await message.delete()
                await reply.delete()
        except asyncio.TimeoutError:
            # 超时未确认
            await reply.edit_text("⚠️ 未收到确认，操作已取消")
            await asyncio.sleep(5)
            await reply.delete()
            await message.delete()
        return
    
    # 启动大乐透
    await start_lottery(client, message.chat.id)
    
    # 删除命令消息
    await message.delete()

# 手动开奖命令（仅用于开发测试）
@auto_delete()
async def draw_command(client, message):
    """处理/draw命令，管理员手动开奖（仅用于开发测试）"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        reply = await message.reply("⚠️ 只有管理员才能执行此操作")
        return await auto_delete_messages([message, reply], 5)
    
    # 检查是否在群组中
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        reply = await message.reply("⚠️ 此命令只能在群组中使用")
        return await auto_delete_messages([message, reply], 5)
    
    # 检查是否有进行中的大乐透
    if not lottery_status["is_active"]:
        reply = await message.reply("⚠️ 当前没有进行中的大乐透")
        return await auto_delete_messages([message, reply], 5)
    
    # 手动开奖
    await end_lottery(client, message.chat.id)
    
    # 删除命令消息
    await message.delete()

# 用户下注命令
@auto_delete()
async def le_command(client, message):
    """处理/le命令，用户参与大乐透"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or f"用户{user_id}"
    
    # 检查是否在群组中
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        reply = await message.reply("⚠️ 此命令只能在群组中使用")
        return await auto_delete_messages([message, reply], 5)
    
    # 检查是否有进行中的大乐透
    if not lottery_status["is_active"]:
        reply = await message.reply("⚠️ 当前没有进行中的大乐透，请等待下一期")
        return await auto_delete_messages([message, reply], 5)
    
    # 解析命令参数
    command_parts = message.text.split()
    if len(command_parts) != 3:
        reply = await message.reply(
            "⚠️ 格式错误，正确格式：/le [三位数字] [注数]\n"
            "例如：/le 123 5 表示选择123下注5注"
        )
        return await auto_delete_messages([message, reply], 5)
    
    # 获取选号和注数
    numbers = command_parts[1]
    bet_count = command_parts[2]
    
    # 检查选号格式
    if not numbers.isdigit() or len(numbers) != 3:
        reply = await message.reply("⚠️ 选号必须是3位数字(0-9)，例如：123")
        return await auto_delete_messages([message, reply], 5)
    
    # 检查注数格式
    if not bet_count.isdigit():
        reply = await message.reply("⚠️ 注数必须是正整数")
        return await auto_delete_messages([message, reply], 5)
    
    # 执行下注
    result = lottery_service.place_bet(user_id, username, numbers, bet_count)
    
    if not result["success"]:
        reply = await message.reply(result["message"])
        return await auto_delete_messages([message, reply], 5)
    
    # 下注成功，更新公告
    try:
        await update_lottery_announcement(client, message.chat.id, result["new_pool_amount"])
    except Exception as e:
        print(f"更新大乐透公告失败: {e}")
    
    # 发送成功消息
    reply = await message.reply(result["message"])
    return await auto_delete_messages([message, reply], 5)

# 设置定时任务
async def setup_lottery_scheduler(client):
    """设置大乐透相关的定时任务"""
    from datetime import datetime, timedelta
    import pytz
    
    # 设置时区
    tz = pytz.timezone('Asia/Shanghai')
    
    # 计算下一个早上8点
    now = datetime.now(tz)
    tomorrow_morning = now.replace(hour=8, minute=0, second=0, microsecond=0)
    if now.hour >= 8:
        tomorrow_morning += timedelta(days=1)
    
    # 计算下一个晚上10点
    today_night = now.replace(hour=22, minute=0, second=0, microsecond=0)
    if now.hour >= 22:
        today_night += timedelta(days=1)
    
    # 计算到早上8点和晚上10点的秒数
    seconds_to_morning = (tomorrow_morning - now).total_seconds()
    seconds_to_night = (today_night - now).total_seconds()
    
    # 设置早上8点的任务
    client.loop.create_task(wait_and_start_lottery(client, seconds_to_morning))
    print(f"已设置{seconds_to_morning:.1f}秒后(早上8点)启动大乐透")
    
    # 设置晚上10点的任务
    client.loop.create_task(wait_and_end_lottery(client, seconds_to_night))
    print(f"已设置{seconds_to_night:.1f}秒后(晚上10点)结束大乐透")

async def wait_and_start_lottery(client, seconds):
    """等待指定秒数后启动大乐透"""
    await asyncio.sleep(seconds)
    await start_lottery(client)
    
    # 设置下一天的任务
    client.loop.create_task(wait_and_start_lottery(client, 24 * 60 * 60))

async def wait_and_end_lottery(client, seconds):
    """等待指定秒数后结束大乐透并开奖"""
    await asyncio.sleep(seconds)
    await end_lottery(client)
    
    # 设置下一天的任务
    client.loop.create_task(wait_and_end_lottery(client, 24 * 60 * 60))

# 注册大乐透相关的消息处理器
def register_lottery_handlers(app):
    """注册大乐透相关的处理器"""
    # 管理员命令
    app.add_handler(MessageHandler(daletou_command, filters.command("daletou")))
    app.add_handler(MessageHandler(draw_command, filters.command("draw")))
    
    # 用户命令
    app.add_handler(MessageHandler(le_command, filters.command("le")))
    
    # 设置定时任务
    app.loop.create_task(setup_lottery_scheduler(app))
    
    # 恢复大乐透状态
    app.loop.create_task(restore_lottery_status(app))
    
    print("大乐透处理器和定时任务已注册")

# 从数据库恢复大乐透状态
async def restore_lottery_status(client):
    """启动时从数据库恢复大乐透状态"""
    global lottery_status
    
    try:
        # 获取最新的大乐透记录
        numbers = lottery_service.get_current_numbers()
        message_id = lottery_service.get_lottery_message_id()
        
        # 检查是否有大乐透记录
        if numbers and message_id:
            # 检查最新一期大乐透的创建时间
            today_lottery = db_service.get_today_lottery()
            
            if today_lottery:
                # 如果有今天的大乐透记录，则恢复状态
                lottery_status["is_active"] = True
                lottery_status["announcement_message_id"] = message_id
                print(f"已恢复大乐透状态，中奖号码: {numbers}，消息ID: {message_id}")
            else:
                print("没有找到今天的大乐透记录，不恢复状态")
        else:
            print("没有找到大乐透记录，不恢复状态")
    except Exception as e:
        print(f"恢复大乐透状态时出错: {e}") 