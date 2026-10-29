import argparse
import json
import os
import re
import sys
import subprocess
from typing import Dict, List, Any

from openai import OpenAI

API_KEY = os.getenv("OPENROUTER_API_KEY")
BASE_URL = os.getenv("OPENROUTER_BASE_URL", default="https://openrouter.ai/api/v1")
MODEL_NAME = "anthropic/claude-haiku-4.5"

def load_skills() -> Dict[str, Dict[str, str]]:
    """Loads all skills from the .claude/skills directory and parses their frontmatter/body."""
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
                    
                    name, desc, context_val = skill_name, "", ""
                    for line in frontmatter.split("\n"):
                        line = line.strip()
                        if line.startswith("name:"):
                            name = line.replace("name:", "").strip()
                        elif line.startswith("description:"):
                            desc = line.replace("description:", "").strip()
                        elif line.startswith("context:"):
                            context_val = line.replace("context:", "").strip()
                            
                    skills[skill_name] = {
                        "name": name,
                        "description": desc,
                        "context": context_val,
                        "body": body
                    }
    return skills

def execute_tool(tool_name: str, arguments: dict, skills: dict, client: OpenAI, tools: list) -> str:
    """Handles the execution of specific tools based on the LLM's request."""
    if tool_name == "Skill":
        skill_req_name = arguments.get("name")
        skill_args_str = arguments.get("args", "") or ""
            
        if skill_req_name in skills:
            skill_data = skills[skill_req_name]
            body = skill_data["body"]
            call_arg_tokens = skill_args_str.split()
            
            def replace_tool_indexed(match):
                idx = int(match.group(1))
                return call_arg_tokens[idx] if idx < len(call_arg_tokens) else ""
            
            body = re.sub(r'\$ARGUMENTS\[(\d+)\]', replace_tool_indexed, body)
            body = body.replace("$ARGUMENTS", skill_args_str)
            body = re.sub(r'\$(\d+)', replace_tool_indexed, body)
            
            if skill_data.get("context") == "fork":
                # Forked context: Start a subagent
                sub_messages = [{"role": "user", "content": body}]
                sub_result = run_agent_loop(client, sub_messages, skills, tools)
                return f"Skill {skill_req_name} ran in a separate context and returned: {sub_result}"
            else:
                # Normal context
                prefix = f"Skill: {skill_req_name} (located at .claude/skills/{skill_req_name})\nPaths in the instructions below are relative to that folder.\n\n"
                return prefix + body
        return f"Skill '{skill_req_name}' not found."

    elif tool_name == "Read":
        try:
            with open(arguments.get("file_path"), "r") as f:
                return f.read()
        except Exception as e:
            print(f"Error reading file: {e}", file=sys.stderr)
            return f"Error reading file: {e}"
            
    elif tool_name == "Write":
        file_path = arguments.get("file_path")
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w") as f:
                f.write(arguments.get("content"))
            return "File written successfully."
        except Exception as e:
            print(f"Error writing file: {e}", file=sys.stderr)
            return f"Error writing file: {e}"
            
    elif tool_name == "Bash":
        try:
            result = subprocess.run(
                arguments.get("command"), 
                shell=True, 
                capture_output=True, 
                text=True
            )
            if result.returncode == 0:
                return result.stdout if result.stdout else "Command executed successfully."
            return result.stderr if result.stderr else f"Command failed with exit code {result.returncode}."
        except Exception as e:
            print(f"Error executing command: {e}", file=sys.stderr)
            return f"Error executing command: {e}"

    return f"Unknown tool: {tool_name}"

def run_agent_loop(client: OpenAI, messages: List[Dict[str, Any]], skills: dict, tools: list) -> str:
    """Main communication loop with the LLM, managing responses and tool executions."""
    while True:
        chat = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools,
        )

        if not chat.choices:
            raise RuntimeError("no choices in response")

        message = chat.choices[0].message
        messages.append(message)

        if hasattr(message, "tool_calls") and message.tool_calls:
            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                arguments = json.loads(tool_call.function.arguments)
                
                tool_content = execute_tool(tool_name, arguments, skills, client, tools)
                
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_content,
                })
        else:
            return message.content if message.content else ""

def get_tools_schema() -> List[Dict[str, Any]]:
    """Returns the JSON schema for all available tools."""
    return [
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
                        "file_path": { "type": "string", "description": "The path to the file to read" }
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
                        "file_path": { "type": "string", "description": "The path of the file to write to" },
                        "content": { "type": "string", "description": "The content to write to the file" }
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
                        "command": { "type": "string", "description": "The command to execute" }
                    }
                }
            }
        }
    ]

def prepare_initial_messages(user_input: str, skills: dict) -> List[Dict[str, Any]]:
    """Prepares the initial system prompt and parses user input for stacked skills."""
    messages = []
    
    if skills:
        system_content = "You have access to the following skills:\n\n"
        for s_data in skills.values():
            system_content += f"- {s_data['name']}: {s_data['description']}\n"
        system_content += "\nIf a skill matches the user's request, call the Skill tool with its name\nand follow the instructions it returns."
        messages.append({"role": "system", "content": system_content.strip()})

    tokens = user_input.split()
    invoked_skills, arg_tokens = [], []
    
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
            messages.append({"role": "user", "content": prefix + body})
    else:
        messages.append({"role": "user", "content": user_input})
        
    return messages

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", required=True, help="The prompt to send to the model")
    args = parser.parse_args()

    if not API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is not set")

    client = OpenAI(api_key=API_KEY, base_url=BASE_URL)
    skills = load_skills()
    messages = prepare_initial_messages(args.p, skills)
    tools = get_tools_schema()

    print("Logs from your program will appear here!", file=sys.stderr)
    
    final_response = run_agent_loop(client, messages, skills, tools)
    print(final_response)

if __name__ == "__main__":
    main()