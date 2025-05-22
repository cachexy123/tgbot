import asyncio
import logging
import signal
import os
import sys
import functools
import traceback
from pyrogram import Client
from pyrogram.errors.exceptions.flood_420 import FloodWait
from bot.config.config import API_TOKEN, API_ID, API_HASH
from bot.handlers.command_handlers import register_command_handlers
from bot.handlers.message_handlers import register_message_handlers
from bot.handlers.callback_handlers import register_callback_handlers
from bot.handlers.scheduler_handlers import setup_scheduler
from bot.handlers.book_handlers import register_book_handlers
from bot.handlers.lottery_handlers import register_lottery_handlers

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 事件循环和停止标志
stop_event = None

# 全局异常处理装饰器
def handle_exceptions(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        max_retries = 3
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                return await func(*args, **kwargs)
            except FloodWait as e:
                logger.warning(f"FloodWait: 需要等待 {e.value} 秒，函数: {func.__name__}")
                retry_count += 1
                if retry_count < max_retries:
                    # 减少等待时间，但不低于1秒
                    adjusted_wait = max(1, e.value // 2)
                    await asyncio.sleep(adjusted_wait)
                else:
                    logger.error(f"达到最大重试次数，无法执行函数: {func.__name__}")
                    raise
            except Exception as e:
                logger.error(f"执行 {func.__name__} 时发生错误: {e}")
                logger.error(traceback.format_exc())
                raise
        
        return None
    
    return wrapper

# 应用异常处理装饰器到Pyrogram方法
def apply_exception_handler():
    # 包装容易触发洪水控制的方法
    critical_methods = [
        "send_message", 
        "edit_message_text", 
        "delete_messages", 
        "download_media",
        "send_photo",
        "send_document",
        "answer_callback_query"
    ]
    
    for method_name in critical_methods:
        if hasattr(Client, method_name):
            original_method = getattr(Client, method_name)
            wrapped_method = handle_exceptions(original_method)
            setattr(Client, method_name, wrapped_method)
            logger.info(f"已为 {method_name} 添加异常处理")

async def main():
    """主函数"""
    global stop_event
    stop_event = asyncio.Event()
    
    # 应用异常处理装饰器
    apply_exception_handler()
    
    # 创建机器人客户端
    app = Client(
        "novel_bot",
        api_id=API_ID,
        api_hash=API_HASH,
        bot_token=API_TOKEN
    )
    
    # 打印启动信息
    logger.info("机器人正在启动...")
    
    # 启动机器人
    await app.start()
    
    # 注册处理器 - 注意注册顺序很重要
    # 命令处理器必须先注册，否则可能会被文本消息处理器捕获
    register_command_handlers(app)
    register_book_handlers(app)  # 先注册书籍处理器，确保它的回调处理器优先级更高
    register_lottery_handlers(app)  # 注册大乐透处理器
    register_callback_handlers(app)
    register_message_handlers(app)
    
    # 设置定时任务
    setup_scheduler(app)
    
    # 获取机器人信息
    bot_info = await app.get_me()
    logger.info(f"机器人启动成功！ @{bot_info.username}")
    
    # 设置信号处理（仅在非Windows系统上）
    if os.name != 'nt':
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: stop_event.set())
    
    # 等待停止信号
    try:
        await stop_event.wait()
    except KeyboardInterrupt:
        # 捕获Ctrl+C
        pass
    finally:
        # 关闭机器人
        await app.stop()
        logger.info("机器人已关闭")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("接收到退出信号，机器人正在关闭...")
    except Exception as e:
        logger.error(f"发生错误: {e}")
        logger.error(traceback.format_exc())
    finally:
        logger.info("机器人已关闭，再见！") 