#!/usr/bin/env python3
"""
Test script for the Global Application Load Balancer frontend.
Sends requests to the Load Balancer IP (34.110.158.115).
"""

import sys
import json
import asyncio
from pathlib import Path
import grpc
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

GENERATED_DIR = Path(__file__).parent.parent / "src" / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import envoy.service.auth.v3.external_auth_pb2 as external_auth_pb2
import envoy.service.auth.v3.external_auth_pb2_grpc as external_auth_pb2_grpc

LB_IP = "8.232.13.92"
AGENT_ID = "gw-ingress-test"

def test_lb_http():
    print(f"\n[1] Testing HTTPS connectivity to Load Balancer (https://{LB_IP}/)...")
    url = f"https://{LB_IP}/"
    headers = {
        "Host": "agw-ingress.agentgateway",
        "Authorization": "Bearer test-user-jwt",
        "x-agent-id": AGENT_ID,
        "x-agent-tenant-id": "tenant-corp-alpha"
    }
    res = requests.get(url, headers=headers, verify=False, timeout=10)
    print(f"-> Status Code: {res.status_code}")
    print(f"-> Headers: via={res.headers.get('via')}, server={res.headers.get('server')}")

async def test_lb_grpc_authz():
    print(f"\n[2] Testing Envoy ext_authz gRPC through Load Balancer IP ({LB_IP}:443)...")
    
    # Load the self-signed certificate data from Terraform state for TLS validation
    import subprocess
    cert_pem = None
    try:
        raw = subprocess.getoutput("terraform -chdir=terraform show -json")
        data = json.loads(raw)
        for r in data.get("values", {}).get("root_module", {}).get("resources", []):
            if r.get("type") == "tls_self_signed_cert":
                cert_pem = r.get("values", {}).get("cert_pem")
                break
    except Exception:
        pass

    if cert_pem:
        creds = grpc.ssl_channel_credentials(root_certificates=cert_pem.encode())
    else:
        creds = grpc.ssl_channel_credentials()

    options = [('grpc.ssl_target_name_override', 'agw-ingress.agentgateway')]
    channel = grpc.aio.secure_channel(f"{LB_IP}:443", creds, options=options)
    stub = external_auth_pb2_grpc.AuthorizationStub(channel)

    req = external_auth_pb2.CheckRequest()
    req.attributes.request.http.method = "POST"
    req.attributes.request.http.path = f"/v1/agents/{AGENT_ID}/tools/query/execute"
    req.attributes.request.http.host = "agw-ingress.agentgateway"
    req.attributes.request.http.headers["authorization"] = "Bearer test-jwt-token-alice"
    req.attributes.request.http.headers["x-agent-id"] = AGENT_ID
    req.attributes.request.http.headers["x-agent-tool-name"] = "query"
    req.attributes.request.http.headers["x-agent-tenant-id"] = "tenant-corp-alpha"
    req.attributes.context_extensions["tenant_id"] = "tenant-corp-alpha"
    req.attributes.context_extensions["dev.agentgateway.jwt"] = "alice@company.com"

    try:
        response = await stub.Check(req, timeout=10.0)
        print(f"-> Authz Check Response: Code {response.status.code} ({'ALLOWED' if response.status.code == 0 else 'DENIED'})")
        if response.status.code == 0:
            print("-> Injected Headers:")
            for h in response.ok_response.headers:
                print(f"   • {h.header.key}: {h.header.value}")
    except Exception as e:
        print(f"-> gRPC Check Note: {e}")
    finally:
        await channel.close()

async def main():
    print("=" * 65)
    print("Testing Ingress Application Load Balancer (GLB)")
    print(f"Public Static IP: {LB_IP}")
    print("=" * 65)
    test_lb_http()
    await test_lb_grpc_authz()
    print("\n" + "=" * 65)
    print("Load Balancer Validation Complete!")
    print("=" * 65)

if __name__ == "__main__":
    asyncio.run(main())
