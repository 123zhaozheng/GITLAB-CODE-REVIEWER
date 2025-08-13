"""
AI处理器模块
基于PR Agent的AI处理逻辑优化而来，支持多种AI模型和智能成本控制
"""
import asyncio
import json
import re
from typing import Dict, List, Optional, Any, AsyncGenerator
import tiktoken
from litellm import acompletion
import logging

from config.settings import settings, MODEL_COSTS, REVIEW_TYPES
from core.gitlab_client import FilePatchInfo

logger = logging.getLogger(__name__)

class TokenManager:
    """Token管理器 - 基于PR Agent的token_handler优化"""
    
    def __init__(self, model: str = None):
        self.model = model or settings.default_ai_model
        try:
            if "gpt" in self.model:
                self.encoder = tiktoken.encoding_for_model(self.model)
            else:
                self.encoder = tiktoken.get_encoding("o200k_base")
        except:
            # 备用方案：使用 cl100k_base 编码
            try:
                self.encoder = tiktoken.get_encoding("cl100k_base")
            except:
                # 最后备用方案：使用 GPT-3.5 的编码
                self.encoder = tiktoken.encoding_for_model("gpt-3.5-turbo")
    
    def count_tokens(self, text: str) -> int:
        """计算文本token数量"""
        try:
            return len(self.encoder.encode(text))
        except:
            # 备用方案：按字符数估算
            return len(text) // 4
    
    def estimate_cost(self, input_tokens: int, output_tokens: int = 1000) -> float:
        """估算API调用成本"""
        costs = MODEL_COSTS.get(self.model, {"input": 0.01, "output": 0.03})
        return (input_tokens * costs["input"] + output_tokens * costs["output"]) / 1000

class AIProcessor:
    """AI代码分析处理器"""
    
    def __init__(self, model: str = None):
        self.model = model or settings.default_ai_model
        self.fallback_model = settings.fallback_ai_model
        self.token_manager = TokenManager(self.model)
        self.max_tokens = settings.max_tokens_per_request
        
    async def analyze_merge_request(self, diff_files: List[FilePatchInfo], 
                                   review_type: str = "full",
                                   mr_info: Dict = None) -> Dict[str, Any]:
        """分析整个MR - 主要入口函数"""
        try:
            # 成本优化检查
            if settings.enable_cost_optimization:
                diff_files = await self._optimize_for_cost(diff_files, review_type)
            
            # 根据审查类型选择策略
            if review_type == "security":
                return await self._security_focused_analysis(diff_files, mr_info)
            elif review_type == "performance":
                return await self._performance_focused_analysis(diff_files, mr_info)
            elif review_type == "quick":
                return await self._quick_analysis(diff_files, mr_info)
            else:
                return await self._comprehensive_analysis(diff_files, mr_info)
                
        except Exception as e:
            logger.error(f"AI analysis failed: {e}")
            raise
    
    async def _comprehensive_analysis(self, diff_files: List[FilePatchInfo], 
                                    mr_info: Dict) -> Dict[str, Any]:
        """全面代码分析"""
        
        # 构建分析提示
        prompt = self._build_comprehensive_prompt(diff_files, mr_info)
        
        # 检查token限制
        if self.token_manager.count_tokens(prompt) > self.max_tokens * 0.8:
            # 如果超出限制，分块处理
            return await self._chunked_analysis(diff_files, mr_info, "comprehensive")
        
        # 调用AI进行分析
        response = await self._call_ai_model(prompt, "comprehensive")
        
        # 解析和结构化响应
        return self._parse_comprehensive_response(response, diff_files)
    
    async def _security_focused_analysis(self, diff_files: List[FilePatchInfo], 
                                       mr_info: Dict) -> Dict[str, Any]:
        """安全专项分析"""
        security_patterns = {
            "sql_injection": [
                r"\.execute\s*\(",
                r"\.query\s*\(",
                r"SELECT.*\+.*",
                r"INSERT.*\+.*",
                r"UPDATE.*\+.*",
                r"DELETE.*\+.*"
            ],
            "xss": [
                r"innerHTML\s*=",
                r"outerHTML\s*=",
                r"document\.write\s*\(",
                r"eval\s*\(",
                r"\.html\s*\("
            ],
            "auth_bypass": [
                r"admin\s*=\s*true",
                r"is_admin\s*=",
                r"role\s*=\s*['\"]admin",
                r"bypass",
                r"skip.*auth"
            ],
            "sensitive_data": [
                r"password\s*=",
                r"secret\s*=",
                r"api[_-]?key",
                r"token\s*=",
                r"\.env",
                r"config\.py"
            ]
        }
        
        findings = []
        
        for file_patch in diff_files:
            # 分析新增代码行
            new_lines = [line for line in file_patch.patch.split('\n') if line.startswith('+')]
            
            for line_num, line in enumerate(new_lines, 1):
                for category, patterns in security_patterns.items():
                    for pattern in patterns:
                        if re.search(pattern, line, re.IGNORECASE):
                            # 使用AI进一步分析
                            analysis = await self._analyze_security_issue(
                                line, file_patch.filename, category, line_num
                            )
                            if analysis.get("is_vulnerability", False):
                                findings.append(analysis)
        
        # 计算安全分数
        security_score = self._calculate_security_score(findings)
        
        return {
            "type": "security",
            "findings": findings,
            "score": security_score,
            "summary": f"发现 {len(findings)} 个潜在安全问题",
            "recommendations": self._generate_security_recommendations(findings)
        }
    
    async def _analyze_security_issue(self, code_line: str, filename: str, 
                                    category: str, line_num: int) -> Dict[str, Any]:
        """使用AI分析具体安全问题"""
        prompt = f"""
作为安全专家，分析以下代码行是否存在安全漏洞：

文件: {filename}
行号: {line_num}
代码: {code_line}
可能的问题类型: {category}

请分析：
1. 这是否真的是一个安全漏洞？
2. 风险级别（1-10）
3. 具体的安全风险
4. 修复建议

请以JSON格式回复：
{{
    "is_vulnerability": true/false,
    "risk_level": 1-10,
    "description": "详细描述",
    "fix_suggestion": "修复建议"
}}
"""
        
        try:
            # 构建litellm调用参数
            call_params = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.1,
                "max_tokens": 500
            }
            
            # 添加自定义配置
            litellm_config = settings.litellm_model_config
            if litellm_config:
                call_params.update(litellm_config)
            
            response = await acompletion(**call_params)
            
            result = json.loads(response.choices[0].message.content)
            result.update({
                "filename": filename,
                "line_number": line_num,
                "code_line": code_line,
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
            ai_analysis = await self._ai_performance_analysis(performance_issues, diff_files)
            performance_issues.extend(ai_analysis)
        
        performance_score = self._calculate_performance_score(performance_issues)
        
        return {
            "type": "performance",
            "findings": performance_issues,
            "score": performance_score,
            "summary": f"发现 {len(performance_issues)} 个性能问题",
            "recommendations": self._generate_performance_recommendations(performance_issues)
        }
    
    def _detect_performance_issues(self, file_patch: FilePatchInfo) -> List[Dict]:
        """检测常见性能问题"""
        issues = []
        new_lines = [line for line in file_patch.patch.split('\n') if line.startswith('+')]
        
        performance_patterns = {
            "n_plus_1_query": [r"for.*in.*:", r"\.get\(", r"\.filter\("],
            "inefficient_loop": [r"for.*in.*for.*in", r"while.*while"],
            "memory_leak": [r"\.append\(", r"global\s+", r"cache\["],
            "blocking_io": [r"requests\.get", r"urllib\.request", r"time\.sleep"],
            "inefficient_data_structure": [r"list\(\)", r"dict\(\)", r"\[\].*in.*for"]
        }
        
        for line_num, line in enumerate(new_lines, 1):
            for issue_type, patterns in performance_patterns.items():
                if any(re.search(pattern, line, re.IGNORECASE) for pattern in patterns):
                    issues.append({
                        "type": issue_type,
                        "filename": file_patch.filename,
                        "line_number": line_num,
                        "code_line": line.strip(),
                        "severity": "medium",
                        "suggestion": self._get_performance_suggestion(issue_type)
                    })
        
        return issues
    
    async def _quick_analysis(self, diff_files: List[FilePatchInfo], 
                            mr_info: Dict) -> Dict[str, Any]:
        """快速基础分析"""
        issues = []
        
        for file_patch in diff_files:
            # 基础代码质量检查
            basic_issues = self._basic_quality_check(file_patch)
            issues.extend(basic_issues)
        
        quality_score = 10 - min(len(issues), 5)  # 简单评分
        
        return {
            "type": "quick",
            "findings": issues[:10],  # 限制结果数量
            "score": quality_score,
            "summary": f"快速检查发现 {len(issues)} 个基础问题",
            "recommendations": ["进行更详细的代码审查", "运行完整测试套件"]
        }
    
    def _basic_quality_check(self, file_patch: FilePatchInfo) -> List[Dict]:
        """基础代码质量检查"""
        issues = []
        new_lines = [line for line in file_patch.patch.split('\n') if line.startswith('+')]
        
        for line_num, line in enumerate(new_lines, 1):
            line_content = line[1:].strip()  # 移除'+'符号
            
            # 检查基础问题
            if len(line_content) > 120:
                issues.append({
                    "type": "line_too_long",
                    "filename": file_patch.filename,
                    "line_number": line_num,
                    "message": "代码行过长"
                })
            
            if re.search(r"console\.log|print\(.*\)|System\.out\.println", line_content):
                issues.append({
                    "type": "debug_statement",
                    "filename": file_patch.filename,
                    "line_number": line_num,
                    "message": "可能包含调试语句"
                })
            
            if re.search(r"TODO|FIXME|HACK", line_content, re.IGNORECASE):
                issues.append({
                    "type": "todo_comment",
                    "filename": file_patch.filename,
                    "line_number": line_num,
                    "message": "包含待办事项或修复标记"
                })
        
        return issues
    
    async def _call_ai_model(self, prompt: str, analysis_type: str) -> str:
        """调用AI模型进行分析"""
        try:
            # 构建litellm调用参数
            call_params = {
                "model": self.model,
                "messages": [
                    {
                        "role": "system", 
                        "content": self._get_system_prompt(analysis_type)
                    },
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 4000
            }
            
            # 添加自定义配置
            litellm_config = settings.litellm_model_config
            if litellm_config:
                call_params.update(litellm_config)
            
            # 首先尝试主模型
            response = await acompletion(**call_params)
            
            return response.choices[0].message.content
            
        except Exception as e:
            logger.warning(f"Primary model failed, trying fallback: {e}")
            
            # 尝试备用模型
            try:
                fallback_params = {
                    "model": self.fallback_model,
                    "messages": [
                        {
                            "role": "system", 
                            "content": self._get_system_prompt(analysis_type)
                        },
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                    "max_tokens": 2000
                }
                
                # 添加自定义配置
                litellm_config = settings.litellm_model_config
                if litellm_config:
                    fallback_params.update(litellm_config)
                
                response = await acompletion(**fallback_params)
                
                return response.choices[0].message.content
                
            except Exception as e2:
                logger.error(f"Both models failed: {e2}")
                raise
    
    def _get_system_prompt(self, analysis_type: str) -> str:
        """获取系统提示"""
        base_prompt = """你是一个资深的代码审查专家，专门分析GitLab Merge Request中的代码变更。
你的任务是提供建设性、准确、实用的代码审查反馈。

重点关注：
1. 代码质量和最佳实践
2. 潜在的bug和逻辑错误
3. 性能优化机会
4. 安全性问题
5. 可维护性和可读性

请提供具体、可操作的建议，并给出改进建议。"""

        if analysis_type == "security":
            return base_prompt + "\n\n特别专注于安全漏洞检测，包括SQL注入、XSS、认证绕过、敏感数据泄露等。"
        elif analysis_type == "performance":
            return base_prompt + "\n\n特别专注于性能问题，包括算法效率、数据库查询优化、内存使用等。"
        elif analysis_type == "quick":
            return base_prompt + "\n\n进行快速基础检查，重点关注明显的问题和最佳实践违反。"
        else:
            return base_prompt
    
    async def _optimize_for_cost(self, diff_files: List[FilePatchInfo], 
                               review_type: str) -> List[FilePatchInfo]:
        """成本优化 - 智能选择要分析的文件"""
        if not settings.enable_cost_optimization:
            return diff_files
        
        # 估算当前成本
        total_tokens = sum(
            self.token_manager.count_tokens(f.patch + f.new_content) 
            for f in diff_files
        )
        estimated_cost = self.token_manager.estimate_cost(total_tokens)
        
        if estimated_cost <= settings.max_cost_per_review:
            return diff_files
        
        # 按重要性排序文件
        from config.settings import FILE_PRIORITY
        
        def get_file_importance(file_patch):
            ext = '.' + file_patch.filename.split('.')[-1] if '.' in file_patch.filename else ''
            base_priority = FILE_PRIORITY.get(ext, 5)
            
            # 根据变更大小调整优先级
            change_size = file_patch.num_plus_lines + file_patch.num_minus_lines
            if change_size > 100:
                base_priority += 2
            elif change_size > 50:
                base_priority += 1
            
            return base_priority
        
        # 排序并选择
        sorted_files = sorted(diff_files, key=get_file_importance, reverse=True)
        
        selected_files = []
        current_cost = 0
        
        for file_patch in sorted_files:
            file_tokens = self.token_manager.count_tokens(file_patch.patch + file_patch.new_content)
            file_cost = self.token_manager.estimate_cost(file_tokens)
            
            if current_cost + file_cost <= settings.max_cost_per_review:
                selected_files.append(file_patch)
                current_cost += file_cost
            else:
                break
        
        logger.info(f"Cost optimization: selected {len(selected_files)}/{len(diff_files)} files")
        return selected_files
    
    def _build_comprehensive_prompt(self, diff_files: List[FilePatchInfo], 
                                  mr_info: Dict) -> str:
        """构建全面分析的提示"""
        prompt = f"""
请分析以下GitLab Merge Request的代码变更：

MR信息：
- 标题: {mr_info.get('title', '未知')}
- 描述: {mr_info.get('description', '无描述')[:500]}
- 变更文件数: {len(diff_files)}

代码变更详情：
"""
        
        for file_patch in diff_files:
            prompt += f"""

## 文件: {file_patch.filename}
编辑类型: {file_patch.edit_type}
新增行数: {file_patch.num_plus_lines}
删除行数: {file_patch.num_minus_lines}

代码差异:
```diff
{file_patch.patch[:2000]}  
```
"""
            if len(file_patch.patch) > 2000:
                prompt += "\n[代码差异过长，已截断]"
        
        prompt += """

请提供详细的代码审查，包括：
1. 代码质量评估 (1-10分)
2. 发现的问题和建议
3. 优点和改进点
4. 安全性考虑
5. 性能影响评估

请以结构化格式回复。
"""
        
        return prompt
    
    def _parse_comprehensive_response(self, response: str, 
                                   diff_files: List[FilePatchInfo]) -> Dict[str, Any]:
        """解析全面分析的响应"""
        # 简化的解析逻辑，实际应用中可以更复杂
        try:
            # 尝试提取分数
            score_match = re.search(r'(\d+(?:\.\d+)?)\s*分', response)
            score = float(score_match.group(1)) if score_match else 7.0
            
            # 提取建议
            suggestions = re.findall(r'[建议建議]\s*[:：]\s*(.+)', response)
            
            # 提取问题
            issues = re.findall(r'[问题問題]\s*[:：]\s*(.+)', response)
            
            return {
                "type": "comprehensive",
                "score": min(max(score, 1), 10),  # 限制在1-10范围
                "summary": response[:500] + "..." if len(response) > 500 else response,
                "suggestions": suggestions,
                "issues": issues,
                "raw_response": response,
                "files_analyzed": len(diff_files)
            }
            
        except Exception as e:
            logger.error(f"Failed to parse AI response: {e}")
            return {
                "type": "comprehensive", 
                "score": 7.0,
                "summary": "AI分析完成，但解析结果时出现问题",
                "raw_response": response,
                "files_analyzed": len(diff_files)
            }
    
    def _calculate_security_score(self, findings: List[Dict]) -> float:
        """计算安全分数"""
        if not findings:
            return 10.0
        
        total_risk = sum(f.get("risk_level", 5) for f in findings)
        max_possible_risk = len(findings) * 10
        
        # 转换为0-10分数（风险越高，分数越低）
        score = 10 - (total_risk / max_possible_risk * 10)
        return max(score, 1.0)
    
    def _calculate_performance_score(self, issues: List[Dict]) -> float:
        """计算性能分数"""
        if not issues:
            return 10.0
        
        severity_weights = {"high": 3, "medium": 2, "low": 1}
        total_weight = sum(severity_weights.get(i.get("severity", "medium"), 2) for i in issues)
        
        # 简单的评分逻辑
        score = 10 - min(total_weight, 8)
        return max(score, 1.0)
    
    def _generate_security_recommendations(self, findings: List[Dict]) -> List[str]:
        """生成安全建议"""
        recommendations = [
            "定期进行安全代码审查",
            "使用静态代码安全分析工具",
            "实施输入验证和清理",
            "使用参数化查询防止SQL注入",
            "启用HTTPS和安全头"
        ]
        return recommendations[:3]  # 返回前3个建议
    
    def _generate_performance_recommendations(self, issues: List[Dict]) -> List[str]:
        """生成性能建议"""
        recommendations = [
            "使用数据库索引优化查询",
            "实施缓存策略减少重复计算",
            "优化算法复杂度",
            "使用异步处理提高并发性",
            "监控和分析性能瓶颈"
        ]
        return recommendations[:3]
    
    def _get_performance_suggestion(self, issue_type: str) -> str:
        """获取性能问题的建议"""
        suggestions = {
            "n_plus_1_query": "考虑使用批量查询或预加载来避免N+1查询问题",
            "inefficient_loop": "考虑优化嵌套循环或使用更高效的算法",
            "memory_leak": "注意内存使用，及时清理不需要的对象",
            "blocking_io": "考虑使用异步IO操作提高性能",
            "inefficient_data_structure": "选择更适合的数据结构提高效率"
        }
        return suggestions.get(issue_type, "需要进一步性能优化")