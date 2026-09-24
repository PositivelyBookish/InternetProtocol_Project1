# -*- coding: utf-8 -*-
"""
Created on Tue Sep 22 14:21:29 2026

@author: jazmi
"""
import asyncio
import csv
import time

from aioquic.asyncio import connect
from aioquic.asyncio.protocol import QuicConnectionProtocol
from aioquic.h3.connection import H3Connection
from aioquic.h3.events import HeadersReceived, DataReceived
from aioquic.quic.configuration import QuicConfiguration
from aioquic.quic.events import QuicEvent


COMPUTER_NUMBER = 1

#
# For testing on one computer, you can use sasme IP

COMPUTER_1_IP = "10.154.1.68"
COMPUTER_2_IP = "10.154.1.68"

PORT = 4433

RESULTS_FILE = "HTTP3_results.csv"

A_FILES = [
    ("A_10kB", 1000),
    ("A_100kB", 100),
    ("A_1MB", 10),
    ("A_10MB", 1)
]

B_FILES = [
    ("B_10kB", 1000),
    ("B_100kB", 100),
    ("B_1MB", 10),
    ("B_10MB", 1)
]

if COMPUTER_NUMBER == 1:

    # Computer 1 requests files from Computer 2
    SERVER_IP = COMPUTER_2_IP
    FILES_TO_REQUEST = B_FILES

elif COMPUTER_NUMBER == 2:

    # Computer 2 requests files from Computer 1
    SERVER_IP = COMPUTER_1_IP
    FILES_TO_REQUEST = A_FILES

else:

    raise ValueError(
        "COMPUTER_NUMBER must be either 1 or 2."
    )


class HTTP3ClientProtocol(QuicConnectionProtocol):

    def __init__(self, *args, **kwargs):

        super().__init__(*args, **kwargs)

        # Create HTTP/3 connection
        self.http = H3Connection(self._quic)

        # Queue for HTTP/3 
        self.http_events = asyncio.Queue()


    def quic_event_received(self, event: QuicEvent):

        # Send QUIC 
        for http_event in self.http.handle_event(event):

            self.http_events.put_nowait(http_event)

async def transfer_file(
    http,
    protocol,
    server_ip,
    file_name,
    save_file=False
):

    stream_id = protocol._quic.get_next_available_stream_id()

    http.send_headers(
        stream_id=stream_id,
        headers=[
            (b":method", b"GET"),
            (b":scheme", b"https"),
            (b":authority", server_ip.encode()),
            (b":path", ("/" + file_name).encode())
        ],
        end_stream=True
    )

    protocol.transmit()


    received_data = bytearray()
    header_bytes = 0

    while True:

        response = await protocol.http_events.get()

        if isinstance(response, HeadersReceived):

            for name, value in response.headers:

                header_bytes += len(name) + len(value)


        elif isinstance(response, DataReceived):

            received_data.extend(response.data)


            
            if response.stream_ended:

                if save_file:

                    output_file = "received_" + file_name

                    with open(output_file, "wb") as output:

                        output.write(received_data)

                application_data = (
                    len(received_data) + header_bytes
                )


                return (
                    len(received_data),
                    application_data
                )

async def test_file(
    http,
    protocol,
    server_ip,
    file_name,
    number_of_transfers
):

    total_file_data = 0
    total_application_data = 0


    start_time = time.perf_counter()


    # Transfer multiple times
    for i in range(number_of_transfers):
        save_file = (i == 0)
        file_data, application_data = await transfer_file(
            http,
            protocol,
            server_ip,
            file_name,
            save_file
        )

        total_file_data += file_data
        total_application_data += application_data

    end_time = time.perf_counter()


    total_time = end_time - start_time

    # Size of one file
    file_size = total_file_data // number_of_transfers

    # Header/application overhead
    total_header_data = (
        total_application_data - total_file_data
    )

    application_data_ratio = (
        total_application_data /
        (file_size * number_of_transfers)
    )


    throughput = total_file_data / total_time

    return (
        file_size,
        total_file_data,
        total_header_data,
        total_application_data,
        application_data_ratio,
        total_time,
        throughput
    )

def save_results(
    file_name,
    number_of_transfers,
    file_size,
    total_file_data,
    total_header_data,
    total_application_data,
    application_data_ratio,
    total_time,
    throughput
):

    with open(
        RESULTS_FILE,
        "a",
        newline=""
    ) as csv_file:

        writer = csv.writer(csv_file)


        writer.writerow([
            "HTTP/3",
            file_name,
            number_of_transfers,
            file_size,
            total_file_data,
            total_header_data,
            total_application_data,
            application_data_ratio,
            total_time,
            throughput
        ])



async def run_tests():

    configuration = QuicConfiguration(
        is_client=True,
        alpn_protocols=["h3"]
    )


    # Don't verify our self-signed certificate
    configuration.verify_mode = False



    async with connect(
        SERVER_IP,
        PORT,
        configuration=configuration,
        create_protocol=HTTP3ClientProtocol
    ) as protocol:

        http = protocol.http

        for file_name, number_of_transfers in FILES_TO_REQUEST:

            print(
                f"Testing {file_name}: "
                f"{number_of_transfers} transfers"
            )

            results = await test_file(
                http,
                protocol,
                SERVER_IP,
                file_name,
                number_of_transfers
            )

            (
                file_size,
                total_file_data,
                total_header_data,
                total_application_data,
                application_data_ratio,
                total_time,
                throughput
            ) = results

            save_results(
                file_name,
                number_of_transfers,
                file_size,
                total_file_data,
                total_header_data,
                total_application_data,
                application_data_ratio,
                total_time,
                throughput
            )


            print(
                f"Completed {file_name}"
            )

async def main():

    with open(
        RESULTS_FILE,
        "w",
        newline=""
    ) as csv_file:

        writer = csv.writer(csv_file)


        writer.writerow([
            "Protocol",
            "File",
            "Transfers",
            "File Size (bytes)",
            "Total File Data (bytes)",
            "Total Header Data (bytes)",
            "Total Application Data (bytes)",
            "Application Data / File Size",
            "Total Time (seconds)",
            "Throughput (bytes/second)"
        ])

    print("HTTP/3 Test")
    print(f"Computer: {COMPUTER_NUMBER}")
    print(f"Server IP: {SERVER_IP}")
    print("Files to request:")

    for file_name, number_of_transfers in FILES_TO_REQUEST:

        print(
            f"  {file_name}: "
            f"{number_of_transfers} transfers"
        )

    print("----------------------------------------")


    await run_tests()


    print()
    print("HTTP/3 tests completed.")
    print("Results saved to:", RESULTS_FILE)

asyncio.run(main())
