#!/usr/bin/env python3
"""
Test script to send the query ('Weather of Fremont today?') through:
1. Two-Tier Ingress Agent Gateway (Anycast IP: 107.178.242.66, Host: agw-ingress.agentgateway)
2. Direct Vertex AI Reasoning Engine (Baseline verification)

Payload format:
{
    "class_method": "async_stream_query",
    "input": {
        "user_id": "user-123",
        "message": "Weather of Fremont today?"
    }
}
"""

import argparse
import json
import ssl
import subprocess
import sys
import time
import urllib.request
import urllib.error


def get_gcp_access_token():
    """Retrieve OAuth2 access token from gcloud."""
    try:
        token = subprocess.check_output(
            ["gcloud", "auth", "print-access-token"],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        return token
    except Exception as e:
        print(f"[WARN] Could not retrieve gcloud access token: {e}")
        return "mock-unauthenticated-token"


def test_direct_vertex_ai(project_id: str, region: str, engine_id: str, payload: dict, token: str):
    """Direct baseline call to Vertex AI Reasoning Engine."""
    url = f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{region}/reasoningEngines/{engine_id}:streamQuery"
    print("\n" + "=" * 80)
    print(" [1] DIRECT VERTEX AI REASONING ENGINE TEST (Baseline)")
    print(f" URL    : {url}")
    print(f" Payload: {json.dumps(payload, indent=2)}")
    print("=" * 80)

    data_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url=url,
        data=data_bytes,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "Direct-TestClient/1.0",
        },
        method="POST"
    )

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    start_time = time.time()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=45) as resp:
            elapsed = time.time() - start_time
            body = resp.read().decode("utf-8")
            print(f"<--- Direct Backend Response Received ({elapsed:.3f}s):")
            print(f"     Status: {resp.getcode()} OK")
            print(f"     Body  :\n{body.strip()}")
            return True
    except Exception as e:
        print(f"<--- Direct Backend Error: {e}")
        return False


def test_agent_gateway(ip: str, host: str, endpoint: str, payload: dict, token: str):
    """Test query through the Two-Tier Ingress Agent Gateway."""
    url = f"https://{ip}{endpoint}"
    print("\n" + "=" * 80)
    print(" [2] TWO-TIER INGRESS AGENT GATEWAY TEST")
    print(f" Gateway URL: {url} (Host: {host})")
    print(f" Payload    : {json.dumps(payload, indent=2)}")
    print("=" * 80)

    data_bytes = json.dumps(payload).encode("utf-8")
    headers = {
        "Host": host,
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "x-agent-id": "gw-ingress-test",
        "x-agent-tool-name": "weather_service",
        "x-request-id": f"req-test-{int(time.time())}",
        "User-Agent": "TwoTier-AgentGateway-Client/1.0",
    }

    # Disable SSL host verification for self-signed cert on test IP
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    start_time = time.time()
    req = urllib.request.Request(url=url, data=data_bytes, headers=headers, method="POST")

    try:
        with urllib.request.urlopen(req, context=ctx, timeout=45) as resp:
            elapsed = time.time() - start_time
            body = resp.read().decode("utf-8")
            print(f"<--- Gateway Response Received ({elapsed:.3f}s):")
            print(f"     Status: {resp.getcode()} OK")
            print(f"     Body  :\n{body.strip()}")
            return True
    except urllib.error.HTTPError as e:
        elapsed = time.time() - start_time
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"<--- Gateway HTTP Error ({elapsed:.3f}s): Status {e.code} {e.reason}")
        print(f"     Body: {error_body.strip()}")
        return False
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"<--- Gateway Exception ({elapsed:.3f}s): {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Test query through Two-Tier Ingress Agent Gateway")
    parser.add_argument("--ip", default="107.178.242.66", help="Tier 1 Anycast Public IP")
    parser.add_argument("--host", default="agw-ingress.agentgateway", help="Host Header")
    parser.add_argument("--query", default="Weather of Fremont today?", help="Query text")
    parser.add_argument("--user-id", default="user-123", help="Caller User ID")
    parser.add_argument("--class-method", default="async_stream_query", help="Reasoning Engine class method")
    parser.add_argument("--project-id", default="622260204773", help="Agent project ID")
    parser.add_argument("--region", default="us-central1", help="Agent region")
    parser.add_argument("--engine-id", default="1231533837213761536", help="Reasoning Engine ID")

    args = parser.parse_args()

    payload = {
        "class_method": args.class_method,
        "input": {
            "user_id": args.user_id,
            "message": args.query
        }
    }

    token = get_gcp_access_token()

    # 1. Direct Vertex AI call
    test_direct_vertex_ai(
        project_id=args.project_id,
        region=args.region,
        engine_id=args.engine_id,
        payload=payload,
        token=token
    )

    # 2. Ingress Gateway call
    test_agent_gateway(
        ip=args.ip,
        host=args.host,
        endpoint="/streamQuery",
        payload=payload,
        token=token
    )


if __name__ == "__main__":
    main()
