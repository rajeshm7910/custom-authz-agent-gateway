import argparse
import logging
import sys
import grpc

from pathlib import Path
sys.path.append(str(Path(__file__).parent.resolve()))
sys.path.append(str((Path(__file__).parent / "generated").resolve()))

from generated import echo_pb2
from generated import echo_pb2_grpc


def print_metadata(title: str, metadata):
    print(f"--- {title} ---")
    if metadata:
        for key, value in metadata:
            print(f"  {key}: {value}")
    else:
        print("  (No headers / metadata received)")


def run(server_address: str, message: str, deny: bool = False):
    # Determine channel security based on URL scheme or address
    is_secure = False

    if server_address.startswith("https://"):
        is_secure = True
        server_address = server_address[len("https://"):]
        if ":" not in server_address:
            server_address = f"{server_address}:443"
    elif server_address.startswith("http://"):
        server_address = server_address[len("http://"):]

    logging.info("Connecting to gRPC Echo server at %s (Secure: %s)", server_address, is_secure)

    create_channel = grpc.secure_channel if is_secure else grpc.insecure_channel
    credentials = grpc.ssl_channel_credentials() if is_secure else None
    channel_args = (server_address, credentials) if is_secure else (server_address,)

    # If deny flag is set, inject 'ssn' into the message to trigger denial
    if deny and "ssn" not in message.lower():
        message = f"{message} (with SSN: 123-45-6789)"
        logging.info("Deny flag set. Injected SSN into request message: '%s'", message)

    with create_channel(*channel_args) as channel:
        stub = echo_pb2_grpc.EchoServiceStub(channel)
        logging.info("Calling EchoService.Echo with message: '%s'", message)
        
        try:
            # Use .with_call() to capture response alongside HTTP/2 headers (metadata)
            response, call = stub.Echo.with_call(echo_pb2.EchoRequest(message=message))
            
            print("\n" + "=" * 60)
            print("HTTP / gRPC Response Details")
            print("=" * 60)
            print_metadata("HTTP Response Headers (Initial Metadata)", call.initial_metadata())
            print_metadata("HTTP Response Trailing Metadata", call.trailing_metadata())
            print("--- Response Body / Payload ---")
            print(f"  message: {response.message}")
            print("=" * 60 + "\n")
            
        except grpc.RpcError as e:
            print("\n" + "=" * 60)
            print("gRPC Request Failed / Denied")
            print("=" * 60)
            print(f"  Status Code : {e.code()}")
            print(f"  Details     : {e.details()}")
            print_metadata(
                "HTTP Response Headers (Initial Metadata)",
                e.initial_metadata() if hasattr(e, "initial_metadata") else None
            )
            print_metadata(
                "HTTP Response Trailing Metadata",
                e.trailing_metadata() if hasattr(e, "trailing_metadata") else None
            )
            print("=" * 60 + "\n")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    parser = argparse.ArgumentParser(description="gRPC Client for Echo Service.")
    parser.add_argument(
        "message",
        type=str,
        nargs="?",
        default="Hello Antigravity",
        help="The message to send to the gRPC Echo server (default: 'Hello Antigravity')"
    )
    parser.add_argument(
        "--server",
        type=str,
        default="localhost:50051",
        help="The server address (e.g. localhost:50051 or https://my-service-xxxxx.run.app)"
    )
    parser.add_argument(
        "--deny",
        action="store_true",
        help="Simulate request denial by injecting 'SSN' into the request payload"
    )
    args = parser.parse_args()

    run(args.server, args.message, deny=args.deny)
