import asyncio
import os
import signal
import sys
from pathlib import Path
import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc
import structlog

# Add generated directory to python path
GENERATED_DIR = Path(__file__).parent / "generated"
if str(GENERATED_DIR) not in sys.path:
    sys.path.insert(0, str(GENERATED_DIR))

import envoy.service.auth.v3.external_auth_pb2_grpc as external_auth_pb2_grpc
import envoy.service.ext_proc.v3.external_processor_pb2_grpc as ext_proc_pb2_grpc
from src.authz_service import ExternalAuthzService
from src.ext_proc_service import ExternalProcessorService
from src.config import settings
from src.health_server import start_http_server

logger = structlog.get_logger(__name__)


async def serve():
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass

    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.add_log_level,
            structlog.processors.JSONRenderer()
        ]
    )

    # gRPC port is assigned via PORT env var (or defaults to PORT config)
    server_port = settings.PORT

    # 1. Start gRPC Server
    grpc_server = grpc.aio.server()

    # Register ext_proc (for Global External ALB Service Extensions)
    ext_proc_service = ExternalProcessorService()
    ext_proc_pb2_grpc.add_ExternalProcessorServicer_to_server(ext_proc_service, grpc_server)

    # Register ext_authz (for Regional Internal ALB / direct authorization checks)
    authz_service = ExternalAuthzService()
    external_auth_pb2_grpc.add_AuthorizationServicer_to_server(authz_service, grpc_server)

    # Register standard gRPC health checking servicer for Cloud Run probes
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, grpc_server)
    health_servicer.set("", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set("envoy.service.ext_proc.v3.ExternalProcessor", health_pb2.HealthCheckResponse.SERVING)
    health_servicer.set("envoy.service.auth.v3.Authorization", health_pb2.HealthCheckResponse.SERVING)

    grpc_server.add_insecure_port(f"0.0.0.0:{server_port}")
    await grpc_server.start()
    logger.info("Envoy ext_proc & ext_authz gRPC Server running on PORT", port=server_port)

    # 2. Start HTTP Gateway and health server
    http_runner = None
    try:
        http_runner = await start_http_server(host="0.0.0.0", port=settings.HEALTH_PORT)
    except Exception as e:
        logger.warning("Auxiliary HTTP server skipped", error=str(e))

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _shutdown():
        logger.info("Shutdown signal received. Initiating graceful shutdown...")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    await stop_event.wait()
    logger.info("Stopping servers...")

    if http_runner:
        await http_runner.cleanup()
    await grpc_server.stop(grace=5.0)
    logger.info("Shutdown complete cleanly.")


if __name__ == "__main__":
    asyncio.run(serve())
