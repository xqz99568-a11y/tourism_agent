"""
带详细计时的 Chat API 测试
"""
import requests
import json
import time

BASE_URL = "http://localhost:8000"

def test_chat_timed(message: str, session_id: str = None):
    """测试聊天接口并记录详细耗时"""
    print("=" * 60)
    print(f"Testing /chat with: {message[:50]}...")
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
            timeout=180
        )
        total_elapsed = time.time() - start_time

        print(f"HTTP Status: {response.status_code}")
        print(f"Total time: {total_elapsed:.2f}s")

        if response.status_code == 200:
            result = response.json()
            print(f"Session ID: {result.get('session_id')}")
            print(f"Content length: {len(result.get('content', ''))} chars")
            print(f"\nResponse:\n{result.get('content', '')}")
            return result.get('session_id'), result
        else:
            print(f"Error: {response.text}")
            return None, None

    except requests.exceptions.Timeout:
        print("Request timed out after 180s")
        return None, None
    except Exception as e:
        print(f"Error: {e}")
        return None, None

def main():
    print("\n" + "=" * 60)
    print("Tourism Agent - Detailed Timing Test")
    print("=" * 60)

    # Test 1: Simple Q&A (should be fastest)
    print("\n[Test 1] Simple attraction recommendation")
    session1, _ = test_chat_timed("推荐一些杭州的景点")
    if session1:
        print(f"Test 1 completed - Session: {session1[:20]}...")

    # Test 2: Multi-turn conversation
    print("\n[Test 2] Second message with context")
    session2, _ = test_chat_timed(
        "安排一个3天行程，预算5000元",
        session_id=session1
    )
    if session2:
        print(f"Test 2 completed - Session: {session2[:20]}...")

    # Test 3: Budget question only
    print("\n[Test 3] Budget question only")
    _, _ = test_chat_timed("2000元能在杭州玩几天？")

if __name__ == "__main__":
    main()
