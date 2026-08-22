#!/usr/bin/env python3
"""Минимальный CONNECT-прокси для docker-контейнеров в корпоративной сети.

Зачем: хост ходит во внутренний Confluence через VPN-туннель (utun), а трафик
Docker VM идёт мимо туннеля и получает публичный сертификат mts.ru вместо
сертификата confluence.mts.ru (hostname mismatch). Backend в контейнере
направляется на этот прокси через HTTPS_PROXY=http://host.docker.internal:3128
— httpx сам подхватывает переменную. Прокси устанавливает соединения FROM
хоста, поэтому проходит по VPN-маршруту и получает настоящий сертификат;
TLS при этом сквозной (CONNECT-туннель), проверка сертификатов не ослабляется.

Ограничения безопасности: только метод CONNECT, только порт 443 — прокси
нельзя использовать как открытый ретранслятор произвольного трафика.

Запуск:  python3 tools/connect_proxy.py [--bind 127.0.0.1] [--port 3128]
Только stdlib, без зависимостей.
"""

from __future__ import annotations

import argparse
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("connect-proxy")

ALLOWED_PORT = 443
BUF = 65536


async def _pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await reader.read(BUF)
            if not data:
                break
            writer.write(data)
            await writer.drain()
    except ConnectionError:
        pass
    finally:
        try:
            writer.close()
        except Exception:
            pass


async def _handle(client_reader, client_writer) -> None:
    peer = client_writer.get_extra_info("peername")
    try:
        line = await asyncio.wait_for(client_reader.readline(), timeout=30)
        parts = line.decode("latin-1", "replace").split()
        if len(parts) != 3 or parts[0].upper() != "CONNECT":
            client_writer.write(b"HTTP/1.1 405 Only CONNECT is allowed\r\n\r\n")
            await client_writer.drain()
            return
        host, _, port = parts[1].rpartition(":")
        if not port.isdigit() or int(port) != ALLOWED_PORT or not host:
            client_writer.write(
                f"HTTP/1.1 403 Only :{ALLOWED_PORT} is allowed\r\n\r\n".encode()
            )
            await client_writer.drain()
            return
        # дочитываем заголовки запроса
        while True:
            header = await asyncio.wait_for(client_reader.readline(), timeout=10)
            if header in (b"\r\n", b"\n", b""):
                break

        upstream_reader, upstream_writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port)), timeout=15
        )
        logger.info("%s -> %s", peer, parts[1])
    except (asyncio.TimeoutError, OSError) as exc:
        logger.warning("%s: %s", peer, exc)
        client_writer.write(b"HTTP/1.1 502 Upstream unavailable\r\n\r\n")
        await client_writer.drain()
        return

    client_writer.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
    await client_writer.drain()
    await asyncio.gather(
        _pipe(client_reader, upstream_writer),
        _pipe(upstream_reader, client_writer),
        return_exceptions=True,
    )


async def main(bind: str, port: int) -> None:
    server = await asyncio.start_server(_handle, bind, port)
    logger.info("CONNECT-прокси слушает %s:%d (только порт %d)", bind, port, ALLOWED_PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=3128)
    args = parser.parse_args()
    try:
        asyncio.run(main(args.bind, args.port))
    except KeyboardInterrupt:
        pass
