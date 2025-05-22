import random
from datetime import datetime
from bot.services.db_service import db_service

# 大乐透游戏状态
class LotteryService:
    def __init__(self):
        """初始化大乐透服务"""
        self.current_numbers = None  # 当前期的中奖号码
        self.lottery_message_id = None  # 当前置顶公告的消息ID
        self.current_pool_amount = 100000  # 初始奖池金额
        self.current_bet_amount = 0  # 当前期下注总额
        self.bets = {}  # 当前期的下注记录 {user_id: [(numbers, bet_count), ...]}
        
        # 确保数据库中有大乐透表
        self._ensure_lottery_tables()
        
        # 从数据库加载当前奖池金额
        pool_info = self.get_lottery_pool()
        if pool_info:
            self.current_pool_amount = pool_info['amount']
    
    def _ensure_lottery_tables(self):
        """确保数据库中有大乐透相关的表"""
        # 这个方法会在db_service中实现
        db_service.ensure_lottery_tables()
    
    def start_new_lottery(self):
        """开始新一期大乐透，生成随机数字"""
        # 生成3个0-9的随机数字
        self.current_numbers = [random.randint(0, 9) for _ in range(3)]
        
        # 重置下注记录
        self.bets = {}
        self.current_bet_amount = 0
        
        # 保存到数据库
        db_service.save_lottery_numbers(self.current_numbers)
        
        return self.current_numbers
    
    def place_bet(self, user_id, username, numbers, bet_count):
        """用户下注
        
        Args:
            user_id: 用户ID
            username: 用户名
            numbers: 用户选择的3个数字
            bet_count: 下注数量
            
        Returns:
            dict: 包含操作结果和信息
        """
        # 检查下注格式
        if len(numbers) != 3:
            return {"success": False, "message": "请选择3个数字"}
        
        # 检查数字是否有效
        try:
            nums = [int(n) for n in numbers]
            for n in nums:
                if n < 0 or n > 9:
                    return {"success": False, "message": "数字必须在0-9之间"}
        except ValueError:
            return {"success": False, "message": "请输入有效的数字"}
        
        # 检查下注数量
        try:
            bet_count = int(bet_count)
            if bet_count <= 0:
                return {"success": False, "message": "下注数量必须大于0"}
        except ValueError:
            return {"success": False, "message": "请输入有效的下注数量"}
        
        # 计算所需积分
        cost = bet_count * 100
        
        # 检查用户积分是否足够
        user_points = db_service.get_user_points(user_id)
        if user_points < cost:
            return {
                "success": False, 
                "message": f"灵石不足！下{bet_count}注需要{cost}灵石，但你只有{user_points}灵石"
            }
        
        # 扣除用户积分
        new_points = db_service.update_points(user_id, -cost)
        
        # 更新奖池金额和下注记录
        self.current_bet_amount += cost
        self.current_pool_amount += cost
        
        # 更新奖池金额到数据库
        db_service.update_lottery_pool(self.current_pool_amount)
        
        # 添加到下注记录
        if user_id not in self.bets:
            self.bets[user_id] = []
        self.bets[user_id].append((numbers, bet_count))
        
        # 保存下注记录到数据库
        db_service.save_lottery_bet(user_id, username, numbers, bet_count, cost)
        
        return {
            "success": True,
            "message": f"下注成功！\n已下注: {numbers} {bet_count}注\n花费灵石: {cost}\n剩余灵石: {new_points}",
            "new_pool_amount": self.current_pool_amount,
            "bet_amount": cost
        }
    
    def draw_lottery(self):
        """开奖并发放奖励
        
        Returns:
            dict: 包含开奖结果和中奖信息
        """
        if not self.current_numbers:
            return {"success": False, "message": "当前没有进行中的大乐透"}
        
        # 获取所有下注记录
        all_bets = db_service.get_all_lottery_bets()
        
        # 中奖结果
        winners = {
            "first": [],  # 一等奖 (三个数字全中)
            "second": []  # 二等奖 (两个数字相同)
        }
        
        winning_numbers = ''.join(map(str, self.current_numbers))
        total_reward = 0
        
        # 检查每个下注是否中奖
        for bet in all_bets:
            user_id = bet['user_id']
            username = bet['username']
            bet_numbers = bet['numbers']
            bet_count = bet['bet_count']
            
            # 将字符串转换为列表
            user_nums = [int(n) for n in bet_numbers]
            
            # 计算匹配数
            matches = sum(1 for i in range(3) if user_nums[i] == self.current_numbers[i])
            
            if matches == 3:
                # 一等奖 - 每注50000灵石
                reward = bet_count * 50000
                winners["first"].append({
                    "user_id": user_id,
                    "username": username,
                    "numbers": bet_numbers,
                    "bet_count": bet_count,
                    "reward": reward
                })
                total_reward += reward
                
                # 发放奖励
                db_service.update_points(user_id, reward)
                
            elif matches == 2:
                # 二等奖 - 每注5000灵石
                reward = bet_count * 5000
                winners["second"].append({
                    "user_id": user_id,
                    "username": username,
                    "numbers": bet_numbers,
                    "bet_count": bet_count,
                    "reward": reward
                })
                total_reward += reward
                
                # 发放奖励
                db_service.update_points(user_id, reward)
        
        # 更新奖池金额
        self.current_pool_amount -= total_reward
        if self.current_pool_amount < 100000:
            self.current_pool_amount = 100000  # 确保奖池最低有10万灵石
        
        # 更新数据库中的奖池金额
        db_service.update_lottery_pool(self.current_pool_amount)
        
        # 重置当前游戏状态
        db_service.reset_lottery_bets()
        
        # 返回开奖结果
        return {
            "success": True,
            "winning_numbers": winning_numbers,
            "winners": winners,
            "total_reward": total_reward,
            "new_pool_amount": self.current_pool_amount
        }
    
    def set_lottery_message_id(self, message_id):
        """设置大乐透公告消息ID"""
        self.lottery_message_id = message_id
        db_service.save_lottery_message_id(message_id)
    
    def get_lottery_message_id(self):
        """获取当前大乐透公告消息ID"""
        if not self.lottery_message_id:
            # 从数据库加载
            self.lottery_message_id = db_service.get_lottery_message_id()
        return self.lottery_message_id
    
    def get_lottery_pool(self):
        """获取当前奖池信息"""
        return db_service.get_lottery_pool()
    
    def get_current_numbers(self):
        """获取当前的中奖号码"""
        if not self.current_numbers:
            # 从数据库加载
            numbers = db_service.get_lottery_numbers()
            if numbers:
                self.current_numbers = numbers
        return self.current_numbers

# 创建全局服务实例
lottery_service = LotteryService() 