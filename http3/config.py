import asyncio
import os
import ssl
import typing

import certifi

CertTypes = typing.Union[str, typing.Tuple[str, str]]
VerifyTypes = typing.Union[str, bool]
TimeoutTypes = typing.Union[float, typing.Tuple[float, float, float], "TimeoutConfig"]


DEFAULT_CIPHERS = ":".join(
    [
        "ECDHE+AESGCM",
        "ECDHE+CHACHA20",
        "DHE+AESGCM",
        "DHE+CHACHA20",
        "ECDH+AESGCM",
        "DH+AESGCM",
        "ECDH+AES",
        "DH+AES",
        "RSA+AESGCM",
        "RSA+AES",
        "!aNULL",
        "!eNULL",
        "!MD5",
        "!DSS",
    ]
)


class SSLConfig:
    """
    SSL Configuration.
    """

    def __init__(self, *, cert: CertTypes = None, verify: VerifyTypes = True):
        self.cert = cert
        self.verify = verify

    def __eq__(self, other: typing.Any) -> bool:
        return (
            isinstance(other, self.__class__)
            and self.cert == other.cert
            and self.verify == other.verify
        )

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}(cert={self.cert}, verify={self.verify})"

    def with_overrides(
        self, cert: CertTypes = None, verify: VerifyTypes = None
    ) -> "SSLConfig":
        cert = self.cert if cert is None else cert
        verify = self.verify if verify is None else verify
        if (cert == self.cert) and (verify == self.verify):
            return self
        return SSLConfig(cert=cert, verify=verify)

    async def load_ssl_context(self) -> ssl.SSLContext:
        if not hasattr(self, "ssl_context"):
            if not self.verify:
                self.ssl_context = self.load_ssl_context_no_verify()
            else:
                # Run the SSL loading in a threadpool, since it makes disk accesses.
                loop = asyncio.get_event_loop()
                self.ssl_context = await loop.run_in_executor(
                    None, self.load_ssl_context_verify
                )

        return self.ssl_context

    def load_ssl_context_no_verify(self) -> ssl.SSLContext:
        """
        Return an SSL context for unverified connections.
        """
        context = ssl.SSLContext(ssl.PROTOCOL_SSLv23)
        context.options |= ssl.OP_NO_SSLv2
        context.options |= ssl.OP_NO_SSLv3
        context.options |= ssl.OP_NO_COMPRESSION
        context.set_default_verify_paths()
        return context

    def load_ssl_context_verify(self) -> ssl.SSLContext:
        """
        Return an SSL context for verified connections.
        """
        if isinstance(self.verify, bool):
            ca_bundle_path = DEFAULT_CA_BUNDLE_PATH
        elif os.path.exists(self.verify):
            ca_bundle_path = self.verify
        else:
            raise IOError(
                "Could not find a suitable TLS CA certificate bundle, "
                "invalid path: {}".format(self.verify)
            )

        context = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)

        context.verify_mode = ssl.CERT_REQUIRED

        context.options |= ssl.OP_NO_SSLv2
        context.options |= ssl.OP_NO_SSLv3
        context.options |= ssl.OP_NO_COMPRESSION

        context.set_ciphers(DEFAULT_CIPHERS)

        if ssl.HAS_ALPN:
            context.set_alpn_protocols(["h2", "http/1.1"])
        if ssl.HAS_NPN:
            context.set_npn_protocols(["h2", "http/1.1"])

        if os.path.isfile(ca_bundle_path):
            context.load_verify_locations(cafile=ca_bundle_path)
        elif os.path.isdir(ca_bundle_path):
            context.load_verify_locations(capath=ca_bundle_path)

        if self.cert is not None:
            if isinstance(self.cert, str):
                context.load_cert_chain(certfile=self.cert)
            else:
                context.load_cert_chain(certfile=self.cert[0], keyfile=self.cert[1])

        return context


class TimeoutConfig:
    """
    Timeout values.
    """

    def __init__(
        self,
        timeout: TimeoutTypes = None,
        *,
        connect_timeout: float = None,
        read_timeout: float = None,
        write_timeout: float = None,
    ):
        if timeout is None:
            self.connect_timeout = connect_timeout
            self.read_timeout = read_timeout
            self.write_timeout = write_timeout
        else:
            # Specified as a single timeout value
            assert connect_timeout is None
            assert read_timeout is None
            assert write_timeout is None
            if isinstance(timeout, TimeoutConfig):
                self.connect_timeout = timeout.connect_timeout
                self.read_timeout = timeout.read_timeout
                self.write_timeout = timeout.write_timeout
            elif isinstance(timeout, tuple):
                self.connect_timeout = timeout[0]
                self.read_timeout = timeout[1]
                self.write_timeout = timeout[2]
            else:
                self.connect_timeout = timeout
                self.read_timeout = timeout
                self.write_timeout = timeout

    def __eq__(self, other: typing.Any) -> bool:
        return (
            isinstance(other, self.__class__)
            and self.connect_timeout == other.connect_timeout
            and self.read_timeout == other.read_timeout
            and self.write_timeout == other.write_timeout
        )

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        if len(set([self.connect_timeout, self.read_timeout, self.write_timeout])) == 1:
            return f"{class_name}(timeout={self.connect_timeout})"
        return f"{class_name}(connect_timeout={self.connect_timeout}, read_timeout={self.read_timeout}, write_timeout={self.write_timeout})"


class PoolLimits:
    """
    Limits on the number of connections in a connection pool.
    """

    def __init__(
        self,
        *,
        soft_limit: int = None,
        hard_limit: int = None,
        pool_timeout: float = None,
    ):
        self.soft_limit = soft_limit
        self.hard_limit = hard_limit
        self.pool_timeout = pool_timeout

    def __eq__(self, other: typing.Any) -> bool:
        return (
            isinstance(other, self.__class__)
            and self.soft_limit == other.soft_limit
            and self.hard_limit == other.hard_limit
            and self.pool_timeout == other.pool_timeout
        )

    def __repr__(self) -> str:
        class_name = self.__class__.__name__
        return f"{class_name}(soft_limit={self.soft_limit}, hard_limit={self.hard_limit}, pool_timeout={self.pool_timeout})"


DEFAULT_SSL_CONFIG = SSLConfig(cert=None, verify=True)
DEFAULT_TIMEOUT_CONFIG = TimeoutConfig(timeout=5.0)
DEFAULT_POOL_LIMITS = PoolLimits(soft_limit=10, hard_limit=100, pool_timeout=5.0)
DEFAULT_CA_BUNDLE_PATH = certifi.where()
DEFAULT_MAX_REDIRECTS = 20
