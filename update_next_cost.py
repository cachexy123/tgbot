#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
脚本功能：更新所有用户的next_cost值，使用新的计算方式
使用方法：python update_next_cost.py
"""

import pymysql
from bot.services.db_service import db_service
from bot.config.config import CULTIVATION_STAGES, DB_CONFIG

def get_all_users_with_cultivation():
    """获取所有有修仙数据的用户"""
    connection = pymysql.connect(**DB_CONFIG)
    try:
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("""
                SELECT user_id, stage FROM user_cultivation
            """)
            return cursor.fetchall()
    finally:
        connection.close()

def main():
    users = get_all_users_with_cultivation()
    print(f"找到 {len(users)} 个用户有修仙数据")
    
    updated_count = 0
    for user in users:
        user_id = user['user_id']
        stage = user['stage']
        
        # 使用新公式计算next_cost - 使用1.5次方指数增长
        base_cost = 100
        next_cost = int(base_cost * pow(stage + 1, 1.5))
        
        # 更新用户的next_cost
        if db_service.update_next_cost(user_id, next_cost):
            updated_count += 1
            print(f"已更新用户 {user_id} 的next_cost为 {next_cost}（境界：{CULTIVATION_STAGES[stage]}）")
    
    print(f"成功更新了 {updated_count}/{len(users)} 个用户的突破消耗")

if __name__ == "__main__":
    main() 