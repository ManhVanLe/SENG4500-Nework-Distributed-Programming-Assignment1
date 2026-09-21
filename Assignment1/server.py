import argparse
import socket
import struct
import zlib

# ============================================================
# Protocol constants
# ============================================================
LOOKUP = 0x01
RESERVE = 0x02
ADD_ITEM = 0x03
LIST_CATEGORY = 0x04

# Response flag.
# LOOKUP = 0x01
# Successful LOOKUP response = 0x81
RESPONSEFLAG = 0x80

ERROR = 0xFF

# Error codes
ERR_INVALID_REQUEST = 0x01
ERR_ITEM_NOT_FOUND = 0x02
ERR_CHECKSUM = 0x03
ERR_UNKNOWN_OPERATION = 0x04
ERR_INVALID_QUANTITY = 0x05
ERR_INSUFFICIENT_STOCK = 0x06
ERR_DUPLICATE_ITEM = 0x07
ERR_CATEGORY_NOT_FOUND = 0x08

# Maximum size of a request or response packet (in bytes)
MAX_MESSAGE_SIZE = 65536

# ============================================================
# Initialization inventory
# ============================================================

inventory = {
    "RPI-004": {
        "item_name": "Raspberry Pi 4",
        "category": "controller",
        "quantity": 12,
        "unit": "units",
        "location": "Cabinet A"
    },

    "SNS-011": {
        "item_name": "Ultrasonic Sensor",
        "category": "sensor",
        "quantity": 40,
        "unit": "units",
        "location": "Cabinet C"
    },

    "CBL-USB": {
        "item_name": "USB-C Cable",
        "category": "cable",
        "quantity": 75,
        "unit": "units",
        "location": "Drawer 2"
    }
}

# ============================================================
# TCP helper functions
# ============================================================

def receive_exact(sock, num_bytes):
    """
    Receives exactly the requested number of bytes from the socket.
    
    TCP is a byte stream, so one recv() call may not return all the requested bytes. This function ensures that we read exactly the number of bytes we expect.
    """
    data = b""

    while len(data) < num_bytes:
        chunk = sock.recv(num_bytes - len(data))

        #Empty bytes means the connection has been closed by the client
        if not chunk:
            raise ConnectionError("Socket connection closed unexpectedly.")
        
        data += chunk
        return data

def send_packet(conn, message_type, payload=b""):
    """
    Sends a packet to the client with the specified message type and payload.
    
    The packet structure is as follows:
    - 1 byte: message type
    - 4 bytes: payload length 
    - N bytes: payload (if any)
    - 4 bytes: CRC32 checksum of the payload 
    """
   # Message type + payload
    content = bytes([message_type]) + payload

    # Calculate CRC32 checksum of the payload
    checksum = zlib.crc32(content) & 0xFFFFFFFF  # Ensure it's a 32-bit unsigned integer

    # Add checksum to the end of the content
    body = content + struct.pack('!I', checksum)

    #Add 4-byte length prefix
    packet = struct.pack('!I', len(body)) + body

    conn.sendall(packet)


def receive_packet(conn):
    """receive and validate a complete protocal message from the client, including length prefix and checksum.
    """

    #First receive the 4-byte Lenth prefix
    length_bytes = receive_exact(conn, 4)

    #Convert the 4 bytes to an integer 
    body_length = struct.unpack('!I', length_bytes)[0]

    # Minimum: 
    # 1 byte messag type
    # 4 bytes CRC

    if body_length < 5:
        raise ValueError("Invalid packet length.")
    if body_length > MAX_MESSAGE_SIZE:
        raise ValueError("Packet length exceeds maximum allowed size.")

    #Now we know exactly how many bytes to read for the body
    body = receive_exact(conn, body_length)

    # Last 4 bytes contain the CRC32 checksum
    received_checksum = struct.unpack('!I', body[-4:])[0]

    #Everything before CRC is protected by the checksum
    content = body[:-4]

    calculated_crc = zlib.crc32(content) & 0xFFFFFFFF

    if received_checksum != calculated_crc:
        raise ValueError("Checksum mismatch.")

    # First byte is the message type
    message_type = content[0]

    # Remaining bytes are the payload
    payload = content[1:]

    return message_type, payload



# ============================================================
# Payload helper functions
# ============================================================

def encode_string(text):
    """
    Encodes a string as:
    2 bytes: length of the string
    N bytes: UTF-8 encoded string
    """

    encoded_text = text.encode('utf-8')

    return struct.pack('!H', len(encoded_text)) + encoded_text

def decode_string(data, offset=0):
    """
    Read a length-prefixed string from bytes
    """

    if offset + 2 > len(data):
        raise ValueError("Insufficient data for string length.")

    length = struct.unpack('!H', data[offset:offset + 2])[0]
    offset += 2

    if offset + length > len(data):
        raise ValueError("Incomplete string.")

    text = data[offset:offset + length].decode('utf-8')

    offset += length

    return text, offset    

# ============================================================
# Error response helper function
# ============================================================

def send_error(conn, error_code, message):
    """
    Sends an error response to the client.
    """
    payload = bytes([error_code]) + encode_string(message)
    send_packet(conn, ERROR, payload)

# ============================================================
# Function 1 - Look up an item 
# ============================================================

def handle_lookup(conn, payload):
    try:
        item_code, offset = decode_string(payload)

    except (ValueError, UnicodeDecodeError):
        send_error(conn, ERR_INVALID_REQUEST, "Invalid lookup request.")
        return

    # There should be no extra data in the payload
    if offset != len(payload):
        send_error(conn, ERR_INVALID_REQUEST, "Extra data in lookup request.")
        return

    item_code = item_code.strip().upper()

    if not item_code:
        send_error(conn, ERR_INVALID_REQUEST, "Item code cannot be empty.")
        return

    item = inventory.get(item_code)

    if item is None:  
        send_error(conn, ERR_ITEM_NOT_FOUND, f"Item code '{item_code}' not found.")
        return

    # Successful lookup, prepare the response payload
    response = (
        encode_string(item_code) +
        encode_string(item['item_name']) +
        encode_string(item['category']) +
        struct.pack('!I', item['quantity']) +
        encode_string(item['unit']) +
        encode_string(item['location'])
    )
    send_packet(conn, LOOKUP | RESPONSEFLAG, response)

#============================================================
# Function 2 - Reserve an item
#============================================================
def handle_reserve(conn, payload):
    try:
        # Read the item code first
        item_code, offset = decode_string(payload)

        # After the item code, exactly 4 bytes should remain for the quantity
        if offset + 4 != len(payload):
            raise ValueError("Invalid reserve request: incorrect payload length.")

        # Decode the 4-byte quantity
        quantity = struct.unpack('!I', payload[offset:offset + 4])[0]

    except (ValueError, UnicodeDecodeError):
        send_error(conn, ERR_INVALID_REQUEST, "Invalid reserve request.")
        return

    # Clean up item code
    item_code = item_code.strip().upper()

    # Check if item code is empty
    if not item_code:
        send_error(conn, ERR_INVALID_REQUEST, "Item code cannot be empty.")
        return

    # Find the item
    item = inventory.get(item_code)

    # Item does not exist
    if item is None:
        send_error(conn, ERR_ITEM_NOT_FOUND, f"Item code '{item_code}' not found.")
        return

    # Quantity must be greater than 0    
    if quantity <= 0:
        send_error(conn, ERR_INVALID_QUANTITY, "Quantity must be greater than 0.")
        return

    # Not enough stock available
    if quantity > item['quantity']:
        send_error(conn, ERR_INSUFFICIENT_STOCK, f"Insufficient stock for item '{item_code}'. Available: {item['quantity']}, Requested: {quantity}.")
        return

    # Reduce stock
    item['quantity'] -= quantity

    # Successful response:
    # item code + remain quantity
    response = (
        encode_string(item_code) +
        struct.pack('!I', item['quantity'])
    )
    send_packet(conn, RESERVE | RESPONSEFLAG, response)

#============================================================
# Function 3 - Add a new item 
#============================================================
def handle_add_item(conn, payload):
    """
    Handle function 3 - Add a new inventory item.
    Expected payload format:
    item_code :encoded string
    item_name :encoded string
    category :encoded string
    quantity :4 bytes unsigned int
    unit :encoded string
    location :encoded string
    """
    try:
        # decode the item code from the payload
        item_code, offset = decode_string(payload)

        # decode the item name strating form the current offset
        item_name, offset = decode_string(payload, offset)

        # decode the item category
        category, offset = decode_string(payload, offset)

        # decode the quantity
        # if fewer than 4 bytes remain, the request is malformed
        if len(payload) < offset + 4:
            raise ValueError("Invalid add item request: insufficient data for quantity.")

        # Convert the 4-bytes network-order integer into a Python integer.
        quantity = struct.unpack('!I', payload[offset:offset + 4])[0]

        # move the offset past the quantity field.
        offset += 4
     
        # decode the unit
        unit, offset = decode_string(payload, offset)

        # decode the location
        location, offset = decode_string(payload, offset)

        #After decoding all fields, check if there is any extra data in the payload
        if offset != len(payload):
            raise ValueError(
                "Invalid add item request: extra data in payload."
            )
        
    except (ValueError, UnicodeDecodeError) as e:
        send_error(conn, ERR_INVALID_REQUEST, f"Invalid add item request: {str(e)}")
        return

    #Normalise text input
    #Item codes are stored in uppercase so lookups are consistent.
    item_code= item_code.strip().upper()

    # Remove unnecessary spaces from text fields.
    item_name = item_name.strip()
    category = category.strip().lower()
    unit = unit.strip()
    location = location.strip()

    #Validate that all required text fields contain a value.
    if (
        not item_code
        or not item_name
        or not category
        or not unit
        or not location
    ):
        send_error(
            conn,
            ERR_INVALID_REQUEST,
            "Item fields cannot be empty"
        )
        return

    #Item codes must be unique
    #Reject the request if this code already exists.
    if item_code in inventory:
        send_error(
            conn,
            ERR_DUPLICATE_ITEM,
            "Item code already exists"
        )
        return

    #Quantity must be greater than zero
    if quantity <= 0:
        send_error(
            conn,
            ERR_INVALID_QUANTITY,
            "Quantity must be greater than zero"
        )
        return

    #Add the new item to the in-memory inventory dictionary.
    inventory[item_code]={
        "item_name": item_name,
        "category": category,
        "quantity": quantity,
        "unit": unit,
        "location": location
    }

    #Build a success response containing the new item code.
    response = encode_string(item_code)


    #Send the successful ADD_ITEM response
    #ADD_ITEM = 0x03 and RESPONSE_FLAG = 0x80
    #so the response type becomes 0x83
    send_packet(conn, ADD_ITEM | RESPONSEFLAG, response)

#============================================================
# Function 4 - List Items By Category 
#============================================================
def handle_list_category(conn, payload):
    """
    Expected request payload:
        category: encoded string
        
    Successful response payload:
        item_count: 2-byte unsign integer
        
        Followed by each matching item:
            item_code: encoded string
            item_name: encoded string
            quantity: 4-byte unsigned integer
            unit : encoded string
            location: encoded string
            """
    try:
        #decode the category requested by the client
        category, offset = decode_string(payload)

        #There should be no additional bytes after the category.
        #Extra bytes would indicate a malformed request.
        if offset != len(payload):
            raise ValueError(
                "Unexpected data in category request"
            )

    except (ValueError, UnicodeDecodeError):
        # The payload could not be decoded correctly
        send_error(
            conn,
            ERR_INVALID_REQUEST,
            "Invalid category request"
        )
        return

    #Remove unnessary spaces and convert to lowercase
    #Categories are stored in lowercase in the inventory.
    category = category.strip().lower()

    #Reject an empty category.
    if not category:
        send_error(
            conn,
            ERR_INVALID_REQUEST,
            "Category cannot be empty"
        )
        return

    #Find every item whose category matches the requested category.
    matching_items = []

    for item_code, item in inventory.items():
        if item["category"].lower() == category:
            matching_items.append(
                (item_code, item)
            )

    # if no matching items were found, return an error response
    if not matching_items:
        send_error(
            conn,
            ERR_CATEGORY_NOT_FOUND,
            "No items found in this category"
        )
        return

    #Start the response with the number of matching items.
    #
    # H = unsigned 16-bit integer, alowing up to 65,535 records.
    response = struct.pack(
        "!H",
        len(matching_items)
    )

    #Encode each matching inventory record into the response.
    for item_code, item in matching_items:
        response += (
            encode_string(item_code)
            + encode_string(item["item_name"])
            + struct.pack("!I", item["quantity"])
            + encode_string(item["unit"])
            + encode_string(item["location"])
        )

    #Send successful LIST_CATEGORY response.
    #LIST_CATEGORY = 0x04
    #RESPONSE_FLAG = 0x80
    #Therefore response type = 0x84
    send_packet(
        conn,
        LIST_CATEGORY | RESPONSEFLAG,
        response
    )

# ============================================================
# Client handling function
# ============================================================
def handle_client(conn, addr):
    print(f"Connection from {addr}")

    with conn:
        while True:
            try:
                message_type, payload = receive_packet(conn)

            except ConnectionError:
                print(f"Connection closed by {addr}")
                break

            except ValueError as e:
                print(f"Protocol error: {e}")
                send_error(conn, ERR_INVALID_REQUEST, str(e))
                continue
        # ============================================================
        # LOOKUP
        # ============================================================

            if message_type == LOOKUP:
                handle_lookup(conn, payload)


        # ============================================================
        # RESERVE
        # ============================================================

            elif message_type == RESERVE:
                handle_reserve(conn, payload)

        # ============================================================
        # ADD AN ITEM
        # ============================================================
        
            elif message_type == ADD_ITEM:
                handle_add_item(conn, payload)

        # ============================================================
        # ADD AN ITEM
        # ============================================================

            elif message_type == LIST_CATEGORY  :
                handle_list_category(conn, payload)

        # ============================================================      
        # Unknown operation
        # ============================================================

            else:
                print("Unknown operation:", message_type)
                send_error(conn, ERR_UNKNOWN_OPERATION, "Unknown operation.")

# ============================================================
# Main server loop
# ============================================================
def main():

    parser = argparse.ArgumentParser(
        description= "Engineering Lab Invotentory Server"
    )

    parser.add_argument(
        "--port",
        type=int,
        required=True,
        help="TCP port for the server"
    )

    args = parser.parse_args()

    # validate port number
    if args.port < 1 or args.port > 65535:
        print("Error: Port number must be between 1 and 65535.")
        return

    # Create a TCP socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:

        #makes restrating the server easier during development
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        #Bind the socket to the specified port on all interfaces
        server_socket.bind(('', args.port)) 

        #Listen for incoming connections
        server_socket.listen()
        print(f"Server listening on port {args.port}")
        
        # Server continues accepting clients
        while True:
            conn, addr = server_socket.accept()
            handle_client(conn, addr)

if __name__ == "__main__":
    main()