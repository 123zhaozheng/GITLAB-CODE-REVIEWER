#!/usr/bin/env python3
"""
测试pydantic-settings修复是否有效
"""

import os

# 设置一些测试环境变量
os.environ.setdefault("OPENAI_API_KEY", "test-key")

try:
    from config.settings import settings
    print("✅ Settings导入成功")
    print(f"✅ allowed_hosts: {settings.allowed_hosts}")
    print(f"✅ api_key: {settings.openai_api_key}")
    print(f"✅ model: {settings.default_ai_model}")
    print("✅ 所有配置加载正常")
except Exception as e:
    print(f"❌ 配置加载失败: {e}")
    import traceback
    traceback.print_exc()
    exit(1)