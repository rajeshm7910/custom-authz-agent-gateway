#!/usr/bin/env python3
"""
Script to compile Envoy ext_authz & ext_proc protobuf definitions into Python gRPC code.
"""
import os
import sys
import importlib.resources
from pathlib import Path
from grpc_tools import protoc
import grpc_tools

PROJECT_ROOT = Path(__file__).parent.parent
PROTOS_DIR = PROJECT_ROOT / "protos"
OUT_DIR = PROJECT_ROOT / "src" / "generated"

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Ensure __init__.py files exist in generated subdirectories (excluding google namespace)
    for d in [OUT_DIR,
              OUT_DIR / "envoy", OUT_DIR / "envoy" / "type", OUT_DIR / "envoy" / "type" / "v3",
              OUT_DIR / "envoy" / "config", OUT_DIR / "envoy" / "config" / "core", OUT_DIR / "envoy" / "config" / "core" / "v3",
              OUT_DIR / "envoy" / "service", OUT_DIR / "envoy" / "service" / "auth", OUT_DIR / "envoy" / "service" / "auth" / "v3",
              OUT_DIR / "envoy" / "service" / "ext_proc", OUT_DIR / "envoy" / "service" / "ext_proc" / "v3"]:
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").touch()

    proto_files = [
        str(PROTOS_DIR / "google" / "rpc" / "status.proto"),
        str(PROTOS_DIR / "envoy" / "type" / "v3" / "http_status.proto"),
        str(PROTOS_DIR / "envoy" / "config" / "core" / "v3" / "base.proto"),
        str(PROTOS_DIR / "envoy" / "service" / "auth" / "v3" / "external_auth.proto"),
        str(PROTOS_DIR / "envoy" / "service" / "ext_proc" / "v3" / "external_processor.proto"),
    ]

    include_path = str(importlib.resources.files(grpc_tools).joinpath("_proto"))

    args = [
        "protoc",
        f"-I{PROTOS_DIR}",
        f"-I{include_path}",
        f"--python_out={OUT_DIR}",
        f"--grpc_python_out={OUT_DIR}",
    ] + proto_files

    print(f"Compiling protos with include path: {include_path}")
    res = protoc.main(args)
    if res != 0:
        print(f"Error compiling protos: exit code {res}", file=sys.stderr)
        sys.exit(res)
    print("Successfully compiled protobuf files!")

if __name__ == "__main__":
    main()
