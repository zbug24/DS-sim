import socket

HOST = "127.0.0.1"
PORT = 59476  # Default ds-server port; change to your unique port on uni servers

buf = ""

def send(sock, msg):
    """Send a newline-terminated message to ds-server."""
    sock.sendall((msg + "\n").encode())

def rline(sock):
    """Read one complete newline-terminated line from ds-server."""
    global buf
    while "\n" not in buf:
        buf += sock.recv(4096).decode()
    line, buf = buf.split("\n", 1)
    return line.strip()

def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))

    # --- Handshake ---
    send(sock, "HELO")
    rline(sock)                  # Receive: OK

    send(sock, "AUTH Ben & Sushi")
    rline(sock)                  # Receive: OK

    # --- Main scheduling loop ---
    while True:
        send(sock, "REDY")
        msg = rline(sock)
        parts = msg.split()

        if parts[0] == "NONE":
            # No more jobs — end simulation
            break

        elif parts[0] == "JCPL":
            # Job completed notification — loop back and send REDY again
            # BUG FIX: was 'continue', which skipped back to send(REDY) correctly
            # but the issue is REDY is at the TOP of the loop, so continue is fine here.
            # However, keeping it explicit with 'continue' is clearer.
            continue

        elif parts[0] in ("JOBN", "JOBP"):
            # JOBN format: JOBN submitTime jobID estRunTime cores memory disk
            #              parts[0]  [1]      [2]    [3]       [4]   [5]    [6]
            # BUG FIX: was parts[1] for job_id — that's submitTime, not jobID
            job_id = int(parts[2])
            cores  = int(parts[4])
            mem    = int(parts[5])
            disk   = int(parts[6])

            # Ask server for all capable servers for this job's resource requirements
            send(sock, f"GETS Capable {cores} {mem} {disk}")
            data_msg = rline(sock)        # Receive: DATA nRecs recLen
            data_parts = data_msg.split()
            n = int(data_parts[1])        # Number of capable servers

            send(sock, "OK")
            servers = []
            for _ in range(n):
                servers.append(rline(sock).split())
            send(sock, "OK")
            rline(sock)                   # Receive: "."

            # Select first capable server (First-Fit style)
            # servers[i] = [type, id, state, startTime, cores, mem, disk]
            server_type = servers[0][0]
            server_id   = servers[0][1]

            send(sock, f"SCHD {job_id} {server_type} {server_id}")
            rline(sock)                   # Receive: OK

    # --- End simulation ---
    send(sock, "QUIT")
    rline(sock)                           # Receive: QUIT
    sock.close()

if __name__ == "__main__":
    main()