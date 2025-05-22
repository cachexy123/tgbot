import pymysql
from datetime import datetime, date, timedelta
import random
from bot.config.config import DB_CONFIG, CULTIVATION_STAGES
from bot.utils.db_config_helper import get_optimized_connection
import time
import aiohttp
import json

class DBService:
    def __init__(self):
        self.config = DB_CONFIG
        # 尝试初始化数据库
        try:
            self.initialize_database()
        except Exception as e:
            print(f"初始化数据库时出错: {e}")

    def initialize_database(self):
        """初始化数据库，创建必要的表"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 首先创建数据库
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS {self.config['database']}")
                cursor.execute(f"USE {self.config['database']}")
                
                # 优化数据库设置
                cursor.execute("ALTER DATABASE CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
                
                # 设置会话参数
                cursor.execute("SET innodb_lock_wait_timeout = 20")  # 增加锁等待超时
                cursor.execute("SET tx_isolation = 'READ-COMMITTED'")  # 设置事务隔离级别
                
                # 创建用户表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL UNIQUE,
                        username VARCHAR(255),
                        first_name VARCHAR(255),
                        last_name VARCHAR(255),
                        points INT DEFAULT 0,
                        total_books_uploaded INT DEFAULT 0
                    ) ENGINE=InnoDB
                """)
                
                # 检查是否需要添加total_books_uploaded列
                try:
                    cursor.execute("SELECT total_books_uploaded FROM users LIMIT 1")
                except Exception:
                    cursor.execute("ALTER TABLE users ADD COLUMN total_books_uploaded INT DEFAULT 0")
                    print("已添加total_books_uploaded列到users表")
                
                # 检查是否需要添加first_name和last_name列
                try:
                    cursor.execute("SELECT first_name FROM users LIMIT 1")
                except Exception:
                    cursor.execute("ALTER TABLE users ADD COLUMN first_name VARCHAR(255)")
                    print("已添加first_name列到users表")
                
                try:
                    cursor.execute("SELECT last_name FROM users LIMIT 1")
                except Exception:
                    cursor.execute("ALTER TABLE users ADD COLUMN last_name VARCHAR(255)")
                    print("已添加last_name列到users表")
                
                # 创建用户负分记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS negative_points_records (
                        user_id BIGINT PRIMARY KEY,
                        first_negative_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建授权群组表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS authorized_groups (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        group_id BIGINT NOT NULL UNIQUE,
                        group_name VARCHAR(255),
                        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                """)
                
                # 创建用户群组关系表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_group (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        group_id BIGINT NOT NULL,
                        joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE KEY user_group_unique (user_id, group_id),
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建文件表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS files (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        md5 CHAR(32) NOT NULL UNIQUE,
                        user_id BIGINT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建保护罩记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS shield_records (
                        user_id BIGINT NOT NULL,
                        date DATE NOT NULL,
                        books_uploaded INT DEFAULT 0,
                        shield_active BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (user_id, date),
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建刮刮乐记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS gua_records (
                        user_id BIGINT NOT NULL,
                        date DATE NOT NULL,
                        times_used INT DEFAULT 0,
                        PRIMARY KEY (user_id, date),
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建用户修仙表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_cultivation (
                        user_id BIGINT PRIMARY KEY,
                        stage INT DEFAULT 0,
                        pills INT DEFAULT 0,
                        next_cost INT DEFAULT 10,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建用户事件表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS user_events (
                        user_id BIGINT PRIMARY KEY,
                        last_trigger TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        event_count INT DEFAULT 0,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建打劫记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS rob_records (
                        user_id BIGINT PRIMARY KEY,
                        last_rob TIMESTAMP,
                        count INT DEFAULT 0,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建帮派记录表（签到记录）
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS gang_records (
                        user_id BIGINT NOT NULL,
                        start_date DATE NOT NULL,
                        consecutive_days INT DEFAULT 1,
                        total_donated INT DEFAULT 0,
                        PRIMARY KEY (user_id, start_date),
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建奴隶记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS slave_records (
                        master_id BIGINT NOT NULL,
                        slave_id BIGINT NOT NULL,
                        group_id BIGINT NOT NULL,
                        created_date DATE NOT NULL,
                        confirmed BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (master_id, created_date),
                        FOREIGN KEY (master_id) REFERENCES users(user_id),
                        FOREIGN KEY (slave_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建猫娘记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS catgirl_records (
                        master_id BIGINT NOT NULL,
                        user_id BIGINT NOT NULL,
                        group_id BIGINT NOT NULL,
                        status VARCHAR(255) NOT NULL,
                        expires_at TIMESTAMP NOT NULL,
                        PRIMARY KEY (master_id, user_id, group_id),
                        FOREIGN KEY (master_id) REFERENCES users(user_id),
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建兑换码表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS redemption_codes (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        code VARCHAR(32) NOT NULL UNIQUE,
                        creator_id BIGINT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        used BOOLEAN DEFAULT FALSE,
                        used_by BIGINT DEFAULT NULL,
                        used_at TIMESTAMP NULL,
                        FOREIGN KEY (creator_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建生死战游戏表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS duel_games (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        challenger_id BIGINT NOT NULL,
                        challenged_id BIGINT NOT NULL,
                        group_id BIGINT NOT NULL,
                        status VARCHAR(255) NOT NULL,
                        current_turn BIGINT,
                        last_action_time TIMESTAMP,
                        FOREIGN KEY (challenger_id) REFERENCES users(user_id),
                        FOREIGN KEY (challenged_id) REFERENCES users(user_id),
                        FOREIGN KEY (group_id) REFERENCES authorized_groups(group_id)
                    ) ENGINE=InnoDB
                """)
                
                # 修改生死战游戏表，添加更多字段
                cursor.execute("""
                    ALTER TABLE duel_games 
                    ADD COLUMN IF NOT EXISTS challenger_cards TEXT NULL,
                    ADD COLUMN IF NOT EXISTS challenged_cards TEXT NULL,
                    ADD COLUMN IF NOT EXISTS challenger_stand BOOLEAN DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS challenged_stand BOOLEAN DEFAULT FALSE,
                    ADD COLUMN IF NOT EXISTS winner_id BIGINT NULL
                """)
                
                # 创建飞升任务表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS ascension_tasks (
                        user_id BIGINT PRIMARY KEY,
                        current_stage INT DEFAULT 1,
                        duel_wins INT DEFAULT 0,
                        math_attempts INT DEFAULT 0,
                        math_question TEXT NULL,
                        math_answer INT NULL,
                        shared_books INT DEFAULT 0,
                        last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建飞升获胜记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS ascension_duel_wins (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        duel_id INT NOT NULL,
                        win_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id),
                        FOREIGN KEY (duel_id) REFERENCES duel_games(id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建地仙每日首次发言记录表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS immortal_daily_chat (
                        user_id BIGINT NOT NULL,
                        date DATE NOT NULL,
                        has_greeted BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (user_id, date),
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
            connection.commit()
            print("数据库初始化成功")
        except Exception as e:
            print(f"初始化数据库出错: {e}")
        finally:
            connection.close()

    def get_connection(self):
        """获取数据库连接"""
        return get_optimized_connection(self.config)

    # ========== 用户管理 ==========
    def get_user(self, user_id):
        """获取用户信息"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM users WHERE user_id = %s
                """, (user_id,))
                return cursor.fetchone()
        finally:
            connection.close()

    def create_user(self, user_id, username, first_name=None, last_name=None):
        """创建新用户"""
        # 如果username为None，使用默认值
        if username is None:
            username = "无名修士"
            
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 创建用户基本信息
                cursor.execute("""
                    INSERT IGNORE INTO users (user_id, username, first_name, last_name, points)
                    VALUES (%s, %s, %s, %s, 100)
                """, (user_id, username, first_name, last_name))
                
                # 计算初始境界所需的突破成本，与attempt_breakthrough方法保持一致
                initial_stage = 0
                base_cost = 200
                major_level = initial_stage // 3
                minor_level = initial_stage % 3
                major_linear = (major_level + 1) * 200
                major_exp = 1.25 ** major_level
                minor_multiplier = 1 + (minor_level * 0.5)
                initial_cost = int((base_cost + major_linear) * major_exp * minor_multiplier)
                
                # 初始化用户的修仙记录
                cursor.execute("""
                    INSERT IGNORE INTO user_cultivation (user_id, stage, pills, next_cost)
                    VALUES (%s, 0, 0, %s)
                """, (user_id, initial_cost))
                
                # 初始化用户事件记录
                cursor.execute("""
                    INSERT IGNORE INTO user_events (user_id)
                    VALUES (%s)
                """, (user_id,))
                
                # 初始化打劫记录
                cursor.execute("""
                    INSERT IGNORE INTO rob_records (user_id, last_rob, count)
                    VALUES (%s, NULL, 0)
                """, (user_id,))
                
            connection.commit()
        finally:
            connection.close()

    def update_username(self, user_id, username, first_name=None, last_name=None):
        """更新用户名和姓名"""
        # 如果username为None，使用默认值
        if username is None:
            username = "无名修士"
            
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE users 
                    SET username = %s, first_name = %s, last_name = %s 
                    WHERE user_id = %s
                """, (username, first_name, last_name, user_id))
            connection.commit()
        finally:
            connection.close()

    def add_user_to_group(self, user_id, group_id):
        """添加用户到群组关联"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT IGNORE INTO user_group (user_id, group_id)
                    VALUES (%s, %s)
                """, (user_id, group_id))
            connection.commit()
        finally:
            connection.close()

    # ========== 群组管理 ==========
    def is_group_authorized(self, group_id):
        """检查群组是否已授权"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT * FROM authorized_groups WHERE group_id = %s
                """, (group_id,))
                return cursor.fetchone() is not None
        finally:
            connection.close()

    def authorize_group(self, group_id, group_name):
        """授权群组"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT IGNORE INTO authorized_groups (group_id, group_name)
                    VALUES (%s, %s)
                """, (group_id, group_name))
            connection.commit()
            return True
        except Exception as e:
            print(f"授权群组失败: {e}")
            return False
        finally:
            connection.close()

    def get_all_authorized_groups(self):
        """获取所有授权的群组"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("SELECT * FROM authorized_groups")
                return cursor.fetchall()
        finally:
            connection.close()

    # ========== 积分管理 ==========
    def update_points(self, user_id, points_change, max_retries=3):
        """更新用户积分"""
        retries = 0
        while retries < max_retries:
            connection = self.get_connection()
            try:
                with connection.cursor() as cursor:
                    # 允许负积分
                    cursor.execute("""
                        UPDATE users 
                        SET points = points + %s 
                        WHERE user_id = %s
                    """, (points_change, user_id))
                connection.commit()
                
                # 获取更新后的积分
                with connection.cursor() as cursor:
                    cursor.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
                    result = cursor.fetchone()
                    new_points = result[0] if result else 0
                    
                    # 如果积分为负数，记录首次负分时间
                    if new_points < 0:
                        self.record_negative_points(user_id)
                        
                    return new_points
            except pymysql.err.OperationalError as e:
                # 如果是锁等待超时，尝试重试
                if e.args[0] == 1205:  # Lock wait timeout exceeded
                    retries += 1
                    if retries < max_retries:
                        print(f"锁等待超时，正在重试 ({retries}/{max_retries})...")
                        # 等待一小段时间后重试
                        time.sleep(0.5)
                    else:
                        print("达到最大重试次数，操作失败")
                        raise
                else:
                    raise
            finally:
                connection.close()

    def record_negative_points(self, user_id):
        """记录用户积分首次变为负数的时间"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 检查是否已有记录
                cursor.execute("""
                    SELECT user_id FROM negative_points_records
                    WHERE user_id = %s
                """, (user_id,))
                
                # 如果没有记录，添加一条
                if cursor.fetchone() is None:
                    cursor.execute("""
                        INSERT INTO negative_points_records (user_id, first_negative_time)
                        VALUES (%s, CURRENT_TIMESTAMP)
                    """, (user_id,))
                    connection.commit()
                    print(f"用户 {user_id} 积分首次变为负数，已记录时间")
        except Exception as e:
            print(f"记录负分时间出错: {e}")
        finally:
            connection.close()
            
    def get_negative_points_users_to_kick(self):
        """获取积分为负且超过3天的用户列表"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                # 查询积分为负且首次负分时间超过3天的用户
                cursor.execute("""
                    SELECT u.user_id, u.username, u.points, npr.first_negative_time
                    FROM users u
                    JOIN negative_points_records npr ON u.user_id = npr.user_id
                    WHERE u.points < 0 AND npr.first_negative_time < DATE_SUB(NOW(), INTERVAL 3 DAY)
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"获取需要踢出的负分用户出错: {e}")
            return []
        finally:
            connection.close()
            
    def remove_negative_points_record(self, user_id):
        """移除用户的负分记录"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM negative_points_records
                    WHERE user_id = %s
                """, (user_id,))
                connection.commit()
                print(f"已移除用户 {user_id} 的负分记录")
        except Exception as e:
            print(f"移除负分记录出错: {e}")
        finally:
            connection.close()

    def get_user_points(self, user_id):
        """获取用户积分"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT points FROM users WHERE user_id = %s", (user_id,))
                result = cursor.fetchone()
                return result[0] if result else 0
        finally:
            connection.close()

    # ========== 签到系统 ==========
    def check_in(self, user_id, max_retries=3):
        """用户签到"""
        # 首先检查今天是否已经签到
        today = date.today()
        today_record = None
        
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM gang_records 
                    WHERE user_id = %s AND start_date = %s
                """, (user_id, today))
                today_record = cursor.fetchone()
        finally:
            connection.close()
            
        # 如果已经签到过，直接返回
        if today_record:
            return {"success": False, "message": "今天已经签到过了"}
        
        retries = 0
        while retries < max_retries:
            connection = self.get_connection()
            try:
                today = date.today()
                yesterday = today - timedelta(days=1)
                
                with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                    # 再次检查今天是否已签到（双重检查，防止并发问题）
                    cursor.execute("""
                        SELECT * FROM gang_records 
                        WHERE user_id = %s AND start_date = %s
                    """, (user_id, today))
                    
                    if cursor.fetchone():
                        return {"success": False, "message": "今天已经签到过了"}
                    
                    # 检查是否有昨天的记录
                    cursor.execute("""
                        SELECT * FROM gang_records 
                        WHERE user_id = %s AND start_date = %s
                    """, (user_id, yesterday))
                    
                    yesterday_record = cursor.fetchone()
                    consecutive_days = 1
                    
                    # 如果有昨天的记录，连续签到天数+1
                    if yesterday_record:
                        consecutive_days = yesterday_record['consecutive_days'] + 1
                        # 如果达到7天，重置为1
                        if consecutive_days > 7:
                            consecutive_days = 1
                    
                    # 基础积分：1-10随机
                    base_points = random.randint(1, 10)
                    extra_points = 0
                    
                    # 连续签到奖励
                    if consecutive_days == 3:
                        extra_points = 3
                    elif consecutive_days == 5:
                        extra_points = 5
                    elif consecutive_days == 7:
                        extra_points = 10
                    
                    total_points = base_points + extra_points
                    
                    # 更新签到记录
                    cursor.execute("""
                        INSERT INTO gang_records (user_id, start_date, consecutive_days)
                        VALUES (%s, %s, %s)
                        ON DUPLICATE KEY UPDATE consecutive_days = %s
                    """, (user_id, today, consecutive_days, consecutive_days))
                    
                    # 提交事务，确保签到记录保存成功
                    connection.commit()
                
                # 使用单独的连接更新积分，避免长事务
                new_points = self.update_points(user_id, total_points)
                
                result = {
                    "success": True,
                    "base_points": base_points,
                    "extra_points": extra_points,
                    "total_points": total_points,
                    "consecutive_days": consecutive_days
                }
                
                return result
                
            except pymysql.err.OperationalError as e:
                # 如果是锁等待超时，尝试重试
                if e.args[0] == 1205:  # Lock wait timeout exceeded
                    retries += 1
                    if retries < max_retries:
                        print(f"签到操作锁等待超时，正在重试 ({retries}/{max_retries})...")
                        # 等待一小段时间后重试
                        time.sleep(0.5)
                    else:
                        print("签到操作达到最大重试次数，操作失败")
                        return {"success": False, "message": "服务器繁忙，请稍后再试"}
                else:
                    print(f"签到操作出错: {e}")
                    return {"success": False, "message": "签到失败，请稍后再试"}
            finally:
                connection.close()
    
    def get_checkin_status(self, user_id):
        """获取用户签到状态"""
        connection = self.get_connection()
        try:
            today = date.today()
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                # 检查今天是否已签到
                cursor.execute("""
                    SELECT * FROM gang_records 
                    WHERE user_id = %s AND start_date = %s
                """, (user_id, today))
                today_record = cursor.fetchone()
                
                # 获取最近的签到记录
                cursor.execute("""
                    SELECT * FROM gang_records 
                    WHERE user_id = %s 
                    ORDER BY start_date DESC 
                    LIMIT 1
                """, (user_id,))
                
                last_record = cursor.fetchone()
                if not last_record:
                    return {
                        "consecutive_days": 0, 
                        "last_checkin": None,
                        "today_checked": False
                    }
                
                return {
                    "consecutive_days": last_record['consecutive_days'],
                    "last_checkin": last_record['start_date'],
                    "today_checked": today_record is not None
                }
        finally:
            connection.close()

    # ========== 刮刮乐系统 ==========
    def get_gua_records(self, user_id):
        """获取用户当天刮刮乐记录"""
        connection = self.get_connection()
        try:
            today = date.today()
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM gua_records 
                    WHERE user_id = %s AND date = %s
                """, (user_id, today))
                return cursor.fetchone()
        finally:
            connection.close()
            
    def update_gua_records(self, user_id, times_used=1):
        """更新刮刮乐使用记录"""
        connection = self.get_connection()
        try:
            today = date.today()
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO gua_records (user_id, date, times_used)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE times_used = times_used + %s
                """, (user_id, today, times_used, times_used))
            connection.commit()
        finally:
            connection.close()

    # ========== 修仙系统 ==========
    def get_cultivation(self, user_id):
        """获取用户修仙信息"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM user_cultivation 
                    WHERE user_id = %s
                """, (user_id,))
                return cursor.fetchone()
        finally:
            connection.close()
    
    def initialize_user_cultivation(self, user_id):
        """初始化用户修仙信息"""
        # 检查记录是否已存在
        cultivation = self.get_cultivation(user_id)
        if cultivation:
            # 记录已存在，不需要初始化
            return True
            
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 创建初始修仙记录
                cursor.execute("""
                    INSERT INTO user_cultivation (user_id, stage, pills, next_cost)
                    VALUES (%s, 0, 0, 200)
                """, (user_id,))
            connection.commit()
            print(f"已为用户 {user_id} 初始化修仙信息")
            return True
        except Exception as e:
            print(f"初始化用户修仙信息出错: {e}")
            return False
        finally:
            connection.close()
    
    def update_cultivation_stage(self, user_id, new_stage, max_retries=3):
        """更新修炼阶段"""
        connection = self.get_connection()
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE user_cultivation 
                        SET stage = %s
                        WHERE user_id = %s
                    """, (new_stage, user_id))
                connection.commit()
                return True
            except pymysql.err.OperationalError as e:
                if "Deadlock" in str(e) or "Lock wait timeout" in str(e):
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"更新修炼阶段失败，已达到最大重试次数: {e}")
                        return False
                    time.sleep(0.5)  # 短暂延迟后重试
                else:
                    print(f"更新修炼阶段时发生错误: {e}")
                    return False
            except Exception as e:
                print(f"更新修炼阶段时发生错误: {e}")
                return False
            finally:
                if retry_count >= max_retries - 1:  # 只在最后一次尝试后关闭连接
                    connection.close()
    
    def update_cultivation_pills(self, user_id, pills_change, max_retries=3):
        """更新用户丹药数量"""
        connection = self.get_connection()
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                with connection.cursor() as cursor:
                    if pills_change >= 0:
                        cursor.execute("""
                            UPDATE user_cultivation 
                            SET pills = pills + %s
                            WHERE user_id = %s
                        """, (pills_change, user_id))
                    else:
                        # 确保不会减到负数
                        cursor.execute("""
                            UPDATE user_cultivation 
                            SET pills = GREATEST(0, pills + %s)
                            WHERE user_id = %s
                        """, (pills_change, user_id))
                connection.commit()
                return True
            except pymysql.err.OperationalError as e:
                if "Deadlock" in str(e) or "Lock wait timeout" in str(e):
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"更新丹药数量失败，已达到最大重试次数: {e}")
                        return False
                    time.sleep(0.5)  # 短暂延迟后重试
                else:
                    print(f"更新丹药数量时发生错误: {e}")
                    return False
            except Exception as e:
                print(f"更新丹药数量时发生错误: {e}")
                return False
            finally:
                if retry_count >= max_retries - 1:  # 只在最后一次尝试后关闭连接
                    connection.close()
    
    def update_next_cost(self, user_id, next_cost, max_retries=3):
        """更新下次突破所需丹药数量"""
        connection = self.get_connection()
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                with connection.cursor() as cursor:
                    cursor.execute("""
                        UPDATE user_cultivation 
                        SET next_cost = %s
                        WHERE user_id = %s
                    """, (next_cost, user_id))
                connection.commit()
                return True
            except pymysql.err.OperationalError as e:
                if "Deadlock" in str(e) or "Lock wait timeout" in str(e):
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"更新突破花费失败，已达到最大重试次数: {e}")
                        return False
                    time.sleep(0.5)  # 短暂延迟后重试
                else:
                    print(f"更新突破花费时发生错误: {e}")
                    return False
            except Exception as e:
                print(f"更新突破花费时发生错误: {e}")
                return False
            finally:
                if retry_count >= max_retries - 1:  # 只在最后一次尝试后关闭连接
                    connection.close()
    
    def attempt_breakthrough(self, user_id, max_retries=3):
        """尝试突破修为"""
        # 获取用户当前修为信息
        cultivation = self.get_cultivation(user_id)
        if not cultivation:
            return {"success": False, "message": "用户修为信息不存在"}
        
        current_stage = cultivation['stage']
        current_pills = cultivation['pills']
        
        # 计算新的所需灵石 - 使用更合理的计算方式，高境界需要更多灵石
        # 基础消耗
        base_cost = 200
        # 大境界等级（从0开始）
        major_level = current_stage // 3
        # 当前小境界位置（0,1,2）
        minor_level = current_stage % 3
        
        # 线性增长部分 - 每个大境界增加200基础点
        major_linear = (major_level + 1) * 200
        # 指数增长部分 - 确保高级境界增长更快
        major_exp = 1.25 ** major_level
        # 小境界调整因子
        minor_multiplier = 1 + (minor_level * 0.5)  # 1, 1.5, 2
        
        # 最终计算 - 高级境界会达到几万灵石
        next_cost = int((base_cost + major_linear) * major_exp * minor_multiplier)
        
        # 获取用户当前积分
        current_points = self.get_user_points(user_id)
        
        # 检查是否有足够积分
        if current_points < next_cost:
            return {
                "success": False, 
                "message": f"灵石不足，需要{next_cost}灵石，当前只有{current_points}灵石"
            }
        
        # 检查是否需要突破丹（大境界突破）
        is_major_breakthrough = (current_stage + 1) % 3 == 0 and current_stage > 0
        pills_needed = 2 ** ((current_stage + 1) // 3) if is_major_breakthrough else 0
        
        if is_major_breakthrough and current_pills < pills_needed:
            return {
                "success": False, 
                "message": f"需要{pills_needed}个突破丹才能突破到{CULTIVATION_STAGES[current_stage + 1]}，当前只有{current_pills}个"
            }
        
        connection = self.get_connection()
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                with connection.cursor() as cursor:
                    # 更新用户积分
                    cursor.execute("""
                        UPDATE users SET points = points - %s WHERE user_id = %s
                    """, (next_cost, user_id))
                    
                    # 更新修为
                    new_stage = current_stage + 1
                    
                    # 计算下一次突破所需灵石 - 基于新境界
                    new_major_level = new_stage // 3
                    new_minor_level = new_stage % 3
                    new_major_linear = (new_major_level + 1) * 200
                    new_major_exp = 1.25 ** new_major_level
                    new_minor_multiplier = 1 + (new_minor_level * 0.5)
                    next_breakthrough_cost = int((base_cost + new_major_linear) * new_major_exp * new_minor_multiplier)
                    
                    # 如果是大境界突破，减少突破丹
                    if is_major_breakthrough:
                        cursor.execute("""
                            UPDATE user_cultivation 
                            SET stage = %s, pills = pills - %s, next_cost = %s
                            WHERE user_id = %s
                        """, (new_stage, pills_needed, next_breakthrough_cost, user_id))
                    else:
                        cursor.execute("""
                            UPDATE user_cultivation 
                            SET stage = %s, next_cost = %s
                            WHERE user_id = %s
                        """, (new_stage, next_breakthrough_cost, user_id))
                
                connection.commit()
                
                return {
                    "success": True,
                    "message": f"突破成功！消耗了{next_cost}灵石" + 
                              (f"和{pills_needed}个突破丹" if is_major_breakthrough else "") + 
                              f"，修为提升到了{CULTIVATION_STAGES[new_stage]}",
                    "new_stage": CULTIVATION_STAGES[new_stage],
                    "next_cost": next_breakthrough_cost
                }
            except pymysql.err.OperationalError as e:
                if "Deadlock" in str(e) or "Lock wait timeout" in str(e):
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"尝试突破修为失败，已达到最大重试次数: {e}")
                        return {"success": False, "message": "突破过程中遇到了障碍，请稍后再试"}
                    time.sleep(0.5)  # 短暂延迟后重试
                else:
                    print(f"尝试突破修为时发生错误: {e}")
                    return {"success": False, "message": "突破过程中遇到了意外，请稍后再试"}
            except Exception as e:
                print(f"尝试突破修为时发生错误: {e}")
                return {"success": False, "message": "突破过程中遇到了错误，请稍后再试"}
            finally:
                if retry_count >= max_retries - 1:  # 只在最后一次尝试后关闭连接
                    connection.close()
    
    # ========== 奇遇系统 ==========
    def record_user_event(self, user_id, max_retries=3):
        """记录用户事件触发"""
        connection = self.get_connection()
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                now = datetime.now()
                with connection.cursor() as cursor:
                    # 先检查记录是否存在
                    cursor.execute("""
                        SELECT COUNT(*) as count FROM user_events 
                        WHERE user_id = %s
                    """, (user_id,))
                    result = cursor.fetchone()
                    
                    if result and result[0] > 0:
                        # 更新已有记录
                        cursor.execute("""
                            UPDATE user_events 
                            SET last_trigger = %s, event_count = event_count + 1
                            WHERE user_id = %s
                        """, (now, user_id))
                    else:
                        # 创建新记录
                        cursor.execute("""
                            INSERT INTO user_events (user_id, last_trigger, event_count)
                            VALUES (%s, %s, 1)
                        """, (user_id, now))
                
                connection.commit()
                return True
            except pymysql.err.OperationalError as e:
                if "Deadlock" in str(e) or "Lock wait timeout" in str(e):
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"记录用户事件失败，已达到最大重试次数: {e}")
                        return False
                    time.sleep(0.5)  # 短暂延迟后重试
                else:
                    print(f"记录用户事件时发生错误: {e}")
                    return False
            except Exception as e:
                print(f"记录用户事件时发生错误: {e}")
                return False
            finally:
                if retry_count >= max_retries - 1:  # 只在最后一次尝试后关闭连接
                    connection.close()
    
    # ========== 打劫系统 ==========
    def update_rob_record(self, user_id, max_retries=3):
        """更新打劫记录"""
        connection = self.get_connection()
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                now = datetime.now()
                with connection.cursor() as cursor:
                    # 先检查记录是否存在
                    cursor.execute("""
                        SELECT COUNT(*) as count FROM rob_records 
                        WHERE user_id = %s
                    """, (user_id,))
                    result = cursor.fetchone()
                    
                    if result and result[0] > 0:
                        # 更新现有记录
                        cursor.execute("""
                            UPDATE rob_records 
                            SET last_rob = %s, count = count + 1
                            WHERE user_id = %s
                        """, (now, user_id))
                    else:
                        # 创建新记录
                        cursor.execute("""
                            INSERT INTO rob_records (user_id, last_rob, count)
                            VALUES (%s, %s, 1)
                        """, (user_id, now))
                        
                connection.commit()
                return True
            except pymysql.err.OperationalError as e:
                if "Deadlock" in str(e) or "Lock wait timeout" in str(e):
                    retry_count += 1
                    if retry_count >= max_retries:
                        print(f"更新打劫记录失败，已达到最大重试次数: {e}")
                        return False
                    time.sleep(0.5)  # 短暂延迟后重试
                else:
                    print(f"更新打劫记录时发生错误: {e}")
                    return False
            except Exception as e:
                print(f"更新打劫记录时发生错误: {e}")
                return False
            finally:
                if retry_count >= max_retries - 1:  # 只在最后一次尝试后关闭连接
                    connection.close()
    
    def get_rob_record(self, user_id):
        """获取打劫记录"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM rob_records 
                    WHERE user_id = %s
                """, (user_id,))
                record = cursor.fetchone()
                # 如果没有记录，返回一个初始状态
                if not record:
                    return {
                        'user_id': user_id,
                        'last_rob': None,
                        'count': 0
                    }
                return record
        except Exception as e:
            print(f"获取打劫记录时发生错误: {e}")
            return {
                'user_id': user_id,
                'last_rob': None,
                'count': 0
            }
        finally:
            connection.close()
    
    # ========== 天骄榜 ==========
    def get_top_players(self, limit=10):
        """获取排行榜前10名用户"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT u.user_id, u.username, u.first_name, u.last_name, u.points, c.stage
                    FROM users u
                    JOIN user_cultivation c ON u.user_id = c.user_id
                    ORDER BY c.stage DESC, u.points DESC
                    LIMIT %s
                """, (limit,))
                return cursor.fetchall()
        finally:
            connection.close()
    
    # ========== 帮主系统 ==========
    def get_gang_leader(self):
        """获取当前帮主信息"""
        top_players = self.get_top_players(1)
        if top_players:
            leader = top_players[0]
            return leader
        return None

    def update_slave_record(self, master_id, slave_id, group_id):
        """更新奴隶记录"""
        connection = self.get_connection()
        try:
            today = date.today()
            with connection.cursor() as cursor:
                # 检查当天是否已经指定过奴隶
                cursor.execute("""
                    SELECT * FROM slave_records 
                    WHERE master_id = %s AND created_date = %s
                """, (master_id, today))
                
                if cursor.fetchone():
                    return False
                
                # 创建新的奴隶记录
                cursor.execute("""
                    INSERT INTO slave_records 
                    (master_id, slave_id, group_id, created_date, confirmed)
                    VALUES (%s, %s, %s, %s, FALSE)
                """, (master_id, slave_id, group_id, today))
                
            connection.commit()
            return True
        finally:
            connection.close()
    
    def confirm_slave(self, master_id, slave_id):
        """确认奴隶身份"""
        connection = self.get_connection()
        try:
            today = date.today()
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE slave_records 
                    SET confirmed = TRUE
                    WHERE master_id = %s AND slave_id = %s AND created_date = %s
                """, (master_id, slave_id, today))
            
            connection.commit()
            return cursor.rowcount > 0
        finally:
            connection.close()
    
    def get_slave_status(self, user_id):
        """获取用户奴隶状态"""
        connection = self.get_connection()
        try:
            today = date.today()
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                # 检查是否是别人的奴隶
                cursor.execute("""
                    SELECT sr.*, u.username as master_name
                    FROM slave_records sr
                    JOIN users u ON sr.master_id = u.user_id
                    WHERE sr.slave_id = %s AND sr.created_date = %s
                """, (user_id, today))
                
                slave_record = cursor.fetchone()
                
                # 检查是否有奴隶
                cursor.execute("""
                    SELECT sr.*, u.username as slave_name
                    FROM slave_records sr
                    JOIN users u ON sr.slave_id = u.user_id
                    WHERE sr.master_id = %s AND sr.created_date = %s
                """, (user_id, today))
                
                master_record = cursor.fetchone()
                
                return {
                    "is_slave": slave_record is not None,
                    "slave_record": slave_record,
                    "has_slave": master_record is not None,
                    "master_record": master_record
                }
        finally:
            connection.close()
    
    # ========== 书籍管理 ==========
    def check_file_exists(self, md5):
        """检查文件MD5是否已存在"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT * FROM files WHERE md5 = %s", (md5,))
                return cursor.fetchone() is not None
        finally:
            connection.close()

    def add_file_record(self, md5, user_id):
        """添加文件记录"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO files (md5, user_id)
                    VALUES (%s, %s)
                """, (md5, user_id))
            connection.commit()
            return True
        except Exception as e:
            print(f"添加文件记录失败: {e}")
            return False
        finally:
            connection.close()

    def get_catgirl_record(self, user_id, group_id):
        """获取猫娘记录"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM catgirl_records 
                    WHERE user_id = %s AND group_id = %s
                """, (user_id, group_id))
                return cursor.fetchone()
        except Exception as e:
            print(f"获取猫娘记录失败: {e}")
            return None
        finally:
            connection.close()
    
    def create_catgirl_record(self, master_id, user_id, group_id):
        """创建猫娘记录"""
        # 首先检查记录是否存在
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM catgirl_records 
                    WHERE user_id = %s AND group_id = %s
                """, (user_id, group_id))
                existing = cursor.fetchone()
                
                # 如果记录存在且未过期，则先删除
                if existing:
                    cursor.execute("""
                        DELETE FROM catgirl_records 
                        WHERE user_id = %s AND group_id = %s
                    """, (user_id, group_id))
                
                # 创建新记录
                cursor.execute("""
                    INSERT INTO catgirl_records (master_id, user_id, group_id, status, expires_at)
                    VALUES (%s, %s, %s, 'pending', DATE_ADD(NOW(), INTERVAL 24 HOUR))
                """, (master_id, user_id, group_id))
            connection.commit()
        except Exception as e:
            print(f"创建猫娘记录失败: {e}")
            connection.rollback()  # 出错时回滚
        finally:
            connection.close()
    
    def update_catgirl_status(self, user_id, group_id, status):
        """更新猫娘状态"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE catgirl_records 
                    SET status = %s
                    WHERE user_id = %s AND group_id = %s
                """, (status, user_id, group_id))
            connection.commit()
        finally:
            connection.close()
    
    def delete_catgirl_record(self, user_id, group_id):
        """删除猫娘记录"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM catgirl_records 
                    WHERE user_id = %s AND group_id = %s
                """, (user_id, group_id))
            connection.commit()
            print(f"已删除用户 {user_id} 在群组 {group_id} 的猫娘记录")
        except Exception as e:
            print(f"删除猫娘记录失败: {e}")
            connection.rollback()
        finally:
            connection.close()

    # ========== 生死战系统 ==========
    def create_duel_game(self, challenger_id, challenged_id, group_id):
        """创建生死战游戏"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO duel_games 
                    (challenger_id, challenged_id, group_id, status, current_turn, last_action_time)
                    VALUES (%s, %s, %s, 'waiting', NULL, NOW())
                """, (challenger_id, challenged_id, group_id))
                
                # 获取新创建的ID
                cursor.execute("SELECT LAST_INSERT_ID()")
                result = cursor.fetchone()
                duel_id = result[0] if result else None
                
            connection.commit()
            return duel_id
        except Exception as e:
            print(f"创建生死战游戏失败: {e}")
            connection.rollback()
            return None
        finally:
            connection.close()
    
    def get_active_duel(self, challenger_id=None, challenged_id=None, group_id=None):
        """获取活跃的生死战游戏"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                query = """
                    SELECT * FROM duel_games 
                    WHERE status IN ('waiting', 'playing')
                """
                params = []
                
                if challenger_id:
                    query += " AND challenger_id = %s"
                    params.append(challenger_id)
                
                if challenged_id:
                    query += " AND challenged_id = %s"
                    params.append(challenged_id)
                
                if group_id:
                    query += " AND group_id = %s"
                    params.append(group_id)
                
                cursor.execute(query, params)
                return cursor.fetchone()
        except Exception as e:
            print(f"获取生死战游戏失败: {e}")
            return None
        finally:
            connection.close()
    
    def get_duel_by_id(self, duel_id):
        """根据ID获取生死战游戏"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM duel_games 
                    WHERE id = %s
                """, (duel_id,))
                return cursor.fetchone()
        except Exception as e:
            print(f"获取生死战游戏失败: {e}")
            return None
        finally:
            connection.close()
    
    def update_duel(self, duel_id, **kwargs):
        """更新生死战游戏"""
        if not kwargs:
            return False
        
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 构建更新语句
                set_clause = ', '.join([f"{k} = %s" for k in kwargs.keys()])
                query = f"UPDATE duel_games SET {set_clause} WHERE id = %s"
                
                # 构建参数
                params = list(kwargs.values())
                params.append(duel_id)
                
                cursor.execute(query, params)
            
            connection.commit()
            return True
        except Exception as e:
            print(f"更新生死战游戏失败: {e}")
            connection.rollback()
            return False
        finally:
            connection.close()
    
    def get_active_duels_by_user(self, user_id):
        """获取用户参与的所有活跃生死战"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM duel_games 
                    WHERE (challenger_id = %s OR challenged_id = %s)
                    AND status IN ('waiting', 'playing')
                """, (user_id, user_id))
                return cursor.fetchall()
        except Exception as e:
            print(f"获取用户生死战游戏失败: {e}")
            return []
        finally:
            connection.close()
    
    def get_timeout_duels(self):
        """获取所有超时的生死战"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                # 获取状态为playing且最后活动时间超过2分钟，或状态为waiting且最后活动时间超过1分钟的对决
                query = """
                    SELECT * FROM duel_games 
                    WHERE (
                        (status = 'playing' AND last_action_time < DATE_SUB(NOW(), INTERVAL 2 MINUTE))
                        OR 
                        (status = 'waiting' AND last_action_time < DATE_SUB(NOW(), INTERVAL 1 MINUTE))
                    )
                """
                cursor.execute(query)
                result = cursor.fetchall()
                if result:
                    print(f"数据库查询到 {len(result)} 条超时生死战记录")
                    for duel in result:
                        print(f"- ID: {duel['id']}, 状态: {duel['status']}, 上次操作: {duel['last_action_time']}")
                return result
        except Exception as e:
            print(f"获取超时生死战失败: {e}")
            return []
        finally:
            connection.close()

    # ========== 飞升系统 ==========
    def get_ascension_task(self, user_id):
        """获取用户飞升任务状态"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM ascension_tasks 
                    WHERE user_id = %s
                """, (user_id,))
                return cursor.fetchone()
        finally:
            connection.close()
    
    def create_ascension_task(self, user_id):
        """创建飞升任务"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 确保ascension_tasks表有所需字段
                try:
                    cursor.execute("""
                        ALTER TABLE ascension_tasks 
                        ADD COLUMN IF NOT EXISTS math_question TEXT NULL,
                        ADD COLUMN IF NOT EXISTS math_answer INT NULL
                    """)
                    connection.commit()
                    print("已确保ascension_tasks表包含math_question和math_answer字段")
                except Exception as e:
                    print(f"更新ascension_tasks表结构失败: {e}")
                
                # 创建飞升任务记录
                cursor.execute("""
                    INSERT IGNORE INTO ascension_tasks 
                    (user_id, current_stage, duel_wins, math_attempts, shared_books)
                    VALUES (%s, 1, 0, 0, 0)
                """, (user_id,))
            connection.commit()
            return True
        except Exception as e:
            print(f"创建飞升任务失败: {e}")
            connection.rollback()
            return False
        finally:
            connection.close()
    
    def update_ascension_task(self, user_id, **kwargs):
        """更新飞升任务状态"""
        if not kwargs:
            return False
            
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 构建更新查询
                query = "UPDATE ascension_tasks SET "
                query += ", ".join([f"{key} = %s" for key in kwargs.keys()])
                query += ", last_update = NOW() WHERE user_id = %s"
                
                # 构建参数
                params = list(kwargs.values())
                params.append(user_id)
                
                cursor.execute(query, params)
            connection.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"更新飞升任务失败: {e}")
            connection.rollback()
            return False
        finally:
            connection.close()
    
    def reset_ascension_task(self, user_id):
        """重置飞升任务"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE ascension_tasks 
                    SET current_stage = 1, duel_wins = 0, math_attempts = 0, shared_books = 0,
                        last_update = NOW()
                    WHERE user_id = %s
                """, (user_id,))
            connection.commit()
            return cursor.rowcount > 0
        except Exception as e:
            print(f"重置飞升任务失败: {e}")
            connection.rollback()
            return False
        finally:
            connection.close()
    
    def record_ascension_duel_win(self, user_id, duel_id):
        """记录飞升任务的生死战胜利"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 检查是否已记录过这场胜利
                cursor.execute("""
                    SELECT * FROM ascension_duel_wins 
                    WHERE user_id = %s AND duel_id = %s
                """, (user_id, duel_id))
                
                if cursor.fetchone():
                    return False  # 已记录过
                
                # 记录新的胜利
                cursor.execute("""
                    INSERT INTO ascension_duel_wins (user_id, duel_id)
                    VALUES (%s, %s)
                """, (user_id, duel_id))
                
                # 更新任务记录中的胜利次数
                cursor.execute("""
                    UPDATE ascension_tasks 
                    SET duel_wins = duel_wins + 1,
                        last_update = NOW()
                    WHERE user_id = %s
                """, (user_id,))
                
            connection.commit()
            return True
        except Exception as e:
            print(f"记录飞升任务生死战胜利失败: {e}")
            connection.rollback()
            return False
        finally:
            connection.close()
    
    def get_ascension_duel_wins(self, user_id):
        """获取用户飞升任务中的生死战胜利次数"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT COUNT(*) FROM ascension_duel_wins 
                    WHERE user_id = %s
                """, (user_id,))
                result = cursor.fetchone()
                return result[0] if result else 0
        finally:
            connection.close()
            
    def remove_all_ascension_duel_wins(self, user_id):
        """清除用户所有飞升任务生死战胜利记录"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM ascension_duel_wins 
                    WHERE user_id = %s
                """, (user_id,))
            connection.commit()
            return True
        except Exception as e:
            print(f"清除飞升任务生死战胜利记录失败: {e}")
            connection.rollback()
            return False
        finally:
            connection.close()

    def get_user_groups(self, user_id):
        """获取用户所在的所有群组"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT g.group_id, g.group_name
                    FROM user_group ug
                    JOIN authorized_groups g ON ug.group_id = g.group_id
                    WHERE ug.user_id = %s
                """, (user_id,))
                return cursor.fetchall()
        except Exception as e:
            print(f"获取用户群组出错: {e}")
            return []
        finally:
            connection.close()
            
    def remove_user_from_group(self, user_id, group_id):
        """从群组中移除用户关系"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    DELETE FROM user_group
                    WHERE user_id = %s AND group_id = %s
                """, (user_id, group_id))
                connection.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"从群组移除用户出错: {e}")
            return False
        finally:
            connection.close()

    def update_book_upload_count(self, user_id, increment=1):
        """更新用户当天上传书籍数量，如果达到10本则激活保护罩"""
        connection = self.get_connection()
        today = date.today()
        try:
            with connection.cursor() as cursor:
                # 获取今日上传记录
                cursor.execute("""
                    SELECT * FROM shield_records
                    WHERE user_id = %s AND date = %s
                """, (user_id, today))
                record = cursor.fetchone()
                
                if record:
                    # 更新现有记录
                    cursor.execute("""
                        UPDATE shield_records
                        SET books_uploaded = books_uploaded + %s
                        WHERE user_id = %s AND date = %s
                    """, (increment, user_id, today))
                else:
                    # 创建新记录
                    cursor.execute("""
                        INSERT INTO shield_records (user_id, date, books_uploaded, shield_active)
                        VALUES (%s, %s, %s, FALSE)
                    """, (user_id, today, increment))
                    
                # 获取更新后的记录
                cursor.execute("""
                    SELECT books_uploaded FROM shield_records
                    WHERE user_id = %s AND date = %s
                """, (user_id, today))
                updated_record = cursor.fetchone()
                books_uploaded = updated_record[0] if updated_record else 0
                
                # 如果达到10本，激活保护罩
                if books_uploaded >= 10:
                    cursor.execute("""
                        UPDATE shield_records
                        SET shield_active = TRUE
                        WHERE user_id = %s AND date = %s
                    """, (user_id, today))
                
                # 更新用户总上传书籍数量
                cursor.execute("""
                    UPDATE users 
                    SET total_books_uploaded = total_books_uploaded + %s
                    WHERE user_id = %s
                """, (increment, user_id))
                    
            connection.commit()
            return books_uploaded
        except Exception as e:
            print(f"更新书籍上传数量出错: {e}")
            return 0
        finally:
            connection.close()
    
    def has_active_shield(self, user_id):
        """检查用户是否有激活的保护罩"""
        connection = self.get_connection()
        today = date.today()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT shield_active FROM shield_records
                    WHERE user_id = %s AND date = %s
                """, (user_id, today))
                result = cursor.fetchone()
                return result and result[0]
        except Exception as e:
            print(f"检查保护罩状态出错: {e}")
            return False
        finally:
            connection.close()
            
    def get_shield_status(self, user_id):
        """获取用户的保护罩状态"""
        connection = self.get_connection()
        today = date.today()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT books_uploaded, shield_active FROM shield_records
                    WHERE user_id = %s AND date = %s
                """, (user_id, today))
                result = cursor.fetchone()
                
                if result:
                    return {
                        "books_uploaded": result[0],
                        "shield_active": bool(result[1])
                    }
                else:
                    return {
                        "books_uploaded": 0,
                        "shield_active": False
                    }
        except Exception as e:
            print(f"获取保护罩状态出错: {e}")
            return {
                "books_uploaded": 0,
                "shield_active": False
            }
        finally:
            connection.close()

    def get_top_uploaders(self, limit=10):
        """获取上传书籍最多的用户（功德榜）"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT u.user_id, u.username, u.first_name, u.last_name, u.points, u.total_books_uploaded, c.stage
                    FROM users u
                    JOIN user_cultivation c ON u.user_id = c.user_id
                    ORDER BY u.total_books_uploaded DESC, c.stage DESC, u.points DESC
                    LIMIT %s
                """, (limit,))
                return cursor.fetchall()
        except Exception as e:
            print(f"获取功德榜失败: {e}")
            return []
        finally:
            connection.close()

    def check_immortal_daily_chat(self, user_id):
        """检查地仙用户今天是否已经被欢迎过"""
        connection = self.get_connection()
        today = date.today()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT has_greeted FROM immortal_daily_chat
                    WHERE user_id = %s AND date = %s
                """, (user_id, today))
                result = cursor.fetchone()
                
                # 如果没有记录或未被欢迎，返回False
                if not result:
                    # 创建新记录
                    cursor.execute("""
                        INSERT INTO immortal_daily_chat (user_id, date, has_greeted)
                        VALUES (%s, %s, FALSE)
                        ON DUPLICATE KEY UPDATE date = VALUES(date)
                    """, (user_id, today))
                    connection.commit()
                    return False
                
                return bool(result[0])
        except Exception as e:
            print(f"检查地仙每日发言状态出错: {e}")
            return True  # 出错时返回True防止重复欢迎
        finally:
            connection.close()
            
    def mark_immortal_greeted(self, user_id):
        """标记地仙用户今天已经被欢迎过"""
        connection = self.get_connection()
        today = date.today()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO immortal_daily_chat (user_id, date, has_greeted)
                    VALUES (%s, %s, TRUE)
                    ON DUPLICATE KEY UPDATE has_greeted = TRUE
                """, (user_id, today))
                connection.commit()
                return True
        except Exception as e:
            print(f"标记地仙欢迎状态出错: {e}")
            return False
        finally:
            connection.close()
            
    def is_immortal(self, user_id):
        """检查用户是否为地仙"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT stage FROM user_cultivation
                    WHERE user_id = %s
                """, (user_id,))
                result = cursor.fetchone()
                
                if not result:
                    return False
                
                # 检查是否已达到地仙境界
                from bot.config.config import CULTIVATION_STAGES
                return result[0] >= len(CULTIVATION_STAGES)
        except Exception as e:
            print(f"检查用户是否为地仙出错: {e}")
            return False
        finally:
            connection.close()

    def get_all_pending_catgirls(self):
        """获取所有处于等待确认状态的猫娘记录"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT c.*, u1.username as master_name, u2.username as user_name 
                    FROM catgirl_records c
                    JOIN users u1 ON c.master_id = u1.user_id
                    JOIN users u2 ON c.user_id = u2.user_id
                    WHERE c.status = 'pending'
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"获取等待确认的猫娘记录失败: {e}")
            return []
        finally:
            connection.close()
    
    def get_all_confirmed_catgirls(self):
        """获取所有已确认状态的猫娘记录"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT c.*, u1.username as master_name, u2.username as user_name 
                    FROM catgirl_records c
                    JOIN users u1 ON c.master_id = u1.user_id
                    JOIN users u2 ON c.user_id = u2.user_id
                    WHERE c.status = 'confirmed'
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"获取已确认的猫娘记录失败: {e}")
            return []
        finally:
            connection.close()
            
    def save_hongbao(self, hongbao_id, hongbao_data):
        """保存红包数据到数据库"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 首先检查红包表是否存在，不存在则创建
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS hongbao_records (
                        hongbao_id VARCHAR(36) PRIMARY KEY,
                        creator_id BIGINT NOT NULL,
                        creator_name VARCHAR(255),
                        total_amount INT NOT NULL,
                        total_people INT NOT NULL,
                        remaining_amount INT NOT NULL,
                        remaining_people INT NOT NULL,
                        claimed_users JSON,
                        chat_id BIGINT NOT NULL,
                        message_id BIGINT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        expires_at TIMESTAMP
                    )
                """)
                
                # 将字典转换为JSON
                import json
                claimed_users_json = json.dumps(hongbao_data.get('claimed_users', {}))
                
                # 计算过期时间
                from datetime import datetime, timedelta
                created_at = hongbao_data.get('created_at', datetime.now())
                expires_at = created_at + timedelta(hours=24)
                
                # 插入或更新红包记录
                cursor.execute("""
                    INSERT INTO hongbao_records
                    (hongbao_id, creator_id, creator_name, total_amount, total_people,
                     remaining_amount, remaining_people, claimed_users, chat_id,
                     message_id, created_at, expires_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                    remaining_amount = VALUES(remaining_amount),
                    remaining_people = VALUES(remaining_people),
                    claimed_users = VALUES(claimed_users),
                    message_id = VALUES(message_id)
                """, (
                    hongbao_id,
                    hongbao_data.get('creator_id'),
                    hongbao_data.get('creator_name', ''),
                    hongbao_data.get('total_amount', 0),
                    hongbao_data.get('total_people', 0),
                    hongbao_data.get('remaining_amount', 0),
                    hongbao_data.get('remaining_people', 0),
                    claimed_users_json,
                    hongbao_data.get('chat_id', 0),
                    hongbao_data.get('message_id'),
                    created_at,
                    expires_at
                ))
                connection.commit()
                return True
        except Exception as e:
            print(f"保存红包记录失败: {e}")
            connection.rollback()
            return False
        finally:
            connection.close()
    
    def get_all_active_hongbaos(self):
        """获取所有活跃的红包记录"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM hongbao_records
                    WHERE remaining_people > 0
                    AND expires_at > NOW()
                """)
                hongbao_records = cursor.fetchall()
                
                # 处理JSON字段
                import json
                result = []
                for record in hongbao_records:
                    # 将JSON字符串转换为字典
                    if isinstance(record['claimed_users'], str):
                        record['claimed_users'] = json.loads(record['claimed_users'])
                    result.append(record)
                
                return result
        except Exception as e:
            print(f"获取活跃红包记录失败: {e}")
            return []
        finally:
            connection.close()

    # ========== 大乐透系统 ==========
    def ensure_lottery_tables(self):
        """确保数据库中有大乐透相关的表"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                # 创建大乐透号码表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS lottery_numbers (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        numbers VARCHAR(10) NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                """)
                
                # 创建大乐透下注表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS lottery_bets (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        user_id BIGINT NOT NULL,
                        username VARCHAR(255),
                        numbers VARCHAR(10) NOT NULL,
                        bet_count INT NOT NULL,
                        cost INT NOT NULL,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(user_id)
                    ) ENGINE=InnoDB
                """)
                
                # 创建大乐透奖池表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS lottery_pool (
                        id INT PRIMARY KEY DEFAULT 1,
                        amount INT NOT NULL DEFAULT 100000,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                """)
                
                # 创建大乐透消息ID表
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS lottery_message (
                        id INT PRIMARY KEY DEFAULT 1,
                        message_id BIGINT,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
                    ) ENGINE=InnoDB
                """)
                
                # 检查奖池表是否有数据，如果没有则初始化
                cursor.execute("SELECT COUNT(*) FROM lottery_pool")
                count = cursor.fetchone()[0]
                if count == 0:
                    cursor.execute("""
                        INSERT INTO lottery_pool (id, amount) VALUES (1, 100000)
                    """)
                
            connection.commit()
        except Exception as e:
            print(f"确保大乐透表存在时出错: {e}")
        finally:
            connection.close()
            
    def save_lottery_numbers(self, numbers):
        """保存大乐透中奖号码
        
        Args:
            numbers: 中奖号码列表 [n1, n2, n3]
        """
        connection = self.get_connection()
        try:
            numbers_str = ''.join(map(str, numbers))
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO lottery_numbers (numbers)
                    VALUES (%s)
                """, (numbers_str,))
            connection.commit()
            return True
        except Exception as e:
            print(f"保存大乐透号码失败: {e}")
            return False
        finally:
            connection.close()
            
    def get_lottery_numbers(self):
        """获取最新的大乐透中奖号码"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT numbers FROM lottery_numbers
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                result = cursor.fetchone()
                if result:
                    # 将字符串转换为数字列表
                    return [int(n) for n in result['numbers']]
                return None
        except Exception as e:
            print(f"获取大乐透号码失败: {e}")
            return None
        finally:
            connection.close()
            
    def save_lottery_bet(self, user_id, username, numbers, bet_count, cost):
        """保存用户下注记录
        
        Args:
            user_id: 用户ID
            username: 用户名
            numbers: 下注号码字符串
            bet_count: 下注数量
            cost: 花费的积分
        """
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO lottery_bets (user_id, username, numbers, bet_count, cost)
                    VALUES (%s, %s, %s, %s, %s)
                """, (user_id, username, numbers, bet_count, cost))
            connection.commit()
            return True
        except Exception as e:
            print(f"保存大乐透下注失败: {e}")
            return False
        finally:
            connection.close()
            
    def get_all_lottery_bets(self):
        """获取所有当前的下注记录"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM lottery_bets
                    ORDER BY created_at
                """)
                return cursor.fetchall()
        except Exception as e:
            print(f"获取大乐透下注记录失败: {e}")
            return []
        finally:
            connection.close()
            
    def reset_lottery_bets(self):
        """重置大乐透下注记录（开奖后清空）"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("TRUNCATE TABLE lottery_bets")
            connection.commit()
            return True
        except Exception as e:
            print(f"重置大乐透下注记录失败: {e}")
            return False
        finally:
            connection.close()
            
    def update_lottery_pool(self, amount):
        """更新大乐透奖池金额
        
        Args:
            amount: 新的奖池金额
        """
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    UPDATE lottery_pool
                    SET amount = %s
                    WHERE id = 1
                """, (amount,))
            connection.commit()
            return True
        except Exception as e:
            print(f"更新大乐透奖池金额失败: {e}")
            return False
        finally:
            connection.close()
            
    def get_lottery_pool(self):
        """获取当前大乐透奖池信息"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM lottery_pool
                    WHERE id = 1
                """)
                return cursor.fetchone()
        except Exception as e:
            print(f"获取大乐透奖池信息失败: {e}")
            return None
        finally:
            connection.close()
            
    def save_lottery_message_id(self, message_id):
        """保存大乐透公告消息ID
        
        Args:
            message_id: 消息ID
        """
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    INSERT INTO lottery_message (id, message_id)
                    VALUES (1, %s)
                    ON DUPLICATE KEY UPDATE message_id = %s
                """, (message_id, message_id))
            connection.commit()
            return True
        except Exception as e:
            print(f"保存大乐透消息ID失败: {e}")
            return False
        finally:
            connection.close()
            
    def get_lottery_message_id(self):
        """获取当前大乐透公告消息ID"""
        connection = self.get_connection()
        try:
            with connection.cursor() as cursor:
                cursor.execute("""
                    SELECT message_id FROM lottery_message
                    WHERE id = 1
                """)
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            print(f"获取大乐透消息ID失败: {e}")
            return None
        finally:
            connection.close()
            
    def get_today_lottery(self):
        """获取今天的大乐透记录"""
        connection = self.get_connection()
        try:
            with connection.cursor(pymysql.cursors.DictCursor) as cursor:
                cursor.execute("""
                    SELECT * FROM lottery_numbers
                    WHERE DATE(created_at) = CURDATE()
                    ORDER BY created_at DESC
                    LIMIT 1
                """)
                return cursor.fetchone()
        except Exception as e:
            print(f"获取今天的大乐透记录失败: {e}")
            return None
        finally:
            connection.close()

    # 兑换码相关方法
    def add_redemption_code(self, code, creator_id):
        """添加新的兑换码"""
        try:
            connection = self.get_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO redemption_codes (code, creator_id) VALUES (%s, %s)",
                    (code, creator_id)
                )
                connection.commit()
                return True
        except Exception as e:
            print(f"添加兑换码失败: {e}")
            return False
        finally:
            connection.close()
    
    def get_unused_redemption_code(self):
        """获取一个未使用的兑换码"""
        try:
            connection = self.get_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT code FROM redemption_codes WHERE used = FALSE ORDER BY RAND() LIMIT 1"
                )
                result = cursor.fetchone()
                return result[0] if result else None
        except Exception as e:
            print(f"获取未使用兑换码失败: {e}")
            return None
        finally:
            connection.close()
    
    def mark_redemption_code_used(self, code, user_id):
        """标记兑换码为已使用"""
        try:
            connection = self.get_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE redemption_codes SET used = TRUE, used_by = %s, used_at = NOW() WHERE code = %s AND used = FALSE",
                    (user_id, code)
                )
                connection.commit()
                return cursor.rowcount > 0
        except Exception as e:
            print(f"标记兑换码使用失败: {e}")
            return False
        finally:
            connection.close()
    
    def is_code_used(self, code):
        """检查兑换码是否已被使用"""
        try:
            connection = self.get_connection()
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT used FROM redemption_codes WHERE code = %s",
                    (code,)
                )
                result = cursor.fetchone()
                return result[0] if result else True  # 如果不存在则视为已使用
        except Exception as e:
            print(f"检查兑换码状态失败: {e}")
            return True
        finally:
            connection.close()
    
    def get_redemption_codes_count(self, used=None):
        """获取兑换码数量，可以指定是否已使用"""
        try:
            connection = self.get_connection()
            with connection.cursor() as cursor:
                if used is None:
                    cursor.execute("SELECT COUNT(*) as count FROM redemption_codes")
                else:
                    cursor.execute(
                        "SELECT COUNT(*) as count FROM redemption_codes WHERE used = %s",
                        (used,)
                    )
                result = cursor.fetchone()
                # 返回的result是元组，第一个元素就是计数值
                return result[0] if result else 0
        except Exception as e:
            print(f"获取兑换码数量失败: {e}")
            return 0
        finally:
            connection.close()

# 创建全局数据库服务实例
db_service = DBService()