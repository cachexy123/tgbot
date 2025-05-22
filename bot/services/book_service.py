import os
from bot.config.config import BOOK_DOWNLOAD_PATH, BOOK_POINT_REWARD, ALLOWED_EXTENSIONS
from bot.services.db_service import db_service
from bot.utils.helpers import calculate_md5, ensure_dir
import pyrogram
import asyncio

class BookService:
    def __init__(self):
        self.db = db_service
        # 确保下载目录存在
        ensure_dir(BOOK_DOWNLOAD_PATH)
    
    async def process_book_file(self, file_id, file_name, user_id, client):
        """处理书籍文件下载"""
        # 检查文件类型是否允许
        file_ext = os.path.splitext(file_name)[1].lower()
        if file_ext not in ALLOWED_EXTENSIONS:
            return {
                'success': False,
                'message': f"不支持的文件类型: {file_ext}，只允许 {', '.join(ALLOWED_EXTENSIONS)}"
            }
        
        # 构建保存路径
        save_path = os.path.join(BOOK_DOWNLOAD_PATH, file_name)
        
        try:
            # 下载文件，添加洪水控制异常处理
            max_retries = 3
            retry_count = 0
            download_success = False
            
            while not download_success and retry_count < max_retries:
                try:
                    await client.download_media(file_id, save_path)
                    download_success = True
                except pyrogram.errors.exceptions.flood_420.FloodWait as e:
                    print(f"FloodWait: 需要等待 {e.value} 秒下载文件: {file_name}")
                    retry_count += 1
                    if retry_count < max_retries:
                        # 减少等待时间，但不低于1秒
                        adjusted_wait = max(1, e.value // 2)
                        await asyncio.sleep(adjusted_wait)
                    else:
                        raise Exception(f"达到最大重试次数，无法下载文件: {file_name}")
            
            if not download_success:
                return {
                    'success': False,
                    'message': "文件下载失败，请稍后重试"
                }
            
            # 计算MD5
            file_md5 = calculate_md5(save_path)
            
            # 检查文件是否已存在（通过MD5值）
            exists = self.db.check_file_exists(file_md5)
            
            if exists:
                # 文件已存在，删除刚下载的副本
                os.remove(save_path)
                return {
                    'success': True,
                    'is_duplicate': True,
                    'message': f"文件 {file_name} 已经存在，跳过奖励"
                }
            
            # 添加文件记录到数据库
            self.db.add_file_record(file_md5, user_id)
            
            # 给用户加积分
            new_points = self.db.update_points(user_id, BOOK_POINT_REWARD)
            
            # 更新书籍上传计数并检查是否激活保护罩
            books_uploaded = self.db.update_book_upload_count(user_id)
            shield_activated = books_uploaded >= 10
            
            result = {
                'success': True,
                'is_duplicate': False,
                'message': f"成功保存书籍 {file_name}",
                'reward': BOOK_POINT_REWARD,
                'new_points': new_points,
                'books_uploaded': books_uploaded
            }
            
            # 如果刚刚达到10本书并激活保护罩，添加提示信息
            if shield_activated and books_uploaded == 10:
                result['shield_activated'] = True
                result['message'] += "，并且激活了今日保护罩！"
            
            return result
            
        except Exception as e:
            print(f"处理文件 {file_name} 时出错: {e}")
            # 如果下载失败，尝试清理可能部分下载的文件
            if os.path.exists(save_path):
                try:
                    os.remove(save_path)
                except:
                    pass
            
            return {
                'success': False,
                'message': f"处理文件失败: {str(e)}"
            }

# 创建全局书籍服务实例
book_service = BookService() 