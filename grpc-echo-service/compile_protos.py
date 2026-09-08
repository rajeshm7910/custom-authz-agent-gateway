#!/usr/bin/env python3
"""
Script to compile echo.proto and Envoy ext_proc protobuf definitions into Python gRPC code.
"""
import os
import re
import sys
import importlib.resources
from pathlib import Path
from grpc_tools import protoc
import grpc_tools

PROJECT_ROOT = Path(__file__).parent.resolve()
PROTOS_DIR = PROJECT_ROOT / "protos"
OUT_DIR = PROJECT_ROOT / "src" / "generated"

def main():
    print(f"Creating output directories in: {OUT_DIR}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # Touch __init__.py files to make packages
    (PROJECT_ROOT / "src" / "__init__.py").touch()
    
    # Ensure __init__.py files exist in generated subdirectories (excluding google namespace)
    for d in [OUT_DIR,
              OUT_DIR / "envoy", OUT_DIR / "envoy" / "type", OUT_DIR / "envoy" / "type" / "v3",
              OUT_DIR / "envoy" / "config", OUT_DIR / "envoy" / "config" / "core", OUT_DIR / "envoy" / "config" / "core" / "v3",
              OUT_DIR / "envoy" / "service", OUT_DIR / "envoy" / "service" / "auth", OUT_DIR / "envoy" / "service" / "auth" / "v3",
              OUT_DIR / "envoy" / "service" / "ext_proc", OUT_DIR / "envoy" / "service" / "ext_proc" / "v3",
              OUT_DIR / "envoy" / "extensions", OUT_DIR / "envoy" / "extensions" / "filters",
              OUT_DIR / "envoy" / "extensions" / "filters" / "http", OUT_DIR / "envoy" / "extensions" / "filters" / "http" / "ext_proc",
              OUT_DIR / "envoy" / "extensions" / "filters" / "http" / "ext_proc" / "v3"]:
        d.mkdir(parents=True, exist_ok=True)
        (d / "__init__.py").touch()

    proto_files = [
        str(PROTOS_DIR / "echo.proto"),
        str(PROTOS_DIR / "google" / "rpc" / "status.proto"),
        str(PROTOS_DIR / "envoy" / "type" / "v3" / "http_status.proto"),
        str(PROTOS_DIR / "envoy" / "config" / "core" / "v3" / "base.proto"),
        str(PROTOS_DIR / "envoy" / "extensions" / "filters" / "http" / "ext_proc" / "v3" / "processing_mode.proto"),
        str(PROTOS_DIR / "envoy" / "service" / "auth" / "v3" / "external_auth.proto"),
        str(PROTOS_DIR / "envoy" / "service" / "ext_proc" / "v3" / "external_processor.proto"),
    ]

    for f in proto_files:
        if not Path(f).exists():
            print(f"Error: proto file not found at {f}", file=sys.stderr)
            sys.exit(1)

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

    # Fix the imports in the generated files to support relative imports
    print("Fixing imports in generated gRPC code for package consistency...")
    generated_files = list(OUT_DIR.glob("*.py"))
    for file_path in generated_files:
        if file_path.name == "__init__.py":
            continue
        content = file_path.read_text(encoding="utf-8")
        # Replace 'import echo_pb2' with 'from . import echo_pb2'
        fixed_content = re.sub(
            r"^import\s+(echo_pb2\s+as\s+echo__pb2)",
            r"from . import \1",
            content,
            flags=re.MULTILINE
        )
        if fixed_content != content:
            file_path.write_text(fixed_content, encoding="utf-8")
            print(f"Patched relative import in {file_path.name}")

    print("Proto compilation and post-processing completed successfully!")

if __name__ == "__main__":
    main()
