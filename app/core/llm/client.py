"""
LLM 客户端模块
支持多种 LLM Provider 的统一接口
"""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    AsyncGenerator,
    Dict,
    List,
    Literal,
    Optional,
    Union,
)

import httpx
from openai import AsyncOpenAI
from openai.types.chat import ChatCompletion, ChatCompletionMessageParam
from openai.types.chat.chat_completion import Choice
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.logger import get_logger
from app.core.tracing import finish_llm_call, mark_llm_first_token, start_llm_call

logger = get_logger(__name__)


class MessageRole(str, Enum):
    """消息角色"""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass
class LLMMessage:
    """LLM 消息"""
    role: MessageRole | str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> dict:
        result: dict = {
            "role": self.role.value if isinstance(self.role, MessageRole) else self.role,
            "content": self.content,
        }
        if self.name:
            result["name"] = self.name
        if self.tool_call_id:
            result["tool_call_id"] = self.tool_call_id
        return result


@dataclass
class ToolCall:
    """工具调用"""
    id: str
    name: str
    arguments: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": self.arguments,
            },
        }


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    parameters: dict

    def to_dict(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    usage: dict
    finish_reason: str
    tool_calls: List[ToolCall] = field(default_factory=list)

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0


class BaseLLMClient(ABC):
    """LLM 客户端基类"""

    @abstractmethod
    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""
        pass

    @abstractmethod
    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        pass

    @abstractmethod
    async def embeddings(self, texts: List[str]) -> List[List[float]]:
        """获取文本嵌入"""
        pass


class OpenRouterClient(BaseLLMClient):
    """
    OpenRouter API 客户端
    支持 OpenAI 兼容格式
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 30,  # 降低超时时间，加快响应
    ):
        self.api_key = api_key or settings.llm.api_key
        self.base_url = base_url or settings.llm.base_url
        self.model = model or settings.llm.model
        self.timeout = timeout

        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            timeout=timeout,
            http_client=httpx.AsyncClient(timeout=httpx.Timeout(timeout)),
        )

    @retry(
        stop=stop_after_attempt(2),  # 减少重试次数
        wait=wait_exponential(multiplier=1, min=1, max=5),  # 缩短等待时间
    )
    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""

        # 转换为 API 格式
        api_messages = [msg.to_dict() for msg in messages]

        # 构建请求参数
        request_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": temperature or settings.llm.temperature,
            "max_tokens": max_tokens or settings.llm.max_tokens,
        }

        if tools:
            request_kwargs["tools"] = [tool.to_dict() for tool in tools]
            request_kwargs["tool_choice"] = "auto"

        try:
            response: ChatCompletion = await self.client.chat.completions.create(
                **request_kwargs
            )

            return self._parse_response(response)

        except Exception as e:
            logger.error(f"LLM API 调用失败: {e}")
            raise

    def _parse_response(self, response: ChatCompletion) -> LLMResponse:
        """解析 API 响应"""
        choice: Choice = response.choices[0]
        message = choice.message

        # 解析 tool_calls
        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                if tc.function:
                    tool_calls.append(
                        ToolCall(
                            id=tc.id or "",
                            name=tc.function.name or "",
                            arguments=tc.function.arguments or "{}",
                        )
                    )

        return LLMResponse(
            content=message.content or "",
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                "total_tokens": response.usage.total_tokens if response.usage else 0,
            },
            finish_reason=choice.finish_reason or "",
            tool_calls=tool_calls,
        )

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: Optional[float] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""

        api_messages = [msg.to_dict() for msg in messages]

        request_kwargs: Dict[str, Any] = {
            "model": self.model,
            "messages": api_messages,
            "temperature": temperature or settings.llm.temperature,
            "stream": True,
        }

        if tools:
            request_kwargs["tools"] = [tool.to_dict() for tool in tools]

        try:
            stream = await self.client.chat.completions.create(**request_kwargs)

            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content

        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            raise

    async def embeddings(self, texts: List[str]) -> List[List[float]]:
        """获取文本嵌入"""
        try:
            response = await self.client.embeddings.create(
                model="text-embedding-3-small",
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error(f"Embedding 获取失败: {e}")
            raise


class OllamaClient(BaseLLMClient):
    """
    Ollama 本地模型客户端
    支持本地部署的模型（如 Qwen2.5, Llama3.2 等）
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "qwen2.5",
        timeout: int = 120,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
        )

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""
        # 转换消息格式 (Ollama 格式)
        ollama_messages = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            ollama_messages.append({
                "role": role,
                "content": msg.content,
            })

        request_data: Dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": False,
            "options": {
                "temperature": temperature or 0.7,
                "num_predict": max_tokens or 4096,
            },
        }

        # 添加 tools 如果支持
        if tools:
            request_data["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool.parameters,
                    }
                }
                for tool in tools
            ]

        try:
            response = await self.client.post("/api/chat", json=request_data)
            response.raise_for_status()
            data = response.json()

            content = data.get("message", {}).get("content", "")

            tool_calls = []
            if "tool_calls" in data.get("message", {}):
                for tc in data["message"]["tool_calls"]:
                    tool_calls.append(
                        ToolCall(
                            id=tc.get("id", ""),
                            name=tc.get("function", {}).get("name", ""),
                            arguments=tc.get("function", {}).get("arguments", "{}"),
                        )
                    )

            return LLMResponse(
                content=content,
                model=self.model,
                usage={
                    "prompt_tokens": data.get("prompt_eval_count", 0),
                    "completion_tokens": data.get("eval_count", 0),
                    "total_tokens": data.get("prompt_eval_count", 0) + data.get("eval_count", 0),
                },
                finish_reason=data.get("done_reason", "stop"),
                tool_calls=tool_calls,
            )

        except httpx.HTTPError as e:
            logger.error(f"Ollama API 调用失败: {e}")
            raise

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        temperature: Optional[float] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        # 转换消息格式
        ollama_messages = []
        for msg in messages:
            role = msg.role.value if hasattr(msg.role, 'value') else msg.role
            ollama_messages.append({
                "role": role,
                "content": msg.content,
            })

        request_data: Dict[str, Any] = {
            "model": self.model,
            "messages": ollama_messages,
            "stream": True,
            "options": {
                "temperature": temperature or 0.7,
                "num_predict": 4096,
            },
        }

        try:
            async with self.client.stream("POST", "/api/chat", json=request_data) as stream:
                async for line in stream.aiter_lines():
                    if line:
                        import json
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            content = data["message"]["content"]
                            if content:
                                yield content

        except httpx.HTTPError as e:
            logger.error(f"Ollama 流式调用失败: {e}")
            raise

    async def embeddings(self, texts: List[str]) -> List[List[float]]:
        """获取文本嵌入"""
        model_name = "nomic-embed-text"

        try:
            embeddings = []
            for text in texts:
                response = await self.client.post(
                    "/api/embeddings",
                    json={"model": model_name, "prompt": text},
                )
                response.raise_for_status()
                data = response.json()
                embeddings.append(data.get("embedding", []))
            return embeddings
        except httpx.HTTPError as e:
            logger.error(f"Ollama embedding 失败: {e}")
            raise

    async def health_check(self) -> bool:
        """健康检查"""
        try:
            response = await self.client.get("/api/tags")
            return response.status_code == 200
        except Exception:
            return False


class MockLLMClient(BaseLLMClient):
    """
    Mock LLM 客户端（用于开发/测试）
    当没有配置 API key 时使用
    """

    # 用于存储上一次意图解析的结果
    _last_intent_info = {}

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> LLMResponse:
        """返回模拟响应"""
        # 分析消息
        user_message = ""
        system_prompt = ""
        for msg in messages:
            if hasattr(msg, 'role'):
                if msg.role == "user":
                    user_message = msg.content
                elif msg.role == "system":
                    system_prompt = msg.content

        # 检测是否需要 JSON 响应（IntentParser 场景）
        if "JSON" in system_prompt or "json" in system_prompt.lower():
            response_content = self._generate_json_response(user_message)
            # 尝试解析并存储意图信息
            try:
                import json
                data = json.loads(response_content)
                self._last_intent_info = data.get("extracted_info", {})
            except:
                pass
        else:
            # 根据系统提示判断是哪个 Agent
            if "景点推荐" in system_prompt or "景点" in system_prompt:
                response_content = self._generate_attraction_response(user_message)
            elif "预算" in system_prompt:
                response_content = self._generate_budget_response(user_message)
            elif "行程" in system_prompt:
                response_content = self._generate_itinerary_response(user_message)
            elif "天气" in system_prompt:
                response_content = self._generate_weather_response(user_message)
            elif "审查" in system_prompt:
                response_content = self._generate_review_response(user_message)
            else:
                response_content = self._generate_response(user_message)

        return LLMResponse(
            content=response_content,
            model="mock-model",
            usage={
                "prompt_tokens": 100,
                "completion_tokens": 200,
                "total_tokens": 300,
            },
            finish_reason="stop",
            tool_calls=[],
        )

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式响应（单次返回）"""
        response = await self.chat(messages, tools, **kwargs)
        yield response.content

    async def embeddings(self, texts: List[str]) -> List[List[float]]:
        """返回随机嵌入向量"""
        import random
        return [[random.random() for _ in range(1536)] for _ in texts]

    def _generate_json_response(self, user_message: str) -> str:
        """生成 JSON 格式的意图解析响应"""
        import re

        # 检测目的地
        destinations = ["杭州", "北京", "上海", "成都", "西安", "桂林", "深圳", "广州", "厦门", "丽江"]
        found_destination = None
        for dest in destinations:
            if dest in user_message:
                found_destination = dest
                break

        # 检测天数
        days_match = re.search(r"(\d+)[天日]", user_message)
        days = int(days_match.group(1)) if days_match else 3

        # 检测人数
        people_match = re.search(r"(\d+)[个人位]", user_message)
        people = int(people_match.group(1)) if people_match else 2

        # 检测预算
        budget_match = re.search(r"(\d+)(?:00)?[0-9]?[元块]", user_message)
        budget = int(budget_match.group(1)) * 100 if budget_match else 5000

        # 确定意图
        if found_destination:
            intent = "trip_planning"
        else:
            intent = "general_chat"

        return f'{{"intent": "{intent}", "extracted_info": {{"destination": "{found_destination or ""}", "duration": {days}, "num_travelers": {people}, "budget": {budget}, "travel_styles": []}}}}'

    def _generate_attraction_response(self, user_message: str) -> str:
        """生成景点推荐响应"""
        dest = self._last_intent_info.get("destination", "当地")
        return f"""## {dest}景点推荐

根据您的需求，为您推荐以下景点：

### 必去经典景点
1. **西湖** - 杭州的标志性景点，环境优美，适合漫步
2. **灵隐寺** - 历史悠久的佛教寺院，香火鼎盛
3. **宋城** - 体验南宋文化的主题公园

### 特色景点
1. **河坊街** - 古老的商业街，可以品尝当地小吃
2. **龙井村** - 著名的龙井茶产地，空气清新

### 适合人群
- 西湖适合所有人群，老人家也可以轻松游览
- 灵隐寺建议穿舒适的鞋子
- 记得提前预约热门景点门票"""

    def _generate_budget_response(self, user_message: str) -> str:
        """生成预算分析响应"""
        days = self._last_intent_info.get("duration", 3)
        people = self._last_intent_info.get("num_travelers", 2)
        budget = self._last_intent_info.get("budget", 5000)

        per_person = budget // people
        per_day = per_person // days

        return f"""## 预算分析

### 总体预算
- 总预算：{budget}元
- 人均预算：{per_person}元
- 每日预算：约{per_day}元

### 费用分配建议
| 类别 | 占比 | 金额 |
|------|------|------|
| 交通 | 20% | {int(budget*0.2)}元 |
| 住宿 | 35% | {int(budget*0.35)}元 |
| 餐饮 | 20% | {int(budget*0.2)}元 |
| 门票 | 15% | {int(budget*0.15)}元 |
| 其他 | 10% | {int(budget*0.1)}元 |

### 省钱建议
1. 提前预订机票/火车票
2. 选择性价比高的酒店
3. 尝试当地特色小吃，比餐厅便宜"""

    def _generate_itinerary_response(self, user_message: str) -> str:
        """生成行程规划响应"""
        dest = self._last_intent_info.get("destination", "当地")
        days = self._last_intent_info.get("duration", 3)
        return f"""## {dest}{days}日行程规划

### 第1天：抵达与休整
- 上午：抵达后前往酒店办理入住
- 中午：在酒店附近品尝当地美食
- 下午：游览核心景区
- 晚上：欣赏夜景，休息调整

### 第2天：深度游览
- 上午：参观著名景点
- 中午：尝试当地特色午餐
- 下午：继续探索周边景点
- 晚上：自由活动时间

### 第3天：休闲返程
- 上午：安排轻松的景点
- 中午：享受最后一顿美食
- 下午：准备返程

### 温馨提示
- 建议提前查看天气预报
- 热门景点请提前预约"""

    def _generate_weather_response(self, user_message: str) -> str:
        """生成天气响应"""
        dest = self._last_intent_info.get("destination", "当地")
        return f"""## {dest}天气预报

### 出行建议
- 温度适宜，建议携带薄外套
- 可能有小雨，请带好雨具
- 紫外线较强，注意防晒

### 穿着建议
- 白天：轻薄长袖+短裤/长裙
- 早晚：添加薄外套
- 鞋子：舒适的步行鞋

### 必备物品
- 雨伞/雨衣
- 防晒霜
- 常用药品"""

    def _generate_review_response(self, user_message: str) -> str:
        """生成审查响应"""
        return """## 规划质量审查报告

### 完整性检查
- [x] 包含目的地介绍
- [x] 有每日行程安排
- [x] 有预算分析
- [x] 有实用贴士

### 质量评分
- 内容质量：8/10
- 实用性：9/10
- 个性化程度：7/10

### 总体评价
规划方案完整合理，可以作为出行参考。建议根据实际情况微调。"""

    def _generate_response(self, user_message: str) -> str:
        """根据用户输入生成模拟响应"""
        user_lower = user_message.lower()

        # 检测目的地
        destinations = ["杭州", "北京", "上海", "成都", "西安", "桂林", "深圳", "杭州"]
        found_destination = None
        for dest in destinations:
            if dest in user_message:
                found_destination = dest
                break

        # 检测天数
        import re
        days_match = re.search(r"(\d+)[天日]", user_message)
        days = int(days_match.group(1)) if days_match else 3

        # 检测人数
        people_match = re.search(r"(\d+)[个人位]", user_message)
        people = int(people_match.group(1)) if people_match else 2

        if found_destination:
            return f"""## {found_destination}旅行规划建议

### 目的地简介
{found_destination}是中国著名的旅游城市，拥有丰富的历史文化和美丽的自然风光。建议游览时间：{days}天。

### 行程安排

**第1天：市区经典游**
- 上午：抵达后入住酒店，休整片刻
- 中午：品尝当地特色美食
- 下午：游览核心景区
- 晚上：欣赏夜景

**第2天：深度体验**
- 上午：参观博物馆或文化遗址
- 中午：尝试当地小吃
- 下午：探索特色街区
- 晚上：自由活动

**第3天：周边休闲**
- 上午：前往周边景点
- 中午：农家乐午餐
- 下午：返回市区，准备返程

### 预算估算（{people}人/{days}天）
| 类别 | 预算 |
|------|------|
| 交通 | ¥800-1500 |
| 住宿 | ¥600-1200 |
| 餐饮 | ¥500-1000 |
| 门票 | ¥400-800 |
| 其他 | ¥200-500 |
| **总计** | **¥2500-5000** |

### 实用贴士
1. 提前查看天气预报，准备合适的衣物
2. 热门景点建议提前预约门票
3. 准备好舒适的步行鞋
4. 随身携带常用药品和防晒用品

祝您旅途愉快！"""

        return f"""## 旅行规划助手

您好！我是您的智能旅行规划助手。

要为您制定完美的旅行规划，请告诉我：
1. **想去哪里？**（目的地）
2. **玩几天？**
3. **几个人一起？**
4. **预算大概多少？**

例如："我想去杭州玩3天，2个人，预算5000元"

我会为您安排好一切！"""


class LLMManager:
    """
    LLM 管理器
    支持多种后端：Ollama (本地) > OpenRouter (云端) > Mock
    """

    def __init__(self):
        self._client: Optional[BaseLLMClient] = None
        self._init_client()

    def _init_client(self) -> None:
        """初始化客户端，优先使用本地 Ollama"""
        # 检查是否配置了 Ollama (本地模型)
        import os
        ollama_base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
        ollama_model = os.environ.get("OLLAMA_MODEL", "qwen2.5")
        
        # 尝试连接 Ollama
        try:
            import httpx
            test_client = httpx.AsyncClient(base_url=ollama_base_url, timeout=5)
            response = test_client.sync_client.get("/api/tags")
            if response.status_code == 200:
                self._client = OllamaClient(
                    base_url=ollama_base_url,
                    model=ollama_model,
                    timeout=120,
                )
                logger.info(f"Ollama 客户端已初始化，使用模型: {ollama_model}")
                return
        except Exception as e:
            logger.debug(f"Ollama 不可用: {e}")

        # 降级到 OpenRouter
        if settings.llm.is_configured:
            self._client = OpenRouterClient()
            logger.info(f"OpenRouter 客户端已初始化，使用模型: {settings.llm.model}")
        else:
            logger.warning("No LLM API key configured, using mock client for demo")
            self._client = MockLLMClient()

    def get_client(self) -> BaseLLMClient:
        """获取 LLM 客户端"""
        if self._client:
            return self._client
        raise ValueError("No LLM client configured")

    def _estimate_message_chars(self, messages: List[LLMMessage]) -> int:
        total = 0
        for message in messages:
            total += len(str(getattr(message, "content", "") or ""))
        return total

    def _client_model_name(self, client: BaseLLMClient) -> str:
        return str(getattr(client, "model", settings.llm.model) or settings.llm.model)

    async def chat(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> LLMResponse:
        """发送对话请求"""
        client = self.get_client()

        try:
            return await client.chat(messages, tools, **kwargs)
        except Exception as e:
            logger.error(f"LLM API 调用失败: {e}")
            # 失败时尝试使用 Mock 客户端
            if not isinstance(client, MockLLMClient):
                logger.info("回退到 Mock 客户端")
                mock_client = MockLLMClient()
                return await mock_client.chat(messages, tools, **kwargs)
            raise

    async def stream(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[ToolDefinition]] = None,
        **kwargs,
    ) -> AsyncGenerator[str, None]:
        """流式对话"""
        client = self.get_client()
        async for chunk in client.stream(messages, tools, **kwargs):
            yield chunk


# 全局 LLM 管理器
_llm_manager: Optional[LLMManager] = None


async def _traced_llm_manager_chat(
    self: LLMManager,
    messages: List[LLMMessage],
    tools: Optional[List[ToolDefinition]] = None,
    **kwargs,
) -> LLMResponse:
    client = self.get_client()
    trace_call = start_llm_call(
        model=self._client_model_name(client),
        streaming=False,
        mock=isinstance(client, MockLLMClient),
        fallback=False,
        message_count=len(messages),
        message_chars=self._estimate_message_chars(messages),
        tool_count=len(tools or []),
    )

    try:
        response = await client.chat(messages, tools, **kwargs)
        finish_llm_call(
            trace_call,
            model=response.model,
            usage=response.usage,
            success=True,
            mock=isinstance(client, MockLLMClient),
            fallback=False,
            output_chars=len(str(response.content or "")),
        )
        return response
    except Exception as exc:
        logger.error(f"LLM API 璋冪敤澶辫触: {exc}")
        if not isinstance(client, MockLLMClient):
            logger.info("Falling back to Mock LLM client")
            mock_client = MockLLMClient()
            try:
                response = await mock_client.chat(messages, tools, **kwargs)
                finish_llm_call(
                    trace_call,
                    model=response.model,
                    usage=response.usage,
                    success=True,
                    mock=True,
                    fallback=True,
                    output_chars=len(str(response.content or "")),
                )
                return response
            except Exception as mock_error:
                finish_llm_call(
                    trace_call,
                    model="mock-model",
                    success=False,
                    error=mock_error,
                    mock=True,
                    fallback=True,
                )
                raise
        finish_llm_call(
            trace_call,
            model=self._client_model_name(client),
            success=False,
            error=exc,
            mock=isinstance(client, MockLLMClient),
            fallback=False,
        )
        raise


async def _traced_llm_manager_stream(
    self: LLMManager,
    messages: List[LLMMessage],
    tools: Optional[List[ToolDefinition]] = None,
    **kwargs,
) -> AsyncGenerator[str, None]:
    client = self.get_client()
    trace_call = start_llm_call(
        model=self._client_model_name(client),
        streaming=True,
        mock=isinstance(client, MockLLMClient),
        fallback=False,
        message_count=len(messages),
        message_chars=self._estimate_message_chars(messages),
        tool_count=len(tools or []),
    )
    chunk_count = 0
    output_chars = 0
    try:
        async for chunk in client.stream(messages, tools, **kwargs):
            if chunk_count == 0:
                mark_llm_first_token(trace_call)
            chunk_count += 1
            output_chars += len(str(chunk or ""))
            yield chunk
    except BaseException as exc:
        finish_llm_call(
            trace_call,
            model=self._client_model_name(client),
            success=False,
            error=exc,
            mock=isinstance(client, MockLLMClient),
            fallback=False,
            output_chars=output_chars,
            chunk_count=chunk_count,
        )
        raise
    else:
        finish_llm_call(
            trace_call,
            model=self._client_model_name(client),
            success=True,
            mock=isinstance(client, MockLLMClient),
            fallback=False,
            output_chars=output_chars,
            chunk_count=chunk_count,
        )


LLMManager.chat = _traced_llm_manager_chat  # type: ignore[method-assign]
LLMManager.stream = _traced_llm_manager_stream  # type: ignore[method-assign]


def get_llm() -> LLMManager:
    """获取 LLM 管理器"""
    global _llm_manager
    if _llm_manager is None:
        _llm_manager = LLMManager()
    return _llm_manager
