import pymysql

def optimize_mysql_connection(connection):
    """优化MySQL连接的事务隔离级别和锁超时设置"""
    try:
        with connection.cursor() as cursor:
            # 设置事务隔离级别为READ COMMITTED，减少锁定
            cursor.execute("SET SESSION TRANSACTION ISOLATION LEVEL READ COMMITTED")
            
            # 设置锁等待超时为5秒
            cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
            
            # 使用较小的事务隔离级别
            cursor.execute("SET SESSION tx_isolation = 'READ-COMMITTED'")
        
        connection.commit()
        return True
    except Exception as e:
        print(f"优化数据库连接失败: {e}")
        return False

def get_optimized_connection(db_config):
    """获取优化后的数据库连接"""
    connection = pymysql.connect(**db_config)
    optimize_mysql_connection(connection)
    return connection 