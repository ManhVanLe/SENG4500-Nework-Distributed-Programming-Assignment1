import argparse
import socket
import struct
import zlib


# ============================================================
# Protocol constants
# ============================================================

# Request operation codes.
LOOKUP = 0x01
RESERVE = 0x02
ADD_ITEM = 0x03
LIST_CATEGORY = 0x04

# Successful responses have this flag added to the
# original operation code.
RESPONSE_FLAG = 0x80

# Generic error response type.
ERROR = 0xFF

# Maximum protocol message size accepted by the client.
MAX_MESSAGE_SIZE = 65536


# ============================================================
# TCP helper functions
# ============================================================

def recv_exact(sock, number_of_bytes):
    """
    Receive exactly the requested number of bytes.

    TCP is a byte stream, so a single recv() call is not
    guaranteed to return all the bytes that were sent.
    """

    data = b""

    while len(data) < number_of_bytes:

        # Ask TCP for the number of bytes that are still missing.
        chunk = sock.recv(number_of_bytes - len(data))

        # An empty bytes object means the server closed
        # the connection.
        if not chunk:
            raise ConnectionError(
                "Server disconnected"
            )

        data += chunk

    return data


def send_packet(sock, message_type, payload=b""):
    """
    Create and send one protocol packet.

    Packet format:

        4 bytes : body length
        1 byte  : message type
        N bytes : payload
        4 bytes : CRC32 checksum
    """

    # Protect both the message type and payload with CRC32.
    content = bytes([message_type]) + payload

    # Calculate the application-layer checksum.
    checksum = zlib.crc32(content) & 0xFFFFFFFF

    # Add the checksum to the message body.
    body = content + struct.pack(
        "!I",
        checksum
    )

    # Prefix the body with its total length so the receiver
    # knows exactly where this message ends.
    packet = (
        struct.pack("!I", len(body))
        + body
    )

    # sendall() ensures Python attempts to send
    # the complete packet.
    sock.sendall(packet)


def receive_packet(sock):
    """
    Receive and validate one complete protocol packet
    from the server.
    """

    # First read the 4-byte message length.
    length_bytes = recv_exact(sock, 4)

    # Convert the four network-order bytes into an integer.
    body_length = struct.unpack(
        "!I",
        length_bytes
    )[0]

    # A valid body requires at least:
    # 1 byte message type + 4 byte CRC.
    if body_length < 5:
        raise ValueError(
            "Invalid response length"
        )

    # Prevent unexpectedly large messages.
    if body_length > MAX_MESSAGE_SIZE:
        raise ValueError(
            "Response is too large"
        )

    # Now that the length is known, receive the entire body.
    body = recv_exact(
        sock,
        body_length
    )

    # The last four bytes contain the checksum
    # supplied by the server.
    received_crc = struct.unpack(
        "!I",
        body[-4:]
    )[0]

    # Everything before the CRC is protected data.
    content = body[:-4]

    # Recalculate the checksum ourselves.
    calculated_crc = (
        zlib.crc32(content)
        & 0xFFFFFFFF
    )

    # Reject the response if the checksums do not match.
    if received_crc != calculated_crc:
        raise ValueError(
            "Checksum mismatch"
        )

    # The first byte identifies the response type.
    message_type = content[0]

    # Everything after it is the response payload.
    payload = content[1:]

    return message_type, payload


# ============================================================
# String encoding / decoding
# ============================================================

def encode_string(text):
    """
    Encode a Python string as:

        2 bytes : UTF-8 byte length
        N bytes : UTF-8 text
    """

    encoded = text.encode("utf-8")

    return (
        struct.pack("!H", len(encoded))
        + encoded
    )


def decode_string(data, offset=0):
    """
    Decode one length-prefixed UTF-8 string from a payload.

    Returns:
        decoded string
        new offset
    """

    # Two bytes are required to read the string length.
    if offset + 2 > len(data):
        raise ValueError(
            "Missing string length"
        )

    string_length = struct.unpack(
        "!H",
        data[offset:offset + 2]
    )[0]

    offset += 2

    # Make sure all string bytes are actually present.
    if offset + string_length > len(data):
        raise ValueError(
            "Incomplete string"
        )

    text = data[
        offset:offset + string_length
    ].decode("utf-8")

    offset += string_length

    return text, offset


# ============================================================
# Error response handling
# ============================================================

def display_error(payload):
    """
    Decode and display an error response sent by the server.

    Error payload format:

        1 byte  : error code
        string  : error message
    """

    try:
        # The first byte stores the numeric error code.
        error_code = payload[0]

        # The rest contains the encoded error message.
        error_message, offset = decode_string(
            payload,
            1
        )

        print()
        print(
            f"Error {error_code}: "
            f"{error_message}"
        )

    except (
        IndexError,
        ValueError,
        UnicodeDecodeError
    ):
        print(
            "\nError: Invalid error response "
            "received from server."
        )


# ============================================================
# Function 1 - Look up item
# ============================================================

def lookup_item(sock):
    """
    Ask the user for an item code, send a LOOKUP request,
    and display the item returned by the server.
    """

    print()
    print("--- Look Up Item ---")

    # Collect the item code from the user.
    item_code = input(
        "Enter item code: "
    ).strip()

    # Perform basic validation on the client before sending.
    if not item_code:
        print(
            "Item code cannot be empty."
        )
        return

    # The LOOKUP request contains only the item code.
    payload = encode_string(item_code)

    # Send operation 0x01 to the server.
    send_packet(
        sock,
        LOOKUP,
        payload
    )

    # Wait for the server response.
    message_type, payload = receive_packet(
        sock
    )

    # A successful LOOKUP response is:
    #
    # 0x01 | 0x80 = 0x81
    if message_type == (
        LOOKUP | RESPONSE_FLAG
    ):
        try:
            offset = 0

            # Decode the returned item fields one at a time.
            item_code, offset = decode_string(
                payload,
                offset
            )

            item_name, offset = decode_string(
                payload,
                offset
            )

            category, offset = decode_string(
                payload,
                offset
            )

            # Quantity is stored as a 4-byte unsigned integer.
            if offset + 4 > len(payload):
                raise ValueError(
                    "Missing quantity"
                )

            quantity = struct.unpack(
                "!I",
                payload[offset:offset + 4]
            )[0]

            offset += 4

            unit, offset = decode_string(
                payload,
                offset
            )

            location, offset = decode_string(
                payload,
                offset
            )

            # Ensure there is no unexpected data after
            # the final field.
            if offset != len(payload):
                raise ValueError(
                    "Unexpected response data"
                )

            # Display the item details returned by the server.
            print()
            print("Item found")
            print("-------------------------")
            print(f"Code:     {item_code}")
            print(f"Name:     {item_name}")
            print(f"Category: {category}")
            print(
                f"Quantity: {quantity} {unit}"
            )
            print(f"Location: {location}")

        except (
            ValueError,
            UnicodeDecodeError
        ):
            print(
                "Error: Invalid LOOKUP response "
                "received from server."
            )

    # The server returned a normal protocol error.
    elif message_type == ERROR:
        display_error(payload)

    # Anything else is an unexpected response type.
    else:
        print(
            f"Unexpected response type: "
            f"{hex(message_type)}"
        )
# ============================================================
# Function 2 - Reserve an item
# ============================================================
def reserve_item(sock):
    """
    Ask the user for an item code and quantity, send a RESERVE
    request, and display the result returned by the server.
    """

    print()
    print("--- Reserve Item ---")

    # Ask the user for the item code.
    item_code = input(
        "Enter item code: "
    ).strip()

    # Validate the item code before sending anything.
    if not item_code:
        print("Item code cannot be empty.")
        return
    
    # -------------------------------------------------
    # Check whether the item exists BEFORE asking
    # the user for a quantity.
    # -------------------------------------------------

    # Build a LOOKUP request using the entered item code.
    lookup_payload = encode_string(item_code)

    # Send the lookup request to the server.
    send_packet(
        sock,
        LOOKUP,
        lookup_payload
    )

    # Receive the lookup response.
    message_type, response_payload = receive_packet(
        sock
    )

    # If the server returns an error, the item does not
    # exist or the request was invalid.
    if message_type == ERROR:
        display_error(response_payload)

        # Stop reserve_item() immediately.
        # The main menu will then be shown again.
        return

    # Make sure the response was actually a successful LOOKUP.
    if message_type != (
        LOOKUP | RESPONSE_FLAG
    ):
        print(
            "Unexpected response from server."
        )
        return
    
    # Ask the user for the quantity.
    quantity_input = input(
        "Enter quantity to reserve: "
    ).strip()

    # Convert the quantity into an integer.
    try:
        quantity = int(quantity_input)

    except ValueError:
        print(
            "Quantity must be a whole number."
        )
        return

    # The assignment requires invalid quantities
    # to be rejected.
    if quantity <= 0:
        print(
            "Quantity must be greater than zero."
        )
        return

    # Build the RESERVE request payload:
    #
    # encoded item code
    # +
    # 4-byte unsigned integer quantity
    payload = (
        encode_string(item_code)
        + struct.pack("!I", quantity)
    )

    # Send operation 0x02 to the server.
    send_packet(
        sock,
        RESERVE,
        payload
    )

    # Wait for the server response.
    message_type, payload = receive_packet(
        sock
    )

    # Successful RESERVE response:
    #
    # 0x02 | 0x80 = 0x82
    if message_type == (
        RESERVE | RESPONSE_FLAG
    ):
        try:
            offset = 0

            # Decode the item code returned by the server.
            returned_item_code, offset = decode_string(
                payload,
                offset
            )

            # Four bytes should remain for the new
            # quantity after the reservation.
            if offset + 4 > len(payload):
                raise ValueError(
                    "Missing remaining quantity"
                )

            remaining_quantity = struct.unpack(
                "!I",
                payload[offset:offset + 4]
            )[0]

            offset += 4

            # Reject unexpected bytes after the expected fields.
            if offset != len(payload):
                raise ValueError(


                    "Unexpected response data"
                )

            print()
            print("Reservation successful")
            print("-------------------------")
            print(
                f"Item: {returned_item_code}"
            )
            print(
                f"Remaining quantity: "
                f"{remaining_quantity}"
            )

        except (
            ValueError,
            UnicodeDecodeError
        ):
            print(
                "Error: Invalid RESERVE response "
                "received from server."
            )

    # Display any normal server error.
    elif message_type == ERROR:
        display_error(payload)

    # Catch unexpected response types.
    else:
        print(
            f"Unexpected response type: "
            f"{hex(message_type)}"
        )

# ============================================================
# Funtion 3 - Add a new item
# ============================================================
def add_item(sock):
    """
    Ask the user for the details of a new inventory item,
    send an ADD_ITEM request to the server, and display
    whether the operation succeeded or failed.
    """

    print()
    print("--- Add New Item ---")

    # Ask the user for the new item code.
    item_code = input(
        "Enter item code: "
    ).strip()

    # Item code is required.
    if not item_code:
        print("Item code cannot be empty.")
        return

    # Ask for the item name.
    item_name = input(
        "Enter item name: "
    ).strip()

    if not item_name:
        print("Item name cannot be empty.")
        return

    # Ask for the category.
    category = input(
        "Enter category: "
    ).strip()

    if not category:
        print("Category cannot be empty.")
        return

    # Ask for quantity as text first.
    quantity_input = input(
        "Enter quantity: "
    ).strip()

    # Convert the quantity to an integer.
    try:
        quantity = int(quantity_input)

    except ValueError:
        print(
            "Quantity must be a whole number."
        )
        return

    # Quantity must be greater than zero.
    if quantity <= 0:
        print(
            "Quantity must be greater than zero."
        )
        return

    # Ask for the unit.
    unit = input(
        "Enter unit: "
    ).strip()

    if not unit:
        print("Unit cannot be empty.")
        return

    # Ask for the storage location.
    location = input(
        "Enter location: "
    ).strip()

    if not location:
        print("Location cannot be empty.")
        return

    # Build the ADD_ITEM payload in the same order
    # expected by the server:
    #
    # item_code
    # item_name
    # category
    # quantity
    # unit
    # location
    payload = (
        encode_string(item_code)
        + encode_string(item_name)
        + encode_string(category)
        + struct.pack("!I", quantity)
        + encode_string(unit)
        + encode_string(location)
    )

    # Send operation 0x03 to the server.
    send_packet(
        sock,
        ADD_ITEM,
        payload
    )

    # Wait for the server response.
    message_type, payload = receive_packet(
        sock
    )

    # Successful ADD_ITEM response:
    #
    # 0x03 | 0x80 = 0x83
    if message_type == (
        ADD_ITEM | RESPONSE_FLAG
    ):
        try:
            # The successful response contains
            # the item code that was added.
            added_item_code, offset = decode_string(
                payload
            )

            # Reject unexpected extra response data.
            if offset != len(payload):
                raise ValueError(
                    "Unexpected response data"
                )

            print()
            print("Item added successfully")
            print("-------------------------")
            print(
                f"Item code: {added_item_code}"
            )

        except (
            ValueError,
            UnicodeDecodeError
        ):
            print(
                "Error: Invalid ADD_ITEM response "
                "received from server."
            )

    # Display any error returned by the server.
    elif message_type == ERROR:
        display_error(payload)

    # Catch an unexpected response type.
    else:
        print(
            f"Unexpected response type: "
            f"{hex(message_type)}"
        )
# ============================================================
# Function 4 - List items by category
# ============================================================
def list_items_by_category(sock):
    """
    Ask the user for a category, send a LIST_CATEGORY request,
    and display all matching inventory items returned by the server.
    """

    print()
    print("--- List Items By Category ---")

    # Ask the user which category they want to search for.
    category = input(
        "Enter category: "
    ).strip()

    # The category must not be empty.
    if not category:
        print("Category cannot be empty.")
        return

    # The request payload contains only the encoded category.
    payload = encode_string(category)

    # Send operation 0x04 to the server.
    send_packet(
        sock,
        LIST_CATEGORY,
        payload
    )

    # Wait for the server response.
    message_type, payload = receive_packet(
        sock
    )

    # Successful LIST_CATEGORY response:
    #
    # 0x04 | 0x80 = 0x84
    if message_type == (
        LIST_CATEGORY | RESPONSE_FLAG
    ):
        try:
            offset = 0

            # The first 2 bytes contain the number of
            # matching records returned by the server.
            if offset + 2 > len(payload):
                raise ValueError(
                    "Missing item count"
                )

            item_count = struct.unpack(
                "!H",
                payload[offset:offset + 2]
            )[0]

            offset += 2

            print()
            print(
                f"Found {item_count} item(s) "
                f"in category '{category}'"
            )
            print("-------------------------")

            # Decode each returned item one at a time.
            for item_number in range(item_count):

                # Decode item code.
                item_code, offset = decode_string(
                    payload,
                    offset
                )

                # Decode item name.
                item_name, offset = decode_string(
                    payload,
                    offset
                )

                # Quantity is stored as a 4-byte
                # unsigned integer.
                if offset + 4 > len(payload):
                    raise ValueError(
                        "Missing item quantity"
                    )

                quantity = struct.unpack(
                    "!I",
                    payload[offset:offset + 4]
                )[0]

                offset += 4

                # Decode unit.
                unit, offset = decode_string(
                    payload,
                    offset
                )

                # Decode storage location.
                location, offset = decode_string(
                    payload,
                    offset
                )

                # Display the current record.
                print()
                print(
                    f"Item {item_number + 1}"
                )
                print(
                    f"Code:     {item_code}"
                )
                print(
                    f"Name:     {item_name}"
                )
                print(
                    f"Quantity: {quantity} {unit}"
                )
                print(
                    f"Location: {location}"
                )

            # After all records have been decoded,
            # there should be no additional bytes.
            if offset != len(payload):
                raise ValueError(
                    "Unexpected response data"
                )

        except (
            ValueError,
            UnicodeDecodeError
        ):
            print(
                "Error: Invalid LIST_CATEGORY "
                "response received from server."
            )

    # Display a normal error returned by the server.
    elif message_type == ERROR:
        display_error(payload)

    # Catch unexpected response types.
    else:
        print(
            f"Unexpected response type: "
            f"{hex(message_type)}"
        )



# ============================================================
# CLI menu
# ============================================================

def print_menu():
    """
    Display the main inventory client menu.
    """

    print()
    print("==============================")
    print(" Engineering Lab Inventory")
    print("==============================")
    print("1. Look up an item")
    print("2. Reserve an item")
    print("3. Add a new item")
    print("4. List items by category")
    print("5. Exit")
    print("==============================")


# ============================================================
# Main program
# ============================================================

def main():
    """
    Read command-line configuration, connect to the server,
    and run the client menu.
    """

    # Create command-line argument parser.
    parser = argparse.ArgumentParser(
        description=(
            "Engineering Lab Inventory Client"
        )
    )

    # The server hostname/IP must be configurable.
    parser.add_argument(
        "--host",
        required=True,
        help="Server hostname or IP address"
    )

    # The server TCP port must also be configurable.
    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="Server TCP port"
    )

    args = parser.parse_args()

    # Validate the supplied TCP port.
    if args.port < 1 or args.port > 65535:
        print(
            "Error: port must be between "
            "1 and 65535."
        )
        return

    try:
        # Create an IPv4 TCP socket.
        with socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        ) as sock:

            print(
                f"Connecting to "
                f"{args.host}:{args.port}..."
            )

            # Connect to the inventory server.
            sock.connect(
                (args.host, args.port)
            )

            print("Connected to server.")

            # Keep the connection open while the user
            # performs multiple inventory operations.
            while True:

                print_menu()

                choice = input(
                    "Select option: "
                ).strip()

                # Function 1 - Look up an item.
                if choice == "1":
                    lookup_item(sock)

                # Function 2 - Reserver an item.
                elif choice == "2":
                    reserve_item(sock)

                elif choice == "3":
                    add_item(sock)

                elif choice == "4":
                    list_items_by_category(sock)
                # Exit the client.
                elif choice == "5":
                    print(
                        "Disconnecting from server."
                    )
                    break

                else:
                    print(
                        "Invalid option. "
                        "Please select 1-5."
                    )

    except ConnectionRefusedError:
        print(
            "Error: Could not connect to the server."
        )

    except ConnectionError as error:
        print(
            f"Connection error: {error}"
        )

    except OSError as error:
        print(
            f"Network error: {error}"
        )

    except ValueError as error:
        print(
            f"Protocol error: {error}"
        )


# Run main() only when this file is executed directly.
if __name__ == "__main__":
    main()