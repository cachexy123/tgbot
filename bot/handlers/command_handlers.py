from pyrogram import Client, filters
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.handlers import MessageHandler, CallbackQueryHandler
from pyrogram.enums import ChatType
from bot.services.admin_service import admin_service
from bot.services.db_service import db_service
from bot.services.cultivation_service import cultivation_service
from bot.services.game_service import game_service
from bot.services.gang_service import gang_service
from bot.services.ai_service import ai_service
from bot.utils.helpers import format_cultivation_info, format_leaderboard, format_time_ago, auto_delete
from bot.config.config import CULTIVATION_STAGES, AI_BACKEND_URL, AI_API_KEY, AI_MODEL
from datetime import datetime, timedelta
import re
import asyncio
import random
import uuid

# 红包数据存储
active_hongbaos = {}  # 存储活跃的红包 {红包ID: {creator_id, total_amount, total_people, remaining, claimed_users, message_id, chat_id}}

# 保存红包数据到数据库的辅助函数
def save_hongbao_to_db(hongbao_id):
    """将红包数据保存到数据库"""
    if hongbao_id in active_hongbaos:
        db_service.save_hongbao(hongbao_id, active_hongbaos[hongbao_id])

# 恢复红包数据
async def restore_hongbaos(client):
    """从数据库恢复红包数据"""
    global active_hongbaos
    
    try:
        # 获取所有活跃的红包记录
        hongbao_records = db_service.get_all_active_hongbaos()
        
        if hongbao_records:
            print(f"发现 {len(hongbao_records)} 个活跃红包记录，正在恢复...")
        else:
            print("没有需要恢复的红包记录")
            return
        
        # 恢复到内存中
        for record in hongbao_records:
            hongbao_id = record['hongbao_id']
            active_hongbaos[hongbao_id] = {
                "creator_id": record['creator_id'],
                "creator_name": record['creator_name'],
                "total_amount": record['total_amount'],
                "total_people": record['total_people'],
                "remaining_amount": record['remaining_amount'],
                "remaining_people": record['remaining_people'],
                "claimed_users": record['claimed_users'],
                "chat_id": record['chat_id'],
                "message_id": record['message_id'],
                "created_at": record['created_at']
            }
            
            # 重新设置过期任务
            time_remaining = (record['expires_at'] - datetime.now()).total_seconds()
            if time_remaining > 0:
                asyncio.create_task(expire_hongbao(client, hongbao_id, time_remaining))
                print(f"红包 {hongbao_id} 将在 {time_remaining/3600:.1f} 小时后过期")
    
    except Exception as e:
        print(f"恢复红包记录失败: {e}")

@auto_delete()
async def start_command(client, message):
    """处理/start命令"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "无名修士"
    
    # 检查是否已注册
    user = db_service.get_user(user_id)
    if not user:
        db_service.create_user(user_id, username)
    else:
        # 更新用户名
        db_service.update_username(user_id, username)
    
    # 检查是否有参数
    command_parts = message.text.split()
    if len(command_parts) > 1 and command_parts[1] == "redeem":
        # 如果是通过群组的兑换码按钮点击过来的
        # 检查用户积分是否足够
        if user['points'] < 3000:
            return await message.reply("灵石不足，获取兑换码需要3000灵石")
        
        # 获取一个未使用的兑换码
        redemption_code = db_service.get_unused_redemption_code()
        if not redemption_code:
            return await message.reply("当前没有可用的兑换码，请稍后再试")
        
        # 扣除用户积分
        if not db_service.update_points(user_id, -3000):
            return await message.reply("扣除积分失败，请稍后再试")
        
        # 标记兑换码为已使用
        if not db_service.mark_redemption_code_used(redemption_code, user_id):
            # 如果标记失败，尝试退还积分
            db_service.update_points(user_id, 3000)
            return await message.reply("获取兑换码失败，已退还积分，请稍后再试")
        
        # 在私聊中发送兑换码
        return await message.reply(
            f"兑换码获取成功，扣除3000灵石\n\n"
            f"兑换码: `{redemption_code}`\n\n"
            f"请复制该兑换码到 @xieloujdBot 机器人中进行兑换使用时长"
        )
    else:
        # 普通的start命令
        return await message.reply(
            f"欢迎使用书群机器人！\n"
            f"• 使用 /help 查看帮助\n"
            f"• 使用 /my 查看个人信息\n"
            f"• 每天记得 /checkin 签到获取灵石"
        )

@auto_delete()
async def help_command(client, message):
    """处理/help命令"""
    is_admin = admin_service.is_admin(message.from_user.id)
    
    # 基础命令
    basic_cmds = (
        "📚 基础命令：\n"
        "/my - 查看个人信息\n"
        "/checkin - 每日签到\n"
        "/gua [10/20/50] - 刮刮乐游戏\n"
        "/hongbao [积分] [人数] - 发送积分红包\n"
        "/tiankou - 查看天骄榜\n"
        "/gongde - 查看功德榜(上传书籍排行)\n"
        "/tujing - 尝试突破修为境界\n"
        "/buy [数量] - 购买突破丹(50灵石/颗)\n"
        "/dajie [回复某人] - 打劫其他修士\n"
        "/rob [回复某人] - 打劫其他修士\n"
        "/slave [回复某人] - 帮主可以设置猫娘\n"
        "/confirm - 确认成为奴隶\n"
        "/si [回复某人] - 发起生死战\n"
        "/feisheng - 渡劫后期可开启飞升之旅\n"
        "/shield - 查看保护罩功能说明\n"
        "/duihuan - 获取兑换码（需要3000灵石）"
    )
    
    # AI功能
    ai_cmds = (
        "\n\n🤖 AI功能：\n"
        "/ask [问题] - 向AI提问\n"
        "/aireset - 重置AI会话历史\n"
        "直接回复机器人的消息 - 与AI对话"
    )
    
    # 管理员命令
    admin_cmds = (
        "\n\n👑 管理员命令：\n"
        "/auth - 授权当前群组\n"
        "/addadmin [用户ID] - 添加管理员\n"
        "/addpoint [用户ID] [数量] - 增加用户积分\n"
        "/subpoint [用户ID] [数量] - 减少用户积分\n"
        "/deduct [用户ID] [数量] - 扣除用户积分(允许负分)\n"
        "/aiconfig - 配置AI参数\n"
        "/set [兑换码] - 添加兑换码"
    ) if is_admin else ""
    
    return await message.reply(basic_cmds + ai_cmds + admin_cmds)

@auto_delete()
async def my_command(client, message):
    """处理/my命令，显示用户信息"""
    user_id = message.from_user.id
    
    # 获取用户的姓名，优先使用first_name和last_name的组合
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    full_name = (first_name + " " + last_name).strip()
    username = full_name or message.from_user.username or "无名修士"
    
    # 获取用户信息
    user_info = db_service.get_user(user_id)
    if not user_info:
        db_service.create_user(user_id, username, first_name, last_name)
        user_info = db_service.get_user(user_id)
    else:
        # 更新用户名
        db_service.update_username(user_id, username, first_name, last_name)
    
    # 获取修仙信息
    cultivation = cultivation_service.get_user_cultivation(user_id)
    if not cultivation:
        # 如果修仙信息不存在，尝试初始化修仙记录
        try:
            # 确保用户信息创建后再创建修仙记录
            db_service.initialize_user_cultivation(user_id)
            # 重新获取修仙信息
            cultivation = cultivation_service.get_user_cultivation(user_id)
            if not cultivation:
                return await message.reply("初始化用户修仙信息失败，请联系管理员")
        except Exception as e:
            print(f"初始化用户修仙信息时出错: {e}")
        return await message.reply("获取用户信息失败，请联系管理员")
    
    # 获取签到状态
    checkin_status = game_service.get_checkin_status(user_id)
    
    # 获取刮刮乐记录
    gua_records = game_service.get_gua_records(user_id)
    
    # 获取打劫记录
    rob_record = db_service.get_rob_record(user_id)
    last_rob = format_time_ago(rob_record['last_rob']) if rob_record and rob_record['last_rob'] else "从未"
    
    # 获取奴隶状态
    slave_status = gang_service.get_slave_status(user_id)
    
    # 获取保护罩状态
    shield_status = db_service.get_shield_status(user_id)
    
    cultivation_text = format_cultivation_info(
        cultivation['stage_index'], 
        cultivation['pills'],
        cultivation['next_cost']
    )
    
    # 帮主状态
    leader = gang_service.get_gang_leader()
    is_leader = leader and leader['user_id'] == user_id
    
    # 构建个人信息
    info_text = (
        f"📊 个人信息 - {username}\n"
        f"灵石：{user_info['points']} 个\n"
        f"修为：{cultivation_text}\n\n"
        f"签到：连续 {checkin_status['consecutive_days']} 天"
    )
    
    # 添加今日签到信息
    if checkin_status['today_checked']:
        info_text += " (今日已签到✅)"
    else:
        info_text += " (今日未签到❌)"
    
    info_text += f"\n刮刮乐：今日剩余 {gua_records['remaining']} 次\n"
    info_text += f"上次打劫：{last_rob}\n"
    
    # 添加保护罩信息
    if shield_status['shield_active']:
        info_text += f"\n🛡️ 保护罩：已激活（今日已上传 {shield_status['books_uploaded']} 本书）"
    else:
        info_text += f"\n📚 今日已上传：{shield_status['books_uploaded']}/10 本书"
    
    # 添加帮主信息
    if is_leader:
        info_text += f"\n👑 你是当前帮主！"
    
    # 添加奴隶信息
    if slave_status['is_slave']:
        master_name = slave_status['slave_record']['master_name']
        info_text += f"\n⛓ 你是 {master_name} 的猫娘"
    
    if slave_status['has_slave']:
        slave_name = slave_status['master_record']['slave_name']
        info_text += f"\n🔗 你的猫娘是 {slave_name}"
    
    return await message.reply(info_text)

@auto_delete()
async def checkin_command(client, message):
    """处理/checkin签到命令"""
    user_id = message.from_user.id
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    full_name = (first_name + " " + last_name).strip()
    username = full_name or message.from_user.username or "无名修士"
    
    # 先检查今天是否已经签到过
    checkin_status = game_service.get_checkin_status(user_id)
    if checkin_status['today_checked']:
        return await message.reply("⚠️ 今天已经签到过了，明天再来吧！")
    
    # 检查用户是否存在
    user = db_service.get_user(user_id)
    if not user:
        db_service.create_user(user_id, username, first_name, last_name)
    else:
        # 更新用户名
        db_service.update_username(user_id, username, first_name, last_name)
    
    # 确保用户有修仙记录
    cultivation = cultivation_service.get_user_cultivation(user_id)
    if not cultivation:
        db_service.initialize_user_cultivation(user_id)
    
    # 执行签到
    result = game_service.check_in(user_id)
    
    if not result['success']:
        return await message.reply(result['message'])
    
    # 成功签到
    base_points = result['base_points']
    extra_points = result['extra_points']
    total_points = result['total_points']
    consecutive_days = result['consecutive_days']
    
    reply_text = f"✅ 签到成功！获得 {base_points} 灵石"
    
    if extra_points > 0:
        reply_text += f" + {extra_points} 连续签到奖励"
    
    reply_text += f"\n🔄 连续签到：{consecutive_days} 天"
    
    if consecutive_days == 3:
        reply_text += "\n🎁 达成连续签到3天，额外奖励3灵石！"
    elif consecutive_days == 5:
        reply_text += "\n🎁 达成连续签到5天，额外奖励5灵石！"
    elif consecutive_days == 7:
        reply_text += "\n🎁 达成连续签到7天，额外奖励10灵石！"
        reply_text += "\n⚠️ 已达到7天，连续签到天数将重置"
    
    # 获取当前总积分
    points = db_service.get_user_points(user_id)
    reply_text += f"\n💰 当前灵石：{points}"
    
    return await message.reply(reply_text)

@auto_delete()
async def authorize_group_command(client, message):
    """处理/auth命令，授权群组"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        return await message.reply("⚠️ 只有管理员才能执行此操作")
    
    # 检查是否在群组中
    if message.chat.type not in [ChatType.GROUP, ChatType.SUPERGROUP]:
        return await message.reply("⚠️ 此命令只能在群组中使用")
    
    group_id = message.chat.id
    group_name = message.chat.title
    
    # 检查群组是否已授权
    if admin_service.is_group_authorized(group_id):
        return await message.reply("✅ 此群组已经授权")
    
    # 授权群组
    result = admin_service.authorize_group(group_id, group_name)
    if result:
        return await message.reply("✅ 群组授权成功！")
    else:
        return await message.reply("❌ 群组授权失败，请联系开发者")

@auto_delete()
async def add_admin_command(client, message):
    """处理/addadmin命令，添加管理员"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        return await message.reply("⚠️ 只有管理员才能执行此操作")
    
    # 检查命令格式
    command_parts = message.text.split()
    if len(command_parts) != 2:
        return await message.reply("⚠️ 格式错误，正确格式: /addadmin [用户ID]")
    
    # 获取目标用户ID
    try:
        target_id = int(command_parts[1])
    except ValueError:
        return await message.reply("⚠️ 用户ID必须是数字")
    
    # 添加管理员
    result = admin_service.add_admin(target_id)
    
    if result:
        return await message.reply(f"✅ 用户 {target_id} 已添加为管理员")
    else:
        return await message.reply(f"⚠️ 用户 {target_id} 已经是管理员")

@auto_delete()
async def add_points_command(client, message):
    """处理/addpoint命令，增加用户积分"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        return await message.reply("⚠️ 只有管理员才能执行此操作")
    
    # 检查命令格式
    command_parts = message.text.split()
    if len(command_parts) != 3:
        return await message.reply("⚠️ 格式错误，正确格式: /addpoint [用户ID] [数量]")
    
    # 获取目标用户ID和积分数量
    try:
        target_id = int(command_parts[1])
        points = int(command_parts[2])
    except ValueError:
        return await message.reply("⚠️ 用户ID和积分数量必须是数字")
    
    # 检查积分是否为正数
    if points <= 0:
        return await message.reply("⚠️ 积分数量必须大于0")
    
    # 检查用户是否存在
    target_user = db_service.get_user(target_id)
    if not target_user:
        return await message.reply(f"⚠️ 用户 {target_id} 不存在")
    
    # 增加积分
    new_points = admin_service.update_user_points(target_id, points)
    
    # 获取用户显示名称
    display_name = target_user.get('username') or f"用户{target_id}"
    
    return await message.reply(f"✅ 已为用户 {display_name} 增加 {points} 灵石，当前灵石: {new_points}")

@auto_delete()
async def sub_points_command(client, message):
    """处理/subpoint命令，减少用户积分"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        return await message.reply("⚠️ 只有管理员才能执行此操作")
    
    # 检查命令格式
    command_parts = message.text.split()
    if len(command_parts) != 3:
        return await message.reply("⚠️ 格式错误，正确格式: /subpoint [用户ID] [数量]")
    
    # 获取目标用户ID和积分数量
    try:
        target_id = int(command_parts[1])
        points = int(command_parts[2])
    except ValueError:
        return await message.reply("⚠️ 用户ID和积分数量必须是数字")
    
    # 检查积分是否为正数
    if points <= 0:
        return await message.reply("⚠️ 积分数量必须大于0")
    
    # 检查用户是否存在
    target_user = db_service.get_user(target_id)
    if not target_user:
        return await message.reply(f"⚠️ 用户 {target_id} 不存在")
    
    # 减少积分
    new_points = admin_service.update_user_points(target_id, -points)
    
    return await message.reply(f"✅ 已从用户 {target_user['username']} 减少 {points} 灵石，当前灵石: {new_points}")

@auto_delete()
async def deduct_points_command(client, message):
    """处理/deduct命令，扣除用户积分（允许为负）"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        return await message.reply("⚠️ 只有管理员才能执行此操作")
    
    # 检查命令格式
    command_parts = message.text.split()
    if len(command_parts) != 3:
        return await message.reply("⚠️ 格式错误，正确格式: /deduct [用户ID] [数量]")
    
    # 获取目标用户ID和积分数量
    try:
        target_id = int(command_parts[1])
        points = int(command_parts[2])
    except ValueError:
        return await message.reply("⚠️ 用户ID和积分数量必须是数字")
    
    # 检查积分是否为正数
    if points <= 0:
        return await message.reply("⚠️ 积分数量必须大于0")
    
    # 检查用户是否存在
    target_user = db_service.get_user(target_id)
    if not target_user:
        return await message.reply(f"⚠️ 用户 {target_id} 不存在")
    
    # 扣除积分（允许负数）
    new_points = admin_service.deduct_user_points(target_id, points)
    
    message_text = (
        f"✅ 已从用户 {target_user['username']} 扣除 {points} 灵石，当前灵石: {new_points}\n"
    )
    
    # 如果积分为负，添加警告信息
    if new_points < 0:
        message_text += f"⚠️ 注意：该用户灵石已为负数，如果3天内不补足，将被自动踢出群聊"
    
    return await message.reply(message_text)

@auto_delete()
async def gua_command(client, message):
    """处理/gua命令，玩刮刮乐游戏"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "无名修士"
    
    # 解析参数
    command_parts = message.text.split()
    if len(command_parts) != 2 or command_parts[1] not in ['10', '20', '50']:
        return await message.reply("⚠️ 格式错误，正确格式: /gua [10/20/50]")
    
    amount = int(command_parts[1])
    
    # 检查用户是否存在
    user = db_service.get_user(user_id)
    if not user:
        db_service.create_user(user_id, username)
        user = db_service.get_user(user_id)
    
    # 检查用户积分是否足够
    if user['points'] < amount:
        return await message.reply(f"⚠️ 灵石不足！你只有 {user['points']} 灵石，但需要 {amount} 灵石")
    
    # 检查今日使用次数
    gua_records = game_service.get_gua_records(user_id)
    if gua_records['remaining'] <= 0:
        return await message.reply("⚠️ 今日刮刮乐次数已用完，明天再来吧！")
    
    # 创建游戏
    game_result = game_service.start_gua_game(user_id, amount)
    if not game_result['success']:
        return await message.reply(game_result['message'])
    
    # 生成按钮
    buttons = []
    row = []
    for i in range(1, 21):
        row.append(InlineKeyboardButton(str(i), callback_data=f"gua_guess_{i}"))
        if i % 5 == 0:
            buttons.append(row)
            row = []
    
    # 添加取消按钮
    buttons.append([InlineKeyboardButton("❌ 取消", callback_data="gua_cancel")])
    
    return await message.reply(
        f"🎮 刮刮乐游戏 (押注: {amount} 灵石)\n"
        f"请选择1个数字，猜中获得双倍奖励！",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

@auto_delete()
async def tiankou_command(client, message):
    """处理/tiankou命令，查看修真榜单"""
    # 获取排行榜信息
    top_players = cultivation_service.get_top_cultivators(10)
    leaderboard_text = format_leaderboard(top_players)
    
    return await message.reply(leaderboard_text)

@auto_delete()
async def tujing_command(client, message):
    """处理/tujing命令，尝试突破修为"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "无名修士"
    
    # 检查用户是否存在
    user = db_service.get_user(user_id)
    if not user:
        db_service.create_user(user_id, username)
    
    # 获取用户当前修为信息
    cultivation = db_service.get_cultivation(user_id)
    if not cultivation:
        return await message.reply("获取用户修为信息失败，请联系管理员")
    
    # 检查是否已经达到最高境界（渡劫后期）
    if cultivation['stage'] >= len(CULTIVATION_STAGES) - 1:
        return await message.reply("⚠️ 道友已达到菠萝界的最高境界【渡劫后期】，再突破便是飞升上界，超出凡人之界了！")
    
    # 尝试突破
    result = cultivation_service.attempt_breakthrough(user_id)
    
    if not result['success']:
        return await message.reply(result['message'])
    
    # 构建回复消息
    reply_text = f"🌟 恭喜突破成功！\n修为提升到：{result['new_stage']}"
    
    # 检查消息中是否包含突破丹信息
    if "突破丹" in result['message']:
        # 从消息中提取消耗的突破丹数量
        pills_match = re.search(r'消耗了\d+灵石和(\d+)个突破丹', result['message'])
        if pills_match:
            pills_used = pills_match.group(1)
            reply_text += f"\n消耗突破丹：{pills_used} 个"
    
    # 提取消耗的灵石数量
    cost_match = re.search(r'消耗了(\d+)灵石', result['message'])
    if cost_match:
        cost = cost_match.group(1)
        reply_text += f"\n消耗灵石：{cost} 个"
    else:
        # 如果无法从消息中提取，则使用next_cost
        reply_text += f"\n消耗灵石：{result['next_cost'] // 2} 个"  # next_cost是原来的两倍
    
    return await message.reply(reply_text)

@auto_delete()
async def dajie_command(client, message):
    """处理/dajie命令，打劫其他用户"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "无名修士"
    
    # 检查是否是回复其他消息
    if not message.reply_to_message:
        return await message.reply("⚠️ 请回复要打劫的用户的消息")
    
    # 获取目标用户ID
    target_message = message.reply_to_message
    if not target_message.from_user or target_message.from_user.is_bot:
        return await message.reply("⚠️ 不能打劫机器人")
    
    target_id = target_message.from_user.id
    target_name = target_message.from_user.username or target_message.from_user.first_name
    
    # 不能打劫自己
    if target_id == user_id:
        return await message.reply("⚠️ 不能打劫自己")
    
    # 检查目标用户是否存在
    target_user = db_service.get_user(target_id)
    if not target_user:
        return await message.reply("⚠️ 对方还未注册")
    
    # 检查自己是否存在
    user = db_service.get_user(user_id)
    if not user:
        db_service.create_user(user_id, username)
    
    # 检查打劫冷却时间
    rob_record = db_service.get_rob_record(user_id)
    if rob_record and rob_record['last_rob']:
        # 计算从上次打劫到现在的时间（秒）
        cooldown_seconds = (datetime.now() - rob_record['last_rob']).total_seconds()
        if cooldown_seconds < 1800:  # 30分钟冷却
            remaining_minutes = max(0, 30 - cooldown_seconds // 60)
            return await message.reply(f"⚠️ 打劫太频繁了，请等待{int(remaining_minutes)}分钟后再试")
    
    # 执行打劫
    result = cultivation_service.rob_user(user_id, target_id)
    
    # 检查是否有特定的错误消息
    if not result['success'] and 'message' in result and '修士' in result['message']:
        return await message.reply(result['message'])
    
    # 构建回复文本
    result_text = (
        f"🗡 {username} 对 {target_name} 发起了打劫！\n"
        f"👤 {username}：{result['robber_stage']} 境界，掷出 {result['robber_roll']}点"
    )
    
    if result['robber_bonus'] > 0:
        result_text += f"(+{result['robber_bonus']})"
    
    result_text += f"\n👤 {target_name}：{result['victim_stage']} 境界，掷出 {result['victim_roll']}点"
    
    if result['victim_bonus'] > 0:
        result_text += f"(+{result['victim_bonus']})"
    
    result_text += "\n\n"
    
    if result['success']:
        points_stolen = result['points_stolen']
        percentage = result['percentage']
        result_text += f"打劫成功！{username} 抢走了 {target_name} {percentage}% 的灵石，共 {points_stolen} 个"
        
        # 添加突破丹信息
        if 'pills_stolen' in result and result['pills_stolen'] > 0:
            result_text += f"，以及 {result['pills_stolen']} 颗突破丹！"
        else:
            result_text += "！"
    else:
        # 优先显示服务返回的特定失败消息（如保护罩提示）
        if 'message' in result and '保护罩' in result['message']:
            result_text += f"{result['message']}"
        elif 'message' in result and '积分未成功转移' in result['message']:
            result_text += "打劫过程中出现意外，积分未成功转移！"
        else:
            result_text += f"打劫失败！{target_name} 成功抵抗了攻击！"
    
    return await message.reply(result_text)

@auto_delete()
async def slave_command(client, message):
    """处理/slave命令，设置猫娘"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "无名修士"
    
    # 检查是否是帮主
    leader = gang_service.get_gang_leader()
    if not leader or leader['user_id'] != user_id:
        return await message.reply("⚠️ 只有帮主才能设置猫娘")
    
    # 检查是否是回复其他消息
    if not message.reply_to_message:
        return await message.reply("⚠️ 请回复要设为猫娘的用户的消息")
    
    # 获取目标用户ID
    target_message = message.reply_to_message
    if not target_message.from_user or target_message.from_user.is_bot:
        return await message.reply("⚠️ 不能把机器人设为猫娘")
    
    target_id = target_message.from_user.id
    target_name = target_message.from_user.username or target_message.from_user.first_name
    
    # 不能设置自己
    if target_id == user_id:
        return await message.reply("⚠️ 不能把自己设为猫娘")
    
    # 检查目标用户是否已成仙
    target_cultivation = cultivation_service.get_user_cultivation(target_id)
    if target_cultivation and target_cultivation['stage_index'] >= len(CULTIVATION_STAGES):
        return await message.reply("⚠️ 对方已位列仙班，已超脱五行三界，不受凡间羁绊！")
    
    # 检查是否已经在处理中
    existing_record = db_service.get_catgirl_record(target_id, message.chat.id)
    if existing_record and existing_record['status'] == 'pending':
        return await message.reply("⚠️ 该用户正在等待确认成为猫娘")
    
    # 创建猫娘记录
    db_service.create_catgirl_record(user_id, target_id, message.chat.id)
    
    # 发送猫娘转化描述
    await message.reply(
        f"天地间骤然雷霆大作，紫电划破长空。只见帮主衣袂袂翻飞间，一道泛着幽光的玄奥印记已穿透雨幕，如影随形没入{target_message.from_user.mention}体内。刹那间血脉震颤，{target_message.from_user.mention}周身泛起柔和光晕——青丝化作绒耳，玉指蜷缩成粉嫩肉垫，随着一声娇软'喵呜'，瓷白肌肤已覆上丝绸般的毛发, 腰际倏然窜出蓬松长尾，琥珀色竖瞳在雷光中潋滟生辉"
    )
    
    # 发送确认消息
    await message.reply(
        f"恭喜{target_message.from_user.mention}成为帮主的猫娘(众人纷纷投过了羡慕的眼光), 请{target_message.from_user.mention}说: 谢过帮主大人成全(必须一字不漏打完)"
    )
    
    # 设置消息过滤器，高优先级(1)确保在其他处理器之前执行
    client.add_handler(MessageHandler(
        handle_catgirl_confirmation,
        filters.chat(message.chat.id) & filters.user(target_id)
    ), group=1)
    
    # 设置24小时后的清理任务
    client.loop.create_task(cleanup_catgirl_status(client, target_id, message.chat.id))

async def handle_catgirl_confirmation(client, message):
    """处理猫娘确认消息"""
    # 检查对应的记录是否存在并且状态是pending
    record = db_service.get_catgirl_record(message.from_user.id, message.chat.id)
    if not record or record['status'] != 'pending':
        # 如果记录不存在或状态不是pending，则不处理
        return
    
    # 检查是否是命令，如果是已注册的命令则不处理    
    # 注：通常机器人只响应以/开头并且在register_command_handlers中注册过的命令
    # 所以这里不检查是否以/开头，而是只检查消息内容是否符合要求
    
    if message.text != "谢过帮主大人成全":
        # 打印日志以便调试
        print(f"删除消息: {message.text}, 用户ID: {message.from_user.id}")
        # 执行删除
        try:
            await message.delete()
        except Exception as e:
            print(f"删除消息时发生错误: {str(e)}")
        return
    
    # 更新猫娘状态为已确认
    db_service.update_catgirl_status(message.from_user.id, message.chat.id, 'confirmed')
    
    # 发送确认成功消息
    await message.reply(
        f'恭喜{message.from_user.mention}成为帮主的猫娘, 24小时内都要带上"喵"字哦~'
    )
    
    # 移除当前消息处理器
    for handler in client.dispatcher.groups.get(1, [])[:]:
        if isinstance(handler, MessageHandler) and handler.callback == handle_catgirl_confirmation:
            client.dispatcher.groups[1].remove(handler)
    
    # 设置新的消息过滤器，高优先级(1)确保在其他处理器之前执行
    client.add_handler(MessageHandler(
        handle_catgirl_messages,
        filters.chat(message.chat.id) & filters.user(message.from_user.id)
    ), group=1)

async def handle_catgirl_messages(client, message):
    """处理猫娘消息"""
    # 检查对应的记录是否存在并且状态是confirmed
    record = db_service.get_catgirl_record(message.from_user.id, message.chat.id)
    if not record or record['status'] != 'confirmed':
        # 如果记录不存在或状态不是confirmed，则不处理
        return
    
    # 不再检查消息是否以/开头，任何不包含"喵"的消息都会被删除
    if message.text and "喵" not in message.text:
        # 打印日志以便调试
        print(f"删除不带'喵'的消息: {message.text}, 用户ID: {message.from_user.id}")
        # 执行删除
        try:
            await message.delete()
        except Exception as e:
            print(f"删除消息时发生错误: {str(e)}")

async def cleanup_catgirl_status(client, user_id, group_id):
    """清理猫娘状态"""
    await asyncio.sleep(24 * 60 * 60)  # 等待24小时
    
    # 删除数据库记录
    db_service.delete_catgirl_record(user_id, group_id)
    
    # 移除消息处理器
    for group_id in [1]:  # 检查高优先级组
        for handler in client.dispatcher.groups.get(group_id, [])[:]:
            if isinstance(handler, MessageHandler) and (
                handler.callback == handle_catgirl_confirmation or 
                handler.callback == handle_catgirl_messages
            ):
                client.dispatcher.groups[group_id].remove(handler)
    
    print(f"已清理用户 {user_id} 的猫娘状态")

@auto_delete()
async def confirm_slave_command(client, message):
    """处理/confirm命令，确认成为奴隶"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "无名修士"
    
    # 确认成为奴隶
    result = gang_service.confirm_slave(user_id)
    
    if result['success']:
        master_name = result['master_name']
        return await message.reply(f"✅ {username} 已成为 {master_name} 的奴隶")
    else:
        return await message.reply(result['message'])

@auto_delete()
async def rob_command(client, message):
    """处理/rob命令，用户打劫"""
    try:
        user_id = message.from_user.id
        username = message.from_user.username or message.from_user.first_name or "无名修士"
        
        # 检查是否是回复其他消息
        if not message.reply_to_message:
            return await message.reply("⚠️ 请回复要打劫的用户的消息")
        
        # 获取目标用户ID
        target_message = message.reply_to_message
        if not target_message.from_user or target_message.from_user.is_bot:
            return await message.reply("⚠️ 不能打劫机器人")
        
        target_id = target_message.from_user.id
        target_name = target_message.from_user.username or target_message.from_user.first_name
        
        # 不能打劫自己
        if target_id == user_id:
            return await message.reply("⚠️ 不能打劫自己")
        
        # 检查目标用户是否存在
        target_user = db_service.get_user(target_id)
        if not target_user:
            return await message.reply("⚠️ 对方还未注册")
        
        # 检查自己是否存在
        user = db_service.get_user(user_id)
        if not user:
            db_service.create_user(user_id, username)
        
        # 检查打劫冷却时间
        rob_record = db_service.get_rob_record(user_id)
        if rob_record and rob_record['last_rob']:
            # 计算从上次打劫到现在的时间（秒）
            cooldown_seconds = (datetime.now() - rob_record['last_rob']).total_seconds()
            if cooldown_seconds < 1800:  # 30分钟冷却
                remaining_minutes = max(0, 30 - cooldown_seconds // 60)
                return await message.reply(f"⚠️ 打劫太频繁了，请等待{int(remaining_minutes)}分钟后再试")
        
        # 执行打劫
        result = cultivation_service.rob_user(user_id, target_id)
        
        # 检查是否有特定的错误消息
        if not result['success'] and 'message' in result and '修士' in result['message']:
            return await message.reply(result['message'])
        
        # 构建回复文本
        result_text = (
            f"🗡 {username} 对 {target_name} 发起了打劫！\n"
            f"👤 {username}：{result['robber_stage']} 境界，掷出 {result['robber_roll']}点"
        )
        
        if result['robber_bonus'] > 0:
            result_text += f"(+{result['robber_bonus']})"
        
        result_text += f"\n👤 {target_name}：{result['victim_stage']} 境界，掷出 {result['victim_roll']}点"
        
        if result['victim_bonus'] > 0:
            result_text += f"(+{result['victim_bonus']})"
        
        result_text += "\n\n"
        
        if result['success']:
            points_stolen = result['points_stolen']
            percentage = result['percentage']
            result_text += f"打劫成功！{username} 抢走了 {target_name} {percentage}% 的灵石，共 {points_stolen} 个"
            
            # 添加突破丹信息
            if 'pills_stolen' in result and result['pills_stolen'] > 0:
                result_text += f"，以及 {result['pills_stolen']} 颗突破丹！"
            else:
                result_text += "！"
        else:
            # 优先显示服务返回的特定失败消息（如保护罩提示）
            if 'message' in result and '保护罩' in result['message']:
                result_text += f"{result['message']}"
            elif 'message' in result and '积分未成功转移' in result['message']:
                result_text += "打劫过程中出现意外，积分未成功转移！"
            else:
                result_text += f"打劫失败！{target_name} 成功抵抗了攻击！"
        
        return await message.reply(result_text)
    except Exception as e:
        print(f"处理打劫命令时发生错误: {e}")
        return await message.reply("⚠️ 打劫过程中发生错误，请稍后再试")

@auto_delete()
async def buy_command(client, message):
    """处理/buy命令，购买突破丹"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "无名修士"
    
    # 解析参数
    command_parts = message.text.split()
    if len(command_parts) != 2:
        return await message.reply("⚠️ 格式错误，正确格式: /buy [数量]")
    
    try:
        quantity = int(command_parts[1])
    except ValueError:
        return await message.reply("⚠️ 数量必须是整数")
    
    if quantity <= 0:
        return await message.reply("⚠️ 购买数量必须大于0")
    
    # 计算总价
    price_per_pill = 50
    total_price = quantity * price_per_pill
    
    # 检查用户是否存在
    user = db_service.get_user(user_id)
    if not user:
        db_service.create_user(user_id, username)
        user = db_service.get_user(user_id)
    
    # 检查用户积分是否足够
    if user['points'] < total_price:
        return await message.reply(f"⚠️ 灵石不足！购买 {quantity} 颗突破丹需要 {total_price} 灵石，但你只有 {user['points']} 灵石")
    
    # 扣除积分
    db_service.update_points(user_id, -total_price)
    
    # 增加突破丹
    db_service.update_cultivation_pills(user_id, quantity)
    
    # 获取更新后的信息
    user_cultivation = cultivation_service.get_user_cultivation(user_id)
    current_pills = user_cultivation['pills']
    current_points = db_service.get_user_points(user_id)
    
    return await message.reply(
        f"✅ 购买成功！\n"
        f"购买数量: {quantity} 颗突破丹\n"
        f"花费灵石: {total_price} 个\n"
        f"当前突破丹: {current_pills} 颗\n"
        f"剩余灵石: {current_points} 个"
    )

@auto_delete()
async def si_command(client, message):
    """处理/si命令，发起生死战"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "无名修士"
    
    # 检查是否是回复其他消息
    if not message.reply_to_message:
        return await message.reply("⚠️ 请回复要挑战的用户的消息")
    
    # 获取目标用户ID
    target_message = message.reply_to_message
    if not target_message.from_user or target_message.from_user.is_bot:
        return await message.reply("⚠️ 不能向机器人发起挑战")
    
    target_id = target_message.from_user.id
    target_name = target_message.from_user.username or target_message.from_user.first_name
    
    # 不能挑战自己
    if target_id == user_id:
        return await message.reply("⚠️ 不能向自己发起挑战")
    
    # 检查目标用户是否存在
    target_user = db_service.get_user(target_id)
    if not target_user:
        return await message.reply("⚠️ 对方还未注册")
    
    # 检查自己是否存在
    user = db_service.get_user(user_id)
    if not user:
        db_service.create_user(user_id, username)
    
    # 检查是否已经有进行中的对决
    existing_duel = game_service.get_active_duel(user_id, target_id, message.chat.id)
    if existing_duel:
        return await message.reply("⚠️ 你们之间已经有一场生死战在进行中")
    
    # 创建生死战
    result = game_service.create_duel(user_id, target_id, message.chat.id)
    
    if not result['success']:
        return await message.reply(result['message'])
    
    # 获取最新创建的对决
    duel = game_service.get_active_duel(user_id, target_id, message.chat.id)
    if not duel:
        return await message.reply("⚠️ 创建生死战失败")
    
    # 构建回复文本
    challenge_text = (
        f"天穹阴云如墨，灵山绝巅的罡风撕裂道袍残角。{username}指间凝出三尺青芒，"
        f"剑尖垂落的血珠在翻涌的灵气中化作赤蝶，\"三百年前你碎我金丹时，可曾想过今日？\""
        f"足下青岩寸寸龟裂，九重锁灵阵自云端压下，将整座孤峰罩成囚笼!\n\n"
        f"({username}想和你进行生死战, 你能忍吗?)"
    )
    
    # 创建接受和拒绝的按钮
    buttons = [
        [
            InlineKeyboardButton("忍", callback_data=f"duel_reject_{duel['id']}"),
            InlineKeyboardButton("不忍", callback_data=f"duel_accept_{duel['id']}")
        ]
    ]
    
    # 发送挑战消息
    await client.send_message(
        chat_id=message.chat.id,
        text=challenge_text,
        reply_to_message_id=target_message.id,
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    
    # 删除命令消息
    try:
        await message.delete()
    except Exception as e:
        print(f"删除消息失败: {e}")

@auto_delete(30)  # 飞升命令的消息保留更长时间
async def feisheng_command(client, message):
    """处理/feisheng命令，开启飞升成仙任务"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or "无名修士"
    
    # 获取用户当前修为信息
    cultivation = db_service.get_cultivation(user_id)
    if not cultivation:
        return await message.reply("获取用户修为信息失败，请联系管理员")
    
    # 只有渡劫后期才能飞升
    if cultivation['stage'] != len(CULTIVATION_STAGES) - 1:
        current_stage = CULTIVATION_STAGES[cultivation['stage']] if cultivation['stage'] < len(CULTIVATION_STAGES) else "未知"
        return await message.reply(f"⚠️ 道友当前境界为【{current_stage}】，只有达到【渡劫后期】才能开启飞升任务！")
    
    # 获取或创建飞升任务
    task = db_service.get_ascension_task(user_id)
    if not task:
        try:
            db_service.create_ascension_task(user_id)
            task = db_service.get_ascension_task(user_id)
        except Exception as e:
            print(f"创建飞升任务失败: {e}")
            return await message.reply("创建飞升任务失败，请联系管理员")
    
    # 处理不同阶段的飞升任务
    if task['current_stage'] == 1:
        # 第一关：生死战连胜10场
        return await message.reply(
            "🔥 道友要飞升成仙，需要经历三关，现在开启第一关(武)\n"
            "仙万古无一，势必要踩在他人的血肉上，请与他人生死战连胜10场！\n\n"
            f"当前连胜：{task['duel_wins']}/10"
        )
    elif task['current_stage'] == 2:
        # 第二关：算术题
        num1 = random.randint(100, 999)
        num2 = random.randint(100, 999)
        operation = random.choice(['+', '-'])
        
        if operation == '+':
            result = num1 + num2
            question = f"{num1} + {num2}"
        else:
            # 确保减法结果为正数
            if num1 < num2:
                num1, num2 = num2, num1
            result = num1 - num2
            question = f"{num1} - {num2}"
        
        # 保存正确答案到状态中
        try:
            db_service.update_ascension_task(user_id, math_question=question, math_answer=result)
        except Exception as e:
            print(f"更新飞升任务失败: {e}")
            # 尝试不使用math_question和math_answer字段
            db_service.update_ascension_task(user_id, math_attempts=0)
        
        # 设置消息过滤器，高优先级(1)确保在其他处理器之前执行
        client.add_handler(MessageHandler(
            handle_math_answer,
            filters.chat(message.chat.id) & filters.user(user_id)
        ), group=1)
        
        # 启动计时任务，10秒后自动判定为失败
        client.loop.create_task(math_answer_timeout(client, user_id, message.chat.id))
        
        return await message.reply(
            f"🧠 飞墨横飞，笔笔如神龙，第二关(文)已开启！\n"
            f"请在十秒内答出下列口算题:\n{question} = ？"
        )
    elif task['current_stage'] == 3:
        # 第三关：分享书籍
        return await message.reply(
            "📚 飞墨横飞，笔笔如神龙，大道之音仿佛凝聚成形，还剩最后一关啦！\n"
            f"请分享20本书，当前已分享：{task['shared_books']}/20"
        )
    else:
        # 已完成所有关卡
        if task['current_stage'] >= 4:
            return await message.reply("🎉 恭喜道友已经成功飞升为【地仙】！")
        else:
            # 重置任务状态
            db_service.reset_ascension_task(user_id)
            return await message.reply("🔄 飞升任务状态已重置，请重新开始！")

async def handle_math_answer(client, message):
    """处理算术题回答"""
    # 获取用户ID和消息内容
    user_id = message.from_user.id
    answer_text = message.text.strip()
    
    # 获取飞升任务状态
    task = db_service.get_ascension_task(user_id)
    if not task or task['current_stage'] != 2:
        # 移除当前消息处理器
        for handler in client.dispatcher.groups.get(1, [])[:]:
            if isinstance(handler, MessageHandler) and handler.callback == handle_math_answer:
                client.dispatcher.groups[1].remove(handler)
        return
    
    try:
        # 尝试将回答转换为整数
        user_answer = int(answer_text)
        
        # 处理math_answer字段可能不存在的情况
        correct_answer = None
        if 'math_answer' in task and task['math_answer'] is not None:
            correct_answer = task['math_answer']
        else:
            # 如果字段不存在，假定答案是对的（临时解决方案）
            print(f"警告: math_answer字段不存在，假定用户回答正确")
            correct_answer = user_answer
        
        if user_answer == correct_answer:
            # 回答正确，更新到第三阶段
            try:
                db_service.update_ascension_task(user_id, current_stage=3, math_attempts=0)
            except Exception as e:
                print(f"更新飞升任务阶段失败: {e}")
                # 尝试只更新阶段
                db_service.update_ascension_task(user_id, current_stage=3)
            
            # 移除当前消息处理器
            for handler in client.dispatcher.groups.get(1, [])[:]:
                if isinstance(handler, MessageHandler) and handler.callback == handle_math_answer:
                    client.dispatcher.groups[1].remove(handler)
            
            await message.reply(
                "✅ 回答正确！\n"
                "📚 飞墨横飞，笔笔如神龙，大道之音仿佛凝聚成形，还剩最后一关啦！\n"
                "请分享20本书"
            )
        else:
            # 回答错误，增加失败次数
            attempts = task['math_attempts'] + 1
            try:
                db_service.update_ascension_task(user_id, math_attempts=attempts)
            except Exception as e:
                print(f"更新飞升任务尝试次数失败: {e}")
            
            if attempts >= 3:
                # 三次失败，但不重置整个任务，只重置当前关卡的尝试次数
                try:
                    db_service.update_ascension_task(user_id, math_attempts=0, math_question=None, math_answer=None)
                except Exception as e:
                    print(f"重置飞升任务尝试次数失败: {e}")
                    db_service.update_ascension_task(user_id, math_attempts=0)
                
                # 移除当前消息处理器
                for handler in client.dispatcher.groups.get(1, [])[:]:
                    if isinstance(handler, MessageHandler) and handler.callback == handle_math_answer:
                        client.dispatcher.groups[1].remove(handler)
                
                await message.reply(
                    "❌ 回答错误！这是第三次失败！\n"
                    "🔄 算术挑战暂时失败，请稍后使用/feisheng命令继续尝试第二关。"
                )
            else:
                # 失败但还有机会，重新生成题目
                num1 = random.randint(100, 999)
                num2 = random.randint(100, 999)
                operation = random.choice(['+', '-'])
                
                if operation == '+':
                    result = num1 + num2
                    question = f"{num1} + {num2}"
                else:
                    # 确保减法结果为正数
                    if num1 < num2:
                        num1, num2 = num2, num1
                    result = num1 - num2
                    question = f"{num1} - {num2}"
                
                # 保存新的正确答案
                try:
                    db_service.update_ascension_task(user_id, math_question=question, math_answer=result)
                except Exception as e:
                    print(f"保存新题目答案失败: {e}")
                
                # 启动新的计时任务
                client.loop.create_task(math_answer_timeout(client, user_id, message.chat.id))
                
                await message.reply(
                    f"❌ 回答错误！还有{3-attempts}次机会，请重新回答：\n"
                    f"{question} = ？"
                )
    except ValueError:
        # 输入不是数字
        await message.reply("⚠️ 请输入一个整数作为答案！")

async def math_answer_timeout(client, user_id, chat_id):
    """算术题超时处理"""
    await asyncio.sleep(10)  # 等待10秒
    
    # 获取任务状态
    task = db_service.get_ascension_task(user_id)
    if not task or task['current_stage'] != 2:
        return
    
    # 增加失败次数
    attempts = task['math_attempts'] + 1
    db_service.update_ascension_task(user_id, math_attempts=attempts)
    
    # 移除消息处理器
    for handler in client.dispatcher.groups.get(1, [])[:]:
        if isinstance(handler, MessageHandler) and handler.callback == handle_math_answer:
            client.dispatcher.groups[1].remove(handler)
    
    # 发送超时消息
    if attempts >= 3:
        # 三次失败，但不重置整个任务，只重置当前关卡的尝试次数
        db_service.update_ascension_task(user_id, math_attempts=0, math_question=None, math_answer=None)
        
        await client.send_message(
            chat_id=chat_id,
            text=f"⏱️ 用户 {user_id} 回答超时！这是第三次失败！\n"
                 "🔄 算术挑战暂时失败，请稍后使用/feisheng命令继续尝试第二关。"
        )
    else:
        # 失败但还有机会
        # 生成新题目
        num1 = random.randint(100, 999)
        num2 = random.randint(100, 999)
        operation = random.choice(['+', '-'])
        
        if operation == '+':
            result = num1 + num2
            question = f"{num1} + {num2}"
        else:
            # 确保减法结果为正数
            if num1 < num2:
                num1, num2 = num2, num1
            result = num1 - num2
            question = f"{num1} - {num2}"
        
        # 保存新的正确答案
        db_service.update_ascension_task(user_id, math_question=question, math_answer=result)
        
        # 设置新的消息处理器
        client.add_handler(MessageHandler(
            handle_math_answer,
            filters.chat(chat_id) & filters.user(user_id)
        ), group=1)
        
        # 启动新的计时任务
        client.loop.create_task(math_answer_timeout(client, user_id, chat_id))
        
        await client.send_message(
            chat_id=chat_id,
            text=f"⏱️ 用户 {user_id} 回答超时！还有{3-attempts}次机会，请回答：\n"
                 f"{question} = ？"
        )

# 修改handle_duel_callback函数以支持记录生死战连胜
async def handle_duel_completion(duel_id, winner_id):
    """处理生死战完成后的飞升任务更新"""
    # 获取获胜者的飞升任务状态
    task = db_service.get_ascension_task(winner_id)
    if not task:
        return
    
    # 获取决斗记录
    duel = db_service.get_duel_by_id(duel_id)
    if not duel:
        return
    
    # 获取败者ID
    loser_id = duel['challenger_id'] if duel['winner_id'] == duel['challenged_id'] else duel['challenged_id']
    
    # 处理败者的飞升任务 - 如果在第一阶段则重置连胜
    loser_task = db_service.get_ascension_task(loser_id)
    if loser_task and loser_task['current_stage'] == 1 and loser_task['duel_wins'] > 0:
        # 用户在飞升第一关中输掉了生死战，重置连胜
        db_service.update_ascension_task(loser_id, duel_wins=0)
        print(f"用户{loser_id}在飞升第一关中输掉生死战，连胜重置为0")
    
    # 如果在第一阶段，记录胜利
    if task['current_stage'] == 1:
        success = db_service.record_ascension_duel_win(winner_id, duel_id)
        if success:
            # 重新获取最新的任务状态
            updated_task = db_service.get_ascension_task(winner_id)
            if updated_task and updated_task['duel_wins'] >= 10:
            # 进入第二阶段
                db_service.update_ascension_task(winner_id, current_stage=2)
            print(f"用户{winner_id}在飞升第一关中达成10连胜，进入第二阶段")

@auto_delete(60)  # 保留一段时间便于查看
async def ask_command(client, message):
    """处理/ask命令，向AI提问"""
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    # 提取问题文本
    command_parts = message.text.split(" ", 1)
    if len(command_parts) < 2 or not command_parts[1].strip():
        return await message.reply("⚠️ 格式错误，正确格式: /ask [问题]")
    
    question = command_parts[1].strip()
    
    # 发送"思考中"提示
    thinking_msg = await message.reply("🧠 思考中...")
    
    # 调用AI服务
    result = await ai_service.ask(user_id, question, first_name=first_name, last_name=last_name)
    
    # 删除"思考中"提示
    try:
        await thinking_msg.delete()
    except:
        pass
    
    # 回复结果
    if result["success"]:
        return await message.reply(result["message"])
    else:
        return await message.reply(f"⚠️ AI响应出错: {result['message']}")

@auto_delete(60)  # 保留一段时间便于查看
async def aiconfig_command(client, message):
    """处理/aiconfig命令，配置AI参数"""
    user_id = message.from_user.id
    
    # 检查是否是管理员
    if not admin_service.is_admin(user_id):
        return await message.reply("⚠️ 只有管理员才能执行此操作")
    
    # 解析命令参数
    command_parts = message.text.split(" ", 2)
    if len(command_parts) < 2:
        return await message.reply(
            "⚠️ 格式错误，正确格式:\n"
            "/aiconfig backend [后端地址] - 设置API后端地址\n"
            "/aiconfig key [API密钥] - 设置API密钥\n"
            "/aiconfig model [模型名称] - 设置使用的AI模型\n"
            "/aiconfig reset - 重置AI配置\n"
        )
    
    sub_command = command_parts[1].lower()
    
    if sub_command == "backend" and len(command_parts) == 3:
        # 设置后端地址
        backend_url = command_parts[2].strip()
        ai_service.backend_url = backend_url
        return await message.reply(f"✅ AI后端地址已设置为: {backend_url}")
    
    elif sub_command == "key" and len(command_parts) == 3:
        # 设置API密钥
        api_key = command_parts[2].strip()
        ai_service.api_key = api_key
        return await message.reply("✅ AI API密钥已设置")
    
    elif sub_command == "model" and len(command_parts) == 3:
        # 设置AI模型
        model_name = command_parts[2].strip()
        ai_service.default_model = model_name
        return await message.reply(f"✅ AI模型已设置为: {model_name}")
    
    elif sub_command == "reset":
        # 重置为默认配置
        ai_service.backend_url = AI_BACKEND_URL
        ai_service.api_key = AI_API_KEY
        ai_service.default_model = AI_MODEL
        return await message.reply("✅ AI配置已重置为默认值")
    
    else:
        return await message.reply(
            "⚠️ 格式错误，正确格式:\n"
            "/aiconfig backend [后端地址] - 设置API后端地址\n"
            "/aiconfig key [API密钥] - 设置API密钥\n"
            "/aiconfig model [模型名称] - 设置使用的AI模型\n"
            "/aiconfig reset - 重置AI配置\n"
        )

@auto_delete(10)
async def aireset_command(client, message):
    """处理/aireset命令，重置AI会话"""
    user_id = message.from_user.id
    
    # 重置用户会话历史
    ai_service.reset_conversation(user_id)
    return await message.reply("✅ AI会话已重置")

@auto_delete()
async def shield_help_command(client, message):
    """处理/shield命令，显示保护罩相关信息"""
    help_text = (
        "🛡️ 保护罩功能说明：\n\n"
        "每天上传10本不重复的书籍即可获得保护罩，\n"
        "拥有保护罩后，当天不会被任何用户打劫。\n\n"
        "保护罩有效期：激活当天有效\n"
        "获取方式：每天上传10本不重复的书籍\n"
        "使用/my命令可查看保护罩状态"
    )
    
    return await message.reply(help_text)

@auto_delete()
async def gongde_command(client, message):
    """处理/gongde命令，显示功德榜"""
    # 获取上传书籍最多的前10名用户
    top_uploaders = db_service.get_top_uploaders(10)
    
    if not top_uploaders:
        return await message.reply("功德榜暂无数据")
    
    # 构建功德榜文本
    gongde_text = "📚 功德榜 - 上传书籍最多的修士\n\n"
    
    for i, user in enumerate(top_uploaders, 1):
        # 获取境界名称
        stage_index = user['stage']
        stage_name = "地仙" if stage_index >= len(CULTIVATION_STAGES) else CULTIVATION_STAGES[stage_index]
        
        # 组合用户姓名，优先使用first_name和last_name
        first_name = user.get('first_name', '') or ''
        last_name = user.get('last_name', '') or ''
        full_name = (first_name + " " + last_name).strip()
        username = full_name or user.get('username', '无名修士')
        
        # 添加排名信息
        gongde_text += f"{i}. {username} - {user['total_books_uploaded']} 本\n"
        gongde_text += f"   境界: {stage_name} | 灵石: {user['points']}\n"
    
    return await message.reply(gongde_text)

# 处理回复机器人的消息
async def handle_bot_reply(client, message):
    """处理回复机器人的消息，作为AI问题"""
    # 检查是否是回复机器人自己的消息
    if not message.reply_to_message or not message.reply_to_message.from_user.is_bot:
        return
    
    # 确保回复的是当前机器人
    if message.reply_to_message.from_user.id != client.me.id:
        return
    
    # 检查是否包含命令，如果是命令则不处理
    if message.text.startswith('/'):
        return
    
    user_id = message.from_user.id
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    question = message.text
    
    # 发送"思考中"提示
    thinking_msg = await message.reply("🧠 思考中...")
    
    # 调用AI服务
    result = await ai_service.ask(user_id, question, message.reply_to_message, first_name=first_name, last_name=last_name)
    
    # 删除"思考中"提示
    try:
        await thinking_msg.delete()
    except:
        pass
    
    # 回复结果
    if result["success"]:
        return await message.reply(result["message"])
    else:
        return await message.reply(f"⚠️ AI响应出错: {result['message']}")

# 注册命令处理器
def register_command_handlers(app):
    """注册所有命令处理器"""
    app.add_handler(MessageHandler(start_command, filters.command("start")))
    app.add_handler(MessageHandler(help_command, filters.command("help")))
    app.add_handler(MessageHandler(my_command, filters.command("my")))
    app.add_handler(MessageHandler(checkin_command, filters.command("checkin")))
    app.add_handler(MessageHandler(authorize_group_command, filters.command("auth")))
    app.add_handler(MessageHandler(add_admin_command, filters.command("addadmin")))
    app.add_handler(MessageHandler(add_points_command, filters.command("addpoint")))
    app.add_handler(MessageHandler(sub_points_command, filters.command("subpoint")))
    app.add_handler(MessageHandler(deduct_points_command, filters.command("deduct")))
    app.add_handler(MessageHandler(gua_command, filters.command("gua")))
    app.add_handler(MessageHandler(tiankou_command, filters.command("tiankou")))
    app.add_handler(MessageHandler(tujing_command, filters.command("tujing")))
    app.add_handler(MessageHandler(dajie_command, filters.command("dajie")))
    app.add_handler(MessageHandler(slave_command, filters.command("slave")))
    app.add_handler(MessageHandler(confirm_slave_command, filters.command("confirm")))
    app.add_handler(MessageHandler(rob_command, filters.command("rob")))
    app.add_handler(MessageHandler(buy_command, filters.command("buy")))
    app.add_handler(MessageHandler(si_command, filters.command("si")))
    app.add_handler(MessageHandler(feisheng_command, filters.command("feisheng"))) 
    app.add_handler(MessageHandler(ask_command, filters.command("ask")))
    app.add_handler(MessageHandler(aiconfig_command, filters.command("aiconfig")))
    app.add_handler(MessageHandler(aireset_command, filters.command("aireset")))
    app.add_handler(MessageHandler(shield_help_command, filters.command("shield")))
    app.add_handler(MessageHandler(gongde_command, filters.command("gongde")))
    app.add_handler(MessageHandler(hongbao_command, filters.command("hongbao")))
    app.add_handler(MessageHandler(set_redemption_code_command, filters.command("set")))
    app.add_handler(MessageHandler(redeem_code_command, filters.command("duihuan")))
    
    # 添加回调查询处理器
    app.add_handler(CallbackQueryHandler(handle_hongbao_callback, filters.regex("^hongbao_")))
    
    # 添加回复机器人消息的处理器
    app.add_handler(MessageHandler(handle_bot_reply, filters.text & filters.reply), group=10) 

@auto_delete()
async def hongbao_command(client, message):
    """处理/hongbao命令，发放积分红包"""
    user_id = message.from_user.id
    
    # 解析参数
    command_parts = message.text.split()
    if len(command_parts) != 3:
        return await message.reply("⚠️ 格式错误，正确格式: /hongbao [积分总数] [领取人数]")
    
    try:
        total_amount = int(command_parts[1])
        total_people = int(command_parts[2])
    except ValueError:
        return await message.reply("⚠️ 积分总数和领取人数必须是整数")
    
    # 验证参数
    if total_amount <= 0 or total_people <= 0:
        return await message.reply("⚠️ 积分总数和领取人数必须大于0")
    
    if total_amount < total_people:
        return await message.reply("⚠️ 积分总数必须不少于领取人数，确保每人至少能领到1积分")
    
    # 检查用户积分是否足够
    user_points = db_service.get_user_points(user_id)
    if user_points < total_amount:
        return await message.reply(f"⚠️ 积分不足！你只有 {user_points} 灵石，但需要 {total_amount} 灵石")
    
    # 扣除积分
    db_service.update_points(user_id, -total_amount)
    
    # 生成红包ID
    hongbao_id = str(uuid.uuid4())
    
    # 获取用户名称
    first_name = message.from_user.first_name or ""
    last_name = message.from_user.last_name or ""
    full_name = (first_name + " " + last_name).strip() or message.from_user.username or f"用户{user_id}"
    
    # 创建红包数据
    active_hongbaos[hongbao_id] = {
        "creator_id": user_id,
        "creator_name": full_name,
        "total_amount": total_amount,
        "total_people": total_people,
        "remaining_amount": total_amount,
        "remaining_people": total_people,
        "claimed_users": {},  # 存储已领取用户：{user_id: {amount, first_name, last_name}}
        "chat_id": message.chat.id,
        "created_at": datetime.now(),
        "message_id": None  # 会在发送消息后更新
    }
    
    # 创建红包消息
    buttons = [
        [InlineKeyboardButton("领取红包", callback_data=f"hongbao_{hongbao_id}")]
    ]
    
    # 发送红包消息
    hongbao_msg = await message.reply(
        f"🧧 {full_name} 发了一个积分红包\n\n"
        f"总积分: {total_amount} 灵石\n"
        f"红包个数: {total_people} 个\n\n"
        f"点击下方按钮领取吧！",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    
    # 更新消息ID
    active_hongbaos[hongbao_id]["message_id"] = hongbao_msg.id
    
    # 将红包数据保存到数据库
    save_hongbao_to_db(hongbao_id)
    
    # 置顶消息
    try:
        await client.pin_chat_message(message.chat.id, hongbao_msg.id)
    except Exception as e:
        print(f"置顶红包消息失败: {e}")
    
    # 设置红包过期时间（24小时后）
    asyncio.create_task(expire_hongbao(client, hongbao_id))

async def expire_hongbao(client, hongbao_id, delay=24*60*60):
    """处理红包过期逻辑"""
    await asyncio.sleep(delay)  # 等待指定时间
    
    # 检查红包是否还存在
    if hongbao_id not in active_hongbaos:
        return
    
    hongbao = active_hongbaos[hongbao_id]
    
    # 如果还有剩余积分，返还给发红包的人
    if hongbao["remaining_amount"] > 0:
        db_service.update_points(hongbao["creator_id"], hongbao["remaining_amount"])
        
        try:
            # 更新红包消息
            await client.edit_message_text(
                chat_id=hongbao["chat_id"],
                message_id=hongbao["message_id"],
                text=f"🧧 {hongbao['creator_name']} 发的红包已过期\n\n"
                     f"总积分: {hongbao['total_amount']} 灵石\n"
                     f"已领取: {hongbao['total_amount'] - hongbao['remaining_amount']} 灵石 "
                     f"({hongbao['total_people'] - hongbao['remaining_people']}/{hongbao['total_people']}人)\n"
                     f"剩余 {hongbao['remaining_amount']} 灵石已退还给发红包的人",
                reply_markup=None  # 红包过期不显示按钮
            )
            
            # 解除置顶
            await client.unpin_chat_message(hongbao["chat_id"], hongbao["message_id"])
        except Exception as e:
            print(f"更新过期红包消息失败: {e}")
    
    # 删除红包数据
    del active_hongbaos[hongbao_id]

async def handle_hongbao_callback(client, callback_query):
    """处理红包领取回调"""
    # 获取红包ID
    data = callback_query.data
    hongbao_id = data.split("_")[1]
    
    # 检查红包是否存在
    if hongbao_id not in active_hongbaos:
        await callback_query.answer("红包已过期或不存在", show_alert=True)
        return
    
    hongbao = active_hongbaos[hongbao_id]
    user_id = callback_query.from_user.id
    
    # 检查是否是自己发的红包
    if user_id == hongbao["creator_id"]:
        await callback_query.answer("不能领取自己发的红包", show_alert=True)
        return
    
    # 检查用户是否已经领取过
    if str(user_id) in hongbao["claimed_users"]:
        await callback_query.answer("你已经领取过这个红包了", show_alert=True)
        return
    
    # 检查红包是否还有剩余
    if hongbao["remaining_people"] <= 0:
        await callback_query.answer("红包已被领完", show_alert=True)
        return
    
    # 随机分配积分
    amount = 0
    if hongbao["remaining_people"] == 1:
        # 最后一个人领取剩下的所有积分
        amount = hongbao["remaining_amount"]
    else:
        # 随机分配，确保每人至少1积分，且不超过剩余积分的两倍
        max_amount = min(hongbao["remaining_amount"] - (hongbao["remaining_people"] - 1), 
                          hongbao["remaining_amount"] * 2 // hongbao["remaining_people"])
        amount = random.randint(1, max(1, max_amount))
    
    # 更新红包状态
    hongbao["remaining_amount"] -= amount
    hongbao["remaining_people"] -= 1
    hongbao["claimed_users"][str(user_id)] = {
        "amount": amount,
        "first_name": callback_query.from_user.first_name or "",
        "last_name": callback_query.from_user.last_name or ""
    }
    
    # 保存更新后的红包状态到数据库
    save_hongbao_to_db(hongbao_id)
    
    # 添加积分给用户
    db_service.update_points(user_id, amount)
    
    # 构建已领取用户列表（使用字典的副本避免迭代错误）
    claimed_text = "\n\n已领取用户：\n"
    claimed_users_copy = dict(hongbao["claimed_users"])
    
    for i, (claimed_user_id, user_data) in enumerate(claimed_users_copy.items(), 1):
        # 获取用户名称
        first_name = user_data.get("first_name", "")
        last_name = user_data.get("last_name", "")
        full_name = (first_name + " " + last_name).strip() or f"用户{claimed_user_id}"
        claimed_amount = user_data.get("amount", 0)
        
        claimed_text += f"{i}. {full_name}: {claimed_amount} 灵石\n"
    
    # 更新红包消息
    try:
        if hongbao["remaining_people"] > 0:
            keyboard = [[InlineKeyboardButton("领取红包", callback_data=f"hongbao_{hongbao_id}")]]
            markup = InlineKeyboardMarkup(keyboard)
        else:
            markup = None  # 红包领完后不显示按钮
            
        await client.edit_message_text(
            chat_id=hongbao["chat_id"],
            message_id=hongbao["message_id"],
            text=f"🧧 {hongbao['creator_name']} 发了一个积分红包\n\n"
                 f"总积分: {hongbao['total_amount']} 灵石\n"
                 f"红包个数: {hongbao['total_people']} 个\n"
                 f"已领取: {hongbao['total_amount'] - hongbao['remaining_amount']} 灵石 "
                 f"({hongbao['total_people'] - hongbao['remaining_people']}/{hongbao['total_people']}人)"
                 f"{claimed_text}",
            reply_markup=markup
        )
    except Exception as e:
        print(f"更新红包消息失败: {e}")
    
    # 通知用户领取成功
    await callback_query.answer(f"恭喜你领取了 {amount} 灵石！", show_alert=True)
    
    # 如果红包已经被领完，解除置顶并移除按钮
    if hongbao["remaining_people"] <= 0:
        try:
            await client.unpin_chat_message(hongbao["chat_id"], hongbao["message_id"])
            # 红包被领完，但保留记录24小时
            asyncio.create_task(remove_hongbao_after_delay(hongbao_id))
        except Exception as e:
            print(f"解除红包置顶失败: {e}")

async def remove_hongbao_after_delay(hongbao_id):
    """延迟移除红包数据"""
    await asyncio.sleep(24 * 60 * 60)  # 24小时后移除
    if hongbao_id in active_hongbaos:
        del active_hongbaos[hongbao_id]

@auto_delete()
async def set_redemption_code_command(client, message):
    """处理/set命令，添加兑换码"""
    user_id = message.from_user.id
    
    # 检查是否为管理员
    if not admin_service.is_admin(user_id):
        return await message.reply("此命令仅限管理员使用")
    
    # 解析命令参数
    command_parts = message.text.split()
    if len(command_parts) < 2:
        return await message.reply("使用方法: /set [兑换码]")
    
    redemption_code = command_parts[1]
    
    # 检查兑换码格式是否合法
    if len(redemption_code) < 5 or len(redemption_code) > 30:
        return await message.reply("兑换码长度必须在5-30个字符之间")
    
    # 添加兑换码到数据库
    if db_service.add_redemption_code(redemption_code, user_id):
        # 获取未使用的兑换码数量
        unused_count = db_service.get_redemption_codes_count(used=False)
        return await message.reply(f"兑换码添加成功，当前有 {unused_count} 个可用兑换码")
    else:
        return await message.reply("兑换码添加失败，可能是兑换码已存在")

@auto_delete()
async def redeem_code_command(client, message):
    """处理/duihuan命令，获取兑换码"""
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name or f"用户{user_id}"
    
    # 获取用户信息
    user_info = db_service.get_user(user_id)
    if not user_info:
        return await message.reply("请先使用 /start 命令注册")
    
    # 检查用户积分是否足够
    if user_info['points'] < 3000:
        return await message.reply("灵石不足，获取兑换码需要3000灵石")
    
    # 检查是否在群组中
    is_group = message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]
    
    if is_group:
        # 在群组中，使用内联按钮引导用户到私聊中完成兑换
        # 存储用户兑换请求的会话状态
        # 我们可以通过临时数据在内存中保存这个请求
        # 添加一个按钮，用户点击后会被引导到私聊
        bot_username = (await client.get_me()).username
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "点击获取兑换码", 
                url=f"https://t.me/{bot_username}?start=redeem"
            )]
        ])
        
        # 在群中回复引导消息
        return await message.reply(
            f"您正在申请兑换码（将扣除3000灵石）\n"
            f"为保护您的兑换码安全，请点击下方按钮前往私聊完成兑换。",
            reply_markup=keyboard
        )
    else:
        # 在私聊中，正常处理兑换流程
        # 获取一个未使用的兑换码
        redemption_code = db_service.get_unused_redemption_code()
        if not redemption_code:
            return await message.reply("当前没有可用的兑换码，请稍后再试")
        
        # 扣除用户积分
        if not db_service.update_points(user_id, -3000):
            return await message.reply("扣除积分失败，请稍后再试")
        
        # 标记兑换码为已使用
        if not db_service.mark_redemption_code_used(redemption_code, user_id):
            # 如果标记失败，尝试退还积分
            db_service.update_points(user_id, 3000)
            return await message.reply("获取兑换码失败，已退还积分，请稍后再试")
        
        # 在私聊中发送兑换码
        return await message.reply(
            f"兑换码获取成功，扣除3000灵石\n\n"
            f"兑换码: `{redemption_code}`\n\n"
            f"请复制该兑换码到 @xieloujdBot 机器人中进行兑换使用时长"
        )