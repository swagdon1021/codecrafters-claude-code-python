import argparse
import json
import os
import sys

from openai import OpenAI

API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = os.getenv("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", required=True)
    args = p.parse_args()

    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    # 1. Initialize messages array
    messages = [{"role": "user", "content": args.p}]
    tools = [
        {
            "type": "function",
            "function": {
                "name": "Read",
                "description": "Read and return the contents of a file",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "The path to the file to read",
                        }
                    },
                    "required": ["file_path"],
                },
            },
        }
    ]

    print("Logs from your program will appear here!", file=sys.stderr)

    # 2. Enter the agent loop
    while True:
        chat = client.chat.completions.create(
            model="anthropic/claude-haiku-4.5",
            messages=messages,
            tools=tools,
        )

        if not chat.choices or len(chat.choices) == 0:
            raise RuntimeError("no choices in response")

        message = chat.choices[0].message
        
        # 3. Append assistant's response to messages history
        messages.append(message)

        # 4. Handle tool calls or break loop
        if hasattr(message, "tool_calls") and message.tool_calls:
            for tool_call in message.tool_calls:
                arguments = json.loads(tool_call.function.arguments)
                file_path = arguments.get("file_path")
                
                try:
                    with open(file_path, "r") as f:
                        file_content = f.read()
                except Exception as e:
                    file_content = f"Error reading file: {e}"
                    print(f"Error reading file: {e}", file=sys.stderr)
                
                # Append tool result back to messages
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": file_content,
                })
        else:
            # 5. No more tool calls, print final response and exit
            if message.content:
                print(message.content)
            break


if __name__ == "__main__":
    main()