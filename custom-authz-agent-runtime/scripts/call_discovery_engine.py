#!/usr/bin/env python3
"""
Sample script to invoke Discovery Engine (Gemini Enterprise) Search & Assistant API.
"""

import sys
import google.auth
from google.auth.transport.requests import Request
import requests

def call_discovery_engine(query_text: str = "Hello, what can you do?", agent_name: str = "gw-ingress-test"):
    # Prepend @agent_name if specified and not already in prompt
    if agent_name and not query_text.startswith(f"@{agent_name}"):
        full_query = f"@{agent_name} {query_text}"
    else:
        full_query = query_text

    # 1. Obtain Application Default Credentials
    credentials, project_id = google.auth.default()
    credentials.refresh(Request())

    # 2. Configuration
    project_number = "622260204773"
    quota_project_id = "ai-practice-489716"
    engine_id = "myapp_1773239825160"  # Gemini Enterprise App ID

    url = (
        f"https://discoveryengine.googleapis.com/v1/projects/{project_number}/"
        f"locations/global/collections/default_collection/engines/{engine_id}/"
        "servingConfigs/default_search:answer"
    )

    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "X-Goog-User-Project": quota_project_id,
        "Content-Type": "application/json",
    }

    body = {
        "query": {
            "text": full_query
        }
    }

    print(f"Sending query to Gemini Enterprise ({engine_id}): '{full_query}'...")
    response = requests.post(url, headers=headers, json=body)
    print(f"HTTP Status: {response.status_code}")

    if response.status_code == 200:
        data = response.json()
        answer = data.get("answer", {})
        answer_text = answer.get("answerText")
        if answer_text:
            print("\n--- Assistant / Agent Response ---")
            print(answer_text)
        else:
            print("\n--- Raw Response Data ---")
            print(data)
    else:
        print(f"Error ({response.status_code}): {response.text}")

if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else "Hello, what can you do?"
    call_discovery_engine(query)

