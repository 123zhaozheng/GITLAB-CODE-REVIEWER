"""
简化AI处理器模块
直接使用OpenAI API，避免LiteLLM的复杂性
"""
import asyncio
import json
import re
import time
from typing import Dict, List, Optional, Any
# import tiktoken  # 已移除，使用简单估算替代
import openai
import logging

from config.settings import settings, MODEL_COSTS, REVIEW_TYPES
from core.gitlab_client import FilePatchInfo

logger = logging.getLogger(__name__)

# JSON Schema定义 - 用于结构化输出
CODE_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "description": "问题类型"},
                    "filename": {"type": "string", "description": "文件名"},
                    "line_number": {"type": "integer", "description": "行号"},
                    "severity": {
                        "type": "string", 
                        "enum": ["high", "medium", "low"],
                        "description": "严重程度"
                    },
                    "description": {"type": "string", "description": "问题描述"},
                    "suggestion": {"type": "string", "description": "修复建议"}
                },
                "required": ["type", "filename", "severity", "description"]
            }
        },
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "description": "改进建议列表"
        },
        "overall_assessment": {
            "type": "string",
            "description": "整体评估"
        }
    },
    "required": ["findings", "suggestions", "overall_assessment"]
}

SECURITY_ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "is_vulnerability": {"type": "boolean", "description": "是否为安全漏洞"},
        "risk_level": {
            "type": "integer", 
            "minimum": 1, 
            "maximum": 10,
            "description": "风险级别(1-10)"
        },
        "description": {"type": "string", "description": "详细描述"},
        "fix_suggestion": {"type": "string", "description": "修复建议"}
    },
    "required": ["is_vulnerability", "risk_level", "description", "fix_suggestion"]
}

PERFORMANCE_ANALYSIS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "type": {"type": "string", "description": "性能问题类型"},
            "severity": {
                "type": "string",
                "enum": ["high", "medium", "low"],
                "description": "严重程度"
            },
            "description": {"type": "string", "description": "问题描述"},
            "optimization": {"type": "string", "description": "优化建议"}
        },
        "required": ["type", "severity", "description", "optimization"]
    }
}

class TokenManager:
    """Token管理器 - 使用简单估算，不依赖tiktoken"""
    
    # 不同模型的字符-token比例 (字符数/token数)
    CHAR_TOKEN_RATIOS = {
        'gpt-4': 3.8,
        'gpt-4-turbo': 3.8, 
        'gpt-3.5-turbo': 3.8,
        'claude': 4.0,
        'llama': 3.5,      # Llama 系列
        'qwen': 4.2,       # 通义千问 (中文友好)
        'chatglm': 4.2,    # ChatGLM (中文友好)
        'deepseek': 3.8,   # DeepSeek
        'default': 4.0     # 默认比例
    }
    
    def __init__(self, model: str = None):
        self.model = model or settings.default_ai_model
        self.ratio = self._get_ratio_for_model(self.model)
        logger.info(f"TokenManager initialized for model '{self.model}' with ratio {self.ratio}")
    
    def _get_ratio_for_model(self, model: str) -> float:
        """根据模型名获取字符-token比例"""
        model_lower = model.lower()
        
        # 检查模型名中是否包含已知模型类型
        for model_type, ratio in self.CHAR_TOKEN_RATIOS.items():
            if model_type in model_lower:
                return ratio
        
        # 如果是中文相关的模型，使用更高的比例
        chinese_indicators = ['chinese', 'zh', 'cn', 'baichuan', 'internlm']
        if any(indicator in model_lower for indicator in chinese_indicators):
            return 4.5
            
        return self.CHAR_TOKEN_RATIOS['default']
    
    def count_tokens(self, text: str) -> int:
        """计算文本token数量 - 基于字符数的简单估算"""
        if not text:
            return 0
        
        char_count = len(text)
        
        # 检测文本类型并调整比例
        adjusted_ratio = self._adjust_ratio_for_content(text, self.ratio)
        
        # 计算token数量
        estimated_tokens = max(1, int(char_count / adjusted_ratio))
        
        return estimated_tokens
    
    def _adjust_ratio_for_content(self, text: str, base_ratio: float) -> float:
        """根据文本内容调整字符-token比例"""
        # 检测是否是代码文本
        code_patterns = [
            r'def\s+\w+\s*\(',      # Python函数定义
            r'class\s+\w+',         # 类定义
            r'function\s*\(',       # JavaScript函数
            r'import\s+\w+',        # 导入语句
            r'from\s+\w+\s+import', # Python导入
            r'{\s*$',               # 代码块开始
            r'}\s*$',               # 代码块结束
            r'if\s*\(',             # 条件语句
            r'for\s*\(',            # 循环语句
            r'while\s*\(',          # while循环
        ]
        
        is_code = any(re.search(pattern, text, re.MULTILINE) for pattern in code_patterns)
        
        if is_code:
            # 代码文本通常token密度更高（更多符号和关键字）
            return base_ratio * 0.75
        
        # 检测是否包含大量中文
        chinese_char_count = len(re.findall(r'[\u4e00-\u9fff]', text))
        chinese_ratio = chinese_char_count / len(text) if text else 0
        
        if chinese_ratio > 0.3:  # 超过30%中文字符
            # 中文字符通常需要更多token
            return base_ratio * 1.2
        
        return base_ratio
    
    def estimate_cost(self, input_tokens: int, output_tokens: int = 1000) -> float:
        """估算API调用成本"""
        costs = MODEL_COSTS.get(self.model, {"input": 0.01, "output": 0.03})
        return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1000

class SimpleOpenAIClient:
    """简化的OpenAI客户端 - 最小化初始化参数避免版本兼容问题"""
    
    def __init__(self, api_key: str, base_url: Optional[str] = None):
        if not api_key:
            raise ValueError("API key is required")
            
        try:
            # 使用最基本的参数进行初始化，避免版本兼容问题
            # 明确只传递支持的参数，避免传递不兼容的参数如proxies
            client_kwargs = {
                "api_key": api_key,
                "timeout": 60.0,  # 明确设置超时
            }
            
            if base_url:
                client_kwargs["base_url"] = base_url
                logger.info(f"OpenAI client initializing with custom base URL: {base_url}")
            
            self.client = openai.AsyncOpenAI(**client_kwargs)
            logger.info("OpenAI client initialized successfully")
                
        except Exception as e:
            logger.error(f"Failed to initialize OpenAI client: {e}")
            # 如果base_url导致问题，尝试仅使用API key
            if base_url:
                try:
                    logger.warning("Retrying without custom base URL")
                    self.client = openai.AsyncOpenAI(
                        api_key=api_key,
                        timeout=60.0
                    )
                    logger.info("OpenAI client initialized with default settings as fallback")
                except Exception as e2:
                    raise RuntimeError(f"Cannot initialize OpenAI client: {e2}")
            else:
                raise RuntimeError(f"Cannot initialize OpenAI client: {e}")
    
    async def chat_completion(self, messages: List[Dict], model: str, 
                            response_format: Optional[Dict] = None, **kwargs) -> str:
        """发送聊天完成请求 - 带详细日志记录"""
        import time
        
        # 记录请求开始时间
        start_time = time.time()
        
        # 计算输入token数量
        input_text = "\n".join([msg.get('content', '') for msg in messages])
        input_tokens = len(input_text) // 4  # 简单估算
        
        # 记录请求参数详情
        logger.info("=" * 60)
        logger.info("🚀 OpenAI API 调用开始")
        logger.info("=" * 60)
        logger.info(f"📋 请求参数:")
        logger.info(f"  - 模型: {model}")
        logger.info(f"  - 消息数量: {len(messages)}")
        logger.info(f"  - 估算输入tokens: {input_tokens}")
        logger.info(f"  - 额外参数: {kwargs}")
        
        # 记录消息内容（可选择性记录）
        logger.info(f"💬 消息内容:")
        for i, msg in enumerate(messages):
            role = msg.get('role', 'unknown')
            content = msg.get('content', '')[:200] + '...' if len(msg.get('content', '')) > 200 else msg.get('content', '')
            logger.info(f"  [{i+1}] {role}: {content}")
        
        try:
            # 发送API请求
            logger.info("⏳ 正在调用OpenAI API...")
            
            # 构建API调用参数
            api_params = {
                "model": model,
                "messages": messages,
                **kwargs
            }
            
            # 如果支持结构化输出，添加response_format
            if response_format and self._supports_structured_output(model):
                api_params["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": "code_review_response",
                        "schema": response_format
                    }
                }
                logger.info("🎯 使用结构化输出模式")
            elif response_format:
                logger.info("📝 模型不支持结构化输出，使用提示词约束")
            
            response = await self.client.chat.completions.create(**api_params)
            
            # 计算响应时间
            end_time = time.time()
            response_time = end_time - start_time
            
            # 获取响应内容
            response_content = response.choices[0].message.content
            response_tokens = len(response_content) // 4  # 简单估算
            
            # 记录响应详情
            logger.info("=" * 60)
            logger.info("✅ OpenAI API 调用成功")
            logger.info("=" * 60)
            logger.info(f"⏱️  响应时间: {response_time:.2f}秒")
            logger.info(f"📊 Token使用情况:")
            
            # 尝试获取实际token使用量（如果API返回了）
            if hasattr(response, 'usage') and response.usage:
                logger.info(f"  - 输入tokens: {response.usage.prompt_tokens}")
                logger.info(f"  - 输出tokens: {response.usage.completion_tokens}")
                logger.info(f"  - 总tokens: {response.usage.total_tokens}")
            else:
                logger.info(f"  - 估算输入tokens: {input_tokens}")
                logger.info(f"  - 估算输出tokens: {response_tokens}")
                
            logger.info(f"🎯 响应内容:")
            # 记录完整响应内容，但如果太长则截取
            if len(response_content) > 2000:
                logger.info(f"  {response_content[:800]}...")
                logger.info(f"  ... [中间省略 {len(response_content)-1600} 个字符] ...")
                logger.info(f"  ...{response_content[-800:]}")
            else:
                logger.info(f"  {response_content}")
            
            # 为调试目的，记录响应的前1000个字符到DEBUG级别
            logger.debug(f"Full response preview: {response_content[:1000]}")
            
            logger.info("=" * 60)
            
            return response_content
            
        except Exception as e:
            end_time = time.time()
            response_time = end_time - start_time
            
            logger.error("=" * 60)
            logger.error("❌ OpenAI API 调用失败")
            logger.error("=" * 60)
            logger.error(f"⏱️  失败时间: {response_time:.2f}秒")
            logger.error(f"💥 错误详情: {str(e)}")
            logger.error(f"🔍 错误类型: {type(e).__name__}")
            logger.error("=" * 60)
            raise
    
    async def close(self):
        """安全关闭客户端，避免状态错误"""
        try:
            if hasattr(self, 'client') and self.client:
                # 检查客户端是否有close方法且可以安全调用
                if hasattr(self.client, 'close'):
                    await self.client.close()
                    logger.info("OpenAI client closed successfully")
        except Exception as e:
            # 忽略关闭时的错误，避免影响主要功能
            logger.warning(f"Error closing OpenAI client (ignored): {e}")
    
    def __del__(self):
        """析构函数，确保资源清理"""
        try:
            if hasattr(self, 'client') and self.client:
                # 在同步环境中无法调用异步close，只记录日志
                logger.debug("OpenAI client cleanup in destructor")
        except:
            pass  # 忽略析构函数中的所有错误
    
    def _supports_structured_output(self, model: str) -> bool:
        """检查模型是否支持结构化输出"""
        # 首先检查全局配置
        if not settings.enable_structured_output:
            return False
        
        # 如果强制启用，直接返回True
        if settings.force_structured_output:
            return True
        
        # OpenAI GPT-4 和 GPT-3.5-turbo 的较新版本支持结构化输出
        # DeepSeek 和其他现代模型也支持结构化输出
        supported_models = [
            "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", 
            "gpt-4", "gpt-3.5-turbo",
            "deepseek", "claude", "gemini"  # 添加更多模型支持
        ]
        
        # 检查是否为支持的模型
        for supported in supported_models:
            if model.startswith(supported):
                return True
        
        # 对于自定义模型，根据配置决定
        return settings.force_structured_output

class SimpleAIProcessor:
    """简化AI代码分析处理器"""
    
    def __init__(self, model: str = None):
        self.model = model or settings.default_ai_model
        self.fallback_model = settings.fallback_ai_model
        self.token_manager = TokenManager(self.model)
        
        # 延迟初始化OpenAI客户端，避免启动时的依赖问题
        self._client = None
        
        logger.info(f"SimpleAIProcessor initialized with model: {self.model}")
    
    @property
    def client(self):
        """延迟初始化OpenAI客户端，失败时返回None以启用基础模式"""
        if self._client is None:
            try:
                self._client = SimpleOpenAIClient(
                    api_key=settings.openai_api_key,
                    base_url=settings.api_base_url
                )
                logger.info("OpenAI client initialized successfully")
            except Exception as e:
                logger.error(f"Failed to initialize OpenAI client: {e}")
                logger.warning("AI client unavailable, will use basic analysis mode only")
                # 返回False表示客户端不可用，而不是抛出异常
                return False
        return self._client
    
    def _is_ai_available(self) -> bool:
        """检查AI客户端是否可用"""
        return self.client is not False
    
    async def analyze_merge_request(self, diff_files: List[FilePatchInfo],
                                  review_type: str, mr_info: Dict,
                                  historical_issues: Optional[Dict[str, List[Dict]]] = None) -> Dict[str, Any]:
        """分析MR的主入口函数"""
        import time

        # 记录分析开始
        start_time = time.time()
        logger.info("🔍" + "=" * 80)
        logger.info("🔍 开始代码审查分析")
        logger.info("🔍" + "=" * 80)
        logger.info(f"📋 审查参数:")
        logger.info(f"  - 审查类型: {review_type}")
        logger.info(f"  - 文件数量: {len(diff_files)}")
        logger.info(f"  - AI模型: {self.model}")
        logger.info(f"  - AI客户端可用: {self._is_ai_available()}")
        logger.info(f"  - 逐文件审查: {settings.enable_per_file_review}")
        logger.info(f"  - 历史问题: {len(historical_issues or {})} 个文件有历史记录")

        logger.info(f"📁 变更文件列表:")
        for i, file_patch in enumerate(diff_files):
            has_history = file_patch.filename in (historical_issues or {})
            history_mark = "📌 (有历史问题)" if has_history else ""
            logger.info(f"  [{i+1}] {file_patch.filename} ({file_patch.edit_type}) {history_mark}")

        logger.info(f"🎯 MR信息:")
        logger.info(f"  - 标题: {mr_info.get('title', '未知')}")
        logger.info(f"  - 源分支: {mr_info.get('source_branch', '未知')}")
        logger.info(f"  - 目标分支: {mr_info.get('target_branch', '未知')}")

        try:
            logger.info(f"⚡ 开始执行 {review_type} 类型审查...")

            # 根据审查类型和配置选择分析策略
            if settings.enable_per_file_review and len(diff_files) > 1:
                result = await self._per_file_analysis(diff_files, review_type, mr_info, historical_issues)
            elif review_type == "security":
                result = await self._security_focused_analysis(diff_files, mr_info)
            elif review_type == "performance":
                result = await self._performance_focused_analysis(diff_files, mr_info)
            elif review_type == "quick":
                result = await self._quick_analysis(diff_files, mr_info)
            else:  # full analysis
                result = await self._comprehensive_analysis(diff_files, mr_info)

            # 估算成本
            cost_estimate = self._estimate_analysis_cost(diff_files)
            result["cost_estimate"] = cost_estimate

            # 记录分析完成
            end_time = time.time()
            analysis_time = end_time - start_time

            logger.info("✅" + "=" * 80)
            logger.info("✅ 代码审查分析完成")
            logger.info("✅" + "=" * 80)
            logger.info(f"⏱️  总分析时间: {analysis_time:.2f}秒")
            logger.info(f"📊 分析结果概览:")
            logger.info(f"  - 审查类型: {result.get('type', 'unknown')}")
            logger.info(f"  - 评分: {result.get('score', 0):.1f}/10.0")
            logger.info(f"  - 发现问题数: {len(result.get('findings', []))}")
            logger.info(f"  - 建议数: {len(result.get('suggestions', []))}")
            logger.info(f"  - 推荐数: {len(result.get('recommendations', []))}")
            logger.info(f"  - 成本估算: ${cost_estimate:.4f}")

            if result.get('findings'):
                logger.info(f"🔍 发现的主要问题:")
                for i, finding in enumerate(result['findings'][:3]):  # 只显示前3个
                    logger.info(f"  [{i+1}] {finding.get('filename', 'N/A')}: {finding.get('message', finding.get('description', 'N/A'))}")
                if len(result['findings']) > 3:
                    logger.info(f"  ... 还有 {len(result['findings']) - 3} 个问题")

            logger.info(f"📝 总结: {result.get('summary', '无总结')}")
            logger.info("✅" + "=" * 80)

            logger.info(f"Analysis completed with score: {result['score']}")
            return result

        except Exception as e:
            end_time = time.time()
            analysis_time = end_time - start_time

            logger.error("❌" + "=" * 80)
            logger.error("❌ 代码审查分析失败")
            logger.error("❌" + "=" * 80)
            logger.error(f"⏱️  失败时间: {analysis_time:.2f}秒")
            logger.error(f"💥 错误详情: {str(e)}")
            logger.error(f"🔍 错误类型: {type(e).__name__}")
            logger.error("❌" + "=" * 80)
            logger.error(f"AI analysis failed: {e}")
            raise
        finally:
            # 确保客户端正确清理
            await self._cleanup_client()
    
    async def _cleanup_client(self):
        """清理AI客户端资源"""
        try:
            if self._client and self._client is not False:
                await self._client.close()
                logger.debug("AI client resources cleaned up")
        except Exception as e:
            # 忽略清理错误，避免影响主要流程
            logger.debug(f"Client cleanup error (ignored): {e}")
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self._cleanup_client()
    
    async def _per_file_analysis(self, diff_files: List[FilePatchInfo],
                               review_type: str, mr_info: Dict,
                               historical_issues: Optional[Dict[str, List[Dict]]] = None) -> Dict[str, Any]:
        """逐文件并行分析 - 新的核心方法"""
        logger.info(f"🚀 启动逐文件并行分析，文件数量: {len(diff_files)}")
        logger.info(f"🔧 最大并发数: {settings.max_concurrent_file_reviews}")

        # 使用信号量控制并发数
        semaphore = asyncio.Semaphore(settings.max_concurrent_file_reviews)

        async def analyze_single_file(file_patch: FilePatchInfo) -> Dict[str, Any]:
            async with semaphore:
                # 获取该文件的历史问题
                file_historical_issues = (historical_issues or {}).get(file_patch.filename, [])
                return await self._analyze_single_file(file_patch, review_type, file_historical_issues)

        # 并行处理所有文件
        start_time = time.time()
        tasks = [analyze_single_file(file_patch) for file_patch in diff_files]
        file_results = await asyncio.gather(*tasks, return_exceptions=True)

        parallel_time = time.time() - start_time
        logger.info(f"⚡ 并行文件分析完成，耗时: {parallel_time:.2f}秒")

        # 聚合结果
        all_findings = []
        all_suggestions = []
        failed_files = []

        for i, result in enumerate(file_results):
            if isinstance(result, Exception):
                logger.error(f"文件 {diff_files[i].filename} 分析失败: {result}")
                failed_files.append(diff_files[i].filename)
                continue

            all_findings.extend(result.get("findings", []))
            all_suggestions.extend(result.get("suggestions", []))

        # 生成全局总结
        global_summary = await self._generate_global_summary(
            all_findings, all_suggestions, mr_info, failed_files
        )

        # 计算整体评分
        score = self._calculate_overall_score(all_findings, diff_files, failed_files)

        logger.info(f"📊 逐文件分析完成:")
        logger.info(f"  - 成功分析文件: {len(diff_files) - len(failed_files)}")
        logger.info(f"  - 失败文件: {len(failed_files)}")
        logger.info(f"  - 总问题数: {len(all_findings)}")
        logger.info(f"  - 总建议数: {len(all_suggestions)}")

        return {
            "type": f"{review_type}_per_file",
            "findings": all_findings[:30],  # 限制数量防止结果过大
            "suggestions": all_suggestions[:20],
            "recommendations": self._generate_recommendations(all_findings),
            "score": score,
            "summary": global_summary,
            "failed_files": failed_files,
            "parallel_analysis_time": parallel_time
        }
    
    async def _analyze_single_file(self, file_patch: FilePatchInfo,
                                 review_type: str,
                                 historical_issues: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """分析单个文件"""
        import time

        start_time = time.time()
        logger.info(f"📄 开始分析文件: {file_patch.filename}")

        if historical_issues:
            logger.info(f"  📌 发现 {len(historical_issues)} 个历史问题需要关注")

        try:
            # 基础问题检测（本地，快速）
            # basic_issues = self._detect_basic_issues(file_patch)

            # 构建完整文件内容用于AI分析
            full_file_content = self._prepare_file_content_for_analysis(file_patch)

            # AI深度分析
            ai_findings = []
            ai_suggestions = []

            if self._is_ai_available() and full_file_content:
                try:
                    ai_result = await self._ai_single_file_analysis(
                        file_patch, full_file_content, review_type, historical_issues
                    )
                    ai_findings = ai_result.get("findings", [])
                    ai_suggestions = ai_result.get("suggestions", [])
                except Exception as e:
                    logger.warning(f"文件 {file_patch.filename} 的AI分析失败: {e}")

            # 合并结果
            #all_findings = basic_issues + ai_findings
            all_findings = ai_findings

            end_time = time.time()
            analysis_time = end_time - start_time

            logger.info(f"✅ 文件 {file_patch.filename} 分析完成 ({analysis_time:.2f}秒)")
            logger.info(f"    - 基础问题: {len(basic_issues)}个")
            logger.info(f"    - AI发现问题: {len(ai_findings)}个")
            logger.info(f"    - AI建议: {len(ai_suggestions)}个")

            return {
                "filename": file_patch.filename,
                "findings": all_findings,
                "suggestions": ai_suggestions,
                "analysis_time": analysis_time
            }

        except Exception as e:
            end_time = time.time()
            logger.error(f"❌ 文件 {file_patch.filename} 分析失败: {e} ({end_time - start_time:.2f}秒)")
            raise
    
    def _prepare_file_content_for_analysis(self, file_patch: FilePatchInfo) -> str:
        """准备用于AI分析的文件内容（包含完整内容和diff）"""
        logger.debug(f"准备文件内容: {file_patch.filename}")
        
        # 获取文件内容（优先使用new_content，如果为空则使用old_content）
        full_content = file_patch.new_content or file_patch.old_content
        
        if not full_content:
            logger.debug(f"文件 {file_patch.filename} 无完整内容，仅使用diff")
            return file_patch.patch
        
        # 按行截断文件内容
        lines = full_content.splitlines()
        if len(lines) > settings.max_file_lines:
            logger.info(f"文件 {file_patch.filename} 行数过多({len(lines)})，截断至{settings.max_file_lines}行")
            truncated_content = '\n'.join(lines[:settings.max_file_lines])
            truncated_content += f"\n... [文件被截断，原始行数: {len(lines)}]"
        else:
            truncated_content = full_content
        
        # 组合完整内容和变更信息
        content_for_analysis = f"""
文件: {file_patch.filename}
变更类型: {file_patch.edit_type}

完整文件内容:
```
{truncated_content}
```

变更详情(diff):
```diff
{file_patch.patch}
```
"""
        return content_for_analysis.strip()
    
    async def _ai_single_file_analysis(self, file_patch: FilePatchInfo,
                                     full_content: str, review_type: str,
                                     historical_issues: Optional[List[Dict]] = None) -> Dict[str, Any]:
        """对单个文件进行AI分析"""
        if not self._is_ai_available():
            return {"findings": [], "suggestions": []}

        # 根据审查类型构建不同的提示词
        focus_areas = REVIEW_TYPES.get(review_type, {}).get("focus_areas", ["quality"])
        focus_description = ", ".join(focus_areas)

        # 构建历史问题的提示 - 强制关注历史问题
        historical_context = ""

        if historical_issues:
            historical_context = "\n\n🔴 **重要：本次审查为历史问题追踪模式**\n\n"
            historical_context += "⚠️ **上一次审查发现的问题清单**：\n\n"

            for i, issue in enumerate(historical_issues, 1):
                historical_context += f"{i}. [{issue.get('severity', 'low').upper()}] {issue.get('type', 'unknown')}\n"
                historical_context += f"   描述: {issue.get('description', 'N/A')}\n"
                if issue.get('line_number'):
                    historical_context += f"   位置: 第{issue.get('line_number')}行附近\n"
                historical_context += f"   修复建议: {issue.get('suggestion', 'N/A')}\n\n"

            historical_context += "\n🎯 **强制审查要求（极其重要）**：\n"
            historical_context += "1. **仅关注历史问题**：只检查上述历史问题相关的代码区域是否有修改\n"
            historical_context += "2. **检查修复状态**：对每个历史问题，判断本次 diff 中是否已修复\n"
            historical_context += "3. **修复即清除**：如果历史问题已被正确修复且没有引入新的严重问题，返回空 findings []\n"
            historical_context += "4. **问题持续**：如果历史问题仍然存在（代码未改或改得不对），在 findings 中报告\n"
            historical_context += "5. **新问题严格限制**：除非是严重影响生产的新问题（如安全漏洞、崩溃风险），否则不要报告新问题\n"
            historical_context += "6. **不要报告其他代码**：不要审查与历史问题无关的代码区域\n\n"
            historical_context += "💡 **理想结果**：如果开发者正确修复了所有历史问题，你应该返回 findings: []\n\n"

        base_prompt = f"""
请专门分析以下文件的代码变更。

{full_content}
{historical_context}

{'🔴 **审查模式：历史问题追踪模式**' if historical_issues else '📋 **审查模式：常规代码审查**'}

{'**审查要求（历史问题模式）**：' if historical_issues else '**分析要求**：'}
{'''
1. **只看历史问题区域**：仅检查上述历史问题所在的代码行及其周边代码在本次 diff 中的修改情况
2. **判断修复状态**：
   - 如果问题已修复且没引入新的严重bug → findings 返回空数组 []
   - 如果问题未修复或修复不当 → findings 中报告该历史问题
   - 如果引入了严重的新问题（如安全漏洞）→ findings 中报告新问题
3. **严格限制新问题**：不要审查与历史问题无关的代码，不要报告小问题或建议性问题
4. **目标**：帮助开发者确认历史问题是否已修复，而不是发现新问题
''' if historical_issues else '''
1. **避免重复发现**：对于同一个根本问题，合并到一个 finding
2. **合并相关问题**：同一代码行的多个问题整合为一个描述
3. **聚焦关键问题**：只报告对代码功能和质量有重大影响的问题（0-3个）
4. **只审查 diff**：只关注 diff 部分的变更，不要审查整个文件内容
5. **无伤大雅的问题不报告**：代码风格、注释建议等小问题不要报告
'''}

注意：这是单文件分析。{' ⚠️ 本次是历史问题追踪，如果历史问题都已修复，请返回空的 findings: []' if historical_issues else ''}
"""

        # 如果不支持结构化输出，添加JSON格式说明
        if not self.client._supports_structured_output(self.model):
            prompt = base_prompt + """

⚠️ 重要：请严格按照以下JSON格式回复，不要添加任何其他文本、解释或markdown标记：

{
    "findings": [
        {
            "type": "问题类型",
            "line_number": 行号,
            "severity": "high/medium/low",
            "description": "完整的问题描述（如果同一行有多个相关问题，请合并描述）",
            "suggestion": "综合的修复建议"
        }
    ],
    "suggestions": ["改进建议1", "改进建议2"]
}

格式要求：
1. 输出必须是有效的JSON格式
2. 不要用```json或其他代码块包装
3. 不要添加任何解释文字
4. 确保所有字符串都用双引号包围
5. 确保同一行或相关的问题只生成一个finding对象
"""
        else:
            prompt = base_prompt

        try:
            response = await self.client.chat_completion(
                messages=[
                    {"role": "system", "content": "你是一个专业的代码审查专家，专注于单文件代码分析。"},
                    {"role": "user", "content": prompt}
                ],
                model=self.model,
                temperature=0.2,
                max_tokens=2000,
                response_format={
                    "type": "object",
                    "properties": {
                        "findings": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "type": {"type": "string"},
                                    "line_number": {"type": "integer"},
                                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                                    "description": {"type": "string"},
                                    "suggestion": {"type": "string"}
                                },
                                "required": ["type", "severity", "description"]
                            }
                        },
                        "suggestions": {
                            "type": "array",
                            "items": {"type": "string"}
                        }
                    },
                    "required": ["findings", "suggestions"]
                }
            )

            # 解析响应
            cleaned_response = self._extract_json_from_response(response)

            try:
                result = json.loads(cleaned_response)
                logger.debug("Successfully parsed JSON response")
            except json.JSONDecodeError as e:
                logger.error(f"JSON解析失败: {e}")
                logger.error(f"尝试解析的JSON: {cleaned_response[:500]}...")

                # 尝试使用更激进的修复方法
                try:
                    fixed_json = self._aggressive_json_fix(cleaned_response)
                    result = json.loads(fixed_json)
                    logger.info("使用激进修复方法成功解析JSON")
                except Exception as e2:
                    logger.error(f"激进修复也失败: {e2}")
                    # 返回默认结构
                    return {
                        "findings": [],
                        "suggestions": [f"AI分析失败，JSON解析错误: {str(e)[:100]}"]
                    }

            # 验证并修复结果结构
            result = self._validate_and_fix_result(result)

            # 为每个finding添加filename
            for finding in result.get("findings", []):
                finding["filename"] = file_patch.filename

            return result

        except Exception as e:
            logger.error(f"AI单文件分析失败: {e}")
            return {"findings": [], "suggestions": []}
    
    async def _generate_global_summary(self, all_findings: List[Dict], 
                                     all_suggestions: List[str], mr_info: Dict,
                                     failed_files: List[str]) -> str:
        """生成全局分析总结"""
        if not self._is_ai_available():
            high_issues = len([f for f in all_findings if f.get("severity") == "high"])
            medium_issues = len([f for f in all_findings if f.get("severity") == "medium"])
            return f"逐文件分析完成，发现{high_issues}个高风险问题，{medium_issues}个中等风险问题。"
        
        # 统计信息
        high_issues = len([f for f in all_findings if f.get("severity") == "high"])
        medium_issues = len([f for f in all_findings if f.get("severity") == "medium"])
        low_issues = len([f for f in all_findings if f.get("severity") == "low"])
        
        # 问题分类统计
        issue_types = {}
        for finding in all_findings:
            issue_type = finding.get("type", "unknown")
            issue_types[issue_type] = issue_types.get(issue_type, 0) + 1
        
        top_issues = sorted(issue_types.items(), key=lambda x: x[1], reverse=True)[:5]
        
        prompt = f"""
请基于以下逐文件代码审查结果，生成一个全局总结：

MR信息：
- 标题：{mr_info.get('title', '未知')}
- 源分支：{mr_info.get('source_branch', '未知')}
- 目标分支：{mr_info.get('target_branch', '未知')}

分析统计：
- 高风险问题：{high_issues}个
- 中等风险问题：{medium_issues}个
- 低风险问题：{low_issues}个
- 分析失败文件：{len(failed_files)}个

主要问题类型：
{chr(10).join([f"- {issue_type}: {count}个" for issue_type, count in top_issues])}

改进建议数量：{len(all_suggestions)}个

请生成一个简洁的总结，评估整体代码质量和主要改进方向。
"""
        
        try:
            response = await self.client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.3,
                max_tokens=300
            )
            return response.strip()
        except Exception as e:
            logger.error(f"生成全局总结失败: {e}")
            return f"逐文件并行分析完成，总共发现{len(all_findings)}个问题，{len(all_suggestions)}个建议。"
    
    def _calculate_overall_score(self, all_findings: List[Dict], 
                               diff_files: List[FilePatchInfo], 
                               failed_files: List[str]) -> float:
        """计算整体评分"""
        base_score = 8.0
        
        # 根据问题严重程度扣分
        for finding in all_findings:
            severity = finding.get("severity", "low")
            if severity == "high":
                base_score -= 1.0
            elif severity == "medium":
                base_score -= 0.5
            else:
                base_score -= 0.2
        
        # 根据失败文件扣分
        if failed_files:
            failure_penalty = len(failed_files) * 0.5
            base_score -= failure_penalty
            logger.info(f"由于{len(failed_files)}个文件分析失败，扣分{failure_penalty}")
        
        # 根据文件数量调整
        if len(diff_files) > 10:
            base_score -= 0.3
        
        return max(base_score, 2.0)  # 最低2分
    
    async def _comprehensive_analysis(self, diff_files: List[FilePatchInfo], 
                                    mr_info: Dict) -> Dict[str, Any]:
        """全面分析"""
        all_findings = []
        all_suggestions = []
        
        # 基础问题检测
        for file_patch in diff_files:
            basic_issues = self._detect_basic_issues(file_patch)
            all_findings.extend(basic_issues)
        
        # AI深度分析
        try:
            ai_analysis = await self._ai_comprehensive_analysis(diff_files, mr_info)
            all_findings.extend(ai_analysis.get("findings", []))
            all_suggestions.extend(ai_analysis.get("suggestions", []))
        except Exception as e:
            logger.warning(f"AI analysis failed, using basic analysis only: {e}")
        
        # 计算综合评分
        score = self._calculate_comprehensive_score(all_findings, diff_files)
        
        return {
            "type": "comprehensive",
            "findings": all_findings[:20],  # 限制数量
            "suggestions": all_suggestions[:10],
            "recommendations": self._generate_recommendations(all_findings),
            "score": score,
            "summary": self._generate_summary(all_findings, score, len(diff_files))
        }
    
    async def _security_focused_analysis(self, diff_files: List[FilePatchInfo], 
                                       mr_info: Dict) -> Dict[str, Any]:
        """安全专项分析"""
        security_issues = []
        
        for file_patch in diff_files:
            # 检测常见安全问题
            issues = self._detect_security_issues(file_patch)
            security_issues.extend(issues)
            
            # 对每个潜在问题进行AI深度分析
            for issue in issues:
                try:
                    # 从描述中提取代码行（如果需要）
                    code_line = issue.get("description", "").split("代码：")[-1] if "代码：" in issue.get("description", "") else ""
                    ai_result = await self._ai_security_analysis(
                        file_patch.filename, 
                        issue["line_number"], 
                        code_line,
                        issue["category"]
                    )
                    if ai_result["is_vulnerability"]:
                        security_issues.append(ai_result)
                except Exception as e:
                    logger.warning(f"Security AI analysis failed: {e}")
        
        security_score = self._calculate_security_score(security_issues)
        
        return {
            "type": "security",
            "findings": security_issues,
            "score": security_score,
            "summary": f"发现 {len(security_issues)} 个安全问题",
            "recommendations": self._generate_security_recommendations(security_issues)
        }
    
    async def _performance_focused_analysis(self, diff_files: List[FilePatchInfo], 
                                          mr_info: Dict) -> Dict[str, Any]:
        """性能专项分析"""
        performance_issues = []
        
        for file_patch in diff_files:
            # 检查常见性能问题
            issues = self._detect_performance_issues(file_patch)
            performance_issues.extend(issues)
        
        # 使用AI进行深度性能分析
        if performance_issues:
            try:
                ai_analysis = await self._ai_performance_analysis(performance_issues, diff_files)
                performance_issues.extend(ai_analysis)
            except Exception as e:
                logger.warning(f"Performance AI analysis failed: {e}")
        
        performance_score = self._calculate_performance_score(performance_issues)
        
        return {
            "type": "performance",
            "findings": performance_issues,
            "score": performance_score,
            "summary": f"发现 {len(performance_issues)} 个性能问题",
            "recommendations": self._generate_performance_recommendations(performance_issues)
        }
    
    async def _quick_analysis(self, diff_files: List[FilePatchInfo], 
                            mr_info: Dict) -> Dict[str, Any]:
        """快速基础分析"""
        basic_issues = []
        
        for file_patch in diff_files:
            issues = self._detect_basic_issues(file_patch)
            basic_issues.extend(issues)
        
        # 快速AI总结
        try:
            quick_summary = await self._ai_quick_summary(diff_files, mr_info)
        except Exception as e:
            logger.warning(f"Quick AI summary failed: {e}")
            quick_summary = "快速分析完成，发现基础问题。"
        
        score = 8.0 - min(len(basic_issues) * 0.5, 3.0)  # 基础评分逻辑
        
        return {
            "type": "quick",
            "findings": basic_issues[:10],  # 限制数量
            "score": max(score, 5.0),
            "summary": quick_summary,
            "recommendations": ["建议进行完整审查以发现更多问题"]
        }
    
    def _detect_basic_issues(self, file_patch: FilePatchInfo) -> List[Dict]:
        """检测基础代码问题"""
        logger.info(f"🔎 开始基础问题检测: {file_patch.filename}")
        
        issues = []
        new_lines = [line for line in file_patch.patch.split('\n') if line.startswith('+')]
        
        logger.info(f"  - 文件类型: {file_patch.edit_type}")
        logger.info(f"  - 新增行数: {len(new_lines)}")
        
        detected_issues_by_type = {}
        
        for line_num, line in enumerate(new_lines, 1):
            line_content = line[1:].strip()  # 移除'+'符号
            
            # 检查基础问题
            if len(line_content) > 120:
                issue = {
                    "type": "line_too_long",
                    "filename": file_patch.filename,
                    "line_number": line_num,
                    "description": f"代码行过长（{len(line_content)}字符），建议保持在120字符以内以提高可读性",
                    "suggestion": "将长行代码拆分为多行，或者重构复杂的表达式",
                    "severity": "low"
                }
                issues.append(issue)
                detected_issues_by_type.setdefault("line_too_long", 0)
                detected_issues_by_type["line_too_long"] += 1
                logger.info(f"  ⚠️  行{line_num}: 代码行过长 ({len(line_content)} 字符)")
            
            if re.search(r"console\.log|print\(.*\)|System\.out\.println", line_content):
                issue = {
                    "type": "debug_statement",
                    "filename": file_patch.filename,
                    "line_number": line_num,
                    "description": f"检测到疑似调试语句：{line_content[:50]}{'...' if len(line_content) > 50 else ''}。调试语句不应提交到生产代码中",
                    "suggestion": "移除调试语句，或使用日志系统替代",
                    "severity": "medium"
                }
                issues.append(issue)
                detected_issues_by_type.setdefault("debug_statement", 0)
                detected_issues_by_type["debug_statement"] += 1
                logger.info(f"  ⚠️  行{line_num}: 检测到调试语句: {line_content[:50]}...")
            
            if re.search(r"TODO|FIXME|HACK", line_content, re.IGNORECASE):
                issue = {
                    "type": "todo_comment",
                    "filename": file_patch.filename,
                    "line_number": line_num,
                    "description": f"包含待办事项或修复标记：{line_content[:50]}{'...' if len(line_content) > 50 else ''}。建议在发布前处理所有TODO和FIXME",
                    "suggestion": "完成TODO项目或创建对应的工单来跟踪，避免在生产代码中留下未完成的标记",
                    "severity": "low"
                }
                issues.append(issue)
                detected_issues_by_type.setdefault("todo_comment", 0)
                detected_issues_by_type["todo_comment"] += 1
                logger.info(f"  ⚠️  行{line_num}: 发现TODO/FIXME: {line_content[:50]}...")
        
        # 总结检测结果
        if issues:
            logger.info(f"  📊 {file_patch.filename} 检测结果:")
            for issue_type, count in detected_issues_by_type.items():
                logger.info(f"    - {issue_type}: {count}个")
            logger.info(f"  ✅ 总计发现 {len(issues)} 个基础问题")
        else:
            logger.info(f"  ✅ {file_patch.filename} 未发现基础问题")
        
        return issues
    
    def _detect_security_issues(self, file_patch: FilePatchInfo) -> List[Dict]:
        """检测安全问题"""
        issues = []
        new_lines = [line for line in file_patch.patch.split('\n') if line.startswith('+')]
        
        security_patterns = {
            "sql_injection": {
                "patterns": [r"execute\(.*\+.*\)", r"query\(.*\+.*\)", r"SELECT.*\+"],
                "description": "可能存在SQL注入风险，检测到字符串拼接构建SQL查询",
                "suggestion": "使用参数化查询或预编译语句防止SQL注入"
            },
            "xss": {
                "patterns": [r"innerHTML\s*=", r"document\.write\(", r"eval\("],
                "description": "可能存在跨站脚本(XSS)风险，检测到直接操作DOM或执行动态代码",
                "suggestion": "对用户输入进行转义，使用安全的DOM操作方法"
            },
            "hardcoded_secrets": {
                "patterns": [r"password\s*=\s*['\"]", r"api[_-]?key\s*=\s*['\"]", r"secret\s*=\s*['\"]"],
                "description": "检测到硬编码的敏感信息，存在安全泄露风险",
                "suggestion": "将敏感信息存储在环境变量或安全的配置管理系统中"
            },
            "path_traversal": {
                "patterns": [r"\.\.\/", r"\.\.\\\\", r"os\.path\.join.*\.\."],
                "description": "可能存在路径穿越风险，检测到相对路径操作",
                "suggestion": "验证和清理文件路径，使用绝对路径或安全的路径处理方法"
            },
            "command_injection": {
                "patterns": [r"os\.system\(", r"subprocess\.", r"exec\(", r"shell=True"],
                "description": "可能存在命令注入风险，检测到系统命令执行",
                "suggestion": "避免执行用户输入的命令，使用参数化的命令执行或白名单验证"
            }
        }
        
        for line_num, line in enumerate(new_lines, 1):
            for category, config in security_patterns.items():
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in config["patterns"]):
                    issues.append({
                        "type": "potential_security_issue",
                        "filename": file_patch.filename,
                        "line_number": line_num,
                        "description": f"{config['description']}。代码：{line.strip()[:50]}{'...' if len(line.strip()) > 50 else ''}",
                        "suggestion": config["suggestion"],
                        "severity": "high",
                        "category": category
                    })
        
        return issues
    
    def _detect_performance_issues(self, file_patch: FilePatchInfo) -> List[Dict]:
        """检测性能问题"""
        issues = []
        new_lines = [line for line in file_patch.patch.split('\n') if line.startswith('+')]
        
        performance_patterns = {
            "n_plus_1_query": {
                "patterns": [r"for.*in.*:", r"\.get\(", r"\.filter\("],
                "description": "可能存在N+1查询问题，在循环中进行数据库查询"
            },
            "inefficient_loop": {
                "patterns": [r"for.*in.*for.*in", r"while.*while"],
                "description": "检测到嵌套循环，可能存在性能问题"
            },
            "memory_leak": {
                "patterns": [r"\.append\(", r"global\s+", r"cache\["],
                "description": "可能存在内存泄漏风险，检测到持续增长的数据结构"
            },
            "blocking_io": {
                "patterns": [r"requests\.get", r"urllib\.request", r"time\.sleep"],
                "description": "检测到阻塞I/O操作，可能影响性能"
            },
            "inefficient_data_structure": {
                "patterns": [r"list\(\)", r"dict\(\)", r"\[\].*in.*for"],
                "description": "可能使用了低效的数据结构或操作"
            }
        }
        
        for line_num, line in enumerate(new_lines, 1):
            for issue_type, config in performance_patterns.items():
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in config["patterns"]):
                    issues.append({
                        "type": issue_type,
                        "filename": file_patch.filename,
                        "line_number": line_num,
                        "description": f"{config['description']}。代码：{line.strip()[:50]}{'...' if len(line.strip()) > 50 else ''}",
                        "severity": "medium",
                        "suggestion": self._get_performance_suggestion(issue_type)
                    })
        
        return issues
    
    async def _ai_comprehensive_analysis(self, diff_files: List[FilePatchInfo], mr_info: Dict) -> Dict[str, Any]:
        """AI综合分析"""
        # 检查AI客户端是否可用
        if not self._is_ai_available():
            logger.info("AI client not available, skipping AI comprehensive analysis")
            return {"findings": [], "suggestions": [], "overall_assessment": "AI客户端不可用，跳过AI分析"}
        
        # 构建分析提示词
        file_summaries = []
        for file_patch in diff_files[:10]:  # 限制文件数量
            summary = f"文件: {file_patch.filename}\n"
            summary += f"变更类型: {file_patch.edit_type}\n"
            summary += f"变更内容:\n{file_patch.patch[:1000]}...\n"  # 限制长度
            file_summaries.append(summary)
        
        # 构建基础提示词
        base_prompt = f"""
请分析以下GitLab Merge Request的代码变更：

MR信息：
- 标题：{mr_info.get('title', '未知')}
- 源分支：{mr_info.get('source_branch', '未知')}
- 目标分支：{mr_info.get('target_branch', '未知')}

文件变更：
{chr(10).join(file_summaries)}

请从以下方面进行分析：
1. 代码质量和最佳实践
2. 潜在的bug和问题
3. 性能影响
4. 安全考虑
5. 可维护性
"""
        
        # 如果不支持结构化输出，添加JSON格式说明
        if not self.client._supports_structured_output(self.model):
            prompt = base_prompt + """
请严格按照以下JSON格式回复，不要添加任何其他文本：
{
    "findings": [
        {
            "type": "问题类型",
            "filename": "文件名", 
            "line_number": 行号,
            "severity": "high/medium/low",
            "description": "问题描述",
            "suggestion": "修复建议"
        }
    ],
    "suggestions": ["改进建议1", "改进建议2"],
    "overall_assessment": "整体评估"
}
"""
        else:
            prompt = base_prompt + "\n请提供详细的代码审查分析。"
        
        try:
            response = await self.client.chat_completion(
                messages=[
                    {"role": "system", "content": "你是一个专业的代码审查专家，请仔细分析代码并提供建设性的反馈。"},
                    {"role": "user", "content": prompt}
                ],
                model=self.model,
                temperature=0.2,
                max_tokens=4000,
                response_format=CODE_REVIEW_SCHEMA
            )
            
            # 清理响应内容，提取JSON部分
            cleaned_response = self._extract_json_from_response(response)
            return json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            logger.warning(f"AI response is not valid JSON: {e}")
            logger.debug(f"Raw response: {response[:500]}...")
            return {"findings": [], "suggestions": [], "overall_assessment": "AI分析失败"}
        except Exception as e:
            logger.error(f"Error processing AI response: {e}")
            return {"findings": [], "suggestions": [], "overall_assessment": "AI分析处理失败"}
    
    def _extract_json_from_response(self, response: str) -> str:
        """从响应中提取JSON内容，增强容错性"""
        import re
        
        # 移除可能的markdown代码块标记
        response = response.strip()
        logger.debug(f"Processing response: {response[:200]}...")
        
        # 如果响应包含```json标记，提取其中的JSON
        if "```json" in response:
            start = response.find("```json") + 7
            end = response.find("```", start)
            if end != -1:
                json_content = response[start:end].strip()
                logger.debug("Extracted JSON from ```json markdown block")
                return self._fix_common_json_issues(json_content)
        
        # 如果响应包含```标记但没有json标识，也尝试提取
        if response.startswith("```") and response.endswith("```"):
            lines = response.split('\n')
            if len(lines) > 2:
                json_content = '\n'.join(lines[1:-1]).strip()
                logger.debug("Extracted content from generic code block")
                return self._fix_common_json_issues(json_content)
        
        # 尝试找到JSON对象的开始和结束
        start_idx = response.find('{')
        if start_idx != -1:
            # 从第一个{开始，找到匹配的}
            brace_count = 0
            for i, char in enumerate(response[start_idx:], start_idx):
                if char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        json_content = response[start_idx:i+1]
                        logger.debug("Extracted JSON object from response")
                        return self._fix_common_json_issues(json_content)
        
        # 如果没有找到JSON结构，尝试修复并返回
        logger.debug("No clear JSON structure found, attempting to fix response")
        return self._fix_common_json_issues(response)
    
    def _fix_common_json_issues(self, json_str: str) -> str:
        """修复常见的JSON格式问题"""
        import re
        
        # 移除前后空白
        json_str = json_str.strip()
        
        # 如果不是以{开头，尝试找到并截取JSON部分
        if not json_str.startswith('{'):
            match = re.search(r'\{.*\}', json_str, re.DOTALL)
            if match:
                json_str = match.group(0)
        
        # 修复常见的JSON格式错误
        # 1. 修复单引号为双引号
        json_str = re.sub(r"'([^']*)':", r'"\1":', json_str)  # 'key': -> "key":
        json_str = re.sub(r":\s*'([^']*)'", r': "\1"', json_str)  # : 'value' -> : "value"
        
        # 2. 修复未引用的键名
        json_str = re.sub(r'(\w+):', r'"\1":', json_str)
        
        # 3. 修复尾随逗号
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)
        
        # 4. 确保字符串值被正确引用
        # 这个比较复杂，先跳过高级修复
        
        logger.debug(f"Fixed JSON: {json_str[:200]}...")
        return json_str
    
    def _aggressive_json_fix(self, json_str: str) -> str:
        """激进的JSON修复方法"""
        import re
        
        logger.debug("尝试激进JSON修复...")
        
        # 如果完全解析失败，尝试构建一个最小的有效JSON
        if not json_str or json_str.strip() == "":
            return '{"findings": [], "suggestions": []}'
        
        # 尝试提取findings和suggestions的内容
        findings_match = re.search(r'"findings"\s*:\s*\[(.*?)\]', json_str, re.DOTALL)
        suggestions_match = re.search(r'"suggestions"\s*:\s*\[(.*?)\]', json_str, re.DOTALL)
        
        findings_content = findings_match.group(1) if findings_match else ""
        suggestions_content = suggestions_match.group(1) if suggestions_match else ""
        
        # 构建一个新的JSON
        fixed_json = f'{{"findings": [{findings_content}], "suggestions": [{suggestions_content}]}}'
        
        # 再次应用基础修复
        return self._fix_common_json_issues(fixed_json)
    
    def _validate_and_fix_result(self, result: dict) -> dict:
        """验证并修复结果结构"""
        # 确保必需的字段存在
        if not isinstance(result, dict):
            logger.warning("结果不是字典类型，返回默认结构")
            return {"findings": [], "suggestions": []}
        
        # 确保findings是列表
        if "findings" not in result or not isinstance(result["findings"], list):
            logger.warning("findings字段缺失或格式错误，使用空列表")
            result["findings"] = []
        
        # 确保suggestions是列表
        if "suggestions" not in result or not isinstance(result["suggestions"], list):
            logger.warning("suggestions字段缺失或格式错误，使用空列表")
            result["suggestions"] = []
        
        # 验证每个finding的格式
        valid_findings = []
        for i, finding in enumerate(result["findings"]):
            if not isinstance(finding, dict):
                logger.warning(f"Finding {i} 不是字典类型，跳过")
                continue
            
            # 确保必需字段存在
            if "type" not in finding:
                finding["type"] = "unknown"
            if "severity" not in finding:
                finding["severity"] = "low"
            if "description" not in finding:
                finding["description"] = "未提供描述"
            
            # 确保severity值有效
            if finding["severity"] not in ["high", "medium", "low"]:
                finding["severity"] = "low"
            
            valid_findings.append(finding)
        
        result["findings"] = valid_findings
        
        # 验证suggestions
        valid_suggestions = []
        for suggestion in result["suggestions"]:
            if isinstance(suggestion, str) and suggestion.strip():
                valid_suggestions.append(suggestion.strip())
        result["suggestions"] = valid_suggestions
        
        logger.debug(f"验证后的结果: {len(result['findings'])} findings, {len(result['suggestions'])} suggestions")
        return result
    
    async def _ai_security_analysis(self, filename: str, line_num: int, code_line: str, category: str) -> Dict[str, Any]:
        """AI安全分析"""
        # 检查AI客户端是否可用
        if not self._is_ai_available():
            logger.info("AI client not available, skipping AI security analysis")
            return {
                "is_vulnerability": False,
                "risk_level": 0,
                "description": "AI客户端不可用，无法进行AI安全分析",
                "filename": filename,
                "line_number": line_num,
                "category": category
            }
            
        # 构建基础提示词
        base_prompt = f"""
分析以下代码行是否存在安全漏洞：

文件：{filename}
行号：{line_num}  
代码：{code_line}
可能问题：{category}

请分析：
1. 这是否真的是一个安全漏洞？
2. 风险级别（1-10）
3. 具体的安全风险
4. 修复建议
"""
        
        # 如果不支持结构化输出，添加JSON格式说明
        if not self.client._supports_structured_output(self.model):
            prompt = base_prompt + """
请严格按照以下JSON格式回复：
{
    "is_vulnerability": true/false,
    "risk_level": 1-10,
    "description": "详细描述",
    "fix_suggestion": "修复建议"
}
"""
        else:
            prompt = base_prompt
        
        try:
            response = await self.client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.1,
                max_tokens=500,
                response_format=SECURITY_ANALYSIS_SCHEMA
            )
            
            # 清理响应内容，提取JSON部分
            cleaned_response = self._extract_json_from_response(response)
            result = json.loads(cleaned_response)
            result.update({
                "filename": filename,
                "line_number": line_num,
                "category": category
            })
            return result
            
        except Exception as e:
            logger.error(f"Failed to analyze security issue: {e}")
            return {
                "is_vulnerability": False,
                "risk_level": 0,
                "description": "分析失败",
                "filename": filename,
                "line_number": line_num,
                "category": category
            }
    
    async def _ai_performance_analysis(self, issues: List[Dict], diff_files: List[FilePatchInfo]) -> List[Dict]:
        """AI性能分析"""
        if not issues:
            return []
            
        # 检查AI客户端是否可用
        if not self._is_ai_available():
            logger.info("AI client not available, skipping AI performance analysis")
            return []
        
        # 构建性能分析提示
        issues_summary = "\n".join([
            f"- {issue['type']} in {issue['filename']}:{issue['line_number']}"
            for issue in issues[:5]
        ])
        
        # 构建基础提示词
        base_prompt = f"""
检测到以下性能问题：
{issues_summary}

请分析这些问题的严重程度并提供优化建议。
"""
        
        # 如果不支持结构化输出，添加JSON格式说明
        if not self.client._supports_structured_output(self.model):
            prompt = base_prompt + """
请严格按照以下JSON数组格式回复，每个问题一个对象：
[
    {
        "type": "性能问题类型",
        "severity": "high/medium/low", 
        "description": "问题描述",
        "optimization": "优化建议"
    }
]
"""
        else:
            prompt = base_prompt
        
        try:
            response = await self.client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.2,
                max_tokens=1000,
                response_format=PERFORMANCE_ANALYSIS_SCHEMA
            )
            
            # 清理响应内容，提取JSON部分
            cleaned_response = self._extract_json_from_response(response)
            return json.loads(cleaned_response)
        except Exception as e:
            logger.error(f"Performance analysis failed: {e}")
            return []
    
    async def _ai_quick_summary(self, diff_files: List[FilePatchInfo], mr_info: Dict) -> str:
        """AI快速总结"""
        # 检查AI客户端是否可用
        if not self._is_ai_available():
            logger.info("AI client not available, using basic summary")
            files_count = len(diff_files)
            return f"快速分析完成，变更涉及{files_count}个文件。AI客户端不可用，仅提供基础分析。"
            
        files_info = ", ".join([f.filename for f in diff_files[:5]])
        if len(diff_files) > 5:
            files_info += f" 等{len(diff_files)}个文件"
        
        prompt = f"""
快速总结以下MR的变更：
- 标题：{mr_info.get('title', '未知')}
- 变更文件：{files_info}
- 总文件数：{len(diff_files)}

请用1-2句话总结主要变更内容和影响。
"""
        
        try:
            return await self.client.chat_completion(
                messages=[{"role": "user", "content": prompt}],
                model=self.model,
                temperature=0.3,
                max_tokens=200
            )
        except Exception as e:
            logger.error(f"Quick summary failed: {e}")
            return f"快速分析完成，变更涉及{len(diff_files)}个文件。"
    
    def _calculate_comprehensive_score(self, findings: List[Dict], diff_files: List[FilePatchInfo]) -> float:
        """计算综合评分"""
        base_score = 8.0
        
        # 根据问题严重程度扣分
        for finding in findings:
            severity = finding.get("severity", "low")
            if severity == "high":
                base_score -= 1.0
            elif severity == "medium":
                base_score -= 0.5
            else:
                base_score -= 0.2
        
        # 根据文件数量调整
        if len(diff_files) > 10:
            base_score -= 0.5
        
        return max(base_score, 3.0)  # 最低3分
    
    def _calculate_security_score(self, security_issues: List[Dict]) -> float:
        """计算安全评分"""
        base_score = 9.0
        
        for issue in security_issues:
            risk_level = issue.get("risk_level", 0)
            base_score -= risk_level * 0.3
        
        return max(base_score, 1.0)
    
    def _calculate_performance_score(self, performance_issues: List[Dict]) -> float:
        """计算性能评分"""
        base_score = 8.0
        
        for issue in performance_issues:
            severity = issue.get("severity", "low")
            if severity == "high":
                base_score -= 1.5
            elif severity == "medium":
                base_score -= 0.8
            else:
                base_score -= 0.3
        
        return max(base_score, 2.0)
    
    def _generate_summary(self, findings: List[Dict], score: float, files_count: int) -> str:
        """生成分析总结"""
        high_issues = len([f for f in findings if f.get("severity") == "high"])
        medium_issues = len([f for f in findings if f.get("severity") == "medium"])
        
        if score >= 8.0:
            quality = "优秀"
        elif score >= 6.0:
            quality = "良好"
        elif score >= 4.0:
            quality = "一般"
        else:
            quality = "需要改进"
        
        return f"代码质量评估：{quality}。分析了{files_count}个文件，发现{high_issues}个高风险问题，{medium_issues}个中等风险问题。"
    
    def _generate_recommendations(self, findings: List[Dict]) -> List[str]:
        """生成改进建议"""
        recommendations = []
        
        if any(f.get("type") == "debug_statement" for f in findings):
            recommendations.append("移除调试语句和日志输出")
        
        if any(f.get("type") == "line_too_long" for f in findings):
            recommendations.append("保持代码行长度在合理范围内")
        
        if any(f.get("severity") == "high" for f in findings):
            recommendations.append("优先处理高风险问题")
        
        recommendations.append("建议添加单元测试覆盖变更代码")
        recommendations.append("确保代码遵循项目编码规范")
        
        return recommendations
    
    def _generate_security_recommendations(self, issues: List[Dict]) -> List[str]:
        """生成安全建议"""
        recommendations = []
        
        categories = set(issue.get("category") for issue in issues)
        
        if "sql_injection" in categories:
            recommendations.append("使用参数化查询防止SQL注入")
        if "xss" in categories:
            recommendations.append("对输出内容进行适当转义")
        if "hardcoded_secrets" in categories:
            recommendations.append("将敏感信息存储在环境变量或配置文件中")
        if "command_injection" in categories:
            recommendations.append("避免直接执行用户输入的命令")
        
        return recommendations
    
    def _generate_performance_recommendations(self, issues: List[Dict]) -> List[str]:
        """生成性能建议"""
        recommendations = []
        
        types = set(issue.get("type") for issue in issues)
        
        if "n_plus_1_query" in types:
            recommendations.append("优化数据库查询，避免N+1问题")
        if "inefficient_loop" in types:
            recommendations.append("优化循环逻辑，减少嵌套层级")
        if "blocking_io" in types:
            recommendations.append("考虑使用异步I/O操作")
        if "memory_leak" in types:
            recommendations.append("检查内存使用，避免内存泄漏")
        
        return recommendations
    
    def _get_performance_suggestion(self, issue_type: str) -> str:
        """获取性能问题建议"""
        suggestions = {
            "n_plus_1_query": "考虑使用批量查询或预加载",
            "inefficient_loop": "尝试优化算法或使用更高效的数据结构",
            "memory_leak": "确保及时清理不需要的对象引用",
            "blocking_io": "使用异步操作或线程池",
            "inefficient_data_structure": "选择更适合的数据结构"
        }
        return suggestions.get(issue_type, "考虑优化此处的性能")
    
    def _estimate_analysis_cost(self, diff_files: List[FilePatchInfo]) -> float:
        """估算分析成本"""
        total_tokens = 0
        for file_patch in diff_files:
            total_tokens += self.token_manager.count_tokens(file_patch.patch)
        
        return self.token_manager.estimate_cost(total_tokens)