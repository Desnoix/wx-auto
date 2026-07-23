"""最小验证：文本 vs 图片调用"""
import base64
from openai import OpenAI

client = OpenAI(
    base_url="https://token.sensenova.cn/v1",
    api_key="sk-iEDWwdaUfLv2Ymn4HaxrmyQZB7exn6rI",
    timeout=60,
)
model = "sensenova-6.7-flash-lite"

# 1. 纯文本
print("=== 测试纯文本 ===")
try:
    r = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "你好，回复一个字"}],
        max_tokens=4096,
    )
    print("choice[0]:", r.choices[0])
    print("content:", repr(r.choices[0].message.content))
    print("finish_reason:", r.choices[0].finish_reason)
except Exception as e:
    print("失败:", e)

# 2. 带图片（用一个 1x1 红色像素的合法 JPEG）
print("\n=== 测试图片（最小 JPEG） ===")
from PIL import Image
from io import BytesIO

img = Image.new("RGB", (64, 64), color=(255, 0, 0))
buf = BytesIO()
img.save(buf, format="JPEG", quality=85)
img_b64 = base64.b64encode(buf.getvalue()).decode()

try:
    r2 = client.chat.completions.create(
        model=model,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": "这张图片是什么颜色？"},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            ],
        }],
        max_tokens=4096,
    )
    print("choice[0]:", r2.choices[0])
    print("content:", repr(r2.choices[0].message.content))
    print("finish_reason:", r2.choices[0].finish_reason)
except Exception as e:
    print("失败:", type(e).__name__, e)
