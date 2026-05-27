# Kubernetes Port Forward Manager

Desktop utility (PyQt6) to manage multiple `kubectl port-forward` processes with health checks, auto-restart, profiles, and log viewing.

## Features

- Manage multiple Kubernetes port-forwards from a single UI
- Start/stop forwards individually or as saved profiles
- Health checks per service
  - HTTP/HTTPS (`http` or `https`)
  - **gRPC** (via `grpc.health.v1.Health/Check`)
- Automatic restart after repeated health check failures
- Rotating log file output with an integrated log viewer
- System tray support (minimize-to-tray behavior)

## Requirements

- Windows 10/11 (primary target)
- Python 3.11+
- `kubectl` available on `PATH`
- Access to a Kubernetes cluster and valid kubeconfig

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

**Note:** If using gRPC health checks, ensure `grpcio` and `grpcio-health-checking` are installed (already included in `requirements.txt`).

## Run

### Default config location

```bash
python -m src.main
```

The default config path is:

`%APPDATA%\portforward\config.yaml`

### Custom config path

```bash
python -m src.main path\to\config.yaml
```

## Configuration

Use `config/example-config.yaml` as a starting point.

Each forward entry supports:

- `name`: display name
- `resource`: Kubernetes target, e.g. `deployment/my-service` or `pod/my-pod`
- `local_port`: local port on your machine
- `remote_port`: remote port in the cluster target
- `context` (optional): kube context passed to `kubectl`
- `health_check_path` (optional): HTTP path polled every 30s while running (e.g. `/health`)
- `health_check_grpc` (optional): `true` to enable gRPC health check (`grpc.health.v1.Health/Check`) instead of HTTP
- `health_check_tls` (optional): `true` for HTTPS/TLS (applies to both HTTP and gRPC health checks)

Example:

```yaml
forwards:
  # HTTP health check example
  - name: "landlord"
    resource: "deployment/landlord"
    local_port: 9543
    remote_port: 8443
    health_check_path: "/health/health"
    health_check_tls: true

  # gRPC health check example
  - name: "my-grpc-service"
    resource: "deployment/my-grpc-service"
    local_port: 5000
    remote_port: 50051
    health_check_grpc: true
    health_check_tls: false
```

## Logging

Logs are written to `./logs/portforward.log` by default, with rotation enabled.

See `LOGGING.md` for details about log format and behavior.

## Development

Quick validation:

```bash
python -m compileall src
```

GitHub Actions runs the same compilation check on push and pull requests to `main`.

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup details, expectations for pull requests, and how code review is assigned.

## License

This project is licensed under the terms of the MIT License. See `LICENSE`.
