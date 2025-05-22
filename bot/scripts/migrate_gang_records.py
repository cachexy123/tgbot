import pymysql
import sys
import os
import time
from datetime import date

# 添加项目根目录到系统路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入数据库配置
from bot.services.db_service import db_service

def migrate_gang_records():
    """迁移gang_records表，将主键改为(user_id, start_date)"""
    print("开始迁移gang_records表...")
    
    # 备份现有数据
    records = []
    connection = db_service.get_connection()
    
    try:
        # 获取现有记录
        with connection.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute("SELECT * FROM gang_records")
            records = cursor.fetchall()
            print(f"从原表读取了 {len(records)} 条记录")
        
        # 重命名旧表
        with connection.cursor() as cursor:
            cursor.execute("RENAME TABLE gang_records TO gang_records_old")
            print("已将原表重命名为gang_records_old")
        
        # 创建新表
        with connection.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE gang_records (
                    user_id BIGINT NOT NULL,
                    start_date DATE NOT NULL,
                    consecutive_days INT DEFAULT 1,
                    total_donated INT DEFAULT 0,
                    PRIMARY KEY (user_id, start_date),
                    FOREIGN KEY (user_id) REFERENCES users(user_id)
                ) ENGINE=InnoDB
            """)
            print("已创建新的gang_records表，主键为(user_id, start_date)")
        
        # 导入数据到新表
        today = date.today()
        dup_users = set()
        
        with connection.cursor() as cursor:
            for record in records:
                user_id = record['user_id']
                start_date = record.get('start_date', today)
                consecutive_days = record.get('consecutive_days', 1)
                total_donated = record.get('total_donated', 0)
                
                # 检查是否已经存在此用户今天的记录
                if user_id in dup_users:
                    print(f"警告：用户 {user_id} 已有今天的记录，跳过")
                    continue
                    
                try:
                    cursor.execute("""
                        INSERT INTO gang_records 
                        (user_id, start_date, consecutive_days, total_donated)
                        VALUES (%s, %s, %s, %s)
                    """, (user_id, start_date, consecutive_days, total_donated))
                    dup_users.add(user_id)
                except Exception as e:
                    print(f"插入记录时出错: {e}")
            
            print(f"成功导入 {len(dup_users)} 条记录到新表")
        
        connection.commit()
        print("迁移提交成功")
        
        # 询问是否删除旧表
        while True:
            answer = input("是否删除旧表gang_records_old？(yes/no): ").strip().lower()
            if answer in ('yes', 'y'):
                with connection.cursor() as cursor:
                    cursor.execute("DROP TABLE gang_records_old")
                connection.commit()
                print("已删除旧表")
                break
            elif answer in ('no', 'n'):
                print("保留旧表，完成迁移")
                break
            else:
                print("请输入yes或no")
        
    except Exception as e:
        print(f"迁移过程中出现错误: {e}")
        connection.rollback()
        print("已回滚所有更改")
        
        # 如果新表创建失败，尝试恢复旧表
        try:
            with connection.cursor() as cursor:
                cursor.execute("SHOW TABLES LIKE 'gang_records'")
                if not cursor.fetchone():
                    cursor.execute("RENAME TABLE gang_records_old TO gang_records")
                    connection.commit()
                    print("已恢复原表")
        except Exception as e:
            print(f"恢复原表失败: {e}")
    finally:
        connection.close()

if __name__ == "__main__":
    migrate_gang_records() 