#!/usr/bin/env python3
"""
GitLab Code Reviewer 统一启动脚本
支持内测模式和生产模式
"""
import sys
import os
import subprocess
import argparse
import time

def check_dependencies():
    """检查依赖"""
    print("🔍 检查依赖...")
    
    try:
        import fastapi
        import uvicorn
        import aiohttp
        import gitlab
        import litellm
        print("✅ Python依赖检查通过")
        return True
    except ImportError as e:
        print(f"❌ 缺少依赖: {e}")
        print("请运行: pip install -r requirements.txt")
        return False

def start_test_mode():
    """启动内测模式"""
    print("\n🧪 启动内测模式...")
    print("=" * 50)
    print("📖 API文档: http://localhost:8001/docs")
    print("🏠 内测首页: http://localhost:8001")
    print("🔧 测试命令: python quick_test.py")
    print("=" * 50)
    
    try:
        # 启动内测服务
        subprocess.run([
            sys.executable, "test_api.py"
        ])
    except KeyboardInterrupt:
        print("\n⏹️ 内测服务已停止")

def start_production_mode():
    """启动生产模式"""
    print("\n🚀 启动生产模式...")
    
    # 检查环境变量
    required_env = ["OPENAI_API_KEY"]
    missing_env = []
    
    for env_var in required_env:
        if not os.getenv(env_var):
            missing_env.append(env_var)
    
    if missing_env:
        print(f"❌ 缺少环境变量: {', '.join(missing_env)}")
        print("请设置环境变量或编辑.env文件")
        return False
    
    print("=" * 50)
    print("📖 API文档: http://localhost:8000/docs")
    print("🌐 服务地址: http://localhost:8000")
    print("💡 健康检查: http://localhost:8000/health")
    print("=" * 50)
    
    try:
        # 启动生产服务
        subprocess.run([
            sys.executable, "-m", "uvicorn", 
            "api.main:app",
            "--host", "0.0.0.0",
            "--port", "8000",
            "--reload"
        ])
    except KeyboardInterrupt:
        print("\n⏹️ 生产服务已停止")

def run_quick_test():
    """运行快速测试"""
    print("\n🏃 运行快速测试...")
    
    try:
        subprocess.run([sys.executable, "quick_test.py"])
    except KeyboardInterrupt:
        print("\n⏹️ 测试已中断")

def show_status():
    """显示服务状态"""
    print("\n📊 服务状态检查...")
    
    # 检查端口
    import socket
    
    def check_port(port, service_name):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(1)
        result = sock.connect_ex(('localhost', port))
        sock.close()
        
        if result == 0:
            print(f"✅ {service_name} (端口 {port}): 运行中")
            return True
        else:
            print(f"❌ {service_name} (端口 {port}): 未运行")
            return False
    
    test_running = check_port(8001, "内测服务")
    prod_running = check_port(8000, "生产服务")
    
    if not test_running and not prod_running:
        print("\n💡 建议:")
        print("  启动内测: python start.py test")
        print("  启动生产: python start.py prod")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="GitLab Code Reviewer 启动工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s test              # 启动内测模式
  %(prog)s prod              # 启动生产模式  
  %(prog)s quick-test        # 运行快速测试
  %(prog)s status            # 查看服务状态
  %(prog)s demo              # 查看演示
        """
    )
    
    parser.add_argument(
        'command',
        choices=['test', 'prod', 'production', 'quick-test', 'status', 'demo'],
        help='启动模式'
    )
    
    args = parser.parse_args()
    
    print("GitLab Code Reviewer 启动工具")
    print("基于PR Agent核心技术，专为GitLab优化")
    
    # 检查依赖
    if not check_dependencies():
        sys.exit(1)
    
    # 根据命令执行相应操作
    if args.command == 'test':
        start_test_mode()
    elif args.command in ['prod', 'production']:
        start_production_mode()
    elif args.command == 'quick-test':
        run_quick_test()
    elif args.command == 'status':
        show_status()
    elif args.command == 'demo':
        show_demo()

def show_demo():
    """显示演示信息"""
    print("\n🎪 GitLab Code Reviewer 演示")
    print("=" * 60)
    
    print("\n📋 快速开始:")
    print("1. 内测模式 (推荐开始):")
    print("   python start.py test")
    print("   python quick_test.py")
    
    print("\n2. 生产模式:")
    print("   # 设置环境变量")
    print("   export OPENAI_API_KEY=sk-your-key")
    print("   # 启动服务") 
    print("   python start.py prod")
    
    print("\n📖 API调用示例:")
    print("# 内测调用")
    print("""curl -X POST "http://localhost:8001/test/review" \\
  -H "Content-Type: application/json" \\
  -d '{
    "project_id": "123",
    "mr_id": 456,
    "review_type": "full",
    "mock_scenario": "default"
  }'""")
    
    print("\n# 生产调用")
    print("""curl -X POST "http://localhost:8000/review" \\
  -H "Content-Type: application/json" \\
  -d '{
    "gitlab_url": "https://gitlab.com",
    "project_id": "123", 
    "mr_id": 456,
    "access_token": "glpat-xxxx",
    "review_type": "full"
  }'""")
    
    print("\n🔗 相关链接:")
    print("  内测文档: TEST_GUIDE.md")
    print("  快速指南: QUICKSTART.md") 
    print("  项目说明: README.md")
    
    print("\n💡 提示:")
    print("  - 内测模式无需真实GitLab，使用Mock数据")
    print("  - 生产模式需要配置GitLab访问令牌")
    print("  - 支持多种审查类型: full/security/performance/quick")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 再见！")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ 启动失败: {e}")
        sys.exit(1)