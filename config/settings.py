"""
应用配置模块
基于PR Agent的配置系统优化而来
"""
import os
from typing import Optional, List, Dict, Any
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseSettings):
    """应用配置类"""
    
    # 服务基本配置
    service_name: str = Field(default="gitlab-code-reviewer", env="SERVICE_NAME")
    service_version: str = Field(default="1.0.0", env="SERVICE_VERSION")
    debug: bool = Field(default=False, env="DEBUG")
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    
    # AI模型配置
    openai_api_key: str = Field(..., env="OPENAI_API_KEY")
    openai_api_base: Optional[str] = Field(default=None, env="OPENAI_API_BASE")
    openai_api_url: Optional[str] = Field(default=None, env="OPENAI_API_URL")  # 别名支持
    default_ai_model: str = Field(default="gpt-4", env="DEFAULT_AI_MODEL")
    fallback_ai_model: str = Field(default="gpt-3.5-turbo", env="FALLBACK_AI_MODEL")
    max_tokens_per_request: int = Field(default=32000, env="MAX_TOKENS_PER_REQUEST")
    
    # OpenAI兼容服务配置
    ai_provider: str = Field(default="openai", env="AI_PROVIDER")  # openai, azure, custom等
    
    # 数据库配置
    database_url: str = Field(default="sqlite:///./app.db", env="DATABASE_URL")

    # Redis 配置
    redis_url: str = Field(default="redis://localhost:6379/0", env="REDIS_URL")
    redis_task_ttl: int = Field(default=86400, env="REDIS_TASK_TTL")  # 任务过期时间（秒），默认24小时
    
    # 性能配置
    max_concurrent_reviews: int = Field(default=10, env="MAX_CONCURRENT_REVIEWS")
    review_timeout_seconds: int = Field(default=300, env="REVIEW_TIMEOUT_SECONDS")
    token_cache_ttl: int = Field(default=3600, env="TOKEN_CACHE_TTL")
    
    # GitLab配置
    default_gitlab_url: str = Field(default="https://gitlab.com", env="DEFAULT_GITLAB_URL")
    max_files_per_review: int = Field(default=50, env="MAX_FILES_PER_REVIEW")
    
    # 文件内容处理配置
    max_file_lines: int = Field(default=1000, env="MAX_FILE_LINES")
    enable_per_file_review: bool = Field(default=True, env="ENABLE_PER_FILE_REVIEW")
    max_concurrent_file_reviews: int = Field(default=5, env="MAX_CONCURRENT_FILE_REVIEWS")
    
    # 安全配置
    api_key_header: str = Field(default="X-API-Key", env="API_KEY_HEADER")
    rate_limit_per_minute: int = Field(default=60, env="RATE_LIMIT_PER_MINUTE")
    allowed_hosts: List[str] = Field(default=["*"])
    
    # 成本优化配置
    enable_cost_optimization: bool = Field(default=True, env="ENABLE_COST_OPTIMIZATION")
    max_cost_per_review: float = Field(default=0.50, env="MAX_COST_PER_REVIEW")
    smart_filtering: bool = Field(default=True, env="SMART_FILTERING")
    
    # 路径/文件忽略模式（支持通配符，基于fnmatch），用于排除无需审查的目录/文件
    # 可通过环境变量覆盖：IGNORE_PATH_PATTERNS（JSON数组或逗号分隔）
    ignore_path_patterns: List[str] = Field(default_factory=lambda: [
        # 版本/包管理与构建产物（支持任意层级）
        "node_modules/*", "*/node_modules/*",
        "dist/*", "*/dist/*",
        "build/*", "*/build/*",
        "target/*", "*/target/*",
        "out/*", "*/out/*",
        # 虚拟环境与缓存
        "venv/*", "*/venv/*",
        ".venv/*", "*/.venv/*",
        "__pycache__/*", "*/__pycache__/*",
        "site-packages/*", "*/site-packages/*",
        # VCS/IDE
        ".git/*", "*/.git/*",
        ".idea/*", "*/.idea/*",
        ".vscode/*", "*/.vscode/*",
        # 生成/覆盖率
        "coverage/*", "*/coverage/*", "coverage.*",
        # 压缩/二进制/日志临时等
        "*.min.js", "*.min.css", "*.lock", "*.log", "*.tmp", "*.cache",
        # 其他常见供应商目录
        "vendor/*", "*/vendor/*"
    ])
    
    # LiteLLM兼容配置 (用于向后兼容)
    litellm_model_config: Optional[Dict[str, Any]] = None
    
    # 结构化输出配置
    enable_structured_output: bool = Field(default=True, env="ENABLE_STRUCTURED_OUTPUT")
    force_structured_output: bool = Field(default=True, env="FORCE_STRUCTURED_OUTPUT")

    def __init__(self, **kwargs):
        """初始化设置，手动处理allowed_hosts环境变量"""
        # 从环境变量中读取ALLOWED_HOSTS
        allowed_hosts_env = os.getenv("ALLOWED_HOSTS")
        if allowed_hosts_env is not None:
            kwargs["allowed_hosts"] = self._parse_allowed_hosts(allowed_hosts_env)
        
        super().__init__(**kwargs)
    
    @staticmethod
    def _parse_allowed_hosts(value: str) -> List[str]:
        """解析allowed_hosts环境变量"""
        if not value or not value.strip():
            return ["127.0.0.1"]  # 默认值
        
        value = value.strip()
        
        # 如果看起来像JSON数组，尝试解析
        if value.startswith('[') and value.endswith(']'):
            try:
                import json
                result = json.loads(value)
                if isinstance(result, list):
                    return [str(item) for item in result]
            except json.JSONDecodeError:
                pass
        
        # 否则按逗号分割处理
        return [host.strip() for host in value.split(',') if host.strip()]
    
    @property
    def api_base_url(self) -> Optional[str]:
        """获取API基础URL，支持多种配置方式"""
        return self.openai_api_url or self.openai_api_base
    
    
    model_config = {
        "env_file": "../.env",
        "case_sensitive": False
    }

# 全局设置实例
settings = Settings()

# 审查类型配置
REVIEW_TYPES = {
    "full": {
        "name": "全面审查",
        "description": "完整的代码质量、安全、性能审查",
        "focus_areas": ["quality", "security", "performance", "maintainability"]
    },
    "security": {
        "name": "安全审查", 
        "description": "专注于安全漏洞和风险检测",
        "focus_areas": ["security", "vulnerabilities", "data_protection"]
    },
    "performance": {
        "name": "性能审查",
        "description": "专注于性能优化和效率提升",
        "focus_areas": ["performance", "optimization", "scalability"]
    },
    "quick": {
        "name": "快速审查",
        "description": "基础的代码质量检查",
        "focus_areas": ["basic_quality", "syntax", "conventions"]
    }
}

# AI模型成本配置 (每1K tokens)
MODEL_COSTS = {
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-3.5-turbo": {"input": 0.001, "output": 0.002},
    "claude-3-sonnet": {"input": 0.015, "output": 0.075},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125}
}

# 文件类型优先级 (用于智能过滤)
FILE_PRIORITY = {
    # 高优先级 - 核心业务逻辑
    ".py": 10, ".js": 10, ".ts": 10, ".java": 10, ".go": 10, ".rs": 10,
    ".cpp": 9, ".c": 9, ".cs": 9, ".php": 9, ".rb": 9,
    
    # 中优先级 - 配置和模板
    ".yaml": 7, ".yml": 7, ".json": 7, ".xml": 6, ".html": 6,
    ".css": 5, ".scss": 5, ".less": 5,
    
    # 低优先级 - 文档和资源
    ".md": 3, ".txt": 2, ".rst": 2,
    ".png": 1, ".jpg": 1, ".gif": 1, ".svg": 1,
    
    # 忽略的文件类型
    ".lock": 0, ".log": 0, ".tmp": 0, ".cache": 0
}