import random
from datetime import datetime, date, timedelta
import json
from bot.config.config import GUA_MAX_TIMES, GUA_PRIZES, GUA_WINNING_MULTIPLIER, CULTIVATION_STAGES
from bot.services.db_service import db_service
from bot.utils.helpers import generate_gua_game
import asyncio

class GameService:
    def __init__(self):
        self.db = db_service
        # 保存每个用户正在进行的刮刮乐游戏
        self.active_games = {}
        # 用于生死战的扑克牌
        self.cards = ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K'] * 4
    
    def check_in(self, user_id):
        """执行签到"""
        # 检查用户是否存在
        user = self.db.get_user(user_id)
        if not user:
            return {"success": False, "message": "用户不存在，请先注册"}
        
        # 检查是否有修仙记录
        cultivation = self.db.get_cultivation(user_id)
        if not cultivation:
            # 如果没有修仙记录，尝试初始化
            success = self.db.initialize_user_cultivation(user_id)
            if not success:
                return {"success": False, "message": "初始化修仙信息失败，请联系管理员"}
        
        # 调用签到方法
        result = self.db.check_in(user_id)
        return result
    
    def get_checkin_status(self, user_id):
        """获取用户签到状态"""
        status = self.db.get_checkin_status(user_id)
        
        # 如果没有获取到状态，返回默认值
        if not status:
            return {
                "consecutive_days": 0,
                "last_checkin": None,
                "today_checked": False
            }
            
        return status
    
    def start_gua_game(self, user_id, level):
        """开始刮刮乐游戏"""
        # 检查用户今天已使用的次数
        gua_record = self.db.get_gua_records(user_id)
        times_used = gua_record['times_used'] if gua_record else 0
        
        if times_used >= GUA_MAX_TIMES:
            return {
                'success': False,
                'message': f"今天的刮刮乐次数已用完（{times_used}/{GUA_MAX_TIMES}）"
            }
        
        # 检查用户积分是否足够
        user_points = self.db.get_user_points(user_id)
        if user_points < level:
            return {
                'success': False,
                'message': f"灵石不足，需要{level}灵石，当前只有{user_points}灵石"
            }
        
        # 扣除用户积分
        self.db.update_points(user_id, -level)
        
        # 生成游戏
        game = generate_gua_game(level)
        self.active_games[user_id] = game
        
        # 更新使用记录
        self.db.update_gua_records(user_id)
        
        # 返回游戏信息
        remaining = GUA_MAX_TIMES - (times_used + 1)
        return {
            'success': True,
            'message': f"开始刮刮乐游戏（投入{level}灵石），今天还剩{remaining}次机会",
            'game': game
        }
    
    def guess_number(self, user_id, number):
        """猜数字"""
        # 检查用户是否有正在进行的游戏
        if user_id not in self.active_games:
            return {
                'success': False,
                'message': "没有正在进行的刮刮乐游戏，请先开始游戏"
            }
        
        game = self.active_games[user_id]
        level = game['level']
        winning_numbers = game['numbers']
        
        # 检查用户猜的数字是否在范围内
        if number < 1 or number > 20:
            return {
                'success': False,
                'message': "请猜1到20之间的数字"
            }
        
        # 清除活动游戏
        del self.active_games[user_id]
        
        # 判断是否猜中
        if number in winning_numbers:
            # 猜中了，奖励10倍积分
            reward = level * GUA_WINNING_MULTIPLIER
            self.db.update_points(user_id, reward)
            
            return {
                'success': True,
                'win': True,
                'message': f"恭喜！猜中了数字{number}，获得{reward}灵石！",
                'reward': reward,
                'winning_numbers': winning_numbers
            }
        else:
            return {
                'success': True,
                'win': False,
                'message': f"很遗憾，没有猜中。幸运数字是：{', '.join(map(str, winning_numbers))}",
                'winning_numbers': winning_numbers
            }
    
    def cancel_game(self, user_id):
        """取消游戏并退还积分"""
        if user_id not in self.active_games:
            return {
                'success': False,
                'message': "没有正在进行的刮刮乐游戏"
            }
        
        game = self.active_games[user_id]
        level = game['level']
        
        # 退还积分
        self.db.update_points(user_id, level)
        
        # 清除活动游戏
        del self.active_games[user_id]
        
        return {
            'success': True,
            'message': f"已取消游戏，退还{level}灵石"
        }
    
    def get_active_game(self, user_id):
        """获取用户当前进行的游戏"""
        return self.active_games.get(user_id)
    
    def get_gua_records(self, user_id):
        """获取用户刮刮乐记录"""
        records = self.db.get_gua_records(user_id)
        
        # 如果没有获取到记录，返回默认值
        if not records:
            return {
                "times_used": 0,
                "remaining": 3,  # 每天默认3次
                "date": None
            }
            
        # 计算剩余次数
        remaining = 3 - records['times_used']
        records['remaining'] = max(0, remaining)
        
        return records
    
    # ========== 生死战功能 ==========
    def create_duel(self, challenger_id, challenged_id, group_id):
        """创建生死战游戏"""
        # 检查是否已经有进行中的对决
        existing_duel = self.get_active_duel(challenger_id, challenged_id, group_id)
        if existing_duel:
            return {
                'success': False,
                'message': "已经有一场生死战在进行中"
            }
        
        # 获取双方的修为信息
        challenger_cultivation = self.db.get_cultivation(challenger_id)
        challenged_cultivation = self.db.get_cultivation(challenged_id)
        
        if not challenger_cultivation or not challenged_cultivation:
            return {
                'success': False,
                'message': "获取修为信息失败"
            }
        
        # 检查是否为凡夫俗子（境界为0），不允许参与生死战
        if challenger_cultivation['stage'] == 0:
            return {
                'success': False,
                'message': "凡夫俗子不能参与生死战，请先提升境界"
            }
        
        if challenged_cultivation['stage'] == 0:
            return {
                'success': False,
                'message': "对方是凡夫俗子，不能参与生死战"
            }
        
        try:
            # 创建新对决记录
            self.db.create_duel_game(challenger_id, challenged_id, group_id)
            
            return {
                'success': True,
                'message': "生死战发起成功"
            }
        except Exception as e:
            print(f"创建生死战时出错: {e}")
            return {
                'success': False,
                'message': "创建生死战失败"
            }
            
    def get_active_duel(self, challenger_id=None, challenged_id=None, group_id=None):
        """获取进行中的生死战"""
        return self.db.get_active_duel(challenger_id, challenged_id, group_id)
    
    def accept_duel(self, duel_id):
        """接受生死战挑战并开始游戏"""
        duel = self.db.get_duel_by_id(duel_id)
        if not duel:
            return {
                'success': False,
                'message': "找不到对应的生死战"
            }
        
        if duel['status'] != 'waiting':
            return {
                'success': False,
                'message': "该生死战已经开始或结束"
            }
        
        # 洗牌
        shuffled_cards = self.cards.copy()
        random.shuffle(shuffled_cards)
        
        # 发牌
        challenger_cards = [shuffled_cards.pop(), shuffled_cards.pop()]
        challenged_cards = [shuffled_cards.pop(), shuffled_cards.pop()]
        
        # 更新对决状态为开始
        success = self.db.update_duel(
            duel_id,
            status='playing',
            current_turn=duel['challenger_id'],
            challenger_cards=json.dumps(challenger_cards),
            challenged_cards=json.dumps(challenged_cards),
            last_action_time=datetime.now()
        )
        
        if not success:
            return {
                'success': False,
                'message': "开始生死战失败"
            }
        
        challenger_points = self.calculate_card_points(challenger_cards)
        challenged_points = self.calculate_card_points(challenged_cards)
        
        return {
            'success': True,
            'message': "生死战已开始",
            'duel': self.db.get_duel_by_id(duel_id),
            'challenger_cards': challenger_cards,
            'challenged_cards': challenged_cards,
            'challenger_points': challenger_points,
            'challenged_points': challenged_points
        }
    
    def reject_duel(self, duel_id):
        """拒绝生死战挑战"""
        duel = self.db.get_duel_by_id(duel_id)
        if not duel:
            return {
                'success': False,
                'message': "找不到对应的生死战"
            }
        
        if duel['status'] != 'waiting':
            return {
                'success': False,
                'message': "该生死战已经开始或结束"
            }
        
        # 更新对决状态为结束，没有赢家
        success = self.db.update_duel(
            duel_id,
            status='finished'
        )
        
        if not success:
            return {
                'success': False,
                'message': "取消生死战失败"
            }
        
        return {
            'success': True,
            'message': "生死战已拒绝"
        }
    
    def calculate_card_points(self, cards, bust_limit=21):
        """计算牌组点数，可以自定义爆牌上限"""
        points = 0
        ace_count = 0
        
        for card in cards:
            if card == 'A':
                points += 11
                ace_count += 1
            elif card in ['J', 'Q', 'K']:
                points += 10
            else:
                points += int(card)
        
        # 如果点数超过上限且有A，则将A当作1点
        while points > bust_limit and ace_count > 0:
            points -= 10
            ace_count -= 1
        
        return points
    
    def check_duel_timeout(self, duel_id):
        """检查生死战是否超时"""
        duel = self.db.get_duel_by_id(duel_id)
        if not duel:
            print(f"生死战ID {duel_id} 不存在")
            return False
        
        # 检查上次操作时间
        last_action_time = duel['last_action_time']
        if not last_action_time:
            print(f"生死战ID {duel_id} 没有记录上次操作时间")
            return False
        
        now = datetime.now()
        time_diff = (now - last_action_time).total_seconds()
        
        print(f"处理生死战ID {duel_id}, 状态: {duel['status']}, 已经过 {time_diff:.1f} 秒")
        
        # 处理等待接受的生死战
        if duel['status'] == 'waiting':
            if time_diff > 60:  # 1分钟超时
                print(f"生死战ID {duel_id} 等待接受超时(>60秒)，自动取消")
                # 自动拒绝生死战
                success = self.db.update_duel(
                    duel_id,
                    status='finished',
                    winner_id=None
                )
                return success
            return False
        
        # 处理进行中的生死战
        elif duel['status'] == 'playing':
            if time_diff > 120:  # 2分钟超时
                # 确定当前回合的玩家
                current_turn_id = duel['current_turn']
                
                # 超时者输掉比赛
                winner_id = duel['challenged_id'] if current_turn_id == duel['challenger_id'] else duel['challenger_id']
                
                print(f"生死战ID {duel_id} 游戏中超时(>120秒)，用户{current_turn_id}失败，用户{winner_id}获胜")
                
                # 更新数据库
                success = self.db.update_duel(
                    duel_id,
                    status='finished',
                    winner_id=winner_id
                )
                
                if success:
                    # 处理资源转移
                    reward_result = self.handle_duel_reward(duel_id)
                    print(f"生死战ID {duel_id} 资源转移结果: {'成功' if reward_result else '失败'}")
                    return True
                else:
                    print(f"生死战ID {duel_id} 更新状态失败")
                    return False
            else:
                print(f"生死战ID {duel_id} 尚未超时，仍在进行中")
        
        return False
    
    def draw_card(self, duel_id, user_id):
        """抽牌"""
        duel = self.db.get_duel_by_id(duel_id)
        if not duel:
            return {
                'success': False,
                'message': "找不到对应的生死战"
            }
        
        if duel['status'] != 'playing':
            return {
                'success': False,
                'message': "该生死战已经结束"
            }
        
        if duel['current_turn'] != user_id:
            return {
                'success': False,
                'message': "现在不是你的回合"
            }
        
        # 获取双方修为信息用于计算爆牌上限
        challenger_cultivation = self.db.get_cultivation(duel['challenger_id'])
        challenged_cultivation = self.db.get_cultivation(duel['challenged_id'])
        
        # 确定是挑战者还是被挑战者
        is_challenger = user_id == duel['challenger_id']
        
        # 计算大境界差距并调整爆牌上限
        challenger_major_level = challenger_cultivation['stage'] // 3
        challenged_major_level = challenged_cultivation['stage'] // 3
        major_diff = challenger_major_level - challenged_major_level
        
        # 根据境界差距调整爆牌上限
        challenger_bust_limit = 21
        challenged_bust_limit = 21
        
        if major_diff >= 2:
            # 挑战者比被挑战者高2个以上大境界，提高爆牌上限
            challenger_bust_limit += major_diff - 1  # 差2个提高1点，差3个提高2点，以此类推
        elif major_diff <= -2:
            # 被挑战者比挑战者高2个以上大境界，提高爆牌上限
            challenged_bust_limit += abs(major_diff) - 1
        
        # 获取当前牌组
        if is_challenger:
            cards = json.loads(duel['challenger_cards'])
            bust_limit = challenger_bust_limit
        else:
            cards = json.loads(duel['challenged_cards'])
            bust_limit = challenged_bust_limit
        
        # 随机抽一张牌
        new_card = random.choice(self.cards)
        cards.append(new_card)
        
        # 检查是否爆牌，使用调整后的爆牌上限
        points = self.calculate_card_points(cards, bust_limit)
        busted = points > bust_limit
        
        # 更新牌组
        update_data = {
            'last_action_time': datetime.now()
        }
        
        if is_challenger:
            update_data['challenger_cards'] = json.dumps(cards)
            next_turn = duel['challenged_id']
        else:
            update_data['challenged_cards'] = json.dumps(cards)
            next_turn = duel['challenger_id']
        
        # 如果爆牌，直接结束游戏
        if busted:
            update_data['status'] = 'finished'
            update_data['winner_id'] = duel['challenged_id'] if is_challenger else duel['challenger_id']
        else:
            update_data['current_turn'] = next_turn
        
        # 更新数据库
        success = self.db.update_duel(duel_id, **update_data)
        
        if not success:
            return {
                'success': False,
                'message': "抽牌失败"
            }
        
        # 如果爆牌了，处理资源转移和境界变化
        if busted:
            self.handle_duel_reward(duel_id)
        
        return {
            'success': True,
            'message': "抽牌成功",
            'card': new_card,
            'points': points,
            'busted': busted,
            'cards': cards,
            'bust_limit': bust_limit  # 返回调整后的爆牌上限
        }
    
    def stand(self, duel_id, user_id):
        """选择不抽牌"""
        duel = self.db.get_duel_by_id(duel_id)
        if not duel:
            return {
                'success': False,
                'message': "找不到对应的生死战"
            }
        
        if duel['status'] != 'playing':
            return {
                'success': False,
                'message': "该生死战已经结束"
            }
        
        if duel['current_turn'] != user_id:
            return {
                'success': False,
                'message': "现在不是你的回合"
            }
        
        # 获取双方修为信息用于计算爆牌上限
        challenger_cultivation = self.db.get_cultivation(duel['challenger_id'])
        challenged_cultivation = self.db.get_cultivation(duel['challenged_id'])
        
        # 计算大境界差距并调整爆牌上限
        challenger_major_level = challenger_cultivation['stage'] // 3
        challenged_major_level = challenged_cultivation['stage'] // 3
        major_diff = challenger_major_level - challenged_major_level
        
        # 根据境界差距调整爆牌上限
        challenger_bust_limit = 21
        challenged_bust_limit = 21
        
        if major_diff >= 2:
            # 挑战者比被挑战者高2个以上大境界，提高爆牌上限
            challenger_bust_limit += major_diff - 1
        elif major_diff <= -2:
            # 被挑战者比挑战者高2个以上大境界，提高爆牌上限
            challenged_bust_limit += abs(major_diff) - 1
            
        # 确定是挑战者还是被挑战者
        is_challenger = user_id == duel['challenger_id']
        
        # 更新数据
        update_data = {
            'last_action_time': datetime.now()
        }
        
        if is_challenger:
            update_data['challenger_stand'] = True
            next_turn = duel['challenged_id']
        else:
            update_data['challenged_stand'] = True
            next_turn = duel['challenger_id']
        
        # 如果双方都选择结牌，结束游戏
        if (is_challenger and duel['challenged_stand']) or (not is_challenger and duel['challenger_stand']):
            update_data['status'] = 'finished'
            
            # 计算分数确定赢家
            challenger_cards = json.loads(duel['challenger_cards'])
            challenged_cards = json.loads(duel['challenged_cards'])
            
            challenger_points = self.calculate_card_points(challenger_cards, challenger_bust_limit)
            challenged_points = self.calculate_card_points(challenged_cards, challenged_bust_limit)
            
            # 计算赢家
            if challenger_points > challenger_bust_limit:  # 挑战者爆牌
                update_data['winner_id'] = duel['challenged_id']
            elif challenged_points > challenged_bust_limit:  # 被挑战者爆牌
                update_data['winner_id'] = duel['challenger_id']
            elif challenger_points > challenged_points:  # 挑战者点数大
                update_data['winner_id'] = duel['challenger_id']
            elif challenged_points > challenger_points:  # 被挑战者点数大
                update_data['winner_id'] = duel['challenged_id']
            else:  # 平局
                update_data['winner_id'] = None
        else:
            update_data['current_turn'] = next_turn
        
        # 更新数据库
        success = self.db.update_duel(duel_id, **update_data)
        
        if not success:
            return {
                'success': False,
                'message': "操作失败"
            }
        
        # 如果游戏结束，处理资源转移和境界变化
        if 'status' in update_data and update_data['status'] == 'finished':
            self.handle_duel_reward(duel_id)
            
            return {
                'success': True,
                'message': "生死战结束",
                'challenger_points': challenger_points,
                'challenged_points': challenged_points,
                'winner_id': update_data.get('winner_id'),
                'challenger_bust_limit': challenger_bust_limit,
                'challenged_bust_limit': challenged_bust_limit
            }
        
        return {
            'success': True,
            'message': "已选择不抽牌"
        }
    
    def handle_duel_reward(self, duel_id):
        """处理生死战奖励"""
        duel = self.db.get_duel_by_id(duel_id)
        if not duel or duel['status'] != 'finished':
            return False
        
        # 如果没有赢家（平局），不处理资源转移和境界变化
        if not duel['winner_id']:
            return True
            
        # 获取赢家和输家ID
        winner_id = duel['winner_id']
        loser_id = duel['challenger_id'] if winner_id == duel['challenged_id'] else duel['challenged_id']
        
        # 获取输家的资源
        loser_points = self.db.get_user_points(loser_id)
        loser_cultivation = self.db.get_cultivation(loser_id)
        loser_pills = loser_cultivation['pills'] if loser_cultivation else 0
        
        # 转移积分
        if loser_points > 0:
            self.db.update_points(loser_id, -loser_points)
            self.db.update_points(winner_id, loser_points)
        
        # 转移突破丹
        if loser_pills > 0:
            self.db.update_cultivation_pills(loser_id, -loser_pills)
            self.db.update_cultivation_pills(winner_id, loser_pills)
        
        # 处理境界变化
        winner_cultivation = self.db.get_cultivation(winner_id)
        if loser_cultivation and winner_cultivation:
            # 检查输家是否已飞升成仙（境界为len(CULTIVATION_STAGES)）
            if loser_cultivation['stage'] > 0 and loser_cultivation['stage'] < len(CULTIVATION_STAGES):
                # 输家100%降低一个小境界，但如果已飞升成仙则不降低
                self.db.update_cultivation_stage(loser_id, loser_cultivation['stage'] - 1)
                
            # 赢家50%概率提升一个小境界
            if random.random() < 0.5 and winner_cultivation['stage'] < len(CULTIVATION_STAGES) - 1:
                self.db.update_cultivation_stage(winner_id, winner_cultivation['stage'] + 1)
        
        # 调用飞升任务处理函数
        try:
            # 导入handle_duel_completion函数
            from bot.handlers.command_handlers import handle_duel_completion
            # 创建异步任务来处理飞升任务
            asyncio.create_task(handle_duel_completion(duel_id, winner_id))
        except (ImportError, AttributeError) as e:
            print(f"导入或调用handle_duel_completion函数失败: {e}")
        
        return True

# 创建全局游戏服务实例
game_service = GameService() 