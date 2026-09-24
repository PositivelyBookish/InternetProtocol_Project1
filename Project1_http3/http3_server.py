# -*- coding: utf-8 -*-
"""
Created on Tue Sep 22 15:31:19 2026

@author: jazmi
"""

import asyncio
import os
import datetime

from aioquic.asyncio import serve
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.quic.configuration import QuicConfiguration
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import HeadersReceived

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


# HTTP/3 server port
PORT = 4433

# Folder where the files are stored
FILE_FOLDER = "Data files"

# Certificate and private key filenames
CERT_FILE = "server-cert.pem"
KEY_FILE = "server-key.pem"


def create_certificate():

    # Check if the certificate already exists
    if os.path.exists(CERT_FILE) and os.path.exists(KEY_FILE):
        return

    print("Creating HTTP/3 test certificate...")

    # Create private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )

    # Create certificate info
    subject = issuer = x509.Name([
        x509.NameAttribute(
            NameOID.COMMON_NAME,
            "localhost"
        )
    ])

    # Create certificate
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(minutes=1)
        )
        .not_valid_after(
            datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(days=365)
        )
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(
                    __import__("ipaddress").ip_address("127.0.0.1")
                )
            ]),
            critical=False
        )
        .sign(
            private_key,
            hashes.SHA256()
        )
    )

    # Save private key
    with open(KEY_FILE, "wb") as key_file:

        key_file.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption()
            )
        )

    # Save certificate
    with open(CERT_FILE, "wb") as cert_file:

        cert_file.write(
            certificate.public_bytes(
                serialization.Encoding.PEM
            )
        )

    print("Certificate created.")

class HTTP3ServerProtocol(QuicConnectionProtocol):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # Create HTTP/3 connection
        self.http = H3Connection(self._quic)

    def quic_event_received(self, event):

        # Pass QUIC
        for http_event in self.http.handle_event(event):

            # Check if the client sent a request
            if isinstance(http_event, HeadersReceived):

                headers = dict(http_event.headers)
                path = headers.get(
                    b":path",
                    b"/"
                ).decode()

                file_name = path.lstrip("/")

                # Build file path
                file_path = os.path.join(
                    FILE_FOLDER,
                    file_name
                )

                if os.path.isfile(file_path):

                    with open(file_path, "rb") as file:
                        data = file.read()

                    self.http.send_headers(
                        http_event.stream_id,
                        [
                            (b":status", b"200"),
                            (
                                b"content-length",
                                str(len(data)).encode()
                            )
                        ]
                    )

                    self.http.send_data(
                        http_event.stream_id,
                        data,
                        end_stream=True
                    )

                else:

                    self.http.send_headers(
                        http_event.stream_id,
                        [
                            (b":status", b"404")
                        ],
                        end_stream=True
                    )

                self.transmit()


async def main():

    create_certificate()

    configuration = QuicConfiguration(
        is_client=False,
        alpn_protocols=["h3"]
    )

    configuration.load_cert_chain(
        CERT_FILE,
        KEY_FILE
    )
    await serve(
        "0.0.0.0",
        PORT,
        configuration=configuration,
        create_protocol=HTTP3ServerProtocol
    )

    print("HTTP/3 server running on port", PORT)

    await asyncio.Future()


asyncio.run(main())




