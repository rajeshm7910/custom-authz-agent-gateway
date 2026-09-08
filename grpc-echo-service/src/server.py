import asyncio
import logging
import os
import sys
from pathlib import Path
import grpc

# Add src and generated directories to sys.path for nested Envoy imports
sys.path.append(str(Path(__file__).parent.resolve()))
sys.path.append(str((Path(__file__).parent / "generated").resolve()))

from generated import echo_pb2
from generated import echo_pb2_grpc

import envoy.service.ext_proc.v3.external_processor_pb2 as ext_proc_pb2
import envoy.service.ext_proc.v3.external_processor_pb2_grpc as ext_proc_pb2_grpc
import envoy.extensions.filters.http.ext_proc.v3.processing_mode_pb2 as processing_mode_pb2
import envoy.type.v3.http_status_pb2 as http_status_pb2
import envoy.config.core.v3.base_pb2 as base_pb2


def contains_ssn(text: str) -> bool:
    """Check if text contains the word 'ssn' (case-insensitive)."""
    return "ssn" in str(text or "").lower()


def extract_headers_dict(http_headers) -> dict:
    """Extract key-value pairs from envoy HttpHeaders."""
    headers_dict = {}
    if hasattr(http_headers, "headers"):
        h_obj = http_headers.headers
        header_list = h_obj.headers if hasattr(h_obj, "headers") else h_obj
        for h in header_list:
            k = h.key.decode("utf-8", errors="ignore") if isinstance(h.key, bytes) else str(h.key or "")
            k = k.lower()
            v = h.value.decode("utf-8", errors="ignore") if isinstance(h.value, bytes) else str(h.value or "")
            if not v and hasattr(h, "raw_value") and h.raw_value:
                v = h.raw_value.decode("utf-8", errors="ignore") if isinstance(h.raw_value, bytes) else str(h.raw_value)
            headers_dict[k] = v
    return headers_dict


class EchoService(echo_pb2_grpc.EchoServiceServicer):
    """
    gRPC Echo Service:
    - Denies request if 'ssn' is found in the message.
    - Otherwise echoes back the input message prefixed with 'echo: '.
    """
    async def Echo(self, request, context):
        msg = request.message
        logging.info("EchoService received message: '%s'", msg)

        if contains_ssn(msg):
            logging.warning("EchoService: Denying request because message contains restricted keyword 'ssn'")
            context.set_trailing_metadata((
                ("x-denial-reason", "sensitive-data-ssn"),
                ("x-echo-status", "denied"),
            ))
            await context.abort(
                grpc.StatusCode.PERMISSION_DENIED,
                "Access denied: request payload contains restricted keyword (SSN)."
            )

        # Send response headers (initial metadata)
        await context.send_initial_metadata((
            ("x-service-name", "grpc-echo-service"),
            ("x-echo-status", "allowed"),
        ))

        # Prefix response with 'echo: '
        echo_response = f"echo: {msg}"
        logging.info("EchoService responding: '%s'", echo_response)
        return echo_pb2.EchoReply(message=echo_response)


class ExternalProcessor(ext_proc_pb2_grpc.ExternalProcessorServicer):
    """
    Envoy ext_proc (External Processing) Servicer using asyncio.
    - Inspects request headers and request body for the word 'ssn' (case-insensitive).
    - Blocks with HTTP 403 Forbidden ImmediateResponse if 'ssn' is detected.
    - Echoes / allows clean traffic and modifies the response body with 'echo: ' prefix.
    """
    async def Process(self, request_iterator, context):
        try:
            async for request in request_iterator:
                req_type = request.WhichOneof("request")
                logging.info("ext_proc: Received incoming request type: %s", req_type)

                # --- 1. INSPECT REQUEST HEADERS ---
                if req_type == "request_headers":
                    http_headers = request.request_headers
                    headers_dict = extract_headers_dict(http_headers)
                    logging.info("ext_proc: Received request headers (count=%d): %s", len(headers_dict), headers_dict)

                    deny = False
                    for k, v in headers_dict.items():
                        if contains_ssn(k) or contains_ssn(v):
                            logging.warning("ext_proc: Blocking request - Found 'ssn' in header '%s: %s'", k, v)
                            deny = True
                            break

                    if deny:
                        yield ext_proc_pb2.ProcessingResponse(
                            immediate_response=ext_proc_pb2.ImmediateResponse(
                                status=http_status_pb2.HttpStatus(code=http_status_pb2.StatusCode.Forbidden),
                                body="Access Denied: Request headers contain restricted keyword (SSN).",
                                details="Restricted keyword 'ssn' detected in headers"
                            )
                        )
                        return

                    # Allow clean headers through and instruct Envoy to stream buffered request and response bodies
                    yield ext_proc_pb2.ProcessingResponse(
                        request_headers=ext_proc_pb2.HeadersResponse(
                            response=ext_proc_pb2.CommonResponse(
                                header_mutation=ext_proc_pb2.HeaderMutation()
                            )
                        ),
                        mode_override=processing_mode_pb2.ProcessingMode(
                            request_body_mode=processing_mode_pb2.ProcessingMode.BUFFERED,
                            response_body_mode=processing_mode_pb2.ProcessingMode.BUFFERED,
                        )
                    )

                # --- 2. INSPECT REQUEST BODY ---
                elif req_type == "request_body":
                    http_body = request.request_body
                    body_text = http_body.body.decode("utf-8", errors="ignore") if http_body.body else ""
                    logging.info("ext_proc: Received request body payload: '%s'", body_text)

                    if contains_ssn(body_text):
                        logging.warning("ext_proc: Blocking request - Found 'ssn' in Body")
                        yield ext_proc_pb2.ProcessingResponse(
                            immediate_response=ext_proc_pb2.ImmediateResponse(
                                status=http_status_pb2.HttpStatus(code=http_status_pb2.StatusCode.Forbidden),
                                body="Access Denied: Request payload contains restricted keyword (SSN).",
                                details="Restricted keyword 'ssn' detected in body"
                            )
                        )
                        return

                    logging.info("ext_proc: Body check passed. Allowing payload through.")
                    yield ext_proc_pb2.ProcessingResponse(
                        request_body=ext_proc_pb2.BodyResponse(
                            response=ext_proc_pb2.CommonResponse()
                        )
                    )

                # --- 3. PROCESS RESPONSE HEADERS ---
                elif req_type == "response_headers":
                    logging.info("ext_proc: Received response headers. Allowing through.")
                    yield ext_proc_pb2.ProcessingResponse(
                        response_headers=ext_proc_pb2.HeadersResponse(
                            response=ext_proc_pb2.CommonResponse(
                                header_mutation=ext_proc_pb2.HeaderMutation(
                                    set_headers=[
                                        base_pb2.HeaderValueOption(
                                            header=base_pb2.HeaderValue(
                                                key=b"x-echo-processed",
                                                value=b"true",
                                                raw_value=b"true"
                                            )
                                        )
                                    ]
                                )
                            )
                        )
                    )

                # --- 4. MODIFY RESPONSE BODY (ECHO PREFIX) ---
                elif req_type == "response_body":
                    http_body = request.response_body
                    resp_body_text = http_body.body.decode("utf-8", errors="ignore") if http_body.body else ""
                    logging.info("ext_proc: Received response body (len=%d): '%s'.", len(resp_body_text), resp_body_text)

                    # If empty body chunk (e.g. EOF frame), do not mutate
                    if not resp_body_text:
                        yield ext_proc_pb2.ProcessingResponse(
                            response_body=ext_proc_pb2.BodyResponse(
                                response=ext_proc_pb2.CommonResponse()
                            )
                        )
                        continue

                    # If response is JSON, modify JSON content while preserving valid JSON syntax
                    modified_bytes = None
                    trimmed = resp_body_text.strip()
                    if trimmed.startswith(("{", "[")):
                        try:
                            import json
                            data = json.loads(trimmed)
                            if isinstance(data, dict):
                                data["echo_prefix"] = "echo: allowed"
                                modified_bytes = json.dumps(data).encode("utf-8")
                            elif isinstance(data, list):
                                for item in data:
                                    if isinstance(item, dict) and "content" in item:
                                        content = item.get("content", {})
                                        if isinstance(content, dict) and "parts" in content:
                                            for part in content.get("parts", []):
                                                if isinstance(part, dict) and "text" in part:
                                                    part["text"] = f"echo: {part['text']}"
                                modified_bytes = json.dumps(data).encode("utf-8")
                        except Exception as json_err:
                            logging.warning("ext_proc: Failed to parse JSON response body: %s", str(json_err))

                    if modified_bytes is None:
                        modified_bytes = f"echo: {resp_body_text}".encode("utf-8")

                    yield ext_proc_pb2.ProcessingResponse(
                        response_body=ext_proc_pb2.BodyResponse(
                            response=ext_proc_pb2.CommonResponse(
                                body_mutation=ext_proc_pb2.BodyMutation(
                                    body=modified_bytes
                                )
                            )
                        )
                    )

                else:
                    # Default pass-through for any other event
                    yield ext_proc_pb2.ProcessingResponse()

        except Exception as e:
            logging.exception("Error during ext_proc Process execution: %s", str(e))
            yield ext_proc_pb2.ProcessingResponse()


async def serve(port: int = 8080):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    port_num = os.environ.get("PORT", str(port))
    server_address = f"[::]:{port_num}"

    server = grpc.aio.server()
    echo_pb2_grpc.add_EchoServiceServicer_to_server(EchoService(), server)
    ext_proc_pb2_grpc.add_ExternalProcessorServicer_to_server(ExternalProcessor(), server)

    server.add_insecure_port(server_address)
    logging.info("Starting Async gRPC Echo and ext_proc server on %s", server_address)
    await server.start()
    await server.wait_for_termination()


if __name__ == "__main__":
    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received. Stopping server gracefully...")
