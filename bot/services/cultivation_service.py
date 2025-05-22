import random
from bot.services.db_service import db_service
from bot.config.config import CULTIVATION_STAGES
from bot.utils.helpers import roll_random_event

class CultivationService:
    def __init__(self):
        self.db = db_service
    
    def get_user_cultivation(self, user_id):
        """获取用户修仙信息"""
        cultivation = self.db.get_cultivation(user_id)
        if not cultivation:
            return None
        
        return {
            'stage_index': cultivation['stage'],
            'stage_name': CULTIVATION_STAGES[cultivation['stage']] if cultivation['stage'] < len(CULTIVATION_STAGES) else "未知",
            'pills': cultivation['pills'],
            'next_cost': cultivation['next_cost']
        }
    
    def process_message(self, user_id, message_text):
        """处理用户消息，可能触发随机事件"""
        try:
            # 记录用户事件
            self.db.record_user_event(user_id)
            
            # 随机生成事件
            event = roll_random_event()
            
            if not event:
                return None
                
            # 获取用户当前信息
            user_points = self.db.get_user_points(user_id)
            cultivation = self.db.get_cultivation(user_id)
            
            if not cultivation:
                return None
                
            # 检查用户是否已成仙（成仙后不再触发灵石相关奇遇）
            has_ascended = cultivation['stage'] >= len(CULTIVATION_STAGES)
            
            # 成仙后不触发好事件和坏事件（灵石奇遇）
            if has_ascended and (event == 'good' or event == 'bad'):
                return None
                
            result = {
                'event_type': event,
                'message': None
            }
            
            # 处理不同事件
            if event == 'pill':
                self.db.update_cultivation_pills(user_id, 1)
                result['message'] = "✨ 机缘巧合之下，你发现了一颗闪闪发光的突破丹！"
                
            elif event == 'good':
                # 改为获得当前灵石的1%到5%
                if user_points <= 0:
                    points_gain = 10  # 如果用户没有灵石，给予固定数额
                else:
                    min_percentage = 1
                    max_percentage = 5
                    percentage = random.randint(min_percentage, max_percentage)
                    points_gain = max(int(user_points * percentage / 100), 10)  # 至少获得10灵石
                
                success = self.db.update_points(user_id, points_gain)
                if not success:
                    print(f"更新积分失败（好事件）: 用户ID {user_id}")
                    return None
                result['message'] = f"💰 你遇到了一处秘境，获得了{points_gain}灵石！"
                result['points_change'] = points_gain
                
            elif event == 'bad':
                # 改为损失当前灵石的2%到6%
                if user_points <= 0:
                    return None  # 无灵石可损失，不触发事件
                
                min_percentage = 2
                max_percentage = 6
                percentage = random.randint(min_percentage, max_percentage)
                points_loss = max(int(user_points * percentage / 100), 10)  # 至少损失10灵石
                points_loss = min(points_loss, user_points)  # 不能超过用户现有积分
                
                if points_loss > 0:
                    success = self.db.update_points(user_id, -points_loss)
                    if not success:
                        print(f"更新积分失败（坏事件）: 用户ID {user_id}")
                        return None
                    result['message'] = f"💸 不幸遇到了劫匪，失去了{points_loss}灵石！"
                    result['points_change'] = -points_loss
                else:
                    result = None  # 没有积分可以损失，不触发事件
                    
            elif event == 'breakthrough':
                current_stage = cultivation['stage']
                if current_stage < len(CULTIVATION_STAGES) - 1:
                    success = self.db.update_cultivation_stage(user_id, current_stage + 1)
                    if not success:
                        print(f"更新修为失败（突破）: 用户ID {user_id}")
                        return None
                    new_stage = CULTIVATION_STAGES[current_stage + 1]
                    result['message'] = f"🌟 福至心灵，你顿悟天道真意，修为直接突破到了【{new_stage}】！"
                    result['new_stage'] = new_stage
                else:
                    result = None  # 已经是最高境界，不触发事件
                    
            elif event == 'deviation':
                current_stage = cultivation['stage']
                # 检查用户是否已飞升成仙（境界为len(CULTIVATION_STAGES)）
                if current_stage > 0 and current_stage < len(CULTIVATION_STAGES):
                    success = self.db.update_cultivation_stage(user_id, current_stage - 1)
                    if not success:
                        print(f"更新修为失败（跌落）: 用户ID {user_id}")
                        return None
                    new_stage = CULTIVATION_STAGES[current_stage - 1]
                    result['message'] = f"⚠️ 修炼走火入魔，境界跌落到了【{new_stage}】！"
                    result['new_stage'] = new_stage
                else:
                    # 已飞升成仙或处于最低境界，不触发事件
                    result = None
            
            return result
        except Exception as e:
            print(f"处理消息事件时发生错误: {e}")
            return None
    
    def attempt_breakthrough(self, user_id):
        """尝试突破修为"""
        return self.db.attempt_breakthrough(user_id)
    
    def rob_user(self, robber_id, victim_id):
        """用户打劫"""
        try:
            # 获取两个用户的修为
            robber_cult = self.db.get_cultivation(robber_id)
            victim_cult = self.db.get_cultivation(victim_id)
            
            if not robber_cult or not victim_cult:
                return {'success': False, 'message': '用户信息不存在'}
            
            # 获取受害者积分
            victim_points = self.db.get_user_points(victim_id)
            if victim_points <= 0:
                return {'success': False, 'message': '对方一穷二白，没有灵石可抢'}
            
            # 检查是否涉及成仙用户
            robber_has_ascended = robber_cult['stage'] >= len(CULTIVATION_STAGES)
            victim_has_ascended = victim_cult['stage'] >= len(CULTIVATION_STAGES)
            
            # 安全获取境界名称
            robber_stage = "地仙" if robber_has_ascended else CULTIVATION_STAGES[robber_cult['stage']]
            victim_stage = "地仙" if victim_has_ascended else CULTIVATION_STAGES[victim_cult['stage']]
            
            # 创建基本结果对象
            result = {
                'success': False,
                'robber_stage': robber_stage,
                'victim_stage': victim_stage,
                'robber_roll': 0,
                'victim_roll': 0,
                'robber_bonus': 0,
                'victim_bonus': 0
            }
            
            # 检查受害者是否有保护罩 - 移到创建结果对象之后
            if self.db.has_active_shield(victim_id):
                result['message'] = '对方今日上传了十本书籍，获得了保护罩，无法被打劫'
                return result
            
            # 成仙用户不能打劫凡人
            if robber_has_ascended and not victim_has_ascended:
                result['message'] = "道友已位列仙班，怎可欺凌凡人？此举有伤天和，不可为之。"
                return result
            
            # 凡人打劫成仙用户将受到天罚
            if not robber_has_ascended and victim_has_ascended:
                # 使打劫者境界下降一级
                current_stage = robber_cult['stage']
                if current_stage > 0:
                    success = self.db.update_cultivation_stage(robber_id, current_stage - 1)
                    new_stage = CULTIVATION_STAGES[current_stage - 1]
                    result['message'] = f"天雷滚滚，大胆！一道雷直直的劈下来，你的境界跌落到了【{new_stage}】！"
                    result['punishment'] = True
                    result['new_stage'] = new_stage
                    return result
                else:
                    result['message'] = "天雷滚滚，大胆！幸好你境界太低，天道不忍过于责罚，饶你一命。"
                    return result
            
            # 计算两人修为差
            stage_diff = robber_cult['stage'] - victim_cult['stage']
            
            # 检查境界范围是否有效
            if robber_cult['stage'] >= len(CULTIVATION_STAGES) or victim_cult['stage'] >= len(CULTIVATION_STAGES):
                # 如果双方都是仙，则不影响打劫规则
                if not (robber_has_ascended and victim_has_ascended):
                    result['message'] = '境界信息错误，无法进行打劫'
                    return result
                # 双方都是仙，正常打劫
                stage_diff = 0
            
            # 检查境界差距
            if stage_diff >= 2:
                result['message'] = f"道友，欺负弱小非君子所为。{result['victim_stage']}的修士，岂是你这等{result['robber_stage']}大能该出手的？"
                return result
            elif stage_diff <= -2:
                result['message'] = f"道友，你可知天外有天？{result['victim_stage']}的修士，岂是你这等{result['robber_stage']}小辈能招惹的？"
                return result
            
            # 更新打劫记录
            self.db.update_rob_record(robber_id)
            
            # 基础dice加成，修为高的一方额外加3
            robber_bonus = 3 if stage_diff > 0 else 0
            victim_bonus = 3 if stage_diff < 0 else 0
            
            # 投骰子，1-6的随机数
            robber_roll = random.randint(1, 6) + robber_bonus
            victim_roll = random.randint(1, 6) + victim_bonus
            
            # 更新结果对象
            result.update({
                'robber_roll': robber_roll,
                'victim_roll': victim_roll,
                'robber_bonus': robber_bonus,
                'victim_bonus': victim_bonus
            })
            
            # 判断胜负
            if robber_roll > victim_roll:
                # 抢劫成功，随机抢走一定比例的积分
                percentage = random.randint(10, 50)
                points_stolen = int(victim_points * percentage / 100)
                
                # 检查对方是否有突破丹
                victim_pills = victim_cult['pills']
                pills_stolen = 0
                
                if victim_pills > 0:
                    # 随机抢走1-2颗突破丹，但不超过对方拥有的数量
                    max_pills = min(victim_pills, 2)
                    pills_stolen = random.randint(1, max_pills) if max_pills > 1 else 1
                
                try:
                    # 更新积分
                    self.db.update_points(robber_id, points_stolen)
                    self.db.update_points(victim_id, -points_stolen)
                    
                    # 更新突破丹
                    if pills_stolen > 0:
                        self.db.update_cultivation_pills(robber_id, pills_stolen)
                        self.db.update_cultivation_pills(victim_id, -pills_stolen)
                    
                    result['success'] = True
                    result['points_stolen'] = points_stolen
                    result['percentage'] = percentage
                    result['pills_stolen'] = pills_stolen
                    
                    # 构建结果消息
                    result['message'] = f"抢劫成功！抢走了对方{percentage}%的灵石，共{points_stolen}个"
                    if pills_stolen > 0:
                        result['message'] += f"，以及{pills_stolen}颗突破丹"
                except Exception as e:
                    print(f"打劫过程中更新资源失败: {e}")
                    result['success'] = False
                    result['message'] = "打劫过程中出现意外，资源未成功转移"
            else:
                result['success'] = False
                result['message'] = "打劫失败！对方成功抵抗了你的攻击"
            
            return result
        except Exception as e:
            print(f"打劫过程中发生错误: {e}")
            # 安全的获取境界名称，避免索引越界
            robber_stage = "地仙"
            victim_stage = "地仙"
            
            if robber_cult and 'stage' in robber_cult:
                if 0 <= robber_cult['stage'] < len(CULTIVATION_STAGES):
                    robber_stage = CULTIVATION_STAGES[robber_cult['stage']]
                elif robber_cult['stage'] >= len(CULTIVATION_STAGES):
                    robber_stage = "地仙"
            
            if victim_cult and 'stage' in victim_cult:
                if 0 <= victim_cult['stage'] < len(CULTIVATION_STAGES):
                    victim_stage = CULTIVATION_STAGES[victim_cult['stage']]
                elif victim_cult['stage'] >= len(CULTIVATION_STAGES):
                    victim_stage = "地仙"
            
            return {
                'success': False, 
                'message': '打劫过程中发生错误，请稍后再试',
                'robber_stage': robber_stage,
                'victim_stage': victim_stage,
                'robber_roll': 0,
                'victim_roll': 0,
                'robber_bonus': 0,
                'victim_bonus': 0
            }
    
    def get_top_cultivators(self, limit=10):
        """获取修为排行榜"""
        return self.db.get_top_players(limit)

# 创建全局修仙服务实例
cultivation_service = CultivationService() 