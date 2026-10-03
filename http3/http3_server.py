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
from aioquic.h3.events import HeadersReceived, DataReceived

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa


# HTTP/3 server port
PORT = 4433

# Folder where the files are stored
FILE_FOLDER = os.path.join("..", "Data files")

# Certificate and private key filenames
CERT_FILE = "server-cert.pem"
KEY_FILE = "server-key.pem"


def create_certificate():

    # Check if the certificate exists
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

        # Store request information for each stream
        self.request_headers = {}

        self.received_data = {}


    def quic_event_received(self, event):

        # Pass QUIC events to HTTP/3
        for http_event in self.http.handle_event(event):


            if isinstance(http_event, HeadersReceived):

                headers = dict(http_event.headers)

                method = headers.get(
                    b":method",
                    b""
                ).decode()


                path = headers.get(
                    b":path",
                    b"/"
                ).decode()


                file_name = path.lstrip("/")


                if method == "POST":

                    self.request_headers[
                        http_event.stream_id
                    ] = file_name

                    self.received_data[
                        http_event.stream_id
                    ] = bytearray()


                elif method == "GET":

                    file_path = os.path.join(
                        FILE_FOLDER,
                        file_name
                    )


                    if os.path.isfile(file_path):

                        with open(
                            file_path,
                            "rb"
                        ) as file:

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


            elif isinstance(http_event, DataReceived):

                stream_id = http_event.stream_id


                # Make sure this stream is an upload
                if stream_id not in self.received_data:
                    continue


                # Add received file data
                self.received_data[
                    stream_id
                ].extend(http_event.data)


                if http_event.stream_ended:

                    file_name = self.request_headers[
                        stream_id
                    ]


                    file_path = os.path.join(
                        FILE_FOLDER,
                        file_name
                    )


                    # Save the uploaded A file
                    with open(
                        file_path,
                        "wb"
                    ) as output:

                        output.write(
                            self.received_data[
                                stream_id
                            ]
                        )


                    print(
                        f"Received {file_name}: "
                        f"{len(self.received_data[stream_id])} bytes"
                    )


                    # Send response to client
                    self.http.send_headers(
                        stream_id,
                        [
                            (b":status", b"200"),
                            (
                                b"content-length",
                                b"2"
                            )
                        ]
                    )

                    self.http.send_data(
                        stream_id,
                        b"OK",
                        end_stream=True
                    )


                    self.transmit()


                    # Clean up stream information
                    del self.request_headers[
                        stream_id
                    ]

                    del self.received_data[
                        stream_id
                    ]


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


    print(
        "HTTP/3 server running on port",
        PORT
    )


    await asyncio.Future()


asyncio.run(main())




