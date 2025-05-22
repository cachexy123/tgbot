from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from pyrogram.handlers import CallbackQueryHandler
from bot.services.game_service import game_service
from bot.services.db_service import db_service
import re
import json
import pyrogram
import asyncio
import random
from datetime import datetime

# 处理回调函数，接收回调数据并决定下一步操作
async def callback_handler(client, callback_query):
    """处理所有回调查询"""
    data = callback_query.data
    
    # 处理刮刮乐猜数字回调
    if data.startswith("gua_guess_"):
        await handle_gua_guess(client, callback_query)
    
    # 处理刮刮乐取消回调
    elif data == "gua_cancel":
        await handle_gua_cancel(client, callback_query)
    
    # 处理生死战接受回调
    elif data.startswith("duel_accept_"):
        await handle_duel_accept(client, callback_query)
    
    # 处理生死战拒绝回调
    elif data.startswith("duel_reject_"):
        await handle_duel_reject(client, callback_query)
    
    # 处理生死战抽牌回调
    elif data.startswith("duel_draw_"):
        await handle_duel_draw(client, callback_query)
    
    # 处理生死战结牌回调
    elif data.startswith("duel_stand_"):
        await handle_duel_stand(client, callback_query)
    
    # 处理书籍列表翻页回调
    elif data.startswith("book_list_"):
        # 这些回调由book_handlers.py中注册的处理器处理
        pass
    
    # 处理书籍搜索翻页回调
    elif data.startswith("book_search_"):
        # 这些回调由book_handlers.py中注册的处理器处理
        pass
    
    # 其他回调处理...
    else:
        await callback_query.answer("未知的操作")

async def handle_gua_guess(client, callback_query):
    """处理刮刮乐猜数字回调"""
    # 获取用户信息
    user_id = callback_query.from_user.id
    
    # 解析选择的数字
    choice = int(callback_query.data.replace("gua_guess_", ""))
    
    # 确认游戏并获取结果
    result = game_service.guess_number(user_id, choice)
    
    if not result['success']:
        try:
            await callback_query.answer(result['message'], show_alert=True)
        except pyrogram.errors.exceptions.flood_420.FloodWait as e:
            print(f"FloodWait: 需要等待 {e.value} 秒")
            # 减少等待时间，但不低于1秒
            adjusted_wait = max(1, e.value // 2)
            await asyncio.sleep(adjusted_wait)
            try:
                await callback_query.answer(result['message'], show_alert=True)
            except Exception as ex:
                print(f"回答回调时出错: {str(ex)}")
        return
    
    # 构建结果文本
    result_text = (
        f"🎮 刮刮乐游戏结果\n"
        f"您选择的数字: {choice}\n"
        f"幸运数字: {', '.join(map(str, result['winning_numbers']))}\n\n"
    )
    
    # 获取最新的积分
    current_points = db_service.get_user_points(user_id)
    
    if result['win']:
        result_text += (
            f"🎉 恭喜，您猜对了！\n"
            f"奖励: {result['reward']} 灵石\n"
            f"当前灵石: {current_points}"
        )
    else:
        result_text += (
            f"💔 很遗憾，您没有猜中\n"
            f"当前灵石: {current_points}"
        )
    
    # 更新原始消息，移除按钮
    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            await callback_query.edit_message_text(
                result_text,
                reply_markup=None
            )
            break
        except pyrogram.errors.exceptions.flood_420.FloodWait as e:
            print(f"FloodWait: 需要等待 {e.value} 秒来更新消息")
            retry_count += 1
            if retry_count < max_retries:
                # 减少等待时间，但不低于1秒
                adjusted_wait = max(1, e.value // 2)
                await asyncio.sleep(adjusted_wait)
            else:
                print("达到最大重试次数，无法更新消息")
                break
        except Exception as e:
            print(f"更新消息时出错: {str(e)}")
            break
    
    # 如果是猜对了，不显示气泡通知
    # 如果是猜错了，显示气泡通知
    try:
        await callback_query.answer(
            "已更新游戏结果" if result['win'] else "猜错了，再接再厉！", 
            show_alert=not result['win']
        )
    except pyrogram.errors.exceptions.flood_420.FloodWait as e:
        print(f"FloodWait: 需要等待 {e.value} 秒来回答回调")
        # 减少等待时间，但不低于1秒
        adjusted_wait = max(1, e.value // 2)
        await asyncio.sleep(adjusted_wait)
        try:
            await callback_query.answer(
                "已更新游戏结果" if result['win'] else "猜错了，再接再厉！", 
                show_alert=not result['win']
            )
        except Exception as ex:
            print(f"回答回调时出错: {str(ex)}")

async def handle_gua_cancel(client, callback_query):
    """处理刮刮乐取消回调"""
    # 获取用户信息
    user_id = callback_query.from_user.id
    
    # 取消游戏
    result = game_service.cancel_game(user_id)
    
    # 更新原始消息
    max_retries = 3
    retry_count = 0
    while retry_count < max_retries:
        try:
            await callback_query.edit_message_text(
                "🛑 游戏已取消，积分已退还" if result['success'] else "⚠️ 无法取消游戏",
                reply_markup=None
            )
            break
        except pyrogram.errors.exceptions.flood_420.FloodWait as e:
            print(f"FloodWait: 需要等待 {e.value} 秒来更新消息")
            retry_count += 1
            if retry_count < max_retries:
                # 减少等待时间，但不低于1秒
                adjusted_wait = max(1, e.value // 2)
                await asyncio.sleep(adjusted_wait)
            else:
                print("达到最大重试次数，无法更新消息")
                break
        except Exception as e:
            print(f"更新消息时出错: {str(e)}")
            break
    
    # 显示通知
    try:
        await callback_query.answer(
            "游戏已取消，积分已退还" if result['success'] else "无法取消游戏", 
            show_alert=True
        )
    except pyrogram.errors.exceptions.flood_420.FloodWait as e:
        print(f"FloodWait: 需要等待 {e.value} 秒来回答回调")
        # 减少等待时间，但不低于1秒
        adjusted_wait = max(1, e.value // 2)
        await asyncio.sleep(adjusted_wait)
        try:
            await callback_query.answer(
                "游戏已取消，积分已退还" if result['success'] else "无法取消游戏", 
                show_alert=True
            )
        except Exception as ex:
            print(f"回答回调时出错: {str(ex)}")

async def handle_duel_accept(client, callback_query):
    """处理生死战接受回调"""
    # 获取用户信息
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username or callback_query.from_user.first_name
    
    # 解析对决ID
    duel_id = int(callback_query.data.replace("duel_accept_", ""))
    
    # 获取对决信息
    duel = db_service.get_duel_by_id(duel_id)
    if not duel:
        await callback_query.answer("找不到对应的生死战", show_alert=True)
        return
    
    # 检查是否是被挑战者
    if user_id != duel['challenged_id']:
        await callback_query.answer("只有被挑战者才能接受挑战", show_alert=True)
        return
    
    # 检查对决状态
    if duel['status'] != 'waiting':
        await callback_query.answer("该挑战已经被响应过了", show_alert=True)
        return
    
    # 接受挑战
    result = game_service.accept_duel(duel_id)
    
    if not result['success']:
        await callback_query.answer(result['message'], show_alert=True)
        return
    
    # 获取挑战者信息
    challenger = db_service.get_user(duel['challenger_id'])
    challenger_name = challenger['username'] if challenger and challenger['username'] else f"用户{duel['challenger_id']}"
    
    # 构建游戏信息文本
    duel_text = (
        f"⚔️ 生死战已开始！\n"
        f"挑战者({challenger_name}) vs 被挑战者({username})\n\n"
        f"初始牌:\n"
        f"🎮 {challenger_name}: {', '.join(result['challenger_cards'])} (点数: {result['challenger_points']})\n"
        f"🎮 {username}: {', '.join(result['challenged_cards'])} (点数: {result['challenged_points']})\n\n"
        f"当前回合: {challenger_name}"
    )
    
    # 创建游戏操作按钮
    buttons = [
        [
            InlineKeyboardButton("抽牌", callback_data=f"duel_draw_{duel_id}"),
            InlineKeyboardButton("结牌", callback_data=f"duel_stand_{duel_id}")
        ]
    ]
    
    # 更新原始消息
    await callback_query.edit_message_text(
        duel_text,
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    
    await callback_query.answer("你接受了挑战，生死战开始！")

async def handle_duel_reject(client, callback_query):
    """处理生死战拒绝回调"""
    # 获取用户信息
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username or callback_query.from_user.first_name
    
    # 解析对决ID
    duel_id = int(callback_query.data.replace("duel_reject_", ""))
    
    # 获取对决信息
    duel = db_service.get_duel_by_id(duel_id)
    if not duel:
        await callback_query.answer("找不到对应的生死战", show_alert=True)
        return
    
    # 检查是否是被挑战者
    if user_id != duel['challenged_id']:
        await callback_query.answer("只有被挑战者才能拒绝挑战", show_alert=True)
        return
    
    # 检查对决状态
    if duel['status'] != 'waiting':
        await callback_query.answer("该挑战已经被响应过了", show_alert=True)
        return
    
    # 拒绝挑战
    result = game_service.reject_duel(duel_id)
    
    if not result['success']:
        await callback_query.answer(result['message'], show_alert=True)
        return
    
    # 获取挑战者信息
    challenger = db_service.get_user(duel['challenger_id'])
    challenger_name = challenger['username'] if challenger and challenger['username'] else f"用户{duel['challenger_id']}"
    
    # 更新原始消息
    await callback_query.edit_message_text(
        f"在众人的笑声中, {username}灰溜溜的跑了",
        reply_markup=None
    )
    
    await callback_query.answer("你选择了忍，已拒绝挑战")

async def handle_duel_draw(client, callback_query):
    """处理生死战抽牌回调"""
    # 获取用户信息
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username or callback_query.from_user.first_name
    
    # 解析对决ID
    duel_id = int(callback_query.data.replace("duel_draw_", ""))
    
    # 获取对决信息
    duel = db_service.get_duel_by_id(duel_id)
    if not duel:
        await callback_query.answer("找不到对应的生死战", show_alert=True)
        return
    
    # 检查用户是否参与该对决
    if user_id != duel['challenger_id'] and user_id != duel['challenged_id']:
        await callback_query.answer("你不是该对决的参与者", show_alert=True)
        return
    
    # 检查对决状态
    if duel['status'] != 'playing':
        await callback_query.answer("该对决已经结束", show_alert=True)
        return
    
    # 检查是否是当前回合的玩家
    if user_id != duel['current_turn']:
        await callback_query.answer("现在不是你的回合", show_alert=True)
        return
    
    # 抽牌
    result = game_service.draw_card(duel_id, user_id)
    
    if not result['success']:
        await callback_query.answer(result['message'], show_alert=True)
        return
    
    # 获取更新后的对决信息
    updated_duel = db_service.get_duel_by_id(duel_id)
    
    # 更新消息
    await update_duel_message(client, callback_query, updated_duel, result)

async def handle_duel_stand(client, callback_query):
    """处理生死战结牌回调"""
    # 获取用户信息
    user_id = callback_query.from_user.id
    username = callback_query.from_user.username or callback_query.from_user.first_name
    
    # 解析对决ID
    duel_id = int(callback_query.data.replace("duel_stand_", ""))
    
    # 获取对决信息
    duel = db_service.get_duel_by_id(duel_id)
    if not duel:
        await callback_query.answer("找不到对应的生死战", show_alert=True)
        return
    
    # 检查用户是否参与该对决
    if user_id != duel['challenger_id'] and user_id != duel['challenged_id']:
        await callback_query.answer("你不是该对决的参与者", show_alert=True)
        return
    
    # 检查对决状态
    if duel['status'] != 'playing':
        await callback_query.answer("该对决已经结束", show_alert=True)
        return
    
    # 检查是否是当前回合的玩家
    if user_id != duel['current_turn']:
        await callback_query.answer("现在不是你的回合", show_alert=True)
        return
    
    # 结牌
    result = game_service.stand(duel_id, user_id)
    
    if not result['success']:
        await callback_query.answer(result['message'], show_alert=True)
        return
    
    # 获取更新后的对决信息
    updated_duel = db_service.get_duel_by_id(duel_id)
    
    # 更新消息
    await update_duel_message(client, callback_query, updated_duel, result)

async def update_duel_message(client, callback_query, duel, result=None):
    """更新生死战消息"""
    # 获取挑战者和被挑战者信息
    challenger = db_service.get_user(duel['challenger_id'])
    challenged = db_service.get_user(duel['challenged_id'])
    
    challenger_name = challenger['username'] if challenger and challenger['username'] else f"用户{duel['challenger_id']}"
    challenged_name = challenged['username'] if challenged and challenged['username'] else f"用户{duel['challenged_id']}"
    
    # 解析牌组
    challenger_cards = json.loads(duel['challenger_cards']) if duel['challenger_cards'] else []
    challenged_cards = json.loads(duel['challenged_cards']) if duel['challenged_cards'] else []
    
    # 计算点数
    challenger_points = game_service.calculate_card_points(challenger_cards)
    challenged_points = game_service.calculate_card_points(challenged_cards)
    
    # 构建状态文本
    if duel['status'] == 'playing':
        if duel['current_turn'] == duel['challenger_id']:
            current_turn = challenger_name
        else:
            current_turn = challenged_name
            
        duel_text = (
            f"⚔️ 生死战进行中！\n"
            f"挑战者({challenger_name}) vs 被挑战者({challenged_name})\n\n"
            f"当前牌:\n"
            f"🎮 {challenger_name}: {', '.join(challenger_cards)} "
            f"(点数: {challenger_points}) "
            f"{'[已结牌]' if duel['challenger_stand'] else ''}\n"
            f"🎮 {challenged_name}: {', '.join(challenged_cards)} "
            f"(点数: {challenged_points}) "
            f"{'[已结牌]' if duel['challenged_stand'] else ''}\n\n"
            f"当前回合: {current_turn}"
        )
        
        # 如果刚抽了牌，显示抽到了什么
        if result and 'card' in result:
            duel_text += f"\n\n最新抽牌: {result['card']}"
        
        # 创建游戏操作按钮
        buttons = [
            [
                InlineKeyboardButton("抽牌", callback_data=f"duel_draw_{duel['id']}"),
                InlineKeyboardButton("结牌", callback_data=f"duel_stand_{duel['id']}")
            ]
        ]
        
        # 更新消息
        await callback_query.edit_message_text(
            duel_text,
            reply_markup=InlineKeyboardMarkup(buttons)
        )
        
        # 如果刚抽了牌且爆牌了，显示提示
        if result and result.get('busted', False):
            await callback_query.answer(f"爆牌了！点数超过21点({result['points']})", show_alert=True)
        else:
            await callback_query.answer("操作成功")
    else:
        # 游戏结束
        if duel['winner_id'] == duel['challenger_id']:
            winner_name = challenger_name
            loser_name = challenged_name
        elif duel['winner_id'] == duel['challenged_id']:
            winner_name = challenged_name
            loser_name = challenger_name
        else:
            winner_name = None
        
        if winner_name:
            # 获取双方资源信息
            winner = db_service.get_user(duel['winner_id'])
            winner_cultivation = db_service.get_cultivation(duel['winner_id'])
            winner_points = winner['points']
            winner_pills = winner_cultivation['pills'] if winner_cultivation else 0
            
            # 构建结果文本
            duel_text = (
                f"⚔️ 生死战结束！\n"
                f"挑战者({challenger_name}) vs 被挑战者({challenged_name})\n\n"
                f"最终牌:\n"
                f"🎮 {challenger_name}: {', '.join(challenger_cards)} "
                f"(点数: {challenger_points})\n"
                f"🎮 {challenged_name}: {', '.join(challenged_cards)} "
                f"(点数: {challenged_points})\n\n"
                f"胜者: {winner_name}\n"
                f"胜者当前灵石: {winner_points}\n"
                f"胜者当前突破丹: {winner_pills}"
            )
        else:
            # 平局
            duel_text = (
                f"⚔️ 生死战结束！\n"
                f"挑战者({challenger_name}) vs 被挑战者({challenged_name})\n\n"
                f"最终牌:\n"
                f"🎮 {challenger_name}: {', '.join(challenger_cards)} "
                f"(点数: {challenger_points})\n"
                f"🎮 {challenged_name}: {', '.join(challenged_cards)} "
                f"(点数: {challenged_points})\n\n"
                f"结果: 平局"
            )
        
        # 更新消息
        await callback_query.edit_message_text(
            duel_text,
            reply_markup=None
        )
        
        # 显示结果提示
        if winner_name:
            await callback_query.answer(f"{winner_name} 赢得了生死战！", show_alert=True)
        else:
            await callback_query.answer("生死战以平局结束", show_alert=True)

async def handle_duel_draw_callback(client, callback_query, duel_id):
    """处理生死战平局回调"""
    duel = db_service.get_duel_by_id(duel_id)
    if not duel:
        await callback_query.answer("生死战已不存在", show_alert=True)
        return
    
    # 设置平局结果
    result = game_service.set_duel_draw(duel_id)
    if not result['success']:
        await callback_query.answer(result['message'], show_alert=True)
        return
    
    # 设置消息为平局
    await update_duel_message(client, callback_query, duel)
    await callback_query.answer("生死战平局，双方和解")

# 在获取玩家获胜后调用命令处理中的handle_duel_completion函数
async def handle_duel_winner(client, callback_query, duel_id, winner_id, winner_points, loser_id, loser_points, bust_limit, message=None):
    """处理生死战获胜"""
    # 更新数据库
    success = db_service.update_duel(
        duel_id,
        status='finished',
        winner_id=winner_id
    )
    
    # 处理奖励
    game_service.handle_duel_reward(duel_id)
    
    # 获取最新的决斗信息
    duel = db_service.get_duel_by_id(duel_id)
    
    # 更新消息
    if message:
        await update_duel_message(client, callback_query, duel, {
            'challenger_points': winner_points if duel['challenger_id'] == winner_id else loser_points,
            'challenged_points': winner_points if duel['challenged_id'] == winner_id else loser_points,
            'winner_id': winner_id,
            'challenger_bust_limit': bust_limit,
            'challenged_bust_limit': bust_limit
        })
    else:
        await update_duel_message(client, callback_query, duel)
    
    # 提示获胜信息
    await callback_query.answer("游戏结束，您胜利了！" if callback_query.from_user.id == winner_id else "游戏结束，您输了！", show_alert=True)
    
    # 处理飞升任务
    try:
        from bot.handlers.command_handlers import handle_duel_completion
        asyncio.create_task(handle_duel_completion(duel_id, winner_id))
    except (ImportError, AttributeError) as e:
        print(f"回调处理中导入或调用handle_duel_completion函数失败: {e}")

async def handle_duel_accept_callback(client, callback_query):
    """处理接受生死战挑战"""
    # 解析对决ID
    duel_id = int(callback_query.data.split('_')[2])
    
    # 获取对决信息
    duel = db_service.get_duel_by_id(duel_id)
    if not duel:
        await callback_query.answer("生死战已不存在", show_alert=True)
        return
    
    # 检查是否是被挑战者
    if callback_query.from_user.id != duel['challenged_id']:
        await callback_query.answer("你不是被挑战者，不能接受挑战", show_alert=True)
        return
    
    # 检查状态是否是等待中
    if duel['status'] != 'waiting':
        await callback_query.answer("生死战已经开始或已结束", show_alert=True)
        return
    
    # 更新状态为进行中，并设置当前回合为挑战者
    db_service.update_duel(
        duel_id,
        status='playing',
        current_turn=duel['challenger_id'],
        last_action_time=datetime.now()
    )
    
    # 生成初始卡片
    challenger_card = random.choice(list(range(1, 11)))
    challenged_card = random.choice(list(range(1, 11)))
    
    # 更新卡片信息
    db_service.update_duel(
        duel_id,
        challenger_cards=str(challenger_card),
        challenged_cards=str(challenged_card)
    )
    
    # 获取对手信息
    challenger = db_service.get_user(duel['challenger_id'])
    challenger_name = challenger['username'] if challenger and 'username' in challenger else f"用户{duel['challenger_id']}"
    
    challenged = db_service.get_user(duel['challenged_id'])
    challenged_name = challenged['username'] if challenged and 'username' in challenged else f"用户{duel['challenged_id']}"
    
    # 创建按钮
    markup = create_duel_buttons(duel_id, duel['challenger_id'])
    
    # 获取更新后的对决信息
    updated_duel = db_service.get_duel_by_id(duel_id)
    
    # 更新消息内容
    duel_text = (
        f"⚔️ 生死战对决！\n"
        f"挑战者({challenger_name}) vs 被挑战者({challenged_name})\n\n"
        f"当前牌:\n"
        f"🎮 {challenger_name}: {challenger_card} (点数: {challenger_card})\n"
        f"🎮 {challenged_name}: {challenged_card} (点数: {challenged_card})\n\n"
        f"当前回合: {challenger_name}"
    )
    
    await callback_query.edit_message_text(
        duel_text,
        reply_markup=markup
    )
    
    await callback_query.answer("你已接受挑战，游戏开始！", show_alert=True)

# 注册回调处理器
def register_callback_handlers(app):
    """注册所有回调处理器"""
    app.add_handler(CallbackQueryHandler(callback_handler)) 