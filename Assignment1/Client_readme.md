# SENG4500 Assignment 1 – Client
Run the Client

Make sure the server is already running.

Open a terminal in the client folder and run:

python client.py --host 127.0.0.1 --port 4500

Command-line arguments:

--host – hostname or IP address of the server

--port – TCP port used by the server

The client and server must use the same TCP port.

For example, if the server is started with:

python server.py --port 5000

the client should connect with:

python client.py --host 127.0.0.1 --port 5000

Client Menu

After connecting, the client displays:

1. Look up an item
2. Reserve an item
3. Add a new item
4. List items by category
5. Exit

Select an option and follow the prompts.