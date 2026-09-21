# SENG4500 Assignment 1 – TCP Inventory Service

## Overview

This project implements a TCP-based inventory service for a university engineering lab stockroom.

The system consists of:

- `server.py` – maintains the inventory and processes client requests.
- `client.py` – provides a command-line interface for interacting with the server.
- `test_client.py` – optional development/testing client used to test protocol behaviour.
- `README.md` – instructions for running and testing the project.

The client and server communicate using a custom binary application-layer protocol over TCP.

The server starts with the following inventory:

| Item Code | Item Name | Category | Quantity | Unit | Location |
|---|---|---:|---:|---|---|
| RPI-004 | Raspberry Pi 4 | controller | 12 | units | Cabinet A |
| SNS-011 | Ultrasonic Sensor | sensor | 40 | units | Cabinet C |
| CBL-USB | USB-C Cable | cable | 75 | units | Drawer 2 |

Inventory changes are stored only in memory. Restarting the server resets the inventory to the original dataset.

---

## Requirements

- Python 3
- No third-party Python libraries are required.
- The program uses only Python standard-library modules, including:
  - `socket`
  - `argparse`
  - `struct`
  - `zlib`

---

## Running the Server

Open a terminal in the project directory and run:

```bash
python server.py --port 4500
```

The server port is configurable. For example:

```bash
python server.py --port 5000
```

A valid TCP port must be between 1 and 65535.

Example output:

```text
Server listening on port 4500
```

The server continues running after a client disconnects and waits for another client connection.

To stop the server manually, press:

```text
Ctrl + C
```

---

## Running the Client

Open a second terminal in the project directory and run:

```bash
python client.py --host 127.0.0.1 --port 4500
```

The hostname and TCP port are configurable through command-line arguments.

The client displays the following menu:

```text
==============================
 Engineering Lab Inventory
==============================
1. Look up an item
2. Reserve an item
3. Add a new item
4. List items by category
5. Exit
==============================
```

The client keeps the TCP connection open while the user performs multiple operations.

---

## Supported Functions

### 1. Look Up an Item

The client asks for an item code and sends a lookup request to the server.

Example:

```text
Enter item code: RPI-004
```

Example response:

```text
Item found
-------------------------
Code:     RPI-004
Name:     Raspberry Pi 4
Category: controller
Quantity: 12 units
Location: Cabinet A
```

If the item does not exist, the server returns an error response.

---

### 2. Reserve an Item

The client asks for an item code and quantity.

The server validates that:

- the item exists;
- the requested quantity is valid;
- enough stock is available.

If successful, the server reduces the available quantity in memory.

Example:

```text
Enter item code: RPI-004
Enter quantity to reserve: 2
```

Example response:

```text
Reservation successful
-------------------------
Item: RPI-004
Remaining quantity: 10
```

Invalid quantities and insufficient stock are returned as protocol error responses.

---

### 3. Add a New Item

The client asks for:

- item code;
- item name;
- category;
- quantity;
- unit;
- location.

Example:

```text
Item code: CAM-002
Item name: USB Microscope Camera
Category: camera
Quantity: 5
Unit: units
Location: Cabinet D
```

The server:

- rejects duplicate item codes;
- validates quantity;
- validates required fields;
- stores the new item in memory.

Added items are lost when the server restarts.

---

### 4. List Items by Category

The client asks for a category and the server returns all matching inventory records.

Example:

```text
Enter category: sensor
```

The protocol supports multiple records in one response.

If no matching items exist, the server returns an appropriate error response.

---

## Application-Layer Protocol

TCP is a byte-stream protocol and does not preserve application message boundaries.

To handle this, each request and response uses the following packet structure:

```text
+-------------+--------------+------------------+-------------+
| Body Length | Message Type | Payload          | CRC32       |
| 4 bytes     | 1 byte       | Variable length  | 4 bytes     |
+-------------+--------------+------------------+-------------+
```

### Body Length

The first 4 bytes contain the number of bytes in the remaining message body.

The body consists of:

```text
Message Type + Payload + CRC32
```

The receiver first reads the 4-byte length field and then uses a helper function to receive exactly the required number of bytes.

---

## Message Types

| Operation | Request Code | Successful Response |
|---|---:|---:|
| Look Up Item | `0x01` | `0x81` |
| Reserve Item | `0x02` | `0x82` |
| Add Item | `0x03` | `0x83` |
| List Category | `0x04` | `0x84` |
| Error | — | `0xFF` |

Successful responses set the `0x80` response flag.

For example:

```text
LOOKUP request  = 0x01
Response flag   = 0x80
LOOKUP response = 0x81
```

---

## String Encoding

Strings are encoded as:

```text
+---------------+-------------------+
| String Length | UTF-8 Data        |
| 2 bytes       | Variable length   |
+---------------+-------------------+
```

This allows multiple variable-length strings to be transmitted without relying on delimiter characters.

For example, `RPI-004` is encoded as a 2-byte length value followed by 7 UTF-8 bytes.

---

## Integer Encoding

Quantities are encoded as unsigned 32-bit integers in network byte order.

Python's `struct` module is used:

```python
struct.pack("!I", quantity)
```

`!` specifies network byte order (big-endian), while `I` represents an unsigned 32-bit integer.

---

## TCP Message Framing

A normal `recv()` call is not guaranteed to return a complete application message.

The project therefore uses a helper function that repeatedly calls `recv()` until exactly the requested number of bytes has been received.

This ensures that packet parsing remains correct even when TCP divides a message across multiple reads.

---

## Error Detection

The protocol includes a CRC32 checksum in every packet.

The sender calculates CRC32 over:

```text
Message Type + Payload
```

The receiver recalculates the checksum after receiving the packet.

If the received checksum and calculated checksum do not match, the packet is rejected.

This provides application-layer error detection in addition to TCP's transport-layer protection.

---

## Error Responses

Errors use message type:

```text
0xFF
```

The error payload contains:

```text
1-byte error code + encoded error message
```

Examples of handled errors include:

- invalid request;
- item not found;
- invalid quantity;
- insufficient stock;
- duplicate item code;
- category not found;
- unknown operation;
- checksum/protocol errors.

---

## Example Test Cases

### Lookup

```text
RPI-004
```

Expected: Raspberry Pi 4 details are returned.

```text
ABC-999
```

Expected: item-not-found error.

---

### Reserve

```text
RPI-004, quantity 2
```

Expected: success and 10 units remaining.

```text
RPI-004, quantity 999
```

Expected: insufficient-stock error.

```text
RPI-004, quantity 0
```

Expected: invalid-quantity error.

---

### Add Item

Add:

```text
CAM-002
USB Microscope Camera
camera
5
units
Cabinet D
```

Expected: item added successfully.

Add the same item code again.

Expected: duplicate-item error.

---

### List Category

```text
sensor
```

Expected: all sensor records are returned.

```text
computer
```

Expected: category-not-found error if no matching records exist.

---

## Compiling / Syntax Checking

Python source can be compiled to bytecode and checked for syntax errors using:

```bash
python -m py_compile server.py
python -m py_compile client.py
```

Successful compilation normally produces no console output.

---

## Wireshark

When the client and server both run on `127.0.0.1`, capture the loopback interface in Wireshark.

A useful display filter is:

```text
tcp.port == 4500
```

Using **Follow TCP Stream** and selecting **Hex Dump** shows the binary application protocol, including:

- length prefix;
- message type;
- payload data;
- CRC32 checksum.

---

## Notes

- The server inventory is not persisted to disk.
- Restarting the server restores the original inventory.
- The client does not access the inventory directly.
- Inventory validation is performed by the server.
- Client-side validation is also used to improve user experience.
- The server remains running after a client disconnects and can accept another connection.

---

## Submission Files

Recommended submission contents:

```text
server.py
client.py
README.md
SENG4500_Assignment1_ManhLe_Presentation.mp4
```

`test_client.py` may also be included if development/testing files are permitted by the submission requirements.
