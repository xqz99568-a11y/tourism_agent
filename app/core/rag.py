"""
RAG Module - 检索增强生成
提供景点知识库检索能力
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING

from app.core.logger import get_logger
from app.storage.vector_store import BaseVectorStore, get_store

if TYPE_CHECKING:
    from app.core.llm.client import LLMManager

logger = get_logger(__name__)


class RetrievalStrategy(str, Enum):
    """检索策略"""
    SIMPLE = "simple"                    # 简单检索
    SEMANTIC = "semantic"                # 语义检索
    HYBRID = "hybrid"                    # 混合检索
    KEYWORD_BOOST = "keyword_boost"      # 关键词增强
    RECENCY_BOOST = "recency_boost"      # 时效性增强


@dataclass
class Document:
    """文档"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    content: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Document":
        return cls(
            id=data["id"],
            content=data["content"],
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data.get("created_at", datetime.utcnow().isoformat())),
            updated_at=datetime.fromisoformat(data.get("updated_at", datetime.utcnow().isoformat())),
        )


@dataclass
class Chunk:
    """文档块"""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    document_id: str = ""
    content: str = ""
    chunk_index: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "document_id": self.document_id,
            "content": self.content,
            "chunk_index": self.chunk_index,
            "metadata": self.metadata,
        }


@dataclass
class RetrievalResult:
    """检索结果"""
    chunk: Chunk
    score: float
    rerank_score: Optional[float] = None
    highlights: List[str] = field(default_factory=list)


@dataclass
class RAGContext:
    """RAG 上下文"""
    query: str
    retrieved_chunks: List[RetrievalResult] = field(default_factory=list)
    system_prompt: str = ""
    context_window: int = 4000
    max_chunks: int = 5

    def build_context(self) -> str:
        """构建上下文字符串"""
        if not self.retrieved_chunks:
            return ""

        chunks = self.retrieved_chunks[:self.max_chunks]
        parts = ["【参考资料】\n"]

        for i, result in enumerate(chunks, 1):
            chunk = result.chunk
            parts.append(f"--- 来源 {i} (相关性: {result.score:.2f}) ---")
            parts.append(chunk.content)
            parts.append("")

        return "\n".join(parts)

    def build_prompt(self, question: str) -> str:
        """构建完整提示词"""
        context = self.build_context()
        if context:
            return f"{context}\n\n【问题】\n{question}\n\n请根据以上参考资料回答问题。如果参考资料中没有相关信息，请说明。"
        return question


class ChunkingStrategy:
    """
    文档分块策略
    """

    @staticmethod
    def simple_chunk(
        text: str,
        chunk_size: int = 500,
        overlap: int = 50,
    ) -> List[str]:
        """简单分块（按字符数）"""
        chunks = []
        start = 0

        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end].strip()

            if chunk:
                chunks.append(chunk)

            start = end - overlap

        return chunks

    @staticmethod
    def semantic_chunk(
        text: str,
        separator: str = "\n\n",
        max_chunk_size: int = 500,
    ) -> List[str]:
        """语义分块（按段落）"""
        paragraphs = text.split(separator)
        chunks = []
        current_chunk = []

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            current_text = separator.join(current_chunk)
            if len(current_text) + len(para) > max_chunk_size and current_chunk:
                chunks.append(separator.join(current_chunk))
                # 保留最后一个段落作为下一个块的开头
                current_chunk = [current_chunk[-1], para] if len(current_chunk) > 1 else [para]
            else:
                current_chunk.append(para)

        if current_chunk:
            chunks.append(separator.join(current_chunk))

        return chunks

    @staticmethod
    def recursive_chunk(
        text: str,
        separators: List[str] = None,
        chunk_size: int = 500,
    ) -> List[str]:
        """递归分块"""
        if separators is None:
            separators = ["\n\n", "\n", "。", "！", "？", ". ", " "]

        def split_text(text: str, sep_idx: int) -> List[str]:
            if sep_idx >= len(separators):
                return [text] if len(text) <= chunk_size else simple_split(text, chunk_size)

            sep = separators[sep_idx]
            parts = text.split(sep)

            result = []
            current = []

            for part in parts:
                part = part.strip()
                if not part:
                    continue

                test = (sep.join(current) + sep + part if current else part)
                if len(test) <= chunk_size:
                    current.append(part)
                else:
                    if current:
                        result.append(sep.join(current))
                    current = [part]

            if current:
                result.append(sep.join(current))

            return result

        def simple_split(text: str, size: int) -> List[str]:
            return [text[i:i+size] for i in range(0, len(text), size)]

        return split_text(text, 0)


class EmbeddingFunction:
    """
    嵌入函数
    使用 LLM 生成文本嵌入
    """

    def __init__(self, llm_manager: "LLMManager"):
        self.llm = llm_manager
        self._embedding_cache: Dict[str, List[float]] = {}

    async def embed_text(self, text: str, use_cache: bool = True) -> List[float]:
        """生成文本嵌入"""
        # 简单缓存
        if use_cache and text in self._embedding_cache:
            return self._embedding_cache[text]

        # 使用 LLM 生成嵌入
        # 实际项目中应该使用专门的嵌入模型（如 OpenAI text-embedding-3）
        # 这里使用简化实现
        try:
            # 方法1: 使用 LLM 的内部表示
            response = await self.llm.chat([
                {"role": "user", "content": f"Generate a brief semantic embedding for: {text[:100]}"}
            ])
            # 简化处理 - 实际应该使用专门的嵌入 API
            embedding = self._simple_embedding(text)
        except Exception as e:
            logger.warning(f"Failed to generate embedding with LLM: {e}")
            embedding = self._simple_embedding(text)

        if use_cache:
            self._embedding_cache[text] = embedding

        return embedding

    def _simple_embedding(self, text: str) -> List[float]:
        """简单的基于哈希的嵌入（用于开发/测试）"""
        import hashlib
        # 使用文本哈希生成一个确定性的向量
        hash_digest = hashlib.sha256(text.encode()).digest()

        # 将哈希分成多个float
        import struct
        embedding = []
        for i in range(0, min(len(hash_digest), 48), 4):
            val = struct.unpack('f', hash_digest[i:i+4])[0]
            embedding.append(val)

        # 填充到标准维度
        while len(embedding) < 48:
            embedding.append(0.0)

        # L2 归一化
        import math
        norm = math.sqrt(sum(x*x for x in embedding))
        if norm > 0:
            embedding = [x/norm for x in embedding]

        return embedding

    def clear_cache(self) -> None:
        """清空缓存"""
        self._embedding_cache.clear()


class RAGEngine:
    """
    RAG 引擎
    检索增强生成核心引擎
    """

    def __init__(
        self,
        vector_store: Optional[BaseVectorStore] = None,
        embedding_function: Optional[EmbeddingFunction] = None,
        chunking_strategy: str = "semantic",
    ):
        self.vector_store = vector_store or get_store()
        self.embedding_function = embedding_function
        self.chunking_strategy = chunking_strategy

        self._collections: Dict[str, List[Chunk]] = {}  # collection_name -> chunks
        self._initialized = False

    async def initialize(self) -> None:
        """初始化 RAG 引擎"""
        if self._initialized:
            return

        await self.vector_store.init_collection()
        self._initialized = True
        logger.info("RAG engine initialized")

    async def add_document(
        self,
        document: Document,
        collection_name: str = "poi_knowledge",
        chunk_size: int = 500,
        chunk_overlap: int = 50,
    ) -> List[str]:
        """添加文档"""
        if not self.embedding_function:
            raise ValueError("Embedding function not configured")

        # 分块
        if self.chunking_strategy == "semantic":
            chunk_texts = ChunkingStrategy.semantic_chunk(document.content, max_chunk_size=chunk_size)
        else:
            chunk_texts = ChunkingStrategy.simple_chunk(document.content, chunk_size, chunk_overlap)

        chunk_ids = []

        for i, chunk_text in enumerate(chunk_texts):
            # 生成嵌入
            embedding = await self.embedding_function.embed_text(chunk_text)

            # 创建 Chunk
            chunk = Chunk(
                document_id=document.id,
                content=chunk_text,
                chunk_index=i,
                metadata={
                    **document.metadata,
                    "collection": collection_name,
                },
                embedding=embedding,
            )

            # 存储到向量数据库
            await self.vector_store.upsert(
                id=chunk.id,
                vector=embedding,
                payload={
                    **chunk.to_dict(),
                    "content": chunk.content,
                },
            )

            chunk_ids.append(chunk.id)

            # 缓存到内存
            if collection_name not in self._collections:
                self._collections[collection_name] = []
            self._collections[collection_name].append(chunk)

        logger.info(f"Added document {document.id} with {len(chunk_ids)} chunks")
        return chunk_ids

    async def retrieve(
        self,
        query: str,
        collection_name: str = "poi_knowledge",
        top_k: int = 5,
        strategy: RetrievalStrategy = RetrievalStrategy.SEMANTIC,
        filter_conditions: Optional[Dict[str, Any]] = None,
    ) -> List[RetrievalResult]:
        """检索相关文档"""
        if not self.embedding_function:
            raise ValueError("Embedding function not configured")

        # 生成查询嵌入
        query_embedding = await self.embedding_function.embed_text(query)

        # 构建过滤条件
        search_filter = {"collection": collection_name}
        if filter_conditions:
            search_filter.update(filter_conditions)

        # 向量搜索
        search_results = await self.vector_store.search(
            query_vector=query_embedding,
            top_k=top_k,
            filter_conditions=search_filter if filter_conditions else None,
        )

        # 转换为检索结果
        results = []
        for sr in search_results:
            # 查找对应的 Chunk
            chunk_data = sr.payload
            chunk = Chunk(
                id=sr.id,
                document_id=chunk_data.get("document_id", ""),
                content=chunk_data.get("content", ""),
                chunk_index=chunk_data.get("chunk_index", 0),
                metadata=chunk_data.get("metadata", {}),
            )

            results.append(RetrievalResult(
                chunk=chunk,
                score=sr.score,
            ))

        # 应用检索策略
        if strategy == RetrievalStrategy.RECENCY_BOOST:
            results = self._apply_recency_boost(results)

        return results

    def _apply_recency_boost(self, results: List[RetrievalResult]) -> List[RetrievalResult]:
        """应用时效性增强"""
        import math
        now = datetime.utcnow().timestamp()

        for result in results:
            # 检查 metadata 中的时间
            updated_at = result.chunk.metadata.get("updated_at")
            if isinstance(updated_at, str):
                try:
                    updated_ts = datetime.fromisoformat(updated_at).timestamp()
                    days_old = (now - updated_ts) / 86400
                    # 越新的文档 boost 越高
                    boost = math.exp(-days_old / 30) * 0.2
                    result.score += boost
                except Exception:
                    pass

        return sorted(results, key=lambda x: x.score, reverse=True)

    async def query(
        self,
        question: str,
        collection_name: str = "poi_knowledge",
        top_k: int = 5,
        llm: Optional["LLMManager"] = None,
    ) -> Dict[str, Any]:
        """RAG 查询"""
        # 1. 检索
        retrieved = await self.retrieve(
            query=question,
            collection_name=collection_name,
            top_k=top_k,
        )

        # 2. 构建上下文
        rag_context = RAGContext(
            query=question,
            retrieved_chunks=retrieved,
        )

        # 3. 如果提供了 LLM，生成答案
        answer = None
        if llm:
            prompt = rag_context.build_prompt(question)
            response = await llm.chat([{"role": "user", "content": prompt}])
            answer = response.content

        return {
            "question": question,
            "answer": answer,
            "sources": [
                {
                    "content": r.chunk.content,
                    "score": r.score,
                    "metadata": r.chunk.metadata,
                }
                for r in retrieved
            ],
            "context": rag_context.build_context(),
        }

    async def batch_add_documents(
        self,
        documents: List[Document],
        collection_name: str = "poi_knowledge",
        concurrency: int = 5,
    ) -> Dict[str, Any]:
        """批量添加文档"""
        total_chunks = 0
        successful = 0
        failed = 0

        semaphore = asyncio.Semaphore(concurrency)

        async def add_one(doc: Document):
            nonlocal total_chunks, successful, failed
            async with semaphore:
                try:
                    chunk_ids = await self.add_document(doc, collection_name)
                    total_chunks += len(chunk_ids)
                    successful += 1
                except Exception as e:
                    logger.error(f"Failed to add document {doc.id}: {e}")
                    failed += 1

        await asyncio.gather(*[add_one(doc) for doc in documents], return_exceptions=True)

        return {
            "total_documents": len(documents),
            "successful": successful,
            "failed": failed,
            "total_chunks": total_chunks,
        }


# ========== 景点知识库预置数据 ==========

POI_KNOWLEDGE_DATA = [
    {
        "name": "北京故宫",
        "category": "景区",
        "content": """北京故宫，又称紫禁城，是明清两代的皇家宫殿，位于北京中轴线的中心，是世界上现存规模最大、保存最为完整的木质结构古建筑之一。故宫收藏了大量珍贵文物，包括绘画、书法、陶瓷、玉器、金银器等180多万件。故宫分为外朝和内廷两部分，外朝是举行大典、召见群臣的场所，内廷是皇帝和后妃居住的地方。建议游览时间为3-4小时，最佳季节为春秋两季。门票需要在故宫博物院官网提前预约。""",
        "tags": ["历史", "文化", "博物馆", "世界遗产"],
    },
    {
        "name": "西湖",
        "category": "景区",
        "content": """西湖，位于浙江省杭州市西面，是中国大陆首批国家重点风景名胜区和中国十大风景名胜之一。西湖三面环山，面积约6.39平方千米，湖中有苏堤、白堤、杨公堤等堤坝，以及断桥、雷峰塔等景点。西湖十景包括苏堤春晓、断桥残雪、曲院风荷、花港观鱼、柳浪闻莺、三潭印月、平湖秋月、雷峰西照、南屏晚钟、双峰插云。免费开放，建议游览时间为半天到一天。""",
        "tags": ["自然风光", "历史文化", "免费"],
    },
    {
        "name": "张家界国家森林公园",
        "category": "景区",
        "content": """张家界国家森林公园位于湖南省张家界市，是中国第一个国家森林公园。主要景观包括金鞭溪、黄石寨、袁家界、天子山等。其中袁家界的哈利路亚山因电影《阿凡达》而闻名。张家界以独特的石英砂岩峰林地貌著称，是世界自然遗产、世界地质公园。建议游览时间2-3天，最佳季节为4-10月。门票为通票制，可在四天内多次进入。""",
        "tags": ["自然风光", "地质公园", "世界遗产"],
    },
]


async def initialize_poi_knowledge(rag_engine: RAGEngine) -> Dict[str, Any]:
    """初始化景点知识库"""
    documents = [
        Document(
            content=data["content"],
            metadata={
                "name": data["name"],
                "category": data["category"],
                "tags": data.get("tags", []),
            },
        )
        for data in POI_KNOWLEDGE_DATA
    ]

    result = await rag_engine.batch_add_documents(documents, "poi_knowledge")
    logger.info(f"Initialized POI knowledge base: {result}")
    return result


# ========== 全局 RAG 引擎实例 ==========

_rag_engine: Optional[RAGEngine] = None


def get_rag_engine() -> RAGEngine:
    """获取 RAG 引擎"""
    global _rag_engine
    if _rag_engine is None:
        _rag_engine = RAGEngine()
    return _rag_engine


async def init_rag_engine(llm_manager: Optional["LLMManager"] = None) -> RAGEngine:
    """初始化 RAG 引擎"""
    global _rag_engine

    store = get_store()
    embedding_fn = EmbeddingFunction(llm_manager) if llm_manager else None

    _rag_engine = RAGEngine(
        vector_store=store,
        embedding_function=embedding_fn,
    )

    await _rag_engine.initialize()

    # 初始化预置数据
    if llm_manager:
        await initialize_poi_knowledge(_rag_engine)

    return _rag_engine
