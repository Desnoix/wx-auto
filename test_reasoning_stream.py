"""最小验证：LLM 是否在流式模式下返回思考链（reasoning_content）。

用法：
    python test_reasoning_stream.py
    python test_reasoning_stream.py <model_name>   # 覆盖 config 里的模型

从 config/config.yaml 读取 base_url / api_key / model。
"""
import os
import sys
import yaml
from openai import OpenAI


def load_llm_config() -> dict:
    path = os.path.join(os.path.dirname(__file__), "config", "config.yaml")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f).get("llm", {})


def main():
    cfg = load_llm_config()
    model = sys.argv[1] if len(sys.argv) > 1 else cfg["model"]

    print(f"[cfg] base_url={cfg['base_url']}")
    print(f"[cfg] model={model}")
    print(f"[cfg] timeout={cfg.get('timeout', 30)}s")
    print("-" * 60)

    client = OpenAI(
        base_url=cfg["base_url"],
        api_key=cfg["api_key"],
        timeout=cfg.get("timeout", 30),
        max_retries=0,
    )

    stream = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "9.11 和 9.8 哪个大？请一步步思考。"}],
        stream=True,
        max_tokens=1024,
    )

    reasoning_chunks, content_chunks = [], []
    saw_reasoning_field = False
    chunk_count = 0

    for chunk in stream:
        chunk_count += 1
        if not chunk.choices:
            continue
        delta = chunk.choices[0].delta

        reasoning = getattr(delta, "reasoning_content", None)
        if reasoning is not None:
            saw_reasoning_field = True
            reasoning_chunks.append(reasoning)
            print(f"\033[90m{reasoning}\033[0m", end="", flush=True)

        if delta.content:
            content_chunks.append(delta.content)
            print(delta.content, end="", flush=True)

    print("\n" + "-" * 60)
    print(f"[stat] chunk_count={chunk_count}")
    print(f"[stat] saw reasoning_content field: {saw_reasoning_field}")
    print(f"[stat] reasoning length: {sum(len(x) for x in reasoning_chunks)}")
    print(f"[stat] content length:   {sum(len(x) for x in content_chunks)}")

    if not saw_reasoning_field:
        print("\n结论：当前模型不返回 reasoning_content。想看思考链需要换成推理模型。")
    elif not reasoning_chunks:
        print("\n结论：字段存在但内容为空，可能需要在 messages/参数中显式开启推理。")
    else:
        print("\n结论：模型支持流式思考链输出，可以改造 openai_provider.py。")


if __name__ == "__main__":
    main()
