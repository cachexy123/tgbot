import os
import hashlib
import random
import asyncio
import functools
from datetime import datetime
from bot.config.config import CULTIVATION_STAGES
from typing import List, Union
from pyrogram.types import Message

def calculate_md5(file_path):
    """计算文件的MD5值"""
    md5_hash = hashlib.md5()
    with open(file_path, "rb") as f:
        # 读取文件块
        for byte_block in iter(lambda: f.read(4096), b""):
            md5_hash.update(byte_block)
    return md5_hash.hexdigest()

def ensure_dir(directory):
    """确保目录存在，不存在则创建"""
    if not os.path.exists(directory):
        os.makedirs(directory)

def format_cultivation_info(stage_index, pills, next_cost):
    """格式化修仙信息"""
    if stage_index < 0 or stage_index >= len(CULTIVATION_STAGES):
        # 如果索引超出数组范围，可能是飞升后的境界
        if stage_index == len(CULTIVATION_STAGES):
            return "【地仙】\n突破丹：{} 个\n您已飞升成仙，位列仙班！\n(飞升后不再掉落境界)".format(pills)
        return "境界信息错误"
    
    stage_name = CULTIVATION_STAGES[stage_index]
    
    # 检查是否是大境界的最后一个小境界
    is_before_major = (stage_index + 1) % 3 == 0 and stage_index < len(CULTIVATION_STAGES) - 1
    
    if is_before_major:
        next_stage = CULTIVATION_STAGES[stage_index + 1]
        pills_needed = 2 ** ((stage_index + 1) // 3)
        return f"【{stage_name}】\n突破丹：{pills} 个\n下一境界：{next_stage}（需要 {next_cost} 灵石和 {pills_needed} 个突破丹）"
    elif stage_index < len(CULTIVATION_STAGES) - 1:
        next_stage = CULTIVATION_STAGES[stage_index + 1]
        return f"【{stage_name}】\n突破丹：{pills} 个\n下一境界：{next_stage}（需要 {next_cost} 灵石）"
    else:
        return f"【{stage_name}】\n突破丹：{pills} 个\n已达到最高境界，可使用/feisheng命令尝试飞升成仙"

def generate_gua_game(level):
    """生成刮刮乐游戏"""
    # 从1到20随机抽取5个数字
    winning_numbers = random.sample(range(1, 21), 5)
    return {
        'level': level,
        'numbers': winning_numbers
    }

def is_chinese_text(text, min_chars=3):
    """检查文本是否包含足够多的汉字"""
    chinese_chars = 0
    for char in text:
        if '\u4e00' <= char <= '\u9fff':
            chinese_chars += 1
    return chinese_chars >= min_chars

def format_leaderboard(players):
    """格式化排行榜信息"""
    if not players:
        return "暂无排名信息"
    
    result = "✨ 天骄榜 ✨\n"
    for i, player in enumerate(players):
        if 0 <= player['stage'] < len(CULTIVATION_STAGES):
            stage = CULTIVATION_STAGES[player['stage']]
        elif player['stage'] == len(CULTIVATION_STAGES):
            stage = "地仙"
        else:
            stage = "未知"
        
        # 优先使用first_name和last_name的组合
        first_name = player.get('first_name', '') or ''
        last_name = player.get('last_name', '') or ''
        full_name = (first_name + " " + last_name).strip()
        username = full_name or player.get('username', '无名修士')
        
        result += f"{i+1}. {username} - {stage} (灵石: {player['points']})\n"
    
    return result

def roll_random_event():
    """随机生成事件类型"""
    rand = random.random()
    if rand < 0.02:  # 2%概率获得突破丹
        return "pill"
    elif rand < 0.05:  # 3%概率获得灵石
        return "good"
    elif rand < 0.07:  # 2%概率丢失灵石
        return "bad"
    elif rand < 0.09:  # 2%概率直接突破
        return "breakthrough"
    elif rand < 0.10:  # 1%概率走火入魔
        return "deviation"
    else:
        return None

def is_allowed_file(filename, allowed_extensions):
    """检查文件是否是允许的类型"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in [ext.lstrip('.') for ext in allowed_extensions]

def format_time_ago(timestamp):
    """格式化时间为多久之前"""
    if not timestamp:
        return "从未"
    
    now = datetime.now()
    delta = now - timestamp
    
    if delta.days > 0:
        return f"{delta.days}天前"
    elif delta.seconds >= 3600:
        return f"{delta.seconds // 3600}小时前"
    elif delta.seconds >= 60:
        return f"{delta.seconds // 60}分钟前"
    else:
        return f"{delta.seconds}秒前"

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
            if hasattr(message, 'delete'):
                await message.delete()
        except Exception as e:
            print(f"删除消息失败: {e}")

async def auto_delete_reply(reply, delay=10):
    """只删除机器人的回复消息，保留原始消息
    
    Args:
        reply: 机器人回复的消息
        delay: 延迟删除的时间（秒）
    """
    await asyncio.sleep(delay)
    try:
        # 只删除回复消息
        await reply.delete()
    except Exception as e:
        print(f"删除回复消息失败: {e}")

def auto_delete(delay=10):
    """自动删除命令和回复的装饰器
    
    Args:
        delay: 延迟时间(秒)
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(client, message, *args, **kwargs):
            # 执行原函数
            result = await func(client, message, *args, **kwargs)
            
            # 如果函数返回了消息列表用于删除，则使用它
            if isinstance(result, list) and all(isinstance(m, Message) for m in result):
                messages_to_delete = result
            # 如果函数返回单个消息对象用于删除
            elif isinstance(result, Message):
                messages_to_delete = [message, result]
            # 如果函数返回了包含消息列表的元组，第一个元素是返回值
            elif isinstance(result, tuple) and len(result) >= 2 and isinstance(result[1], list):
                messages_to_delete = result[1]
                result = result[0]
            # 默认只删除命令消息
            else:
                messages_to_delete = [message]
            
            # 延迟删除
            client.loop.create_task(auto_delete_messages(messages_to_delete, delay))
            
            return result
        return wrapper
    return decorator 