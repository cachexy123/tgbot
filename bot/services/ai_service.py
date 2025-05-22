import json
import aiohttp
import asyncio
from bot.config.config import (
    AI_ENABLED, AI_BACKEND_URL, AI_API_KEY,
    AI_MODEL, AI_MAX_TOKENS, AI_TEMPERATURE,
    DEFAULT_AI_PROMPT
)

class AIService:
    """AI服务，处理与AI模型的交互"""
    
    def __init__(self):
        self.enabled = AI_ENABLED
        self.backend_url = AI_BACKEND_URL
        self.api_key = AI_API_KEY
        self.default_model = AI_MODEL
        self.max_tokens = AI_MAX_TOKENS
        self.temperature = AI_TEMPERATURE
        self.default_prompt = DEFAULT_AI_PROMPT
        self.conversation_history = {}  # 用户会话历史 {user_id: [messages]}
        self.custom_backend = {}  # 用户自定义后端 {user_id: backend_url}
        self.custom_api_keys = {}  # 用户自定义API密钥 {user_id: api_key}
    
    async def ask(self, user_id, question, reply_to_message=None, first_name=None, last_name=None):
        """向AI发送问题并获取回答"""
        if not self.enabled:
            return {"success": False, "message": "AI功能未启用"}
        
        # 获取用户昵称
        # 优先使用传入的first_name和last_name
        if first_name or last_name:
            if first_name and last_name:
                username = f"{first_name} {last_name}"
            else:
                username = first_name or last_name
        else:
            # 如果没有传入，则尝试从数据库获取
            from bot.services.db_service import db_service
            user = db_service.get_user(user_id) if user_id != 0 else None
            username = user['username'] if user and 'username' in user and user['username'] else "道友"
        
        # 构建系统提示，包含用户昵称
        system_prompt = self.default_prompt.replace("【用户昵称】", username)
        
        # 获取用户的会话历史，如果不存在则初始化
        if user_id not in self.conversation_history:
            self.conversation_history[user_id] = [
                {"role": "system", "content": system_prompt}
            ]
        else:
            # 更新系统提示以包含最新的用户昵称
            self.conversation_history[user_id][0] = {"role": "system", "content": system_prompt}
        
        # 如果是回复其他消息，将该消息作为上下文
        if reply_to_message and reply_to_message.text:
            # 添加被回复的消息作为上下文
            self.conversation_history[user_id].append(
                {"role": "user", "content": reply_to_message.text}
            )
        
        # 添加用户当前问题
        self.conversation_history[user_id].append(
            {"role": "user", "content": question}
        )
        
        # 保持会话历史长度适中，避免token过多
        if len(self.conversation_history[user_id]) > 20:
            # 保留system提示和最近的9条消息
            self.conversation_history[user_id] = [
                self.conversation_history[user_id][0]
            ] + self.conversation_history[user_id][-19:]
        
        try:
            # 获取用户自定义后端或使用默认后端
            backend_url = self.custom_backend.get(user_id, self.backend_url)
            api_key = self.custom_api_keys.get(user_id, self.api_key)
            
            # 构建请求数据
            data = {
                "model": self.default_model,
                "messages": self.conversation_history[user_id],
                "max_tokens": self.max_tokens,
                "temperature": self.temperature
            }
            
            # 发送请求
            async with aiohttp.ClientSession() as session:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}"
                }
                
                endpoint = f"{backend_url}/chat/completions"
                async with session.post(endpoint, headers=headers, json=data) as response:
                    if response.status != 200:
                        error_text = await response.text()
                        return {
                            "success": False, 
                            "message": f"API请求失败: {response.status}, {error_text}"
                        }
                    
                    response_data = await response.json()
                    
                    # 从响应中获取AI的回答
                    ai_response = response_data["choices"][0]["message"]["content"]
                    
                    # 将AI回答添加到会话历史
                    self.conversation_history[user_id].append(
                        {"role": "assistant", "content": ai_response}
                    )
                    
                    return {"success": True, "message": ai_response}
                    
        except Exception as e:
            return {"success": False, "message": f"处理AI请求时出错: {str(e)}"}
    
    def set_custom_backend(self, user_id, backend_url):
        """设置用户自定义后端"""
        self.custom_backend[user_id] = backend_url
        return True
    
    def set_custom_api_key(self, user_id, api_key):
        """设置用户自定义API密钥"""
        self.custom_api_keys[user_id] = api_key
        return True
    
    def reset_conversation(self, user_id):
        """重置用户的会话历史"""
        self.conversation_history[user_id] = [
            {"role": "system", "content": self.default_prompt}
        ]
        return True
    
    def get_conversation_history(self, user_id):
        """获取用户的会话历史"""
        if user_id not in self.conversation_history:
            return []
        return self.conversation_history[user_id]

# 创建全局AI服务实例
ai_service = AIService() 