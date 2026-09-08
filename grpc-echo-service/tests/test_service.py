import json
import pytest
import grpc
import sys
from pathlib import Path

sys.path.append(str((Path(__file__).parent.parent / "src").resolve()))
sys.path.append(str((Path(__file__).parent.parent / "src" / "generated").resolve()))

from generated import echo_pb2
from generated import echo_pb2_grpc
import envoy.service.ext_proc.v3.external_processor_pb2 as ext_proc_pb2
import envoy.type.v3.http_status_pb2 as http_status_pb2
import envoy.config.core.v3.base_pb2 as base_pb2

from server import EchoService, ExternalProcessor, contains_ssn


class MockContext:
    def __init__(self):
        self.code = None
        self.details = None
        self.trailing_metadata = None
        self.initial_metadata = None

    def set_trailing_metadata(self, metadata):
        self.trailing_metadata = metadata

    async def send_initial_metadata(self, metadata):
        self.initial_metadata = metadata

    async def abort(self, code, details):
        self.code = code
        self.details = details
        raise grpc.RpcError(details)


def test_contains_ssn():
    assert contains_ssn("My SSN is 123-45-6789") is True
    assert contains_ssn("ssn") is True
    assert contains_ssn("No sensitive data here") is False
    assert contains_ssn("") is False


@pytest.mark.asyncio
async def test_echo_success():
    servicer = EchoService()
    ctx = MockContext()
    req = echo_pb2.EchoRequest(message="Hello world")
    reply = await servicer.Echo(req, ctx)

    assert reply.message == "echo: Hello world"
    assert ctx.initial_metadata == (
        ("x-service-name", "grpc-echo-service"),
        ("x-echo-status", "allowed"),
    )


@pytest.mark.asyncio
async def test_echo_denied_ssn():
    servicer = EchoService()
    ctx = MockContext()
    req = echo_pb2.EchoRequest(message="Confidential SSN: 123-45-6789")

    with pytest.raises(grpc.RpcError) as exc_info:
        await servicer.Echo(req, ctx)

    assert "Access denied" in str(exc_info.value)
    assert ctx.code == grpc.StatusCode.PERMISSION_DENIED
    assert ctx.trailing_metadata == (
        ("x-denial-reason", "sensitive-data-ssn"),
        ("x-echo-status", "denied"),
    )


@pytest.mark.asyncio
async def test_ext_proc_blocks_ssn_header():
    servicer = ExternalProcessor()

    header = base_pb2.HeaderValue(key=b"x-user-ssn", value=b"000-00-0000")
    header_map = base_pb2.HeaderMap(headers=[header])
    req = ext_proc_pb2.ProcessingRequest(
        request_headers=ext_proc_pb2.HttpHeaders(headers=header_map)
    )

    async def request_stream():
        yield req

    responses = [resp async for resp in servicer.Process(request_stream(), None)]
    assert len(responses) == 1
    assert responses[0].HasField("immediate_response")
    assert responses[0].immediate_response.status.code == http_status_pb2.StatusCode.Forbidden
    assert "Access Denied" in responses[0].immediate_response.body


@pytest.mark.asyncio
async def test_ext_proc_modifies_response_body_json_dict():
    servicer = ExternalProcessor()

    req = ext_proc_pb2.ProcessingRequest(
        response_body=ext_proc_pb2.HttpBody(
            body=b'{"id":"session-123","appName":"app"}'
        )
    )

    async def request_stream():
        yield req

    responses = [resp async for resp in servicer.Process(request_stream(), None)]
    assert len(responses) == 1
    assert responses[0].HasField("response_body")
    mutated = json.loads(responses[0].response_body.response.body_mutation.body.decode("utf-8"))
    assert mutated["id"] == "session-123"
    assert mutated["echo_prefix"] == "echo: allowed"


@pytest.mark.asyncio
async def test_ext_proc_modifies_response_body_json_list():
    servicer = ExternalProcessor()

    req = ext_proc_pb2.ProcessingRequest(
        response_body=ext_proc_pb2.HttpBody(
            body=b'[{"content":{"parts":[{"text":"hello from agent"}]}}]'
        )
    )

    async def request_stream():
        yield req

    responses = [resp async for resp in servicer.Process(request_stream(), None)]
    assert len(responses) == 1
    assert responses[0].HasField("response_body")
    mutated = json.loads(responses[0].response_body.response.body_mutation.body.decode("utf-8"))
    assert mutated[0]["content"]["parts"][0]["text"] == "echo: hello from agent"


@pytest.mark.asyncio
async def test_ext_proc_modifies_response_body_plain_text():
    servicer = ExternalProcessor()

    req = ext_proc_pb2.ProcessingRequest(
        response_body=ext_proc_pb2.HttpBody(
            body=b'plain text response'
        )
    )

    async def request_stream():
        yield req

    responses = [resp async for resp in servicer.Process(request_stream(), None)]
    assert len(responses) == 1
    assert responses[0].HasField("response_body")
    assert responses[0].response_body.response.body_mutation.body == b'echo: plain text response'
