import asyncio
import struct
import logging
from typing import Callable, Optional

logger = logging.getLogger("ff.sni_proxy")

class SniProxy:
    def __init__(self, is_allowed_callback: Callable[[str], bool]):
        self.is_allowed_callback = is_allowed_callback
        self.server = None
        self._loop = None
        self._runner_task = None
        self._thread = None

    async def _start(self, host: str, port: int):
        self.server = await asyncio.start_server(self.handle_client, host, port)
        logger.info(f"SNI Proxy running on {host}:{port}")
        async with self.server:
            await self.server.serve_forever()

    def start_sync(self, host='127.0.0.1', port=8443):
        """Start the proxy server from a synchronous context (e.g. threading)."""
        if self._runner_task or self._loop:
            return

        def run_loop():
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            self._runner_task = self._loop.create_task(self._start(host, port))
            try:
                self._loop.run_forever()
            finally:
                self._loop.run_until_complete(self._loop.shutdown_asyncgens())
                self._loop.close()

        import threading
        self._thread = threading.Thread(target=run_loop, name="sni_proxy", daemon=True)
        self._thread.start()

    def stop_sync(self):
        """Stop the proxy server from a synchronous context."""
        if not self._loop:
            return
            
        async def _stop():
            if self.server:
                self.server.close()
                await self.server.wait_closed()
                logger.info("SNI Proxy stopped")
            if self._runner_task:
                self._runner_task.cancel()
        
        asyncio.run_coroutine_threadsafe(_stop(), self._loop)
        
        # Give it a moment to stop gracefully, then stop the loop
        self._loop.call_later(1.0, self._loop.stop)
        self._thread.join(timeout=2.0)
        
        self.server = None
        self._loop = None
        self._runner_task = None

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            # Read first chunk which should be TLS Client Hello
            data = await reader.read(4096)
            if not data:
                writer.close()
                return

            sni = self.extract_sni(data)
            if not sni:
                # No SNI or not TLS, reject in whitelist mode
                logger.warning("SNI Proxy: Connection rejected (No SNI found or invalid TLS)")
                writer.close()
                return

            if not self.is_allowed_callback(sni):
                logger.info(f"SNI Proxy: Connection rejected to {sni} (Not in whitelist)")
                writer.close()
                return

            logger.info(f"SNI Proxy: Allowing connection to {sni}")
            
            # Connect to actual destination
            try:
                # We resolve the SNI domain to its actual IP and connect on port 443
                remote_reader, remote_writer = await asyncio.wait_for(
                    asyncio.open_connection(sni, 443),
                    timeout=5.0
                )
            except Exception as e:
                logger.error(f"SNI Proxy: Failed to connect to {sni}: {e}")
                writer.close()
                return

            # Forward the initially read data (ClientHello)
            remote_writer.write(data)
            await remote_writer.drain()

            # Bidirectional forwarding
            await asyncio.gather(
                self.pipe(reader, remote_writer),
                self.pipe(remote_reader, writer)
            )

        except Exception as e:
            logger.debug(f"SNI Proxy handle error: {e}")
        finally:
            writer.close()

    async def pipe(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            while True:
                data = await reader.read(8192)
                if not data:
                    break
                writer.write(data)
                await writer.drain()
        except Exception:
            pass
        finally:
            writer.close()

    @staticmethod
    def extract_sni(data: bytes) -> Optional[str]:
        """Extract Server Name Indication (SNI) from TLS ClientHello."""
        try:
            # TLS record starts with 0x16 (Handshake)
            if data[0] != 0x16:
                return None
            
            # Record header is 5 bytes. Handshake type starts at offset 5.
            # ClientHello type is 1.
            if data[5] != 0x01:
                return None

            # Skip Record Header (5), Handshake Header (4), Client Version (2), Random (32)
            offset = 5 + 4 + 2 + 32
            
            # Session ID length
            session_id_len = data[offset]
            offset += 1 + session_id_len
            
            # Cipher Suites length
            cipher_suites_len = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2 + cipher_suites_len
            
            # Compression Methods length
            comp_methods_len = data[offset]
            offset += 1 + comp_methods_len
            
            # Extensions length
            extensions_len = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
            
            # Parse extensions
            end_of_extensions = offset + extensions_len
            while offset < end_of_extensions:
                ext_type = struct.unpack('>H', data[offset:offset+2])[0]
                ext_len = struct.unpack('>H', data[offset+2:offset+4])[0]
                offset += 4
                
                if ext_type == 0x0000:  # Server Name Extension
                    # SNI list length
                    list_len = struct.unpack('>H', data[offset:offset+2])[0]
                    sni_offset = offset + 2
                    
                    # Read names in the list
                    while sni_offset < offset + ext_len:
                        name_type = data[sni_offset]
                        name_len = struct.unpack('>H', data[sni_offset+1:sni_offset+3])[0]
                        if name_type == 0:  # HostName
                            sni = data[sni_offset+3 : sni_offset+3+name_len].decode('utf-8')
                            return sni
                        sni_offset += 3 + name_len
                
                offset += ext_len
        except Exception:
            return None
        return None
