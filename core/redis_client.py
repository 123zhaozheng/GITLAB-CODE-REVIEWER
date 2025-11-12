"""
统一的 Redis 连接管理器
提供单例模式的 Redis 连接池，避免重复创建连接
"""
import logging
from typing import Optional
import redis.asyncio as redis
from config.settings import settings

logger = logging.getLogger(__name__)


class RedisConnectionManager:
    """
    Redis 连接管理器 - 单例模式

    提供统一的 Redis 连接池管理，确保整个应用共享同一个连接池
    """

    _instance: Optional['RedisConnectionManager'] = None
    _redis_client: Optional[redis.Redis] = None
    _is_connected: bool = False

    def __new__(cls):
        """单例模式：确保只创建一个实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化（仅在第一次创建时执行）"""
        # 避免重复初始化
        if hasattr(self, '_initialized'):
            return

        self._initialized = True
        self.redis_url = settings.redis_url
        logger.info(f"RedisConnectionManager initialized with URL: {self.redis_url}")

    async def connect(self) -> Optional[redis.Redis]:
        """
        连接到 Redis

        Returns:
            Redis 客户端实例，连接失败返回 None
        """
        if self._is_connected and self._redis_client:
            return self._redis_client

        if not self.redis_url:
            logger.warning("Redis URL not configured, Redis functionality disabled")
            return None

        try:
            self._redis_client = await redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                # 连接池配置
                max_connections=50,
                # 重试配置
                retry_on_timeout=True,
                health_check_interval=30
            )

            # 测试连接
            await self._redis_client.ping()
            self._is_connected = True
            logger.info("Successfully connected to Redis")
            return self._redis_client

        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self._redis_client = None
            self._is_connected = False
            return None

    async def get_client(self) -> Optional[redis.Redis]:
        """
        获取 Redis 客户端

        如果未连接，自动尝试连接

        Returns:
            Redis 客户端实例，连接失败返回 None
        """
        if not self._is_connected or not self._redis_client:
            return await self.connect()

        return self._redis_client

    async def close(self):
        """关闭 Redis 连接"""
        if self._redis_client:
            try:
                await self._redis_client.close()
                self._is_connected = False
                logger.info("Redis connection closed")
            except Exception as e:
                logger.warning(f"Error closing Redis connection: {e}")
            finally:
                self._redis_client = None

    async def health_check(self) -> bool:
        """
        健康检查

        Returns:
            Redis 是否可用
        """
        try:
            client = await self.get_client()
            if not client:
                return False

            await client.ping()
            return True
        except Exception as e:
            logger.error(f"Redis health check failed: {e}")
            self._is_connected = False
            return False

    @property
    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._is_connected

    async def reconnect(self):
        """重新连接"""
        logger.info("Attempting to reconnect to Redis...")
        await self.close()
        return await self.connect()


# 全局单例实例
_redis_manager: Optional[RedisConnectionManager] = None


def get_redis_manager() -> RedisConnectionManager:
    """
    获取全局 Redis 连接管理器实例

    Returns:
        RedisConnectionManager: Redis 连接管理器单例
    """
    global _redis_manager
    if _redis_manager is None:
        _redis_manager = RedisConnectionManager()
    return _redis_manager


async def get_redis_client() -> Optional[redis.Redis]:
    """
    获取 Redis 客户端（便捷函数）

    Returns:
        Redis 客户端实例，连接失败返回 None
    """
    manager = get_redis_manager()
    return await manager.get_client()


async def close_redis_connection():
    """关闭全局 Redis 连接（便捷函数）"""
    manager = get_redis_manager()
    await manager.close()


async def redis_health_check() -> bool:
    """Redis 健康检查（便捷函数）"""
    manager = get_redis_manager()
    return await manager.health_check()
