import argparse
import json
import os
import re
import sys
import subprocess

from openai import OpenAI

API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = os.getenv("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1")

def load_skills():
    skills = {}
    skills_dir = ".claude/skills"
    if not os.path.exists(skills_dir):
        return skills
        
    for skill_name in os.listdir(skills_dir):
        skill_path = os.path.join(skills_dir, skill_name, "SKILL.md")
        if os.path.isfile(skill_path):
            with open(skill_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    frontmatter = parts[1].strip()
                    body = parts[2].strip()
                    
                    name = skill_name
                    desc = ""
                    for line in frontmatter.split("\n"):
                        line = line.strip()
                        if line.startswith("name:"):
                            name = line.replace("name:", "").strip()
                        elif line.startswith("description:"):
                            desc = line.replace("description:", "").strip()
                            
                    skills[skill_name] = {
                        "name": name,
                        "description": desc,
                        "body": body
                    }
    return skills

def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", required=True)
    args = p.parse_args()

    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)

    skills = load_skills()
    
    messages = []
    
    if skills:
        system_content = "You have access to the following skills:\n\n"
        for s_data in skills.values():
            system_content += f"- {s_data['name']}: {s_data['description']}\n"
        messages.append({"role": "system", "content": system_content.strip()})

    user_content = args.p
    if user_content.startswith("/"):
        command_parts = user_content.split(maxsplit=1)
        skill_key = command_parts[0][1:] # Remove '/'
        
        if skill_key in skills:
            body = skills[skill_key]["body"]
            
            # Argument substitution logic
            args_str = command_parts[1] if len(command_parts) > 1 else ""
            args_list = args_str.split()
            
            def replace_indexed(match):
                idx = int(match.group(1))
                return args_list[idx] if idx < len(args_list) else ""
            
            # Prothome $ARGUMENTS[N] replace koro, nahole pore $ARGUMENTS er sathe conflict hobe
            body = re.sub(r'\$ARGUMENTS\[(\d+)\]', replace_indexed, body)
            # Tarpor $ARGUMENTS replace koro
            body = body.replace("$ARGUMENTS", args_str)
            # Sesh e $N replace koro
            body = re.sub(r'\$(\d+)', replace_indexed, body)
            
            user_content = body

    messages.append({"role": "user", "content": user_content})

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
        },
        {
            "type": "function",
            "function": {
                "name": "Bash",
                "description": "Execute a shell command",
                "parameters": {
                    "type": "object",
                    "required": ["command"],
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The command to execute"
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
                        dir_name = os.path.dirname(file_path)
                        if dir_name:
                            os.makedirs(dir_name, exist_ok=True)
                        with open(file_path, "w") as f:
                            f.write(content)
                        tool_content = "File written successfully."
                    except Exception as e:
                        tool_content = f"Error writing file: {e}"
                        print(f"Error writing file: {e}", file=sys.stderr)
                        
                elif tool_name == "Bash":
                    command = arguments.get("command")
                    try:
                        result = subprocess.run(
                            command, 
                            shell=True, 
                            capture_output=True, 
                            text=True
                        )
                        if result.returncode == 0:
                            tool_content = result.stdout if result.stdout else "Command executed successfully."
                        else:
                            tool_content = result.stderr if result.stderr else f"Command failed with exit code {result.returncode}."
                    except Exception as e:
                        tool_content = f"Error executing command: {e}"
                        print(f"Error executing command: {e}", file=sys.stderr)
                
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