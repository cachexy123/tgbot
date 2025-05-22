import pymysql
from bot.config.config import DB_CONFIG

def migrate_gang_records():
    """更新gang_records表的主键结构"""
    print("开始迁移gang_records表...")
    connection = pymysql.connect(**DB_CONFIG)
    
    try:
        with connection.cursor() as cursor:
            # 首先备份现有数据
            cursor.execute("CREATE TABLE IF NOT EXISTS gang_records_backup LIKE gang_records")
            cursor.execute("INSERT INTO gang_records_backup SELECT * FROM gang_records")
            print("已备份现有数据到gang_records_backup")
            
            # 修改表结构
            cursor.execute("DROP TABLE IF EXISTS gang_records")
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
            print("已创建新的gang_records表结构")
            
            # 恢复数据
            cursor.execute("""
                INSERT INTO gang_records (user_id, start_date, consecutive_days, total_donated)
                SELECT user_id, start_date, consecutive_days, total_donated FROM gang_records_backup
                ON DUPLICATE KEY UPDATE consecutive_days = VALUES(consecutive_days), total_donated = VALUES(total_donated)
            """)
            print("已恢复数据到新结构")
            
            connection.commit()
            print("迁移成功完成！")
    except Exception as e:
        print(f"迁移过程中发生错误: {e}")
        connection.rollback()
    finally:
        connection.close()

if __name__ == "__main__":
    migrate_gang_records() 