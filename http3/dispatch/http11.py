import typing

import h11

from ..config import DEFAULT_TIMEOUT_CONFIG, TimeoutConfig, TimeoutTypes
from ..exceptions import ConnectTimeout, ReadTimeout
from ..interfaces import BaseReader, BaseWriter
from ..models import AsyncRequest, AsyncResponse

H11Event = typing.Union[
    h11.Request,
    h11.Response,
    h11.InformationalResponse,
    h11.Data,
    h11.EndOfMessage,
    h11.ConnectionClosed,
]


# Callback signature: async def callback() -> None
# In practice the callback will be a functools partial, which binds
# the `ConnectionPool.release_connection(conn: HTTPConnection)` method.
OnReleaseCallback = typing.Callable[[], typing.Awaitable[None]]


class HTTP11Connection:
    READ_NUM_BYTES = 4096

    def __init__(
        self,
        reader: BaseReader,
        writer: BaseWriter,
        on_release: typing.Optional[OnReleaseCallback] = None,
    ):
        self.reader = reader
        self.writer = writer
        self.on_release = on_release
        self.h11_state = h11.Connection(our_role=h11.CLIENT)

    async def send(
        self, request: AsyncRequest, timeout: TimeoutTypes = None
    ) -> AsyncResponse:
        timeout = None if timeout is None else TimeoutConfig(timeout)

        #  Start sending the request.
        method = request.method.encode("ascii")
        target = request.url.full_path.encode("ascii")
        headers = request.headers.raw
        if "Host" not in request.headers:
            host = request.url.authority.encode("ascii")
            headers = [(b"host", host)] + headers
        event = h11.Request(method=method, target=target, headers=headers)
        await self._send_event(event, timeout)

        # Send the request body.
        async for data in request.stream():
            event = h11.Data(data=data)
            await self._send_event(event, timeout)

        # Finalize sending the request.
        event = h11.EndOfMessage()
        await self._send_event(event, timeout)

        # Start getting the response.
        event = await self._receive_event(timeout)
        if isinstance(event, h11.InformationalResponse):
            event = await self._receive_event(timeout)

        assert isinstance(event, h11.Response)
        status_code = event.status_code
        headers = event.headers
        content = self._body_iter(timeout)

        return AsyncResponse(
            status_code=status_code,
            protocol="HTTP/1.1",
            headers=headers,
            content=content,
            on_close=self.response_closed,
            request=request,
        )

    async def close(self) -> None:
        event = h11.ConnectionClosed()
        self.h11_state.send(event)
        await self.writer.close()

    async def _body_iter(
        self, timeout: TimeoutConfig = None
    ) -> typing.AsyncIterator[bytes]:
        event = await self._receive_event(timeout)
        while isinstance(event, h11.Data):
            yield event.data
            event = await self._receive_event(timeout)
        assert isinstance(event, h11.EndOfMessage)

    async def _send_event(self, event: H11Event, timeout: TimeoutConfig = None) -> None:
        data = self.h11_state.send(event)
        await self.writer.write(data, timeout)

    async def _receive_event(self, timeout: TimeoutConfig = None) -> H11Event:
        event = self.h11_state.next_event()

        while event is h11.NEED_DATA:
            data = await self.reader.read(self.READ_NUM_BYTES, timeout)
            self.h11_state.receive_data(data)
            event = self.h11_state.next_event()

        return event

    async def response_closed(self) -> None:
        if (
            self.h11_state.our_state is h11.DONE
            and self.h11_state.their_state is h11.DONE
        ):
            self.h11_state.start_next_cycle()
        else:
            await self.close()

        if self.on_release is not None:
            await self.on_release()

    @property
    def is_closed(self) -> bool:
        return self.h11_state.our_state in (h11.CLOSED, h11.ERROR)
