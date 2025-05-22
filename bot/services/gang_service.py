from datetime import datetime, date, timedelta
from bot.services.db_service import db_service

class GangService:
    def __init__(self):
        self.db = db_service
        self.current_leader = None
        self.leader_points = {}  # 记录帮主连任天数和奖励
    
    def get_gang_leader(self):
        """获取当前帮主信息"""
        return self.db.get_gang_leader()
    
    def update_gang_leader(self):
        """更新帮主，返回新的帮主信息"""
        new_leader = self.get_gang_leader()
        
        # 没有合适的帮主
        if not new_leader:
            self.current_leader = None
            self.leader_points = {}
            return None
        
        leader_id = new_leader['user_id']
        
        # 如果是同一个帮主连任
        if self.current_leader and self.current_leader['user_id'] == leader_id:
            # 连任天数加1，奖励每天增加100
            days = self.leader_points.get(leader_id, {'days': 0, 'reward': 0})
            days['days'] += 1
            days['reward'] = days['days'] * 100  # 天数 * 100作为奖励
            self.leader_points[leader_id] = days
            
            # 给帮主发放奖励
            reward = days['reward']
            self.db.update_points(leader_id, reward)
            
            new_leader['consecutive_days'] = days['days']
            new_leader['reward'] = reward
        else:
            # 新帮主，重置记录
            self.leader_points[leader_id] = {'days': 1, 'reward': 100}
            
            # 给新帮主发放初始奖励
            self.db.update_points(leader_id, 100)
            
            new_leader['consecutive_days'] = 1
            new_leader['reward'] = 100
        
        self.current_leader = new_leader
        return new_leader
    
    def set_slave(self, master_id, slave_id, group_id):
        """帮主设置奴隶"""
        # 检查是否是帮主
        leader = self.get_gang_leader()
        if not leader or leader['user_id'] != master_id:
            return {
                'success': False, 
                'message': '只有帮主才能设置奴隶'
            }
        
        # 检查奴隶是否存在
        slave = self.db.get_user(slave_id)
        if not slave:
            return {
                'success': False, 
                'message': '找不到指定的用户'
            }
        
        # 不能设置自己为奴隶
        if master_id == slave_id:
            return {
                'success': False, 
                'message': '不能设置自己为奴隶'
            }
        
        # 尝试设置奴隶
        result = self.db.update_slave_record(master_id, slave_id, group_id)
        if not result:
            return {
                'success': False, 
                'message': '今天你已经指定过奴隶了'
            }
        
        return {
            'success': True, 
            'message': f'成功将用户设为奴隶，等待对方确认',
            'slave_name': slave['username']
        }
    
    def confirm_slave(self, master_id, slave_id):
        """确认奴隶身份"""
        result = self.db.confirm_slave(master_id, slave_id)
        return {
            'success': result, 
            'message': '成功确认奴隶身份' if result else '确认失败或没有找到对应的奴隶记录'
        }
    
    def get_slave_status(self, user_id):
        """获取用户的奴隶状态"""
        return self.db.get_slave_status(user_id)

# 创建全局帮派服务实例
gang_service = GangService() 