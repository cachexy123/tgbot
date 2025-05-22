import asyncio
import pytz
from datetime import datetime, time
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from bot.services.gang_service import gang_service
from bot.services.game_service import game_service
from bot.services.db_service import db_service
from bot.services.admin_service import admin_service
from pyrogram.enums import ChatMemberStatus
from pyrogram.handlers import MessageHandler
from pyrogram import filters

# 导入猫娘相关的处理函数
from bot.handlers.command_handlers import handle_catgirl_confirmation, handle_catgirl_messages, restore_hongbaos

# 全局变量，用于存储机器人客户端实例
client = None

async def update_gang_leader():
    """更新帮主（每晚10点）"""
    if not client:
        print("客户端未初始化，无法更新帮主")
        return
    
    # 更新帮主
    new_leader = gang_service.update_gang_leader()
    
    if not new_leader:
        print("未能更新帮主，可能没有合适的帮主候选人")
        return
    
    # 获取所有授权的群组，并通知新帮主
    try:
        groups = db_service.get_all_authorized_groups()
        
        username = new_leader['username']
        reward = new_leader['reward']
        consecutive_days = new_leader['consecutive_days']
        
        # 构建消息
        message = (
            f"📢 天骄榜更新！\n\n"
            f"👑 新的帮主：{username}\n"
            f"💰 获得奖励：{reward} 灵石\n"
            f"🔄 连任天数：{consecutive_days} 天\n\n"
            f"帮主可以使用回复并发送 `/slave` 命令来指定一名奴隶"
        )
        
        # 发送到所有授权群组
        for group in groups:
            try:
                await client.send_message(group['group_id'], message)
            except Exception as e:
                print(f"发送帮主通知到群组 {group['group_name']} 失败: {e}")
    
    except Exception as e:
        print(f"发送帮主通知失败: {e}")

async def check_negative_points_users():
    """检查并踢出积分为负且超过3天的用户"""
    if not client:
        print("客户端未初始化，无法检查负分用户")
        return
    
    try:
        # 获取所有需要踢出的负分用户
        negative_users = admin_service.check_negative_points_users()
        
        if negative_users:
            print(f"发现 {len(negative_users)} 名负分超过3天的用户，准备处理...")
        
        for user in negative_users:
            user_id = user['user_id']
            username = user['username'] or f"用户{user_id}"
            points = user['points']
            negative_since = user['first_negative_time']
            
            # 获取用户所在的群组
            user_groups = db_service.get_user_groups(user_id)
            
            # 在数据库标记后再实际踢出用户
            for group in user_groups:
                group_id = group['group_id']
                group_name = group['group_name']
                
                try:
                    # 尝试从群组踢出用户
                    try:
                        await client.ban_chat_member(
                            chat_id=group_id,
                            user_id=user_id,
                            revoke_messages=False  # 不删除历史消息
                        )
                        await client.unban_chat_member(  # 立即解除封禁，这样用户将来可以重新加入
                            chat_id=group_id,
                            user_id=user_id
                        )
                        print(f"已踢出用户 {username}(ID:{user_id}) 从群组 {group_name}(ID:{group_id})")
                        
                        # 移除数据库中的用户-群组关联
                        db_service.remove_user_from_group(user_id, group_id)
                        
                        # 发送通知
                        await client.send_message(
                            group_id,
                            f"⚠️ 用户 {username} 已被系统踢出\n"
                            f"原因：灵石为负值({points})超过3天\n"
                            f"首次负分时间：{negative_since}"
                        )
                    except Exception as e:
                        print(f"从群组 {group_name} 踢出用户 {username} 失败: {e}")
                except Exception as e:
                    print(f"处理负分用户 {username} 时出错: {e}")
            
            # 移除负分记录
            db_service.remove_negative_points_record(user_id)
    except Exception as e:
        print(f"检查负分用户失败: {e}")

async def check_duel_timeouts():
    """检查并处理生死战超时情况"""
    if not client:
        print("客户端未初始化，无法检查生死战超时")
        return
    
    try:
        # 获取所有超时的生死战
        timeout_duels = db_service.get_timeout_duels()
        
        if timeout_duels:
            print(f"发现 {len(timeout_duels)} 场超时的生死战，准备处理...")
        
        for duel in timeout_duels:
            # 处理超时
            is_timeout = game_service.check_duel_timeout(duel['id'])
            
            if is_timeout:
                print(f"生死战 {duel['id']} 已超时处理完成")
                # 构建消息
                if duel['status'] == 'waiting':
                    # 等待接受超时
                    challenger = db_service.get_user(duel['challenger_id'])
                    challenged = db_service.get_user(duel['challenged_id'])
                    challenger_name = challenger['username'] if challenger and challenger['username'] else f"用户{duel['challenger_id']}"
                    challenged_name = challenged['username'] if challenged and challenged['username'] else f"用户{duel['challenged_id']}"
                    
                    message = (
                        f"⚔️ 生死战邀请已过期！\n\n"
                        f"挑战者：{challenger_name}\n"
                        f"被挑战者：{challenged_name}\n"
                        f"由于被挑战者未在1分钟内做出反应，挑战自动取消。"
                    )
                else:
                    # 游戏中超时
                    current_turn_id = duel['current_turn']
                    winner_id = duel['challenged_id'] if current_turn_id == duel['challenger_id'] else duel['challenger_id']
                    
                    # 获取用户信息
                    loser = db_service.get_user(current_turn_id)
                    winner = db_service.get_user(winner_id)
                    loser_name = loser['username'] if loser and loser['username'] else f"用户{current_turn_id}"
                    winner_name = winner['username'] if winner and winner['username'] else f"用户{winner_id}"
                    
                    # 获取胜者资源信息
                    winner_cultivation = db_service.get_cultivation(winner_id)
                    winner_points = winner['points']
                    winner_pills = winner_cultivation['pills'] if winner_cultivation else 0
                    
                    message = (
                        f"⚔️ 生死战超时结束！\n\n"
                        f"玩家 {loser_name} 操作超时（超过2分钟未操作），自动判定为失败。\n"
                        f"胜者：{winner_name}\n"
                        f"胜者当前灵石：{winner_points}\n"
                        f"胜者当前突破丹：{winner_pills}"
                    )
                
                # 发送到对应群组
                try:
                    await client.send_message(duel['group_id'], message)
                    print(f"已发送生死战超时消息到群组 {duel['group_id']}")
                except Exception as e:
                    print(f"发送生死战超时通知失败: {e}")
    
    except Exception as e:
        print(f"检查生死战超时失败: {e}")

async def restore_pending_catgirls():
    """恢复等待确认的猫娘状态（机器人启动时调用）"""
    if not client:
        print("客户端未初始化，无法恢复猫娘状态")
        return
    
    try:
        # 获取所有等待确认的猫娘记录
        pending_records = db_service.get_all_pending_catgirls()
        
        if pending_records:
            print(f"发现 {len(pending_records)} 个正在等待确认的猫娘记录，正在恢复...")
        else:
            print("没有需要恢复的等待确认猫娘记录")
        
        # 为每条记录重新设置消息处理器
        for record in pending_records:
            user_id = record['user_id']
            group_id = record['group_id']
            user_name = record['user_name']
            master_name = record['master_name']
            
            print(f"正在恢复用户 {user_name}(ID:{user_id}) 在群组 {group_id} 的猫娘确认状态")
            
            # 添加消息处理器，高优先级(1)确保在其他处理器之前执行
            client.add_handler(MessageHandler(
                handle_catgirl_confirmation,
                filters.chat(group_id) & filters.user(user_id)
            ), group=1)
            
            # 发送提醒消息
            try:
                await client.send_message(
                    group_id,
                    f"🔄 机器人重启后恢复状态：{user_name} 需要确认成为 {master_name} 的猫娘\n"
                    f"请回复: 谢过帮主大人成全(必须一字不漏打完)"
                )
            except Exception as e:
                print(f"发送猫娘确认提醒消息失败: {e}")
    
    except Exception as e:
        print(f"恢复猫娘确认状态失败: {e}")

async def restore_confirmed_catgirls():
    """恢复已确认的猫娘状态（机器人启动时调用）"""
    if not client:
        print("客户端未初始化，无法恢复已确认猫娘状态")
        return
    
    try:
        # 获取所有已确认的猫娘记录
        confirmed_records = db_service.get_all_confirmed_catgirls()
        
        if confirmed_records:
            print(f"发现 {len(confirmed_records)} 个已确认的猫娘记录，正在恢复...")
        else:
            print("没有需要恢复的已确认猫娘记录")
            return
        
        # 为每条记录重新设置消息处理器
        for record in confirmed_records:
            user_id = record['user_id']
            group_id = record['group_id']
            user_name = record['user_name']
            master_name = record['master_name']
            
            print(f"正在恢复用户 {user_name}(ID:{user_id}) 在群组 {group_id} 的已确认猫娘状态")
            
            # 添加消息过滤器，高优先级(1)确保在其他处理器之前执行
            client.add_handler(MessageHandler(
                handle_catgirl_messages,
                filters.chat(group_id) & filters.user(user_id)
            ), group=1)
            
            # 发送提醒消息
            try:
                await client.send_message(
                    group_id,
                    f"🔄 机器人重启后恢复状态：{user_name} 是 {master_name} 的猫娘\n"
                    f"所有消息都必须带上'喵'字哦~"
                )
            except Exception as e:
                print(f"发送已确认猫娘提醒消息失败: {e}")
    
    except Exception as e:
        print(f"恢复已确认猫娘状态失败: {e}")

# 启动时恢复大乐透状态
async def restore_lottery_status(client):
    """从数据库恢复大乐透状态"""
    try:
        # 导入大乐透服务
        from bot.services.lottery_service import lottery_service
        from bot.handlers.lottery_handlers import lottery_status, start_lottery
        
        # 恢复大乐透的中奖号码
        numbers = lottery_service.get_current_numbers()
        if numbers:
            print(f"已从数据库恢复大乐透中奖号码: {numbers}")
        
        # 恢复大乐透的奖池金额
        pool_info = lottery_service.get_lottery_pool()
        if pool_info:
            print(f"已从数据库恢复大乐透奖池金额: {pool_info['amount']}")
        else:
            print("没有找到大乐透奖池信息，使用默认值")
        
        # 恢复大乐透的公告消息ID
        message_id = lottery_service.get_lottery_message_id()
        if message_id:
            lottery_status["announcement_message_id"] = message_id
            print(f"已从数据库恢复大乐透公告消息ID: {message_id}")
        
        print("大乐透状态恢复完成")
    except Exception as e:
        print(f"恢复大乐透状态时出错: {e}")

def setup_scheduler(app):
    """设置定时任务调度器"""
    global client
    client = app
    
    # 创建调度器
    scheduler = AsyncIOScheduler(timezone=pytz.timezone('Asia/Shanghai'))
    
    # 添加更新帮主的定时任务（每天晚上10点）
    scheduler.add_job(
        update_gang_leader,
        'cron',
        hour=22,
        minute=0
    )
    
    # 添加检查生死战超时的定时任务（每分钟）
    scheduler.add_job(
        check_duel_timeouts,
        'interval',
        minutes=1
    )
    
    # 添加检查负分用户的定时任务（每天中午12点）
    scheduler.add_job(
        check_negative_points_users,
        'cron',
        hour=12,
        minute=0
    )
    
    # 立即检查一次生死战超时
    asyncio.create_task(check_duel_timeouts())
    
    # 恢复等待确认的猫娘状态
    asyncio.create_task(restore_pending_catgirls())
    
    # 恢复已确认的猫娘状态
    asyncio.create_task(restore_confirmed_catgirls())
    
    # 恢复红包状态
    asyncio.create_task(restore_hongbaos(app))
    
    # 恢复大乐透状态
    asyncio.create_task(restore_lottery_status(app))
    
    # 启动调度器
    scheduler.start()
    print("定时任务调度器已启动，生死战超时检查已设置（每分钟一次），负分用户检查已设置（每天中午12点），猫娘状态和红包状态已恢复") 