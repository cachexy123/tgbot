import os
import json
from bot.config.config import INITIAL_ADMIN
from bot.services.db_service import db_service

class AdminService:
    def __init__(self):
        self.db = db_service
        self.admins = set(INITIAL_ADMIN)
        self.admin_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'admins.json')
        self._load_admins()
    
    def _load_admins(self):
        """从文件加载管理员列表"""
        # 确保data目录存在
        os.makedirs(os.path.dirname(self.admin_file), exist_ok=True)
        
        # 如果文件不存在，创建一个新的并保存初始管理员
        if not os.path.exists(self.admin_file):
            self._save_admins()
            return
        
        # 尝试加载文件
        try:
            with open(self.admin_file, 'r') as f:
                admin_data = json.load(f)
                # 合并初始管理员和保存的管理员
                self.admins = set(admin_data + INITIAL_ADMIN)
        except (json.JSONDecodeError, FileNotFoundError) as e:
            print(f"加载管理员文件出错: {e}")
            # 保存初始管理员
            self._save_admins()
    
    def _save_admins(self):
        """保存管理员列表到文件"""
        try:
            with open(self.admin_file, 'w') as f:
                json.dump(list(self.admins), f)
        except Exception as e:
            print(f"保存管理员文件出错: {e}")
    
    def is_admin(self, user_id):
        """检查用户是否是管理员"""
        return user_id in self.admins
    
    def add_admin(self, user_id):
        """添加新管理员"""
        if user_id in self.admins:
            return False
        
        self.admins.add(user_id)
        self._save_admins()
        return True
    
    def remove_admin(self, user_id):
        """移除管理员"""
        if user_id not in self.admins:
            return False
        
        self.admins.remove(user_id)
        self._save_admins()
        return True
    
    def get_admins(self):
        """获取所有管理员ID"""
        return list(self.admins)
    
    def authorize_group(self, group_id, group_name):
        """授权群组使用机器人"""
        return self.db.authorize_group(group_id, group_name)
    
    def is_group_authorized(self, group_id):
        """检查群组是否已授权"""
        return self.db.is_group_authorized(group_id)
    
    def update_user_points(self, user_id, points_change):
        """更新用户积分（管理员操作）"""
        return self.db.update_points(user_id, points_change)

    def deduct_user_points(self, user_id, points_amount):
        """从用户扣除积分（管理员操作，允许负分）"""
        if points_amount < 0:
            return False  # 确保扣除的是正数
        
        # 扣除积分
        new_points = self.db.update_points(user_id, -points_amount)
        return new_points
        
    def kick_user_from_group(self, user_id, group_id):
        """从群组中踢出用户（管理员操作）"""
        # 检查用户是否存在
        user = self.db.get_user(user_id)
        if not user:
            return {
                "success": False,
                "message": f"找不到用户 ID {user_id}"
            }
            
        # 检查群组是否已授权
        if not self.db.is_group_authorized(group_id):
            return {
                "success": False,
                "message": f"群组 {group_id} 未授权"
            }
            
        # 从数据库中移除用户的群组关系
        result = self.db.remove_user_from_group(user_id, group_id)
        
        if result:
            return {
                "success": True,
                "message": f"已将用户 {user['username']} 从群组数据库中移除"
            }
        else:
            return {
                "success": False,
                "message": f"从群组数据库移除用户失败，可能用户不在该群组中"
            }
        
    def check_negative_points_users(self):
        """检查积分为负且超过3天的用户，用于踢出处理"""
        return self.db.get_negative_points_users_to_kick()

# 创建全局管理员服务实例
admin_service = AdminService() 