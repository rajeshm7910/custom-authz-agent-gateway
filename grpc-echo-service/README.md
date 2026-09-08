# gRPC Echo & Envoy ext_proc Service with Sensitive Data (SSN) Denial

This service provides a gRPC and Envoy `ext_proc` (Service Extension) implementation that:
1. **Denies requests containing the word `ssn`** (case-insensitive) anywhere in the message payload, HTTP headers, or request body.
2. **Echoes everything else** with an `echo: ` prefix in the response.

---

## Features

- **Sensitive Data Denial**:
  - Direct gRPC `EchoService.Echo`: returns `grpc.StatusCode.PERMISSION_DENIED` with an explicit denial error message if `ssn` is detected.
  - Envoy `ext_proc` (`ExternalProcessor.Process`): inspects `request_headers` and `request_body`, returning an `ImmediateResponse` with HTTP `403 Forbidden` if `ssn` is detected.
- **Echo & Response Modification**:
  - Direct gRPC `EchoService.Echo`: prepends `echo: ` to the response message.
  - Envoy `ext_proc`: allows clean requests through to the backend, and mutates `response_body` with `echo: ` prefix using `BodyMutation`.

---

## Directory Structure

```
grpc-echo-service/
├── protos/
│   ├── echo.proto                       # EchoService protobuf definition
│   └── envoy/                           # Envoy ext_proc protobuf definitions
├── src/
│   ├── __init__.py
│   ├── server.py                        # gRPC Echo & ext_proc server
│   ├── client.py                        # gRPC test client (prints HTTP/2 headers & payload)
│   └── generated/                       # Generated gRPC code
├── terraform/
│   ├── main.tf                          # Provisions Cloud Run + ALB + google_network_services_lb_traffic_extension
│   ├── variables.tf                     # Project ID & Region variables
│   └── outputs.tf                       # Output URLs & Load Balancer IP
├── tests/
│   └── test_service.py                  # Pytest unit test suite
├── compile_protos.py                    # Script to compile protobufs
├── deploy-traffic-extension.sh          # One-click deployment script
├── Dockerfile                           # Container definition
├── pyproject.toml                       # Package configuration
├── requirements.txt                     # Dependencies
└── README.md                            # Documentation
```

---

## Local Setup & Testing

### 1. Compile Protos
```bash
python3 compile_protos.py
```

### 2. Run Unit Tests
```bash
python3 -m pytest tests/test_service.py -v
```

### 3. Run the Server Locally
```bash
python3 src/server.py
```

### 4. Test with Client
```bash
# Allowed call
python3 src/client.py "Hello World"

# Denied call (contains SSN)
python3 src/client.py "My SSN is 123-45-6789"
```

---

## Deploying as a GCP Service Extensions Traffic Extension

You can deploy this service to Google Cloud Run and attach it as an Envoy `ext_proc` **LB Traffic Extension** to an Application Load Balancer.

### Automated Deployment
Run the deployment script:
```bash
./deploy-traffic-extension.sh
```

### What this provisions:
1. **Cloud Run Container**: Hosts the gRPC `ext_proc` service over HTTP/2.
2. **Serverless NEG & Backend Service**: Registered as an `EXTERNAL_MANAGED` HTTP2 backend.
3. **Global Application Load Balancer**: Anycast IP with TLS termination.
4. **`google_network_services_lb_traffic_extension`**: Attaches to the Forwarding Rule with events:
   - `REQUEST_HEADERS` (scans for `ssn`)
   - `REQUEST_BODY` (scans for `ssn`)
   - `RESPONSE_BODY` (prepends `echo: ` to the upstream response)
