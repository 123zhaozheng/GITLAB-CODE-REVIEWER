#!/usr/bin/env python3
"""
GitLab Code Reviewer CLI
简单的命令行接口，用于快速测试和使用代码审查功能
"""
import asyncio
import argparse
import json
import sys
from typing import Optional

from core.reviewer import GitLabReviewer
from config.settings import settings, REVIEW_TYPES

def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="GitLab Code Reviewer - AI代码审查工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s review https://gitlab.com/project/repo/-/merge_requests/123 --token glpat-xxx
  %(prog)s review https://gitlab.com/project/repo/-/merge_requests/123 --token glpat-xxx --type security
  %(prog)s list-types
  %(prog)s server --port 8000
        """
    )
    
    subparsers = parser.add_subparsers(dest='command', help='可用命令')
    
    # review 命令
    review_parser = subparsers.add_parser('review', help='审查GitLab MR')
    review_parser.add_argument('mr_url', help='GitLab MR URL')
    review_parser.add_argument('--token', '-t', required=True, help='GitLab访问令牌')
    review_parser.add_argument('--type', '-T', default='full', 
                             choices=list(REVIEW_TYPES.keys()),
                             help='审查类型')
    review_parser.add_argument('--model', '-m', help='AI模型名称')
    review_parser.add_argument('--output', '-o', help='输出文件路径')
    review_parser.add_argument('--format', '-f', choices=['json', 'markdown'], 
                             default='json', help='输出格式')
    review_parser.add_argument('--comment', '-c', action='store_true', 
                             help='将结果发布为MR评论')
    
    # list-types 命令
    subparsers.add_parser('list-types', help='列出支持的审查类型')
    
    # server 命令
    server_parser = subparsers.add_parser('server', help='启动API服务器')
    server_parser.add_argument('--host', default='0.0.0.0', help='服务器地址')
    server_parser.add_argument('--port', type=int, default=8000, help='服务器端口')
    server_parser.add_argument('--reload', action='store_true', help='开发模式（自动重载）')
    
    # health 命令
    health_parser = subparsers.add_parser('health', help='检查服务健康状态')
    health_parser.add_argument('--url', default='http://localhost:8000', 
                             help='服务器URL')
    
    return parser.parse_args()

def parse_mr_url(url: str) -> tuple[str, str, int]:
    """解析GitLab MR URL"""
    import re
    
    # 支持的URL格式：
    # https://gitlab.com/group/project/-/merge_requests/123
    # https://gitlab.example.com/group/project/-/merge_requests/123
    pattern = r'(https?://[^/]+)/([^/-]+(?:/[^/-]+)*?)/-/merge_requests/(\d+)'
    match = re.match(pattern, url)
    
    if not match:
        raise ValueError(f"无效的GitLab MR URL: {url}")
    
    gitlab_url = match.group(1)
    project_path = match.group(2)
    mr_id = int(match.group(3))
    
    return gitlab_url, project_path, mr_id

async def cmd_review(args):
    """执行代码审查"""
    try:
        # 解析MR URL
        gitlab_url, project_id, mr_id = parse_mr_url(args.mr_url)
        
        print(f"开始审查 MR: {project_id}!{mr_id}")
        print(f"GitLab实例: {gitlab_url}")
        print(f"审查类型: {args.type}")
        
        # 创建审查器
        reviewer = GitLabReviewer(
            gitlab_url=gitlab_url,
            access_token=args.token,
            ai_model=args.model
        )
        
        # 执行审查
        result = await reviewer.review_merge_request(
            project_id=project_id,
            mr_id=mr_id,
            review_type=args.type
        )
        
        print(f"\n审查完成！")
        print(f"评分: {result['score']}/10.0")
        print(f"文件数: {result['statistics']['files_analyzed']}")
        
        # 格式化输出
        if args.format == 'json':
            output = json.dumps(result, indent=2, ensure_ascii=False)
        else:  # markdown
            output = format_markdown_result(result)
        
        # 保存到文件或打印
        if args.output:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(output)
            print(f"结果已保存到: {args.output}")
        else:
            print("\n" + "="*50)
            print(output)
        
        # 发布评论
        if args.comment:
            print("\n发布评论到MR...")
            comment_info = await reviewer.post_review_comment(
                project_id=project_id,
                mr_id=mr_id,
                review_result=result
            )
            print(f"评论已发布: {comment_info.get('web_url', 'N/A')}")
        
    except Exception as e:
        print(f"审查失败: {e}", file=sys.stderr)
        sys.exit(1)

def cmd_list_types(args):
    """列出审查类型"""
    print("支持的审查类型:")
    print()
    for type_key, type_info in REVIEW_TYPES.items():
        print(f"📋 {type_key}")
        print(f"   名称: {type_info['name']}")
        print(f"   描述: {type_info['description']}")
        print(f"   关注点: {', '.join(type_info['focus_areas'])}")
        print()

def cmd_server(args):
    """启动API服务器"""
    import uvicorn
    from api.main import app
    
    print(f"启动GitLab Code Reviewer API服务器...")
    print(f"地址: http://{args.host}:{args.port}")
    print(f"文档: http://{args.host}:{args.port}/docs")
    
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info"
    )

async def cmd_health(args):
    """检查服务健康状态"""
    import aiohttp
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{args.url}/health") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print("✅ 服务运行正常")
                    print(f"版本: {data.get('version', 'Unknown')}")
                    print(f"状态: {data.get('status', 'Unknown')}")
                    print(f"运行时间: {data.get('uptime', 'Unknown')}")
                else:
                    print(f"❌ 服务异常 (HTTP {resp.status})")
                    sys.exit(1)
    except Exception as e:
        print(f"❌ 无法连接到服务: {e}")
        sys.exit(1)

def format_markdown_result(result: dict) -> str:
    """格式化Markdown结果"""
    score = result.get('score', 0)
    score_emoji = "🟢" if score >= 8 else "🟡" if score >= 6 else "🔴"
    
    md = f"""# 🤖 AI代码审查报告 {score_emoji}

**评分**: {score:.1f}/10.0
**审查类型**: {result.get('review_type', 'unknown')}
**审查ID**: {result.get('review_id', 'unknown')}

## 📋 审查摘要
{result.get('summary', '无摘要')}

## 📊 统计信息
- 分析文件数: {result.get('statistics', {}).get('files_analyzed', 0)}
- 新增行数: {result.get('statistics', {}).get('total_additions', 0)}
- 删除行数: {result.get('statistics', {}).get('total_deletions', 0)}

"""
    
    # 添加发现的问题
    findings = result.get('findings', [])
    if findings:
        md += "## 🔍 发现的问题\n"
        for i, finding in enumerate(findings[:5], 1):
            if isinstance(finding, dict):
                md += f"{i}. **{finding.get('filename', 'Unknown')}**: {finding.get('description', finding.get('message', 'No description'))}\n"
        if len(findings) > 5:
            md += f"\n... 还有 {len(findings) - 5} 个问题\n"
        md += "\n"
    
    # 添加建议
    suggestions = result.get('suggestions', [])
    recommendations = result.get('recommendations', [])
    all_suggestions = suggestions + recommendations
    
    if all_suggestions:
        md += "## 💡 改进建议\n"
        for i, suggestion in enumerate(all_suggestions[:3], 1):
            md += f"{i}. {suggestion}\n"
        md += "\n"
    
    return md

async def main():
    """主函数"""
    args = parse_args()
    
    if not args.command:
        print("请指定命令。使用 --help 查看帮助。")
        sys.exit(1)
    
    if args.command == 'review':
        await cmd_review(args)
    elif args.command == 'list-types':
        cmd_list_types(args)
    elif args.command == 'server':
        cmd_server(args)
    elif args.command == 'health':
        await cmd_health(args)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n操作已取消")
        sys.exit(0)
    except Exception as e:
        print(f"程序错误: {e}", file=sys.stderr)
        sys.exit(1)