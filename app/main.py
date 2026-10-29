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
        },
        {
            "type": "function",
            "function": {
                "name": "Write",
                "description": "Write content to a file",
                "parameters": {
                    "type": "object",
                    "required": ["file_path", "content"],
                    "properties": {
                        "file_path": {
                            "type": "string",
                            "description": "The path of the file to write to"
                        },
                        "content": {
                            "type": "string",
                            "description": "The content to write to the file"
                        }
                    }
                }
            }
        }
    ]

    print("Logs from your program will appear here!", file=sys.stderr)

    while True:
        chat = client.chat.completions.create(
            model="anthropic/claude-haiku-4.5",
            messages=messages,
            tools=tools,
        )

        if not chat.choices or len(chat.choices) == 0:
            raise RuntimeError("no choices in response")

        message = chat.choices[0].message
        
        messages.append(message)

        if hasattr(message, "tool_calls") and message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                tool_content = ""
                
                if tool_name == "Read":
                    file_path = arguments.get("file_path")
                    try:
                        with open(file_path, "r") as f:
                            tool_content = f.read()
                    except Exception as e:
                        tool_content = f"Error reading file: {e}"
                        print(f"Error reading file: {e}", file=sys.stderr)
                        
                elif tool_name == "Write":
                    file_path = arguments.get("file_path")
                    content = arguments.get("content")
                    try:
                        # Jodi folder age theke toiri na thake tahole toiri kore nebe
                        dir_name = os.path.dirname(file_path)
                        if dir_name:
                            os.makedirs(dir_name, exist_ok=True)
                            
                        with open(file_path, "w") as f:
                            f.write(content)
                        tool_content = "File written successfully."
                    except Exception as e:
                        tool_content = f"Error writing file: {e}"
                        print(f"Error writing file: {e}", file=sys.stderr)
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_content,
                })
        else:
            if message.content:
                print(message.content)
            break


if __name__ == "__main__":
    main()