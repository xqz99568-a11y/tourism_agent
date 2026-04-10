"""
测试 Chat API 接口
"""
import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_health():
    """测试健康检查接口"""
    print("=" * 60)
    print("1. 测试 /health 接口")
    print("=" * 60)
    try:
        response = requests.get(f"{BASE_URL}/health", timeout=10)
        print(f"状态码: {response.status_code}")
        print(f"响应: {json.dumps(response.json(), indent=2, ensure_ascii=False)}")
        return response.status_code == 200
    except Exception as e:
        print(f"错误: {e}")
        return False

def test_chat(message: str, session_id: str = None):
    """测试聊天接口"""
    print("=" * 60)
    print(f"2. 测试 /chat 接口 - 发送消息: {message[:50]}...")
    print("=" * 60)
    
    payload = {
        "message": message
    }
    if session_id:
        payload["session_id"] = session_id
    
    try:
        start_time = time.time()
        response = requests.post(
            f"{BASE_URL}/chat", 
            json=payload, 
            timeout=120  # LLM调用可能需要较长时间
        )
        elapsed = time.time() - start_time
        
        print(f"状态码: {response.status_code}")
        print(f"耗时: {elapsed:.2f}秒")
        
        if response.status_code == 200:
            result = response.json()
            print(f"Session ID: {result.get('session_id')}")
            print(f"Message ID: {result.get('message_id')}")
            print(f"响应内容:\n{result.get('content', '')}")
            return result.get('session_id'), result
        else:
            print(f"错误响应: {response.text}")
            return None, None
            
    except Exception as e:
        print(f"错误: {e}")
        return None, None

def main():
    print("\n" + "=" * 60)
    print("Tourism Agent API 测试")
    print("=" * 60)
    
    # 1. 测试健康检查
    if not test_health():
        print("\n健康检查失败，API服务可能未启动")
        return
    
    print("\n[OK] 健康检查通过!\n")
    
    # 2. 测试聊天接口 - 简单对话
    session_id, response = test_chat("你好，请推荐一些北京的旅游景点")
    
    if session_id:
        print("\n[OK] Chat 接口测试成功!")
        print(f"\n会话ID: {session_id}")
        
        # 3. 测试多轮对话
        print("\n" + "=" * 60)
        print("3. 测试多轮对话")
        print("=" * 60)
        
        _, response2 = test_chat(
            "我想安排一个2天的行程，预算3000元",
            session_id=session_id
        )
        
        if response2:
            print("\n[OK] 多轮对话测试成功!")
    else:
        print("\n[FAIL] Chat 接口测试失败")

if __name__ == "__main__":
    main()
