#!/usr/bin/env python3
"""
快速内测脚本 - 一键运行所有测试场景
"""
import asyncio
import aiohttp
import json
import time
import sys
from typing import Dict, Any

class QuickTester:
    """快速内测工具"""
    
    def __init__(self, api_url: str = "http://localhost:8001"):
        self.api_url = api_url.rstrip('/')
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            async with self.session.get(f"{self.api_url}/health") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    print(f"✅ 服务健康检查通过: {data['status']}")
                    return True
                else:
                    print(f"❌ 服务异常: HTTP {resp.status}")
                    return False
        except Exception as e:
            print(f"❌ 无法连接到服务: {e}")
            return False
    
    async def test_single_review(self, scenario: str = "default") -> Dict[str, Any]:
        """测试单个审查场景"""
        print(f"\n🔍 测试场景: {scenario}")
        
        payload = {
            "project_id": "123",
            "mr_id": 456,
            "review_type": "full",
            "mock_scenario": scenario
        }
        
        start_time = time.time()
        
        try:
            async with self.session.post(
                f"{self.api_url}/test/review",
                json=payload
            ) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    duration = time.time() - start_time
                    
                    print(f"  ✅ 审查完成 ({duration:.2f}秒)")
                    print(f"  📊 评分: {result['score']}/10.0")
                    print(f"  🔍 发现问题: {len(result.get('findings', []))}个")
                    print(f"  📁 分析文件: {result.get('statistics', {}).get('files_analyzed', 0)}个")
                    
                    return result
                else:
                    error = await resp.text()
                    print(f"  ❌ 审查失败: {error}")
                    return None
                    
        except Exception as e:
            print(f"  ❌ 请求异常: {e}")
            return None
    
    async def test_all_scenarios(self):
        """测试所有场景"""
        print("\n📋 获取可用场景...")
        
        try:
            async with self.session.get(f"{self.api_url}/test/scenarios") as resp:
                scenarios_data = await resp.json()
                scenarios = list(scenarios_data["scenarios"].keys())
                
                print(f"发现 {len(scenarios)} 个测试场景")
                
                results = []
                for scenario in scenarios:
                    result = await self.test_single_review(scenario)
                    if result:
                        results.append({
                            "scenario": scenario,
                            "score": result["score"],
                            "findings": len(result.get("findings", []))
                        })
                
                print(f"\n📊 场景测试汇总:")
                for result in results:
                    print(f"  {result['scenario']}: {result['score']}/10.0 ({result['findings']}个问题)")
                
                return results
                
        except Exception as e:
            print(f"❌ 获取场景失败: {e}")
            return []
    
    async def test_performance(self):
        """性能测试"""
        print(f"\n⚡ 执行性能测试...")
        
        try:
            async with self.session.post(f"{self.api_url}/test/performance") as resp:
                if resp.status == 200:
                    result = await resp.json()
                    perf = result["performance_test"]
                    
                    print(f"  📈 并发请求: {perf['concurrent_requests']}")
                    print(f"  ⏱️ 总耗时: {perf['total_time']}秒")
                    print(f"  🚀 平均响应时间: {perf['average_time_per_request']}秒")
                    print(f"  ✅ 成功率: {perf['success_rate']}")
                    
                    if perf.get('errors'):
                        print(f"  ❌ 错误: {len(perf['errors'])}个")
                    
                    return result
                else:
                    error = await resp.text()
                    print(f"  ❌ 性能测试失败: {error}")
                    
        except Exception as e:
            print(f"❌ 性能测试异常: {e}")
    
    async def test_ai_models(self):
        """测试AI模型"""
        print(f"\n🤖 测试AI模型连接...")
        
        try:
            async with self.session.get(f"{self.api_url}/test/ai-models") as resp:
                if resp.status == 200:
                    result = await resp.json()
                    
                    print(f"  📡 状态: {result['status']}")
                    print(f"  🧠 模型: {result['model']}")
                    
                    if result['status'] == 'available':
                        print(f"  ✅ AI模型连接正常")
                    else:
                        print(f"  ❌ AI模型连接异常: {result.get('error', 'Unknown')}")
                    
                    return result
                    
        except Exception as e:
            print(f"❌ AI模型测试异常: {e}")
    
    async def test_batch_review(self):
        """批量测试"""
        print(f"\n📦 执行批量测试...")
        
        try:
            async with self.session.post(f"{self.api_url}/test/batch-review") as resp:
                if resp.status == 200:
                    result = await resp.json()
                    summary = result["summary"]
                    
                    print(f"  📊 总数: {summary['total']}")
                    print(f"  ✅ 成功: {summary['success']}")
                    print(f"  ❌ 失败: {summary['failed']}")
                    
                    print(f"\n  详细结果:")
                    for test_result in result["batch_test_results"]:
                        if test_result.get("status") == "success":
                            print(f"    ✅ {test_result['scenario']}: {test_result['score']}/10.0")
                        else:
                            print(f"    ❌ {test_result['scenario']}: {test_result.get('error', 'Unknown error')}")
                    
                    return result
                    
        except Exception as e:
            print(f"❌ 批量测试异常: {e}")
    
    async def run_full_test(self):
        """运行完整测试套件"""
        print("🚀 GitLab Code Reviewer 快速内测")
        print("=" * 50)
        
        # 1. 健康检查
        if not await self.health_check():
            print("❌ 服务未启动，请先运行: python test_api.py")
            return False
        
        # 2. AI模型测试
        await self.test_ai_models()
        
        # 3. 单个场景测试
        await self.test_single_review("default")
        
        # 4. 性能测试
        await self.test_performance()
        
        # 5. 批量测试
        await self.test_batch_review()
        
        # 6. 所有场景测试
        await self.test_all_scenarios()
        
        print("\n" + "=" * 50)
        print("🎉 内测完成！")
        print("\n💡 下一步:")
        print("  1. 访问 http://localhost:8001/docs 查看API文档")
        print("  2. 修改配置后测试真实GitLab集成")
        print("  3. 部署到生产环境")
        
        return True

async def main():
    """主函数"""
    print("GitLab Code Reviewer 快速内测工具")
    
    # 检查参数
    if len(sys.argv) > 1:
        if sys.argv[1] == "--scenario":
            scenario = sys.argv[2] if len(sys.argv) > 2 else "default"
            async with QuickTester() as tester:
                await tester.test_single_review(scenario)
            return
        elif sys.argv[1] == "--performance":
            async with QuickTester() as tester:
                await tester.test_performance()
            return
        elif sys.argv[1] == "--ai":
            async with QuickTester() as tester:
                await tester.test_ai_models()
            return
    
    # 运行完整测试
    async with QuickTester() as tester:
        await tester.run_full_test()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⏹️ 测试中断")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        sys.exit(1)