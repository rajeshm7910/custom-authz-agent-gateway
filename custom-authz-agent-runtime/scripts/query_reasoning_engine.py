#!/usr/bin/env python3
"""
Script to directly query a Vertex AI Reasoning Engine Agent.

Usage:
  python3 scripts/query_reasoning_engine.py [PROMPT] [ENGINE_ID]

Examples:
  python3 scripts/query_reasoning_engine.py "What is the weather in Fremont?"
  python3 scripts/query_reasoning_engine.py "Hello, what can you do?" 1231533837213761536
"""

import sys
import json
import argparse
import google.auth
from google.auth.transport.requests import Request
import requests

def query_reasoning_engine(
    prompt: str = "What is the status of my order?",
    project_id: str = "622260204773",
    location: str = "us-central1",
    engine_id: str = "1231533837213761536",
):
    # 1. Obtain credentials
    credentials, _ = google.auth.default()
    credentials.refresh(Request())

    # 2. Vertex AI Reasoning Engine streamQuery endpoint
    url = (
        f"https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/"
        f"locations/{location}/reasoningEngines/{engine_id}:streamQuery"
    )

    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }

    # 3. Payload structured for ADK Reasoning Engine
    payload = {
        "user_id": "user@example.com",
        "session_id": "sess-default-001",
        "message": {
            "role": "user",
            "parts": [{"text": prompt}],
        },
    }

    body = {
        "class_method": "streaming_agent_run_with_events",
        "input": {
            "request_json": json.dumps(payload)
        }
    }

    print(f"Querying Reasoning Engine ({engine_id}) at {location}:")
    print(f"Prompt: \"{prompt}\"")
    print("-" * 60)

    response = requests.post(url, headers=headers, json=body, stream=True)

    if response.status_code != 200:
        print(f"Error ({response.status_code}): {response.text}")
        return

    # 4. Parse streaming response chunks
    full_text = []
    for line in response.iter_lines():
        if line:
            decoded = line.decode("utf-8")
            try:
                data = json.loads(decoded)
                events = data.get("events", [])
                for event in events:
                    content = event.get("content", {})
                    for part in content.get("parts", []):
                        if "text" in part:
                            full_text.append(part["text"])
                        elif "function_call" in part:
                            fn = part["function_call"]
                            print(f"[Tool Call] {fn.get('name')}({fn.get('args')})")
                        elif "function_response" in part:
                            fr = part["function_response"]
                            print(f"[Tool Result] {fr.get('name')} -> {fr.get('response')}")
            except json.JSONDecodeError:
                # Direct string or partial chunk
                print(decoded)

    if full_text:
        print("\n--- Agent Response ---")
        print("".join(full_text))
    print("-" * 60)

def main():
    parser = argparse.ArgumentParser(description="Directly query a Vertex AI Reasoning Engine.")
    parser.add_argument("prompt", nargs="?", default="What is the weather in Fremont?", help="Prompt to send to the agent")
    parser.add_argument("--engine-id", default="1231533837213761536", help="Reasoning Engine ID (default: gw-ingress-test)")
    parser.add_argument("--project", default="622260204773", help="GCP Project ID or Number")
    parser.add_argument("--location", default="us-central1", help="GCP Region/Location")

    args = parser.parse_args()
    query_reasoning_engine(
        prompt=args.prompt,
        project_id=args.project,
        location=args.location,
        engine_id=args.engine_id,
    )

if __name__ == "__main__":
    main()
