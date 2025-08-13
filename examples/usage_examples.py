"""
GitLab Code Reviewer 使用示例
演示如何使用API进行代码审查
"""
import asyncio
import aiohttp
import json
from typing import Dict, Any

# API配置
API_BASE_URL = "http://localhost:8000"
GITLAB_URL = "https://gitlab.example.com"
ACCESS_TOKEN = "glpat-your-access-token-here"

class GitLabReviewerClient:
    """GitLab Code Reviewer客户端封装"""
    
    def __init__(self, api_url: str = API_BASE_URL):
        self.api_url = api_url.rstrip('/')
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def health_check(self) -> Dict[str, Any]:
        """健康检查"""
        async with self.session.get(f"{self.api_url}/health") as resp:
            return await resp.json()
    
    async def review_mr(self, gitlab_url: str, project_id: str, mr_id: int,
                       access_token: str, review_type: str = "full") -> Dict[str, Any]:
        """审查单个MR"""
        payload = {
            "gitlab_url": gitlab_url,
            "project_id": project_id,
            "mr_id": mr_id,
            "access_token": access_token,
            "review_type": review_type
        }
        
        async with self.session.post(
            f"{self.api_url}/review",
            json=payload,
            headers={"Content-Type": "application/json"}
        ) as resp:
            if resp.status == 200:
                return await resp.json()
            else:
                error_text = await resp.text()
                raise Exception(f"Review failed: {resp.status} - {error_text}")
    
    async def stream_review(self, gitlab_url: str, project_id: str, mr_id: int,
                           access_token: str, review_type: str = "full"):
        """流式审查MR"""
        payload = {
            "gitlab_url": gitlab_url,
            "project_id": project_id,
            "mr_id": mr_id,
            "access_token": access_token,
            "review_type": review_type
        }
        
        async with self.session.post(
            f"{self.api_url}/review/stream",
            json=payload
        ) as resp:
            async for line in resp.content:
                if line.startswith(b"data: "):
                    try:
                        data = json.loads(line[6:].decode())
                        yield data
                    except json.JSONDecodeError:
                        continue
    
    async def post_comment(self, gitlab_url: str, project_id: str, mr_id: int,
                          access_token: str, review_result: Dict[str, Any]) -> Dict[str, Any]:
        """发布审查评论"""
        payload = {
            "gitlab_url": gitlab_url,
            "project_id": project_id,
            "mr_id": mr_id,
            "access_token": access_token,
            "review_result": review_result,
            "format_type": "markdown"
        }
        
        async with self.session.post(
            f"{self.api_url}/review/comment",
            json=payload
        ) as resp:
            return await resp.json()

# 示例1: 基本代码审查
async def example_basic_review():
    """示例：基本代码审查"""
    print("=== 示例1: 基本代码审查 ===")
    
    async with GitLabReviewerClient() as client:
        # 健康检查
        health = await client.health_check()
        print(f"服务状态: {health['status']}")
        
        # 执行审查
        result = await client.review_mr(
            gitlab_url=GITLAB_URL,
            project_id="123",
            mr_id=456,
            access_token=ACCESS_TOKEN,
            review_type="full"
        )
        
        print(f"审查ID: {result['review_id']}")
        print(f"评分: {result['score']}/10.0")
        print(f"摘要: {result['summary']}")
        print(f"发现 {len(result['findings'])} 个问题")
        print(f"分析了 {result['statistics']['files_analyzed']} 个文件")

# 示例2: 安全专项审查
async def example_security_review():
    """示例：安全专项审查"""
    print("\n=== 示例2: 安全专项审查 ===")
    
    async with GitLabReviewerClient() as client:
        result = await client.review_mr(
            gitlab_url=GITLAB_URL,
            project_id="123",
            mr_id=456,
            access_token=ACCESS_TOKEN,
            review_type="security"
        )
        
        print(f"安全评分: {result['score']}/10.0")
        
        # 显示安全问题
        security_findings = [f for f in result['findings'] if f.get('category') in ['security', 'vulnerability']]
        if security_findings:
            print("发现的安全问题:")
            for i, finding in enumerate(security_findings[:3], 1):
                print(f"  {i}. {finding.get('description', 'No description')}")
                print(f"     风险级别: {finding.get('risk_level', 'Unknown')}")
                print(f"     文件: {finding.get('filename', 'Unknown')}")
        else:
            print("未发现安全问题 ✓")

# 示例3: 流式审查
async def example_stream_review():
    """示例：流式审查"""
    print("\n=== 示例3: 流式审查 ===")
    
    async with GitLabReviewerClient() as client:
        print("开始流式审查...")
        
        async for chunk in client.stream_review(
            gitlab_url=GITLAB_URL,
            project_id="123",
            mr_id=456,
            access_token=ACCESS_TOKEN,
            review_type="quick"
        ):
            chunk_type = chunk.get('type')
            
            if chunk_type == "start":
                print(f"审查开始: {chunk['review_id']}")
            elif chunk_type == "progress":
                progress = chunk.get('progress', 0)
                message = chunk.get('message', '')
                print(f"进度 {progress:.0f}%: {message}")
            elif chunk_type == "file_progress":
                filename = chunk.get('filename', '')
                progress = chunk.get('progress', 0)
                print(f"正在分析: {filename} ({progress:.0f}%)")
            elif chunk_type == "completed":
                result = chunk.get('result', {})
                print(f"审查完成! 评分: {result.get('score', 0)}/10.0")
                break
            elif chunk_type == "error":
                print(f"审查出错: {chunk.get('message', 'Unknown error')}")
                break

# 示例4: 批量审查
async def example_batch_review():
    """示例：批量审查多个MR"""
    print("\n=== 示例4: 批量审查 ===")
    
    # 要审查的MR列表
    mr_list = [
        {"project_id": "123", "mr_id": 456},
        {"project_id": "123", "mr_id": 457},
        {"project_id": "124", "mr_id": 123}
    ]
    
    async with GitLabReviewerClient() as client:
        results = []
        
        for mr in mr_list:
            try:
                print(f"审查 MR {mr['project_id']}!{mr['mr_id']}...")
                
                result = await client.review_mr(
                    gitlab_url=GITLAB_URL,
                    project_id=mr['project_id'],
                    mr_id=mr['mr_id'],
                    access_token=ACCESS_TOKEN,
                    review_type="quick"
                )
                
                results.append({
                    "mr": mr,
                    "score": result['score'],
                    "status": "success"
                })
                
                print(f"  评分: {result['score']}/10.0")
                
            except Exception as e:
                print(f"  失败: {e}")
                results.append({
                    "mr": mr,
                    "error": str(e),
                    "status": "failed"
                })
        
        # 汇总结果
        print("\n批量审查结果:")
        for result in results:
            mr = result['mr']
            if result['status'] == 'success':
                print(f"  ✓ {mr['project_id']}!{mr['mr_id']}: {result['score']}/10.0")
            else:
                print(f"  ✗ {mr['project_id']}!{mr['mr_id']}: {result['error']}")

# 示例5: 自动发布评论
async def example_auto_comment():
    """示例：自动发布审查评论"""
    print("\n=== 示例5: 自动发布评论 ===")
    
    async with GitLabReviewerClient() as client:
        # 执行审查
        result = await client.review_mr(
            gitlab_url=GITLAB_URL,
            project_id="123",
            mr_id=456,
            access_token=ACCESS_TOKEN,
            review_type="full"
        )
        
        print(f"审查完成，评分: {result['score']}/10.0")
        
        # 如果评分较低，自动发布评论
        if result['score'] < 7.0:
            print("评分较低，发布审查评论...")
            
            comment_result = await client.post_comment(
                gitlab_url=GITLAB_URL,
                project_id="123",
                mr_id=456,
                access_token=ACCESS_TOKEN,
                review_result=result
            )
            
            print(f"评论已发布: {comment_result.get('comment_info', {}).get('web_url', 'N/A')}")
        else:
            print("评分良好，无需发布评论")

# 示例6: CI/CD集成示例
def example_cicd_script():
    """示例：CI/CD脚本"""
    print("\n=== 示例6: CI/CD集成脚本 ===")
    
    cicd_script = """
#!/bin/bash
# GitLab CI/CD 代码审查脚本

set -e

# 从环境变量获取MR信息
GITLAB_URL="${CI_SERVER_URL}"
PROJECT_ID="${CI_PROJECT_ID}"
MR_ID="${CI_MERGE_REQUEST_IID}"
ACCESS_TOKEN="${GITLAB_TOKEN}"
REVIEWER_API="${REVIEWER_API_URL:-http://reviewer-api:8000}"

# 检查必要的环境变量
if [ -z "$MR_ID" ]; then
    echo "不是MR流水线，跳过代码审查"
    exit 0
fi

if [ -z "$ACCESS_TOKEN" ]; then
    echo "错误: GITLAB_TOKEN 环境变量未设置"
    exit 1
fi

echo "开始审查 MR ${PROJECT_ID}!${MR_ID}..."

# 调用审查API
REVIEW_RESULT=$(curl -s -X POST "${REVIEWER_API}/review" \\
  -H "Content-Type: application/json" \\
  -d "{
    \\"gitlab_url\\": \\"${GITLAB_URL}\\",
    \\"project_id\\": \\"${PROJECT_ID}\\",
    \\"mr_id\\": ${MR_ID},
    \\"access_token\\": \\"${ACCESS_TOKEN}\\",
    \\"review_type\\": \\"full\\"
  }")

# 解析结果
SCORE=$(echo "$REVIEW_RESULT" | jq -r '.score')
REVIEW_ID=$(echo "$REVIEW_RESULT" | jq -r '.review_id')

echo "审查完成!"
echo "审查ID: $REVIEW_ID"
echo "评分: $SCORE/10.0"

# 根据评分决定是否通过
if (( $(echo "$SCORE < 6.0" | bc -l) )); then
    echo "❌ 代码质量评分过低: $SCORE"
    echo "请修复以下问题后重新提交:"
    echo "$REVIEW_RESULT" | jq -r '.findings[].description' | head -5
    exit 1
else
    echo "✅ 代码审查通过，评分: $SCORE"
fi
    """
    
    print("CI/CD脚本示例:")
    print(cicd_script)

# 主函数
async def main():
    """运行所有示例"""
    print("GitLab Code Reviewer API 使用示例")
    print("=" * 50)
    
    try:
        # await example_basic_review()
        # await example_security_review()
        # await example_stream_review()
        # await example_batch_review()
        # await example_auto_comment()
        example_cicd_script()
        
        print("\n" + "=" * 50)
        print("所有示例演示完成!")
        print("\n使用说明:")
        print("1. 确保服务已启动: docker-compose up -d")
        print("2. 设置正确的GITLAB_URL和ACCESS_TOKEN")
        print("3. 根据需要选择不同的审查类型")
        print("4. 在CI/CD中集成自动化审查")
        
    except Exception as e:
        print(f"示例运行失败: {e}")
        print("请检查:")
        print("1. 服务是否正常运行")
        print("2. 网络连接是否正常")
        print("3. 配置参数是否正确")

if __name__ == "__main__":
    # 注意: 实际使用时需要设置正确的参数
    print("这是示例代码，请根据实际情况修改参数后运行")
    # asyncio.run(main())