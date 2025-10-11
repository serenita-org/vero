from prometheus_client import start_http_server


def setup_metrics(addr: str, port: int) -> None:
    start_http_server(addr=addr, port=port)
