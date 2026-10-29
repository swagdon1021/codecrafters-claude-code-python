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
    
    # Updated System Prompt to advertise the Skill tool
    if skills:
        system_content = "You have access to the following skills:\n\n"
        for s_data in skills.values():
            system_content += f"- {s_data['name']}: {s_data['description']}\n"
        system_content += "\nIf a skill matches the user's request, call the Skill tool with its name\nand follow the instructions it returns."
        messages.append({"role": "system", "content": system_content.strip()})

    user_content = args.p
    tokens = user_content.split()
    invoked_skills = []
    arg_tokens = []
    
    for i, token in enumerate(tokens):
        if token.startswith("/") and len(token) > 1:
            skill_name = token[1:]
            if skill_name in skills:
                invoked_skills.append(skill_name)
                continue
        arg_tokens = tokens[i:]
        break
        
    if invoked_skills:
        args_str = " ".join(arg_tokens)
        
        for skill_name in invoked_skills:
            body = skills[skill_name]["body"]
            
            def replace_indexed(match):
                idx = int(match.group(1))
                return arg_tokens[idx] if idx < len(arg_tokens) else ""
            
            body = re.sub(r'\$ARGUMENTS\[(\d+)\]', replace_indexed, body)
            body = body.replace("$ARGUMENTS", args_str)
            body = re.sub(r'\$(\d+)', replace_indexed, body)
            
            prefix = f"Skill: {skill_name} (located at .claude/skills/{skill_name})\nPaths in the instructions below are relative to that folder.\n\n"
            full_content = prefix + body
            
            messages.append({"role": "user", "content": full_content})
    else:
        messages.append({"role": "user", "content": user_content})

    # Added Skill tool to the tools array
    tools = [
        {
            "type": "function",
            "function": {
                "name": "Skill",
                "description": "Load a skill's instructions into the conversation",
                "parameters": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": { "type": "string", "description": "The name of the skill to use" },
                        "args": { "type": "string", "description": "Optional arguments for the skill" }
                    }
                }
            }
        },
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
                
                # Executing the Skill Tool
                if tool_name == "Skill":
                    skill_req_name = arguments.get("name")
                    skill_args_str = arguments.get("args", "")
                    if skill_args_str is None:
                        skill_args_str = ""
                        
                    if skill_req_name in skills:
                        body = skills[skill_req_name]["body"]
                        call_arg_tokens = skill_args_str.split()
                        
                        def replace_tool_indexed(match):
                            idx = int(match.group(1))
                            return call_arg_tokens[idx] if idx < len(call_arg_tokens) else ""
                        
                        body = re.sub(r'\$ARGUMENTS\[(\d+)\]', replace_tool_indexed, body)
                        body = body.replace("$ARGUMENTS", skill_args_str)
                        body = re.sub(r'\$(\d+)', replace_tool_indexed, body)
                        
                        prefix = f"Skill: {skill_req_name} (located at .claude/skills/{skill_req_name})\nPaths in the instructions below are relative to that folder.\n\n"
                        tool_content = prefix + body
                    else:
                        tool_content = f"Skill '{skill_req_name}' not found."

                elif tool_name == "Read":
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